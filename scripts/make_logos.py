#!/usr/bin/env python3
"""소재타임스 브랜드 로고 생성기 (시그널코리아 scripts/make_logos.py 이식·개작).

산출물 (images/):
- logo-rect.png          직사각형 워드마크 MATERIALS TIMES + 소재타임스 — 구글 뉴스 퍼블리셔·사이트용
- logo-square.png        정사각형 워드마크형 아이콘 (MT) — 텔레그램 채널 기본 추천
- logo-square-hex.png    정사각형 심볼형 아이콘 (육각 결정 셀) — 대안

브랜드: 블루 #0057a8(주색) · 레드 #c8102e(강조) · 딥네이비 #1a2b4a
        — index.html에서 실제 사용 중인 값. 시그널코리아(네이비+골드)와 구분된다.

⚠️ 텔레그램은 프로필 사진을 **원형으로 잘라** 표시한다. 정사각형 산출물의
   모서리는 보이지 않으므로 모든 요소를 중앙 원 안(반지름 ~40%)에 둔다.
   모서리에 글자·번호를 넣는 원소기호 타일 디자인이 여기서 안 되는 이유다.
"""
import os
from PIL import Image, ImageDraw, ImageFont

BLUE = (0, 87, 168, 255)      # #0057a8 주색
RED = (200, 16, 46, 255)      # #c8102e 강조
NAVY = (26, 43, 74, 255)      # #1a2b4a 딥네이비
WHITE = (255, 255, 255, 255)

EN_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
EN_BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
KO = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "images"))


def _fit(draw, text, path, usable, start=200, floor=40, index=None):
    """usable 폭에 들어가는 최대 폰트 크기를 찾는다."""
    size = start
    while size > floor:
        f = ImageFont.truetype(path, size, index=index) if index is not None \
            else ImageFont.truetype(path, size)
        if draw.textlength(text, font=f) <= usable:
            return f, size
        size -= 2
    return f, size


def make_rect():
    """워드마크: MATERIALS(블루) TIMES(레드) + 소재타임스 한글 서브라인."""
    W, H = 1600, 400
    margin = 90
    usable = W - 2 * margin
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    parts = [("MATERIALS ", BLUE), ("TIMES", RED)]
    joined = "".join(t for t, _ in parts)
    f, size = _fit(d, joined, EN_BLACK, usable, start=170)
    total = sum(d.textlength(t, font=f) for t, _ in parts)
    asc, desc = f.getmetrics()

    x = (W - total) / 2
    y = 62
    for text, color in parts:
        d.text((x, y), text, font=f, fill=color)
        x += d.textlength(text, font=f)

    # 레드 언더라인 — 사이트 헤더의 강조 규칙을 그대로 가져왔다
    ul_y = y + asc + 16
    ux = (W - int(total)) // 2
    d.rectangle([ux, ul_y, ux + int(total), ul_y + 12], fill=RED)

    # 한글 제호 서브라인
    fk = ImageFont.truetype(KO, 62, index=2)  # AppleSDGothicNeo Bold
    ko = "소재타임스"
    kw = d.textlength(ko, font=fk)
    d.text(((W - kw) / 2, ul_y + 34), ko, font=fk, fill=NAVY)

    img.save(os.path.join(OUT, "logo-rect.png"))
    print(f"생성: images/logo-rect.png {img.size} 영문 {size}pt")


def make_square():
    """텔레그램 채널 아이콘 — 블루 바탕 + 흰 MT + 레드 언더바.

    원형 크롭을 견디도록 요소를 중앙에 몰아 배치한다.
    """
    S = 512
    img = Image.new("RGBA", (S, S), BLUE)
    d = ImageDraw.Draw(img)

    f = ImageFont.truetype(EN_BLACK, 250)
    txt = "MT"
    tw = d.textlength(txt, font=f)
    asc, desc = f.getmetrics()
    x = (S - tw) / 2
    y = (S - (asc + desc)) / 2 - 26
    d.text((x, y), txt, font=f, fill=WHITE)

    # 레드 언더바 (워드마크와 동일한 강조 언어)
    bw = int(tw * 0.86)
    bx = (S - bw) // 2
    by = y + asc + 24
    d.rectangle([bx, by, bx + bw, by + 22], fill=RED)

    img.save(os.path.join(OUT, "logo-square.png"))
    print(f"생성: images/logo-square.png {img.size}")


def make_square_hex():
    """대안 아이콘 — 육각 결정 셀(소재과학 모티프) + 중앙 레드 노드."""
    import math

    S = 512
    img = Image.new("RGBA", (S, S), BLUE)
    d = ImageDraw.Draw(img)
    cx = cy = S / 2

    def hexagon(r, rot=90):
        return [
            (cx + r * math.cos(math.radians(rot + 60 * i)),
             cy + r * math.sin(math.radians(rot + 60 * i)))
            for i in range(6)
        ]

    outer = hexagon(168)
    d.polygon(outer, outline=WHITE, width=22)

    # 꼭짓점 노드 — 결정 격자의 원자
    for px, py in outer:
        d.ellipse([px - 21, py - 21, px + 21, py + 21], fill=WHITE)

    # 중앙 노드는 레드 (브랜드 강조색)
    d.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], fill=RED)

    img.save(os.path.join(OUT, "logo-square-hex.png"))
    print(f"생성: images/logo-square-hex.png {img.size}")


def make_og():
    """홈 공유용 OG 이미지 1200×630 — 카톡·X·페이스북 미리보기.

    기사 정적페이지(news/*.html)는 기사 이미지를 OG로 쓰므로 여기선 홈 전용 기본값만 만든다.
    """
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # 상단 블루 바 + 하단 레드 라인 — 지면 신문 마스트헤드 문법
    d.rectangle([0, 0, W, 96], fill=BLUE)
    d.rectangle([0, 96, W, 106], fill=RED)

    parts = [("MATERIALS ", BLUE), ("TIMES", RED)]
    joined = "".join(t for t, _ in parts)
    f, _ = _fit(d, joined, EN_BLACK, W - 200, start=132)
    total = sum(d.textlength(t, font=f) for t, _ in parts)
    asc, desc = f.getmetrics()
    x = (W - total) / 2
    y = 236
    for text, color in parts:
        d.text((x, y), text, font=f, fill=color)
        x += d.textlength(text, font=f)

    ul_y = y + asc + 14
    ux = (W - int(total)) // 2
    d.rectangle([ux, ul_y, ux + int(total), ul_y + 10], fill=RED)

    fk = ImageFont.truetype(KO, 44, index=2)
    ko = "소재타임스"
    d.text(((W - d.textlength(ko, font=fk)) / 2, ul_y + 32), ko, font=fk, fill=NAVY)

    fs = ImageFont.truetype(KO, 34, index=1)
    tag = "반도체·희귀금속·산업재·글로벌 공급망 전문 뉴스"
    d.text(((W - d.textlength(tag, font=fs)) / 2, ul_y + 106), tag, font=fs, fill=(90, 100, 115))

    img.save(os.path.join(OUT, "og-default.jpg"), quality=92)
    print(f"생성: images/og-default.jpg {img.size}")


def make_favicons():
    """정사각 로고에서 파비콘·터치아이콘 파생. 원본을 리샘플만 하므로 디자인은 하나로 유지된다."""
    src = Image.open(os.path.join(OUT, "logo-square.png")).convert("RGBA")
    for name, size in [("favicon-32.png", 32), ("favicon-180.png", 180)]:
        src.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, name))
        print(f"생성: images/{name} ({size}×{size})")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    make_rect()
    make_square()
    make_square_hex()
    make_og()
    make_favicons()
