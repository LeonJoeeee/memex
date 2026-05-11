"""memex MCP server — 暴露 ingest + (Phase 2.2) read 能力给任何 MCP client.

设计：
- 单租户分散部署（每人跑自己一份）
- Read-only by default：ingest 仍走 dry-run / staging，需要 --apply 才真改
- 同步模式（不用 FastMCP Tasks，避免 Docket+Redis 依赖）—— mimo digest
  ~30-60s 同步等可接受
- 端口 18766（避开 llm-wiki 旧 mcp_server 18765；将来 Phase 2.2 接管）

Phase 2.1 范围（这个文件）:
- wiki_guide()             — agent 自学
- wiki_ingest_source(...)  — digest 一个 docs/X.md → 返回 plan
- wiki_apply_staging(...)  — 把 staging 写到 production + git commit

Phase 2.2 (TODO):
- wiki_search / wiki_read / wiki_index / wiki_status (移植旧 server)
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .config import DOCS_DIR
from .digest import digest_source
from .git_ops import promote_staging_to_production
from .llm import DEFAULT_MODEL

mcp = FastMCP("memex")


@mcp.tool
def wiki_guide() -> str:
    """Call this FIRST. Returns the usage guide for memex MCP server."""
    return """# memex MCP server — usage guide

memex 是个人知识 specialist agent service（外置大脑）。
任何 user agent 都能通过 MCP 让 memex 帮自己消化内容 / 维护 wiki。

## Tools

- **wiki_guide()** — this guide
- **wiki_ingest_source(source, with_review)**
    输入：source 相对路径（如 "qingang_LiEA12.md"，相对 docs/ 目录）
    动作：跑 digest pipeline（grep 找候选页 → mimo digest → validate
          → optional reviewer pass）→ 写 staging/（不动 production）
    返回：digest plan（verdict / feeds / edits / staging files / review）
    note：with_review=True 触发二次 LLM call 审计，时间翻倍但质量更稳

- **wiki_apply_staging(source, message)**
    输入：source id（用于 commit message），可选 commit message
    动作：把 .staging/ 内容 copy 到 production wiki + git add + commit
    **永远不 git push** —— owner 手动决定 push

## Workflow

1. caller → wiki_ingest_source("X.md", with_review=True)
   → 拿到 plan，看 verdict / feeds / proposed edits
2. caller 评估 plan：质量 ok 吗 / 三铁律守了吗
3. ok → wiki_apply_staging("X.md") → 真改 wiki + commit
4. 异议 → 直接告诉 user，不 apply（staging 自动覆盖）

## Three iron rules（memex 内部 LLM 严守）

1. Concepts first, not sources
2. Sources feed concepts
3. No source-specific pages

## Read 能力

