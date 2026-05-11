#!/usr/bin/env python3
"""Milestone 0 spike: mimo digest a single source, output JSON to stdout
for human comparison vs Opus 4.7 baseline (llm-wiki commit cb9d897).

Usage:
    python3 spike_digest.py [--source DOCS_REL_PATH] [--model MODEL] [--save]

Default: digest docs/qingang_LiEA12.md
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# llm-wiki repo paths（暂时硬编码——Phase 1 改成 config）
LLMWIKI_ROOT = Path("/home/leon/llm-wiki")
DOCS_DIR = LLMWIKI_ROOT / "docs"
WIKI_DIR = LLMWIKI_ROOT / "wiki"
INDEX_FILE = LLMWIKI_ROOT / "INDEX.md"
TOOLS_DIR = LLMWIKI_ROOT / "tools"

# Reuse _env.py from llm-wiki for mimo credentials
sys.path.insert(0, str(TOOLS_DIR))
from _env import load_mimo_env  # noqa: E402

from openai import OpenAI  # noqa: E402


SYSTEM_PROMPT = """你是 memex 的 digest worker。

任务：把给定的 source（学术论文 / 书 / 文章 / 转录）digest 成对 wiki 的增量改动，输出 JSON。

## 三铁律（必守）

1. **Concepts first, not sources** —— wiki 页按概念 / 实体组织，不按来源
2. **Source feeds concepts** —— 给已有 concept/entity 页**追加** facts / quotes / timeline
3. **No source-specific pages** —— 严禁建 "X论文阅读笔记.md" / "Y书章节总结.md" 这种以来源命名的页

## 命名规范

- concept 页：中文 kebab-case，如 `太阳风Flux-Tube湍流模型.md`
- entity 页（人 / 公司 / 产品）：原名保留，如 `Gang-Li.md`、`巴菲特.md`
- 路径形如 `wiki/concepts/X.md` 或 `wiki/entities/Y.md`

## Frontmatter schema（每页必有）

```yaml
---
title: "页面标题"
type: concept | entity | comparison
sources:
  - "docs/source_id.md"
related:
  - "[[相关概念]]"
  - "[[人物实体]]"
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: high | medium | low | disputed
topic: [finance, ai, physics]
---
```

每页至少 2 个 [[wikilinks]]，目标必须真实存在或本次输出中新建。

## 数字 / 引用精度（防 hallucination）

- 论文里的数字 / 日期 / 作者 / 机构 —— 严格忠于原文，标 §段落 / Figure / Table 出处
- 外部 facts（论文未提的）必须标 hedge："据公开记录补充，非 source 原文"
- 严禁编造 / 推测 / 填充未知

## 矛盾处理

新内容跟 wiki 已有矛盾 → 保留双方在 `## Contradictions` 段，confidence: disputed

## 输出 JSON 格式

**只输出一个 JSON object，不要 markdown code fence，不要前后文说明**：

```
{
  "verdict": "digested" | "partial" | "abandoned",
  "summary": "一句话概括 source 核心贡献 + 在 wiki 中的定位",
  "feeds": ["wiki/concepts/A.md", "wiki/entities/B.md", ...],
  "edits": [
    {
      "target": "wiki/concepts/X.md",
      "action": "create" | "append" | "merge",
      "rationale": "为什么动这页（< 50 字）",
      "frontmatter_update": {
        "sources_add": ["docs/source.md"],
        "updated": "YYYY-MM-DD"
      },
      "content": "完整 markdown 内容 (create) 或追加段落 markdown (append/merge)",
      "key_facts": ["事实1 (§3)", "事实2 (Fig.2)"],
      "wikilinks_added": ["[[A]]", "[[B]]"],
      "confidence": "high" | "medium" | "low"
    }
  ],
  "caveat": ["方法论 caveat / 待解决问题"]
}
```

verdict 选择：
- `digested`: 内容密度足、主题相关、完整 digest
- `partial`: 边缘价值，只 digest 值得的部分
- `abandoned`: 内容稀薄 / 离题，不 digest

## 注意

