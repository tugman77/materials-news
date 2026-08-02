"""큐레이션 풀 후보 수집기 — 카테고리별로 후보 이미지를 모아 사람이 고르게 한다.

풀은 API 키가 없거나 외부 검색이 실패했을 때 쓰는 최종 안전망이다. 얇으면
picsum(내용 무관 랜덤)으로 떨어지므로 (2026-08-02 갈매기 사고) 두껍게 유지한다.

    export PEXELS_API_KEY=... PIXABAY_API_KEY=...
    python3 scripts/풀수집.py 수집          # 후보 → images/pool/_후보/
    python3 scripts/풀수집.py 대지          # 카테고리별 컨택트시트 생성(눈으로 고르기용)
    python3 scripts/풀수집.py 확정 반도체소재 3,7,11,12   # 고른 번호만 풀에 편입

수집 단계에서 이미지필터로 음식·생활 사진을 미리 걸러내지만, 최종 선별은 사람이 한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import 이미지필터   # noqa: E402

ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POOL_DIR = os.path.join(ROOT, "images", "pool")
CAND_DIR = os.path.join(POOL_DIR, "_후보")
MANIFEST = os.path.join(POOL_DIR, "manifest.json")

# 카테고리별 검색어. 기존 풀의 공백을 메우는 데 초점을 뒀다 —
# 특히 산업재에 전자재료·디스플레이 계열이 하나도 없어 OLED 기사에 맞는 사진이 없었다.
QUERIES = {
    "반도체소재": [
        "semiconductor wafer fab", "cleanroom semiconductor engineer",
        "microchip circuit board macro", "silicon wafer manufacturing",
        "chip production line factory", "OLED display panel technology",
        "electronic components laboratory",
    ],
    "희귀금속": [
        "rare earth mining site", "ore processing plant",
        "metal refinery furnace", "lithium mine aerial",
        "metal ingot stack industry", "mining haul truck quarry",
        "smelting molten metal",
    ],
    "산업재": [
        "chemical plant industrial", "steel mill production line",
        "factory automation robot arm", "industrial research laboratory",
        "battery manufacturing plant", "display panel factory cleanroom",
        "petrochemical refinery night",
    ],
    "글로벌": [
        "container port aerial view", "cargo ship ocean logistics",
        "freight train container", "logistics warehouse interior",
        "port crane loading containers", "air cargo freight terminal",
        "global shipping trade",
    ],
}

SLUG = {"반도체소재": "semi", "희귀금속": "metal", "산업재": "indus", "글로벌": "global"}


def _search_pexels(q: str, n: int = 6) -> list:
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         params={"query": q, "per_page": n, "orientation": "landscape"},
                         headers={"Authorization": key}, timeout=20)
        if r.status_code != 200:
            return []
        out = []
        for p in r.json().get("photos", []):
            out.append({"url": p.get("src", {}).get("large2x"), "meta": p.get("alt") or "",
                        "source": "pexels", "id": str(p.get("id")),
                        "credit": p.get("photographer") or "", "query": q})
        return out
    except Exception as e:
        print(f"   Pexels 오류 [{q}]: {e}")
        return []


def _search_pixabay(q: str, n: int = 6) -> list:
    key = os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get("https://pixabay.com/api/",
                         params={"key": key, "q": q, "image_type": "photo",
                                 "orientation": "horizontal", "per_page": n,
                                 "safesearch": "true"}, timeout=20)
        if r.status_code != 200:
            return []
        out = []
        for h in r.json().get("hits", []):
            out.append({"url": h.get("largeImageURL"), "meta": h.get("tags") or "",
                        "source": "pixabay", "id": str(h.get("id")),
                        "credit": h.get("user") or "", "query": q})
        return out
    except Exception as e:
        print(f"   Pixabay 오류 [{q}]: {e}")
        return []


def 수집(per_query: int = 4):
    """카테고리별 후보를 내려받아 images/pool/_후보/<slug>_NN.jpg 로 저장."""
    os.makedirs(CAND_DIR, exist_ok=True)
    existing = _manifest_hashes()
    index = {}
    for cat, queries in QUERIES.items():
        seen_hash, picked = set(existing), []
        for q in queries:
            for cand in _search_pexels(q, per_query) + _search_pixabay(q, per_query):
                if not cand["url"]:
                    continue
                if 이미지필터.is_offtopic(cand["meta"]):
                    continue
                try:
                    content = requests.get(cand["url"], timeout=30).content
                except Exception:
                    continue
                if len(content) < 20000:          # 너무 작은 이미지는 헤더용으로 부적합
                    continue
                h = hashlib.md5(content).hexdigest()
                if h in seen_hash:
                    continue
                seen_hash.add(h)
                n = len(picked)
                fn = f"{SLUG[cat]}_{n:02d}.jpg"
                with open(os.path.join(CAND_DIR, fn), "wb") as f:
                    f.write(content)
                cand.update({"file": fn, "md5": h, "no": n})
                picked.append(cand)
        index[cat] = picked
        print(f"  {cat:8} 후보 {len(picked)}장")
    with open(os.path.join(CAND_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"\n후보 저장: {CAND_DIR}")


def 대지(cols: int = 4, thumb: int = 320):
    """카테고리별 컨택트시트(번호 격자) 생성 — 한 장만 보고 고를 수 있게."""
    from PIL import Image, ImageDraw
    index = json.load(open(os.path.join(CAND_DIR, "index.json"), encoding="utf-8"))
    for cat, items in index.items():
        if not items:
            continue
        rows = (len(items) + cols - 1) // cols
        th = int(thumb * 9 / 16)
        sheet = Image.new("RGB", (cols * thumb, rows * (th + 22)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, it in enumerate(items):
            try:
                im = Image.open(os.path.join(CAND_DIR, it["file"])).convert("RGB")
            except Exception:
                continue
            im = im.resize((thumb, th), Image.LANCZOS)
            x, y = (i % cols) * thumb, (i // cols) * (th + 22)
            sheet.paste(im, (x, y))
            draw.text((x + 4, y + th + 4), f"{it['no']}  {it['query'][:34]}", fill="black")
        out = os.path.join(CAND_DIR, f"대지_{SLUG[cat]}.jpg")
        sheet.save(out, quality=88)
        print(f"  {cat:8} → {out}  ({len(items)}장)")


def _manifest_hashes() -> set:
    try:
        m = json.load(open(MANIFEST, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    return {e.get("md5") for cat in m.values() for e in cat if e.get("md5")}


def 확정(cat: str, numbers: str):
    """고른 번호를 images/pool/ 로 옮기고 manifest.json에 등록."""
    os.makedirs(POOL_DIR, exist_ok=True)
    index = json.load(open(os.path.join(CAND_DIR, "index.json"), encoding="utf-8"))
    picks = {int(x) for x in numbers.replace(" ", "").split(",") if x != ""}
    try:
        manifest = json.load(open(MANIFEST, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        manifest = {}
    entries = manifest.setdefault(cat, [])
    have = {e["md5"] for e in entries}
    added = 0
    for it in index.get(cat, []):
        if it["no"] not in picks or it["md5"] in have:
            continue
        dst_name = f"{SLUG[cat]}_{it['source']}_{it['id']}.jpg"
        with open(os.path.join(CAND_DIR, it["file"]), "rb") as src, \
             open(os.path.join(POOL_DIR, dst_name), "wb") as dst:
            dst.write(src.read())
        entries.append({"id": f"{it['source']}-{it['id']}", "file": f"pool/{dst_name}",
                        "md5": it["md5"], "source": it["source"],
                        "credit": it["credit"], "desc": it["query"]})
        added += 1
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"{cat}: {added}장 편입 → 누적 {len(entries)}장")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "수집"
    if cmd == "수집":
        수집()
    elif cmd == "대지":
        대지()
    elif cmd == "확정":
        확정(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
