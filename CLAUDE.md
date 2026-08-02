# 201 소재타임스 — CLAUDE.md

## 개요
반도체·소재·희귀금속·산업재 전문 뉴스 자동 생성 사이트. 매일 기사 5개 + 시세 데이터 자동 발행.

- **GitHub 저장소:** `tugman77/materials-news`
- **배포 방식:** GitHub Pages (main 브랜치 / root 디렉터리)
- **AI 모델:** `claude-sonnet-4-6`
- **DB:** 없음 (JSON 파일 기반)

### 발행 하이브리드 (2026-07-23 전환) — 구독코인 우선 + API코인 백업
API코인이 0이어도 발행이 멈추지 않도록 이원화.

1. **로컬 구독코인 (우선):** 맥에서 launchd `com.aios.sojaetimes`가 매일 **KST 05:00** →
   `800_스킬함/스크립트/소재타임스_로컬발행.command` 실행 (수집→생성→검수→기사기획브리핑→push).
   `LLM_BACKEND=claude_code`로 Claude Code 헤드리스(`claude -p --output-format json`)를 써서 **구독코인** 사용. pmset 04:57 자동 기상 + caffeinate로 발행 중 절전 방지.
2. **클라우드 API코인 (백업):** GitHub Actions `.github/workflows/자동기사생성.yml` cron **KST 06:00**.
   첫 `guard` 스텝이 `articles.json`의 `generated_at`에 오늘(KST) 날짜가 있으면 skip → **로컬 성공한 날은 API코인 안 씀.** 로컬 실패·맥 꺼짐이면 API코인으로 백업 발행.

**백엔드 스위치** (`llm_backend.py`): `LLM_BACKEND=claude_code`(구독) / 미설정=`api`(기본, 기존 SDK 경로 그대로 — 클라우드 하위호환). `기사자동생성.py`·`기사검수.py`가 이 모듈로 분기.
※ 로컬 python은 `/usr/bin/python3`(3.9)뿐이라 두 스크립트에 `from __future__ import annotations` 추가(3.10+ 유니온 어노테이션 회피), `json_repair`는 `--user` 설치.
※ 구독코인을 실제로 쓰려면 맥이 05:00에 깨어 있어야 함(아니면 06:00 클라우드 백업).

---

## 브랜드 정보 (2026-06-28 확정)

| 항목 | 내용 |
|------|------|
| **제호** | 소재타임스 |
| **영문 제호** | MATERIALS TIMES |
| **도메인** | materialtimes.co.kr (2026-07-07 등록, 비아웹, 만료 2027-07-07) |
| **이메일** | ads@materialtimes.co.kr (도메인 메일 개통 후 사용) |
| **현재 URL** | tugman77.github.io/materials-news (GitHub Pages) |
| **텔레그램 채널** | @materialtimes (공개 채널, 2026-08-01 개설) |

> DNS(비아웹) A레코드 4개 + www CNAME 설정 → GitHub Pages Custom domain `materialtimes.co.kr` 입력 → Enforce HTTPS

### 브랜드 자산 (2026-08-01 추가)

`python3 scripts/make_logos.py` (Pillow 필요) → `images/`에 6종 생성.
색상은 `index.html` 실사용값에서 가져온다 — **블루 `#0057a8` + 레드 `#c8102e`**.

| 자산 | 용도 |
|------|------|
| `logo-rect.png` | 가로형 — 외부 등록·제휴 제출용 |
| `logo-square.png` / `logo-square-hex.png` | 정사각 — 텔레그램·SNS 프로필 |
| `og-default.jpg` | 홈 공유 미리보기(개별 기사는 정적페이지생성.py가 따로 생성) |
| `favicon-32.png` / `favicon-180.png` | 브라우저 탭·iOS 홈화면 |

- **텔레그램은 프로필을 원형으로 크롭한다** → 정사각 아이콘 요소를 전부 중앙에 몰았다.
  모서리에 번호를 넣는 원소기호 타일안은 그래서 뺐다.
- **헤더 로고는 텍스트 조판(`.logo-kr`/`.logo-en`) 유지.** 반응형·접근성에서 이미지 교체보다 낫다.
  생성한 로고는 OG·파비콘·외부 등록용 자산으로만 쓴다.

---

## 텔레그램 발행 구조 (2026-08-01 확립)

