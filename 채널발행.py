#!/usr/bin/env python3
"""발행 확정 후 텔레그램 공개 채널(@materialtimes)에 다이제스트를 올린다.

시그널코리아 채널발행.py와 같은 구조다 — 한쪽을 고치면 다른 쪽도 함께 볼 것.

⚠️ **반드시 git push 성공 이후에 실행할 것.** 생성 단계에서 바로 발행하면
   push가 실패했을 때 독자에게는 알렸는데 사이트에는 없는 상태가 된다.

   2026-08-01 실제 사고:
     05:30 로컬 발행 → A세트 생성 → 채널에 A세트 알림 → push 실패
     11:05 클라우드 백업 → B세트 생성 → push 성공 → 사이트는 B세트
   채널 링크가 `article.html?id=N`(배열 인덱스)이라 id=0이 A세트가 아닌
   B세트 0번을 열었다. 제목과 내용이 어긋난 원인이다.

두 가지를 함께 고친다:
  1. push 성공 후에만 발행 → 채널과 사이트가 항상 같은 세트
  2. 링크를 정적 페이지(news/{date}-{i}.html)로 → 재생성돼도 파일이 갱신되고,
     클라이언트 렌더링이 아니라 텔레그램 미리보기 크롤러가 본문을 읽는다

실행: python3 채널발행.py            (articles.json 기준, 오늘자)
      python3 채널발행.py --date 2026-08-01
      TELEGRAM_CHANNEL_ID 미설정 시 조용히 skip (exit 0).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
SITE_URL = "https://tugman77.github.io/materials-news"  # 커스텀 도메인 연결 시 변경
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

CAT_EMOJI = {"반도체소재": "🔵", "희귀금속": "🟠", "산업재": "🟢", "글로벌": "🔴"}


def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(articles: list, date_key: str) -> str:
    label = datetime.strptime(date_key, "%Y-%m-%d").strftime("%Y년 %m월 %d일")
    lines = ["📊 <b>소재타임스</b>",
             f"{label} · 오늘의 기사 {len(articles)}건", ""]
    for i, a in enumerate(articles):
        emoji = CAT_EMOJI.get(a.get("category", ""), "📌")
        summary = esc((a.get("summary", "") or "").strip())
        if len(summary) > 110:
            summary = summary[:110].rstrip() + "…"
                # 배열 위치(i)로 링크한다 — 정적 페이지 파일명이 위치 기준이라 id와 어긋날 수 없다
        link = f"{SITE_URL}/news/{date_key}-{i}.html"
        lines.append(f"{emoji} <b>[{esc(a.get('category',''))}]</b> {esc(a.get('title',''))}")
        if summary:
            lines.append(f"<i>{summary}</i>")
        lines.append(f'<a href="{link}">▸ 기사 보기</a>')
        lines.append("")
    lines.append(f'🔗 <a href="{SITE_URL}/">전체 기사 보기</a>')
    lines.append("#반도체소재 #희귀금속 #산업재 #공급망")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(KST).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("[채널 미설정] TELEGRAM_CHANNEL_ID 없음 — 채널 발행 건너뜀")
        return 0

    path = "articles.json"
    if not os.path.exists(path):
        print(f"❌ {path} 없음")
        return 1
    data = json.load(open(path, encoding="utf-8"))
    articles = data.get("articles", [])
    if not articles:
        print("발행할 기사 없음 — 건너뜀")
        return 0

    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": build_message(articles, args.date),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,   # 기사 5건이면 미리보기 카드가 5개 붙어 지저분하다
        },
        timeout=15,
    )
    if resp.ok:
        print(f"📣 채널 발행 완료 — {len(articles)}건 ({args.date})")
        return 0
    print(f"❌ 채널 발행 실패 {resp.status_code}: {resp.text[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
