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
import tempfile


# ── 토큰 A단계(2026-11-26): AI 호출 1번마다 ~/Library/Logs/aios-usage.jsonl에 한 줄 기록 ──
# 컨트롤타워/사용량.js와 같은 형식. 기록 실패는 무시한다(발행에 영향 없음). 채널 이름은 저장소 폴더 이름.
_USAGE_FILE = os.path.expanduser("~/Library/Logs/aios-usage.jsonl")
_USAGE_CH = os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def _log_usage(who: str, job: str, sec: float, ok: bool, text: str = "", tokens=None) -> None:
    try:
        import datetime as _dt
        if tokens is None and who == "codex":
            m = re.search(r"tokens used\s*:?\s*([\d,]+)", text or "", re.I)
            tokens = int(m.group(1).replace(",", "")) if m else None
        limit = bool(re.search(r"usage limit|rate limit|quota|hit your limit|limit reached", (text or "")[-1500:], re.I)) and not ok
        if limit and who == "codex":
            _mark_codex_limit(job)
        with open(_USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                                "who": who, "job": f"{_USAGE_CH}:{job}", "sec": round(sec), "ok": ok,
                                "limit": limit, "tokens": tokens}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


# 토큰 C단계(2026-11-28): Codex 한도 신호 ~/Library/Logs/aios-limit.json — 어느 채널이든 한도를 만나면 기록하고,
# 오늘(한국 시각) 자정까지 선택 작업(사진 판정·AI 그림)은 쉬고 집필은 Claude가 바로 쓴다.
_LIMIT_FILE = os.path.expanduser("~/Library/Logs/aios-limit.json")


def _codex_limited() -> bool:
    import time as _tm
    try:
        with open(_LIMIT_FILE, encoding="utf-8") as f:
            l = json.load(f).get("codex")
        return bool(l) and _tm.time() * 1000 < l.get("until", 0)
    except Exception:  # noqa: BLE001
        return False


