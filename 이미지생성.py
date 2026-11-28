"""AI 설명 도식 생성 + 스톡 사진 적합성 판정 — 기사자동생성.py·기사검수.py 공용.

배경(2026-11-22): 스톡 사진 검색이 기사와 맞지 않는 사진을 가져오는 일이 있다
(AI 반도체 규제 기사에 컨테이너선 사진). 풀·picsum 폴백은 처음부터 무관한 사진이다.
그래서 ① 스톡 사진이 기사와 맞는지 ChatGPT(Codex 구독)가 보고, 안 맞거나 ② 검색이 실패하면
기사 내용을 설명하는 AI 도식을 만들어 쓴다. 실제 사진이 있고 맞으면 그대로 쓴다.

- 구독만 쓴다: `codex exec`(ChatGPT 로그인). OPENAI_API_KEY는 비워서 호출한다.
- 로컬 맥 전용. 깃허브 클라우드(GITHUB_ACTIONS)나 codex가 없으면 아무것도 하지 않고 기존 경로를 쓴다.
- 끄기: 환경변수 AI_IMAGE=0 (도식 생성·적합성 판정 모두), AI_IMAGE_VISION=0 (적합성 판정만).
- 도식에는 반드시 "[AI 생성 일러스트]" 캡션을 붙인다(`CAPTION`) — 호출부가 article["image_caption"]에 넣는다.

AI 실사 이미지 시범 (2026-11-25 ~ 12-09, 대표님 결정, 소재타임스만):
- 기사의 중심이 소재·장비·공정 같은 '사물'이면 사진처럼 보이는 정물(still-life) 이미지를, 흐름·구조·정책이면 도식을 만든다.
  Codex가 한 번의 호출에서 고르고 마지막 줄에 PHOTO/DIAGRAM을 적는다.
- 사건이 아니라 사물만 그린다: 사람·얼굴·손, 글자·숫자·로고, 국기, 실존 건물·시설, 기업 표시, 사건 장면 금지.
  원문(보도) 사진을 바탕으로 만들지 않는다 — 저작권(2차 저작물)과 가짜 보도사진 위험(대표님과 합의).
- 실사는 만든 뒤 금지 요소를 이미지로 다시 판정(`_photo_clean`)하고, 걸리거나 판정을 못 하면 도식으로 다시 만든다.
- 캡션: 실사는 `PHOTO_CAPTION`("[AI 생성 이미지] …실제 사진이 아닙니다"), 도식은 `CAPTION`. 기사에 image_ai_type(photo/diagram).
- 끄기: AI_IMAGE_PHOTO=0 → 예전처럼 도식만.

    python3 이미지생성.py "기사 제목" "image keyword"   # 도식 1장 시험 생성 → /tmp 경로 출력
"""

from __future__ import annotations

import glob
import io
import os
import re
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Optional

CAPTION = "[AI 생성 일러스트] 기사 내용을 설명하는 도식이며 실제 사진이 아닙니다."
PHOTO_CAPTION = "[AI 생성 이미지] 기사 내용을 바탕으로 만든 참고 이미지이며 실제 사진이 아닙니다."
_AI_CAPTIONS = (CAPTION, PHOTO_CAPTION)
_MODES: dict = {}  # 최종 이미지 경로 → "photo"/"diagram" (호출부가 .ai.tmp에 만든 뒤 제 경로로 옮긴다)

_CODEX = next(
    (p for p in (os.path.expanduser("~/.local/bin/codex"), "/opt/homebrew/bin/codex") if os.path.exists(p)),
    shutil.which("codex") or "",
)
# 헤드리스는 ~/Desktop 아래 cwd에서 돌리지 않는다 (launchd TCC 무한 대기)
_WORK = os.path.join(tempfile.gettempdir(), "aios-headless", "news-image")
_GEN_DIR = os.path.expanduser("~/.codex/generated_images")

_down = False  # 로그인 만료·한도 오류를 한 번 만나면 이번 실행에서는 더 시도하지 않는다



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
    try:
        with open(_LIMIT_FILE, encoding="utf-8") as f:
            l = json.load(f).get("codex")
        return bool(l) and time.time() * 1000 < l.get("until", 0)
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

def enabled() -> bool:
    if os.environ.get("AI_IMAGE", "1") == "0" or os.environ.get("GITHUB_ACTIONS"):
        return False
    return bool(_CODEX) and not _down and not _codex_limited()


def vision_enabled() -> bool:
    return enabled() and os.environ.get("AI_IMAGE_VISION", "1") != "0"


def photo_mode_enabled() -> bool:
    return enabled() and os.environ.get("AI_IMAGE_PHOTO", "1") != "0"


