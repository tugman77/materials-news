#!/usr/bin/env python3
"""소재타임스 RSS 피드 레지스트리.

기사자동생성.py가 `active_feeds()`로 활성 피드만 가져간다.
피드를 늘리거나 빼려면 이 파일의 status만 바꾸면 되고, 생성 코드는 건드리지 않는다.

status
  active     : 실사용. 헬스체크 통과(최근 14일 내 항목 존재).
  candidate  : 후보. 아직 검증 안 됐거나 신선도가 떨어져 보류.
  dead       : 검증 실패(0건/차단). 기록을 남겨 같은 URL을 다시 시도하지 않게 한다.

헬스체크:  python3 피드목록.py          (활성만)
           python3 피드목록.py --all     (후보·사망 포함 전체 재검증)

⚠️ User-Agent 필수 — Mining.com 등은 기본 UA를 차단한다. 2026-08-02 확인 시
   UA 없이는 0건, 브라우저 UA로는 36건이 정상 수신됐다. collect 쪽에서 USER_AGENT를 쓴다.
"""
from __future__ import annotations

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# group: 수집 다양성을 관리하는 축. 한 그룹이 과반을 넘지 않게 유지하는 게 목표다.
#        국내종합만 늘리면 국내 매체 재가공이 되어 기사가 서로 닮는다.
FEEDS = [
    # ── 국내 종합지 (기존) ──────────────────────────────────────
    {"name": "전자신문", "url": "https://rss.etnews.com/20.xml",
     "group": "국내종합", "lang": "ko", "status": "active",
     "note": "2026-08-02 주소 교체. 기존 /rss/section/ 은 0건이었다(언제부터인지 불명)"},
    {"name": "전자신문 소재부품", "url": "https://rss.etnews.com/Section902.xml",
     "group": "국내종합", "lang": "ko", "status": "active"},
    {"name": "연합뉴스 산업", "url": "https://www.yna.co.kr/rss/economy.xml",
     "group": "국내종합", "lang": "ko", "status": "active"},
    {"name": "이데일리 산업", "url": "https://rss.edaily.co.kr/edaily_news.xml",
     "group": "국내종합", "lang": "ko", "status": "active"},
    {"name": "ZDNet Korea", "url": "https://feeds.feedburner.com/zdkorea",
     "group": "국내종합", "lang": "ko", "status": "active"},

    # ── 국내 전문지 (신규) — 종합지가 안 다루는 소부장 디테일 ────
    {"name": "디일렉", "url": "https://www.thelec.kr/rss/allArticle.xml",
     "group": "국내전문", "lang": "ko", "status": "active",
     "note": "반도체·디스플레이 전문. 공정·소재 디테일이 종합지보다 깊다"},
    {"name": "KIPOST", "url": "https://www.kipost.net/rss/allArticle.xml",
     "group": "국내전문", "lang": "ko", "status": "active",
     "note": "전자부품 전문"},

    # ── 영문 원자재·광물 (신규) — 1차 정보. 국내지는 이걸 받아쓴다 ──
    {"name": "Mining.com", "url": "https://www.mining.com/feed/",
     "group": "영문원자재", "lang": "en", "status": "active",
     "note": "광물·희토류 1차 정보. UA 없으면 0건 반환하므로 USER_AGENT 필수"},
    {"name": "Investing Commodities", "url": "https://www.investing.com/rss/news_11.rss",
     "group": "영문원자재", "lang": "en", "status": "active",
     "note": "원자재 시황·가격"},
    {"name": "Recycling Today", "url": "https://www.recyclingtoday.com/rss/",
     "group": "영문원자재", "lang": "en", "status": "active",
     "note": "도시광산·재활용 금속"},

    # ── 영문 반도체·소재 (신규) ─────────────────────────────────
    {"name": "EE Times", "url": "https://www.eetimes.com/feed/",
     "group": "영문반도체", "lang": "en", "status": "active"},
    {"name": "Semiconductor Digest", "url": "https://www.semiconductor-digest.com/feed/",
     "group": "영문반도체", "lang": "en", "status": "active"},
    {"name": "SemiWiki", "url": "https://semiwiki.com/feed/",
     "group": "영문반도체", "lang": "en", "status": "active"},
    {"name": "AZoM 소재", "url": "https://www.azom.com/syndication.axd?format=rss",
     "group": "영문소재", "lang": "en", "status": "active",
     "note": "소재과학 전문"},

    # ── 중국 (신규) — 소재 수출통제·시세의 진원지 ────────────────
    # 희토류·갈륨·게르마늄·흑연·마그네슘 규제가 전부 중국발이다. 국내지는 이를
    # 며칠 뒤에 받아쓰므로, 중국 창구를 직접 보면 그만큼 앞선다.
    {"name": "SCMP China Tech", "url": "https://www.scmp.com/rss/36/feed",
     "group": "중국", "lang": "en", "status": "active",
     "note": "홍콩 매체. 중국 기술·산업 정책을 영문으로 가장 빠르게 전한다"},
    {"name": "G-SMM 금속시황", "group": "중국", "lang": "en", "status": "active",
     "url": "https://news.google.com/rss/search?q=China+metal+price+SMM+rare+earth&hl=en-US&gl=US&ceid=US:en",
     "note": "상하이금속시장(SMM) 시황 브리핑. 중국 내 금속 가격·재고 원문"},
    {"name": "G-中희토류수출통제", "group": "중국", "lang": "en", "status": "active",
     "url": "https://news.google.com/rss/search?q=China+rare+earth+export+control&hl=en-US&gl=US&ceid=US:en"},
    {"name": "G-中수출통제(한글)", "group": "중국", "lang": "ko", "status": "active",
     "url": "https://news.google.com/rss/search?q=중국+수출통제+광물&hl=ko&gl=KR&ceid=KR:ko"},

    # ── 구글뉴스 쿼리 ───────────────────────────────────────────
    {"name": "G-반도체소재", "group": "구글", "lang": "ko", "status": "active",
     "url": "https://news.google.com/rss/search?q=반도체+소재&hl=ko&gl=KR&ceid=KR:ko"},
    {"name": "G-희귀금속", "group": "구글", "lang": "ko", "status": "active",
     "url": "https://news.google.com/rss/search?q=희귀금속+탄탈륨&hl=ko&gl=KR&ceid=KR:ko"},
    {"name": "G-공급망", "group": "구글", "lang": "ko", "status": "active",
     "url": "https://news.google.com/rss/search?q=반도체+공급망+소재&hl=ko&gl=KR&ceid=KR:ko"},
    {"name": "G-소부장투자", "group": "구글", "lang": "ko", "status": "active",
     "url": "https://news.google.com/rss/search?q=소부장+투자&hl=ko&gl=KR&ceid=KR:ko"},
    {"name": "G-디스플레이소재", "group": "구글", "lang": "ko", "status": "active",
     "url": "https://news.google.com/rss/search?q=디스플레이+소재&hl=ko&gl=KR&ceid=KR:ko"},
    {"name": "G-critical-minerals", "group": "구글", "lang": "en", "status": "active",
     "url": "https://news.google.com/rss/search?q=critical+minerals+supply+chain&hl=en-US&gl=US&ceid=US:en"},

    # ── 후보 (신선도 미달 — 쿼리를 다듬으면 살아날 수 있다) ──────
    {"name": "G-소재수출규제", "group": "구글", "lang": "ko", "status": "candidate",
     "url": "https://news.google.com/rss/search?q=소재+수출규제&hl=ko&gl=KR&ceid=KR:ko",
     "note": "2026-08-02 최신 18일 전 — 쿼리가 좁다. '수출통제'로 바꿔 재시도 검토"},
    {"name": "G-semiconductor-materials", "group": "구글", "lang": "en", "status": "candidate",
     "url": "https://news.google.com/rss/search?q=semiconductor+materials+shortage&hl=en-US&gl=US&ceid=US:en",
     "note": "2026-08-02 최신 34일 전 — 'shortage'가 과도하게 좁힌다"},
    {"name": "Phys.org 소재", "group": "영문소재", "lang": "en", "status": "candidate",
     "url": "https://phys.org/rss-feed/tags/materials+science/",
     "note": "2026-08-02 최신 177일 전 — 태그 피드가 갱신 안 됨"},

    # ── 검증 실패 (같은 URL 재시도 방지용 기록) ──────────────────
    {"name": "Mining Weekly", "url": "https://www.miningweekly.com/rss",
     "group": "영문원자재", "lang": "en", "status": "dead",
     "note": "2026-08-02 UA 유무 관계없이 0건"},
    {"name": "Argus Media", "url": "https://www.argusmedia.com/en/rss/news",
     "group": "영문원자재", "lang": "en", "status": "dead",
     "note": "2026-08-02 0건. 유료 구독 매체라 공개 RSS 없는 듯"},
    {"name": "산업부 보도자료", "url": "https://www.motie.go.kr/rss/motie_news.xml",
     "group": "기관", "lang": "ko", "status": "dead",
     "note": "2026-08-02 0건. 정부 사이트 개편으로 경로 변경 추정 — 실제 RSS 주소 재조사 필요"},
    {"name": "KOTRA 해외시장", "url": "https://dream.kotra.or.kr/kotranews/rss/index.do",
     "group": "기관", "lang": "ko", "status": "dead", "note": "2026-08-02 0건"},
    {"name": "아이뉴스24 산업", "url": "https://www.inews24.com/rss/economy",
     "group": "국내종합", "lang": "ko", "status": "dead", "note": "2026-08-02 0건"},
    {"name": "머니투데이 산업", "url": "https://rss.mt.co.kr/mt_news_industry.xml",
     "group": "국내종합", "lang": "ko", "status": "dead", "note": "2026-08-02 0건"},
    {"name": "서울경제 산업", "url": "https://www.sedaily.com/RSS/S1N1.xml",
     "group": "국내종합", "lang": "ko", "status": "dead", "note": "2026-08-02 0건"},
    {"name": "한국경제", "url": "https://feeds.hankyung.com/economic",
     "group": "국내종합", "lang": "ko", "status": "dead",
     "note": "2026-08-02 0건. /feed/economy·/feed/it·/feed/industry 도 전부 0건 — RSS 폐지 추정"},
    {"name": "China Daily Biz", "url": "http://www.chinadaily.com.cn/rss/bizchina_rss.xml",
     "group": "중국", "lang": "en", "status": "dead",
     "note": "2026-08-02 100건이지만 최신이 3155일 전 — 갱신 중단된 화석 피드"},
    {"name": "Xinhua 영문", "url": "http://www.xinhuanet.com/english/rss/businessrss.xml",
     "group": "중국", "lang": "en", "status": "dead", "note": "2026-08-02 최신 3380일 전"},
    {"name": "Global Times 경제", "url": "https://www.globaltimes.cn/rss/bizchina.xml",
     "group": "중국", "lang": "en", "status": "dead", "note": "2026-08-02 0건"},
    {"name": "Caixin Global", "url": "https://www.caixinglobal.com/rss/",
     "group": "중국", "lang": "en", "status": "dead", "note": "2026-08-02 0건"},
    {"name": "Yicai Global", "url": "https://www.yicaiglobal.com/rss",
     "group": "중국", "lang": "en", "status": "dead", "note": "2026-08-02 0건"},
    {"name": "G-China-graphite-gallium", "group": "중국", "lang": "en", "status": "candidate",
     "url": "https://news.google.com/rss/search?q=China+gallium+germanium+graphite+export&hl=en-US&gl=US&ceid=US:en",
     "note": "2026-08-02 최신 41일 전 — 품목을 3개나 AND로 묶어 너무 좁다"},
]

