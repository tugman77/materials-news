"""AI 설명 도식 생성 + 스톡 사진 적합성 판정 — 기사자동생성.py·기사검수.py 공용.

배경(2026-11-22): 스톡 사진 검색이 기사와 맞지 않는 사진을 가져오는 일이 있다
(AI 반도체 규제 기사에 컨테이너선 사진). 풀·picsum 폴백은 처음부터 무관한 사진이다.
그래서 ① 스톡 사진이 기사와 맞는지 ChatGPT(Codex 구독)가 보고, 안 맞거나 ② 검색이 실패하면
기사 내용을 설명하는 AI 도식을 만들어 쓴다. 실제 사진이 있고 맞으면 그대로 쓴다.

- 구독만 쓴다: `codex exec`(ChatGPT 로그인). OPENAI_API_KEY는 비워서 호출한다.
- 로컬 맥 전용. 깃허브 클라우드(GITHUB_ACTIONS)나 codex가 없으면 아무것도 하지 않고 기존 경로를 쓴다.
- 끄기: 환경변수 AI_IMAGE=0 (도식 생성·적합성 판정 모두), AI_IMAGE_VISION=0 (적합성 판정만).
- 도식에는 반드시 "[AI 생성 일러스트]" 캡션을 붙인다(`CAPTION`) — 호출부가 article["image_caption"]에 넣는다.

    python3 이미지생성.py "기사 제목" "image keyword"   # 도식 1장 시험 생성 → /tmp 경로 출력
"""

from __future__ import annotations

import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Optional

CAPTION = "[AI 생성 일러스트] 기사 내용을 설명하는 도식이며 실제 사진이 아닙니다."

_CODEX = next(
    (p for p in (os.path.expanduser("~/.local/bin/codex"), "/opt/homebrew/bin/codex") if os.path.exists(p)),
    shutil.which("codex") or "",
)
# 헤드리스는 ~/Desktop 아래 cwd에서 돌리지 않는다 (launchd TCC 무한 대기)
_WORK = os.path.join(tempfile.gettempdir(), "aios-headless", "news-image")
_GEN_DIR = os.path.expanduser("~/.codex/generated_images")

_down = False  # 로그인 만료·한도 오류를 한 번 만나면 이번 실행에서는 더 시도하지 않는다


def enabled() -> bool:
    if os.environ.get("AI_IMAGE", "1") == "0" or os.environ.get("GITHUB_ACTIONS"):
        return False
    return bool(_CODEX) and not _down


def vision_enabled() -> bool:
    return enabled() and os.environ.get("AI_IMAGE_VISION", "1") != "0"


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
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)
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


def generate(title: str, keyword: str, category: str, out_path: str) -> bool:
    """기사 내용을 설명하는 도식 1장을 out_path(.jpg, 가로 1200px)에 저장. 성공 시 True."""
    if not enabled():
        return False
    from PIL import Image

    work = os.path.join(_WORK, uuid.uuid4().hex[:8])
    os.makedirs(work, exist_ok=True)
    started = time.time()
    try:
        prompt = (
            "Use your image generation tool to create ONE image, then copy the generated file into the current "
            "directory as image.png. Do nothing else.\n"
            f"Subject: an explanatory diagram for the news article titled \"{title}\" "
            f"(category: {category or 'industry'}; keywords: {keyword}).\n"
            f"{_STYLE}\n{_RULES}"
        )
        rc, _, tail = _run(prompt, "low", 420, cwd=work)
        src = os.path.join(work, "image.png")
        if not os.path.exists(src):  # 복사를 못 했으면 Codex가 만든 최신 파일을 찾는다
            fresh = [p for p in glob.glob(os.path.join(_GEN_DIR, "*", "*.png")) if os.path.getmtime(p) >= started - 2]
            src = max(fresh, key=os.path.getmtime) if fresh else ""
        if rc != 0 and not src:
            print(f"   → AI 이미지 생성 실패(rc={rc}): {tail[-120:].strip()}")
            return False
        if not src:
            print("   → AI 이미지 생성 실패: 이미지 파일 없음")
            return False
        im = Image.open(src).convert("RGB")
        if im.width < 600:
            return False
        h = round(1200 * im.height / im.width)
        im = im.resize((1200, h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        data = buf.getvalue()
        if len(data) < 5000:
            return False
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"   → AI 이미지 오류: {e}")
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def mark(article: dict, ai: bool) -> None:
    """기사에 AI 도식 캡션을 붙이거나(ai=True), 이전에 붙은 AI 캡션을 거둔다(실제 사진으로 바뀐 경우).
    직접 쓴 image_caption(수동 기사)은 건드리지 않는다."""
    if ai:
        article["image_ai"] = True
        article["image_caption"] = CAPTION
    elif article.get("image_ai"):
        article.pop("image_ai", None)
        if article.get("image_caption") == CAPTION:
            article.pop("image_caption", None)


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "미 상무부, AI 반도체 해외 데이터센터 접근 신규 규제"
    k = sys.argv[2] if len(sys.argv) > 2 else "semiconductor export control regulation"
    out = os.path.join(tempfile.gettempdir(), "aios-headless", "news-image-test.jpg")
    print("enabled:", enabled(), "| codex:", _CODEX)
    ok = generate(t, k, "글로벌", out)
    print("생성:", ok, out if ok else "")
