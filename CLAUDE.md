# 201 소재경제신문 — CLAUDE.md

## 개요
반도체·소재·희귀금속·산업재 전문 뉴스 자동 생성 사이트.
매일 KST 06:00 GitHub Actions로 기사 5개 + 시세 데이터 자동 생성.

- **GitHub 저장소:** `tugman77/materials-news`
- **배포 방식:** GitHub Pages (main 브랜치 / root 디렉터리)
- **AI 모델:** `claude-sonnet-4-6`
- **DB:** 없음 (JSON 파일 기반)

---

## 파일 구조

```
201 News_Material industry/
├── 기사자동생성.py        ← 메인 스크립트 (RSS 수집 → Claude API → JSON 저장)
├── 기사검수.py            ← 이미지·중복·사실성 검수 + Telegram 보고
├── articles.json          ← 최신 기사 데이터 (index.html이 읽음)
├── index.html             ← 메인 뉴스 페이지 (홈)
├── article.html           ← 기사 본문 페이지
├── category.html          ← 카테고리별 기사 목록 페이지 (URL param: ?cat=...)
├── images/                ← 기사 이미지 (YYYY-MM-DD_article_N.jpg)
├── archive/               ← 날짜별 기사 아카이브
│   ├── index.json         ← 날짜 목록 (최대 90일)
│   └── YYYY-MM-DD.json    ← 날짜별 기사 데이터
└── .github/workflows/
    └── 자동기사생성.yml   ← GitHub Actions (매일 UTC 21:00 = KST 06:00)
```

---

## 기사 생성 구조

### 흐름
1. RSS 수집 (전자신문, 한국경제, 연합뉴스, Google뉴스 4종) → 최대 30건
2. Claude API `save_articles` tool_use로 기사 5개 생성
3. 이미지 다운로드 → `images/YYYY-MM-DD_article_N.jpg` (날짜 포함, 중복 방지)
   - 1차: Unsplash API (`UNSPLASH_ACCESS_KEY` 있을 때, 내용 연관도 최고)
   - 2차: loremflickr / 3차: picsum 폴백
4. `기사검수.py` 실행 (이미지 누락·중복 감지 + Claude 사실성 검수 + Telegram 보고)
5. `articles.json` + `archive/YYYY-MM-DD.json` 저장

### 기사 포맷 (2026-06-25 기준)
- **body**: 단락 배열 (`array[string]`, 10~13개 항목, 각 200~300자)
- **max_tokens**: 32,000
- **카테고리**: `반도체소재` / `희귀금속` / `산업재` / `글로벌`

---

## 중요 버그 이력 및 해결책

### [수정됨] tool_use double-serialization (2026-06-25)
- **증상**: `json.decoder.JSONDecodeError` — body 안의 따옴표/줄바꿈 이스케이프 실패
- **원인**: 프롬프트의 "JSON 형식 반환" 지시가 tool_use와 충돌 → Claude가 배열을 JSON 문자열로 감싸서 반환
- **해결**: 프롬프트 지시 제거 + body를 `string` → `array[string]`으로 변경

### [수정됨] max_tokens 부족 (2026-06-25)
- **증상**: 응답 잘림으로 tool_use JSON 불완전
- **원인**: 5개 기사 × 2500~3500자 ≈ 20,000+ 토큰 → 16,000 한도 초과
- **해결**: max_tokens=32,000으로 증가

### [수정됨] 유사 주제 반복 (2026-06-27)
- **증상**: 석화업계·탄탈럼 등 같은 주제가 2~3일 연속 등장
- **원인**: Claude가 매일 독립적으로 기사를 생성해 이전 주제를 인식 못함
- **해결**: `load_recent_topics(days=3)`로 최근 3일 기사 목록을 추출 → 프롬프트의 `[최근 N일간 이미 다룬 주제 — 반드시 피할 것]` 섹션으로 전달
- **중복 판단 기준**: 동일 기업명 주인공 / 동일 소재·물질명 / 동일 정책·규제 / 동일 이슈 흐름
- **허용 예외**: 동일 소재라도 완전히 다른 각도(예: 공급망 이슈 → 기술 개발 동향)는 허용

### [수정됨] 이미지 중복·불일치 (2026-06-27)
- **증상**: 매일 `images/article_0~4.jpg`를 덮어씌워 아카이브 기사들이 오늘 이미지를 공유, loremflickr/picsum 이미지가 기사 내용과 불일치
- **해결**: 파일명에 날짜 포함 `images/YYYY-MM-DD_article_N.jpg` → 날짜별 독립 이미지 유지
- **해결**: Unsplash API 우선 사용 → 기사 키워드와 시각적으로 연관된 고품질 이미지
- **해결**: `기사검수.py`에 MD5 해시 기반 중복 감지 → 중복 시 자동 재다운로드

### [주의] 이미지 경로
- `article.html`은 `article.html?id=N` 형식으로 기사 접근
- 아카이브 기사는 `article.html?date=YYYY-MM-DD&id=N` 형식
- 이미지 경로는 `articles.json`의 `image_url` 필드 값 사용 (상대 경로, GitHub Pages root 기준 정상 동작)

