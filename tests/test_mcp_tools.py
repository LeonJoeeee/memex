"""Tests for stats / recent_changes MCP tools (no LLM)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _init_repo_with_wiki_commits(tmp_path: Path) -> None:
    """Build a fake repo with wiki/ commits for testing."""
    subprocess.run(["git", "-C", str(tmp_path), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True, capture_output=True)

    wiki = tmp_path / "wiki" / "concepts"
    wiki.mkdir(parents=True)

    # commit 1
    (wiki / "X.md").write_text("---\ntitle: X\n---\n# X\n\nshort\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "wiki: add X"], check=True, capture_output=True)

    # commit 2 - entity
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "Y.md").write_text("---\ntitle: Y\n---\n# Y\n\nlonger\ncontent\nhere\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "wiki: add Y entity"], check=True, capture_output=True)


def test_wiki_stats_basic(tmp_path, monkeypatch):
    _init_repo_with_wiki_commits(tmp_path)
    monkeypatch.setattr("service.mcp_server.WIKI_DIR", tmp_path / "wiki")
    monkeypatch.setattr("service.mcp_server.LLMWIKI_ROOT", tmp_path)

    from service.mcp_server import wiki_stats
    result = wiki_stats()

    assert result["total_pages"] == 2
    assert result["by_type"]["concepts"] == 1
    assert result["by_type"]["entities"] == 1
    assert result["total_bytes"] > 0
    assert result["total_lines"] > 0
    assert len(result["top_5_pages"]) == 2
    assert result["last_commit"] is not None
    assert "wiki: add" in result["last_commit"]["subj"]


def test_wiki_stats_handles_non_utf8(tmp_path, monkeypatch):
    """非 utf-8 文件应被跳过，不崩."""
    wiki = tmp_path / "wiki" / "concepts"
    wiki.mkdir(parents=True)
    # utf-8 文件
    (wiki / "ok.md").write_text("# OK")
    # 非 utf-8 binary 文件
    (wiki / "bad.md").write_bytes(b"\xff\xfe binary garbage")

    # 没 git repo OK，last_commit 会是 None
    monkeypatch.setattr("service.mcp_server.WIKI_DIR", tmp_path / "wiki")
    monkeypatch.setattr("service.mcp_server.LLMWIKI_ROOT", tmp_path)

    from service.mcp_server import wiki_stats
    result = wiki_stats()
    # 不崩 + ok.md 被算入但 bad.md 被跳过
    assert result["total_pages"] == 2  # rglob 找到 2 个 .md
    # but only utf-8 文件的 lines / bytes 被累加
    assert result["total_bytes"] > 0


def test_wiki_recent_changes(tmp_path, monkeypatch):
    _init_repo_with_wiki_commits(tmp_path)
    monkeypatch.setattr("service.mcp_server.LLMWIKI_ROOT", tmp_path)

    from service.mcp_server import wiki_recent_changes
    out = wiki_recent_changes(5)

    assert "Recent wiki/ changes" in out
    assert "wiki: add X" in out
    assert "wiki: add Y entity" in out


def test_wiki_recent_changes_clamps_n(tmp_path, monkeypatch):
    _init_repo_with_wiki_commits(tmp_path)
    monkeypatch.setattr("service.mcp_server.LLMWIKI_ROOT", tmp_path)

    from service.mcp_server import wiki_recent_changes
    # n=0 should clamp to 1
    out_low = wiki_recent_changes(0)
    assert "Recent wiki/" in out_low
    # n=999 clamp to 50
    out_high = wiki_recent_changes(999)
    assert "Recent wiki/" in out_high


def test_wiki_recent_changes_no_commits(tmp_path, monkeypatch):
    """空 repo → 友好提示，不崩."""
    subprocess.run(["git", "-C", str(tmp_path), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True, capture_output=True)
    # 一个 commit 但不在 wiki/
    (tmp_path / "README").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)

    monkeypatch.setattr("service.mcp_server.LLMWIKI_ROOT", tmp_path)

    from service.mcp_server import wiki_recent_changes
    out = wiki_recent_changes(5)
    # 没 wiki/ commit → "No commits..."
    assert "No commits" in out
