"""Digest pipeline — single source → JSON spec (+ optional reviewer + staging).

LLM 是 deterministic function（input prompt → output JSON），代码是 driver。
不是 agent。

Phase 1.1: 单 source 单次 LLM call → JSON → validate → optional staging
Phase 1.2: + retry loop on schema validate fail
         + reviewer pass (2nd LLM call audits) → fix call (3rd LLM)
Phase 1.3 (TODO): promote staging → production wiki + git commit
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import DOCS_DIR, WIKI_DIR
from .llm import DEFAULT_MODEL, call_llm
from .prompts import (
    DIGEST_FIX_USER_PROMPT_TEMPLATE,
    DIGEST_SYSTEM_PROMPT,
)
from .retriever import build_user_prompt, find_candidate_pages
from .reviewer import has_meaningful_issues, review_digest
from .staging import apply_edits_to_staging
from .validator import parse_json_lenient, validate_digest_output


@dataclass
class DigestResult:
    source: str
    raw: str
    parsed: dict | None
    validation_errors: list[str]
    staging_result: dict | None = None
    parse_failed: bool = False
    candidates: list[Path] = field(default_factory=list)
    prompt_chars: int = 0
    review: dict | None = None
    review_applied: bool = False
    retry_count: int = 0


def digest_source(
    source_rel: str,
    docs_dir: Path = DOCS_DIR,
    wiki_dir: Path = WIKI_DIR,
    model: str = DEFAULT_MODEL,
    write_to_staging: bool = False,
    with_reviewer: bool = False,
    max_retries: int = 2,
) -> DigestResult:
    """Digest single source → DigestResult.

    Args:
        source_rel: source path relative to docs_dir (e.g. "qingang_LiEA12.md")
        docs_dir: docs root
        wiki_dir: wiki root
        model: LLM model name
        write_to_staging: if True, apply final LLM edits to .staging/ dir
        with_reviewer: if True, run reviewer pass + fix call on issues
        max_retries: retry digest LLM call on schema validation fail
    """
    source_path = docs_dir / source_rel
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    source_text = source_path.read_text()
    candidates = find_candidate_pages(source_text, wiki_dir)
    user_prompt = build_user_prompt(source_path, candidates)

    # ---- Pass 1: digest ----
    raw, parsed, errors = _digest_call_with_retry(
        DIGEST_SYSTEM_PROMPT, user_prompt, model, max_retries
    )

    result = DigestResult(
        source=source_rel,
        raw=raw,
        parsed=parsed,
        validation_errors=errors,
        candidates=candidates,
        prompt_chars=len(user_prompt),
    )

    if parsed is None:
        result.parse_failed = True
        return result

    # ---- Pass 2: reviewer (optional) ----
    if with_reviewer:
        try:
            review = review_digest(
                source_text, parsed, candidates, source_rel, model=model
            )
            result.review = review
        except Exception as e:
            result.validation_errors.append(f"reviewer failed: {e!r}")
            review = None

        # ---- Pass 3: fix (if reviewer found issues) ----
        if review and has_meaningful_issues(review):
            fix_prompt = DIGEST_FIX_USER_PROMPT_TEMPLATE.format(
                review_json=json.dumps(review, ensure_ascii=False, indent=2),
                prior_digest_json=json.dumps(parsed, ensure_ascii=False, indent=2),
            )
            try:
                raw2 = call_llm(
                    DIGEST_SYSTEM_PROMPT, fix_prompt, model=model, json_mode=True
                )
                parsed2 = parse_json_lenient(raw2)
                errors2 = validate_digest_output(parsed2)
                if not errors2:
                    result.raw = raw2
                    result.parsed = parsed2
                    result.validation_errors = errors2
                    result.review_applied = True
                else:
                    # fix call output 有 schema error，留前次结果，标记
                    result.validation_errors.extend(
                        [f"fix-pass schema fail: {e}" for e in errors2]
                    )
            except Exception as e:
                result.validation_errors.append(f"fix pass failed: {e!r}")

    if write_to_staging and result.parsed:
        result.staging_result = apply_edits_to_staging(
            result.parsed, wiki_root=wiki_dir
        )

    return result


def _digest_call_with_retry(
    system: str, user_prompt: str, model: str, max_retries: int
):
    """Call digest LLM with schema-fail retry. Returns (raw, parsed, errors)."""
    retry = 0
    last_raw = ""
    last_parsed: dict | None = None
    last_errors: list[str] = []
    prompt = user_prompt

    while True:
        last_raw = call_llm(system, prompt, model=model, json_mode=True)
        try:
            last_parsed = parse_json_lenient(last_raw)
        except Exception as e:
            last_errors = [f"parse failed: {e!r}"]
            if retry >= max_retries:
                return last_raw, None, last_errors
            retry += 1
            prompt = _build_retry_prompt(user_prompt, None, last_errors)
            continue

        last_errors = validate_digest_output(last_parsed)
        if not last_errors or retry >= max_retries:
            return last_raw, last_parsed, last_errors

        retry += 1
        prompt = _build_retry_prompt(user_prompt, last_parsed, last_errors)


def _build_retry_prompt(orig_prompt: str, prior: dict | None, errors: list[str]) -> str:
    """Build a retry user prompt that includes prior output + schema errors."""
    prior_block = (
        "\n\n## 你前一次输出（含 schema 错误）\n\n```json\n"
        + json.dumps(prior, ensure_ascii=False, indent=2)
        + "\n```\n"
        if prior else ""
    )
    return (
        orig_prompt
        + "\n\n# 重试通知\n\n你的前一次输出有以下问题，请修正后重新输出完整 JSON：\n\n"
        + "\n".join(f"- {e}" for e in errors)
        + prior_block
    )
