"""수집 기사 최신성 필터 — 시그널코리아·소재타임스 공용 (한쪽을 고치면 다른 쪽에도 복사).

2026-10-26 도입. Google News 검색 RSS는 기간 조건이 없으면 관련도순이라 몇 달 전 기사가
섞인다(시그널 10-26 수집 38건 중 30일 초과 22건, 최고 221일). 그 결과 3월·6월 소식을
오늘 기사로 썼다. 검색 주소에 when:7d를 붙이고, 발행일이 7일을 넘은 항목은 버린다.
발행일을 알 수 없는 항목은 판단할 근거가 없으므로 남긴다.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

MAX_AGE_DAYS = 7
KST = timezone(timedelta(hours=9))


def recent_url(url: str) -> str:
    """Google News 검색 RSS 주소에 기간 조건을 붙인다. 이미 있으면 그대로."""
    if "news.google.com/rss/search" not in url or "when:" in url:
        return url
    if "&" in url:
        head, tail = url.split("&", 1)
        return f"{head}+when:{MAX_AGE_DAYS}d&{tail}"
    return f"{url}+when:{MAX_AGE_DAYS}d"


def entry_date(entry) -> datetime | None:
    """feedparser 항목의 발행 시각(UTC). 없으면 None."""
    tm = entry.get("published_parsed") or entry.get("updated_parsed")
    if tm:
        return datetime.fromtimestamp(calendar.timegm(tm), tz=timezone.utc)
    return parse_date(entry.get("published") or entry.get("updated") or "")


def parse_date(text: str) -> datetime | None:
    """RFC 822(RSS·네이버 pubDate) 또는 ISO 형식 문자열 → datetime. 실패하면 None."""
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_fresh(dt: datetime | None) -> bool:
    return dt is None or datetime.now(timezone.utc) - dt <= timedelta(days=MAX_AGE_DAYS)


def date_label(dt: datetime | None) -> str:
    """KST 기준 YYYY-MM-DD. 날짜를 모르면 빈 문자열."""
    return dt.astimezone(KST).strftime("%Y-%m-%d") if dt else ""
