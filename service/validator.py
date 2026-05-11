"""Validator — deterministic schema check on LLM output.

Phase 1.1 范围：
- parse_json_lenient: 容错 JSON 解析（修常见 unescape 问题）
- validate_digest_output: digest JSON schema check
- 检测常见违规（source-specific naming / frontmatter 缺失 / 等）

Phase 1.2 加：
- validate against existing wikilinks targets（reference integrity）
"""
from __future__ import annotations

import json
from pathlib import Path


def strip_markdown_fence(text: str) -> str:
    """剥离 ```json ... ``` 包裹"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json_lenient(text: str) -> dict:
    """Robust JSON parse: 先 strict，失败则尝试修常见 escape 问题"""
    cleaned = strip_markdown_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    fixed = _escape_inner_quotes(cleaned)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(cleaned)
    return obj


def _escape_inner_quotes(s: str) -> str:
    """状态机扫描 JSON，把 string 内部未 escape 的英文 `"` 替换为 `\\"`。"""
    out: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(s):
        c = s[i]
        if escape:
            out.append(c)
            escape = False
        elif c == "\\":
            out.append(c)
            escape = True
        elif c == '"':
            if not in_string:
                in_string = True
                out.append(c)
            else:
                # 后面是否是合法的 string 结束（, : } ] 等）
                j = i + 1
                while j < len(s) and s[j] in " \t\n\r":
                    j += 1
                if j >= len(s) or s[j] in ",:}]\n":
                    in_string = False
                    out.append(c)
                else:
                    out.append('\\"')
        else:
            out.append(c)
        i += 1
    return "".join(out)


def validate_digest_output(parsed: dict) -> list[str]:
    """Schema check + 业务规则 check"""
    errors = []

    required = {"verdict", "summary", "feeds", "edits"}
    missing = required - set(parsed.keys())
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")

    verdict = parsed.get("verdict")
    if verdict not in {"digested", "partial", "abandoned"}:
        errors.append(f"verdict invalid: {verdict!r}")

    feeds = parsed.get("feeds", [])
    if not isinstance(feeds, list):
        errors.append("feeds not a list")
    else:
        for i, f in enumerate(feeds):
            if not isinstance(f, str) or not f.startswith("wiki/"):
                errors.append(f"feeds[{i}] should be 'wiki/...' string: {f!r}")

    edits = parsed.get("edits", [])
    if not isinstance(edits, list):
        errors.append("edits not a list")
    else:
        for i, e in enumerate(edits):
            errors.extend(_validate_edit(i, e))

    return errors


def _validate_edit(idx: int, e: dict) -> list[str]:
    errors = []
    if not isinstance(e, dict):
        return [f"edits[{idx}] not a dict"]

    for fld in ("target", "action"):
        if fld not in e:
            errors.append(f"edits[{idx}] missing {fld}")

    target = e.get("target", "")
    if not target.startswith("wiki/"):
        errors.append(f"edits[{idx}].target should start with 'wiki/': {target!r}")

    action = e.get("action", "")
    if action not in {"create", "append", "merge"}:
        errors.append(f"edits[{idx}].action invalid: {action!r}")

    # source-specific naming check (三铁律 #3)
    name = Path(target).stem.lower()
    sus_patterns = ["阅读笔记", "总结", "_notes", "_summary", "letter", "ltr"]
    if any(s in name for s in sus_patterns):
        errors.append(
            f"edits[{idx}].target suspect source-specific naming: {target!r}"
        )

    return errors
