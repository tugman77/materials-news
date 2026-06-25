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
    # 혹시 문자열로 반환된 경우 파싱
    if isinstance(articles, str):
        import re
        cleaned = re.sub(r'(?<!\\)\n', '\\n', articles)
        articles = json.loads(cleaned)
    # body가 문자열이면 줄바꿈으로 분리해 배열로 변환
    for a in articles:
        if isinstance(a.get("body"), str):
            a["body"] = [p.strip() for p in a["body"].split("\n") if p.strip()]
    return articles

# ── 시세 데이터 (뉴스 기반 Claude 추출) ───────────
def get_market_prices():
    """Google News RSS에서 시세 뉴스 수집 후 Claude가 가격 추출"""

    # 소재별 검색 쿼리 (영문 검색이 가격 정보 더 정확)
    QUERIES = [
        ("탄탈륨 ($/kg)",  "tantalum price per kg 2026"),
        ("비스무트 ($/kg)", "bismuth metal price per kg 2026"),
        ("텔루륨 ($/kg)",  "tellurium price per kg 2026"),
        ("갈륨 ($/kg)",    "gallium price per kg 2026"),
        ("게르마늄 ($/kg)", "germanium price per kg 2026"),
        ("코발트 ($/ton)", "cobalt price per ton LME 2026"),
    ]

    snippets = []
    for label, query in QUERIES:
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en&gl=US&ceid=US:en"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))[:200]
                snippets.append(f"[{label}] {title} — {summary}")
        except Exception as e:
            print(f"  시세 RSS 오류 [{label}]: {e}")

    # 뉴스 수집 결과를 Claude에 전달해 가격 추출
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    news_text = "\n".join(snippets[:24]) if snippets else "뉴스 없음"

    prompt = f"""다음 뉴스 스니펫과 당신이 알고 있는 최신 시장 정보를 종합해서,
아래 6개 소재의 현재 시세(2026년 6월 기준)를 JSON으로 반환하세요.

[참고 뉴스]
{news_text}

[반환 규칙]
- price: 숫자 문자열 (쉼표 없이, 소수점 가능)
- change: "+X.X%" 또는 "-X.X%" 형식 (전일 또는 최근 대비 변동)
- direction: "up" 또는 "down"
- 뉴스에서 확인된 가격 우선, 없으면 알려진 최신 시장가 사용

반드시 아래 JSON 배열 형식만 반환하세요 (```json 마크다운 없이):

[
  {{"name": "탄탈륨 ($/kg)",  "price": "???", "change": "+?%", "direction": "up"}},
  {{"name": "비스무트 ($/kg)", "price": "???", "change": "+?%", "direction": "up"}},
  {{"name": "텔루륨 ($/kg)",  "price": "???", "change": "-?%", "direction": "down"}},
  {{"name": "갈륨 ($/kg)",    "price": "???", "change": "+?%", "direction": "up"}},
  {{"name": "게르마늄 ($/kg)", "price": "???", "change": "+?%", "direction": "up"}},
  {{"name": "코발트 ($/ton)", "price": "???", "change": "-?%", "direction": "down"}}
]
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            tools=[{
                "name": "save_prices",
                "description": "소재 시세 데이터를 저장합니다",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "prices": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name":      {"type": "string"},
                                    "price":     {"type": "string"},
                                    "change":    {"type": "string"},
                                    "direction": {"type": "string", "enum": ["up","down"]}
                                },
                                "required": ["name","price","change","direction"]
                            }
                        }
                    },
                    "required": ["prices"]
                }
            }],
            tool_choice={"type": "tool", "name": "save_prices"},
            messages=[{"role": "user", "content": prompt}]
        )
        tool_block = next(b for b in response.content if b.type == "tool_use")
        prices = tool_block.input["prices"]
        if isinstance(prices, str):
            prices = json.loads(prices)
        print(f"   → 시세 {len(prices)}개 항목 추출됨")
        return prices
    except Exception as e:
        print(f"  시세 추출 오류: {e} → 기본값 사용")
        return [
            {"name": "탄탈륨 ($/kg)",  "price": "152.4",  "change": "+2.3%", "direction": "up"},
            {"name": "비스무트 ($/kg)", "price": "6.85",   "change": "+1.1%", "direction": "up"},
            {"name": "텔루륨 ($/kg)",  "price": "63.2",   "change": "-0.8%", "direction": "down"},
            {"name": "갈륨 ($/kg)",    "price": "2269",   "change": "+4.2%", "direction": "up"},
            {"name": "게르마늄 ($/kg)", "price": "1240",   "change": "+1.7%", "direction": "up"},
            {"name": "코발트 ($/ton)", "price": "26800",  "change": "-0.5%", "direction": "down"},
        ]

# ── 기사 이미지 다운로드 및 로컬 저장 ─────────────
def download_article_images(articles):
    """각 기사의 image_keyword로 이미지를 다운로드해 images/ 폴더에 저장
    1차: loremflickr (주제별 이미지) / 실패 시 2차: picsum (seed 기반 일관 이미지)
    """
    import hashlib
    os.makedirs(IMAGES_DIR, exist_ok=True)
    for i, article in enumerate(articles):
        keyword = article.get("image_keyword", "semiconductor materials technology")
        keywords_fmt = ",".join(keyword.replace(",", " ").split()[:3])
        seed = hashlib.md5(keyword.encode()).hexdigest()[:8]
        candidates = [
            f"https://loremflickr.com/800/450/{keywords_fmt}",
            f"https://picsum.photos/seed/{seed}/800/450",
        ]
        img_path = f"{IMAGES_DIR}/article_{i}.jpg"
        saved = False
        for img_url in candidates:
            try:
                resp = requests.get(img_url, timeout=20, allow_redirects=True)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    article["image_url"] = img_path
                    print(f"   → 이미지 저장: {img_path} [{keyword}] ({img_url.split('/')[2]})")
                    saved = True
                    break
            except Exception as e:
                print(f"   → 이미지 오류 [{img_url.split('/')[2]}]: {e}")
        if not saved:
            article["image_url"] = None
            print(f"   → 이미지 모두 실패 [{keyword}]")
    return articles


# ── 최종 데이터 파일 저장 ──────────────────────────
def save_data(articles, market_prices):
    """index.html이 읽을 수 있는 JSON 파일로 저장 + 날짜별 아카이브 저장"""
    now = datetime.now(KST)
    date_key = now.strftime("%Y-%m-%d")
    data = {
        "generated_at": now.strftime("%Y년 %m월 %d일 %H:%M"),
        "date_str": now.strftime("%Y년 %m월 %d일"),
        "articles": articles,
        "market": market_prices,
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

    # 5. 시세 데이터 (뉴스 기반 Claude 추출)
    print("💹 소재 시세 수집 중...")
    market = get_market_prices()

    # 6. 저장
    save_data(articles, market)
    print("🎉 완료!")

if __name__ == "__main__":
    main()