**봇 하나, 목적지 둘.** 환경변수를 반드시 구분해서 쓴다.

| 환경변수 | 목적지 | 내용 | 쓰는 곳 |
|---------|--------|------|--------|
| `TELEGRAM_CHAT_ID` | 대표님 개인 채팅 | 운영 알림 — 검수 결과, 실패 보고 | `기사검수.py`, `기사기획브리핑.py`, `뉴스레터생성.py` |
| `TELEGRAM_CHANNEL_ID` | 공개 채널 @materialtimes | 독자용 다이제스트 | `기사자동생성.py` `post_to_channel()`, `뉴스레터생성.py` |

- **채널 ID 미설정이면 채널 발행만 skip** — 발행 파이프라인 자체는 계속 진행한다.
- 일일 5건은 **1개 메시지로 묶는다.** 5개로 나눠 보내면 채널이 도배된다.
- 채널 링크는 **정적 페이지(`news/{date}-{id}.html`)** 를 쓴다. `article.html`은 클라이언트
  렌더링이라 텔레그램 미리보기 크롤러가 본문을 못 읽는다.
- **관리자 알림을 없애지 말 것.** 주간 뉴스레터가 2주간 실패했는데 아무도 몰랐던 게 이 알림이 필요한 이유다.

---

## 파일 구조

```
400_채널/410_소재/소재타임스/
├── 기사자동생성.py        ← 메인 스크립트 (RSS 수집 → Claude API → JSON 저장 → 채널 발행)
├── 기사검수.py            ← 이미지·중복·사실성 검수 + Telegram 보고
├── articles.json          ← 최신 기사 데이터 (index.html이 읽음)
├── index.html             ← 메인 뉴스 페이지 (홈)
├── article.html           ← 기사 본문 페이지
├── category.html          ← 카테고리별 기사 목록 페이지 (URL param: ?cat=...)
├── search.html            ← 검색 결과 페이지 (?q=검색어)
├── about.html             ← 회사소개
├── advertising.html       ← 광고안내
├── privacy.html           ← 개인정보처리방침
├── terms.html             ← 이용약관
├── images/                ← 기사 이미지 (YYYY-MM-DD_article_N.jpg) + 브랜드 자산
│   logo-rect.png / logo-square.png / logo-square-hex.png / og-default.jpg
│   favicon-32.png / favicon-180.png  ← scripts/make_logos.py 산출물
├── archive/               ← 날짜별 기사 아카이브
│   ├── index.json         ← 날짜 목록 (최대 90일)
│   └── YYYY-MM-DD.json    ← 날짜별 기사 데이터
├── sojaetimes/            ← 전문 정보수집 파이프라인 (2026-07-16 추가)
│   ├── collect.py         ← 5개 분야 뉴스 수집 (네이버API + Google RSS)
│   ├── agent_prompt.md    ← 기사기획브리핑.py 프롬프트 스펙 요약본
│   ├── briefing_YYYYMMDD.json        ← 수집 결과
│   └── YYYYMMDD_소재타임스_기사기획브리핑.md  ← 기사기획브리핑.py 산출물
├── 기사기획브리핑.py       ← 기사 기획 지원 에이전트 (2026-07-26 추가, 구독코인 전용)
│   국내 수집본(sojaetimes/briefing) 재사용 + WebSearch/WebFetch 글로벌 보강 →
│   이슈별 [A]중요도~[E]선행보도 분석 + ★★★ 초안 뼈대 → md 저장 + 텔레그램 발송.
│   오늘 이미 발행된 5건과 겹치면 "후속 심화 필요"로 표시(중복 추천 방지).
│   ※ 클라우드 RemoteTrigger 버전(Google Drive+Gmail)은 은퇴 — Gmail MCP가 초안 생성만
│      가능하고 실제 발송이 안 돼 10일치가 임시보관함에 안 읽힌 채 쌓여있던 것을 발견,
│      기사검수.py가 쓰는 텔레그램 봇 재사용 방식으로 로컬 전환.
├── 정적페이지생성.py       ← SEO 정적 페이지 생성기 (2026-07-29 추가)
│   archive/*.json → news/YYYY-MM-DD-N.html 정적 렌더링 + sitemap.xml/rss.xml/robots.txt 생성.
│   발행 파이프라인(save_data)에 연결되어 매일 자동 실행. article.html은 클라이언트 렌더링이라
│   크롤러가 본문을 못 읽던 문제를 해결 (canonical을 정적 페이지로 지정, article.html은 구링크 호환용).
├── 이미지필터.py           ← 이미지 키워드 오매칭 방지 (2026-08-01 추가, 기사자동생성·기사검수 공용)
│   검색 전 키워드 한정어 부착 + 검색 후 태그 기반 음식/생활 사진 거부.
│   단독 실행(`python3 이미지필터.py`)으로 자가 검증 케이스 통과 확인.
├── 이미지소스.py           ← 외부 이미지 소스 API (2026-08-02 추가, 두 파일 공용)
│   Unsplash·Pexels·Pixabay 검색을 한 곳에 모았다. 키는 호출 시점에 os.environ에서 읽는다
│   (로컬 발행이 .env를 source한 뒤 실행하므로 임포트 시점 고정 금지).
│   `python3 이미지소스.py`로 키 등록 상태 + 실제 검색 결과를 점검할 수 있다.
├── 뉴스레터생성.py         ← 주간 뉴스레터 (매주 금 KST 08:00)
│   웹판(newsletter/*.html 전문)과 텔레그램판(요약+링크)을 분리한다.
│   텔레그램에 전문을 다 넣으면 웹 유입이 안 쌓인다.
├── newsletter/            ← 주간 뉴스레터 아카이브 (뉴스레터_YYYYMMDD.html)
├── scripts/
│   └── make_logos.py      ← 브랜드 자산 생성기 (2026-08-01 추가, Pillow 필요)
├── news/                  ← 정적페이지생성.py 산출물 (YYYY-MM-DD-N.html, 크롤러용)
├── sitemap.xml / rss.xml / robots.txt  ← 정적페이지생성.py 산출물
└── .github/workflows/
    ├── 자동기사생성.yml   ← GitHub Actions (매일 UTC 21:00 = KST 06:00)
    └── 주간뉴스레터.yml   ← 매주 목 UTC 23:00 = 금 KST 08:00
```

