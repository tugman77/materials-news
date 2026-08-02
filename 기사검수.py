"""
소재경제신문 기사 검수 시스템
실행: python 기사검수.py
기능:
  1. articles.json 로드 → 오늘 발행 여부 확인
  2. 누락 이미지 자동 다운로드
  3. Claude로 사실성 + 이미지 키워드 적절성 검토
  4. Naver 뉴스 교차 검증 (NAVER_CLIENT_ID 설정 시 활성화)
  5. 이미지 키워드 문제 시 수정 + 재다운로드
  6. 검수 결과 articles.json에 저장
  7. 텔레그램으로 검수 보고
"""

from __future__ import annotations  # 로컬 Python 3.9에서 `str | None` 등 어노테이션 허용 (지연 평가)

import anthropic
import llm_backend  # 구독코인(로컬 Claude Code) / API코인(anthropic SDK) 전환
import 이미지필터    # 이미지 키워드 오매칭(예: wafer → 과자) 방지 필터
import 이미지소스    # 외부 이미지 소스 API (Unsplash/Pexels/Pixabay) — 기사자동생성.py와 공용
import 이미지풀      # 카테고리별 큐레이션 풀 (로컬 self-host + Unsplash hotlink) — 공용
import hashlib
import json
import os
import requests
from datetime import datetime, timezone, timedelta

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

IMAGES_DIR = "images"
OUTPUT_FILE = "articles.json"
IMAGE_HISTORY_FILE = "image_history.json"  # 기사자동생성.py와 공유하는 날짜 간 재사용 방지 기록
KST = timezone(timedelta(hours=9))

# ── 이미지 재사용 방지 상태 (기사자동생성.py와 동일 포맷) ──
_used_photo_ids: set   = set()   # 이번 검수에서 선택된 photo-ID
_downloaded_hashes: set = set()  # 과거 포함 저장된 이미지 MD5
_run_hashes: set       = set()   # 이번 검수에서만 저장된 MD5 (큐레이션 풀 전용 판정)
_photo_id_last_used: dict = {}   # photo-ID → 마지막 사용 날짜(YYYY-MM-DD)

# ⚠️ 큐레이션 풀은 영구 해시 대조에서 제외한다 (2026-08-02).
# 풀 URL은 고정이라 바이트가 매일 같아, 한 번 쓰면 영구 히스토리에 박혀 재사용이 막힌다.
# 실제로 풀 33장 중 29장이 죽어 picsum 폴백이 났고, 그 결과가 '삼성SDI OLED' 기사의 갈매기 사진이다.
# (재다운로드는 이 파일에서 일어났다 — 검수가 키워드를 바꾸고 다시 받는 경로.)


def _load_image_history():
    """image_history.json + images/ 폴더 해시를 적재해 과거 이미지 재사용을 막는다."""
    global _downloaded_hashes, _photo_id_last_used
    try:
        with open(IMAGE_HISTORY_FILE, "r", encoding="utf-8") as f:
            hist = json.load(f)
        _photo_id_last_used = dict(hist.get("photo_ids", {}))
        _downloaded_hashes = set(hist.get("hashes", []))
    except (FileNotFoundError, json.JSONDecodeError):
        _photo_id_last_used = {}
        _downloaded_hashes = set()
    if os.path.isdir(IMAGES_DIR):
        for fn in os.listdir(IMAGES_DIR):
            fp = os.path.join(IMAGES_DIR, fn)
            if os.path.isfile(fp):
                try:
                    with open(fp, "rb") as f:
                        _downloaded_hashes.add(hashlib.md5(f.read()).hexdigest())
                except Exception:
                    pass


def _save_image_history():
    """검수 중 갱신된 photo-ID 이력·해시를 image_history.json에 저장 (최근 800개)."""
    data = {"photo_ids": _photo_id_last_used, "hashes": list(_downloaded_hashes)[-800:]}
    try:
        with open(IMAGE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"   → 히스토리 저장 오류: {e}")


# ── 텔레그램 ────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[텔레그램 미설정] {message[:80]}")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"텔레그램 전송 오류: {e}")
        return False


# ── Naver 교차 검증 ─────────────────────────────────────────