def _run(prompt: str, effort: str, timeout: int, image: Optional[str] = None, cwd: Optional[str] = None):
    """codex exec 한 번. (returncode, 마지막 메시지, stderr 꼬리)."""
    global _down
    work = cwd or os.path.join(_WORK, uuid.uuid4().hex[:8])
    os.makedirs(work, exist_ok=True)
    out = os.path.join(work, "last.txt")
    cmd = [_CODEX, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "workspace-write",
           "-C", work, "-c", f'model_reasoning_effort="{effort}"', "-o", out]
    if image:
        cmd += ["-i", image]
    cmd.append("-")
    env = dict(os.environ, OPENAI_API_KEY="")
    _job = "photo-check" if image else "image"
    _t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        _log_usage("codex", _job, time.time() - _t0, False)
        return 124, "", "timeout"
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)
    _log_usage("codex", _job, time.time() - _t0, p.returncode == 0, p.stderr or "")
    tail = (p.stderr or "")[-400:]
    low = tail.lower()
    if p.returncode != 0 and any(k in low for k in ("login", "usage limit", "quota", "rate limit", "unauthorized")):
        _down = True
        print(f"   ⚠️  ChatGPT(Codex) 사용 불가 — 이번 실행은 AI 이미지를 건너뜀: {tail[-120:].strip()}")
    last = ""
    if os.path.exists(out):
        with open(out, "r", encoding="utf-8", errors="ignore") as f:
            last = f.read().strip()
    return p.returncode, last, tail


def photo_fits(content: bytes, title: str, keyword: str) -> Optional[bool]:
    """스톡 사진이 기사에 어울리는지. True/False, 판정 못 하면 None(→ 사진을 그대로 쓴다)."""
    if not vision_enabled():
        return None
    work = os.path.join(_WORK, uuid.uuid4().hex[:8])
    os.makedirs(work, exist_ok=True)
    img = os.path.join(work, "photo.jpg")
    try:
        with open(img, "wb") as f:
            f.write(content)
        prompt = (
            "You are a news photo editor. The attached image is proposed as the lead picture for a Korean "
            "business news article.\n"
            f'Article title: "{title}"\nTopic keywords: {keyword}\n'
            "Does the image visibly relate to the article's subject (the industry, material, technology or "
            "policy it covers, or a clear visual metaphor for it)? A generic or unrelated scene (for example "
            "ships, landscapes, food, or people unrelated to the topic) does NOT fit.\n"
            "Answer with exactly one word: FIT or MISMATCH."
        )
        rc, last, _ = _run(prompt, "low", 240, image=img, cwd=work)
        word = last.strip().upper()
        if rc != 0 or not word:
            return None
        if word.startswith("MISMATCH"):
            return False
        if word.startswith("FIT"):
            return True
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


_STYLE = (
    "Flat modern editorial vector illustration (infographic style) for a Korean business newspaper. "
    "Clean shapes, a clear central subject with a few supporting icons, generous negative space. "
    "Color palette: deep blue (#0057a8), navy, light grey-blue background, with a small red (#c8102e) accent. "
    "16:9 landscape composition."
)
_RULES = (
    "Hard rules: absolutely no text, letters, numbers or logos anywhere in the image; no real people or faces; "
    "no national flags; no recognizable real buildings, landmarks or government facilities; no company or brand marks; "
    "it must not look like a photograph or like documentary evidence of a real event. Show the concept, not a scene."
)


_PHOTO_STYLE = (
    "Photorealistic editorial still-life photograph, like a stock photo for a materials-industry newspaper: "
    "a close-up or studio/industrial shot of the PHYSICAL OBJECT the article is about (a raw material, metal, "
    "powder, ingot, wafer, battery cell, component, machine part or production process detail). "
    "Natural lighting, shallow depth of field, neutral background. 16:9 landscape composition."
)
_PHOTO_RULES = (
    "Hard rules: absolutely no text, letters, numbers, labels or logos anywhere; no people, faces or hands; "
    "no national flags; no recognizable real buildings, factories, landmarks or government facilities; no company "
    "or brand marks; do not depict a specific news event, meeting, accident or announcement. Show the object only."
)


def _photo_clean(path: str) -> Optional[bool]:
    """AI 실사가 금지 요소 없이 나왔는지. True=깨끗, False=위반, None=판정 못 함."""
    rc, last, _ = _run(
        "You are a strict news photo editor checking an AI-generated illustrative image before publication.\n"
        "Answer VIOLATION if the image contains ANY of: a person, face or hand; readable text, letters, numbers "
        "or labels; a logo or brand mark; a national flag; a recognizable real building or landmark; or a scene "
        "that looks like documentary evidence of a specific news event. Otherwise answer CLEAN.\n"
        "Answer with exactly one word: CLEAN or VIOLATION.",
        "low", 240, image=path)
    word = last.strip().upper()
    if rc != 0 or not word:
        return None
    if word.startswith("VIOLATION"):
        return False
    if word.startswith("CLEAN"):
        return True
    return None


def _final_path(out_path: str) -> str:
    p = out_path[:-len(".ai.tmp")] if out_path.endswith(".ai.tmp") else out_path
    return os.path.normpath(p)


