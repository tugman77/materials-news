"""
소재타임스 주간 뉴스레터 자동 생성 스크립트
실행: python 뉴스레터생성.py
필요: pip install anthropic
"""

import anthropic
import json
import os
import re
import requests
import llm_backend  # 구독코인(로컬 Claude Code) / API코인(anthropic SDK) 전환
from datetime import date, datetime, timezone, timedelta
from urllib.parse import quote

# ── 설정 ──────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "여기에_API키_입력")
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")     # 관리자 알림(대표님 개인 채팅)
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")  # 공개 채널 발행용(@materialtimes)
OUTPUT_DIR = "newsletter"
SITE_URL = "https://tugman77.github.io/materials-news"  # 커스텀 도메인 연결 시 변경
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


# ── 공개 채널 발행 (독자용) ────────────────────────────────────────
# 웹판(전문 HTML)과 텔레그램판(요약+링크)을 분리한다. 텔레그램에 전문을 다 넣으면
# 웹으로 올 이유가 없어져 검색 유입도 안 쌓이고 뉴스레터가 트래픽 자산이 되지 못한다.
# 관리자 알림(send_telegram)은 그대로 유지 — 발행 성공 여부 확인용이다.
def _tg_escape(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_channel_message(nl, week_str, article_count, web_url) -> str:
    headline = _tg_escape(nl.get("headline", ""))
    intro = _tg_escape((nl.get("intro", "") or "").strip())
    if len(intro) > 160:
        intro = intro[:160].rstrip() + "…"
    lines = ["📊 <b>소재타임스 위클리</b>",
             f"{week_str} · 이번 주 주요 기사 {article_count}건", ""]
    if headline:
        lines += [f"<b>{headline}</b>", ""]
    if intro:
        lines += [f"<i>{intro}</i>", ""]

    picks = nl.get("top_picks", []) or []
    if picks:
        lines.append("<b>이번 주 Pick</b>")
        for p in picks[:3]:
            t = _tg_escape(p.get("title", ""))
            r = _tg_escape((p.get("reason", "") or "").strip())
            lines.append(f"📌 {t}")
            if r:
                lines.append(f"   <i>{r}</i>")
        lines.append("")

    signal = _tg_escape((nl.get("week_signal", "") or "").strip())
    if signal:
        lines += [f"📡 <b>다음 주</b> {signal}", ""]

    lines.append(f'<a href="{web_url}">▸ 전문 보기</a>')
    lines.append("#소재 #반도체 #희귀금속 #공급망")
    return "\n".join(lines)


def post_to_channel(nl, week_str, article_count, web_url) -> bool:
    """주간 뉴스레터 요약을 공개 채널에 발행. 채널 미설정 시 skip."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("[채널 미설정] TELEGRAM_CHANNEL_ID 없음 — 채널 발행 건너뜀")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": build_channel_message(nl, week_str, article_count, web_url),
            "parse_mode": "HTML",
            "disable_web_page_preview": False,  # 웹판 미리보기는 노출 — 클릭 유도
        }, timeout=15)
        if resp.ok:
            print("📣 채널 발행 완료 — 주간 뉴스레터")
            return True
        print(f"❌ 채널 발행 실패 {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"채널 발행 오류: {e}")
        return False


# ── 뉴스레터 구조 스키마 ────────────────────────────────────────
# 구독코인 경로(llm_backend)와 API코인 경로가 같은 스키마를 쓴다.
# llm_backend.call_tool()이 input_schema를 프롬프트에 실어 순수 JSON을 받아내므로,
# 헤드리스에서도 tool_use와 동일한 dict가 나온다.
MODEL = "claude-sonnet-4-6"  # 기사 생성과 동일 모델. 주간 요약은 Sonnet으로 충분하다.

# 웹판 뉴스레터에 카드로 싣는 기사 수. 채널 메시지의 "주요 기사 N건"도 이 값을 쓴다 —
# 따로 두면 "채널엔 36건인데 열어보니 8건"처럼 어긋난다(2026-08-02 시범 발행에서 발생).
DISPLAY_LIMIT = 8

NEWSLETTER_TOOL = {
    "name": "save_newsletter",
    "description": "주간 뉴스레터 구성요소를 저장한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "이번 주 핵심 메시지 한 줄. 30자 이내.",
            },
            "intro": {
                "type": "string",
                "description": "편집장 인트로 200자 내외. 이번 주 가장 중요한 산업 흐름을 독자에게 설명한다.",
            },
            "top_picks": {
                "type": "array",
                "description": "이번 주 주목할 기사 3건.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "기사 제목 그대로"},
                        "reason": {"type": "string", "description": "이 기사가 중요한 이유. 60자 이내."},
                    },
                    "required": ["title", "reason"],
                },
            },
            "week_signal": {
                "type": "string",
                "description": "이번 주 산업 시그널 한마디. 100자 이내, 다음 주를 전망한다.",
            },
        },
        "required": ["headline", "intro", "top_picks", "week_signal"],
    },
}

# 카테고리 색상 맵
CAT_COLORS = {
    "반도체소재": ("#e8f0fb", "#0057a8"),
    "희귀금속":   ("#fdf0f0", "#c8102e"),
    "산업재":     ("#f0f7ee", "#2e7d32"),
    "글로벌":     ("#fdf6e3", "#a05000"),
}


# ── 기사 수집 ─────────────────────────────────────
def _articles_json_date(data, fallback: str) -> str:
    """articles.json의 실제 발행일을 generated_at("2026년 08월 02일 08:56")에서 뽑는다.

    오늘치 발행 전에는 이 파일에 '어제' 기사가 들어 있다. 무조건 오늘로 라벨링하면
    아카이브의 어제치와 날짜만 다른 같은 기사가 되어 뉴스레터에 두 번 실린다.
    """
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(data.get("generated_at", "")))
    if m:
        try:
            return date(*(int(x) for x in m.groups())).isoformat()
        except ValueError:
            pass
    return fallback


def load_this_week_articles():
    """이번 주(최근 7일) 기사를 articles.json + archive에서 수집.

    ⚠️ articles.json의 기사는 발행과 동시에 archive/YYYY-MM-DD.json 에도 저장된다.
       두 소스를 그대로 합치면 항상 같은 기사가 두 번 들어온다 — 제목 기준으로 걷어낸다.
       (2026-08-02 발견: 시범 발행에서 두산·LG화학 기사가 08-02와 08-01로 중복 노출)
    """
    articles = []
    today = datetime.now(KST).date()
    week_ago = today - timedelta(days=7)

    # 최신 발행분 (articles.json) — 날짜는 파일이 말하는 값을 쓴다
    if os.path.exists("articles.json"):
        with open("articles.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        date_str = _articles_json_date(data, str(today))
        for i, a in enumerate(data.get("articles", [])):
            articles.append({**a, "date": date_str, "idx": i})
        print(f"   최신 발행분({date_str}): {len(data.get('articles', []))}개")

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
                for i, a in enumerate(data.get("articles", [])):
                    articles.append({**a, "date": date_str, "idx": i})
        print(f"   아카이브 포함 누계: {len(articles)}개")

    # 제목 기준 중복 제거 — 먼저 온 것(=최신 발행분, 그다음 최신 날짜순)을 남긴다
    seen, unique = set(), []
    for a in articles:
        key = (a.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(a)

    dropped = len(articles) - len(unique)
    if dropped:
        print(f"   중복 제거: {dropped}개 → 최종 {len(unique)}개")
    return unique


# ── Claude 뉴스레터 내용 생성 ─────────────────────
def generate_newsletter_content(articles):
    """편집장 인트로·픽·시그널 생성. 구독코인/API코인 양쪽 지원."""
    # 구독코인 경로에서는 API 클라이언트가 필요 없다 — 키 없이도 로컬 실행이 되도록 지연 생성.
    client = None if llm_backend.using_subscription() \
        else anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    article_list = "\n".join([
        f"[{a.get('category','')}] {a.get('title','')} — {(a.get('summary',''))[:100]}"
        for a in articles[:20]
    ])

    prompt = f"""당신은 소재타임스 편집장입니다. 이번 주 기사들을 바탕으로 주간 뉴스레터를 작성해주세요.

이번 주 기사 목록:
{article_list}

top_picks는 이번 주 가장 중요한 3건을 골라주세요. title은 기사 제목 그대로 씁니다."""

    request_params = {
        "model": MODEL,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [NEWSLETTER_TOOL],
        "tool_choice": {"type": "tool", "name": "save_newsletter"},
    }

    try:
        if llm_backend.using_subscription():
            # 구독코인 — 로컬 Claude Code 헤드리스. 스키마를 프롬프트에 실어 순수 JSON을 받는다.
            return llm_backend.call_tool(request_params, "save_newsletter")

        # API코인 — 기존 경로. tool_use로 구조화 출력을 강제해
        # 코드블록 수동 제거(```json …)를 없앴다. 그쪽이 파싱 실패의 원인이었다.
        message = client.messages.create(**request_params)
        for block in message.content:
            if block.type == "tool_use":
                return block.input
        raise ValueError("tool_use 블록 없음")
    except Exception as e:
        print(f"   ⚠️  뉴스레터 생성 실패({llm_backend.backend_label()}): {e}")
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
    for a in articles[:DISPLAY_LIMIT]:
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

        # 5. 공개 채널 발행 (독자용 요약 + 웹판 링크)
        #    파일명이 한글이라 URL은 percent-encoding된다. 동작에는 문제없으나
        #    공유·인용에 불리하므로 ASCII 경로(newsletter/YYYY-MM-DD.html)로의
        #    전환은 별건으로 남아 있다.
        web_url = f"{SITE_URL}/{quote(filename)}"
        # 수집 건수(len(articles))가 아니라 웹판이 실제로 보여주는 건수를 넘긴다.
        # 채널엔 36건이라 써놓고 열어보니 8건이면 독자가 속았다고 느낀다.
        post_to_channel(nl_data, week_str, min(len(articles), DISPLAY_LIMIT), web_url)

        # 6. 텔레그램 완료 알림 (관리자용 — 발행 성공 확인)
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
