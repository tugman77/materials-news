"""이미지 키워드 오매칭 방지 필터 — 기사자동생성.py·기사검수.py 공용.

배경: 2026-08-01 '두산, SK실트론 2.3조 인수' 기사에 웨이퍼 과자(스트룹와플)
사진이 실렸다. image_keyword는 "semiconductor wafer production"으로 멀쩡했지만
Pixabay가 'wafer'를 과자로 해석해 음식 사진을 반환한 것이 원인이다.
즉 문제는 키워드가 아니라 '검색 결과'에 있었으므로, 방어선을 둘로 나눈다.

  1) refine_keyword()  — 검색 전: 중의적 단어에 업계 한정어를 붙여 질의를 좁힌다.
  2) is_offtopic()     — 검색 후: 이미지 자신의 태그·설명을 보고 음식/생활 사진을 거른다.

두 함수 모두 외부 의존성이 없어 단독 실행으로 자가 검증할 수 있다:
    python3 이미지필터.py
"""

from __future__ import annotations

import re

# ── 1) 검색 전 방어 — 중의적 키워드에 한정어 부착 ─────────────
# term: (이미 이 중 하나가 키워드에 있으면 그대로 둔다, 없으면 붙일 한정어)
# 'wafer'가 대표 사례지만 chip(감자칩)·foil(요리용 호일)·plant(식물)·
# crystal(장식용 크리스털)·mine(지뢰)도 같은 함정이 있다.
_AMBIGUOUS = {
    "wafer":   (("semiconductor", "silicon", "fab", "cleanroom"), "semiconductor"),
    "chip":    (("semiconductor", "silicon", "circuit", "processor"), "semiconductor"),
    "foil":    (("metal", "aluminum", "copper", "battery"), "metal"),
    "plant":   (("chemical", "industrial", "power", "manufacturing", "steel"), "industrial"),
    "crystal": (("silicon", "mineral", "ingot", "growth"), "mineral"),
    "mine":    (("mining", "ore", "quarry", "metal", "rare"), "mining"),
    "battery": (("lithium", "industrial", "manufacturing", "cell", "factory"), "industrial"),
    "cell":    (("battery", "solar", "lithium", "manufacturing"), "battery"),
}

# ── 2) 검색 후 방어 — 이미지 메타데이터 차단어 ────────────────
# 이미지의 태그·alt·설명에 아래 단어가 하나라도 있으면 산업 사진이 아니라고 본다.
# 주의: 'plate'(강판)·'crystal'(실리콘 결정)·'sheet'(강판)처럼 산업 문맥에서
# 정상적으로 쓰이는 단어는 절대 넣지 않는다 — 넣으면 멀쩡한 사진까지 걸러진다.
_BLOCK_FOOD = {
    "waffle", "cookie", "biscuit", "cracker", "dessert", "snack", "chocolate",
    "cake", "pastry", "bakery", "baking", "candy", "sweet", "sweets", "sugar",
    "caramel", "syrup", "honey", "cream", "icecream", "coffee", "tea", "juice",
    "breakfast", "lunch", "dinner", "food", "foods", "meal", "cuisine", "recipe",
    "restaurant", "delicious", "tasty", "edible", "fruit", "vegetable", "bread",
    "cheese", "milk", "chocolates", "confectionery",
}
# 'wafer'/'wafers'는 차단어에 넣지 않는다 — 반도체 웨이퍼 사진의 정상 태그이기도 하다.
# 과자 사진은 함께 붙는 waffle·cookie·dessert 같은 단어로 걸러진다.
_BLOCK_LIFESTYLE = {
    "wedding", "birthday", "party", "baby", "toddler", "pet", "puppy", "kitten",
    "makeup", "cosmetics", "fashion", "lingerie", "yoga", "fitness", "massage",
    "beach", "vacation", "holiday", "christmas", "halloween", "flower", "bouquet",
    "toy", "cartoon", "wallpaper", "romantic", "love",
}
_BLOCKED = _BLOCK_FOOD | _BLOCK_LIFESTYLE

_WORD_RE = re.compile(r"[a-z]+")


