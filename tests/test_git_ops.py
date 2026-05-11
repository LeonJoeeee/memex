"""Unit tests for service.git_ops — dry-run + real commit (tmp git repo)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from service.git_ops import (
    _default_commit_message,
    _simulate_diff,
    promote_staging_to_production,
)


def _init_git_repo(path: Path) -> None:
    """Init a minimal git repo with one initial commit."""
    subprocess.run(["git", "-C", str(path), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    (path / "README.md").write_text("# test\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True, capture_output=True,
    )


def test_default_commit_message():
    msg = _default_commit_message("source.md", ["wiki/X.md", "wiki/Y.md"])
    assert "source.md" in msg
    assert "wiki/X.md" in msg
    assert "memex" in msg.lower()


def test_dry_run_create(tmp_path):
    """staging has new files; dry-run lists them as CREATE."""
    staging = tmp_path / "staging"
    wiki = tmp_path / "wiki"
    repo = tmp_path
    staging.mkdir()
    wiki.mkdir()
    _init_git_repo(repo)

    (staging / "concepts").mkdir(parents=True)
    (staging / "concepts" / "X.md").write_text("# X content")

    result = promote_staging_to_production(
        staging_root=staging, wiki_root=wiki, repo_root=repo,
        source_id="test.md", dry_run=True,
    )
    assert result.dry_run is True
    assert len(result.promoted) == 1
    assert "X.md" in result.promoted[0]
    assert result.commit_hash is None
    assert "CREATE" in result.diff_summary


def test_dry_run_update(tmp_path):
    """staging file exists in production already; dry-run lists as UPDATE with delta."""
    staging = tmp_path / "staging"
    wiki = tmp_path / "wiki"
    repo = tmp_path
    staging.mkdir()
    wiki.mkdir()
    _init_git_repo(repo)

    target = wiki / "X.md"
    target.write_text("original\n")
    (staging / "X.md").write_text("original\nplus more\n")

    result = promote_staging_to_production(
        staging_root=staging, wiki_root=wiki, repo_root=repo,
        source_id="test.md", dry_run=True,
    )
    assert "UPDATE" in result.diff_summary
    # delta = new - old > 0
    assert "+" in result.diff_summary


def test_real_apply_commits(tmp_path):
    """dry_run=False 真 copy + git commit。"""
    staging = tmp_path / "staging"
    wiki = tmp_path / "wiki"
    repo = tmp_path
    staging.mkdir()
    wiki.mkdir()
    _init_git_repo(repo)

    (staging / "concepts").mkdir(parents=True)
    (staging / "concepts" / "NewX.md").write_text("# NewX\n\nbody\n")

    result = promote_staging_to_production(
        staging_root=staging, wiki_root=wiki, repo_root=repo,
        source_id="test.md", dry_run=False,
    )
    assert result.dry_run is False
    assert result.commit_hash is not None
    assert len(result.commit_hash) == 40  # SHA-1
    # 文件真的 copy 过去
    target = wiki / "concepts" / "NewX.md"
    assert target.exists()
    # git log 应该有 2 个 commit（init + new）
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    )
    assert len(log.stdout.splitlines()) == 2


def test_simulate_diff_empty():
    out = _simulate_diff([], Path("/tmp/s"), Path("/tmp/w"))
    assert out == ""


def test_no_staging_dir(tmp_path):
    """staging 不存在 → 报 error，不崩。"""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _init_git_repo(tmp_path)

    result = promote_staging_to_production(
        staging_root=tmp_path / "nope", wiki_root=wiki, repo_root=tmp_path,
        source_id="x.md", dry_run=True,
    )
    assert len(result.errors) > 0
    assert "not found" in result.errors[0].lower()


if __name__ == "__main__":
    import inspect

    fns = [
        (n, f) for n, f in inspect.getmembers(sys.modules[__name__])
        if n.startswith("test_") and callable(f)
    ]
    failed = 0
    for name, f in fns:
        try:
            if "tmp_path" in inspect.signature(f).parameters:
                with tempfile.TemporaryDirectory() as td:
                    f(Path(td))
            else:
                f()
            print(f"  ✓ {name}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}: {e!r}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(0 if failed == 0 else 1)
