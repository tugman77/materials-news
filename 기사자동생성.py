"""
소재경제신문 - 자동 기사 생성 스크립트
실행: python 기사자동생성.py
필요: pip install anthropic requests feedparser
"""

import anthropic
import feedparser
import hashlib
import json
import os
import random
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ── 설정 ──────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "여기에_API키_입력")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
PEXELS_API_KEY     = os.environ.get("PEXELS_API_KEY", "")    # https://www.pexels.com/api/
PIXABAY_API_KEY    = os.environ.get("PIXABAY_API_KEY", "")   # https://pixabay.com/api/docs/
OUTPUT_FILE = "articles.json"
IMAGES_DIR  = "images"
IMAGE_HISTORY_FILE = "image_history.json"  # 날짜 간(run 간) 이미지 재사용 방지용 영구 기록

# 수집할 RSS 피드 (소재·산업·경제 분야)
RSS_FEEDS = [
    ("전자신문", "https://www.etnews.com/rss/section/"),
    ("한국경제", "https://feeds.hankyung.com/economic"),
    ("연합뉴스 산업", "https://www.yna.co.kr/rss/economy.xml"),
    ("Google뉴스-반도체", "https://news.google.com/rss/search?q=반도체+소재&hl=ko&gl=KR&ceid=KR:ko"),
    ("Google뉴스-희귀금속", "https://news.google.com/rss/search?q=희귀금속+탄탈륨&hl=ko&gl=KR&ceid=KR:ko"),
    ("Google뉴스-공급망", "https://news.google.com/rss/search?q=반도체+공급망+소재&hl=ko&gl=KR&ceid=KR:ko"),
]

KST = timezone(timedelta(hours=9))

# ── RSS 수집 ───────────────────────────────────────
def collect_news_from_rss(max_per_feed=5):
    """RSS 피드에서 최신 뉴스 제목·요약 수집"""
    collected = []
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))[:300]
                link = entry.get("link", "")
                collected.append({
                    "source": name,
                    "title": title,
                    "summary": summary,
                    "link": link
                })
        except Exception as e:
            print(f"RSS 오류 [{name}]: {e}")
    return collected

# ── 최근 N일치 아카이브에서 기사 주제 추출 ──────────
def load_recent_topics(days: int = 3) -> list:
    """최근 N일치 아카이브 파일에서 기사 제목·카테고리·핵심어 추출.
    오늘 기사 생성 시 유사 주제 반복을 막는 데 사용한다.
    """
    topics = []
    now = datetime.now(KST)
    for d in range(1, days + 1):
        date_key = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        path = f"archive/{date_key}.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for a in data.get("articles", []):
                topics.append({
                    "date": date_key,
                    "category": a.get("category", ""),
                    "title": a.get("title", ""),
                    "summary": (a.get("summary") or "")[:80],
                })
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    return topics


# ── Claude API로 기사 생성 ─────────────────────────
def generate_articles_with_claude(raw_news_list, recent_topics=None):
    """수집된 뉴스를 바탕으로 Claude가 독창적 기사 작성.
    recent_topics: 최근 N일치 기사 목록 — 이 주제들과 겹치지 않게 작성 지시.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 원본 뉴스 목록을 텍스트로 변환
    news_text = ""
    for i, item in enumerate(raw_news_list[:15], 1):  # 최대 15개 처리
        news_text += f"{i}. [{item['source']}] {item['title']}\n   {item['summary']}\n\n"

    if news_text:
        news_section = f"[수집된 원본 뉴스]\n{news_text}\n\n원문을 참고해서 핵심 내용을 바탕으로 새로운 문장으로 작성하세요."
    else:
        news_section = "[원본 뉴스 없음]\nRSS 수집에 실패했습니다. 최근 반도체·소재·희귀금속·산업재 업계 동향을 바탕으로 실제 있을 법한 기사를 작성하세요."

    # 최근 다룬 주제 → 중복 금지 섹션
    if recent_topics:
        days_set = sorted(set(t["date"] for t in recent_topics), reverse=True)
        topic_lines = "\n".join(
            f"  [{t['date']}] [{t['category']}] {t['title']}"
            for t in recent_topics
        )
        avoid_section = f"""[최근 {len(days_set)}일간 이미 다룬 주제 — 반드시 피할 것]
