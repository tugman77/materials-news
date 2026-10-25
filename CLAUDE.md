# 201 소재타임스 — CLAUDE.md

## 개요
반도체·소재·희귀금속·산업재 전문 뉴스 자동 생성 사이트. 매일 기사 **3개** + 시세 데이터 자동 발행.

- **GitHub 저장소:** `tugman77/materials-news`
- **배포 방식:** GitHub Pages (main 브랜치 / root 디렉터리)
- **AI 모델:** `claude-sonnet-4-6`
- **DB:** 없음 (JSON 파일 기반)

### 발행 하이브리드 — 구독코인 우선 + API코인 백업
1. **로컬 구독코인:** launchd `com.aios.sojaetimes` **KST 03:00** → `소재타임스_로컬발행.command` (수집→생성→검수→기사기획브리핑→push). `LLM_BACKEND=claude_code` 헤드리스.
2. **클라우드 API코인:** Actions `자동기사생성.yml` **KST 06:00**. `articles.json`에 오늘 날짜 있으면 skip → 로컬 성공 시 API코인 미사용.

**백엔드 스위치** (`llm_backend.py`): `LLM_BACKEND=claude_code`(구독) / 미설정=`api`(SDK).

---

## 브랜드 정보

| 항목 | 내용 |
|------|------|
| **제호** | 소재타임스 / MATERIALS TIMES |
| **도메인** | materialtimes.co.kr (비아웹, 만료 2027-07-07) |
| **현재 URL** | tugman77.github.io/materials-news |
| **텔레그램** | @materialtimes (공개 채널) |
| **브랜드 색상** | 블루 `#0057a8` + 레드 `#c8102e` |

브랜드 자산: `python3 scripts/make_logos.py` → `images/`에 logo-rect/square/og-default/favicon 생성.
헤더 로고는 텍스트 조판(`.logo-kr`/`.logo-en`) 유지 — 이미지 교체 금지.

### 텔레그램 발행

| 환경변수 | 목적지 | 용도 |
|---------|--------|------|
| `TELEGRAM_CHAT_ID` | 대표님 개인 | 운영 알림 (검수·실패) |
| `TELEGRAM_CHANNEL_ID` | @materialtimes | 독자용 다이제스트 (정적 페이지 링크) |

일일 3건은 1개 메시지로 묶는다. 관리자 알림을 없애지 말 것.

---

## 파일 구조

```
소재타임스/
├── 기사자동생성.py       ← RSS 수집 → Claude API → JSON 저장 → 채널 발행
├── 기사검수.py           ← 이미지·중복·사실성 검수 + Telegram 보고
├── 기사기획브리핑.py      ← 기사 기획 에이전트 (구독코인, 텔레그램 발송)
├── 정적페이지생성.py      ← archive/*.json → news/*.html + sitemap/rss/robots
├── 이미지필터.py          ← 키워드 한정어 + 태그 기반 오매칭 방지 (시그널코리아 동일)
├── 이미지소스.py          ← Unsplash·Pexels·Pixabay 통합 (시그널코리아 동일)
├── 이미지풀.py            ← 카테고리별 큐레이션 풀 (로컬+원격, LRU)
├── 뉴스레터생성.py        ← 주간 뉴스레터 (금 08:00, newsletter/*.html)
├── llm_backend.py        ← 구독/API 백엔드 스위치
├── articles.json         ← 최신 기사 데이터
├── index.html            ← 홈 (히어로 + 카테고리 + 최신 피드)
├── article.html          ← 기사 본문
├── category.html         ← 카테고리 목록
├── search.html           ← 검색 결과
├── about/advertising/privacy/terms.html
├── archive/              ← 날짜별 JSON (최대 90일)
├── news/                 ← 정적 HTML (크롤러용)
├── images/               ← 기사 이미지 + 브랜드 자산
├── images/pool/          ← 자체 호스팅 풀 이미지
├── sojaetimes/           ← 뉴스 수집 파이프라인 (collect.py, briefing_*.json)
├── scripts/              ← make_logos.py, 풀수집.py
└── .github/workflows/    ← 자동기사생성.yml (06:00), 주간뉴스레터.yml (금 08:00)
```

