"""수집 기사 원문 확보 — 생성 프롬프트의 근거 자료용.

RSS 요약은 비어 있거나(Google News는 잘린 링크 태그뿐) 한두 문장이라, 근거만 쓰라고 하면
기사가 500~600자로 짧아졌다(2026-10-27~). 원문을 읽어 **자료로만** 넘긴다.
문장을 옮겨 쓰지 않게 하는 것은 생성 지시문과 표절 검사(겹침_검사)가 맡는다.

실패는 조용히 넘어간다 — 원문을 못 읽은 항목은 지금처럼 제목·요약만 쓰고, 발행은 멈추지 않는다.
외부 라이브러리 없음(로컬 /usr/bin/python3·클라우드 공통).
"""
from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 10
MIN_LEN = 200       # 이보다 짧으면 본문을 찾지 못한 것으로 본다
MAX_BYTES = 3_000_000
PROMPT_CHARS = 3000  # 프롬프트에 싣는 항목당 원문 상한. 1,500자면 뒷부분 사실이 잘렸다(시험 1차)
# Google News 링크는 받지 않는다. 원문 주소를 풀려면 비공개 경로를 항목마다 호출해야 하는데,
# 시험 중 약 60회 요청에 429 차단을 받았다(2026-11-05). 이 맥은 Google News RSS로 매일 수집하므로
# 차단이 발행 수집까지 번질 수 있다. Google 항목은 제목만 쓰고, 원문은 직접 피드에서 얻는다.
GOOGLE_PREFIX = "https://news.google.com/"
_SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg",
         "button", "select", "iframe", "figure", "figcaption", "template"}
_BLOCK = {"div", "article", "section", "main", "td"}
_NOISE = re.compile(r"무단\s*전재|재배포\s*금지|저작권자|Copyright|All rights reserved|기자\s*[\w.+-]+@|구독하기|좋아요|많이 본 뉴스", re.I)


# ── 본문 추출 ─────────────────────────────────────────
class _Density(HTMLParser):
    """블록별로 직접 담긴 글을 모아 글이 가장 많은 블록을 본문으로 본다."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.skip, self.link = [], 0, 0
        self.blocks = []  # [text 조각 목록, 링크 글자 수]

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag == "a":
            self.link += 1
        elif tag in _BLOCK:
            self.blocks.append([[], 0])
            self.stack.append(len(self.blocks) - 1)
        elif tag in ("p", "br", "li") and self.stack:
            self.blocks[self.stack[-1]][0].append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self.stack:
            self.blocks[self.stack[-1]][0].append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "a":
            self.link = max(0, self.link - 1)
        elif tag in _BLOCK and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.skip or not self.stack or not data.strip():
            return
        b = self.blocks[self.stack[-1]]
        b[0].append(data)
        if self.link:
            b[1] += len(data)


def _clean(text: str) -> str:
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if len(ln) >= 25 and not _NOISE.search(ln))


def _from_jsonld(page: str) -> str:
    best = ""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        for body in re.findall(r'"articleBody"\s*:\s*"((?:[^"\\]|\\.)*)"', m.group(1)):
            try:
                body = json.loads(f'"{body}"')
            except ValueError:
                continue
            if len(body) > len(best):
                best = body
    return _clean(re.sub(r"<[^>]+>", " ", html.unescape(best)).replace(". ", ".\n"))


def extract_text(page: str) -> str:
    """HTML → 본문 글. 못 찾으면 빈 문자열."""
    text = _from_jsonld(page)
    if len(text) >= MIN_LEN:
        return text
    p = _Density()
    try:
        p.feed(page)
    except Exception:
        return ""
    best, score = "", 0
    for parts, link_chars in p.blocks:
        cleaned = _clean("".join(parts))
        s = len(cleaned) - link_chars * 2
        if s > score:
            best, score = cleaned, s
    return best if len(best) >= MIN_LEN else ""


# ── 원문 주소 찾기 ────────────────────────────────────
def _download(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.8"},
                     timeout=TIMEOUT, stream=True)
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return ""
    raw = r.raw.read(MAX_BYTES, decode_content=True)
    head = raw[:4000].decode("ascii", "ignore")
    m = re.search(r'charset=["\']?([\w-]+)', r.headers.get("content-type", "") + " " + head, re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "euc-kr"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def fetch_item(item: dict) -> dict:
    """item에 fulltext·fulltext_url을 채워 돌려준다. 실패하면 fulltext는 빈 문자열."""
    url = item.get("link", "")
    text = ""
    if url and not url.startswith(GOOGLE_PREFIX):
        try:
            text = extract_text(_download(url))
        except Exception:
            text = ""
    item["fulltext"], item["fulltext_url"] = text, url if text else ""
    return item


def clean_summary(summary: str) -> str:
    """RSS 요약의 HTML 제거. Google News 요약은 잘린 링크 태그뿐이라 비게 된다."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*(>|$)", " ", summary or ""))).strip()


def enrich(items: list, workers: int = 8) -> list:
    """목록 전체의 원문을 병렬로 채운다(제자리 수정)."""
    if items:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(fetch_item, items))
    return items


# ── 표절 검사 ─────────────────────────────────────────
_QUOTED = re.compile(r"[\"“][^\"”]*[\"”]|['‘][^'’]*['’]")
_MIN_RUN = 30       # 연속 일치로 보는 글자 수(공백·문장부호 제외)
MIN_SINGLE_SOURCE = 1500  # 출처가 하나일 때 필요한 원문 길이. 짧은 원문 하나로는 베끼기 쉽다
MAX_COVERAGE = 0.25  # 기사 글자 중 원문과 12자 이상 겹치는 비율 상한


def _plain(text: str) -> str:
    return re.sub(r"[\s\W_]", "", text or "")


def 겹침_검사(body_text: str, sources: list, min_len: int = _MIN_RUN) -> list:
    """직접 인용을 뺀 기사 글이 원문과 연속 min_len자 이상 같은 구간 목록."""
    a = _plain(_QUOTED.sub(" ", body_text))
    joined = [_plain(s) for s in sources if s]
    hits, i = [], 0
    while i + min_len <= len(a):
        if any(a[i:i + min_len] in s for s in joined):
            j = i + min_len
            while j < len(a) and any(a[i:j + 1] in s for s in joined):
                j += 1
            hits.append(a[i:j])
            i = j
        else:
            i += 1
    return hits


def 일치율(body_text: str, sources: list, n: int = 12) -> float:
    """직접 인용을 뺀 기사 글자 중 원문과 n자 이상 연속으로 겹치는 비율(0~1)."""
    a = _plain(_QUOTED.sub(" ", body_text))
    joined = [_plain(s) for s in sources if s]
    if len(a) < n or not joined:
        return 0.0
    covered = [False] * len(a)
    for i in range(len(a) - n + 1):
        if any(a[i:i + n] in s for s in joined):
            for k in range(i, i + n):
                covered[k] = True
    return sum(covered) / len(a)


def 베낌_판정(body_text: str, sources: list) -> dict:
    """재작성·보류 판단에 쓰는 요약. copied=True면 그대로 내보내지 않는다."""
    runs, ratio = 겹침_검사(body_text, sources), 일치율(body_text, sources)
    return {"runs": runs, "coverage": round(ratio, 3), "copied": bool(runs) or ratio > MAX_COVERAGE}
