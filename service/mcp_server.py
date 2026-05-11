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

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Union

from fastmcp import FastMCP

from .config import (
    DOCS_DIR, INDEX_FILE, LLMWIKI_ROOT, MCP_HOST, MCP_PORT, MEMEX_ROOT, WIKI_DIR,
)
from .digest import digest_source
from .git_ops import promote_staging_to_production
from .llm import DEFAULT_MODEL
from .query import query_wiki as _query_wiki

mcp = FastMCP("memex")

# Pending query log file（外部 client search miss 时记录）
_PENDING_FILE = MEMEX_ROOT / ".pending_queries.jsonl"


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

## Ask the expert ⭐ 主用

- **wiki_ask_expert(question, depth)** — **问 memex 这个专家一个问题**
    类比：你问一个 AI+空间物理+投资 跨界专家一个问题。
    memex 在后台调它积累的 wiki，像专家一样综合，给你**专家的回答**。
    depth: "quick" (~30s) | "deep" (~60s)
    返回 {answer, citations, confidence, related_pages, follow_up_questions, gaps}

## Read tools (P2.2，原料级)

- **wiki_search(query, budget)** — grep wiki/，budget: "quick" | "deep"
- **wiki_read(paths)** — 读完整 wiki 页（接受 str 或 list[str]）
- **wiki_index(filter)** — INDEX.md 内容（filter: concepts/entities/...）
- **wiki_status(target)** — None=kanban; "docs/X.md"=lifecycle; "wiki/X.md"=source-of
- **wiki_recent_changes(n)** — 最近 N 个 wiki/ git commit
- **wiki_stats()** — 总页数 / 主题分布 / 字数 / 最大 5 页 / 最近 commit

## Coverage 信号

`wiki_search` 返回时含 coverage="high/medium/low/miss"。
低 coverage → 自动 log 到 pending queue → 下次 owner session 检查。
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


# ---------------------- Query / RAG (P2.3) ----------------------


@mcp.tool
def wiki_ask_expert(question: str, depth: str = "quick") -> dict[str, Any]:
    """**问 memex 这个专家一个问题** — 像一个人向另一个有积累的人提问。

    memex = 跨界专家 agent（AI 工程 / 空间物理 / 金融投资等，看 wiki 涵盖范围）。
    wiki 是它的 long-term memory，是它过去消化积累的所有知识。

    工作流（类比人类专家咨询）：
      caller 提问 → memex 调取相关 wiki → 像专家一样思考综合 → 给答复
      caller 拿到的是**专家的回答**，不是 raw wiki 内容。

    Args:
        question: 你的问题（中文 / 英文 / 混合）
        depth: "quick" (~30s) | "deep" (~60s, 看更多 wiki 页综合)

    Returns dict:
        - answer:              markdown 答案 (专家回答，含 inline cite)
        - citations:           ["wiki/concepts/X.md", ...]
        - confidence:          "high" | "medium" | "low"
        - related_pages:       可继续探索的相关 wiki 页
        - follow_up_questions: 你可能要追问的 1-3 个问题
        - gaps:                memex 意识到的 wiki 未充分涵盖的 sub-topic

    跟原料级 tools 的差别:
        - wiki_search/read: 你要 raw 素材，自己综合
        - wiki_ask_expert:  问专家，拿专家的答复（不污染你的 context）

    范围边界:
        memex 只回答 wiki 涵盖范围内的问题。范围外（如 "今天天气"）会明说不知道。
    """
    if depth not in ("quick", "deep"):
        depth = "quick"
    try:
        return _query_wiki(question, depth=depth)
    except Exception as e:
        return {"error": f"query failed: {e!r}", "question": question}


# ---------------------- Read tools (P2.2) ----------------------


