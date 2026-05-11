"""Digest pipeline — single source → JSON spec (+ optional staging).

LLM 是 deterministic function（input prompt → output JSON），代码是 driver。
不是 agent。

Phase 1.1: 单 source 单次 LLM call → JSON → validate → optional staging
Phase 1.2 (TODO): retry loop on schema validate fail
Phase 1.2 (TODO): reviewer pass (2nd LLM call audits 1st output)
Phase 1.3 (TODO): promote staging → production wiki + git commit
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import DOCS_DIR, WIKI_DIR
from .llm import call_llm, DEFAULT_MODEL
from .prompts import DIGEST_SYSTEM_PROMPT
from .retriever import build_user_prompt, find_candidate_pages
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


def digest_source(
    source_rel: str,
    docs_dir: Path = DOCS_DIR,
    wiki_dir: Path = WIKI_DIR,
    model: str = DEFAULT_MODEL,
    write_to_staging: bool = False,
) -> DigestResult:
    """Digest single source → DigestResult.

    Args:
        source_rel: source path relative to docs_dir (e.g. "qingang_LiEA12.md")
        docs_dir: docs root
        wiki_dir: wiki root
        model: LLM model name
        write_to_staging: if True, apply LLM edits to .staging/ dir
    """
    source_path = docs_dir / source_rel
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    source_text = source_path.read_text()
    candidates = find_candidate_pages(source_text, wiki_dir)
    user_prompt = build_user_prompt(source_path, candidates)

    raw = call_llm(DIGEST_SYSTEM_PROMPT, user_prompt, model=model, json_mode=True)

    result = DigestResult(
        source=source_rel,
        raw=raw,
        parsed=None,
        validation_errors=[],
        candidates=candidates,
        prompt_chars=len(user_prompt),
    )

    try:
        result.parsed = parse_json_lenient(raw)
    except Exception as e:
        result.parse_failed = True
        result.validation_errors = [f"parse failed: {e!r}"]
        return result

    result.validation_errors = validate_digest_output(result.parsed)

    if write_to_staging:
        result.staging_result = apply_edits_to_staging(
            result.parsed, wiki_root=wiki_dir
        )

    return result