> ⚠️ **워크플로에 `permissions: contents: write`를 빠뜨리지 말 것.** 없으면 push 단계가
> `github-actions[bot]` 403으로 실패한다. 주간뉴스레터.yml에 이게 없어서 2026-07-24·31
> 두 주 연속 `newsletter/` 아카이브 커밋이 누락됐다(생성·발송 자체는 성공해 알아채기 어려웠다).

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

### [완화됨] 구독코인 헤드리스 무응답 타임아웃 (2026-07-26~29)
- **증상**: `기사자동생성.py`가 첫 시도부터 30분 내내 응답 없이 `TimeoutExpired`로 실패 (07-26 2회, 07-29 1회 — 4일 중 3회 발생). 트리비얼 헤드리스 호출은 5초 만에 정상 응답, Anthropic 상태 페이지도 정상이라 원인 특정은 못함.
- **원인 추정**: `--output-format json`은 완료 전까지 아무것도 출력하지 않아 "서버가 느린 것"과 "진짜 멈춘 것"을 구분할 수 없음. 수동 재시도가 수 분 내 성공한 사례(07-27)로 볼 때 일시적 지연/큐잉일 가능성이 높음.
- **완화**: `llm_backend.py`의 `call_tool()`에 타임아웃 전용 자동 재시도 추가. `CLAUDE_CODE_TIMEOUT`은 이제 "총 예산"이 아니라 "시도 1회당 예산"(기본 1200s)이고, 무응답 시 `CLAUDE_CODE_RETRIES`(기본 2회)만큼 재시도. rc≠0 등 실제 실패는 재시도하지 않고 바로 올림(반복해도 같은 결과일 가능성이 높으므로).
- **미해결**: 근본 원인(서버 큐잉 vs 클라이언트 문제) 특정 안 됨. 로컬이 실패해도 KST 06:00 클라우드(API코인) 백업이 있어 발행 자체는 안전.