아래 기사들과 주제가 겹치면 안 됩니다.
중복 판단 기준:
  · 동일 기업명이 주인공인 기사 (예: OCI, 아지노모토, 아람코 등 재등장 금지)
  · 동일 소재/물질명 중심 기사 (예: 탄탈럼, CO2, HBM 등)
  · 동일 정책·규제 이슈 (예: 탄탈럼 수입금지, OPEC+ 감산 등)
  · 동일 이슈 흐름 (예: 석화업계 반도체 피벗, 국제유가 변동 등)
같은 소재를 다루더라도 "각도"가 완전히 다른 경우(예: 공급망 → 기술 개발)는 허용.

{topic_lines}

"""
    else:
        avoid_section = ""

    prompt = f"""반도체·소재·희귀금속·산업재 전문 뉴스 사이트용 기사 5개를 작성해주세요.

{avoid_section}{news_section}

[작성 규칙]
- 카테고리: "반도체소재" / "희귀금속" / "산업재" / "글로벌" 중 하나
- tag_type: "tag-semi" / "tag-rare" / "tag-industry" / "tag-global" 중 하나 (카테고리에 맞게)
- 제목: 15~25자, 핵심 팩트 중심
- summary: 2~3문장 핵심 요약 (150자 이내)
- body: 10~13개 단락 각각을 문자열로 담은 배열. 각 단락 200~300자. 반드시 포함할 내용: ①사건 배경 및 원인 분석 ②구체적 수치·통계(수출액·생산량·가격 변동 포함) ③주요 관련 기업명과 최신 동향 ④전문가·업계 관계자 의견(직접 인용 형식) ⑤국내 산업별 파급 효과 ⑥글로벌·해외 동향 ⑦관련 정책·규제 현황 ⑧향후 시장 전망 및 투자 시사점. 전문 용어는 쉽게 풀어서 작성
- image_keyword: 기사 내용과 관련된 영문 이미지 검색 키워드 2~3단어 (예: "semiconductor wafer", "rare earth mining", "supply chain factory")
- timestamp: 현재 시각 기준 오전/오후 HH:MM 형식

