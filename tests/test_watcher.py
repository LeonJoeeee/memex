"""Tests for service.watcher — stability check, dedup, handler.

Filesystem events 用 tmp_path + 直接 instantiate handler 跑（不真启 Observer）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_is_file_stable_static(tmp_path):
    from service.watcher import is_file_stable
    p = tmp_path / "stable.txt"
    p.write_text("hello")
    # size 不变 → stable
    assert is_file_stable(p, check_sec=1) is True


def test_is_file_stable_missing(tmp_path):
    from service.watcher import is_file_stable
    p = tmp_path / "nope.txt"
    # 不存在 → False, 不崩
    assert is_file_stable(p, check_sec=1) is False


def test_already_processed_no_docs(tmp_path, monkeypatch):
    """没对应 docs/ output → 未处理."""
    monkeypatch.setattr("service.watcher.DOCS_DIR", tmp_path / "docs")
    (tmp_path / "docs").mkdir()
    from service.watcher import already_processed
    raw = tmp_path / "newfile.pdf"
    raw.touch()
    assert already_processed(raw) is False


def test_already_processed_has_docs(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "existing.md").touch()

    monkeypatch.setattr("service.watcher.DOCS_DIR", docs_dir)
    from service.watcher import already_processed
    raw = tmp_path / "existing.pdf"
    raw.touch()
    assert already_processed(raw) is True


def test_log_event_to_stderr(tmp_path, capfd):
    from service.watcher import log_event
    log_event({"event": "test", "x": 42})
    out, err = capfd.readouterr()
    # log_event 写 stderr
    assert "test" in err
    assert '"x": 42' in err


def test_log_pending_apply_writes_file(tmp_path, monkeypatch):
    pending_file = tmp_path / ".pending.jsonl"
    monkeypatch.setattr("service.watcher.PENDING_FILE", pending_file)

    from service.watcher import log_pending_apply
    log_pending_apply("test.md", {"status": "ok", "stages": {}})
    log_pending_apply("test2.md", {"status": "failed", "stages": {}})

    assert pending_file.exists()
    lines = pending_file.read_text().splitlines()
    assert len(lines) == 2
    recs = [json.loads(ln) for ln in lines]
    assert recs[0]["source"] == "test.md"
    assert recs[1]["source"] == "test2.md"
    assert recs[1]["result"]["status"] == "failed"


def test_handler_skips_hidden_files(tmp_path, monkeypatch):
    """RawFolderHandler.on_created 应该 skip 隐藏 + tmp 文件."""
    from service.watcher import RawFolderHandler

    handler = RawFolderHandler()

    # Set up mock state so _handle won't actually run pipeline
    monkeypatch.setattr("service.watcher.is_file_stable", lambda p, **kw: False)
    monkeypatch.setattr("service.watcher.already_processed", lambda p: False)

    # Hidden file
    hidden = tmp_path / ".hidden.pdf"
    hidden.write_text("x")
    # tmp file
    tmpf = tmp_path / "x.tmp"
    tmpf.write_text("x")

    # 调 _handle 不该 raise (skip path)
    handler._handle(hidden)
    handler._handle(tmpf)
    # _in_flight 应该不持有 (因为 skip 在 lock 前)
    assert str(hidden) not in handler._in_flight
    assert str(tmpf) not in handler._in_flight


def test_handler_skips_already_processed(tmp_path, monkeypatch):
    from service.watcher import RawFolderHandler

    monkeypatch.setattr("service.watcher.already_processed", lambda p: True)
    monkeypatch.setattr("service.watcher.is_file_stable", lambda p, **kw: True)

    pipeline_calls = []

    def fake_pipeline(p):
        pipeline_calls.append(p)
        return {"status": "ok"}

    monkeypatch.setattr("service.watcher.process_pipeline", fake_pipeline)

    handler = RawFolderHandler()
    raw = tmp_path / "existing.pdf"
    raw.write_text("x")
    handler._handle(raw)

    # already_processed 时不该调 pipeline
    assert pipeline_calls == []