@mcp.tool
def wiki_search(query: str, budget: str = "quick") -> str:
    """Search the wiki for `query`. budget: "quick" or "deep".

    quick: titles + frontmatter + 3 max-count per file
    deep:  full-text + 2-line context around matches

    Coverage signal in output. Misses are logged to pending queue.
    """
    if budget not in ("quick", "deep"):
        budget = "quick"

    flags = ["-i", "-n", "--type-add", "wiki:*.md", "-twiki"]
    if budget == "quick":
        flags += ["--max-count", "3"]
    else:
        flags += ["-C", "2"]

    # Multi-word query → OR regex
    words = query.split()
    pattern = (
        "(" + "|".join(re.escape(w) for w in words) + ")"
        if len(words) > 1 else query
    )

    try:
        out = subprocess.run(
            ["rg", *flags, "--", pattern, str(WIKI_DIR)],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return f"Search timed out for query: {query!r}"
    except FileNotFoundError:
        return "ripgrep (rg) not found."

    if out.returncode == 1:
        _log_pending(query, hit_quality="miss")
        return (
            f"No matches for {query!r}. Query logged to pending queue."
        )

    raw_lines = out.stdout.splitlines()
    truncated_note = ""
    if len(raw_lines) > 200:
        truncated_note = (
            f"\n... ({len(raw_lines) - 200} more lines truncated)"
        )
        raw_lines = raw_lines[:200]

    body = "\n".join(raw_lines)
    distinct_files = len({ln.split(":", 1)[0] for ln in raw_lines if ":" in ln})
    coverage = "high" if distinct_files >= 3 else ("medium" if distinct_files >= 1 else "low")
    if coverage == "low":
        _log_pending(query, hit_quality="thin")

    return (
        f"# Wiki search: {query}\n\n"
        f"budget: {budget} | coverage: {coverage} | matched files: {distinct_files}\n\n"
        f"```\n{body}{truncated_note}\n```\n"
    )


@mcp.tool
def wiki_read(paths: Union[str, list[str]]) -> str:
    """Read full content of wiki page(s). paths: str or list[str].

    Accepts: "wiki/concepts/X.md" / "concepts/X.md" / "X.md" (will search common subdirs).
    """
    if isinstance(paths, str):
        paths = [paths]
    chunks: list[str] = []
    for p in paths:
        full = _resolve_wiki_path(p)
        if full is None:
            chunks.append(f"# Not found: {p}\n")
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except OSError as e:
            chunks.append(f"# Read error: {p}: {e}\n")
            continue
        cl = content.splitlines()
        if len(cl) > 2000:
            content = "\n".join(cl[:2000]) + (
                f"\n\n... ({len(cl) - 2000} more lines truncated)"
            )
        rel = full.relative_to(LLMWIKI_ROOT)
        chunks.append(f"# {rel}\n\n{content}\n")
    return "\n\n---\n\n".join(chunks)


@mcp.tool
def wiki_index(filter: str | None = None) -> str:
    """Return wiki INDEX. filter: concepts/entities/comparisons/archived/None."""
    if not INDEX_FILE.exists():
        return "INDEX.md not found."
    content = INDEX_FILE.read_text(encoding="utf-8")
    if filter is None:
        return content
    f = filter.strip("/").lower()
    valid = {"concepts", "entities", "comparisons", "archived"}
    if f not in valid:
        return f"Unknown filter {filter!r}. Use one of: {sorted(valid)}."
    needle = f"wiki/{f}/"
    matched = [ln for ln in content.splitlines() if needle in ln]
    if not matched:
        return f"No entries with `{needle}` in INDEX."
    return f"# wiki/{f}/ ({len(matched)} entries)\n\n" + "\n".join(matched)


@mcp.tool
def wiki_status(target: str | None = None) -> str:
    """Pipeline state.

    - None: kanban (lifecycle overview)
    - "docs/X.md": lifecycle of a source
    - "wiki/X.md": which sources fed this page
    """
    state_py = LLMWIKI_ROOT / "tools" / "state.py"
    if target is None:
        cmd = ["python3", str(state_py), "kanban"]
    elif target.startswith("wiki/"):
        cmd = ["python3", str(state_py), "source-of", target]
    elif target.startswith("docs/") or target.startswith("raw/"):
        cmd = ["python3", str(state_py), "lifecycle", target]
    else:
        return (
            f"Unrecognized target: {target!r}. "
            f"Use 'docs/X.md' for lifecycle, 'wiki/X.md' for source-of, or omit for kanban."
        )
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "state.py timed out."
    body = out.stdout or "(no output)"
    if out.stderr:
        body += f"\n\n--stderr--\n{out.stderr}"
    return f"```\n{body}\n```"


@mcp.tool
def wiki_pending() -> str:
    """List queries that hit miss/thin coverage and are queued for enrichment."""
    if not _PENDING_FILE.exists():
        return "No pending queries."
    text = _PENDING_FILE.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "No pending queries."
    rows = []
    for ln in lines:
        try:
            r = json.loads(ln)
            rows.append(
                f"- `{r.get('ts','?')}` — `{r.get('hit_quality','?')}` — "
                f"{r.get('query','?')}"
            )
        except json.JSONDecodeError:
            continue
    shown = rows[-50:]
    suffix = (
        f"\n\n_(showing latest 50 of {len(rows)})_" if len(rows) > 50 else ""
    )
    return f"# Pending queries ({len(rows)})\n\n" + "\n".join(shown) + suffix


@mcp.tool
def wiki_recent_changes(n: int = 10) -> str:
    """最近 N 个 wiki commit（git log 输出）。

    Args:
        n: 数量（默认 10，最大 50）

    返回 markdown 列出 commit hash / 时间 / 一行 message / 改动文件数。
    """
    n = max(1, min(n, 50))
    cmd = [
        "git", "-C", str(LLMWIKI_ROOT),
        "log", f"-{n}", "--pretty=format:%h|%ai|%s", "--shortstat",
        "--", "wiki/",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "git log timed out."

    if out.returncode != 0:
        return f"git log failed: {out.stderr.strip()[:300]}"

    lines = out.stdout.strip().splitlines()
    rows = []
    current: dict[str, Any] = {}
    for ln in lines:
        if "|" in ln and ln.count("|") >= 2:
            if current:
                rows.append(current)
            parts = ln.split("|", 2)
            current = {"hash": parts[0], "time": parts[1], "subj": parts[2]}
        elif ln.strip().startswith(tuple(str(i) for i in range(10))):
            # shortstat line: " 3 files changed, 80 insertions(+), 2 deletions(-)"
            current["stat"] = ln.strip()
    if current:
        rows.append(current)

    if not rows:
        return f"No commits touching wiki/ in last {n}."

    out_lines = [f"# Recent wiki/ changes (last {len(rows)})\n"]
    for r in rows:
        stat = r.get("stat", "")
        out_lines.append(f"- `{r['hash']}` {r['time'][:10]} **{r['subj']}**")
        if stat:
            out_lines.append(f"  {stat}")
    return "\n".join(out_lines)


@mcp.tool
def wiki_stats() -> dict[str, Any]:
    """Wiki 总览统计：页数 / 总字数 / 主题分布 / 最大页 top 5.

    Returns dict with:
        - total_pages: 总 wiki 页数
        - by_type: {concepts: N, entities: N, ...}
        - total_bytes: 总字节
        - total_lines: 总行数
        - top_5_pages: 最大 5 页 (lines, path)
        - last_commit: 最近 wiki/ commit hash + 时间
    """
    counts: dict[str, int] = {}
    total_bytes = 0
    total_lines = 0
    page_sizes: list[tuple[int, str]] = []

    for p in WIKI_DIR.rglob("*.md"):
        if not p.is_file():
            continue
        # 分类（concepts / entities / comparisons / archived）
        try:
            rel = p.relative_to(WIKI_DIR)
            top = rel.parts[0] if rel.parts else "root"
        except ValueError:
            top = "unknown"
        counts[top] = counts.get(top, 0) + 1

        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        total_bytes += len(text.encode("utf-8"))
        n_lines = len(text.splitlines())
        total_lines += n_lines
        page_sizes.append((n_lines, str(p.relative_to(LLMWIKI_ROOT))))

    page_sizes.sort(reverse=True)
    top_5 = [{"lines": n, "path": p} for n, p in page_sizes[:5]]

    # last commit on wiki/
    last_commit = None
    try:
        cmd = [
            "git", "-C", str(LLMWIKI_ROOT),
            "log", "-1", "--pretty=format:%h|%ai|%s",
            "--", "wiki/",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split("|", 2)
            last_commit = {"hash": parts[0], "time": parts[1], "subj": parts[2]}
    except subprocess.TimeoutExpired:
        pass

    return {
        "total_pages": sum(counts.values()),
        "by_type": counts,
        "total_bytes": total_bytes,
        "total_lines": total_lines,
        "top_5_pages": top_5,
        "last_commit": last_commit,
    }


@mcp.tool
def wiki_pending_applies() -> str:
    """List staging digest 结果待 apply 到 production wiki 的队列.

    File watcher (P2.4) 检测到 raw/ 新文件后自动 preprocess + digest +
    写 .staging/，但 default 不 auto-apply。Owner 可通过此 tool 看队列，
    然后调 wiki_apply_staging(source, apply=True) 真应用。
    """
    pending_file = MEMEX_ROOT / ".pending_applies.jsonl"
    if not pending_file.exists():
        return "No pending applies."
    text = pending_file.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "No pending applies."
    rows = []
    for ln in lines:
        try:
            r = json.loads(ln)
            res = r.get("result", {})
            d = res.get("stages", {}).get("digest", {})
            verdict = d.get("verdict", "?") if isinstance(d, dict) else "?"
            edits = d.get("edits_count", "?") if isinstance(d, dict) else "?"
            staged = len(d.get("staging_files", [])) if isinstance(d, dict) else "?"
            rows.append(
                f"- `{r.get('ts','?')}` — {r.get('source','?')} — "
                f"verdict={verdict} edits={edits} staged_files={staged}"
            )
        except json.JSONDecodeError:
            continue
    shown = rows[-50:]
    suffix = (
        f"\n\n_(showing latest 50 of {len(rows)})_" if len(rows) > 50 else ""
    )
    return (
        f"# Pending applies ({len(rows)})\n\n"
        + "\n".join(shown)
        + suffix
        + "\n\nApply with: wiki_apply_staging(source, apply=True)"
    )


def _resolve_wiki_path(p: str) -> Path | None:
    """Resolve user-provided path against repo root with fallbacks."""
    p = p.lstrip("/")
    if not p.endswith(".md"):
        p = p + ".md"
    candidates = [
        LLMWIKI_ROOT / p,
        WIKI_DIR / p,
        WIKI_DIR / "concepts" / Path(p).name,
        WIKI_DIR / "entities" / Path(p).name,
        WIKI_DIR / "comparisons" / Path(p).name,
        WIKI_DIR / "archived" / Path(p).name,
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def _log_pending(query: str, hit_quality: str) -> None:
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "query": query,
        "hit_quality": hit_quality,
    }
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _PENDING_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------- entry ----------------------


def main():
    """Entry point. CLI: python -m service.mcp_server [--http [PORT]]"""
    import argparse

    parser = argparse.ArgumentParser(description="memex MCP server")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--stdio", action="store_true", help="stdio transport (default)")
    g.add_argument(
        "--http", nargs="?", const=MCP_PORT, type=int, metavar="PORT",
        help=f"HTTP transport (default port {MCP_PORT}, from config)",
    )
    parser.add_argument(
        "--host", default=MCP_HOST,
        help=f"HTTP bind host (default {MCP_HOST}, from config)",
    )
    args = parser.parse_args()

    if args.http is not None:
        mcp.run(transport="http", host=args.host, port=args.http)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