save_articles 도구를 사용해 기사 5개를 저장하세요.
- 첫 번째 기사만 is_featured: true, 나머지 4개는 false
- body는 각 단락을 별도 문자열로 된 배열 (10~13개 항목, 각 항목 200~300자)
- body 배열 예시: ["첫째 단락 본문...", "둘째 단락 본문...", ...]
"""

    # tool_use로 JSON 구조 보장 (스트리밍: 32000 토큰 비스트리밍 금지 우회)
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=32000,
        tools=[{
            "name": "save_articles",
            "description": "생성된 기사 5개를 저장합니다",
            "input_schema": {
                "type": "object",
                "properties": {
                    "articles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":            {"type": "integer"},
                                "category":      {"type": "string", "enum": ["반도체소재","희귀금속","산업재","글로벌"]},
                                "tag_type":      {"type": "string"},
                                "title":         {"type": "string"},
                                "summary":       {"type": "string"},
                                "body":          {"type": "array", "items": {"type": "string"}, "minItems": 10, "maxItems": 13},
                                "image_keyword": {"type": "string"},
                                "is_featured":   {"type": "boolean"},
                                "timestamp":     {"type": "string"}
                            },
                            "required": ["id","category","tag_type","title","summary","body","image_keyword","is_featured","timestamp"]
                        },
                        "minItems": 5,
                        "maxItems": 5
                    }
                },
                "required": ["articles"]
            }
        }],
        tool_choice={"type": "tool", "name": "save_articles"},
        messages=[{"role": "user", "content": prompt}]
    ) as stream:
        response = stream.get_final_message()

    # tool_use 블록에서 결과 추출
    tool_block = next(b for b in response.content if b.type == "tool_use")
    articles = tool_block.input["articles"]
    # 혹시 문자열로 반환된 경우 파싱 (double-serialization 방어)
    if isinstance(articles, str):
        print(f"⚠️  articles가 str 타입 (len={len(articles)}), json_repair 시도...")
        from json_repair import repair_json
        articles = json.loads(repair_json(articles))
    # body가 문자열이면 줄바꿈으로 분리해 배열로 변환
    for a in articles:
        if isinstance(a.get("body"), str):
            a["body"] = [p.strip() for p in a["body"].split("\n") if p.strip()]

    # 배치 내 제목 중복 경고 (기사검수.py가 잡기 전 조기 알림)
    seen_titles: dict = {}
    for a in articles:
        title = a.get("title", "")
        if title in seen_titles:
            print(f"⚠️  [배치 내 제목 중복] id={seen_titles[title]} & id={a['id']}: '{title}'")
        else:
            seen_titles[title] = a["id"]

    return articles

# ── 편집국 브리핑 + 글로벌 이슈 레이더 생성 ────────
def generate_editorial(articles):
    """오늘 기사를 바탕으로 편집국 브리핑(2~3문장)과 글로벌 이슈 레이더(4~5개) 생성"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    titles_text = "\n".join(
        f"- {a['title']}: {(a.get('summary') or '')[:80]}" for a in articles
    )

    prompt = f"""오늘 소재경제신문 주요 기사:
{titles_text}

위 기사를 바탕으로 save_editorial 도구를 사용해:
1. briefing: 오늘 산업·공급망 전체 흐름을 2~3문장으로 요약 (150자 이내, 편집장 코멘트 느낌)
2. issues: 현재 진행 중인 글로벌 주요 이슈 4~5개
   - icon: 🔴(위험/긴급) 🟡(주의/모니터링) 🟢(긍정/개선)
   - label: 이슈명 (15자 이내)
   - status: 상태 한 줄 (12자 이내)
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            tools=[{
                "name": "save_editorial",
                "description": "편집국 브리핑과 글로벌 이슈 레이더를 저장합니다",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "briefing": {"type": "string"},
                        "issues": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "icon":   {"type": "string", "enum": ["🔴","🟡","🟢"]},
                                    "label":  {"type": "string"},
                                    "status": {"type": "string"}
                                },
                                "required": ["icon","label","status"]
                            },
                            "minItems": 4,
                            "maxItems": 5
                        }
                    },
                    "required": ["briefing","issues"]
                }
            }],
            tool_choice={"type": "tool", "name": "save_editorial"},
            messages=[{"role": "user", "content": prompt}]
        )
        tool_block = next(b for b in response.content if b.type == "tool_use")
        briefing = tool_block.input["briefing"]
        issues   = tool_block.input["issues"]
        print(f"   → 브리핑 생성 완료, 이슈 {len(issues)}개")
        return briefing, issues
    except Exception as e:
        print(f"  편집국 생성 오류: {e} → 기본값 사용")
        return (
            "오늘 소재경제신문은 반도체·희귀금속·산업재 분야 주요 동향을 집중 보도합니다.",
            [
                {"icon": "🔴", "label": "미·중 공급망 갈등", "status": "진행 중"},
                {"icon": "🟡", "label": "희귀금속 가격 불안", "status": "모니터링"},
                {"icon": "🟡", "label": "반도체 소재 국산화", "status": "진행 중"},
                {"icon": "🟢", "label": "국내 AI 반도체 투자", "status": "확대"},
            ]
        )

# ════════════════════════════════════════════════════════
# 이미지 관리 규칙 (IMAGE RULES)
# ════════════════════════════════════════════════════════
# 1. 카테고리별 풀에 동일 photo-ID가 두 카테고리에 등록되면 안 된다.
#    → 같은 이미지가 같은 날 여러 기사에 사용되는 원인이 됨.
# 2. 한 실행(run) 안에서 이미 선택한 photo-ID는 재사용 금지 (_used_photo_ids).
# 3. 다운로드된 파일의 MD5가 이미 저장된 파일과 동일하면 다음 소스로 넘어간다
#    (_downloaded_hashes). 소스 우선순위: Unsplash API → Pexels → Pixabay → 풀 → picsum.
# 4. 풀은 카테고리당 최소 8개 이상을 유지하고, 아래 검증 함수로 중복을 자동 감지한다.
# ════════════════════════════════════════════════════════

# ── 카테고리별 Unsplash 큐레이션 풀 ──────────────────
# 규칙: 동일 photo-ID가 두 카테고리에 나타나서는 안 된다.
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

# ── 중복 방지 상태 ────────────────────────────────────
# _used_photo_ids / _downloaded_hashes 는 "이번 실행" 범위.
# _photo_id_last_used / (영구 hashes) 는 image_history.json 으로 "날짜 간" 유지된다.
_used_photo_ids: set   = set()   # 이번 실행에서 선택된 Unsplash photo-ID
_downloaded_hashes: set = set()  # 지금까지(과거 포함) 저장된 이미지 MD5
_photo_id_last_used: dict = {}   # photo-ID → 마지막 사용 날짜(YYYY-MM-DD)


def _load_image_history():
    """image_history.json 로드 → 과거 MD5 해시와 photo-ID 사용 이력을 메모리에 적재.
    파일이 없으면 images/ 폴더의 기존 파일을 해시해 부트스트랩한다."""
    global _downloaded_hashes, _photo_id_last_used
    try:
        with open(IMAGE_HISTORY_FILE, "r", encoding="utf-8") as f:
            hist = json.load(f)
        _photo_id_last_used = dict(hist.get("photo_ids", {}))
        _downloaded_hashes = set(hist.get("hashes", []))
    except (FileNotFoundError, json.JSONDecodeError):
        _photo_id_last_used = {}
        _downloaded_hashes = set()

    # 디스크의 기존 이미지 해시도 항상 흡수 (히스토리 파일이 유실돼도 재사용 방지)
    if os.path.isdir(IMAGES_DIR):
        for fn in os.listdir(IMAGES_DIR):
            fp = os.path.join(IMAGES_DIR, fn)
            if not os.path.isfile(fp):
                continue
            try:
                with open(fp, "rb") as f:
                    _downloaded_hashes.add(hashlib.md5(f.read()).hexdigest())
            except Exception:
                pass
    print(f"🗂️  이미지 히스토리 로드: 해시 {len(_downloaded_hashes)}개 · photo-ID {len(_photo_id_last_used)}개")


def _save_image_history():
    """이번 실행에서 갱신된 photo-ID 사용 이력과 MD5 해시를 image_history.json에 저장.
    해시는 최근 800개까지만 보존해 파일 크기를 제한한다."""
    hashes = list(_downloaded_hashes)[-800:]
    data = {"photo_ids": _photo_id_last_used, "hashes": hashes}
    try:
        with open(IMAGE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"🗂️  이미지 히스토리 저장: 해시 {len(hashes)}개 · photo-ID {len(_photo_id_last_used)}개")
    except Exception as e:
        print(f"   → 히스토리 저장 오류: {e}")


def _validate_pool():
    """풀 내 cross-category 중복 ID 감지 (디버그용)"""
    seen = {}
    for cat, ids in _UNSPLASH_POOL.items():
        for pid in ids:
            if pid in seen:
                print(f"⚠️  중복 photo-ID: {pid} — {seen[pid]} ↔ {cat}")
            seen[pid] = cat


def _pick_pool_url(category: str, seed_str: str) -> tuple[str, str]:
    """카테고리 풀에서 photo-ID를 선택. (url, photo_id) 반환.
    선택 우선순위:
      1. 이번 실행에서 아직 안 쓴 ID 중
      2. '가장 오래전에 사용(또는 미사용)' 그룹을 우선(LRU) → 날짜 간 반복 간격 최대화
      3. 동률이면 시드 해시로 결정(변화 부여)
    실제 저장 성공 시점에 _record_photo_id로 사용 날짜를 기록한다."""
    pool = _UNSPLASH_POOL.get(category) or _UNSPLASH_POOL["반도체소재"]
    available = [p for p in pool if p not in _used_photo_ids]
    if not available:
        available = pool  # 이번 실행에서 풀 소진 시 재사용 허용
    # 마지막 사용 날짜 오름차순 — 미사용("")이 가장 앞 = 최우선
    oldest_key = min(_photo_id_last_used.get(p, "") for p in available)
    tied = [p for p in available if _photo_id_last_used.get(p, "") == oldest_key]
    idx = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % len(tied)
    chosen = tied[idx]
    _used_photo_ids.add(chosen)
    return _UNSPLASH_BASE.format(id=chosen), chosen


def _record_photo_id(photo_id: str):
    """실제로 저장에 사용된 photo-ID의 마지막 사용 날짜를 오늘로 기록"""
    if photo_id:
        _photo_id_last_used[photo_id] = datetime.now(KST).strftime("%Y-%m-%d")


# ── 외부 이미지 소스 함수 ─────────────────────────────

def _fetch_pexels(keyword: str) -> str | None:
    """Pexels API로 키워드 관련 이미지 URL 반환 (PEXELS_API_KEY 필요)"""
    if not PEXELS_API_KEY:
        return None
    try:
        resp = requests.get(
            f"https://api.pexels.com/v1/search",
            params={"query": keyword, "per_page": 10, "orientation": "landscape"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=15,
        )
        if resp.status_code == 200:
            photos = resp.json().get("photos", [])
            if photos:
                return random.choice(photos)["src"]["large2x"]
    except Exception as e:
        print(f"   → Pexels 오류: {e}")
    return None


def _fetch_pixabay(keyword: str) -> str | None:
    """Pixabay API로 키워드 관련 이미지 URL 반환 (PIXABAY_API_KEY 필요)"""
    if not PIXABAY_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": PIXABAY_API_KEY,
                "q": keyword,
                "image_type": "photo",
                "orientation": "horizontal",
                "per_page": 10,
                "safesearch": "true",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            if hits:
                return random.choice(hits)["largeImageURL"]
    except Exception as e:
        print(f"   → Pixabay 오류: {e}")
    return None


# ── 이미지 다운로드 (중복 방지 포함) ─────────────────
def _download_single_image(keyword: str, img_path: str, category: str = "", seed_str: str = "") -> bool:
    """이미지를 img_path에 저장. 성공 시 True 반환.

    소스 우선순위:
      1. Unsplash API  — UNSPLASH_ACCESS_KEY 있을 때, 키워드 매칭 최고 품질
      2. Pexels API    — PEXELS_API_KEY 있을 때, 키워드 매칭 고품질
      3. Pixabay API   — PIXABAY_API_KEY 있을 때, 키워드 매칭 무료
      4. Unsplash 풀   — API 키 불필요, 카테고리 연관 큐레이션 이미지
      5. picsum        — 최종 폴백 (무관 이미지지만 서비스 안정성 보장)

    중복 방지:
      - _downloaded_hashes: 동일 MD5 파일은 저장하지 않고 다음 소스로 넘어감
      - _used_photo_ids: Unsplash 풀에서 이미 사용한 photo-ID는 재선택 안 함
    """
    global _downloaded_hashes
    keyword_q = quote(keyword)
    seed = hashlib.md5(keyword.encode()).hexdigest()[:8]

    # 소스 우선순위(풀은 소진 시 재시도용으로 여러 번 시도)
    order: list[str] = []
    if UNSPLASH_ACCESS_KEY:
        order.append("unsplash_api")
    if PEXELS_API_KEY:
        order.append("pexels")
    if PIXABAY_API_KEY:
        order.append("pixabay")
    # 풀은 중복 거부 시 다음 후보로 넘어갈 수 있도록 풀 크기만큼 재시도
    order += ["unsplash_pool"] * 8
    order.append("picsum")

    pool_try = 0
    for source in order:
        chosen_pid = None
        try:
            # 소스별 URL 확정
            if source == "unsplash_api":
                r = requests.get(
                    f"https://api.unsplash.com/photos/random?query={keyword_q}&orientation=landscape"
                    f"&client_id={UNSPLASH_ACCESS_KEY}",
                    timeout=15,
                )
                if r.status_code != 200:
                    continue
                img_url = r.json().get("urls", {}).get("regular", "")
                if not img_url:
                    continue
            elif source == "pexels":
                img_url = _fetch_pexels(keyword)
                if not img_url:
                    continue
            elif source == "pixabay":
                img_url = _fetch_pixabay(keyword)
                if not img_url:
                    continue
            elif source == "unsplash_pool":
                # 재시도마다 시드를 바꿔 다른 photo-ID가 선택되게 함
                img_url, chosen_pid = _pick_pool_url(
                    category or "반도체소재", f"{seed_str or keyword}_{pool_try}"
                )
                pool_try += 1
            else:
                img_url = f"https://picsum.photos/seed/{seed}/800/450"

            resp = requests.get(img_url, timeout=30, allow_redirects=True)
            if resp.status_code != 200 or len(resp.content) < 1000:
                continue

            # MD5 중복 체크 (과거 날짜 포함 — 히스토리에 축적된 해시와 대조)
            img_hash = hashlib.md5(resp.content).hexdigest()
            if img_hash in _downloaded_hashes:
                print(f"   → 중복 이미지 [{source}] md5={img_hash[:8]}, 다음 소스 시도...")
                continue

            _downloaded_hashes.add(img_hash)
            _record_photo_id(chosen_pid)  # 풀 이미지일 때만 사용 날짜 기록
            with open(img_path, "wb") as f:
                f.write(resp.content)
            print(f"   → 이미지 저장: {img_path} [{category}] ({source})")
            return True

        except Exception as e:
            print(f"   → 이미지 오류 [{source}]: {e}")

    return False


def download_article_images(articles):
    """각 기사의 카테고리 기반 이미지 다운로드 → images/YYYY-MM-DD_article_N.jpg
    날짜 포함 파일명으로 날짜별 이미지 중복을 방지한다.
    _used_photo_ids만 run 단위로 초기화하고, _downloaded_hashes·_photo_id_last_used는
    image_history.json에서 로드해 날짜 간(run 간) 재사용을 방지한다.
    """
    global _used_photo_ids
    _used_photo_ids.clear()
    _load_image_history()  # 과거 해시·photo-ID 이력 적재 (_downloaded_hashes 채움)
    _validate_pool()       # 풀 cross-category 중복 감지 (로그 출력)

    os.makedirs(IMAGES_DIR, exist_ok=True)
    date_prefix = datetime.now(KST).strftime("%Y-%m-%d")
    for i, article in enumerate(articles):
        keyword  = article.get("image_keyword", "semiconductor materials technology")
        category = article.get("category", "반도체소재")
        seed_str = f"{date_prefix}_{i}_{article.get('title', '')}"
        img_path = f"{IMAGES_DIR}/{date_prefix}_article_{i}.jpg"
        if _download_single_image(keyword, img_path, category, seed_str):
            article["image_url"] = img_path
        else:
            article["image_url"] = None
            print(f"   → 이미지 모두 실패 [{keyword}]")

    _save_image_history()  # 이번 실행에서 갱신된 이력 영구 저장
    return articles


# ── 최종 데이터 파일 저장 ──────────────────────────
def save_data(articles, briefing, issues):
    """index.html이 읽을 수 있는 JSON 파일로 저장 + 날짜별 아카이브 저장"""
    now = datetime.now(KST)
    date_key = now.strftime("%Y-%m-%d")
    data = {
        "generated_at": now.strftime("%Y년 %m월 %d일 %H:%M"),
        "date_str": now.strftime("%Y년 %m월 %d일"),
        "articles": articles,
        "editorial_briefing": briefing,
        "global_issues": issues,
    }

    # 1. 최신 기사 저장 (articles.json — 사이트 메인)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {OUTPUT_FILE} 저장 완료 — 기사 {len(articles)}건")

    # 2. 날짜별 아카이브 저장
    os.makedirs("archive", exist_ok=True)
    archive_file = f"archive/{date_key}.json"
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"📁 아카이브 저장: {archive_file}")

    # 3. 아카이브 인덱스 업데이트 (최대 90일 보존)
    index_file = "archive/index.json"
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            archive_index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        archive_index = {"dates": []}

    dates = list(dict.fromkeys([date_key] + archive_index.get("dates", [])))
    archive_index = {"dates": sorted(dates, reverse=True)[:90]}
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(archive_index, f, ensure_ascii=False, indent=2)
    print(f"📋 아카이브 인덱스 업데이트: {len(archive_index['dates'])}일치")

# ── 메인 실행 ──────────────────────────────────────
def main():
    print(f"[{datetime.now(KST).strftime('%H:%M')}] 기사 생성 시작...")

    # 1. RSS 수집
    print("📡 RSS 뉴스 수집 중...")
    raw_news = collect_news_from_rss()
    print(f"   → {len(raw_news)}건 수집됨")

    # 2. 최근 기사 주제 로드 (중복 방지용, 최근 3일)
    print("📋 최근 기사 주제 로드 중 (3일치)...")
    recent_topics = load_recent_topics(days=3)
    if recent_topics:
        days_covered = sorted(set(t["date"] for t in recent_topics), reverse=True)
        print(f"   → {len(recent_topics)}건 로드 ({', '.join(days_covered)})")
        for t in recent_topics:
            print(f"      [{t['date']}] {t['title']}")
    else:
        print("   → 아카이브 없음 (첫 실행)")

    # 3. Claude로 기사 생성 (최근 주제 중복 금지)
    print("✍️  Claude API로 기사 작성 중...")
    articles = generate_articles_with_claude(raw_news, recent_topics)
    print(f"   → 기사 {len(articles)}건 생성됨")

    # 3. 기사 이미지 다운로드 (로컬 저장)
    print("🖼️  기사 이미지 다운로드 중...")
    articles = download_article_images(articles)

    # 4. 편집국 브리핑 + 글로벌 이슈 레이더 생성
    print("📰 편집국 브리핑 + 이슈 레이더 생성 중...")
    briefing, issues = generate_editorial(articles)

    # 5. 저장
    save_data(articles, briefing, issues)
    print("🎉 완료!")

if __name__ == "__main__":
    main()