---

## 이미지 관리 규칙

### 소스 우선순위
| 순위 | 소스 | 환경변수 | 특징 |
|------|------|---------|------|
| 1 | Unsplash API | `UNSPLASH_ACCESS_KEY` | 키워드 매칭, 최고 품질 |
| 2 | Pexels API | `PEXELS_API_KEY` | 키워드 매칭, 고품질 무료 |
| 3 | Pixabay API | `PIXABAY_API_KEY` | 키워드 매칭, 대용량 DB |
| 4 | Unsplash 큐레이션 풀 | 불필요 | 카테고리 연관, 항상 사용 가능 |
| 5 | picsum | 불필요 | 최종 폴백, 내용 무관 |

### 중복 방지 규칙 (3중 보호)
1. **Cross-category 중복 금지** — `_UNSPLASH_POOL` 각 photo-ID는 단일 카테고리에만 등록. `_validate_pool()` 함수가 실행마다 자동 감지.
2. **Run 내 재사용 금지** — `_used_photo_ids` set: 동일 실행에서 선택된 photo-ID는 재선택 안 함.
3. **바이너리 중복 금지** — `_downloaded_hashes` set: 동일 MD5 파일은 저장 거부 후 다음 소스 시도.

### 풀 관리 원칙
- 카테고리당 최소 8개 이상 유지 (5기사/일 + 여유분)
- 새 ID 추가 전 전체 풀 검색으로 중복 확인
- `기사자동생성.py`와 `기사검수.py` 두 파일의 풀을 항상 동일하게 유지
- 파일명: `images/YYYY-MM-DD_article_N.jpg` — 날짜 포함으로 날짜 간 덮어쓰기 방지

### API 키 등록 위치
- 로컬: `.env` 또는 `export` 명령
- GitHub Actions: Settings → Secrets → `PEXELS_API_KEY`, `PIXABAY_API_KEY`

---

## 로컬 실행

```bash
cd "200 News_manager/201 News_Material industry"
export ANTHROPIC_API_KEY="sk-ant-..."
export UNSPLASH_ACCESS_KEY="..."  # 선택: 없으면 loremflickr 사용
pip install anthropic feedparser requests
python 기사자동생성.py
python 기사검수.py  # 이미지 중복·불일치 검수 + 텔레그램 보고
```

---

## 아카이브 시스템

- 매 실행 시 `archive/YYYY-MM-DD.json` 저장
- `archive/index.json`에 날짜 목록 유지 (최대 90일, 내림차순)
- 과거 기사 URL: `article.html?date=2026-06-25&id=0`

## UI/UX 설계 규칙 (2026-06-27 확립)

### 페이지 구조
| 파일 | 역할 | URL 형식 |
|------|------|---------|
| `index.html` | 홈 (히어로 + 카테고리 섹션 + 최신 피드) | `/` |
| `category.html` | 카테고리별 기사 목록 | `category.html?cat=반도체소재` |
| `article.html` | 기사 본문 | `article.html?id=N` / `article.html?date=YYYY-MM-DD&id=N` |

### 네비게이션 규칙
- **3개 파일(index·article·category) 네비 항목 반드시 동일** — 하나 수정 시 나머지도 함께 수정
- 카테고리 링크: `href="category.html?cat=반도체소재"` (직접 링크, JS onclick 방식 금지)
- 전체 링크: `href="index.html"`
- 네비 항목: 전체 / 반도체·소재 / 희귀금속·광물 / 산업재·화학 / 글로벌공급망
- 현재 페이지에 해당하는 항목에 `.active` 클래스 → 빨간 밑줄 표시
- 검색창: 모바일(640px 이하)에서 `display:none`

### 홈(index.html) 레이아웃 규칙
**히어로 섹션**
- 그리드: `3fr 2fr`, 3행 (`grid-template-rows: repeat(3, auto)`)
- 좌측(hero-main): `grid-row: 1/4`, `display:flex; flex-direction:column` → 이미지가 `flex:1`로 남은 높이를 채워 빈 공간 없음
- 우측: 사이드 카드 **3개** (오늘 기사 featured 1 + side 3 = 4기사 활용)
- 히어로에 사용된 기사 인덱스는 `heroIndices` Set에 등록

**카테고리 섹션** (반도체·소재 / 희귀금속·광물 / 산업재·화학 / 글로벌공급망)
- 최대 **6기사** 표시 (3열 × 2행)
- **히어로 기사 제외**: `!(r.date === todayISO && heroIndices.has(r.idx))` 조건 필수
- "더보기 →": `category.html?cat=...` 링크

**최신 기사 피드**
- **히어로 기사 제외** 동일 조건 적용
- 카테고리 필터 버튼으로 필터링 가능
- 초기 로드: 오늘 + 최근 2일치 아카이브 자동 로드 → 이후 버튼으로 추가 로드

> ⚠️ **핵심 원칙**: 히어로에 표시된 기사는 홈 어느 섹션에도 중복 노출 금지

