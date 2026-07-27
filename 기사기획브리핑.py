"""
소재타임스 기사 기획 브리핑 — 구독코인(로컬 Claude Code) 전용.

collect.py 직후 실행한다. sojaetimes/briefing_YYYYMMDD.json(국내 수집본)을
그대로 재사용하고, 여기에 WebSearch/WebFetch로 글로벌(영어)·일본어·중국어
매체만 보태 이슈별 [A]중요도 [B]독자관점 [C]기사각도 [D]취재원 [E]선행보도
분석과 ★★★ 이슈의 기사 초안 뼈대를 만든다. 오늘 이미 발행된 5개 기사와
겹치는 이슈는 "후속 심화 필요"로 표시해 중복 추천을 피한다.

결과는 sojaetimes/{date}_소재타임스_기사기획브리핑.md 로 저장하고,
요약을 텔레그램으로 보낸다(발송 전용 — 초안함에만 쌓이는 Gmail 대신
이미 기사검수.py가 쓰고 있는 텔레그램 봇을 그대로 재사용).

LLM_BACKEND=claude_code 가 아니면(API코인/클라우드 경로) 건너뛴다.
이 브리핑은 편집 지원용 부가 기능이라 별도의 클라우드 백업 경로를
만들지 않는다 — 실패해도 본 발행 파이프라인(기사자동생성/기사검수)에는
영향 없음.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import requests
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CLAUDE_CLI = os.environ.get("CLAUDE_CLI", "claude")
CLAUDE_CODE_MODEL = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-6")
CLAUDE_CODE_TIMEOUT = int(os.environ.get("CLAUDE_CODE_TIMEOUT", "1800"))

SOJAE_DIR = "sojaetimes"
ARTICLES_FILE = "articles.json"


def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[텔레그램 미설정] {message[:80]}")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
        }, timeout=10)
        if not resp.ok:
            print(f"텔레그램 전송 실패: {resp.status_code} {resp.text[:200]}")
        return resp.ok
    except Exception as e:
        print(f"텔레그램 전송 오류: {e}")
        return False


def _load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def build_prompt(today_str: str, topics: dict, published_titles: list[str]) -> str:
    topics_text = json.dumps(topics, ensure_ascii=False, indent=2)
    published_text = "\n".join(f"- {t}" for t in published_titles) or "(오늘 발행 기사 없음)"

    return f"""당신은 소재타임스(소재·부품·장비 전문 매체) 기사 기획 지원 에이전트입니다.
바쁜 기자들이 놓칠 수 있는 이슈를 선제적으로 발굴하고, 취재 방향과 기사 각도까지 제시하는 것이 목적입니다.
오늘 날짜: {today_str}

[국내 수집본 — 이미 수집 완료, 그대로 사용할 것. 다시 검색하지 말 것]
{topics_text}

[오늘 소재타임스에 이미 발행된 기사 제목 — 5건]
{published_text}

## 1단계: 글로벌 뉴스 보강 수집
WebSearch로 아래 영어 키워드를 검색해 국내 수집본에 없는 글로벌 이슈를 보강하세요:
- "semiconductor materials China export control latest"
- "critical minerals supply chain disruption"
- "solid-state battery materials breakthrough"
- "OLED materials new development"
- "rare earth export restriction China"
- "CHIPS Act materials semiconductor supply"

WebFetch로 아래 일본어/중국어 매체도 확인하세요(실패하면 건너뛰고 계속 진행):
- https://xtech.nikkei.com (일본 반도체/소재 기술)
- https://www.dempa-digital.com (일본 디스플레이/배터리)
- https://www.iczhiku.com (중국 반도체 소재)
- https://www.cls.cn/telegraph (중국 광물/소재 시장)

## 2단계: 이슈별 기사 기획 분석
국내 수집본 + 글로벌 보강 수집을 합쳐, 이슈별로 아래 5가지를 분석하세요:

[A] 중요도 등급
★★★: 공급망 직접 충격, 수출규제 신규 발표, 대형 기업 생산 중단/전환 → 즉시 기사화 필요
★★: 새로운 기술 개발, 주요 투자/M&A, 정부 R&D 과제 → 이번 주 내 취재 추천
★: 시장 동향, 분석 리포트, 학술 연구 → 기획기사 배경 소재

[B] 소재타임스 독자 관점 설명
소부장 업계 종사자, 연구자, 정책 담당자 관점에서 "왜 이 이슈가 지금 중요한가"를 2~3문장으로 설명.

[C] 기사 각도 제안 (최대 3개)
소재타임스 독자를 위한 구체적 기사 방향.

[D] 추천 취재원 유형
인터뷰/확인 취재 대상 유형 (실명 아닌 기관/직책 유형으로).

[E] 선행 보도 가능성 평가
"단독 발굴 가능성 높음" / "후속·심층 기사로 차별화 필요" / "이미 많이 보도됨" 중 하나.
**중요**: 위 "오늘 이미 발행된 기사 제목"과 동일하거나 사실상 같은 이슈를 다루고 있다면,
반드시 "오늘 소재타임스에 이미 발행됨 — 후속 심화 필요"로 표기하고, 해당 이슈는
3단계(★★★ 초안 뼈대)에서 제외하세요.

