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

import anthropic
import hashlib
import json
import os
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

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
_photo_id_last_used: dict = {}   # photo-ID → 마지막 사용 날짜(YYYY-MM-DD)


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

# 카테고리별 Unsplash 큐레이션 풀
# 규칙: 동일 photo-ID가 두 카테고리에 나타나면 안 됨 (cross-category 중복 금지)
_UNSPLASH_POOL = {
    "반도체소재": [
        "photo-1518770660439-4636190af475",  # PCB 회로기판 클로즈업 (초록)
        "photo-1591799265444-d66432b91588",  # AMD Ryzen CPU 칩
        "photo-1562408590-e32931084e23",     # PCB 회로기판 (파랑/보라)
        "photo-1597852074816-d933c7d2b988",  # 전자 부품 HDD 내부
        "photo-1581092918056-0c4c3acd3789",  # 전자기기 납땜 작업
        "photo-1451187580459-43490279c0fa",  # 서버 데이터센터 랙
        "photo-1526374965328-7f61d4dc18c5",  # 코드 스크린 (매트릭스)
        "photo-1555680202-c86f0e12f086",     # 컴퓨터 마더보드 내부
        "photo-1558494949-ef010cbdcc31",     # 광섬유 케이블 (파랑/컬러)
    ],
    "희귀금속": [
        "photo-1504917595217-d4dc5ebe6122",  # 금속 용접 불꽃
        "photo-1504328345606-18bbc8c9d7d1",  # 용접사 클로즈업
        "photo-1527515637462-cff94eecc1ac",  # 채석장·광산 암반
        "photo-1531538606174-0f90ff5dce83",  # 광물·금 원석
        "photo-1565793298595-6a879b1d9492",  # 광산 덤프트럭
        "photo-1574482620826-40685ca5ebd2",  # 산업 금속 생산 라인
        "photo-1581094244429-b9b51e78f1d7",  # 건설 현장 항공뷰
        "photo-1578375819537-b95e00c82429",  # 금속 제련 용광로
    ],
    "산업재": [
        "photo-1567789884554-0b844b597180",  # 자동차 공장 로봇
        "photo-1473341304170-971dccb5ac1e",  # 고압 송전탑
        "photo-1541888946425-d81bb19240f5",  # 건설 현장 엔지니어
        "photo-1495576775051-8af0d10f68d1",  # 제철·철강 생산
        "photo-1504711434969-e33886168f5c",  # 제철소 용융 쇳물
        "photo-1565791380713-1756b9a05343",  # 화학 플랜트 항공뷰
        "photo-1582139329536-e7284fece509",  # 건설 크레인 군집
        "photo-1581092160607-ee22621dd758",  # 엔지니어 기계 작업
    ],
    "글로벌": [
        "photo-1494412519320-aa613dfb7738",  # 컨테이너 항구 항공뷰
        "photo-1578575437130-527eed3abbec",  # 컨테이너선 접안 항구
        "photo-1586528116311-ad8dd3c8310d",  # 물류 창고 내부
        "photo-1521790361543-f645cf042ec4",  # 화물 항공기
        "photo-1488229297570-58520851e868",  # 화물선 드론 항공뷰
        "photo-1545193544-312489b2d26c",     # 물류 트럭 주차장
        "photo-1558618666-fcd25c85cd64",     # 글로벌 해운 항로
        "photo-1586769852044-692d6e3703f0",  # 세계 공급망 지도
    ],
}
_UNSPLASH_BASE = "https://images.unsplash.com/{id}?w=800&h=450&fit=crop&auto=format"

def _pick_pool_url(category: str, seed_str: str) -> tuple[str, str]:
    """풀에서 '가장 오래전에 사용(또는 미사용)'한 photo-ID를 LRU로 선택. (url, photo_id) 반환."""
    pool = _UNSPLASH_POOL.get(category) or _UNSPLASH_POOL["반도체소재"]
    available = [p for p in pool if p not in _used_photo_ids]
    if not available:
        available = pool
    oldest_key = min(_photo_id_last_used.get(p, "") for p in available)
    tied = [p for p in available if _photo_id_last_used.get(p, "") == oldest_key]
    idx = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % len(tied)
    chosen = tied[idx]
    _used_photo_ids.add(chosen)
    return _UNSPLASH_BASE.format(id=chosen), chosen