- 仅输出 JSON，字段命名严格按上面 schema
- 中文内容直接用中文，UTF-8
- `content` 字段是 markdown，含完整 frontmatter（create 时）或纯追加段（append 时）
- **重要：JSON 字符串里如果含英文 `"`，必须 escape 为 `\\"`；或改用中文 `"` `"` `"`**
- **`feeds` 列表必须列出所有被改动的 wiki 页，与 `edits[].target` 数量一致**
- **`frontmatter_update.sources_add` 必须填入本次 source 路径，例如 `["docs/qingang_LiEA12.md"]`**
- **`wikilinks_added` 必须列出本次 edit 段落里新增的所有 `[[X]]` 链接**
- **verdict 判定标准**：内容主题相关 + 信息密度足够 → digested；不要因"已有 wiki 部分覆盖"而判 partial
"""


# ---------------------- candidate retrieval ----------------------


def find_candidate_pages(source_text: str, wiki_dir: Path, k: int = 15) -> list[Path]:
    """grep wiki/ 找候选相关页"""
    # 抽英文 CamelCase / 大写专名（论文里的人名 / 概念 / 缩写）
    en_tokens = set(re.findall(r"\b[A-Z][a-zA-Z0-9\-]{2,30}\b", source_text))
    noise = {
        "The", "This", "These", "Figure", "Table", "Section", "Available",
        "Online", "Received", "Accepted", "January", "February", "March",
        "April", "May", "June", "July", "August", "September", "October",
        "November", "December", "And", "But", "For", "With", "From",
    }
    keywords = list(en_tokens - noise)[:25]

    hit_counts: dict[Path, int] = {}
    for kw in keywords:
        try:
            out = subprocess.run(
                ["rg", "-l", "-i", "--type-add", "wiki:*.md", "-twiki",
                 "--", kw, str(wiki_dir)],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        for line in out.stdout.splitlines():
            p = Path(line.strip())
            if p.exists():
                hit_counts[p] = hit_counts.get(p, 0) + 1

    ranked = sorted(hit_counts.items(), key=lambda x: -x[1])[:k]
    return [p for p, _ in ranked]


def read_page_summary(path: Path, max_lines: int = 40) -> str:
    """读 wiki page 的 frontmatter + 开头（前 N 行）"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = text.splitlines()[:max_lines]
    rel = path.relative_to(LLMWIKI_ROOT)
    return f"### {rel}\n```\n" + "\n".join(lines) + "\n```\n"


def build_user_prompt(source_path: Path, candidates: list[Path]) -> str:
    parts = []

    parts.append(
        f"# Source to digest\n\n"
        f"Path: `docs/{source_path.name}`\n\n"
        f"```\n{source_path.read_text()}\n```\n"
    )

    if INDEX_FILE.exists():
        index_head = "\n".join(INDEX_FILE.read_text().splitlines()[:50])
        parts.append(f"# Wiki INDEX (头部)\n\n```\n{index_head}\n```\n")

    parts.append(
        f"# 候选相关 wiki 页（前 {len(candidates)} 个，按 keyword 相关度排序，"
        f"含 frontmatter + 开头）\n"
    )
    for p in candidates:
        parts.append(read_page_summary(p))

    parts.append("\n# 任务\n\n按 system prompt 三铁律 + JSON schema，"
                 "digest 上面 source 并输出 JSON（仅 JSON，无 markdown fence）。")
    return "\n".join(parts)


# ---------------------- mimo call ----------------------


def call_mimo(system: str, user: str, model: str) -> str:
    api_key, base_url = load_mimo_env()
    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    # 优先 json_object mode，让 OpenAI-compat endpoint 强制合法 JSON
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("response_format", "not support", "unsupported")):
            eprint(f"(mimo doesn't support response_format, falling back: {e!r})")
            resp = client.chat.completions.create(model=model, messages=messages)
        else:
            raise
    return resp.choices[0].message.content or ""


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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback 1: 把 string 内部未 escape 的英文 " 替换为 \"
    fixed = _escape_inner_quotes(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    # Fallback 2: 用 raw_decode 找最大可解析前缀
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text)
        return obj
    except json.JSONDecodeError as e:
        raise e


def _escape_inner_quotes(s: str) -> str:
    """简化版：扫描 JSON，把出现在 string 内部的未 escape `"` 替换为 `\\"`。
    State machine: in_string / escape / outside。
    """
    out = []
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
                # 看后面是否是合法的 string 结束（, : } ] 等）
                j = i + 1
                while j < len(s) and s[j] in " \t\n\r":
                    j += 1
                if j >= len(s) or s[j] in ",:}]\n":
                    in_string = False
                    out.append(c)
                else:
                    # 内嵌未 escape `"`，替换
                    out.append('\\"')
        else:
            out.append(c)
        i += 1
    return "".join(out)


# ---------------------- apply edits to staging ----------------------


STAGING_DIR = Path(__file__).parent / ".staging"


