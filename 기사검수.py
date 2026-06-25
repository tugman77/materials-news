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

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

IMAGES_DIR = "images"
OUTPUT_FILE = "articles.json"
KST = timezone(timedelta(hours=9))


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

def download_image(keyword: str, article_idx: int) -> str | None:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    keywords_fmt = ",".join(keyword.replace(",", " ").split()[:3])
    seed = hashlib.md5(keyword.encode()).hexdigest()[:8]
    candidates = [
        f"https://loremflickr.com/800/450/{keywords_fmt}",
        f"https://picsum.photos/seed/{seed}/800/450",
    ]
    img_path = f"{IMAGES_DIR}/article_{article_idx}.jpg"
    for img_url in candidates:
        try:
            resp = requests.get(img_url, timeout=20, allow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                print(f"   이미지 저장: {img_path} [{keyword}]")
                return img_path
        except Exception as e:
            print(f"   이미지 오류 ({img_url.split('/')[2]}): {e}")
    return None


def check_and_fix_missing_images(articles: list) -> int:
    """이미지 파일 없는 기사 탐지 후 다운로드, 다운로드 건수 반환"""
    fixed = 0
    for i, article in enumerate(articles):
        img_path = f"{IMAGES_DIR}/article_{i}.jpg"
        if not os.path.exists(img_path) or os.path.getsize(img_path) < 1000:
            keyword = article.get("image_keyword", "semiconductor technology materials")
            print(f"   이미지 누락 [{i}] '{keyword}' → 다운로드 시도")
            path = download_image(keyword, i)
            if path:
                article["image_url"] = path
                fixed += 1
            else:
                article["image_url"] = None
    return fixed


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
                       image_fixes: list, missing_fixed: int, date_str: str):
    STATUS_EMOJI = {"pass": "✅", "warning": "⚠️", "fail": "❌"}
    lines = [f"📋 <b>소재경제신문 검수 보고</b>\n{date_str}\n"]

    has_issues = False
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

    # 2. 누락 이미지 확인 + 다운로드
    print("이미지 파일 확인 중...")
    missing_fixed = check_and_fix_missing_images(articles)
    if missing_fixed:
        print(f"   누락 이미지 {missing_fixed}건 다운로드 완료")
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

            path = download_image(new_kw, idx)
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

    # 7. 텔레그램 보고
    send_review_report(articles, reviews, naver_map, image_fixes, missing_fixed, date_str)

    print("검수 완료!")


if __name__ == "__main__":
    main()
