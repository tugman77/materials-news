"""생성 기사 ↔ 원문 대조 후 부분 수정·보류 (2026-11-10, 비공개 시험 4회 결과로 운영 반영).

흐름: 원문대조(문장별) → 지적 문장만 LLM 부분 수정 → 다시 대조 → 남은 지적은 문장 삭제
      → 제목·수치 high 오류나 600자 미만은 보류.
기존 기사검수.py(일괄 검수)는 시험 4회 내내 거의 5/pass였다. 실제 거름은 여기서 한다.
LLM 부분 수정은 지적 밖 문장을 40% 넘게 다시 쓰거나 베낌이 되면 버리고 문장 삭제로 대신한다
(11-05 시험: 수정 단계가 원문 문구를 되살렸다).
"""
from __future__ import annotations

import json
import re

import llm_backend
import 원문대조 as v
import 원문수집 as w

MIN_BODY = 600
MAX_BODY = 1100  # 넘으면 기록만 (보류하지 않음)
DROP_KINDS = {"원문없음", "귀속", "인용변형", "비교기준"}
HOLD_KINDS = {"제목", "수치"}

FIX_SCHEMA = {"type": "object", "properties": {
    "body": {"type": "array", "items": {"type": "string"}},
    "why_important": {"type": "string"}}, "required": ["body", "why_important"]}


def _nospace(t):
    return re.sub(r"\s", "", t or "")


def _sentences(p):
    return [x for x in re.split(r"(?<=[.다])\s+", p) if x.strip()]


def drop_sentence(a, text):
    """지적된 문장을 본문·why_important에서 뺀다. 뺀 문장 수를 돌려준다."""
    key = _nospace(text)[:40]
    whole = _nospace(text)
    n = 0
    for field in ("body", "why_important"):
        paras = a[field] if field == "body" else [a.get(field, "")]
        newp = []
        for p in paras:
            sents = _sentences(p)
            kept = [s for s in sents if not (key and key in _nospace(s)) and not (_nospace(s) and _nospace(s) in whole)]
            n += len(sents) - len(kept)
            if kept:
                newp.append(" ".join(kept))
        if field == "body":
            a["body"] = newp
        else:
            a["why_important"] = newp[0] if newp else ""
    return n


def _fix_flagged(a, issues):
    rules = {"원문없음": "문장을 삭제", "귀속": "원문의 실제 화자로 바로잡거나, 화자 없이 사실로만 쓰거나, 원문에 없으면 삭제",
             "인용변형": "따옴표를 없애고 '~라고 말했다/밝혔다' 간접화법으로", "비교기준": "덧붙인 비교 기준만 삭제"}
    todo = "\n".join(f"- [{i['kind']} → {rules[i['kind']]}] {i['article_text']}  (원문: {i['source_text'][:200]})" for i in issues)
    prompt = f"""기사 본문에서 아래 지적된 문장만 고쳐라. 지적되지 않은 문장은 한 글자도 바꾸지 않는다.
- 삭제 때문에 앞뒤 문장의 지시어(이와 같은, 이처럼, 이는 등)가 가리킬 대상이 없어지면 그 지시어만 자연스럽게 고친다.
- 원문 문구로 되돌려 쓰지 않는다. 새 사실·수치·전망을 넣지 않는다. 분량을 늘리려 하지 않는다.
- 단락 구성은 그대로 둔다(빈 단락은 빼도 된다).

[고칠 문장]
{todo}

[기사]
{json.dumps({"body": a["body"], "why_important": a.get("why_important", "")}, ensure_ascii=False, indent=1)}

save_fix 도구로 고친 body 배열과 why_important를 저장하세요."""
    params = dict(model="claude-sonnet-4-6", max_tokens=6000,
                  tools=[{"name": "save_fix", "description": "고친 본문 저장", "input_schema": FIX_SCHEMA}],
                  tool_choice={"type": "tool", "name": "save_fix"},
                  messages=[{"role": "user", "content": prompt}])
    return llm_backend.call_tool(params, "save_fix", effort="low")


def _unchanged_ratio(before, after):
    b = [_nospace(x) for p in before for x in _sentences(p)]
    aft = _nospace(" ".join(after))
    return sum(1 for x in b if x in aft) / max(1, len(b))


