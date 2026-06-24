"""
소재경제신문 - 자동 기사 생성 스크립트
실행: python 기사자동생성.py
필요: pip install anthropic requests feedparser
"""

import anthropic
import feedparser
import json
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ── 설정 ──────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "여기에_API키_입력")
OUTPUT_FILE = "articles.json"  # 뉴스 사이트에서 읽는 파일

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
- 본문: 3~4문장, 전문 용어는 쉽게 풀어서
- timestamp: 현재 시각 기준 오전/오후 HH:MM 형식

반드시 아래 JSON 배열 형식만 반환하세요 (```json 마크다운 없이, 순수 JSON만):

[
  {{
    "id": 1,
    "category": "카테고리명",
    "tag_type": "태그클래스",
    "title": "기사 제목",
    "summary": "기사 본문 3~4문장",
    "is_featured": true,
    "timestamp": "오전 09:00"
  }},
  {{
    "id": 2,
    "category": "카테고리명",
    "tag_type": "태그클래스",
    "title": "기사 제목",
    "summary": "기사 본문 3~4문장",
    "is_featured": false,
    "timestamp": "오전 08:30"
  }}
]

첫 번째 기사만 is_featured: true, 나머지는 false로 설정하세요.
"""

    # tool_use로 JSON 구조 보장
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
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
                                "id":          {"type": "integer"},
                                "category":    {"type": "string", "enum": ["반도체소재","희귀금속","산업재","글로벌"]},
                                "tag_type":    {"type": "string"},
                                "title":       {"type": "string"},
                                "summary":     {"type": "string"},
                                "is_featured": {"type": "boolean"},
                                "timestamp":   {"type": "string"}
                            },
                            "required": ["id","category","tag_type","title","summary","is_featured","timestamp"]
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
    )

    articles = response.content[0].input["articles"]
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
        prices = response.content[0].input["prices"]
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

# ── 최종 데이터 파일 저장 ──────────────────────────
def save_data(articles, market_prices):
    """index.html이 읽을 수 있는 JSON 파일로 저장"""
    now = datetime.now(KST)
    data = {
        "generated_at": now.strftime("%Y년 %m월 %d일 %H:%M"),
        "date_str": now.strftime("%Y년 %m월 %d일"),
        "articles": articles,
        "market": market_prices,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {OUTPUT_FILE} 저장 완료 — 기사 {len(articles)}건")

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

    # 3. 시세 데이터 (뉴스 기반 Claude 추출)
    print("💹 소재 시세 수집 중...")
    market = get_market_prices()

    # 4. 저장
    save_data(articles, market)
    print("🎉 완료!")

if __name__ == "__main__":
    main()
