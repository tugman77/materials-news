"""
소재타임스 전문 정보수집 - GitHub Actions 연동용
5개 분야(반도체소재, 디스플레이, 배터리, 희토류, 글로벌규제) 뉴스를 수집하고
sojaetimes/briefing_YYYYMMDD.json 으로 저장한다.

실행: python sojaetimes/collect.py
필요 환경변수(선택):
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET  — 네이버 뉴스 API (없으면 Google RSS만 사용)
"""

import feedparser
import json
import os
import requests
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# ── 네이버 뉴스 API 설정 ────────────────────────────────────────────
NAVER_CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
NAVER_NEWS_URL      = "https://openapi.naver.com/v1/search/news.json"

# 분야별 네이버 검색 키워드
NAVER_TOPICS = [
    # (분야, 키워드)
    ("반도체소재부품장비", "반도체 소재 부품"),
    ("반도체소재부품장비", "EUV 포토레지스트"),
    ("반도체소재부품장비", "반도체 소부장"),
    ("반도체소재부품장비", "첨단 패키징 소재"),
    ("디스플레이소재",   "OLED 소재"),
    ("디스플레이소재",   "디스플레이 소재 부품"),
    ("배터리이차전지",   "양극재 음극재"),
    ("배터리이차전지",   "전고체 배터리 소재"),
    ("배터리이차전지",   "분리막 전해질"),
    ("희토류핵심광물",  "희토류 공급망"),
    ("희토류핵심광물",  "핵심광물 리튬 흑연"),
    ("희토류핵심광물",  "코발트 니켈 수급"),
    ("글로벌규제",      "중국 수출규제 소재"),
    ("글로벌규제",      "반도체 수출통제"),
    ("글로벌규제",      "IRA CHIPS법 소재"),
]

# 분야별 Google News RSS (영어 포함)
GOOGLE_RSS_TOPICS = [
    ("반도체소재부품장비", "https://news.google.com/rss/search?q=반도체+소재+소부장&hl=ko&gl=KR&ceid=KR:ko"),
    ("반도체소재부품장비", "https://news.google.com/rss/search?q=semiconductor+materials+equipment&hl=en&gl=US&ceid=US:en"),
    ("배터리이차전지",    "https://news.google.com/rss/search?q=양극재+음극재+배터리소재&hl=ko&gl=KR&ceid=KR:ko"),
    ("배터리이차전지",    "https://news.google.com/rss/search?q=solid+state+battery+cathode+anode+materials&hl=en&gl=US&ceid=US:en"),
    ("희토류핵심광물",   "https://news.google.com/rss/search?q=희토류+핵심광물+공급망&hl=ko&gl=KR&ceid=KR:ko"),
    ("희토류핵심광물",   "https://news.google.com/rss/search?q=rare+earth+critical+minerals+supply+chain&hl=en&gl=US&ceid=US:en"),
    ("글로벌규제",       "https://news.google.com/rss/search?q=중국+수출규제+반도체+소재&hl=ko&gl=KR&ceid=KR:ko"),
    ("글로벌규제",       "https://news.google.com/rss/search?q=China+export+control+semiconductor+materials&hl=en&gl=US&ceid=US:en"),
    ("글로벌규제",       "https://news.google.com/rss/search?q=CHIPS+Act+IRA+battery+materials&hl=en&gl=US&ceid=US:en"),
    ("디스플레이소재",   "https://news.google.com/rss/search?q=OLED+소재+디스플레이&hl=ko&gl=KR&ceid=KR:ko"),
]


def _empty_topics():
    return {t: [] for t in [
        "반도체소재부품장비", "디스플레이소재",
        "배터리이차전지", "희토류핵심광물", "글로벌규제"
    ]}


def _seen_key(item):
    return item.get("link", "") or item.get("title", "")


def collect_naver(max_per_query=5) -> dict:
    """네이버 뉴스 API로 분야별 수집"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("   네이버 API 키 없음 — Google RSS만 사용")
        return _empty_topics()

    result = _empty_topics()
    seen: set = set()
    headers = {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    for topic, keyword in NAVER_TOPICS:
        try:
            resp = requests.get(
                NAVER_NEWS_URL,
                headers=headers,
                params={"query": keyword, "display": max_per_query, "sort": "date"},
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"   네이버 API 오류 [{keyword}]: {resp.status_code}")
                continue
            items = resp.json().get("items", [])
            for item in items:
                key = item.get("link", item.get("title", ""))
                if key in seen:
                    continue
                seen.add(key)
                result[topic].append({
                    "source":    "네이버뉴스",
                    "lang":      "ko",
                    "topic":     topic,
                    "title":     item.get("title", "").replace("<b>", "").replace("</b>", ""),
                    "summary":   item.get("description", "").replace("<b>", "").replace("</b>", "")[:300],
                    "link":      item.get("link", ""),
                    "published": item.get("pubDate", ""),
                })
        except Exception as e:
            print(f"   네이버 수집 오류 [{keyword}]: {e}")

    return result


def collect_google_rss(max_per_feed=4) -> dict:
    """Google News RSS로 분야별 수집 (한국어 + 영어)"""
    result = _empty_topics()
    seen: set = set()

    for topic, url in GOOGLE_RSS_TOPICS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                key = entry.get("link", entry.get("title", ""))
                if key in seen:
                    continue
                seen.add(key)
                lang = "en" if "ceid=US:en" in url else "ko"
                result[topic].append({
                    "source":    "GoogleNews",
                    "lang":      lang,
                    "topic":     topic,
                    "title":     entry.get("title", ""),
                    "summary":   entry.get("summary", "")[:300],
                    "link":      entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            print(f"   Google RSS 오류 [{url[:60]}]: {e}")

    return result


def merge(a: dict, b: dict) -> dict:
    """두 분야별 dict 합산 (중복 링크 제거)"""
    merged = _empty_topics()
    for topic in merged:
        seen: set = set()
        for item in a.get(topic, []) + b.get(topic, []):
            key = _seen_key(item)
            if key not in seen:
                seen.add(key)
                merged[topic].append(item)
    return merged


def main():
    now = datetime.now(KST)
    date_key = now.strftime("%Y-%m-%d")
    print(f"[sojaetimes collect] {date_key} 수집 시작")

    naver_data  = collect_naver()
    google_data = collect_google_rss()
    topics      = merge(naver_data, google_data)

    total = sum(len(v) for v in topics.values())
    print(f"총 {total}건 수집:")
    for topic, items in topics.items():
        ko = sum(1 for i in items if i["lang"] == "ko")
        en = sum(1 for i in items if i["lang"] == "en")
        print(f"  {topic}: {len(items)}건 (한{ko}/영{en})")

    briefing = {
        "date":          date_key,
        "collected_at":  now.strftime("%Y-%m-%d %H:%M KST"),
        "total_count":   total,
        "topics":        topics,
    }

    os.makedirs("sojaetimes", exist_ok=True)
    out = f"sojaetimes/briefing_{date_key}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {out}")


if __name__ == "__main__":
    main()
