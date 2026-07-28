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

## 2단계 구조(2026-07-28 개선)
WebSearch/WebFetch 도구 호출과 대용량 최종 리포트 작성을 한 턴에 같이
시키면 출력이 상한 근처에서 잘리는 문제가 있었다(마커는 닫혔는데 내용이
문장 중간부터 시작하는 등). 그래서 두 번의 헤드리스 호출로 나눈다:
  1) 조사 전용 호출 — WebSearch/WebFetch만 허용, 결과는 짧은 사실 요약(≤1200자)
  2) 분석 전용 호출 — 도구 사용 없이 llm_backend.call_tool()로 JSON 강제
     (기사자동생성.py와 동일한 검증된 경로 재사용 — 도구 호출 오버헤드 없이
     순수 텍스트 생성이라 대용량 출력에 더 안정적)
1)이 실패해도 국내 수집본만으로 2)를 진행한다(전체 실패로 이어지지 않음).

LLM_BACKEND=claude_code 가 아니면(API코인/클라우드 경로) 건너뛴다.
이 브리핑은 편집 지원용 부가 기능이라 별도의 클라우드 백업 경로를
만들지 않는다 — 실패해도 본 발행 파이프라인(기사자동생성/기사검수)에는
영향 없음.
"""

from __future__ import annotations

import json
import os
import subprocess
import requests
from datetime import datetime, timezone, timedelta

import llm_backend  # 기사자동생성.py/기사검수.py와 동일한 구독코인 JSON 강제 경로 재사용

KST = timezone(timedelta(hours=9))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CLAUDE_CLI = os.environ.get("CLAUDE_CLI", "claude")
CLAUDE_CODE_MODEL = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-6")
RESEARCH_TIMEOUT = int(os.environ.get("BRIEFING_RESEARCH_TIMEOUT", "600"))  # 조사 호출(도구 사용)은 별도 예산

SOJAE_DIR = "sojaetimes"
ARTICLES_FILE = "articles.json"

RESEARCH_PROMPT = """WebSearch로 아래 영어 키워드를 검색하고, WebFetch로 아래 일본어/중국어 매체를 확인해
글로벌 반도체·디스플레이·배터리 소재 이슈를 조사하세요. 사이트 접속이 실패하면 그냥 건너뛰고 계속 진행하세요.

[WebSearch 키워드]
- "semiconductor materials China export control latest"
- "critical minerals supply chain disruption"
- "solid-state battery materials breakthrough"
- "OLED materials new development"
- "rare earth export restriction China"
- "CHIPS Act materials semiconductor supply"

[WebFetch 대상]
- https://xtech.nikkei.com (일본 반도체/소재 기술)
- https://www.dempa-digital.com (일본 디스플레이/배터리)
- https://www.iczhiku.com (중국 반도체 소재)
- https://www.cls.cn/telegraph (중국 광물/소재 시장)

조사가 끝나면 한국의 소재·부품·장비 업계에 의미 있을 만한 새 이슈만 골라
아래 형식으로만 출력하세요(분석·기사각도는 쓰지 말고 사실 요약만):

- [이슈 제목] (출처, 날짜): 한 줄 요약

최대 8개, 전체 1200자 이내. 다른 설명이나 인사말 없이 목록만 출력하세요.
발견한 이슈가 없으면 "글로벌 특이 이슈 없음"이라고만 출력하세요."""


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


def call_research() -> str:
    """WebSearch/WebFetch 전용 호출 — 도구 사용과 최종 리포트 작성을 분리해
    한 턴에 몰아서 쓰다 출력이 잘리는 문제를 피한다."""
    proc = subprocess.run(
        [CLAUDE_CLI, "-p", RESEARCH_PROMPT,
         "--allowedTools", "WebSearch WebFetch",
         "--permission-mode", "dontAsk",
         "--output-format", "json",
         "--model", CLAUDE_CODE_MODEL],
        capture_output=True, text=True, timeout=RESEARCH_TIMEOUT,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RuntimeError(f"조사 호출 실패(rc={proc.returncode}): {detail[:400] or '(출력 없음)'}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"조사 호출 오류 응답: {str(envelope.get('result'))[:400]}")
    return (envelope.get("result") or "").strip()


def build_analysis_prompt(today_str: str, topics: dict, global_digest: str,
                           published_titles: list[str]) -> str:
    topics_text = json.dumps(topics, ensure_ascii=False, indent=2)
    published_text = "\n".join(f"- {t}" for t in published_titles) or "(오늘 발행 기사 없음)"

    return f"""당신은 소재타임스(소재·부품·장비 전문 매체) 기사 기획 지원 에이전트입니다.
바쁜 기자들이 놓칠 수 있는 이슈를 선제적으로 발굴하고, 취재 방향과 기사 각도까지 제시하는 것이 목적입니다.
오늘 날짜: {today_str}