> **이미지필터.py·이미지소스.py는 시그널코리아와 동일 파일** — 한쪽을 고치면 반대쪽에도 복사.

---

## 기사 생성 구조

1. RSS 수집 (전자신문, 한국경제, 연합뉴스, Google뉴스 4종) → 최대 30건
2. Claude API `save_articles` tool_use로 기사 **3건** 생성 (`ARTICLE_COUNT`)
3. 이미지: Unsplash → Pexels → Pixabay → 큐레이션 풀 → picsum(최종 폴백)
4. `기사검수.py` (이미지·중복·사실성 검수 + Telegram 보고)
5. `articles.json` + `archive/YYYY-MM-DD.json` 저장

- **body**: `array[string]` (10~13 단락, 각 200~300자)
- **max_tokens**: 32,000 / **effort**: `"low"` (생성), `medium` (검수)
- **카테고리**: `반도체소재` / `희귀금속` / `산업재` / `글로벌`
- **기사 필드**: `why_important`(120자, 산업 관점), `sources`(원천 매체 2~5개), `reference_date`(YYYY-MM-DD) — 전부 optional
- **편집국 브리핑**: `editorial_briefing`(문자열) + `editorial_briefing_v2`({headline, points}) — v2 우선

### 건수·중복 관리
`ARTICLE_COUNT` 한 곳에서 정한다(환경변수로 override 가능). 프롬프트·스키마가 참조하므로 **숫자를 다른 곳에 쓰지 말 것.**

중복 판정 `check_duplicate_articles()`:
- **이벤트 쿨다운**: `is_event_key()`로 이벤트어가 든 조합 지문만 통과 (`콩고+붕괴` ✅ / `중국` ❌)
- **키워드 겹침**: 양쪽 지문 3개↑, 겹침 2개↑, 조합 포함 필수
- `_WORD_PATTERNS`에 단어 추가 시 **다른 뜻으로 쓰이는지** 확인 (부상/폭발/인도/사고 전례)

### 대표 사진 캡션
`DEFAULT_IMAGE_CAPTION` = "[자료사진] 기사와 무관한 이미지입니다."
출력 위치: `article.html` + `정적페이지생성.py` — 문구 변경 시 **두 곳 동시** 수정.

---

## 이미지 관리

### 소스 우선순위 (`이미지소스.available_sources()` 한 곳에서 관리)
| 순위 | 소스 | 환경변수 |
|------|------|---------|
| 1 | Unsplash | `UNSPLASH_ACCESS_KEY` |
| 2 | Pexels | `PEXELS_API_KEY` |
| 3 | Pixabay | `PIXABAY_API_KEY` |
| 4 | 큐레이션 풀 | — |
| 5 | picsum | — (내용 무관, **여기까지 오면 실패**) |

### 핵심 규칙
- **오매칭 방지** (`이미지필터.py`): 검색 전 `refine_keyword()`로 한정어 부착, 검색 후 `is_offtopic()`으로 태그 거부. 차단어에 `wafer`/`plate`/`sheet`/`crystal` 넣지 말 것.
- **중복 방지 3중**: ① cross-category 중복 금지 ② run 내 재사용 금지 ③ MD5 바이너리 중복 금지
- **풀 MD5를 영구 해시에 넣지 말 것** — URL이 고정이라 한 번 넣으면 그 photo-ID가 영구 차단, 풀이 서서히 죽는다. 풀은 `_run_hashes`(이번 실행)만 대조.
- 풀: 로컬+원격 78장 (카테고리당 18~20). 추가: `scripts/풀수집.py` (수집→대지→확정 3단계)

---

## UI/UX 규칙

### 페이지·네비게이션
| 파일 | 역할 | URL |
|------|------|-----|
| `index.html` | 홈 | `/` |
| `article.html` | 기사 본문 | `?id=N` / `?date=YYYY-MM-DD&id=N` |
| `category.html` | 카테고리 목록 | `?cat=반도체소재` |
| `search.html` | 검색 결과 | `?q=검색어` |

