소재경제신문 - 반도체·소재·산업재 전문 뉴스 사이트
=====================================================

## 파일 구조

index.html                        뉴스 사이트 메인 페이지 (articles.json 동적 로드)
기사자동생성.py                   Claude API 기사 생성 스크립트
articles.json                     자동 생성된 기사 데이터 (실행 후 생성됨)
.github/workflows/자동기사생성.yml  GitHub Actions 자동 실행 설정


## GitHub Pages 배포 순서

──────────────────────────────────────────────────
1단계: GitHub 저장소 생성
──────────────────────────────────────────────────
  1. https://github.com 접속 → New repository
  2. Repository name: materials-news (원하는 이름)
  3. Public 선택 (Pages 무료 사용)
  4. Create repository 클릭

──────────────────────────────────────────────────
2단계: 파일 업로드
──────────────────────────────────────────────────
  터미널에서 이 폴더 위치로 이동 후 아래 명령 실행:

    git init
    git add .
    git commit -m "소재경제신문 초기 배포"
    git branch -M main
    git remote add origin https://github.com/사용자명/materials-news.git
    git push -u origin main

  또는 GitHub 웹사이트에서 직접 파일 업로드 가능
  (Upload files 버튼 → 폴더 전체 드래그앤드롭)

──────────────────────────────────────────────────
3단계: GitHub Pages 활성화
──────────────────────────────────────────────────
  저장소 → Settings → Pages
  → Source: Deploy from a branch
  → Branch: main / (root)
  → Save

  완료 후 주소: https://사용자명.github.io/materials-news

──────────────────────────────────────────────────
4단계: API 키 등록 (자동화 필수)
──────────────────────────────────────────────────
  저장소 → Settings → Secrets and variables → Actions
  → New repository secret
  → Name: ANTHROPIC_API_KEY
  → Secret: 실제 API 키 값 입력
  → Add secret


## 로컬 테스트 방법

  1. API 키 환경변수 설정 후 스크립트 실행:
       export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"
       python 기사자동생성.py

  2. articles.json 생성 확인

  3. index.html을 브라우저로 열기
     (단, fetch는 로컬에서 CORS 제한 있음 → 아래 방법 사용)

     python -m http.server 8000
     → http://localhost:8000 접속


## 자동 실행 스케줄

  매일 오전 6시(KST) GitHub Actions가 자동으로:
  - RSS 뉴스 수집 (전자신문, 한국경제, 연합뉴스, Google뉴스)
  - Claude API로 기사 5건 생성
  - articles.json 업데이트
  - GitHub Pages 자동 반영

  수동 실행: 저장소 → Actions → 매일 자동 기사 생성 → Run workflow


## 비용

  - GitHub Pages 호스팅: 무료
  - Claude API: 기사 5건/일 ≈ 약 월 3,000~5,000원
  - 도메인 (선택): 연 1~2만원


## 주의사항

  - 루트의 자동기사생성.yml 파일은 사용되지 않음 (삭제 가능)
    실제 사용 파일: .github/workflows/자동기사생성.yml
  - articles.json이 없으면 index.html은 예시 기사를 표시함
    (정상 동작이며, 스크립트 실행 후 자동으로 실제 기사로 교체됨)