[국내 수집본 — 이미 수집 완료]
{topics_text}

[글로벌 보강 수집 — 이미 완료]
{global_digest or "(조사 실패 — 국내 수집본만으로 진행)"}

[오늘 소재타임스에 이미 발행된 기사 제목 — 5건]
{published_text}

## 분석 지침 — 출력 분량을 반드시 지킬 것 (전체 응답이 잘리는 것을 방지하기 위함)

1. **전체 이슈 요약표**: 국내+글로벌 이슈를 모두 훑어 한 줄씩(등급|제목|분야|출처|취재포인트).
   최대 20행.
2. **★★★ 등급만** 아래 5가지를 전부 분석: [A]중요도 근거 [B]독자 관점(2~3문장)
   [C]기사 각도(최대 3개) [D]추천 취재원 유형 [E]선행 보도 가능성.
   최대 5건. 위 "오늘 이미 발행된 기사 제목"과 사실상 같은 이슈면 [E]를
   "오늘 소재타임스에 이미 발행됨 — 후속 심화 필요"로 쓰고 초안 뼈대는 만들지 마세요.
3. **★★ 등급**: 분야별로 제목 + 기사 각도 한 줄만. [A]~[E] 전체 분석은 쓰지 마세요.
4. **★ 등급**: 요약표에만 남기고 별도 설명 없음.
5. **★★★이면서 오늘 미발행**인 이슈에 한해 기사 초안 뼈대(제목 후보 3개, 리드 후보,
   구성 제안, 필수 확인 사항)를 추가하세요.

등급 기준 — ★★★: 공급망 직접 충격/수출규제 신규 발표/대형 생산 중단·전환.
★★: 신기술 개발/주요 투자·M&A/정부 R&D. ★: 시장 동향/리포트/학술 연구.

## 주의사항
- 중복 기사 제거(동일 이슈 다른 매체는 1건으로 통합), 단순 주가/시황 기사 제외
- 3일 이상 오래된 기사 제외, 중국 수출규제 이슈 최우선 체크
- 이슈가 없는 분야는 "오늘 특이 이슈 없음"으로 표시
- full_report_markdown 전체 분량은 6000자를 넘기지 마세요(넘을 것 같으면 ★★ 항목부터 줄이세요)

telegram_summary는 순수 텍스트만 사용하고(HTML 태그, 마크다운 기호 금지) 3000자를 넘기지 마세요.
★★★ 이슈 제목과 한 줄 기사각도, ★★ 이슈 제목만 분야별 나열, 마지막 줄에
"총 N건 분석 | ★★★ N건 | ★★ N건" 형식으로 마무리하세요."""


def run_analysis(today_str: str, topics: dict, global_digest: str,
                  published_titles: list[str]) -> dict:
    prompt = build_analysis_prompt(today_str, topics, global_digest, published_titles)
    request_params = {
        "messages": [{"content": prompt}],
        "tools": [{
            "name": "save_briefing",
            "input_schema": {
                "type": "object",
                "properties": {
                    "telegram_summary": {"type": "string"},
                    "full_report_markdown": {"type": "string"},
                },
                "required": ["telegram_summary", "full_report_markdown"],
            },
        }],
    }
    return llm_backend.call_tool(request_params, "save_briefing")


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

    print("🌐 글로벌 보강 조사 중 (WebSearch/WebFetch, 최대 10분)...")
    try:
        global_digest = call_research()
        print(f"   → {len(global_digest)}자 확보")
    except Exception as e:
        print(f"   ⚠️ 조사 실패({e}) — 국내 수집본만으로 진행")
        global_digest = ""

    print("🧠 기사기획 분석 중...")
    try:
        data = run_analysis(today_str, briefing["topics"], global_digest, published_titles)
        telegram_summary = data.get("telegram_summary", "")
        full_report = data.get("full_report_markdown", "")
    except Exception as e:
        print(f"❌ 기사기획브리핑 분석 실패: {e}")
        return

    if not full_report:
        print("⚠️ full_report_markdown 비어있음 — 저장 생략")
        return

    out_path = os.path.join(SOJAE_DIR, f"{today_compact}_소재타임스_기사기획브리핑.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# 소재타임스 기사 기획 브리핑 — {today_str}\n\n")
        f.write(full_report)
    print(f"✅ 브리핑 저장: {out_path} ({len(full_report)}자)")

    header = f"📰 소재타임스 기사기획 브리핑 - {today_str}\n\n"
    msg = header + (telegram_summary or "(요약 없음 — 전체 리포트 파일 확인 필요)")
    msg += f"\n\n전체 리포트: {out_path}"
    send_telegram(msg[:4000])


if __name__ == "__main__":
    main()
