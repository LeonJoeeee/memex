"""Retriever — grep wiki for candidate pages + build LLM context.

设计原则：
- Deterministic（无 LLM call）
- ripgrep keyword 命中排序
- Phase 3+ 可加 embedding semantic retrieval
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import (
    DEFAULT_CANDIDATE_COUNT,
    DEFAULT_PAGE_SUMMARY_LINES,
    INDEX_FILE,
    KEYWORD_MAX,
    KEYWORD_NOISE,
    LLMWIKI_ROOT,
    WIKI_DIR,
)


def find_candidate_pages(
    source_text: str,
    wiki_dir: Path = WIKI_DIR,
    k: int = DEFAULT_CANDIDATE_COUNT,
) -> list[Path]:
    """grep wiki/ 找候选相关页（按 keyword 命中数排序）"""
    en_tokens = set(re.findall(r"\b[A-Z][a-zA-Z0-9\-]{2,30}\b", source_text))
    keywords = list(en_tokens - KEYWORD_NOISE)[:KEYWORD_MAX]

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


def read_page_summary(
    path: Path,
    max_lines: int = DEFAULT_PAGE_SUMMARY_LINES,
    root: Path = LLMWIKI_ROOT,
) -> str:
    """读 wiki page 的 frontmatter + 开头（前 N 行）"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = text.splitlines()[:max_lines]
    rel = path.relative_to(root)
    return f"### {rel}\n```\n" + "\n".join(lines) + "\n```\n"


def build_user_prompt(
    source_path: Path,
    candidates: list[Path],
    index_file: Path = INDEX_FILE,
    index_head_lines: int = 50,
) -> str:
    """构造 LLM user prompt: source 全文 + 候选页 frontmatter + INDEX 头部"""
    parts = []

    parts.append(
        f"# Source to digest\n\n"
        f"Path: `docs/{source_path.name}`\n\n"
        f"```\n{source_path.read_text()}\n```\n"
    )

    if index_file.exists():
        index_head = "\n".join(index_file.read_text().splitlines()[:index_head_lines])
        parts.append(f"# Wiki INDEX (头部)\n\n```\n{index_head}\n```\n")

    parts.append(
        f"# 候选相关 wiki 页（前 {len(candidates)} 个，按 keyword 相关度排序，"
        f"含 frontmatter + 开头）\n"
    )
    for p in candidates:
        parts.append(read_page_summary(p))

    parts.append(
        "\n# 任务\n\n按 system prompt 三铁律 + JSON schema，"
        "digest 上面 source 并输出 JSON（仅 JSON，无 markdown fence）。"
    )
    return "\n".join(parts)
