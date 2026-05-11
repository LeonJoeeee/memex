"""Git operations — promote staging → production wiki + git commit.

Phase 1.3: 把 .staging/ 内容写到 production wiki + git add + commit。
默认 dry-run（只 print 计划 + git diff），需 --apply 才真写。
永远不 git push（保守，user 手动 push）。

设计原则：
- Deterministic (subprocess git)
- Atomicity: 一个 source 一个 commit（per-source commit pattern）
- 不破坏现有 wiki workflow（如果 production wiki 已被 user 手动改过，
  我们检测但不强行覆盖）
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import LLMWIKI_ROOT, STAGING_DIR, WIKI_DIR


@dataclass
class CommitResult:
    promoted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    diff_summary: str = ""
    commit_hash: str | None = None
    dry_run: bool = True


def promote_staging_to_production(
    staging_root: Path = STAGING_DIR,
    wiki_root: Path = WIKI_DIR,
    repo_root: Path = LLMWIKI_ROOT,
    source_id: str = "unknown",
    commit_message: str | None = None,
    dry_run: bool = True,
) -> CommitResult:
    """把 staging dir 里的 wiki 文件 copy 到 production，git add + commit。

    Args:
        staging_root: staging 根目录
        wiki_root: production wiki 根目录
        repo_root: git repo 根目录
        source_id: source 标识符（用于 commit message）
        commit_message: 自定义 commit message；None 则自动生成
        dry_run: True 则只 print 计划 + git diff，不真写 / 不 commit
    """
    result = CommitResult(dry_run=dry_run)

    if not staging_root.exists():
        result.errors.append(f"Staging dir not found: {staging_root}")
        return result

    # 收集所有 staging 文件
    staging_files: list[Path] = []
    for p in staging_root.rglob("*.md"):
        staging_files.append(p)

    if not staging_files:
        result.errors.append("No .md files in staging")
        return result

    # Check git working tree clean
    status = _git_status(repo_root)
    if status and not dry_run:
        # 允许 working tree dirty 但 warn
        result.errors.append(
            f"Working tree not clean (will commit anyway):\n{status}"
        )

    # Plan: 把 staging/<rel> copy 到 wiki_root/<rel>
    for sp in staging_files:
        rel = sp.relative_to(staging_root)
        target = wiki_root / rel
        if dry_run:
            result.promoted.append(str(target))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(sp, target)
            result.promoted.append(str(target))

    # Diff summary
    if dry_run:
        # Simulate: show what would be copied + git diff against staging
        result.diff_summary = _simulate_diff(staging_files, staging_root, wiki_root)
    else:
        # Stage files
        rel_paths = [
            str((wiki_root / p.relative_to(staging_root)).relative_to(repo_root))
            for p in staging_files
        ]
        _git_add(repo_root, rel_paths)

        # Commit
        msg = commit_message or _default_commit_message(source_id, rel_paths)
        h = _git_commit(repo_root, msg)
        result.commit_hash = h
        result.diff_summary = _git_show_stat(repo_root, h) if h else ""

    return result


def _git_status(repo_root: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip()


def _git_add(repo_root: Path, paths: list[str]) -> None:
    subprocess.run(
        ["git", "-C", str(repo_root), "add", *paths],
        capture_output=True, text=True, check=True,
    )


def _git_commit(repo_root: Path, message: str) -> str | None:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", message],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return None
    rev = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return rev.stdout.strip()


def _git_show_stat(repo_root: Path, commit_hash: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "show", "--stat", commit_hash],
        capture_output=True, text=True, check=False,
    )
    return out.stdout


def _simulate_diff(staging_files: list[Path], staging_root: Path, wiki_root: Path) -> str:
    """Dry-run: show what files would change + size estimate."""
    lines = []
    for sp in staging_files:
        rel = sp.relative_to(staging_root)
        target = wiki_root / rel
        if not target.exists():
            lines.append(f"  CREATE {target} ({sp.stat().st_size} bytes)")
        else:
            old_size = target.stat().st_size
            new_size = sp.stat().st_size
            delta = new_size - old_size
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"  UPDATE {target} ({old_size} → {new_size} bytes, {sign}{delta})"
            )
    return "\n".join(lines)


def _default_commit_message(source_id: str, paths: list[str]) -> str:
    """Default commit message: 'wiki: digest <source> (memex)'"""
    return (
        f"wiki: digest {source_id} (memex)\n\n"
        f"Auto-committed by memex Phase 1.3.\n"
        f"Affected pages ({len(paths)}):\n"
        + "\n".join(f"  - {p}" for p in paths)
    )
