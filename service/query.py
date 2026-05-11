"""Query pipeline — RAG synthesis (question → answer + citations).

设计：
- Deterministic retriever (ripgrep + 中英文 keyword)
- 一次 LLM call (mimo synth) 综合答案
- 不写 wiki / 不污染 caller context
- 调用者 (Claude / Codex / etc.) 拿到的就是 LLM-ready answer

Phase 2.3 范围。Phase 3+ 可加 embedding retrieval / 多轮 follow-up。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import LLMWIKI_ROOT, WIKI_DIR
from .llm import DEFAULT_MODEL, call_llm
from .prompts import QUERY_SYSTEM_PROMPT
from .validator import parse_json_lenient


def query_wiki(
    question: str,
    depth: str = "quick",
    model: str = DEFAULT_MODEL,
    wiki_dir: Path = WIKI_DIR,
) -> dict:
    """RAG: question → {answer, citations, confidence, related_pages, follow_up_questions, gaps}.

    Args:
        question: 用户问题（中文 / 英文 / 混合）
        depth: "quick" (top-5 pages) | "deep" (top-12 pages，完整 page body)
        model: LLM model name
        wiki_dir: wiki 根目录
    """
    k = 5 if depth == "quick" else 12
    candidates = find_pages_for_query(question, wiki_dir=wiki_dir, k=k)

    if not candidates:
        return {
            "answer": (
                "memex 没找到与该问题相关的 wiki 页。"
                "建议先 ingest 相关 source（用 wiki_ingest_source tool）。"
            ),
            "citations": [],
            "confidence": "low",
            "related_pages": [],
            "follow_up_questions": [],
            "gaps": [f"No wiki coverage for: {question}"],
            "candidates_count": 0,
        }

    context_parts = []
    for p in candidates:
        rel = p.relative_to(LLMWIKI_ROOT)
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        # cap each page to 2000 lines
        if len(lines) > 2000:
            text = "\n".join(lines[:2000]) + "\n\n... (truncated)"
        context_parts.append(f"## {rel}\n\n{text}")
    context = "\n\n---\n\n".join(context_parts)

    user_prompt = (
        f"# 用户问题\n\n{question}\n\n"
        f"# Wiki context（{len(candidates)} 页，按相关度排序）\n\n{context}\n\n"
        f"# 任务\n\n按 system prompt JSON schema 输出。仅 JSON，无 markdown fence。"
    )

    raw = call_llm(QUERY_SYSTEM_PROMPT, user_prompt, model=model, json_mode=True)
    try:
        parsed = parse_json_lenient(raw)
    except Exception as e:
        return {
            "error": f"JSON parse failed: {e!r}",
            "raw": raw,
            "candidates_count": len(candidates),
        }

    # 加 candidates_count 给 caller debug
    parsed["candidates_count"] = len(candidates)
    return parsed


def find_pages_for_query(
    question: str,
    wiki_dir: Path = WIKI_DIR,
    k: int = 8,
) -> list[Path]:
    """grep wiki 找跟 question 相关的页"""
    # 拆中英 keyword
    en_tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9\-]{2,30}\b", question)
    zh_phrases = re.findall(r"[一-鿿]{2,8}", question)
    keywords = list(set(en_tokens + zh_phrases))[:20]

    if not keywords:
        return []

    pattern = "(" + "|".join(re.escape(k) for k in keywords) + ")"
    try:
        out = subprocess.run(
            ["rg", "-c", "-i", "--type-add", "wiki:*.md", "-twiki",
             "--", pattern, str(wiki_dir)],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    # rg -c 输出: path:N (per file count)
    hit_counts: dict[Path, int] = {}
    for line in out.stdout.splitlines():
        if ":" not in line:
            continue
        path_str, count_str = line.rsplit(":", 1)
        try:
            count = int(count_str)
        except ValueError:
            continue
        p = Path(path_str)
        if p.exists():
            hit_counts[p] = count

    ranked = sorted(hit_counts.items(), key=lambda x: -x[1])[:k]
    return [p for p, _ in ranked]