def apply_edits_to_staging(parsed: dict, staging_root: Path = STAGING_DIR) -> dict:
    """把 mimo 提议的 edits 写到 staging dir（不动 production wiki）。

    Returns: {created: [...], appended: [...], errors: [...]}
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    result = {"created": [], "appended": [], "errors": []}

    for i, edit in enumerate(parsed.get("edits", [])):
        target = edit.get("target", "")
        action = edit.get("action", "")
        content = edit.get("content", "")

        if not target.startswith("wiki/"):
            result["errors"].append(f"edit[{i}]: target not wiki/ — {target}")
            continue

        rel = target[len("wiki/"):]  # e.g. "concepts/X.md"
        staging_path = staging_root / rel
        staging_path.parent.mkdir(parents=True, exist_ok=True)

        production_path = WIKI_DIR / rel
        fm_update = edit.get("frontmatter_update") or {}

        if action == "create":
            staging_path.write_text(content, encoding="utf-8")
            result["created"].append(str(staging_path))
        elif action in ("append", "merge"):
            # 复制 production 文件作为底，再 append/merge
            if not production_path.exists():
                result["errors"].append(
                    f"edit[{i}]: {action} target not in production: {target}"
                )
                continue
            base = production_path.read_text(encoding="utf-8")
            new_text = _apply_frontmatter_update(base, fm_update) + "\n" + content
            staging_path.write_text(new_text, encoding="utf-8")
            result["appended"].append(str(staging_path))
        else:
            result["errors"].append(f"edit[{i}]: unknown action {action!r}")

    return result


def _apply_frontmatter_update(text: str, fm_update: dict) -> str:
    """更新 markdown 文件的 frontmatter（sources_add / updated 字段）"""
    if not fm_update:
        return text
    # 找 frontmatter 边界 (--- ... ---)
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return text  # 没 frontmatter，不动
    fm_text = m.group(1)
    body = text[m.end():]

    sources_add = fm_update.get("sources_add") or []
    updated = fm_update.get("updated")

    if sources_add:
        # 找 sources: 字段
        if "sources:" in fm_text:
            # 在 sources: 下面追加
            lines = fm_text.splitlines()
            new_lines = []
            in_sources = False
            inserted = False
            for line in lines:
                new_lines.append(line)
                if line.startswith("sources:"):
                    in_sources = True
                elif in_sources and not line.startswith(("  -", "  ", "\t")):
                    # 离开 sources block
                    if not inserted:
                        # 在前一个 - 行的位置插
                        for s in sources_add:
                            new_lines.insert(-1, f'  - "{s}"')
                        inserted = True
                    in_sources = False
            if in_sources and not inserted:
                for s in sources_add:
                    new_lines.append(f'  - "{s}"')
            fm_text = "\n".join(new_lines)
        else:
            # 没 sources: 字段，加一个
            fm_text += "\nsources:\n" + "\n".join(f'  - "{s}"' for s in sources_add)

    if updated:
        if re.search(r"^updated:\s.*", fm_text, re.MULTILINE):
            fm_text = re.sub(r"^updated:\s.*", f"updated: {updated}", fm_text, flags=re.MULTILINE)
        else:
            fm_text += f"\nupdated: {updated}"

    return f"---\n{fm_text}\n---\n{body}"


# ---------------------- validation ----------------------


def validate_output(parsed: dict) -> list[str]:
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
            if not isinstance(e, dict):
                errors.append(f"edits[{i}] not a dict")
                continue
            for fld in ("target", "action"):
                if fld not in e:
                    errors.append(f"edits[{i}] missing {fld}")
            target = e.get("target", "")
            if not target.startswith("wiki/"):
                errors.append(f"edits[{i}].target should start with 'wiki/': {target!r}")
            action = e.get("action", "")
            if action not in {"create", "append", "merge"}:
                errors.append(f"edits[{i}].action invalid: {action!r}")
            # source-specific naming check
            name = Path(target).stem.lower()
            sus = ["阅读笔记", "总结", "章节", "_notes", "_summary", "letter", "ltr"]
            if any(s in name for s in sus):
                errors.append(
                    f"edits[{i}].target suspect source-specific naming: {target!r}"
                )

    return errors


# ---------------------- main ----------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source", default="qingang_LiEA12.md",
        help="Source file relative to llm-wiki/docs/ (default: qingang_LiEA12.md)",
    )
    ap.add_argument(
        "--model", default="mimo-v2.5",
        help="Mimo model name (default: mimo-v2.5)",
    )
    ap.add_argument(
        "--save", action="store_true",
        help="Save raw + parsed output to .spike_output_*.json",
    )
    ap.add_argument(
        "--write-to-staging", action="store_true",
        help="Apply mimo edits to .staging/ dir (mirror of wiki/, NOT production)",
    )
    args = ap.parse_args()

    source_path = DOCS_DIR / args.source
    if not source_path.exists():
        sys.exit(f"Source not found: {source_path}")

    text = source_path.read_text()
    eprint(f"=== Spike: digesting {args.source} ===")
    eprint(f"Source: {len(text)} chars / {len(text.splitlines())} lines")

    candidates = find_candidate_pages(text, WIKI_DIR)
    eprint(f"Candidates ({len(candidates)} wiki pages, top 5):")
    for p in candidates[:5]:
        eprint(f"  - {p.relative_to(LLMWIKI_ROOT)}")
    if len(candidates) > 5:
        eprint(f"  ... +{len(candidates) - 5} more")

    user_prompt = build_user_prompt(source_path, candidates)
    eprint(f"\nUser prompt: ~{len(user_prompt)} chars")

    eprint(f"\n=== Calling mimo ({args.model}) ===")
    try:
        raw = call_mimo(SYSTEM_PROMPT, user_prompt, args.model)
    except Exception as e:
        sys.exit(f"mimo call failed: {e!r}")

    eprint(f"Mimo response: {len(raw)} chars\n")

    # --- output section ---
    print("=" * 60)
    print("RAW MIMO OUTPUT")
    print("=" * 60)
    print(raw)

    cleaned = strip_markdown_fence(raw)
    try:
        parsed = parse_json_lenient(cleaned)
    except json.JSONDecodeError as e:
        print("\n" + "=" * 60)
        print("JSON PARSE FAILED (even with lenient fallback)")
        print("=" * 60)
        print(f"Error: {e}")
        if args.save:
            _save_artifact(args.source, raw=raw, parsed=None, errors=[f"parse fail: {e}"])
        sys.exit(1)

    errors = validate_output(parsed)

    print("\n" + "=" * 60)
    print("SCHEMA VALIDATION")
    print("=" * 60)
    if errors:
        for e in errors:
            print(f"  - {e}")
    else:
        print("  OK")

    print("\n" + "=" * 60)
    print("MIMO PROPOSED CHANGES")
    print("=" * 60)
    print(f"Verdict: {parsed.get('verdict')}")
    print(f"Summary: {parsed.get('summary')}")
    print(f"\nFeeds ({len(parsed.get('feeds', []))}):")
    for f in parsed.get("feeds", []):
        print(f"  - {f}")
    print(f"\nEdits ({len(parsed.get('edits', []))}):")
    for e in parsed.get("edits", []):
        action = e.get("action", "?")
        target = e.get("target", "?")
        conf = e.get("confidence", "?")
        rationale = (e.get("rationale", "") or "")[:80]
        print(f"  - [{action:6s}] {target}")
        print(f"      conf={conf} | {rationale}")
        kf = e.get("key_facts", [])
        if kf:
            print(f"      key_facts: {kf[:3]}{'...' if len(kf) > 3 else ''}")
    caveat = parsed.get("caveat", [])
    if caveat:
        print(f"\nCaveat:")
        for c in caveat:
            print(f"  - {c}")

    print("\n" + "=" * 60)
    print("BASELINE (llm-wiki commit cb9d897) — 人工对比")
    print("=" * 60)
    print("Changed pages (4):")
    print("  - wiki/concepts/太阳风Flux-Tube湍流模型.md  [+81 lines]")
    print("  - wiki/entities/Gang-Li.md")
    print("  - wiki/entities/秦刚.md")
    print("  - wiki/concepts/Slab-2D复合湍流模型.md")
    print("Total: +108 / -4 lines, ~12 new wikilinks")
    print("\nSpot-check 项:")
    print("  □ 核心数字 L=26.5 AU / k=13 / 8192 cells / 谱 -1.65~-1.72")
    print("  □ 三铁律（无 source-specific 页）")
    print("  □ Frontmatter sources 字段含 docs/qingang_LiEA12.md")
    print("  □ Wikilink 目标可达（[[Gang-Li]] / [[秦刚]] / [[Slab-2D复合湍流模型]]）")
    print("  □ 无 hallucination")

    if args.save:
        _save_artifact(args.source, raw=raw, parsed=parsed, errors=errors)

    if args.write_to_staging:
        print("\n" + "=" * 60)
        print(f"APPLYING TO STAGING ({STAGING_DIR})")
        print("=" * 60)
        # 清空旧 staging
        if STAGING_DIR.exists():
            import shutil
            shutil.rmtree(STAGING_DIR)
        apply_result = apply_edits_to_staging(parsed)
        for p in apply_result["created"]:
            print(f"  CREATE  {p}")
        for p in apply_result["appended"]:
            print(f"  APPEND  {p}")
        for e in apply_result["errors"]:
            print(f"  ERROR   {e}")
        print(f"\nStaging dir: {STAGING_DIR}")
        print("Compare to production: diff -u production/wiki/X.md staging/wiki/X.md")


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def _save_artifact(source: str, raw: str, parsed: dict | None, errors: list[str]):
    name = source.replace("/", "_").replace(".md", "")
    out = Path(__file__).parent / f".spike_output_{name}.json"
    out.write_text(
        json.dumps(
            {"source": source, "raw": raw, "parsed": parsed, "validation_errors": errors},
            indent=2, ensure_ascii=False,
        )
    )
    eprint(f"Saved artifact: {out}")


if __name__ == "__main__":
    main()