def _words(text) -> set:
    """메타데이터 문자열을 소문자 영단어 집합으로 변환."""
    return set(_WORD_RE.findall(str(text or "").lower()))


def refine_keyword(keyword: str, category: str = "") -> str:
    """검색 전 키워드를 업계 문맥으로 좁힌다.

    "semiconductor wafer production"  → 그대로 (이미 semiconductor 있음)
    "wafer production"                → "wafer production semiconductor"
    ""                                → 카테고리 기본 키워드
    """
    kw = (keyword or "").strip()
    if not kw:
        return {
            "반도체소재": "semiconductor wafer fab",
            "희귀금속": "rare earth mining ore",
            "산업재": "industrial factory manufacturing",
            "글로벌": "cargo container port logistics",
        }.get(category, "semiconductor materials industry")

    have = _words(kw)
    extra = []
    for term, (qualifiers, add) in _AMBIGUOUS.items():
        if term in have and not (have & set(qualifiers)) and add not in extra:
            extra.append(add)
    return " ".join([kw] + extra) if extra else kw


def is_offtopic(meta_text) -> bool:
    """이미지 메타데이터(태그·alt·설명)가 음식/생활 사진을 가리키면 True.

    메타데이터가 비어 있으면 판단 근거가 없으므로 통과시킨다(False).
    근거 없는 거부는 picsum 폴백(내용 무관 이미지)을 부르므로 더 나쁘다.
    """
    hit = _words(meta_text) & _BLOCKED
    return bool(hit)


def offtopic_reason(meta_text) -> str:
    """거부 사유 로그용 — 걸린 차단어를 정렬해 반환."""
    return ", ".join(sorted(_words(meta_text) & _BLOCKED))


def pick_relevant(candidates: list, source: str = "") -> str | None:
    """(url, meta_text) 후보 목록에서 오매칭이 아닌 첫 URL을 반환.

    기존 random.choice(후보 1개만 시도) 대비, 음식 사진이 섞여 있어도
    같은 소스 안에서 다음 후보로 넘어갈 수 있다.
    """
    for url, meta in candidates:
        if not url:
            continue
        if is_offtopic(meta):
            print(f"   → 오매칭 이미지 거부 [{source}]: {offtopic_reason(meta)}")
            continue
        return url
    return None


# ── 자가 검증 ────────────────────────────────────────
if __name__ == "__main__":
    cases_kw = [
        ("semiconductor wafer production", "semiconductor wafer production"),
        ("wafer production", "wafer production semiconductor"),
        ("silicon wafer", "silicon wafer"),
        ("chip manufacturing", "chip manufacturing semiconductor"),
        ("aluminum foil rolling", "aluminum foil rolling"),
        ("chemical plant", "chemical plant"),
        ("rare earth mining ore", "rare earth mining ore"),
    ]
    cases_meta = [
        ("waffles, cookies, sweet, dessert", True),    # 2026-08-01 실제 사고 케이스
        ("wafer, semiconductor, silicon, fab", False),
        ("steel plate, factory, industrial", False),   # plate는 차단어 아님
        ("silicon crystal ingot growth", False),       # crystal도 차단어 아님
        ("chocolate cake on a plate", True),
        ("", False),                                   # 메타 없으면 통과
        ("container ship, port, cargo", False),
        ("wafers, silicon, microchip", False),          # 복수형 wafers도 통과해야 함
        ("wafer, waffle, snack", True),                 # 과자 태그가 섞이면 거부
    ]

    fails = 0
    for kw, want in cases_kw:
        got = refine_keyword(kw)
        if got != want:
            fails += 1
            print(f"FAIL refine_keyword({kw!r}) = {got!r}, want {want!r}")
    for meta, want in cases_meta:
        got = is_offtopic(meta)
        if got != want:
            fails += 1
            print(f"FAIL is_offtopic({meta!r}) = {got}, want {want}")

    if refine_keyword("", "희귀금속") != "rare earth mining ore":
        fails += 1
        print("FAIL refine_keyword('', '희귀금속')")

    print(f"{'❌ 실패 ' + str(fails) + '건' if fails else '✅ 전체 통과'} "
          f"— 키워드 {len(cases_kw)}건 / 메타데이터 {len(cases_meta)}건")
