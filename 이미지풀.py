"""카테고리별 큐레이션 이미지 풀 — 기사자동생성.py·기사검수.py 공용.

풀은 외부 검색 API가 실패하거나 키가 없을 때 쓰는 안전망이다. 얇으면
picsum(내용 무관 랜덤)까지 떨어진다 — 2026-08-02 'OLED 소재' 기사의 갈매기 사진.

풀은 두 갈래로 구성된다.
  1. 원격(hotlink) — Unsplash 고정 photo-ID. 저장소 용량 0, 대신 외부 의존.
  2. 로컬(self-host) — images/pool/manifest.json + 실제 파일. 링크가 죽지 않는다.
     scripts/풀수집.py 로 후보를 모아 사람이 고른 것만 편입한다(2026-08-02 도입).

이전에는 이 목록이 두 파일에 복붙돼 있어 한쪽만 고쳐지는 사고가 있었다.
여기 한 곳에서만 관리한다.

    python3 이미지풀.py     # 카테고리별 장수 + cross-category 중복 점검
"""

from __future__ import annotations

import hashlib
import json
import os

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(_HERE, "images", "pool", "manifest.json")

# ── 원격 풀 (Unsplash 고정 photo-ID) ──────────────────
# 규칙: 동일 photo-ID가 두 카테고리에 나타나서는 안 된다. validate()가 감지한다.
_UNSPLASH_POOL = {
    "반도체소재": [
        "photo-1518770660439-4636190af475",  # PCB 회로기판 클로즈업 (초록)
        "photo-1591799265444-d66432b91588",  # AMD Ryzen CPU 칩
        "photo-1562408590-e32931084e23",     # PCB 회로기판 (파랑/보라)
        "photo-1597852074816-d933c7d2b988",  # 전자 부품 HDD 내부
        "photo-1581092918056-0c4c3acd3789",  # 전자기기 납땜 작업
        "photo-1451187580459-43490279c0fa",  # 서버 데이터센터 랙
        "photo-1526374965328-7f61d4dc18c5",  # 코드 스크린 (매트릭스)
        "photo-1555680202-c86f0e12f086",     # 컴퓨터 마더보드 내부
        "photo-1558494949-ef010cbdcc31",     # 광섬유 케이블 (파랑/컬러)
    ],
    "희귀금속": [
        "photo-1504917595217-d4dc5ebe6122",  # 금속 용접 불꽃
        "photo-1504328345606-18bbc8c9d7d1",  # 용접사 클로즈업
        "photo-1527515637462-cff94eecc1ac",  # 채석장·광산 암반
        "photo-1531538606174-0f90ff5dce83",  # 광물·금 원석
        "photo-1565793298595-6a879b1d9492",  # 광산 덤프트럭
        "photo-1574482620826-40685ca5ebd2",  # 산업 금속 생산 라인
        "photo-1581094244429-b9b51e78f1d7",  # 건설 현장 항공뷰
        "photo-1578375819537-b95e00c82429",  # 금속 제련 용광로
    ],
    "산업재": [
        "photo-1567789884554-0b844b597180",  # 자동차 공장 로봇
        "photo-1473341304170-971dccb5ac1e",  # 고압 송전탑
        "photo-1541888946425-d81bb19240f5",  # 건설 현장 엔지니어
        "photo-1495576775051-8af0d10f68d1",  # 제철·철강 생산
        "photo-1504711434969-e33886168f5c",  # 제철소 용융 쇳물
        "photo-1565791380713-1756b9a05343",  # 화학 플랜트 항공뷰
        "photo-1582139329536-e7284fece509",  # 건설 크레인 군집
        "photo-1581092160607-ee22621dd758",  # 엔지니어 기계 작업
    ],
    "글로벌": [
        "photo-1494412519320-aa613dfb7738",  # 컨테이너 항구 항공뷰
        "photo-1578575437130-527eed3abbec",  # 컨테이너선 접안 항구
        "photo-1586528116311-ad8dd3c8310d",  # 물류 창고 내부
        "photo-1521790361543-f645cf042ec4",  # 화물 항공기
        "photo-1488229297570-58520851e868",  # 화물선 드론 항공뷰
        "photo-1545193544-312489b2d26c",     # 물류 트럭 주차장
        "photo-1558618666-fcd25c85cd64",     # 글로벌 해운 항로
        "photo-1586769852044-692d6e3703f0",  # 세계 공급망 지도
    ],
}
_UNSPLASH_BASE = "https://images.unsplash.com/{id}?w=800&h=450&fit=crop&auto=format"