### [수정됨] 큐레이션 풀 고갈 → picsum 폴백 (2026-08-02)
- **증상**: '삼성SDI, OLED 소재 매출 확대' 기사 대표이미지가 **갈매기 사진**
- **원인**: 오매칭이 아니라 **풀 고갈**이었다. 풀 URL은 고정이라 바이트가 매일 같은데,
  저장할 때마다 MD5를 영구 히스토리(`_downloaded_hashes`)에 넣는 바람에 한 번 쓴 photo-ID가
  영구 차단됐다. 확인 결과 **풀 33장 중 29장이 이미 죽은 상태**(반도체소재는 9/9 전멸).
  풀 8회 시도가 전부 중복으로 거부되자 마지막 폴백인 picsum(내용 무관 랜덤)이 걸렸다.
  실제 재다운로드는 `기사검수.py`에서 났다 — 검수가 키워드를 바꾸고 다시 받는 경로.
- **검증**: 갈매기 파일 MD5가 `picsum.photos/seed/{md5(keyword)[:8]}/800/450` 응답과 정확히 일치
- **해결**: 풀 이미지는 영구 해시 대조에서 제외하고 `_run_hashes`(이번 실행)만 본다.
  두 파일 모두 수정. 수정 후 같은 요청 3연속이 전부 `unsplash_pool`에서 나오는 것을 확인
- **함께 드러난 두 번째 원인**: `기사검수.py`에는 애초에 **Pexels·Pixabay 경로가 없었다.**
  소스가 풀과 picsum뿐이라 풀이 죽자 곧바로 랜덤 이미지행. 키는 로컬 `.env`와
  GitHub Secrets 양쪽에 이미 있었는데 이 파일만 안 쓰고 있었다 →
  `이미지소스.py`로 두 파일의 소스 목록을 통합해 재발 차단
- **교훈**: '중복 방지'와 '고정 URL 재사용'은 서로 모순된다. 폴백이 조용히 성공하면
  파이프라인은 정상으로 보이므로, **picsum까지 내려간 사실 자체가 경보**여야 한다

### [수정됨] 이미지 키워드 오매칭 — 웨이퍼 기사에 과자 사진 (2026-08-01)
- **증상**: '두산, SK실트론 2.3조 인수' 기사 대표이미지가 스트룹와플(웨이퍼 과자) 접시 사진
- **원인**: `image_keyword`는 `"semiconductor wafer production"`으로 정상이었으나 Pixabay가
  `wafer`를 과자로 해석해 음식 사진 반환. 기존 코드는 `random.choice(hits)`로 검증 없이 1건 채택
- **해결**: `이미지필터.py` 신설 — 검색 전 키워드 한정어 부착 + 검색 후 태그 기반 거부·다음 후보 이동
  (위 '오매칭 방지 규칙' 참조). 해당 기사 이미지는 美 에너지부 PD 클린룸 웨이퍼 사진으로 교체
- **교훈**: 이미지 소스 API는 결과를 검증 없이 신뢰하면 안 된다. Claude가 뽑은 키워드가
  멀쩡해도 검색엔진 쪽에서 오매칭이 난다 — `기사검수.py`의 키워드 적절성 검토만으로는 못 잡는다

### [수정됨] 정적 페이지가 커밋되지 않아 기사 링크 전량 404 (2026-08-01)
- **증상**: 메인에서 기사 클릭 시 404. 2026-07-29~08-01 4일치 전부
- **원인**: `자동기사생성.yml`의 `git add` 목록에 `news/`·`sitemap.xml`·`rss.xml`이 빠져 있었다.
  정적 페이지는 생성됐지만 커밋되지 않았고, `index.html`은 기사 링크를 `news/YYYY-MM-DD-N.html`로 만든다.
  로컬 발행은 `git add -A`라 무사했는데 07-29부터 로컬이 계속 실패해 클라우드 백업만 돌면서 드러났다
- **해결**: 워크플로 `git add`에 `news/ sitemap.xml rss.xml robots.txt` 추가 + 누락분 백필
- **교훈**: 발행 산출물이 늘면 **로컬(`git add -A`)과 클라우드(명시 목록) 양쪽**을 함께 확인해야 한다

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
| 5 | picsum | 불필요 | 최종 폴백, **내용 무관 — 여기까지 오면 사실상 실패** |

> ⚠️ **소스 순서는 `이미지소스.available_sources()` 한 곳에서만 정한다** (2026-08-02).
> `기사자동생성.py`와 `기사검수.py`가 각자 순서를 갖고 있던 탓에, 검수 쪽에만 Pexels·Pixabay가
> 빠져 재다운로드가 풀→picsum으로만 떨어졌다. 검수는 **누락 보충·중복 교체·키워드 수정** 세 경로에서
> 이미지를 다시 받으므로, 생성 쪽과 소스가 같아야 한다.