def search_naver_news(query: str, display: int = 3) -> list:
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers, params=params, timeout=10
        )
        if resp.ok:
            return resp.json().get("items", [])
    except Exception as e:
        print(f"Naver 검색 오류 [{query}]: {e}")
    return []


# ── 이미지 다운로드 ──────────────────────────────────────────

# 풀 목록은 이미지풀.py 한 곳에서만 관리한다 (두 파일 복붙으로 어긋나던 것을 통합).

def _pick_pool_entry(category: str, seed_str: str):
    """풀에서 LRU로 한 항목 선택 → 항목 dict 반환 (없으면 None)"""
    entry = 이미지풀.pick(category, seed_str, _used_photo_ids, _photo_id_last_used)
    if entry:
        _used_photo_ids.add(entry["id"])
    return entry


def download_image(keyword: str, img_path: str, category: str = "", seed_str: str = "") -> str | None:
    """이미지 다운로드 → img_path에 저장. 기사자동생성.py와 동일한 소스 순서를 쓴다.
    1차: 외부 API — Unsplash → Pexels → Pixabay (키가 등록된 것만, 이미지소스.py가 판단)
    2차: 카테고리별 Unsplash 큐레이션 풀 (LRU 선택, 과거 사용분 최대한 회피)
    3차: picsum 최종 폴백 — 내용 무관 랜덤이므로 여기까지 오면 사실상 실패다
    저장 직전 MD5 대조: 외부 소스는 과거 날짜까지, 풀은 이번 실행만.
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)
    # 검색 전 1차 방어 — 중의적 키워드(wafer/chip/foil…)에 업계 한정어를 붙인다
    refined = 이미지필터.refine_keyword(keyword, category)
    if refined != keyword:
        print(f"   키워드 보정: '{keyword}' → '{refined}'")
        keyword = refined
    seed = hashlib.md5(keyword.encode()).hexdigest()[:8]

    # 외부 소스(Unsplash·Pexels·Pixabay)를 기사자동생성.py와 동일하게 먼저 시도한다.
    # 2026-08-02까지 이 파일에는 Pexels·Pixabay가 없어 풀→picsum밖에 없었고,
    # 풀이 고갈되자 검수 재다운로드가 곧바로 내용 무관 랜덤 이미지로 떨어졌다.
    order = list(이미지소스.available_sources())
    # 중복 거부 시 다른 항목으로 재시도 — 풀 크기만큼
    order += ["unsplash_pool"] * max(이미지풀.size(category or "반도체소재"), 8)
    order.append("picsum")

    pool_try = 0
    for source in order:
        chosen_pid = None
        try:
            if source in 이미지소스.FETCHERS:
                img_url = 이미지소스.fetch(source, keyword)
                if not img_url:
                    continue
            elif source == "unsplash_pool":
                entry = _pick_pool_entry(
                    category or "반도체소재", f"{seed_str or keyword}_{pool_try}")
                pool_try += 1
                if not entry:
                    continue
                chosen_pid = entry["id"]
                content = 이미지풀.read_bytes(entry)   # 로컬은 파일 읽기, 원격은 HTTP
                if not content:
                    continue
                img_url = entry["ref"]
            else:
                img_url = f"https://picsum.photos/seed/{seed}/800/450"

            is_pool = (source == "unsplash_pool")
            if not is_pool:
                resp = requests.get(img_url, timeout=30, allow_redirects=True)
                if resp.status_code != 200 or len(resp.content) < 1000:
                    continue
                content = resp.content

            # 외부 소스는 과거 날짜까지, 큐레이션 풀은 이번 실행만 대조 — 위 주석 참조
            img_hash = hashlib.md5(content).hexdigest()
            if img_hash in (_run_hashes if is_pool else _downloaded_hashes):
                scope = "오늘 이미 사용" if is_pool else "과거 사용"
                print(f"   중복 이미지 [{source}] md5={img_hash[:8]} ({scope}), 다음 후보 시도...")
                continue

            _run_hashes.add(img_hash)
            if not is_pool:
                # 풀 해시를 영구 히스토리에 넣으면 그 photo-ID가 영영 죽는다
                _downloaded_hashes.add(img_hash)
            if chosen_pid:
                _photo_id_last_used[chosen_pid] = datetime.now(KST).strftime("%Y-%m-%d")
            with open(img_path, "wb") as f:
                f.write(content)
            print(f"   이미지 저장: {img_path} [{category or keyword}] ({source})")
            return img_path
        except Exception as e:
            print(f"   이미지 오류 ({source}): {e}")
    return None


def detect_duplicate_images(articles: list) -> list:
    """이미지 파일 MD5 해시로 중복 감지 → 중복 기사 인덱스 목록 반환"""
    seen_hashes: dict = {}
    duplicates = []
    for i, article in enumerate(articles):
        img_path = article.get("image_url", "")
        if not img_path or not os.path.exists(img_path):
            continue
        try:
            with open(img_path, "rb") as f:
                h = hashlib.md5(f.read()).hexdigest()
            if h in seen_hashes:
                print(f"   ⚠️ 이미지 중복 감지: 기사[{i}] = 기사[{seen_hashes[h]}] (hash={h[:8]})")
                duplicates.append(i)
            else:
                seen_hashes[h] = i
        except Exception:
            pass
    return duplicates


def check_and_fix_missing_images(articles: list, date_prefix: str) -> int:
    """이미지 파일 누락·중복 기사 탐지 후 재다운로드, 조치 건수 반환"""
    fixed = 0

    # 1) 누락 이미지 보충
    for i, article in enumerate(articles):
        expected = f"{IMAGES_DIR}/{date_prefix}_article_{i}.jpg"
        current = article.get("image_url") or ""  # image_url이 None으로 존재할 수 있어 or ""로 방어
        if not current or not os.path.exists(current) or os.path.getsize(current) < 1000:
            keyword = article.get("image_keyword", "semiconductor technology materials")
            category = article.get("category", "반도체소재")
            seed_str = f"{date_prefix}_{i}_{article.get('title','')}"
            print(f"   이미지 누락 [{i}] '{category}' → 다운로드 시도")
            path = download_image(keyword, expected, category, seed_str)
            if path:
                article["image_url"] = path
                fixed += 1
            else:
                article["image_url"] = None

    # 2) 중복 이미지 재다운로드
    duplicates = detect_duplicate_images(articles)
    for i in duplicates:
        article = articles[i]
        keyword = article.get("image_keyword", "semiconductor technology materials")
        category = article.get("category", "반도체소재")
        seed_str = f"{date_prefix}_{i}_retry_{article.get('title','')}"
        img_path = f"{IMAGES_DIR}/{date_prefix}_article_{i}_retry.jpg"
        print(f"   중복 이미지 재다운로드 [{i}] '{category}'")
        path = download_image(keyword, img_path, category, seed_str)
        if path:
            article["image_url"] = path
            fixed += 1

    return fixed


# ── 제목 중복 감지 ──────────────────────────────────────────

def _title_bigrams(title: str) -> set:
    """제목을 문자 2-gram 집합으로 변환 (유사도 비교용).
    단어 단위 비교는 조사(도시광산→도시광산서)·붙여쓰기(자원 순환→자원순환)에
    깨지므로 문자 단위 2-gram을 사용한다."""
    import re as _re
    s = "".join(_re.findall(r"[0-9A-Za-z가-힣]+", title))
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _title_similarity(t1: str, t2: str) -> float:
    """문자 2-gram 자카드 유사도 (0~1).
    실측 기준: 동일 사건 재보도 0.25~0.46, 무관한 기사 0.00~0.09 → 임계값 0.20"""
    a, b = _title_bigrams(t1), _title_bigrams(t2)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def detect_duplicate_titles(articles: list, days: int = 14) -> dict:
    """당일 기사 내 제목 중복 + 최근 N일 아카이브와의 제목 '유사' 중복 감지.
    완전 일치뿐 아니라 문자 2-gram 자카드 유사도 0.20 이상이면 동일 사건 재보도로 판단.
    [속보]/[후속] 표기가 있는 기사는 의도된 후속 보도로 보고 제외."""
    issues: dict = {"within_today": [], "cross_days": []}

    # 당일 기사 내 중복
    seen: dict = {}
    for a in articles:
        title = a.get("title", "")
        if title in seen:
            issues["within_today"].append({
                "title": title,
                "ids": [seen[title], a["id"]],
            })
            print(f"   ⚠️ 당일 제목 중복: id={seen[title]} & id={a['id']} — '{title}'")
        else:
            seen[title] = a["id"]

    # 최근 N일 아카이브와 비교 (유사도 기반)
    SIM_THRESHOLD = 0.20
    today_list = [(a["title"], a["id"]) for a in articles]
    now = datetime.now(KST)
    flagged = set()  # (today_id) — 기사당 1회만 보고
    for d in range(1, days + 1):
        date_key = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        try:
            with open(f"archive/{date_key}.json", "r", encoding="utf-8") as f:
                arch_data = json.load(f)
            for arch_a in arch_data.get("articles", []):
                arch_title = arch_a.get("title", "")
                for today_title, today_id in today_list:
                    if today_id in flagged:
                        continue
                    if today_title.startswith(("[속보]", "[후속]")):
                        continue  # 의도된 후속 보도는 허용
                    sim = _title_similarity(today_title, arch_title)
                    if today_title == arch_title or sim >= SIM_THRESHOLD:
                        flagged.add(today_id)
                        issues["cross_days"].append({
                            "title": today_title,
                            "similar_to": arch_title,
                            "similarity": round(sim, 2),
                            "today_id": today_id,
                            "past_date": date_key,
                        })
                        print(f"   ⚠️ 유사 주제 재보도 의심: 오늘 id={today_id} '{today_title}'")
                        print(f"      ↔ {date_key} '{arch_title}' (유사도 {sim:.2f})")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    return issues


# ── Claude 검수 ─────────────────────────────────────────────

def review_articles_with_claude(articles: list) -> list:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 검수용 요약본 작성 (전체 body 대신 앞 3단락만 사용해 토큰 절약)
    summaries = []
    for a in articles:
        body = a.get("body", [])
        preview = "\n".join(body[:3]) if isinstance(body, list) else str(body)[:400]
        summaries.append({
            "id": a["id"],
            "category": a["category"],
            "title": a["title"],
            "summary": a.get("summary", ""),
            "body_preview": preview,
            "image_keyword": a.get("image_keyword", ""),
        })

    prompt = f"""소재경제신문에 오늘 발행된 기사 {len(summaries)}개를 검수해 주세요.

