"""검수 게이트 — 검수에서 심각한 문제가 나온 기사를 공개(push) 전에 뺀다.

2026-10-14 컨트롤타워 검수관 체계 도입. 기사검수.py가 Claude 검수 직후 호출한다.
소재타임스·시그널코리아에 같은 파일이 있다 (고치면 둘 다 고친다).

보류 기준 (컨트롤타워/검수기준.md 의 뉴스판):
  - Claude 검수 status == "fail", 또는 신뢰도(trust_score) 2 이하
  - 투자 권유 표현 (매수 추천 등) — 뉴스는 종목 추천을 하지 않는다
보류된 기사는 사이트·채널에 나가지 않는다. 남은 기사로 articles.json·정적 페이지·sitemap을 다시 만든다.
전부 보류면 종료코드 3 + GITHUB_OUTPUT all_held=true → 그날은 push하지 않는다
(로컬이면 클라우드 백업이 새로 만들어 다시 검수한다).

기록: REVIEW_LOG_DIR(로컬 발행 스크립트가 컨트롤타워/검수기록 으로 지정)이 있으면
  YYYY-MM-DD.jsonl 에 판정을, 보류/<채널>_<날짜>.json 에 보류 기사 원문을 남긴다.
"""

import html
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

HOLD_PHRASES = ["매수 추천", "매수를 추천", "매도 추천", "매도를 추천", "적극 매수", "지금 사야", "사두면 오른", "투자를 권유", "투자를 추천"]


def esc(s) -> str:
    """텔레그램 HTML 모드용 — 제목의 < & 가 메시지를 깨뜨리지 않게"""
    return html.escape(str(s), quote=False)


def _text(a: dict) -> str:
    parts = [a.get("title", ""), a.get("summary", "")]
    for k in ("body", "fact", "meaning", "winner", "loser", "action"):
        v = a.get(k)
        if v:
            parts.append(" ".join(map(str, v)) if isinstance(v, list) else str(v))
    return " ".join(parts)


def decide(articles: list, review_map: dict) -> dict:
    """기사 id → 보류 사유 목록. 보류할 기사만 담는다."""
    holds = {}
    for a in articles:
        r = review_map.get(a.get("id")) or {}
        why = []
        score = r.get("trust_score")
        if r.get("status") == "fail":
            why.append(f"검수 fail (신뢰도 {score}/5) {r.get('notes', '')}".strip())
        elif isinstance(score, int) and score <= 2:
            why.append(f"신뢰도 낮음 {score}/5 {r.get('notes', '')}".strip())
        hit = [p for p in HOLD_PHRASES if p in _text(a)]
        if hit:
            why.append("투자 권유 표현: " + ", ".join(hit))
        if why:
            holds[a.get("id")] = why
    return holds


def record(channel: str, articles: list, holds: dict, review_map: dict) -> None:
    d = os.environ.get("REVIEW_LOG_DIR")
    if not d:
        return
    now = datetime.now(KST)
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{now:%Y-%m-%d}.jsonl"), "a", encoding="utf-8") as f:
            for a in articles:
                r = review_map.get(a.get("id")) or {}
                held = a.get("id") in holds
                f.write(json.dumps({
                    "at": now.isoformat(), "channel": channel, "id": a.get("id"), "title": a.get("title", ""),
                    "verdict": "hold" if held else "pass", "action": "보류" if held else "공개",
                    "by": "기사검수", "score": r.get("trust_score"),
                    "reasons": holds.get(a.get("id")) or ([r.get("notes")] if r.get("notes") else []),
                    "uncertain": r.get("suspicious_claims", []),
                }, ensure_ascii=False) + "\n")
        if holds:
            os.makedirs(os.path.join(d, "보류"), exist_ok=True)
            with open(os.path.join(d, "보류", f"{channel}_{now:%Y-%m-%d}.json"), "w", encoding="utf-8") as f:
                json.dump([dict(a, 보류사유=holds[a.get("id")]) for a in articles if a.get("id") in holds],
                          f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"⚠️ 검수 기록 실패(발행에는 영향 없음): {e}")


def set_output(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def split(articles: list, holds: dict):
    """(남길 기사, 보류 기사). 남길 기사는 id를 0부터 다시 매기고, 대표 기사가 빠졌으면 첫 기사를 대표로."""
    kept = [a for a in articles if a.get("id") not in holds]
    held = [a for a in articles if a.get("id") in holds]
    for i, a in enumerate(kept):
        a["id"] = i
    if kept and not any(a.get("is_featured") for a in kept):
        kept[0]["is_featured"] = True
    return kept, held


def remove_static(date_key: str) -> None:
    """오늘 날짜 정적 페이지·카드 삭제 — 기사 수가 줄면 마지막 번호 파일이 옛 기사로 남는다."""
    import glob
    for pat in (f"news/{date_key}-*.html", f"cards/{date_key}-*.png"):
        for p in glob.glob(pat):
            os.remove(p)