### 오매칭 방지 규칙 (2026-08-01 추가 — `이미지필터.py`)
`기사자동생성.py`·`기사검수.py`가 공유하는 모듈. 방어선이 둘이다.

1. **검색 전 — `refine_keyword()`**: `wafer`·`chip`·`foil`·`plant`·`crystal`·`mine`처럼
   일상 사물로도 읽히는 단어에 업계 한정어를 자동 부착
   (`"wafer production"` → `"wafer production semiconductor"`). 이미 한정어가 있으면 그대로 둔다.
2. **검색 후 — `is_offtopic()` / `pick_relevant()`**: 이미지 자신의 태그·alt·설명에
   음식·생활 차단어가 있으면 거부하고 **같은 소스의 다음 후보**로 넘어간다.
   Pexels `alt`, Pixabay `tags`, Unsplash `alt_description`을 검사한다.
   후보를 여럿 받으려고 Unsplash random 호출에 `count=5`를 붙였다.
   전량 거부되면 `None` 반환 → 큐레이션 풀로 폴백.

- **차단어에 `wafer`/`wafers`/`plate`/`sheet`/`crystal`을 넣지 말 것** — 반도체·철강 사진의
  정상 태그다. 과자 사진은 함께 붙는 `waffle`·`cookie`·`dessert`로 걸린다.
- 메타데이터가 비어 있으면 통과시킨다. 근거 없는 거부는 picsum(내용 무관) 폴백을 부른다.
- 필터 수정 후 `python3 이미지필터.py`로 자가 검증 케이스를 반드시 통과시킬 것.

### 중복 방지 규칙 (3중 보호)
1. **Cross-category 중복 금지** — `_UNSPLASH_POOL` 각 photo-ID는 단일 카테고리에만 등록. `_validate_pool()` 함수가 실행마다 자동 감지.
2. **Run 내 재사용 금지** — `_used_photo_ids` set: 동일 실행에서 선택된 photo-ID는 재선택 안 함.
3. **바이너리 중복 금지** — 동일 MD5 파일은 저장 거부 후 다음 소스 시도.
   대조 범위가 소스에 따라 다르다(2026-08-02 수정):
   - 외부 API(Unsplash/Pexels/Pixabay)·picsum → `_downloaded_hashes` (**과거 날짜 포함 영구**)
   - 큐레이션 풀 → `_run_hashes` (**이번 실행만**)

> ⚠️ **큐레이션 풀 이미지의 MD5를 영구 히스토리에 넣지 말 것.**
> 풀 URL은 고정이라 매일 같은 바이트가 내려온다. 영구 해시에 넣는 순간 그 photo-ID는
> 두 번 다시 통과하지 못하고, 풀 전체가 서서히 죽어 picsum(내용 무관 랜덤)으로 폴백한다.
> 풀의 날짜 간 반복 간격은 `_photo_id_last_used` LRU가 맡는 것이 원래 설계다.

### 풀 관리 원칙
- 카테고리당 최소 8개 이상 유지 (5기사/일 + 여유분)
- **풀 건강 점검** — 풀 이미지를 받아 MD5가 `image_history.json`의 `hashes`에 있는지 확인.
  다수가 걸리면 위 규칙이 깨진 것이다(2026-08-02엔 33장 중 29장이 죽어 있었다).
- **카테고리별 소재 공백 주의** — `산업재` 풀은 공장·제철·건설 위주라 전자재료·디스플레이
  기사에 맞는 사진이 없다. `_pick_pool_url()`은 카테고리만 보고 키워드는 안 본다.
- 새 ID 추가 전 전체 풀 검색으로 중복 확인
- `기사자동생성.py`와 `기사검수.py` 두 파일의 풀을 항상 동일하게 유지
- 파일명: `images/YYYY-MM-DD_article_N.jpg` — 날짜 포함으로 날짜 간 덮어쓰기 방지

### API 키 등록 위치
- 로컬: `.env` 또는 `export` 명령
- GitHub Actions: Settings → Secrets → `PEXELS_API_KEY`, `PIXABAY_API_KEY`

---

## 로컬 실행

