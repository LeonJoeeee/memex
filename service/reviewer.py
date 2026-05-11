"""Reviewer — 2nd LLM call 审计 digest 输出。

设计：
- 不是 agent；是 deterministic 调用 LLM 做 audit
- 输出 review JSON（issues + suggested additions + pass bool）
- 由 digest pipeline driver 决定是否触发 fix pass

Phase 1.2 范围：basic reviewer + fix loop。
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import LLMWIKI_ROOT
from .llm import DEFAULT_MODEL, call_llm
from .prompts import REVIEWER_SYSTEM_PROMPT
from .retriever import read_page_summary
from .validator import parse_json_lenient


def review_digest(
    source_text: str,
    digest_parsed: dict,
    candidates: list[Path],
    source_rel: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """LLM call 审计 digest output → review JSON.

    Args:
        source_text: source 全文
        digest_parsed: 上一次 digest_LLM 输出的 JSON dict
        candidates: 候选 wiki 页路径列表（让 reviewer 看到 coverage 全集）
        source_rel: source 相对路径 (e.g. 'qingang_LiEA12.md')
        model: LLM model name
    """
    user_prompt = build_reviewer_prompt(
        source_text, digest_parsed, candidates, source_rel
    )
    raw = call_llm(REVIEWER_SYSTEM_PROMPT, user_prompt, model=model, json_mode=True)
    return parse_json_lenient(raw)


def build_reviewer_prompt(
    source_text: str,
    digest_parsed: dict,
    candidates: list[Path],
    source_rel: str,
) -> str:
    """构造 reviewer 用的 user prompt"""
    parts = []

    parts.append(f"# Source (path: docs/{source_rel})\n\n```\n{source_text}\n```\n")

    parts.append(
        f"# 候选相关 wiki 页（共 {len(candidates)}，digest 应已 review 它们）\n"
    )
    for p in candidates:
        parts.append(read_page_summary(p, root=LLMWIKI_ROOT))

    parts.append(
        "# 上一个 LLM 的 digest 输出（待你审计）\n\n```json\n"
        + json.dumps(digest_parsed, ensure_ascii=False, indent=2)
        + "\n```\n"
    )

    parts.append(
        "# 任务\n\n按 system prompt 的 6 类检查，audit 上面 digest 输出。"
        "输出 review JSON（仅 JSON，无 markdown fence）。"
    )

    return "\n".join(parts)


def is_pass(review: dict) -> bool:
    """判断 review 是否通过（避免依赖 LLM 自报的 pass 字段不准）"""
    if not review.get("pass"):
        return False
    # double check: critical 类必须为空
    for k in ("accuracy_issues", "rule_violations", "hallucination_risk"):
        if review.get(k):
            return False
    return True


def has_meaningful_issues(review: dict) -> bool:
    """是否有值得触发 fix 的 issue（coverage 或 critical）"""
    for k in (
        "coverage_issues",
        "accuracy_issues",
        "rule_violations",
        "frontmatter_issues",
        "wikilink_issues",
        "hallucination_risk",
        "suggested_additions",
    ):
        if review.get(k):
            return True
    return False
