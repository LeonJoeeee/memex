"""memex CLI entry — python -m service <subcommand>

Subcommands:
    digest <source>   — digest a docs/X.md → JSON spec (+ optional staging + reviewer)
    commit <source>   — promote staging → production wiki + git commit
    [TODO P2] query <question>  — RAG synthesis query
    [TODO P2] serve             — start MCP server
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import DOCS_DIR, STAGING_DIR
from .digest import DigestResult, digest_source
from .git_ops import promote_staging_to_production
from .llm import DEFAULT_MODEL


def cmd_digest(args) -> int:
    eprint(f"=== Digesting {args.source} ===")
    if args.review:
        eprint("(reviewer pass enabled)")
    try:
        result = digest_source(
            args.source,
            model=args.model,
            write_to_staging=args.write_to_staging,
            with_reviewer=args.review,
            max_retries=args.max_retries,
        )
    except FileNotFoundError as e:
        eprint(f"ERROR: {e}")
        return 2
    except Exception as e:
        eprint(f"ERROR: {e!r}")
        return 1

    print_digest_summary(result)

    if args.save:
        _save_artifact(args.source, result)

    if args.raw_to_stdout:
        print("\n" + "=" * 60)
        print("RAW LLM OUTPUT")
        print("=" * 60)
        print(result.raw)

    if result.parse_failed:
        return 3
    if result.validation_errors:
        return 4
    return 0


def print_digest_summary(r: DigestResult):
    eprint(f"Candidates: {len(r.candidates)} pages")
    eprint(f"Prompt: ~{r.prompt_chars} chars")
    eprint(f"Raw response: {len(r.raw)} chars")

    if r.parse_failed:
        print("\n" + "=" * 60)
        print("JSON PARSE FAILED")
        print("=" * 60)
        for e in r.validation_errors:
            print(f"  - {e}")
        return

    p = r.parsed or {}

    print("\n" + "=" * 60)
    print("SCHEMA VALIDATION")
    print("=" * 60)
    if r.validation_errors:
        for e in r.validation_errors:
            print(f"  - {e}")
    else:
        print("  OK")

    print("\n" + "=" * 60)
    print("PROPOSED CHANGES")
    print("=" * 60)
    print(f"Verdict: {p.get('verdict')}")
    print(f"Summary: {p.get('summary')}")
    print(f"\nFeeds ({len(p.get('feeds', []))}):")
    for f in p.get("feeds", []):
        print(f"  - {f}")
    print(f"\nEdits ({len(p.get('edits', []))}):")
    for e in p.get("edits", []):
        action = e.get("action", "?")
        target = e.get("target", "?")
        conf = e.get("confidence", "?")
        rationale = (e.get("rationale", "") or "")[:80]
        print(f"  - [{action:6s}] {target}")
        print(f"      conf={conf} | {rationale}")
        kf = e.get("key_facts", [])
        if kf:
            print(f"      key_facts: {kf[:3]}{'...' if len(kf) > 3 else ''}")
    caveat = p.get("caveat", [])
    if caveat:
        print("\nCaveat:")
        for c in caveat:
            print(f"  - {c}")

    if r.review is not None:
        print("\n" + "=" * 60)
        print(f"REVIEWER PASS (applied={r.review_applied})")
        print("=" * 60)
        print(f"Pass: {r.review.get('pass')}")
        print(f"Summary: {r.review.get('summary', '')}")
        for cat in (
            "coverage_issues", "accuracy_issues", "rule_violations",
            "frontmatter_issues", "wikilink_issues", "hallucination_risk",
        ):
            issues = r.review.get(cat, [])
            if issues:
                print(f"\n{cat} ({len(issues)}):")
                for i in issues:
                    print(f"  - {i}")
        suggested = r.review.get("suggested_additions", [])
        if suggested:
            print(f"\nsuggested_additions ({len(suggested)}):")
            for s in suggested:
                print(f"  - [{s.get('action', '?')}] {s.get('target')}: {s.get('rationale', '')}")

    if r.staging_result:
        print("\n" + "=" * 60)
        print(f"STAGING ({STAGING_DIR})")
        print("=" * 60)
        for k in ("created", "appended", "errors"):
            for path in r.staging_result.get(k, []):
                marker = {"created": "CREATE", "appended": "APPEND", "errors": "ERROR "}
                print(f"  {marker[k]}  {path}")


def _save_artifact(source: str, r: DigestResult):
    from .config import ARTIFACT_DIR
    name = source.replace("/", "_").replace(".md", "")
    out = ARTIFACT_DIR / f".spike_output_{name}.json"
    out.write_text(
        json.dumps(
            {
                "source": r.source,
                "raw": r.raw,
                "parsed": r.parsed,
                "validation_errors": r.validation_errors,
                "staging_result": r.staging_result,
                "candidates": [str(p) for p in r.candidates],
            },
            indent=2, ensure_ascii=False,
        )
    )
    eprint(f"Saved artifact: {out}")


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def main():
    ap = argparse.ArgumentParser(prog="python -m service", description="memex CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_digest = sub.add_parser("digest", help="Digest a docs/ source")
    p_digest.add_argument(
        "source", help="Source file relative to llm-wiki/docs/"
    )
    p_digest.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"LLM model (default: {DEFAULT_MODEL})"
    )
    p_digest.add_argument(
        "--write-to-staging", action="store_true",
        help="Apply edits to .staging/ (mirror of wiki/, NOT production)",
    )
    p_digest.add_argument(
        "--save", action="store_true",
        help="Save artifact JSON to .spike_output_*.json",
    )
    p_digest.add_argument(
        "--raw-to-stdout", action="store_true",
        help="Also print raw LLM output to stdout",
    )
    p_digest.add_argument(
        "--review", action="store_true",
        help="Run reviewer pass + fix call after first digest",
    )
    p_digest.add_argument(
        "--max-retries", type=int, default=2,
        help="Retry digest LLM call on schema validation fail (default: 2)",
    )

    p_commit = sub.add_parser(
        "commit",
        help="Promote .staging/ → production wiki + git commit (dry-run default)",
    )
    p_commit.add_argument(
        "source", help="Source id for commit message (e.g. qingang_LiEA12.md)"
    )
    p_commit.add_argument(
        "--apply", action="store_true",
        help="Actually copy files + git commit (otherwise dry-run)",
    )
    p_commit.add_argument(
        "--message", default=None, help="Custom commit message (else auto)"
    )

    args = ap.parse_args()

    if args.cmd == "digest":
        return cmd_digest(args)
    if args.cmd == "commit":
        return cmd_commit(args)
    return 1


def cmd_commit(args) -> int:
    eprint(f"=== Promote staging → production for {args.source} ===")
    eprint(f"Mode: {'APPLY (real)' if args.apply else 'DRY-RUN'}")
    result = promote_staging_to_production(
        source_id=args.source,
        commit_message=args.message,
        dry_run=not args.apply,
    )

    print("=" * 60)
    print("FILES")
    print("=" * 60)
    for p in result.promoted:
        marker = "WOULD COPY" if result.dry_run else "COPIED"
        print(f"  {marker}  {p}")
    for p in result.skipped:
        print(f"  SKIPPED     {p}")
    for e in result.errors:
        print(f"  WARN/ERROR  {e}")

    if result.diff_summary:
        print("\n" + "=" * 60)
        print("DIFF SUMMARY" if result.dry_run else "COMMIT STAT")
        print("=" * 60)
        print(result.diff_summary)

    if result.commit_hash:
        print(f"\nCommit: {result.commit_hash}")
        print("NOT pushed (run `git push` manually if intended).")
    elif not result.dry_run and result.promoted:
        print("\n⚠️ Files copied but commit failed (see errors)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
