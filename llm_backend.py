"""
LLM 백엔드 전환 — 구독코인(로컬 Claude Code) vs API코인(anthropic SDK).

환경변수 LLM_BACKEND:
  - "claude_code" : 로컬 Claude Code 헤드리스 호출 = 구독코인 사용 (맥에서 실행)
  - "api"(기본)   : anthropic SDK + ANTHROPIC_API_KEY = API코인 사용 (GitHub Actions)

기사자동생성.py / 기사검수.py 가 이 모듈을 import 해서,
tool_use 로 강제하던 구조화 출력을 백엔드에 따라 갈라 처리한다.
API 경로는 각 스크립트에 그대로 남겨두고, 구독 경로만 여기서 담당한다.
"""

import json
import os
import re
import subprocess

# ── 설정 ──────────────────────────────────────────────
LLM_BACKEND        = os.environ.get("LLM_BACKEND", "api").strip().lower()
CLAUDE_CLI         = os.environ.get("CLAUDE_CLI", "claude")
CLAUDE_CODE_MODEL  = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-6")
CLAUDE_CODE_TIMEOUT = int(os.environ.get("CLAUDE_CODE_TIMEOUT", "900"))  # 초


def using_subscription() -> bool:
    """구독코인(로컬 Claude Code) 백엔드로 동작 중이면 True."""
    return LLM_BACKEND == "claude_code"


def backend_label() -> str:
    return "구독코인(Claude Code)" if using_subscription() else "API코인(anthropic SDK)"


# ── JSON 추출 유틸 ─────────────────────────────────────
def _extract_json_object(text: str) -> str:
    """헤드리스 응답에서 첫 '{' ~ 마지막 '}' 구간만 뽑아낸다 (코드펜스·설명 제거)."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        t = t.strip()
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j != -1 and j > i:
        return t[i:j + 1]
    return t


def _parse_json(text: str) -> dict:
    cleaned = _extract_json_object(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 마지막 방어선: json_repair (기사자동생성.py 의존성에 이미 포함)
        from json_repair import repair_json
        return json.loads(repair_json(cleaned))


# ── 구독코인 헤드리스 호출 ───────────────────────────────
def call_tool(request_params: dict, tool_name: str) -> dict:
    """anthropic messages 요청(request_params)을 Claude Code 헤드리스로 실행.

    tool_use 로 강제하던 구조화 출력을, JSON Schema를 그대로 프롬프트에 실어
    "순수 JSON만 출력" 지시로 대체한다. 지정한 tool 의 input_schema 에 맞는
    dict 를 반환한다. (= 기존 코드의 tool_block.input 과 동일한 형태)
    """
    tool = next(t for t in request_params["tools"] if t["name"] == tool_name)
    schema = json.dumps(tool["input_schema"], ensure_ascii=False, indent=2)
    user_prompt = request_params["messages"][0]["content"]

    full_prompt = (
        f"{user_prompt}\n\n"
        f"[출력 형식 — 반드시 지킬 것]\n"
        f"- 어떤 도구도 사용하지 말고, 파일도 만들지 마세요.\n"
        f"- 아래 JSON Schema에 정확히 부합하는 JSON 객체 **하나만** 출력하세요.\n"
        f"- 설명 문장, 코드펜스(```), JSON 앞뒤 텍스트를 절대 붙이지 마세요.\n"
        f"- 응답 전체가 그대로 json.loads() 로 파싱 가능해야 합니다.\n\n"
        f"[JSON Schema]\n{schema}\n"
    )

    proc = subprocess.run(
        [CLAUDE_CLI, "-p", full_prompt,
         "--output-format", "json",
         "--model", CLAUDE_CODE_MODEL],
        capture_output=True, text=True, timeout=CLAUDE_CODE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude 헤드리스 실패(rc={proc.returncode}): {proc.stderr[:400]}"
        )

    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude 헤드리스 오류 응답: {str(envelope.get('result'))[:400]}")

    return _parse_json(envelope.get("result", ""))
