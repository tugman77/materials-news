#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""정적 기사 페이지 생성 — news/YYYY-MM-DD-N.html

article.html은 archive/*.json을 fetch로 읽어 그리는 클라이언트 렌더링이라,
크롤러가 받는 HTML에는 기사 본문이 한 줄도 없다. 검색 색인·애드센스 심사가
모두 이 HTML을 보므로, 발행할 때마다 본문이 통째로 들어간 정적 페이지를
같이 떨궈 크롤러용 정본으로 삼는다.

디자인은 article.html의 <style> 블록을 그대로 추출해 쓰므로, article.html의
CSS를 고치면 다음 발행분부터 자동으로 따라온다(중복 관리 불필요).

사용:
    python 정적페이지생성.py            # 전체 아카이브 재생성(백필)
    python 정적페이지생성.py --date 2026-07-29   # 특정 날짜만
"""

import argparse
import html
import json
import os
import re
import sys

# 커스텀 도메인(materialtimes.co.kr) 연결 후에는 이 값을 바꿔야 한다 —
# sitemap·canonical·OG가 모두 이 절대주소를 쓴다.
SITE_URL = "https://tugman77.github.io/materials-news"
OUT_DIR = "news"
ARCHIVE_DIR = "archive"
BASE = "../"  # news/ 기준 저장소 루트 상대경로

CATS = {
    "반도체소재": ("tag-semi",     "#e8f0fb", "#0057a8"),
    "희귀금속":   ("tag-rare",     "#fdf0f0", "#c8102e"),
    "산업재":     ("tag-industry", "#f0f7ee", "#2e7d32"),
    "글로벌":     ("tag-global",   "#fdf6e3", "#a05000"),
}
NAV = [
    ("index.html", "전체"),
    ("category.html?cat=반도체소재", "반도체·소재"),
    ("category.html?cat=희귀금속", "희귀금속·광물"),
    ("category.html?cat=산업재", "산업재·화학"),
    ("category.html?cat=글로벌", "글로벌공급망"),
]


def article_path(date_key: str, idx: int) -> str:
    """정적 기사 파일의 저장소 루트 기준 경로."""
    return f"{OUT_DIR}/{date_key}-{idx}.html"


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def get_cat(article: dict):
    return CATS.get(article.get("category", ""), CATS["반도체소재"])


def extract_style(path="article.html") -> str:
    """article.html의 <style>...</style>을 통째로 가져온다 — 디자인 단일 소스 유지."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = re.search(r"<style>.*?</style>", f.read(), re.S)
            return m.group(0) if m else ""
    except FileNotFoundError:
        return ""


def paras(article: dict) -> list:
    """body 배열(또는 문자열)을 단락 리스트로 정규화. 없으면 summary를 문장 분리."""
    body = article.get("body")
    if body:
        raw = body if isinstance(body, list) else re.split(r"\n+", str(body))
        return [p.strip() for p in raw if p and str(p).strip()]
    summary = article.get("summary", "")
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()]


def build_page(article: dict, idx: int, all_articles: list, date_key: str,
               briefing: str, style: str) -> str:
    cls, bg, color = get_cat(article)
    title = article.get("title", "")
    summary = article.get("summary", "")
    category = article.get("category", "")
    timestamp = article.get("timestamp", "")
    canonical = f"{SITE_URL}/{article_path(date_key, idx)}"
    desc = summary[:200]

    img_rel = article.get("image_url") or ""
    img_abs = (f"{SITE_URL}/{img_rel.lstrip('/')}" if img_rel
               else f"{SITE_URL}/images/og-default.jpg")

    # ── 본문 (article.html과 동일하게 중간 지점에 광고 삽입) ──
    ps = paras(article)
    mid = max(3, len(ps) // 2)
    ad_block = (
        f'        <iframe class="coupang-mid-ad" src="{BASE}coupang-ad.html" frameborder="0" '
        f'scrolling="no" title="쿠팡 파트너스 광고" loading="lazy"></iframe>\n'
        f'        <div class="coupang-mid-notice">이 포스팅은 쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다.</div>'
    )
    body_html = "\n".join(
        [f"        <p>{esc(p)}</p>" for p in ps[:mid]]
        + ([ad_block] if len(ps) > mid else [])
        + [f"        <p>{esc(p)}</p>" for p in ps[mid:]]
    )

    hero = (f'      <img src="{BASE}{esc(img_rel)}" alt="{esc(title)}" class="art-hero-img">'
            if img_rel else "")

    nav_html = "\n".join(
        f'        <a href="{BASE}{esc(href)}">{esc(label)}</a>' for href, label in NAV)

    # ── 관련 기사: 같은 카테고리 우선 (정적 <a>라 크롤러가 따라간다) ──
    others = ([(i, a) for i, a in enumerate(all_articles)
               if i != idx and a.get("category") == category]
              + [(i, a) for i, a in enumerate(all_articles)
                 if i != idx and a.get("category") != category])[:5]
    if others:
        rel_html = "\n".join(
            f'        <a class="rel-item" href="{esc(os.path.basename(article_path(date_key, i)))}">\n'
            f'          <span class="rel-tag {get_cat(a)[0]}">{esc(a.get("category", ""))}</span>\n'
            f'          <div class="rel-title">{esc(a.get("title", ""))}</div>\n'
            f'        </a>'
            for i, a in others)
    else:
        rel_html = '        <div style="color:#aaa;font-size:13px;">관련 기사가 없습니다.</div>'

    ticker = "  ·  ".join(a.get("title", "") for a in all_articles)
    disp_date = date_key.replace("-", ".")

    ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "description": desc,
        "image": [img_abs],
        "datePublished": f"{date_key}T06:00:00+09:00",
        "dateModified": f"{date_key}T06:00:00+09:00",
        "url": canonical,
        "mainEntityOfPage": canonical,
        "inLanguage": "ko-KR",
        "author": {"@type": "Organization", "name": "소재타임스 소재산업부"},
        "publisher": {
            "@type": "NewsMediaOrganization",
            "name": "소재타임스",
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/images/og-default.jpg"},
        },
    }
    if category:
        ld["articleSection"] = category

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} - 소재타임스</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="소재타임스">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:image" content="{esc(img_abs)}">
<meta property="og:locale" content="ko_KR">
<meta property="article:section" content="{esc(category)}">
<meta property="article:published_time" content="{date_key}T06:00:00+09:00">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{esc(img_abs)}">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
{style}
</head>
<body>

<div class="breaking-bar">
  <div class="inner">
    <span class="breaking-label">속보</span>
    <span class="breaking-text">{esc(ticker)}</span>
  </div>
</div>

<header>
  <div class="header-top">
    <a class="logo-block" href="{BASE}index.html">
      <div class="logo-kr">소재타임스</div>
      <div class="logo-en">MATERIALS TIMES</div>
    </a>
    <div class="header-meta">
      <div class="date">{disp_date}</div>
      <div>반도체 · 첨단소재 · 희귀금속 · 산업재</div>
    </div>
  </div>
  <nav>
    <div class="nav-inner">
{nav_html}
    </div>
  </nav>
</header>

<div class="breadcrumb">
  <div class="bc-inner">
    <a href="{BASE}index.html">홈</a>
    <span class="bc-sep">›</span>
    <a href="{BASE}category.html?cat={esc(category)}">{esc(category)}</a>
    <span class="bc-sep">›</span>
    <span class="bc-current">{esc(title)}</span>
  </div>
</div>

<div class="page-wrap">

  <div class="article-area">
    <article>

      <div class="art-top-meta">
        <span class="rel-tag {cls}">{esc(category)}</span>
        <span class="art-timestamp">{esc(timestamp)}</span>
      </div>

      <h1 class="art-title">{esc(title)}</h1>

      <div class="art-info">
        <span class="art-author">소재산업부 기자</span>
        <span class="info-sep">|</span>
        <span>{disp_date} {esc(timestamp)}</span>
      </div>

{hero}

      <div class="art-body">
{body_html}
      </div>

      <div class="newsletter-cta">
        <div>
          <div class="nl-cta-title">📬 소재인사이트 뉴스레터</div>
          <div class="nl-cta-desc">반도체·희소금속·소재 공급망의 핵심 신호만 골라 이메일로 보내드립니다.<br>30년 현장 전문가가 직접 고릅니다. 무료입니다.</div>
        </div>
        <button class="nl-cta-btn" onclick="openContactModal('뉴스레터 구독 신청')">구독 신청</button>
      </div>

      <iframe class="coupang-leader-ad" src="{BASE}coupang-ad-leaderboard.html" frameborder="0" scrolling="no" title="쿠팡 파트너스 광고" loading="lazy"></iframe>
      <div class="coupang-mid-notice">이 포스팅은 쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다.</div>

      <hr class="art-divider">

      <div class="art-keyword-label">키워드</div>
      <div class="art-tags">
        <span class="art-tag" style="background:{bg};color:{color};">#{esc(category)}</span>
      </div>

      <a class="back-btn" href="{BASE}index.html">← 목록으로 돌아가기</a>

    </article>
  </div>

  <aside class="art-sidebar">

    <div class="sb-box" style="background:#f8f4ef;border-color:#d4c5b0;">
      <div class="sb-title" style="color:#7a5c3a;border-bottom-color:#7a5c3a;">편집국 브리핑</div>
      <div style="font-size:13px;color:#444;line-height:1.75;">{esc(briefing)}</div>
    </div>

    <div class="sb-box">
      <div class="sb-title">다른 기사</div>
{rel_html}
    </div>

    <div class="sb-box">
      <div class="sb-title">관련 기관</div>
      <a class="link-item" href="https://www.motie.go.kr" target="_blank" rel="noopener noreferrer">
        <span class="link-icon">🏛</span><span class="link-name">산업통상자원부</span><span class="link-arrow">↗</span>
      </a>
      <a class="link-item" href="https://www.kims.re.kr" target="_blank" rel="noopener noreferrer">
        <span class="link-icon">🔬</span><span class="link-name">한국재료연구원 KIMS</span><span class="link-arrow">↗</span>
      </a>
      <a class="link-item" href="https://www.komir.or.kr" target="_blank" rel="noopener noreferrer">
        <span class="link-icon">⛏</span><span class="link-name">한국광해광업공단 KOMIR</span><span class="link-arrow">↗</span>
      </a>
    </div>

  </aside>

</div>

<footer>
  <div class="footer-inner">
    <div>
      <div class="footer-logo">소재타임스</div>
      <div class="footer-info" style="margin-top:6px;">
        반도체 · 첨단소재 · 희귀금속 · 산업재 전문 미디어<br>
        발행인: 대표 | 편집국 | 광고문의: <a href="#" onclick="openContactModal('광고 문의');return false;" style="color:rgba(255,255,255,.6);text-decoration:underline;">문의하기</a>
      </div>
    </div>
    <div>
      <div class="footer-links">
        <a href="{BASE}about.html">회사소개</a>
        <a href="{BASE}advertising.html">광고안내</a>
        <a href="{BASE}privacy.html">개인정보처리방침</a>
        <a href="{BASE}terms.html">이용약관</a>
      </div>
      <div style="margin-top:8px; text-align:right;">© 2026 소재타임스. All rights reserved.</div>
    </div>
  </div>
</footer>

<script src="{BASE}contact-modal.js"></script>
</body>
</html>
"""


def generate_for_date(date_key: str, data: dict, style: str) -> int:
    articles = data.get("articles", [])
    briefing = data.get("editorial_briefing", "") or ""
    os.makedirs(OUT_DIR, exist_ok=True)
    for idx, article in enumerate(articles):
        page = build_page(article, idx, articles, date_key, briefing, style)
        with open(article_path(date_key, idx), "w", encoding="utf-8") as f:
            f.write(page)
    return len(articles)


def load_archive_dates() -> list:
    try:
        with open(f"{ARCHIVE_DIR}/index.json", "r", encoding="utf-8") as f:
            return json.load(f).get("dates", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def generate_all(only_date: str = None) -> int:
    """아카이브 전체(또는 지정 날짜)를 정적 페이지로 생성. 생성된 기사 수를 반환."""
    style = extract_style()
    if not style:
        print("⚠️ article.html에서 <style>을 찾지 못함 — 스타일 없이 생성됨")

    dates = [only_date] if only_date else load_archive_dates()
    total = 0
    for dk in dates:
        try:
            with open(f"{ARCHIVE_DIR}/{dk}.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"   건너뜀 {dk}: {type(e).__name__}")
            continue
        n = generate_for_date(dk, data, style)
        total += n
        print(f"   📄 {dk} — {n}건")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="특정 날짜만 생성 (YYYY-MM-DD)")
    args = ap.parse_args()

    print("🏗️  정적 기사 페이지 생성 시작...")
    total = generate_all(args.date)
    print(f"✅ 완료 — {OUT_DIR}/ 에 기사 {total}건")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