### 카테고리 페이지(category.html) 규칙
- URL `?cat=` 파라미터로 카테고리 판별 (반도체소재 / 희귀금속 / 산업재 / 글로벌)
- 브레드크럼: `홈 > [카테고리명]` — 현재 위치 명확히 표시
- 카테고리 배너: 이름 + 설명 + 총 기사 수
- 그리드: 3열 (태블릿 2열, 모바일 1열), 9기사씩 페이지네이션
- 히어로 기사 중복 제외 불필요 (category.html은 홈과 독립적)

### 관련 뉴스 (article.html)
- 키워드 매칭 점수 threshold: **1.5**
- 카테고리 일치 보너스: **1.0**
- 자기 자신 제외: `seenTitles` Set에 현재 기사 제목 선등록
- STOP_WORDS: 공급, 수출, 수입, 생산, 투자, 미국, 한국, 중국, 달러, 억원 등 50+ 단어 (너무 일반적인 단어 매칭 방지)
- 최대 4건 표시

### 검색 연동 (2026-06-27 확립)
- **전용 결과 페이지**: 검색 시 `search.html?q=검색어`로 이동 (인라인 필터 방식 금지)
- `search.html`: `?q=` 파라미터 읽어 오늘 + 최근 5일 아카이브 로드 후 결과 표시
- 검색어 하이라이트: `reTest`(i flag only, 필터용) / `reHL`(gi flags, 하이라이트용) 분리 필수
  - g 플래그 단일 regex로 `re.test()` 두 번 호출 시 `lastIndex` 오염으로 false negative 발생
- `search.html`의 nav 항목은 index·article·category와 동일하게 유지
- "더 많은 기사 보기": 아카이브 추가 로드 후 재검색, 결과 누적 표시

### 쿠팡 파트너스 광고 (2026-06-28 확립)
- **trackingCode**: AF9787280, template=carousel (전 슬롯 공통)
- **렌더링 방식**: `<iframe src="...">` — 절대 동적 script 주입 방식 사용 금지

  **금지 패턴** (동작하지 않음):
  ```javascript
  // ❌ el.appendChild(script) 방식 — document.currentScript 컨텍스트 오류로 렌더링 실패
  const s = document.createElement('script');
  s.text = `new PartnersCoupang.G({...})`;
  el.appendChild(s);
  ```

### 광고 슬롯 구성

| 위치 | iframe 파일 | id | 크기 | CSS 클래스 |
|------|------------|-----|------|------------|
| 본문 중간 | `coupang-ad.html` | 970645 | 680×140 | `.coupang-mid-ad` (height:160px) |
| 본문 하단 | `coupang-ad-leaderboard.html` | 1000915 | 728×90 | `.coupang-leader-ad` (max-width:728px, height:110px) |
| 사이드바 | 정적 script 쌍 (inline) | 970543 | 300×300 | `.sb-coupang` |

- 본문 중간: article body paragraphs 절반 지점에 동적 삽입 (JS template literal)
- 본문 하단: `<div class="art-body">` 바로 아래 정적 HTML
- 사이드바: `<script src="g.js">` + `<script>new PartnersCoupang.G({...})</script>` 쌍 — 이미 정상 작동하므로 iframe 변환 불필요

### iframe 파일 작성 규칙
```html
<!DOCTYPE html><html><head>
<style>body{margin:0;padding:0;overflow:hidden;background:transparent}</style>
</head><body>
<script src="https://ads-partners.coupang.com/g.js"></script>
<script>
new PartnersCoupang.G({id:XXXXX, trackingCode:"AF9787280", subId:null, template:"carousel", width:"W", height:"H"});
</script>
</body></html>
```

- `coupang-mid-notice` 문구: "이 포스팅은 쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다."
- 새 광고 단위 추가 시: `coupang-ad-{name}.html` 신규 파일 + CSS 클래스 추가

---

## 피드 구조 (2026-06-27 개편)

- **최초 로드**: 오늘(articles.json) + 최근 2일치(archive) 자동 로드
- **추가 로드**: "기사 더 불러오기" 버튼으로 1일치씩 추가
- **검색**: 헤더 우측 검색창, 로드된 전체 기사에서 실시간 필터링
  - 검색 대상: 제목, 요약, 카테고리, 본문(body)
  - 검색어 하이라이트 표시
- **카테고리 필터**: 최신 피드 상단 버튼으로 반도체소재/희귀금속/산업재/글로벌 필터

---

## 배포 체크리스트

- [x] tugman77/materials-news 저장소 생성
- [x] 코드 push
- [x] ANTHROPIC_API_KEY Secret 등록
- [x] GitHub Actions `.github/workflows/자동기사생성.yml` (기사생성 + 검수 연속 실행)
- [ ] **GitHub Pages 활성화** (Settings → Pages → Deploy from branch → main / root)
- [ ] UNSPLASH_ACCESS_KEY Secret 등록 (선택 — 없으면 loremflickr 사용)
- [ ] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID Secret 등록 (선택 — 검수 보고용)
- [ ] Actions 정상 실행 확인