- **3개 파일(index·article·category) 네비 항목 반드시 동일** — 하나 수정 시 나머지도 함께
- 네비: 전체 / 반도체·소재 / 희귀금속·광물 / 산업재·화학 / 글로벌공급망
- 검색어 하이라이트: `reTest`(i flag, 필터용) / `reHL`(gi flags, 하이라이트용) 분리 (g flag `lastIndex` 오염 방지)

### 중복 노출 차단 (핵심 원칙)
1. 히어로 기사 → 카테고리 섹션·최신 피드에 재노출 금지
2. 카테고리 섹션 기사 → 최신 피드에 재노출 금지
3. 동일 기사가 같은 카테고리 섹션에 2회 이상 노출 금지
4. 모바일에서 카테고리 섹션은 2열(`repeat(2, 1fr)`) 표시

### 쿠팡 파트너스 광고
- **trackingCode**: AF9787280 / **렌더링**: `<iframe>` — 동적 script 주입 금지 (동작 안 함)

| 위치 | iframe | id | CSS |
|------|--------|-----|-----|
| 본문 중간 | `coupang-ad.html` | 970645 | `.coupang-mid-ad` |
| 본문 하단 | `coupang-ad-leaderboard.html` | 1000915 | `.coupang-leader-ad` |
| 사이드바 | 정적 script 쌍 | 970543 | `.sb-coupang` |

---

## 재발 방지 규칙 (과거 버그에서 추출)

| 규칙 | 이유 |
|------|------|
| 헤드리스 cwd를 `~/Desktop` 아래로 돌리지 말 것 | macOS TCC가 launchd에서 무한 블록 |
| 생성 호출은 `effort="low"` 유지 | medium이면 사고 토큰이 32k 상한을 먹어 JSON 잘림 |
| 워크플로에 `permissions: contents: write` 필수 | 없으면 push 403 (주간뉴스레터에서 2주 누락) |
| 워크플로 `git add`에 `news/ sitemap.xml rss.xml robots.txt` 포함 | 빠지면 정적 페이지 전량 404 |
| 풀 이미지 MD5를 `_downloaded_hashes`에 넣지 말 것 | 풀 URL 고정 → 영구 차단 → picsum 폴백 |
| 로컬 python 3.9 — 3.10+ 문법 금지 | `from __future__ import annotations`로 어노테이션만 회피 |
| 프롬프트에 "건수 채우려고 비슷한 사건 늘려 쓰지 말 것" | 자리 비면 모델이 각도 바꿔 중복 생산 |

헤드리스 무응답 진단: 먼저 세션 로그 존재 확인(`~/.claude/projects/`). 없으면 API 전 단계에서 멈춘 것.

---

## 디자인 이력

**2.0 경제신문형 UI (2026-10-22)**: fetch 타임아웃+재시도, 히어로 리드 좌우배치, 카테고리 대표1+텍스트, 요약 박스, 모바일 사이드바 하단 표시.
**3차 메타 강화 (2026-10-25)**: `:root` 토큰 통일, 편집국 브리핑 구조화(v2), "왜 중요한가" 박스, 출처/기준일, 정적 페이지 390건 재생성.

---

## 미완료 배포 항목

- [ ] **materialtimes.co.kr 커스텀 도메인 연결** — 연결 시 `SITE_URL`(`정적페이지생성.py`·`기사자동생성.py`·`뉴스레터생성.py`)과 `robots.txt`도 함께 변경
- [ ] UNSPLASH_ACCESS_KEY Secret 등록 (선택)

---

## 로컬 실행

```bash
cd "소재타임스"
pip install anthropic feedparser requests
python3 기사자동생성.py      # 기사 생성
python3 기사검수.py          # 검수
python3 정적페이지생성.py     # 정적 페이지 재생성
python3 이미지필터.py        # 필터 자가 검증
python3 이미지풀.py          # 풀 장수·중복 점검
```
