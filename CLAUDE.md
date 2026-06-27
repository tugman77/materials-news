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
├── articles.json          ← 최신 기사 데이터 (index.html이 읽음)
├── index.html             ← 메인 뉴스 페이지
├── article.html           ← 기사 본문 페이지
├── images/                ← 기사 이미지 (loremflickr 다운로드)
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

## 피드 구조 (2026-06-27 개편)

- **누적 피드**: 오늘 기사 → 어제 → 그제 순으로 날짜별 섹션이 메인에 이어짐
  - 최초 로드: 오늘(articles.json) + 최근 2일치(archive) 자동 로드
  - 무한 스크롤: 페이지 하단 400px 진입 시 1일치 자동 로드
  - "이전 기사 더 보기" 버튼: 2일치 수동 추가 로드
- **검색**: 헤더 우측 검색창, 로드된 전체 기사에서 실시간 필터링 (debounce 280ms)
  - 검색 대상: 제목, 요약, 카테고리, 본문(body)
  - 검색어 하이라이트 표시
- **카테고리 필터**: nav 바 클릭으로 반도체소재/희귀금속/산업재/글로벌 필터

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