# 아직 시도해보지 않은 아이디어. 헬스체크 대상은 아니고 다음 확장 때 참고한다.
BACKLOG = [
    "DART 전자공시 — 오픈API 키 필요. 실적·투자 공시를 남보다 먼저 잡는 경로",
    "한국재료연구원(KIMS) 보도자료 — RSS 유무 확인 필요",
    "USGS Mineral Commodity Summaries — 연간 통계, RSS 아닌 PDF",
    "Nikkei Asia / 日経 소재 — 일본 소부장 동향",
    "SMM(상하이금속시장) 영문 — 중국 금속 시세",
]


def active_feeds() -> list[tuple[str, str]]:
    """기사자동생성.py가 쓰는 (이름, URL) 목록."""
    return [(f["name"], f["url"]) for f in FEEDS if f["status"] == "active"]


def group_counts() -> dict:
    counts: dict = {}
    for f in FEEDS:
        if f["status"] == "active":
            counts[f["group"]] = counts.get(f["group"], 0) + 1
    return counts


if __name__ == "__main__":
    import concurrent.futures as cf
    import datetime
    import ssl
    import sys

    import feedparser

    ssl._create_default_https_context = ssl._create_unverified_context
    targets = FEEDS if "--all" in sys.argv else [f for f in FEEDS if f["status"] == "active"]

    def check(f):
        try:
            d = feedparser.parse(f["url"], agent=USER_AGENT)
            n = len(d.entries)
            if not n:
                return f, "❌", "0건", None
            dates = []
            for e in d.entries:
                p = e.get("published_parsed") or e.get("updated_parsed")
                if p:
                    dates.append(datetime.datetime(*p[:6]).date())
            newest = max(dates) if dates else None
            age = (datetime.date.today() - newest).days if newest else None
            mark = "✅" if age is None or age <= 14 else "⚠️"
            return f, mark, f"{n}건", age
        except Exception as e:
            return f, "❌", type(e).__name__, None

    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(check, targets))

    bad = 0
    for grp in sorted({f["group"] for f in targets}):
        print(f"\n── {grp} ──")
        for f, mark, cnt, age in [r for r in results if r[0]["group"] == grp]:
            if mark != "✅":
                bad += 1
            aged = f"최신 {age}일 전" if age is not None else ""
            print(f"  {mark} [{f['status']:9}] {f['name']:24} {cnt:>6}  {aged}")

    print(f"\n활성 피드 {len(active_feeds())}개 · 그룹별 {group_counts()}")
    print(f"이상 {bad}건" if bad else "\n전부 정상 ✅")
    sys.exit(1 if bad else 0)
