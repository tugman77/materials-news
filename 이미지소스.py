"""외부 이미지 소스 API — 기사자동생성.py·기사검수.py 공용.

배경: 두 파일이 각자 다운로드 로직을 갖고 있었는데, 기사검수.py 쪽에만
Pexels·Pixabay 경로가 없었다. 그래서 검수가 이미지를 다시 받을 때
(누락 보충·중복 교체·키워드 수정) 선택지가 큐레이션 풀과 picsum뿐이었고,
풀이 고갈된 상태에서 picsum이 걸려 'OLED 소재' 기사에 갈매기 사진이 실렸다.

키는 호출 시점에 os.environ에서 읽는다 — 로컬 발행 스크립트가 .env를
source 한 뒤 실행하므로, 모듈 임포트 시점에 고정하면 안 된다.

    python3 이미지소스.py    # 키 등록 상태 + 실제 검색 결과 점검
"""

from __future__ import annotations

import os
import random
import requests

import 이미지필터


def _key(name: str) -> str:
    return os.environ.get(name, "")


def available_sources() -> list:
    """키가 등록된 외부 소스만 우선순위 순으로 반환."""
    order = []
    if _key("UNSPLASH_ACCESS_KEY"):
        order.append("unsplash_api")
    if _key("PEXELS_API_KEY"):
        order.append("pexels")
    if _key("PIXABAY_API_KEY"):
        order.append("pixabay")
    return order


def fetch_unsplash_candidates(keyword: str, count: int = 10) -> list:
    """Unsplash random API에서 오매칭을 거른 후보 URL 목록을 반환.

    한 번 호출에 여러 장을 받아 두면, MD5 중복으로 거부돼도 같은 소스의
    다음 후보로 넘어갈 수 있다 (시그널코리아의 후보 캐시 방식을 공용화한 것).
    """
    api_key = _key("UNSPLASH_ACCESS_KEY")
    if not api_key:
        return []
    try:
        r = requests.get(
            "https://api.unsplash.com/photos/random",
            params={"query": keyword, "orientation": "landscape",
                    "count": count, "client_id": api_key},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        photos = r.json()
        if isinstance(photos, dict):      # count 미반영 응답 방어
            photos = [photos]
        out = []
        for p in photos:
            url = p.get("urls", {}).get("regular")
            meta = f"{p.get('alt_description') or ''} {p.get('description') or ''}"
            if not url:
                continue
            if 이미지필터.is_offtopic(meta):
                print(f"   → 오매칭 이미지 거부 [unsplash_api]: {이미지필터.offtopic_reason(meta)}")
                continue
            out.append(url)
        return out
    except Exception as e:
        print(f"   → Unsplash 오류: {e}")
    return []


def fetch_unsplash(keyword: str) -> str | None:
    """오매칭을 거른 Unsplash 후보 중 첫 장."""
    cands = fetch_unsplash_candidates(keyword)
    return cands[0] if cands else None


def fetch_pexels(keyword: str) -> str | None:
    """Pexels API. alt(사진 설명)로 오매칭을 거른다."""
    api_key = _key("PEXELS_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": keyword, "per_page": 10, "orientation": "landscape"},
            headers={"Authorization": api_key},
            timeout=15,
        )
        if resp.status_code == 200:
            photos = resp.json().get("photos", [])
            random.shuffle(photos)        # 날짜별 변화 유지
            return 이미지필터.pick_relevant(
                [(p.get("src", {}).get("large2x"), p.get("alt")) for p in photos],
                "pexels")
    except Exception as e:
        print(f"   → Pexels 오류: {e}")
    return None


def fetch_pixabay(keyword: str) -> str | None:
    """Pixabay API. tags로 오매칭을 거른다 (2026-08-01 스트룹와플 사고 지점)."""
    api_key = _key("PIXABAY_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://pixabay.com/api/",
            params={"key": api_key, "q": keyword, "image_type": "photo",
                    "orientation": "horizontal", "per_page": 10, "safesearch": "true"},
            timeout=15,
        )
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            random.shuffle(hits)
            return 이미지필터.pick_relevant(
                [(h.get("largeImageURL"), h.get("tags")) for h in hits],
                "pixabay")
    except Exception as e:
        print(f"   → Pixabay 오류: {e}")
    return None


FETCHERS = {
    "unsplash_api": fetch_unsplash,
    "pexels":       fetch_pexels,
    "pixabay":      fetch_pixabay,
}


def fetch(source: str, keyword: str) -> str | None:
    """소스 이름으로 디스패치. 알 수 없는 소스는 None."""
    fn = FETCHERS.get(source)
    return fn(keyword) if fn else None


# ── 점검 ────────────────────────────────────────────
if __name__ == "__main__":
    keyword = os.environ.get("TEST_KEYWORD", "OLED display material manufacturing")
    print("── 키 등록 상태 ──")
    for name in ("UNSPLASH_ACCESS_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY"):
        print(f"  {name:22} {'✅ 있음' if _key(name) else '❌ 없음'}")

    srcs = available_sources()
    print(f"\n── 사용 가능한 외부 소스: {srcs or '없음 — 큐레이션 풀만 쓰게 된다'} ──")
    print(f"   테스트 키워드: {keyword!r}")
    for s in srcs:
        url = fetch(s, keyword)
        print(f"  {s:14} → {(url or '결과 없음')[:90]}")
