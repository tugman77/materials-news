"""
소재타임스 주간 뉴스레터 자동 생성 스크립트
실행: python 뉴스레터생성.py
필요: pip install anthropic
"""

import anthropic
import json
import os
import requests
from datetime import datetime, timezone, timedelta

# ── 설정 ──────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "여기에_API키_입력")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
OUTPUT_DIR = "newsletter"
KST = timezone(timedelta(hours=9))


# ── 텔레그램 알림 ────────────────────────────────────────────────────
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

# 카테고리 색상 맵
CAT_COLORS = {
    "반도체소재": ("#e8f0fb", "#0057a8"),
    "희귀금속":   ("#fdf0f0", "#c8102e"),
    "산업재":     ("#f0f7ee", "#2e7d32"),
    "글로벌":     ("#fdf6e3", "#a05000"),
}


# ── 기사 수집 ─────────────────────────────────────
def load_this_week_articles():
    """이번 주(최근 7일) 기사를 articles.json + archive에서 수집"""
    articles = []
    today = datetime.now(KST).date()
    week_ago = today - timedelta(days=7)

    # 오늘 기사
    if os.path.exists("articles.json"):
        with open("articles.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        date_str = str(today)
        for i, a in enumerate(data.get("articles", [])):
            articles.append({**a, "date": date_str, "idx": i})
        print(f"   오늘 기사: {len(data.get('articles', []))}개")

    # 아카이브 (최근 7일)
    if os.path.exists("archive/index.json"):
        with open("archive/index.json", "r", encoding="utf-8") as f:
            index = json.load(f)
        recent_dates = [d for d in index.get("dates", []) if d >= str(week_ago)]
        for date_str in recent_dates:
            path = f"archive/{date_str}.json"
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                arts = data.get("articles", [])
                for i, a in enumerate(arts):
                    articles.append({**a, "date": date_str, "idx": i})
        print(f"   아카이브 기사: {len(articles)}개 누계")

    return articles


# ── Claude 뉴스레터 내용 생성 ─────────────────────
def generate_newsletter_content(articles):
    """Claude로 편집장 인트로·픽·시그널 생성"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    article_list = "\n".join([
        f"[{a.get('category','')}] {a.get('title','')} — {(a.get('summary',''))[:100]}"
        for a in articles[:20]
    ])

    prompt = f"""당신은 소재타임스 편집장입니다. 이번 주 기사들을 바탕으로 주간 뉴스레터를 작성해주세요.

이번 주 기사 목록:
{article_list}

아래 JSON 형식으로만 답해주세요 (다른 텍스트 없이):
{{
  "headline": "이번 주 핵심 메시지 한 줄 (30자 이내)",
  "intro": "편집장 인트로 200자. 이번 주 가장 중요한 산업 흐름을 독자에게 설명.",
  "top_picks": [
    {{"title": "기사 제목 그대로", "reason": "이 기사가 중요한 이유 60자 이내"}}
  ],
  "week_signal": "이번 주 산업 시그널 한마디 (100자 이내, 다음 주를 전망)"
}}

top_picks는 3개를 골라주세요."""

    try:
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        content = message.content[0].text.strip()
        # 코드블록 제거
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.split("```")[0]
        return json.loads(content.strip())
    except Exception as e:
        print(f"   ⚠️  Claude 생성 실패: {e}")
        return {
            "headline": "이번 주 소재산업 주요 동향",
            "intro": "이번 주 소재산업 뉴스를 요약해드립니다. 반도체·희귀금속·공급망 분야의 주요 이슈를 확인하세요.",
            "top_picks": [],
            "week_signal": "글로벌 소재 공급망 변화를 지속 모니터링 중입니다."
        }


# ── HTML 생성 ─────────────────────────────────────
def cat_badge_html(cat):
    bg, color = CAT_COLORS.get(cat, ("#f0f0f0", "#444"))
    return (f'<span style="background:{bg};color:{color};font-size:11px;'
            f'font-weight:700;padding:2px 8px;border-radius:2px;'
            f'display:inline-block;">{cat}</span>')


def generate_html(articles, nl, week_str):
    """HTML 뉴스레터 파일 생성"""

    # 기사 카드 HTML (최대 8개)
    articles_html = ""
    for a in articles[:8]:
        img_html = ""
        if a.get("image_url"):
            img_html = (
                f'<img src="{a["image_url"]}" alt="{a.get("title","")}" '
                f'style="width:100%;height:180px;object-fit:cover;display:block;" '
                f'onerror="this.style.display=\'none\'">'
            )
        articles_html += f"""
        <div style="background:#fff;border:1px solid #d8d8d2;margin-bottom:16px;">
          {img_html}
          <div style="padding:14px 16px 16px;">
            {cat_badge_html(a.get('category',''))}
            <div style="font-size:16px;font-weight:700;color:#1a2b4a;
                        margin:8px 0 6px;line-height:1.45;word-break:break-all;">
              {a.get('title','')}
            </div>
            <div style="font-size:13px;color:#555;line-height:1.7;">
              {(a.get('summary',''))[:130]}…
            </div>
            <div style="font-size:11px;color:#999;margin-top:8px;">
              {a.get('date','')}
            </div>
          </div>
        </div>"""

    # 이번 주 픽 HTML
    picks_html = ""
    for pick in nl.get("top_picks", []):
        picks_html += f"""
        <div style="padding:10px 0;border-bottom:1px solid #e0dbd4;">
          <div style="font-size:14px;font-weight:700;color:#1a2b4a;">
            📌 {pick.get('title','')}
          </div>
          <div style="font-size:13px;color:#666;margin-top:4px;line-height:1.5;">
            {pick.get('reason','')}
          </div>
        </div>"""

    picks_section = ""
    if picks_html:
        picks_section = f"""
  <!-- 이번 주 PICK -->
  <div style="background:#f8f4ef;padding:16px 24px;border-bottom:1px solid #d8d8d2;">
    <div style="font-size:11px;font-weight:700;color:#7a5c3a;letter-spacing:1px;
                border-bottom:2px solid #7a5c3a;padding-bottom:6px;margin-bottom:12px;">
      이번 주 PICK
    </div>
    {picks_html}
  </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>소재타임스 주간 뉴스레터 — {week_str}</title>
</head>
<body style="margin:0;padding:20px 0;background:#f2f2ee;
             font-family:'Noto Sans KR','Malgun Gothic',sans-serif;">

<div style="max-width:620px;margin:0 auto;">

  <!-- 헤더 -->
  <div style="background:#1a2b4a;padding:24px 24px 20px;border-bottom:3px solid #c8102e;">
    <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-0.5px;">소재타임스</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.4);letter-spacing:2px;margin-top:2px;">
      MATERIALS TIMES
    </div>
    <div style="margin-top:14px;">
      <span style="background:#c8102e;color:#fff;font-size:12px;font-weight:700;
                   padding:3px 12px;display:inline-block;">
        주간 뉴스레터 — {week_str}
      </span>
    </div>
  </div>

  <!-- 편집장 인트로 -->
  <div style="background:#fff;padding:20px 24px;border-bottom:1px solid #d8d8d2;">
    <div style="font-size:19px;font-weight:700;color:#1a2b4a;
                margin-bottom:12px;line-height:1.4;word-break:break-all;">
      {nl.get('headline', '이번 주 소재산업 주요 동향')}
    </div>
    <div style="font-size:14px;color:#444;line-height:1.85;">
      {nl.get('intro', '')}
    </div>
  </div>

  {picks_section}

  <!-- 기사 목록 -->
  <div style="padding:20px 24px;">
    <div style="font-size:11px;font-weight:700;color:#1a2b4a;letter-spacing:1px;
                border-bottom:2px solid #1a2b4a;padding-bottom:6px;margin-bottom:16px;">
      이번 주 기사
    </div>
    {articles_html}
  </div>

  <!-- WEEK SIGNAL -->
  <div style="background:#1a2b4a;padding:18px 24px;margin-bottom:16px;">
    <div style="font-size:11px;font-weight:700;color:#c8102e;
                letter-spacing:1.5px;margin-bottom:8px;">
      WEEK SIGNAL
    </div>
    <div style="font-size:14px;color:rgba(255,255,255,0.88);line-height:1.7;">
      {nl.get('week_signal', '')}
    </div>
  </div>

  <!-- 푸터 -->
  <div style="background:#111;padding:16px 24px;">
    <div style="font-size:13px;color:#fff;font-weight:700;margin-bottom:6px;">소재타임스</div>
    <div style="font-size:11px;color:#777;line-height:1.7;">
      반도체 · 첨단소재 · 희귀금속 · 산업재 전문 미디어<br>
      © 2026 소재타임스. All rights reserved.
    </div>
  </div>

</div>
</body>
</html>"""

    return html


# ── 메인 ──────────────────────────────────────────
def main():
    print("📰 소재타임스 주간 뉴스레터 생성 시작...")
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    try:
        now = datetime.now(KST)
        # 이번 주 월~일 범위 문자열
        monday = now - timedelta(days=now.weekday())
        sunday = monday + timedelta(days=6)
        week_str = f"{monday.month}월 {monday.day}일 ~ {sunday.month}월 {sunday.day}일"

        # 1. 기사 수집
        print("📥 기사 수집 중...")
        articles = load_this_week_articles()
        if not articles:
            print("❌ 이번 주 기사가 없습니다. 종료.")
            send_telegram(f"⚠️ <b>소재타임스 뉴스레터</b>\n{now_str}\n\n이번 주 기사가 없어 뉴스레터를 생성하지 못했습니다.")
            return
        print(f"   → 총 {len(articles)}개 수집 완료")

        # 2. Claude로 뉴스레터 내용 생성
        print("✍️  Claude로 뉴스레터 내용 생성 중...")
        nl_data = generate_newsletter_content(articles)

        # 3. HTML 생성
        print("🎨 HTML 뉴스레터 생성 중...")
        html = generate_html(articles, nl_data, week_str)

        # 4. 저장
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filename = f"{OUTPUT_DIR}/뉴스레터_{now.strftime('%Y%m%d')}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"✅ 완료! 저장 위치: {filename}")
        print(f"   브라우저로 열면 뉴스레터를 확인할 수 있습니다.")

        # 5. 텔레그램 완료 알림
        headline = nl_data.get("headline", "")
        week_signal = nl_data.get("week_signal", "")
        picks = nl_data.get("top_picks", [])
        picks_text = "\n".join(f"  📌 {p.get('title','')}" for p in picks[:3])
        tg_msg = (
            f"✅ <b>소재타임스 주간 뉴스레터 생성 완료</b>\n"
            f"{now_str} ({week_str})\n\n"
            f"📰 {headline}\n\n"
            f"이번 주 Pick:\n{picks_text}\n\n"
            f"📡 WEEK SIGNAL: {week_signal[:80]}{'...' if len(week_signal) > 80 else ''}\n\n"
            f"기사 {len(articles)}건 수록 | 파일: {filename}"
        )
        send_telegram(tg_msg)

    except Exception as e:
        error_msg = f"❌ <b>소재타임스 뉴스레터 생성 오류</b>\n{now_str}\n\n{type(e).__name__}: {e}"
        print(error_msg)
        send_telegram(error_msg)
        raise


if __name__ == "__main__":
    main()