def download_image(keyword: str, img_path: str, category: str = "", seed_str: str = "") -> str | None:
    """이미지 다운로드 → img_path에 저장.
    1차: Unsplash API (UNSPLASH_ACCESS_KEY 있을 때)
    2차: 카테고리별 Unsplash 풀 (LRU 선택, 과거 사용분 최대한 회피)
    3차: picsum 최종 폴백
    저장 직전 MD5를 히스토리와 대조 — 과거(다른 날짜 포함) 이미지와 같으면 다음 후보로 넘어감.
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)
    keyword_q = quote(keyword)
    seed = hashlib.md5(keyword.encode()).hexdigest()[:8]

    order = []
    if UNSPLASH_ACCESS_KEY:
        order.append("unsplash_api")
    order += ["unsplash_pool"] * 8   # 중복 거부 시 다른 photo-ID로 재시도
    order.append("picsum")

    pool_try = 0
    for source in order:
        chosen_pid = None
        try:
            if source == "unsplash_api":
                r = requests.get(
                    f"https://api.unsplash.com/photos/random?query={keyword_q}&orientation=landscape"
                    f"&client_id={UNSPLASH_ACCESS_KEY}", timeout=20, allow_redirects=True)
                if r.status_code != 200:
                    continue
                img_url = r.json().get("urls", {}).get("regular", "")
                if not img_url:
                    continue
            elif source == "unsplash_pool":
                img_url, chosen_pid = _pick_pool_url(
                    category or "반도체소재", f"{seed_str or keyword}_{pool_try}")
                pool_try += 1
            else:
                img_url = f"https://picsum.photos/seed/{seed}/800/450"

            resp = requests.get(img_url, timeout=30, allow_redirects=True)
            if resp.status_code != 200 or len(resp.content) < 1000:
                continue

            img_hash = hashlib.md5(resp.content).hexdigest()
            if img_hash in _downloaded_hashes:
                print(f"   중복 이미지 [{source}] md5={img_hash[:8]}, 다음 후보 시도...")
                continue

            _downloaded_hashes.add(img_hash)
            if chosen_pid:
                _photo_id_last_used[chosen_pid] = datetime.now(KST).strftime("%Y-%m-%d")
            with open(img_path, "wb") as f:
                f.write(resp.content)
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
        current = article.get("image_url", "")
        if not os.path.exists(current) or os.path.getsize(current) < 1000:
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

def detect_duplicate_titles(articles: list, days: int = 3) -> dict:
    """당일 기사 내 제목 중복 + 최근 N일 아카이브와의 제목 중복 감지"""
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

    # 최근 N일 아카이브와 비교
    today_title_map = {a["title"]: a["id"] for a in articles}
    now = datetime.now(KST)
    for d in range(1, days + 1):
        date_key = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        try:
            with open(f"archive/{date_key}.json", "r", encoding="utf-8") as f:
                arch_data = json.load(f)
            for arch_a in arch_data.get("articles", []):
                arch_title = arch_a.get("title", "")
                if arch_title in today_title_map:
                    issues["cross_days"].append({
                        "title": arch_title,
                        "today_id": today_title_map[arch_title],
                        "past_date": date_key,
                    })
                    print(f"   ⚠️ 날짜 간 제목 중복: 오늘 id={today_title_map[arch_title]} = {date_key} — '{arch_title}'")
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

    response = client.messages.create(
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
            lines.append(f"⚠️ <b>날짜 간 제목 중복</b>: 오늘 id={dup['today_id']} ↔ {dup['past_date']}")
            lines.append(f"   \"{dup['title'][:30]}...\"")
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

    send_telegram("\n".join(lines))
    print("텔레그램 검수 보고 전송 완료")


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
    dup_issues = detect_duplicate_titles(articles, days=3)
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