## 3단계: ★★★ 이슈 기사 초안 뼈대
★★★ 등급이면서 오늘 이미 발행되지 않은 이슈에 대해서만:
- 기사 제목 후보 3개
- 리드(첫 문장) 후보
- 기사 구성 제안 (핵심 사실 → 업계 영향 → 정부/업계 반응 → 전망)
- 필수 확인 사항 목록

## 주의사항
- 중복 기사 제거(동일 이슈 다른 매체는 1건으로 통합), 단순 주가/시황 기사 제외
- 3일 이상 오래된 기사 제외, 중국 수출규제 이슈 최우선 체크
- 이슈가 없는 분야는 "오늘 특이 이슈 없음"으로 표시

## 출력 형식 — 반드시 지킬 것
아래 두 블록을 이 순서 그대로, 마커까지 정확히 출력하세요. 다른 설명·인사말은 붙이지 마세요.

[TELEGRAM_SUMMARY]
(순수 텍스트만 사용 — HTML 태그, 마크다운 기호(**, #, |) 금지. 최대 3000자.
★★★ 이슈 제목과 한 줄 기사각도 요약, ★★ 이슈 제목만 분야별로 나열, 마지막 줄에
"총 N건 분석 | ★★★ N건 | ★★ N건")
[/TELEGRAM_SUMMARY]

[FULL_REPORT]
(마크다운 전체 리포트 — 분야별 이슈 요약표 + 이슈별 [A]~[E] 분석 + ★★★ 초안 뼈대)
[/FULL_REPORT]
"""


def call_claude_headless(prompt: str) -> str:
    proc = subprocess.run(
        [CLAUDE_CLI, "-p", prompt,
         "--allowedTools", "WebSearch WebFetch",
         "--permission-mode", "dontAsk",
         "--output-format", "json",
         "--model", CLAUDE_CODE_MODEL],
        capture_output=True, text=True, timeout=CLAUDE_CODE_TIMEOUT,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RuntimeError(f"claude 헤드리스 실패(rc={proc.returncode}): {detail[:600] or '(출력 없음)'}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude 헤드리스 응답 JSON 파싱 실패: {(proc.stdout or '')[:600]}")
    if envelope.get("is_error"):
        raise RuntimeError(f"claude 헤드리스 오류 응답: {str(envelope.get('result'))[:600]}")
    return envelope.get("result", "")


def extract_block(text: str, tag: str) -> str:
    m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", text, re.S)
    return m.group(1).strip() if m else ""


def main():
    if os.environ.get("LLM_BACKEND", "api").strip().lower() != "claude_code":
        print("LLM_BACKEND != claude_code — 기사기획브리핑 건너뜀(구독코인 전용 기능)")
        return

    now = datetime.now(KST)
    today_compact = now.strftime("%Y%m%d")
    today_str = now.strftime("%Y년 %m월 %d일")

    date_key = now.strftime("%Y-%m-%d")  # collect.py가 실제로 쓰는 파일명 형식(대시 포함)
    briefing = _load_json(os.path.join(SOJAE_DIR, f"briefing_{date_key}.json"))
    if not briefing or not briefing.get("topics"):
        print(f"⚠️ sojaetimes 수집 결과 없음(briefing_{date_key}.json) — 브리핑 생략")
        return

    published = _load_json(ARTICLES_FILE) or {}
    published_titles = [a.get("title", "") for a in published.get("articles", []) if a.get("title")]

    total = briefing.get("total_count", sum(len(v) for v in briefing["topics"].values()))
    print(f"📊 국내 수집본 재사용: {total}건 ({briefing.get('date')})")
    print("🧠 기사기획 분석 중 (WebSearch/WebFetch 보강, 최대 30분)...")

    prompt = build_prompt(today_str, briefing["topics"], published_titles)
    try:
        result = call_claude_headless(prompt)
    except Exception as e:
        print(f"❌ 기사기획브리핑 생성 실패: {e}")
        return

    telegram_summary = extract_block(result, "TELEGRAM_SUMMARY")
    full_report = extract_block(result, "FULL_REPORT")
    if not full_report:
        print("⚠️ 응답 형식이 예상과 다름 — 원문 그대로 저장")
        full_report = result

    out_path = os.path.join(SOJAE_DIR, f"{today_compact}_소재타임스_기사기획브리핑.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# 소재타임스 기사 기획 브리핑 — {today_str}\n\n")
        f.write(full_report)
    print(f"✅ 브리핑 저장: {out_path}")

    header = f"📰 소재타임스 기사기획 브리핑 - {today_str}\n\n"
    msg = header + (telegram_summary or "(요약 파싱 실패 — 전체 리포트 파일 확인 필요)")
    msg += f"\n\n전체 리포트: {out_path}"
    send_telegram(msg[:4000])


if __name__ == "__main__":
    main()