[검수 대상 기사]
{json.dumps(summaries, ensure_ascii=False, indent=2)}

[검수 기준]

1. 사실성 평가 (trust_score 1~5):
   - 언급된 기업명이 실제 존재하고 해당 업종에 종사하는지
   - 수치(가격·점유율·성장률·투자액)가 업계 현실과 크게 벗어나지 않는지
   - 법률·정책명이 실제 존재하는지 (예: CHIPS Act, 도드-프랭크법, 국민성장펀드 등)
   - 인용 발언이 지나치게 구체적이거나 출처 없이 창작된 것처럼 보이는지
   - 사건·사고(광산 붕괴, 수입금지 조치 등)가 업계 관점에서 개연성이 있는지
   5=거의 모든 내용 검증 가능, 4=대부분 사실로 판단, 3=일부 주의 필요,
   2=의심스러운 주장 다수, 1=명백한 오류 또는 허위 가능성 높음

2. 이미지 키워드 평가 (image_keyword_ok):
   - 기사 주제와 직접 관련 있는 영문 키워드인지
   - loremflickr 스톡 이미지 검색에 효과적인지
     (너무 추상적: "industry" → 적절: "semiconductor wafer manufacturing")
   - 부적절하면 suggested_image_keyword에 영문 2~3단어 제안