```bash
cd "400_채널/410_소재/소재타임스"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"
export UNSPLASH_ACCESS_KEY="..."  # 선택: 없으면 큐레이션 풀 사용
pip install anthropic feedparser requests
python3 기사자동생성.py
python3 기사검수.py       # 이미지 중복·불일치 검수 + 텔레그램 보고
python3 이미지필터.py     # 이미지 필터 수정 시 자가 검증
python3 정적페이지생성.py  # 정적 페이지 전량 재생성(백필)
```

※ 로컬 python은 `/usr/bin/python3`(3.9)뿐이다. 3.10+ 문법을 쓰지 말 것
  (`from __future__ import annotations`로 어노테이션만 회피 중).

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
- **섹션 내 중복 금지**: 동일 기사(같은 date+idx 또는 같은 title)가 같은 섹션에 2번 이상 노출되지 않도록 `sectionShown` Set으로 관리
- **섹션 표시 기사 전역 추적**: 각 카테고리 섹션에 표시된 기사는 `sectionIndices` Set에 등록 → 최신 피드에서 제외
- "더보기 →": `category.html?cat=...` 링크
- **모바일(640px 이하) 그리드**: `grid-template-columns: repeat(2, 1fr)` — 2열 표시 (기존 1열에서 변경)

**최신 기사 피드**
- **히어로 기사 제외** 동일 조건 적용
- **섹션 기사 제외**: `sectionIndices`에 등록된 기사도 제외 → 섹션에 나온 기사는 최신 피드에 재노출 금지
- 카테고리 필터 버튼으로 필터링 가능
- 초기 로드: 오늘 + 최근 2일치 아카이브 자동 로드 → 이후 버튼으로 추가 로드

> ⚠️ **핵심 원칙 (중복 노출 완전 차단)**
> 1. 히어로 기사 → 카테고리 섹션·최신 피드 어디에도 재노출 금지
> 2. 카테고리 섹션 기사 → 최신 피드에 재노출 금지
> 3. 동일 기사가 같은 카테고리 섹션에 2회 이상 노출 금지
> 4. 모바일에서 카테고리 섹션은 2열(repeat(2, 1fr)) 표시

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
- [x] GitHub Pages 활성화 ✅ 2026-06-28 완료
- [x] Actions 정상 실행 확인 ✅ 2026-06-28 성공
- [x] 제호 확정: **소재타임스** / MATERIALS TIMES ✅ 2026-06-28
- [x] 회사소개·광고안내·개인정보처리방침·이용약관 페이지 생성 ✅ 2026-06-28
- [x] 전체 HTML footer 링크 연결 (about/advertising/privacy/terms) ✅ 2026-06-28
- [x] SEO 정적 페이지 + sitemap/rss/robots 도입 ✅ 2026-07-29 (기존 150건 백필 완료)
- [x] 정적 페이지 404 수정 — 워크플로 `git add`에 `news/`·`sitemap.xml`·`rss.xml` 추가 ✅ 2026-08-01
- [x] 이미지 오매칭 방지 필터 `이미지필터.py` 도입 ✅ 2026-08-01
- [x] 브랜드 자산(로고·OG·파비콘) 생성 + 홈 OG/트위터 카드 ✅ 2026-08-01
- [x] 텔레그램 공개 채널 @materialtimes 개설 + 일일·주간 발행 연결 ✅ 2026-08-01
- [x] 주간뉴스레터.yml `permissions: contents: write` 추가 ✅ 2026-08-01 (403으로 2주 누락되던 것)
- [ ] **materialtimes.co.kr 커스텀 도메인 연결** → GitHub Pages Custom domain 설정
      ※ 연결 시 `정적페이지생성.py`·`기사자동생성.py`·`뉴스레터생성.py`의 `SITE_URL`과 `robots.txt`도
      `tugman77.github.io/materials-news`에서 `materialtimes.co.kr`로 함께 바꿔야 함.
- [ ] UNSPLASH_ACCESS_KEY Secret 등록 (선택 — 없으면 loremflickr 사용)
- [x] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID Secret 등록 ✅ (기사검수.py 검수 보고 + 기사기획브리핑.py 발송용)
- [x] TELEGRAM_CHANNEL_ID Secret 등록 ✅ 2026-08-01 (공개 채널 @materialtimes 발행용)
- [ ] 로컬 구독코인 발행 복구 — 2026-07-29부터 연속 실패, 클라우드 API코인으로 백업 중