def generate(title: str, keyword: str, category: str, out_path: str) -> bool:
    """기사 이미지 1장(AI 실사 또는 도식)을 out_path(.jpg, 가로 1200px)에 저장. 성공 시 True.
    실사가 금지 요소 판정에 걸리면 같은 자리에 도식을 다시 만든다."""
    if not enabled():
        return False
    if photo_mode_enabled():
        mode = _generate_once(title, keyword, category, out_path, allow_photo=True)
        if mode == "photo":
            clean = _photo_clean(out_path)
            if clean is True:
                _MODES[_final_path(out_path)] = "photo"
                print("   → AI 실사 이미지 (금지 요소 없음)")
                return True
            print(f"   → AI 실사 {'금지 요소 발견' if clean is False else '판정 실패'} — 도식으로 다시 만듦")
        elif mode == "diagram":
            _MODES[_final_path(out_path)] = "diagram"
            return True
        elif not enabled():
            return False
    if _generate_once(title, keyword, category, out_path, allow_photo=False):
        _MODES[_final_path(out_path)] = "diagram"
        return True
    return False


def _generate_once(title: str, keyword: str, category: str, out_path: str, allow_photo: bool) -> Optional[str]:
    """이미지 1장 생성. 성공 시 "photo"/"diagram", 실패 시 None."""
    from PIL import Image

    work = os.path.join(_WORK, uuid.uuid4().hex[:8])
    os.makedirs(work, exist_ok=True)
    started = time.time()
    try:
        if allow_photo:
            prompt = (
                "Use your image generation tool to create ONE image, then copy the generated file into the current "
                "directory as image.png.\n"
                f"News article title: \"{title}\" (category: {category or 'industry'}; keywords: {keyword}).\n"
                "First decide the format:\n"
                "- PHOTO if the article is mainly about a physical material, metal, mineral, component, piece of "
                "equipment or production process that can be shown as an object.\n"
                "- DIAGRAM if it is mainly about policy, trade flows, prices, markets, companies' strategy or any "
                "relationship that an object photo cannot explain.\n"
                f"If PHOTO: {_PHOTO_STYLE}\n{_PHOTO_RULES}\n"
                f"If DIAGRAM: an explanatory diagram. {_STYLE}\n{_RULES}\n"
                "Your final message must be exactly one word: PHOTO or DIAGRAM (the format you made)."
            )
        else:
            prompt = (
                "Use your image generation tool to create ONE image, then copy the generated file into the current "
                "directory as image.png. Do nothing else.\n"
                f"Subject: an explanatory diagram for the news article titled \"{title}\" "
                f"(category: {category or 'industry'}; keywords: {keyword}).\n"
                f"{_STYLE}\n{_RULES}"
            )
        rc, last, tail = _run(prompt, "low", 420, cwd=work)
        src = os.path.join(work, "image.png")
        if not os.path.exists(src):  # 복사를 못 했으면 Codex가 만든 최신 파일을 찾는다
            fresh = [p for p in glob.glob(os.path.join(_GEN_DIR, "*", "*.png")) if os.path.getmtime(p) >= started - 2]
            src = max(fresh, key=os.path.getmtime) if fresh else ""
        if rc != 0 and not src:
            print(f"   → AI 이미지 생성 실패(rc={rc}): {tail[-120:].strip()}")
            return None
        if not src:
            print("   → AI 이미지 생성 실패: 이미지 파일 없음")
            return None
        im = Image.open(src).convert("RGB")
        if im.width < 600:
            return None
        h = round(1200 * im.height / im.width)
        im = im.resize((1200, h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        data = buf.getvalue()
        if len(data) < 5000:
            return None
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        # 실사 모드에서 형식을 못 밝혔으면 실사로 보고 금지 요소 판정을 거치게 한다(안전한 쪽)
        if allow_photo and not last.strip().upper().startswith("DIAGRAM"):
            return "photo"
        return "diagram"
    except Exception as e:  # noqa: BLE001
        print(f"   → AI 이미지 오류: {e}")
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def mark(article: dict, ai: bool) -> None:
    """기사에 AI 도식 캡션을 붙이거나(ai=True), 이전에 붙은 AI 캡션을 거둔다(실제 사진으로 바뀐 경우).
    직접 쓴 image_caption(수동 기사)은 건드리지 않는다."""
    if ai:
        kind = _MODES.get(os.path.normpath(article.get("image_url") or ""), "diagram")
        article["image_ai"] = True
        article["image_ai_type"] = kind
        article["image_caption"] = PHOTO_CAPTION if kind == "photo" else CAPTION
    elif article.get("image_ai"):
        article.pop("image_ai", None)
        article.pop("image_ai_type", None)
        if article.get("image_caption") in _AI_CAPTIONS:
            article.pop("image_caption", None)


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "미 상무부, AI 반도체 해외 데이터센터 접근 신규 규제"
    k = sys.argv[2] if len(sys.argv) > 2 else "semiconductor export control regulation"
    out = os.path.join(tempfile.gettempdir(), "aios-headless", "news-image-test.jpg")
    print("enabled:", enabled(), "| codex:", _CODEX)
    ok = generate(t, k, "글로벌", out)
    print("생성:", ok, _MODES.get(_final_path(out)), out if ok else "")