_DEFAULT_CATEGORY = "반도체소재"


def _load_local() -> dict:
    """images/pool/manifest.json 적재. 없으면 빈 dict (원격 풀만으로 동작)."""
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def entries(category: str) -> list:
    """카테고리의 풀 항목 목록. 항목은 {"id", "kind", "ref"} 형태.

    kind="remote" → ref는 URL / kind="local" → ref는 파일 절대경로.
    로컬을 앞에 둔다 — 외부 요청 없이 즉시 쓸 수 있고 링크가 죽지 않는다.
    """
    cat = category if category in _UNSPLASH_POOL else _DEFAULT_CATEGORY
    out = []
    for e in _load_local().get(cat, []):
        path = os.path.join(_HERE, "images", os.path.basename(os.path.dirname(e["file"])),
                            os.path.basename(e["file"]))
        if os.path.exists(path):
            out.append({"id": e["id"], "kind": "local", "ref": path})
    for pid in _UNSPLASH_POOL.get(cat, []):
        out.append({"id": pid, "kind": "remote", "ref": _UNSPLASH_BASE.format(id=pid)})
    return out


def pick(category: str, seed_str: str, used_ids: set, last_used: dict) -> dict | None:
    """LRU 선택 — '가장 오래전에 사용(또는 미사용)'한 항목을 우선한다.

    1. 이번 실행에서 아직 안 쓴 id 중에서 고른다 (소진되면 전체 재사용 허용)
    2. 마지막 사용 날짜가 가장 이른 그룹을 우선 → 날짜 간 반복 간격 최대화
    3. 동률이면 시드 해시로 결정 (같은 날 여러 기사에 변화를 준다)
    """
    pool = entries(category)
    if not pool:
        return None
    available = [e for e in pool if e["id"] not in used_ids] or pool
    oldest = min(last_used.get(e["id"], "") for e in available)
    tied = [e for e in available if last_used.get(e["id"], "") == oldest]
    idx = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % len(tied)
    return tied[idx]


def read_bytes(entry: dict, timeout: int = 30) -> bytes | None:
    """풀 항목의 이미지 바이트. 로컬은 파일 읽기, 원격은 HTTP GET."""
    try:
        if entry["kind"] == "local":
            with open(entry["ref"], "rb") as f:
                return f.read()
        resp = requests.get(entry["ref"], timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) >= 1000:
            return resp.content
    except Exception as e:
        print(f"   → 풀 이미지 읽기 실패 [{entry['id']}]: {e}")
    return None


def size(category: str) -> int:
    return len(entries(category))


def validate() -> int:
    """cross-category 중복 id 감지. 문제 건수를 반환한다."""
    seen, bad = {}, 0
    local = _load_local()
    for cat in _UNSPLASH_POOL:
        ids = [e["id"] for e in local.get(cat, [])] + _UNSPLASH_POOL[cat]
        for pid in ids:
            if pid in seen and seen[pid] != cat:
                print(f"⚠️  중복 photo-ID: {pid} — {seen[pid]} ↔ {cat}")
                bad += 1
            seen[pid] = cat
    return bad


if __name__ == "__main__":
    local = _load_local()
    print("── 카테고리별 풀 크기 ──")
    total = 0
    for cat in _UNSPLASH_POOL:
        n_local = len([e for e in entries(cat) if e["kind"] == "local"])
        n_remote = len(_UNSPLASH_POOL[cat])
        total += n_local + n_remote
        flag = "" if n_local + n_remote >= 8 else "  ⚠️ 8장 미만"
        print(f"  {cat:8} 로컬 {n_local:2}장 + 원격 {n_remote}장 = {n_local + n_remote:2}장{flag}")
    print(f"  {'합계':8} {total}장")
    print(f"\n── cross-category 중복 점검 ──\n  {'문제 없음' if validate() == 0 else '위 항목 확인 필요'}")