def _mark_codex_limit(job: str) -> None:
    try:
        import datetime as _dt
        kst = _dt.timezone(_dt.timedelta(hours=9))
        until = (_dt.datetime.now(kst) + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            with open(_LIMIT_FILE, encoding="utf-8") as f:
                cur = json.load(f)
        except Exception:  # noqa: BLE001
            cur = {}
        cur["codex"] = {"at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "job": f"{_USAGE_CH}:{job}", "until": int(until.timestamp() * 1000)}
        with open(_LIMIT_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f)
    except Exception:  # noqa: BLE001
        pass

# ── 설정 ──────────────────────────────────────────────
LLM_BACKEND        = os.environ.get("LLM_BACKEND", "api").strip().lower()
CLAUDE_CLI         = os.environ.get("CLAUDE_CLI", "claude")
CLAUDE_CODE_EFFORT = os.environ.get("CLAUDE_CODE_EFFORT", "medium")  # low|medium|high|xhigh|max
CLAUDE_CODE_MODEL  = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-6")
CLAUDE_CODE_TIMEOUT = int(os.environ.get("CLAUDE_CODE_TIMEOUT", "1200"))  # 초 — 시도 1회당 예산(총 예산 아님)
CLAUDE_CODE_RETRIES = int(os.environ.get("CLAUDE_CODE_RETRIES", "2"))    # 타임아웃(무응답) 시 재시도 횟수

# ── 집필 엔진 (2026-11-23 대표님 결정: "Codex가 쓰고 Claude가 검수") ──
# 구독 경로(LLM_BACKEND=claude_code)에서 **글을 쓰는 호출**만 Codex(ChatGPT 구독)로 보낸다.
# 검수(review_articles)·원문 대조(report_issues)·원문 대조 수정(save_fix)·기획 브리핑(save_briefing)은
# 그대로 Claude — 쓴 모델과 검수하는 모델을 다르게 둔다. Codex가 실패하면 같은 호출을 Claude가 대신 한다.
# 클라우드 백업(LLM_BACKEND=api)은 영향 없음 → 로컬=Codex, 클라우드=Claude로 장애가 갈린다.
#   LLM_WRITER=codex(기본) | claude(되돌리기)
LLM_WRITER    = os.environ.get("LLM_WRITER", "codex").strip().lower()
CODEX_TOOLS   = {t.strip() for t in os.environ.get(
    "CODEX_TOOLS", "save_articles,save_body,save_editorial,save_newsletter").split(",") if t.strip()}
CODEX_CLI     = os.environ.get("CODEX_CLI") or next(
    (p for p in (os.path.expanduser("~/.local/bin/codex"), "/opt/homebrew/bin/codex") if os.path.exists(p)), "codex")
CODEX_TIMEOUT = int(os.environ.get("CODEX_TIMEOUT", "1500"))  # 초 — 1회 예산

# 헤드리스 프로세스를 돌릴 작업 디렉터리 — TCC 보호 밖의 중립 위치여야 한다. (2026-08-06)
#
# ⚠️ **claude 헤드리스를 ~/Desktop 아래에서 실행하지 말 것.** launchd 자동발행이
#    2026-08-05부터 두 채널 모두 "완전 무응답 → 타임아웃"으로 죽은 원인이다.
#
#    claude는 기동 직후 getcwd()로 작업 디렉터리를 open() 하는데, cwd가 ~/Desktop
#    아래면 macOS TCC가 동의를 요구한다. 터미널에서는 부모 앱의 접근 권한으로
#    통과하지만, launchd 백그라운드 잡에는 동의 창을 띄울 상대가 없어 open()이
#    **영원히 블록된다.** 세션 로그(~/.claude/projects/**)조차 안 생기고 stdout이
#    한 줄도 안 나오므로, 호출부에서는 그냥 무응답 타임아웃으로 보인다.
#
#    2026-08-04 22:04 CLI 자동 업데이트(2.1.221)로 재발했다. TCC 승인은 바이너리
#    경로·서명 단위인데 자동 업데이트는 versions/<새버전>에 **새 바이너리**를 깔기
#    때문이다. 즉 바이너리에 권한을 부여해 두는 방식은 다음 자동 업데이트에 또 깨진다.
#    작업 디렉터리를 옮기는 것이 업데이트에 영향받지 않는 유일한 해법이다.
#
#    실측(launchd·같은 바이너리·같은 환경, "1+1" 프롬프트):
#      cwd=~/Desktop/…/시그널코리아 → 무한 대기 (네트워크 연결 0건)
#      cwd=/private/tmp/…           → 13초 정상 완료
#
#    덤으로 저장소 CLAUDE.md(시그널 30KB)를 매 호출 컨텍스트에 싣지 않게 되어
#    캐시 입력이 22,073토큰 → 6,404토큰으로 줄었다. 프롬프트는 자체 완결형이라
#    저장소 파일을 참조하지 않으므로 결과물에는 영향이 없다.
CLAUDE_CODE_CWD = os.environ.get(
    "CLAUDE_CODE_CWD", os.path.join(tempfile.gettempdir(), "aios-headless")
)


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
def call_tool(request_params: dict, tool_name: str, effort: str = "") -> dict:
    """anthropic messages 요청(request_params)을 Claude Code 헤드리스로 실행.

    tool_use 로 강제하던 구조화 출력을, JSON Schema를 그대로 프롬프트에 실어
    "순수 JSON만 출력" 지시로 대체한다. 지정한 tool 의 input_schema 에 맞는
    dict 를 반환한다. (= 기존 코드의 tool_block.input 과 동일한 형태)

    effort: 호출별 사고 깊이. 비우면 CLAUDE_CODE_EFFORT(기본 medium).
      **출력이 큰 기사 생성은 "low"를 쓴다.** 사고 토큰도 32,000 출력 상한을 함께
      먹기 때문이다. 검수처럼 출력이 작고 판단이 중요한 호출은 기본값을 그대로 둔다.
      (2026-08-06 실측 · 시그널 배치1 기사 3건, launchd)
        medium → 사고 14,895자 · 출력 29,491토큰 · 561초 (상한 아슬아슬, 한 번은
                 32,000+32,000+1,203으로 턴이 갈려 실패)
        low    → 사고 0자      · 출력 13,702토큰 · 247초 (상한 대비 57% 여유)
      low 산출물도 5단계 단락 수·현장 경험 문단·금지표현·카테고리 쿼터를 모두 지켰다.
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

    # 타임아웃(무응답)만 재시도한다 — --output-format json은 완료 전까지 아무것도
    # 안 보여줘서 "서버가 느린 것"과 "진짜 멈춘 것"을 클라이언트에서 구분할 수 없다.
    # 실측상 재시도가 잘 통했다(멈춘 것처럼 보인 시도 직후 재시도가 수 분 내 성공).
    # rc!=0/JSON 오류 등 프로세스가 실제로 끝난 실패는 반복해도 같은 결과일 가능성이
    # 높으므로 재시도하지 않고 바로 올린다.
    # TCC 블록을 피하려면 cwd가 ~/Desktop 밖이어야 한다 (위 CLAUDE_CODE_CWD 주석 참조)
    os.makedirs(CLAUDE_CODE_CWD, exist_ok=True)

    if LLM_WRITER == "codex" and tool_name in CODEX_TOOLS and not _codex_limited():
        try:
            return _call_codex(full_prompt, tool)
        except Exception as e:  # noqa: BLE001 — 어떤 실패든 Claude가 이어받는다
            print(f"⚠️ Codex 집필 실패({tool_name}) → Claude로 대신 씀: {str(e)[:300]}")

    import time as _time
    for attempt in range(1, CLAUDE_CODE_RETRIES + 1):
        _t0 = _time.time()
        try:
            proc = subprocess.run(
                [CLAUDE_CLI, "-p", full_prompt,
                 "--output-format", "json",
                 "--model", CLAUDE_CODE_MODEL,
                 # 구조화 JSON 생성에 도구가 필요 없다. 프롬프트로만 금지하면 모델이
                 # 파일을 뒤지거나 검색을 시도해 턴이 늘어난다(2026-08-02 실패 응답의
                 # num_turns=2). 아예 막아 한 번에 끝내게 한다.
                 "--disallowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep",
                 "WebSearch", "WebFetch", "Task",
                 # 사고 깊이 제한. 정해진 스키마를 채우는 작업이라 깊은 추론이 불필요한데,
                 # 기본값으로 두면 사고 토큰이 폭주한다 — 같은 실패 응답에서 출력이
                 # 75,532토큰(기대치의 약 10배)까지 부풀어 rc=1로 끝났다.
                 "--effort", effort or CLAUDE_CODE_EFFORT],
                capture_output=True, text=True, timeout=CLAUDE_CODE_TIMEOUT,
                cwd=CLAUDE_CODE_CWD,
            )
        except subprocess.TimeoutExpired:
            _log_usage("claude", tool_name, _time.time() - _t0, False)
            more = attempt < CLAUDE_CODE_RETRIES
            print(f"⏱️ claude 헤드리스 {CLAUDE_CODE_TIMEOUT}s 무응답 (시도 {attempt}/{CLAUDE_CODE_RETRIES}) — "
                  f"{'재시도' if more else '포기'}")
            if more:
                continue
            raise RuntimeError(
                f"claude 헤드리스 {CLAUDE_CODE_RETRIES}회 모두 {CLAUDE_CODE_TIMEOUT}s 타임아웃(무응답)"
            )

        try:
            _env = json.loads(proc.stdout or "{}")
            _u = _env.get("usage") or {}
            _tok = sum(_u.get(k) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")) or None
        except Exception:  # noqa: BLE001
            _env, _tok = {}, None
        _log_usage("claude", tool_name, _time.time() - _t0, proc.returncode == 0 and not _env.get("is_error"),
                   f"{proc.stderr or ''}\n{_env.get('result') if _env.get('is_error') else ''}", _tok)

        if proc.returncode != 0:
            # 오류 상세는 stderr가 비어 있을 때가 많아 stdout(JSON 응답의 result 등)도 함께 노출
            detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
            raise RuntimeError(
                f"claude 헤드리스 실패(rc={proc.returncode}): {detail[:600] or '(출력 없음 — rate limit/네트워크 의심)'}"
            )

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"claude 헤드리스 응답 JSON 파싱 실패: {(proc.stdout or '')[:600]}")
        if envelope.get("is_error"):
            raise RuntimeError(f"claude 헤드리스 오류 응답: {str(envelope.get('result'))[:600]}")

        data = _parse_json(envelope.get("result", ""))

        # 출력이 32,000토큰 상한(stop_reason=max_tokens)에 걸리면 헤드리스가 턴을 이어서
        # 마저 쓰는데, envelope["result"]에는 **마지막 턴의 조각만** 담긴다. 그러면 앞부분이
        # 잘린 JSON이 오고, json_repair가 그럴듯한 dict로 복구해버려 최상위 키가 통째로
        # 사라진 채 통과한다 → 호출부에서 KeyError로 엉뚱하게 터진다. (2026-08-06 실측:
        # num_turns=3, 32000+32000+1203 토큰, result는 기사 배열 중간부터 시작)
        # 여기서 스키마의 필수 키 유무로 잡아 원인이 드러나는 메시지를 남긴다.
        missing = [k for k in tool["input_schema"].get("required", []) if k not in data]
        if missing:
            turns = envelope.get("num_turns")
            raise RuntimeError(
                f"claude 헤드리스 응답에 필수 키 {missing} 없음 (num_turns={turns}). "
                f"출력이 32,000토큰 상한을 넘어 턴이 이어지면 마지막 조각만 돌아온다 — "
                f"배치 크기를 줄이거나 CLAUDE_CODE_EFFORT를 낮춰 출력을 줄일 것."
            )
        return data


# ── Codex 집필 호출 ───────────────────────────────────
def _call_codex(full_prompt: str, tool: dict) -> dict:
    """같은 프롬프트(스키마 포함)를 Codex CLI(ChatGPT 구독)로 실행해 dict를 돌려준다.
    --output-schema는 쓰지 않는다 — OpenAI 구조화 출력은 additionalProperties:false·전 필드 required를
    요구해 기존 스키마가 거부될 수 있다. Claude 경로와 같은 '스키마를 프롬프트에 싣고 JSON만 받기' 방식."""
    import time
    os.makedirs(CLAUDE_CODE_CWD, exist_ok=True)  # Desktop 밖 (절대 규칙 10)
    out_path = os.path.join(CLAUDE_CODE_CWD, f"codex-{os.getpid()}-{int(time.time()*1000)}.txt")
    env = {**os.environ, "OPENAI_API_KEY": "",  # 구독 로그인만 쓴다
           "PATH": f"{os.path.expanduser('~/.local/bin')}:/opt/homebrew/bin:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    t0 = time.time()
    try:
        proc = subprocess.run(
            [CODEX_CLI, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
             "-C", CLAUDE_CODE_CWD, "-c", 'model_reasoning_effort="low"', "-o", out_path, "-"],
            input=full_prompt, capture_output=True, text=True, timeout=CODEX_TIMEOUT, env=env,
        )
    except subprocess.TimeoutExpired:
        _log_usage("codex", "write", time.time() - t0, False)
        raise RuntimeError(f"codex {CODEX_TIMEOUT}s 타임아웃")
    _log_usage("codex", "write", time.time() - t0, proc.returncode == 0, proc.stderr or "")
    if not os.path.exists(out_path):
        tail = " | ".join([l for l in (proc.stderr or "").splitlines() if l.strip()][-3:])[:300]
        raise RuntimeError(f"codex 출력 없음(rc={proc.returncode}): {tail}")
    with open(out_path, encoding="utf8") as f:
        text = f.read()
    os.remove(out_path)
    data = _parse_json(text)
    missing = [k for k in tool["input_schema"].get("required", []) if k not in data]
    if missing:
        raise RuntimeError(f"codex 응답에 필수 키 {missing} 없음")
    print(f"✍️ 집필: Codex ({tool['name']}, {int(time.time() - t0)}초)")
    return data
