"""
소재경제신문 - 자동 기사 생성 스크립트
실행: python 기사자동생성.py
필요: pip install anthropic requests feedparser
"""

import anthropic
import feedparser
import json
import os
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ── 설정 ──────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "여기에_API키_입력")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
OUTPUT_FILE = "articles.json"  # 뉴스 사이트에서 읽는 파일
IMAGES_DIR = "images"          # 기사 이미지 저장 폴더

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

# ── Claude API로 기사 생성 ─────────────────────────
def generate_articles_with_claude(raw_news_list):
    """수집된 뉴스를 바탕으로 Claude가 독창적 기사 작성"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 원본 뉴스 목록을 텍스트로 변환
    news_text = ""
    for i, item in enumerate(raw_news_list[:15], 1):  # 최대 15개 처리
        news_text += f"{i}. [{item['source']}] {item['title']}\n   {item['summary']}\n\n"

    if news_text:
        news_section = f"[수집된 원본 뉴스]\n{news_text}\n\n원문을 참고해서 핵심 내용을 바탕으로 새로운 문장으로 작성하세요."
    else:
        news_section = "[원본 뉴스 없음]\nRSS 수집에 실패했습니다. 최근 반도체·소재·희귀금속·산업재 업계 동향을 바탕으로 실제 있을 법한 기사를 작성하세요."

    prompt = f"""반도체·소재·희귀금속·산업재 전문 뉴스 사이트용 기사 5개를 작성해주세요.

{news_section}

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

# ── 카테고리별 Unsplash 이미지 풀 (API 키 불필요, 내용 관련 이미지 보장) ──
# Unsplash 이미지는 photo-ID 형식으로 직접 접근 가능 (CDN 무료)
_UNSPLASH_POOL = {
    "반도체소재": [
        "photo-1518770660439-4636190af475",  # PCB 회로기판 클로즈업
        "photo-1591799265444-d66432b91588",  # AMD Ryzen CPU 칩
        "photo-1562408590-e32931084e23",     # PCB 회로기판 컬러
        "photo-1597852074816-d933c7d2b988",  # HDD 내부 부품
        "photo-1581092918056-0c4c3acd3789",  # 전자기기 회로 수리
        "photo-1581092160607-ee22621dd758",  # 엔지니어 기계 작업
    ],
    "희귀금속": [
        "photo-1504917595217-d4dc5ebe6122",  # 금속 용접 불꽃
        "photo-1504328345606-18bbc8c9d7d1",  # 용접사 클로즈업
        "photo-1567789884554-0b844b597180",  # 제조공장 로봇
        "photo-1541888946425-d81bb19240f5",  # 건설 현장 엔지니어
        "photo-1473341304170-971dccb5ac1e",  # 전력 송전 인프라
        "photo-1581092160607-ee22621dd758",  # 산업 기계 작업
    ],
    "산업재": [
        "photo-1567789884554-0b844b597180",  # 자동차 공장 로봇
        "photo-1504917595217-d4dc5ebe6122",  # 금속 용접 불꽃
        "photo-1504328345606-18bbc8c9d7d1",  # 용접사 불꽃
        "photo-1473341304170-971dccb5ac1e",  # 전력 송전탑
        "photo-1541888946425-d81bb19240f5",  # 건설현장 엔지니어
        "photo-1581092160607-ee22621dd758",  # 엔지니어 기계 작업
        "photo-1586528116311-ad8dd3c8310d",  # 물류 창고 내부
    ],
    "글로벌": [
        "photo-1494412519320-aa613dfb7738",  # 컨테이너 항구 항공뷰
        "photo-1578575437130-527eed3abbec",  # 컨테이너선 항구
        "photo-1565793298595-6a879b1d9492",  # 물류 트럭 주차장
        "photo-1586528116311-ad8dd3c8310d",  # 물류 창고 내부
        "photo-1541888946425-d81bb19240f5",  # 글로벌 인프라 건설
        "photo-1473341304170-971dccb5ac1e",  # 전력 인프라
    ],
}
_UNSPLASH_BASE = "https://images.unsplash.com/{id}?w=800&h=450&fit=crop&auto=format"

def _pick_unsplash_url(category: str, seed_str: str) -> str:
    """카테고리와 시드 문자열로 Unsplash 풀에서 이미지 URL 선택"""
    import hashlib
    pool = _UNSPLASH_POOL.get(category) or _UNSPLASH_POOL["반도체소재"]
    idx = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % len(pool)
    return _UNSPLASH_BASE.format(id=pool[idx])


# ── 기사 이미지 다운로드 및 로컬 저장 ─────────────
def _download_single_image(keyword: str, img_path: str, category: str = "", seed_str: str = "") -> bool:
    """이미지를 img_path에 저장. 성공 시 True 반환.
    1차: Unsplash API (UNSPLASH_ACCESS_KEY 있을 때)
    2차: 카테고리별 Unsplash 풀 (API 키 불필요, 내용 연관 이미지 보장)
    3차: picsum (최종 폴백)
    loremflickr는 전문 산업 키워드(탄탈럼·희귀금속 등)에서 무관한 이미지를 반환하므로 제외.
    """
    import hashlib
    keyword_q = quote(keyword)
    seed = hashlib.md5(keyword.encode()).hexdigest()[:8]

    candidates = []
    # 1차: Unsplash API (키 있을 때)
    if UNSPLASH_ACCESS_KEY:
        candidates.append(("unsplash_api",
            f"https://api.unsplash.com/photos/random?query={keyword_q}&orientation=landscape"
            f"&client_id={UNSPLASH_ACCESS_KEY}"))
    # 2차: 카테고리별 Unsplash 풀 (키 없어도 됨)
    pool_url = _pick_unsplash_url(category or "반도체소재", seed_str or keyword)
    candidates.append(("unsplash_pool", pool_url))
    # 3차: picsum 폴백
    candidates.append(("picsum", f"https://picsum.photos/seed/{seed}/800/450"))

    for source, img_url in candidates:
        try:
            resp = requests.get(img_url, timeout=20, allow_redirects=True)
            if resp.status_code == 200:
                if source == "unsplash_api":
                    raw_url = resp.json().get("urls", {}).get("regular", "")
                    if not raw_url:
                        continue
                    resp = requests.get(raw_url, timeout=30, allow_redirects=True)
                    if resp.status_code != 200 or len(resp.content) < 1000:
                        continue
                elif len(resp.content) < 1000:
                    continue
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                print(f"   → 이미지 저장: {img_path} [{category or keyword}] ({source})")
                return True
        except Exception as e:
            print(f"   → 이미지 오류 [{source}]: {e}")
    return False


def download_article_images(articles):
    """각 기사의 카테고리 기반 이미지 다운로드 → images/YYYY-MM-DD_article_N.jpg
    날짜 포함 파일명으로 날짜별 이미지 중복을 방지한다.
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)
    date_prefix = datetime.now(KST).strftime("%Y-%m-%d")
    for i, article in enumerate(articles):
        keyword = article.get("image_keyword", "semiconductor materials technology")
        category = article.get("category", "반도체소재")
        seed_str = f"{date_prefix}_{i}_{article.get('title','')}"
        img_path = f"{IMAGES_DIR}/{date_prefix}_article_{i}.jpg"
        if _download_single_image(keyword, img_path, category, seed_str):
            article["image_url"] = img_path
        else:
            article["image_url"] = None
            print(f"   → 이미지 모두 실패 [{keyword}]")
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

    # 2. Claude로 기사 생성
    print("✍️  Claude API로 기사 작성 중...")
    articles = generate_articles_with_claude(raw_news)
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