def _mend(body):
    import 기사자동생성 as g  # 순환 import 방지 — 호출 시점에만
    return g._mend_body(body)


def verify_one(a, issues, src_text, srcs):
    """기사 1건 처리. 보류 사유(문자열) 또는 ''를 돌려주고, a는 제자리 수정한다."""
    rec = {"title": a.get("title", ""), "before": sum(map(len, a["body"])), "fixed": [], "recheck_left": [], "how": ""}
    if issues is None:
        rec["hold"] = "원문 대조 실패"
        return rec
    hold, fixable = "", []
    for i in issues:
        if i["kind"] in HOLD_KINDS and i["severity"] == "high":
            hold = f"{i['kind']} 오류: {i['article_text'][:60]}"
        elif i["kind"] in DROP_KINDS:
            fixable.append(i)
        elif i["severity"] == "high":
            hold = f"{i['kind']}(high): {i['article_text'][:60]}"
    if fixable and not hold:
        before, before_why = list(a["body"]), a.get("why_important", "")
        how = "LLM 부분 수정"
        try:
            fx = _fix_flagged(a, fixable)
            body = _mend([p for p in fx["body"] if p.strip()])
            keep = _unchanged_ratio(before, body)
            cv = w.베낌_판정(" ".join(body), srcs)
            if keep < 0.6:
                raise ValueError(f"지적 밖 문장까지 다시 씀(유지 {keep:.0%})")
            if cv["copied"]:
                raise ValueError(f"수정 후 베낌(일치율 {cv['coverage']})")
            a["body"], a["why_important"], a["copy_check"] = body, fx["why_important"], cv
            # 고친 뒤 다시 대조 — 시험 4회차에 '삭제' 지시 문장을 귀속만 떼고 남겼다.
            again = v.check_article(a, src_text)
            for i in again:
                if i["kind"] in HOLD_KINDS and i["severity"] == "high":
                    hold = f"수정 후 {i['kind']} 오류: {i['article_text'][:60]}"
            left = [i for i in again if i["kind"] in DROP_KINDS]
            for i in left:
                drop_sentence(a, i["article_text"])
            rec["recheck_left"] = [f"[{i['kind']}] {i['article_text']}" for i in left]
            if left:
                how += f" → 재대조 남은 {len(left)}곳 삭제"
        except Exception as e:
            how = f"문장 삭제(수정 실패: {type(e).__name__}: {e})"
            a["body"], a["why_important"] = before, before_why
            for i in fixable:
                drop_sentence(a, i["article_text"])
        rec["how"] = how
        rec["fixed"] = [f"[{i['kind']}] {i['article_text']}" for i in fixable]
    rec["after"] = sum(map(len, a["body"]))
    if not hold and rec["after"] < MIN_BODY:
        hold = f"수정 뒤 {rec['after']}자 — 분량 부족"
    rec["hold"] = hold
    return rec


def source_lookup(raw_news, briefing):
    cands = list(raw_news) + [i for items in ((briefing or {}).get("topics") or {}).values() for i in items]
    return {i["title"]: i for i in cands if i.get("title")}


def verify_all(articles, by_title):
    """기사 목록 → (통과 기사, 기록 목록)."""
    pairs, src_lists = [], []
    for a in articles:
        srcs = [by_title[x["title"]].get("fulltext", "") for x in a.get("source_links", []) if x["title"] in by_title]
        srcs = [s for s in srcs if s]
        src_lists.append(srcs)
        pairs.append((a, "\n\n".join(srcs)))
    first = v.check_all(pairs)
    kept, recs = [], []
    for (a, src_text), issues, srcs in zip(pairs, first, src_lists):
        rec = verify_one(a, issues, src_text, srcs)
        recs.append(rec)
        tag = "⛔ 보류" if rec["hold"] else "✅ 통과"
        extra = f" — {rec['hold']}" if rec["hold"] else (f" ({rec['how']})" if rec["how"] else "")
        over = f" ⚠️ 상한 초과" if rec["after"] > MAX_BODY else ""
        print(f"   {tag} {rec['before']}→{rec['after']}자{over}: {rec['title'][:40]}{extra}")
        if not rec["hold"]:
            kept.append(a)
    return kept, recs