review_articles 도구로 전체 검수 결과를 반환하세요."""

    request_params = dict(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        tools=[{
            "name": "review_articles",
            "description": "기사 검수 결과를 저장합니다",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reviews": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "article_id": {"type": "integer"},
                                "trust_score": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 5,
                                    "description": "신뢰도 점수"
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pass", "warning", "fail"],
                                    "description": "pass=문제없음, warning=주의 필요, fail=심각한 오류"
                                },
                                "suspicious_claims": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "검증 필요한 의심스러운 주장 (최대 3개, 각 50자 이내)"
                                },
                                "image_keyword_ok": {"type": "boolean"},
                                "suggested_image_keyword": {
                                    "type": "string",
                                    "description": "image_keyword_ok=false일 때 대체 영문 키워드"
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "전반적 검수 코멘트 (60자 이내)"
                                }
                            },
                            "required": [
                                "article_id", "trust_score", "status",
                                "suspicious_claims", "image_keyword_ok", "notes"
                            ]
                        },
                        "minItems": len(summaries),
                        "maxItems": len(summaries)
                    }
                },
                "required": ["reviews"]
            }
        }],
        tool_choice={"type": "tool", "name": "review_articles"},
        messages=[{"role": "user", "content": prompt}]
    )

    # ── LLM 호출: 구독코인(Claude Code) vs API코인(anthropic SDK) ──
    if llm_backend.using_subscription():
        return llm_backend.call_tool(request_params, "review_articles")["reviews"]

    response = client.messages.create(**request_params)
    tool_block = next(b for b in response.content if b.type == "tool_use")
    return tool_block.input["reviews"]


# ── 텔레그램 보고 ────────────────────────────────────────────

def send_review_report(articles: list, reviews: list, naver_map: dict,
                       image_fixes: list, missing_fixed: int, date_str: str,
                       dup_issues: dict | None = None):
    STATUS_EMOJI = {"pass": "✅", "warning": "⚠️", "fail": "❌"}
    lines = [f"📋 <b>소재경제신문 검수 보고</b>\n{date_str}\n"]

    # 제목 중복 경고 섹션
    has_issues = False
    if dup_issues:
        for dup in dup_issues.get("within_today", []):
            lines.append(f"🚨 <b>당일 제목 중복</b>: id={dup['ids'][0]}, {dup['ids'][1]}")
            lines.append(f"   \"{dup['title'][:30]}...\"")
            has_issues = True
        for dup in dup_issues.get("cross_days", []):
            sim_info = f" (유사도 {dup['similarity']})" if "similarity" in dup else ""
            lines.append(f"⚠️ <b>유사 주제 재보도 의심</b>: 오늘 id={dup['today_id']} ↔ {dup['past_date']}{sim_info}")
            lines.append(f"   오늘: \"{dup['title'][:30]}\"")
            if dup.get("similar_to"):
                lines.append(f"   과거: \"{dup['similar_to'][:30]}\"")
            has_issues = True
        if has_issues:
            lines.append("")  # 빈 줄 구분
    for review in reviews:
        article = next((a for a in articles if a["id"] == review["article_id"]), {})
        emoji = STATUS_EMOJI.get(review["status"], "✅")
        title = article.get("title", "")[:18]
        score = review["trust_score"]

        lines.append(f"{emoji} [{review['article_id']}] {title}... (신뢰도 {score}/5)")

        for claim in review.get("suspicious_claims", [])[:2]:
            lines.append(f"   ⚠️ {claim[:48]}")
            has_issues = True

        if not review.get("image_keyword_ok", True):
            new_kw = review.get("suggested_image_keyword", "")
            lines.append(f"   🖼️ 이미지 키워드 수정 → {new_kw}")
            has_issues = True

        if naver_map and review["article_id"] in naver_map:
            found = naver_map[review["article_id"]]
            lines.append(f"   📰 Naver: {'관련 뉴스 확인' if found else '관련 뉴스 없음'}")

    summary_parts = []
    if missing_fixed:
        summary_parts.append(f"이미지 {missing_fixed}건 다운로드")
    if image_fixes:
        summary_parts.append(f"키워드 {len(image_fixes)}건 수정")
    if summary_parts:
        lines.append(f"\n🔧 자동 조치: {', '.join(summary_parts)}")

    if not has_issues:
        lines.append("\n✨ 모든 기사 검수 통과")

    ok = send_telegram("\n".join(lines))
    print("텔레그램 검수 보고 전송 완료" if ok else "⚠️ 텔레그램 검수 보고 전송 실패")


# ── 메인 ─────────────────────────────────────────────────────

def main():
    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d %H:%M")
    date_prefix = now.strftime("%Y-%m-%d")
    today_str = now.strftime("%Y년 %m월 %d일")
    print(f"[{date_str}] 기사 검수 시작...")

    # 1. articles.json 로드
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        msg = f"❌ 소재경제신문 검수 실패\narticles.json 로드 오류: {e}"
        print(msg)
        send_telegram(msg)
        return

    articles = data.get("articles", [])
    if not articles:
        print("검수할 기사 없음 — 종료")
        return

    # 오늘 발행된 기사인지 확인
    generated_at = data.get("generated_at", "")
    if today_str not in generated_at:
        print(f"오늘({today_str}) 기사가 아님 ({generated_at}) — 검수 건너뜀")
        return

    print(f"   {len(articles)}건 기사 로드 (생성: {generated_at})")

    # 2. 제목 중복 감지 (당일 내 + 최근 3일)
    print("제목 중복 감지 중...")
    dup_issues = detect_duplicate_titles(articles, days=14)
    total_dups = len(dup_issues["within_today"]) + len(dup_issues["cross_days"])
    if total_dups:
        print(f"   ⚠️ 제목 중복 {total_dups}건 감지")
    else:
        print("   제목 중복 없음")

    # 3. 누락·중복 이미지 확인 + 다운로드
    print("이미지 파일 확인 중 (누락 + 중복 감지)...")
    _load_image_history()  # 과거 해시·photo-ID 이력 적재 → 재다운로드 시 재사용 방지
    missing_fixed = check_and_fix_missing_images(articles, date_prefix)
    if missing_fixed:
        print(f"   이미지 {missing_fixed}건 조치 완료")
    else:
        print("   이미지 모두 정상")

    # 3. Claude 검수
    print("Claude 기사 검수 중...")
    reviews = review_articles_with_claude(articles)
    print(f"   {len(reviews)}건 검수 완료")

    # 4. Naver 교차 검증 (선택)
    naver_map = {}
    if NAVER_CLIENT_ID:
        print("Naver 뉴스 교차 검증 중...")
        for article in articles:
            results = search_naver_news(article["title"][:15])
            naver_map[article["id"]] = len(results) > 0
            found = naver_map[article["id"]]
            print(f"   [{article['id']}] {'확인됨' if found else '없음'}: {article['title'][:20]}")

    # 5. 이미지 키워드 수정 + 재다운로드
    image_fixes = []
    for review in reviews:
        if not review.get("image_keyword_ok", True) and review.get("suggested_image_keyword"):
            idx = review["article_id"] - 1
            article = articles[idx]
            old_kw = article.get("image_keyword", "")
            new_kw = review["suggested_image_keyword"]

            print(f"   이미지 키워드 수정 [{article['id']}]: '{old_kw}' → '{new_kw}'")
            article["image_keyword"] = new_kw

            img_path = f"{IMAGES_DIR}/{date_prefix}_article_{idx}.jpg"
            seed_str = f"{date_prefix}_{idx}_kw_{new_kw}"
            path = download_image(new_kw, img_path, article.get("category","반도체소재"), seed_str)
            if path:
                article["image_url"] = path

            image_fixes.append({
                "id": article["id"],
                "old": old_kw,
                "new": new_kw,
            })

    # 6. 검수 결과 articles.json에 저장
    review_map = {r["article_id"]: r for r in reviews}
    for article in articles:
        r = review_map.get(article["id"], {})
        article["review"] = {
            "trust_score": r.get("trust_score", 3),
            "status": r.get("status", "pass"),
            "suspicious_claims": r.get("suspicious_claims", []),
            "notes": r.get("notes", ""),
            "verified_at": date_str,
        }

    data["articles"] = articles
    data["last_reviewed_at"] = date_str

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("검수 결과 articles.json 저장 완료")

    _save_image_history()  # 검수 중 재다운로드로 갱신된 이미지 이력 영구 저장

    # 7. 텔레그램 보고
    send_review_report(articles, reviews, naver_map, image_fixes, missing_fixed, date_str, dup_issues)

    print("검수 완료!")


if __name__ == "__main__":
    main()