Phase 2.1 only ingest；read（wiki_search / wiki_read 等）仍走 llm-wiki
旧 server (18765 端口)。Phase 2.2 将统一到这里。
"""


@mcp.tool
def wiki_ingest_source(
    source: str,
    with_review: bool = True,
    write_to_staging: bool = True,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Digest a docs/ source into wiki update plan + staging.

    Args:
        source: source filename relative to docs/ (e.g. "qingang_LiEA12.md")
        with_review: run reviewer pass + fix call (default True，质量更稳)
        write_to_staging: write proposed edits to .staging/ dir (default True)
        model: LLM model name (default mimo-v2.5)

    Returns dict with:
        - verdict: "digested" | "partial" | "abandoned"
        - summary: one-line characterization
        - feeds: list of wiki pages affected
        - edits: list of {target, action, rationale, content excerpt}
        - validation_errors: schema-level issues
        - review: reviewer JSON (if with_review)
        - review_applied: whether fix call ran
        - staging_files: paths written to .staging/
        - next_step: hint for caller
    """
    source_path = DOCS_DIR / source
    if not source_path.exists():
        return {
            "error": f"Source not found: {source_path}",
            "next_step": "Check source path. It should be relative to llm-wiki/docs/",
        }

    try:
        result = digest_source(
            source,
            model=model,
            write_to_staging=write_to_staging,
            with_reviewer=with_review,
        )
    except Exception as e:
        return {"error": f"Digest failed: {e!r}"}

    parsed = result.parsed or {}
    out: dict[str, Any] = {
        "verdict": parsed.get("verdict"),
        "summary": parsed.get("summary"),
        "feeds": parsed.get("feeds", []),
        "edits": [
            {
                "target": e.get("target"),
                "action": e.get("action"),
                "rationale": e.get("rationale"),
                "confidence": e.get("confidence"),
                "content_preview": (e.get("content") or "")[:200],
                "key_facts": e.get("key_facts", []),
            }
            for e in parsed.get("edits", [])
        ],
        "caveat": parsed.get("caveat", []),
        "validation_errors": result.validation_errors,
        "parse_failed": result.parse_failed,
        "candidates_count": len(result.candidates),
        "prompt_chars": result.prompt_chars,
    }
    if result.review is not None:
        out["review"] = result.review
        out["review_applied"] = result.review_applied
    if result.staging_result:
        out["staging_files"] = {
            "created": result.staging_result.get("created", []),
            "appended": result.staging_result.get("appended", []),
            "errors": result.staging_result.get("errors", []),
        }

    # Hint for next step
    if result.parse_failed:
        out["next_step"] = "Parse failed; review raw output / retry with stronger model"
    elif result.validation_errors:
        out["next_step"] = "Validation errors exist; review before apply"
    elif parsed.get("verdict") == "abandoned":
        out["next_step"] = "Source abandoned (low value); no apply needed"
    else:
        out["next_step"] = (
            f"Review proposed edits, then call wiki_apply_staging({source!r}) to commit"
        )

    return out


@mcp.tool
def wiki_apply_staging(
    source: str,
    message: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Promote .staging/ → production wiki + git commit.

    **IMPORTANT**: apply=False (default) is dry-run. apply=True actually writes.

    Args:
        source: source id (used in commit message)
        message: optional custom commit message
        apply: if True, copy files + git commit; else dry-run only

    Returns dict with:
        - mode: "dry-run" | "applied"
        - promoted: list of file paths
        - skipped / errors: lists
        - diff_summary: human-readable diff overview
        - commit_hash: commit SHA (if applied)
        - next_step: hint
    """
    try:
        result = promote_staging_to_production(
            source_id=source,
            commit_message=message,
            dry_run=not apply,
        )
    except Exception as e:
        return {"error": f"git_ops failed: {e!r}"}

    out: dict[str, Any] = {
        "mode": "dry-run" if result.dry_run else "applied",
        "promoted": result.promoted,
        "skipped": result.skipped,
        "errors": result.errors,
        "diff_summary": result.diff_summary,
        "commit_hash": result.commit_hash,
    }
    if result.dry_run:
        out["next_step"] = (
            "This was dry-run. Call wiki_apply_staging(source, apply=True) to actually write + commit."
        )
    elif result.commit_hash:
        out["next_step"] = (
            f"Committed {result.commit_hash[:8]} (NOT pushed). "
            f"Owner can run `git push` manually."
        )
    elif result.promoted:
        out["next_step"] = "Files copied but commit failed; check errors."
    else:
        out["next_step"] = "Nothing to apply (no staging files?)."

    return out


def main():
    """Entry point. CLI: python -m service.mcp_server [--http [PORT]]"""
    import argparse

    parser = argparse.ArgumentParser(description="memex MCP server")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--stdio", action="store_true", help="stdio transport (default)")
    g.add_argument(
        "--http", nargs="?", const=18766, type=int, metavar="PORT",
        help="HTTP transport (default port 18766)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="HTTP bind host (default 127.0.0.1)",
    )
    args = parser.parse_args()

    if args.http is not None:
        mcp.run(transport="http", host=args.host, port=args.http)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
