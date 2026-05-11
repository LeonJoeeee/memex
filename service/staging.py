"""Staging — apply LLM-proposed edits to .staging/ dir (mirror of wiki/).

Phase 1.1 范围：read-only 等价 wiki write，让 user 人工 diff 验证。
Phase 1.3 加 git_ops: 把 staging 内容 promote 到 production wiki + git commit。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .config import STAGING_DIR, WIKI_DIR


def apply_edits_to_staging(
    parsed: dict,
    staging_root: Path = STAGING_DIR,
    wiki_root: Path = WIKI_DIR,
    clean: bool = True,
) -> dict:
    """把 mimo 提议的 edits 写到 staging dir（不动 production wiki）。

    Returns: {created: [...], appended: [...], errors: [...]}
    """
    if clean and staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    result = {"created": [], "appended": [], "errors": []}

    for i, edit in enumerate(parsed.get("edits", [])):
        target = edit.get("target", "")
        action = edit.get("action", "")
        content = edit.get("content", "") or ""

        if not target.startswith("wiki/"):
            result["errors"].append(f"edit[{i}]: target not wiki/ — {target}")
            continue

        rel = target[len("wiki/"):]
        staging_path = staging_root / rel
        staging_path.parent.mkdir(parents=True, exist_ok=True)

        production_path = wiki_root / rel
        fm_update = edit.get("frontmatter_update") or {}

        if action == "create":
            staging_path.write_text(content, encoding="utf-8")
            result["created"].append(str(staging_path))
        elif action in ("append", "merge"):
            if not production_path.exists():
                result["errors"].append(
                    f"edit[{i}]: {action} target not in production: {target}"
                )
                continue
            base = production_path.read_text(encoding="utf-8")
            new_text = apply_frontmatter_update(base, fm_update) + "\n" + content
            staging_path.write_text(new_text, encoding="utf-8")
            result["appended"].append(str(staging_path))
        else:
            result["errors"].append(f"edit[{i}]: unknown action {action!r}")

    return result


def apply_frontmatter_update(text: str, fm_update: dict) -> str:
    """更新 markdown 文件的 frontmatter（sources_add / updated 字段）"""
    if not fm_update:
        return text
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return text  # 没 frontmatter，不动
    fm_text = m.group(1)
    body = text[m.end():]

    sources_add = fm_update.get("sources_add") or []
    updated = fm_update.get("updated")

    if sources_add:
        fm_text = _add_to_yaml_list(fm_text, "sources", sources_add)

    if updated:
        if re.search(r"^updated:\s.*", fm_text, re.MULTILINE):
            fm_text = re.sub(
                r"^updated:\s.*", f"updated: {updated}", fm_text, flags=re.MULTILINE
            )
        else:
            fm_text += f"\nupdated: {updated}"

    return f"---\n{fm_text}\n---\n{body}"


def _add_to_yaml_list(fm_text: str, key: str, values: list[str]) -> str:
    """在 YAML frontmatter 的 list field（如 sources:）下追加 - "X" 项。"""
    if f"{key}:" not in fm_text:
        # 没该字段，新增
        items = "\n".join(f'  - "{v}"' for v in values)
        return fm_text + f"\n{key}:\n" + items

    lines = fm_text.splitlines()
    new_lines = []
    in_block = False
    inserted = False
    existing: set[str] = set()

    for line in lines:
        if line.startswith(f"{key}:"):
            in_block = True
            new_lines.append(line)
            continue
        if in_block:
            stripped = line.strip()
            if stripped.startswith("- "):
                # 收集已有项（去重用）
                existing.add(stripped[2:].strip().strip('"'))
                new_lines.append(line)
            elif line.startswith(("  ", "\t")) and not stripped:
                new_lines.append(line)
            else:
                # 离开 block，在前一行后插入新 items
                if not inserted:
                    for v in values:
                        if v not in existing:
                            new_lines.insert(-1, f'  - "{v}"')
                    inserted = True
                in_block = False
                new_lines.append(line)
        else:
            new_lines.append(line)

    if in_block and not inserted:
        for v in values:
            if v not in existing:
                new_lines.append(f'  - "{v}"')

    return "\n".join(new_lines)
