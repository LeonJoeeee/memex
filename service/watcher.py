"""File watcher for raw/ folder.

设计:
- 监控 /home/leon/llm-wiki/raw/ 新文件 (递归子目录)
- 文件 stable (size 不再变化) 后触发 pipeline:
    raw/X → preprocess (复用 llm-wiki/tools/preprocess.py CLI)
          → docs/Y  → digest_source (mimo)
          → .staging/
          → (default 不 auto-apply，加入 pending applies queue)
- watcher 是 background service，跑在自己的 systemd unit

Phase 2.4 范围:
- 不 auto-apply（避免污染 production wiki）
- 不并发 (Phase 3 加 multiprocessing)
- 失败 log 到 .pending_applies.jsonl + journald
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import DOCS_DIR, LLMWIKI_ROOT, MEMEX_ROOT, RAW_DIR
from .digest import digest_source

PENDING_FILE = MEMEX_ROOT / ".pending_applies.jsonl"
STABILITY_CHECK_SEC = 5  # 文件 size 这么多秒不变才算 stable
STABILITY_POLL_SEC = 1


def is_file_stable(path: Path, check_sec: int = STABILITY_CHECK_SEC) -> bool:
    """文件 size 在 check_sec 秒内不变化 → stable。"""
    try:
        size1 = path.stat().st_size
    except OSError:
        return False
    for _ in range(int(check_sec / STABILITY_POLL_SEC)):
        time.sleep(STABILITY_POLL_SEC)
        try:
            size2 = path.stat().st_size
        except OSError:
            return False
        if size2 != size1:
            return False
        size1 = size2
    return True


def already_processed(raw_path: Path) -> bool:
    """检查 raw_path 对应的 docs/X.md 是否已存在 (粗粒度去重)"""
    safe_name = raw_path.stem.replace(" ", "_")
    candidates = list(DOCS_DIR.rglob(f"{safe_name}*.md"))
    return len(candidates) > 0


def run_preprocess(raw_path: Path) -> Path | None:
    """跑 preprocess.py 处理单个 raw 文件。返回产出的 docs/X.md (推断)。

    preprocess.py 是个 CLI 工具，处理 raw/ 全目录扫。我们 invoke 一次
    限定类型，让它处理我们关心的文件类型。它会自己 archive + 去重。
    """
    preprocess_script = LLMWIKI_ROOT / "tools" / "preprocess.py"
    # 推断类型
    ext = raw_path.suffix.lower()
    type_map = {
        ".pdf": "pdf",
        ".epub": "book", ".mobi": "book", ".azw3": "book",
        ".mp3": "av", ".mp4": "av", ".wav": "av", ".m4a": "av",
        ".png": "image", ".jpg": "image", ".jpeg": "image",
    }
    file_type = type_map.get(ext)
    if not file_type:
        log_event({"event": "skip", "reason": f"unsupported ext: {ext}", "raw": str(raw_path)})
        return None

    cmd = [
        sys.executable, str(preprocess_script),
        "--types", file_type,
    ]
    log_event({"event": "preprocess_start", "raw": str(raw_path), "cmd": cmd})
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
            cwd=str(LLMWIKI_ROOT),
        )
    except subprocess.TimeoutExpired:
        log_event({"event": "preprocess_timeout", "raw": str(raw_path)})
        return None

    if out.returncode != 0:
        log_event({
            "event": "preprocess_fail", "raw": str(raw_path),
            "returncode": out.returncode,
            "stderr_tail": out.stderr[-500:] if out.stderr else "",
        })
        return None

    # preprocess 完成；尝试找对应 docs/X.md
    safe_name = raw_path.stem.replace(" ", "_")
    candidates = list(DOCS_DIR.rglob(f"{safe_name}*.md"))
    if not candidates:
        log_event({"event": "preprocess_no_output", "raw": str(raw_path)})
        return None

    # 最新一个
    docs_path = max(candidates, key=lambda p: p.stat().st_mtime)
    log_event({"event": "preprocess_done", "raw": str(raw_path), "docs": str(docs_path)})
    return docs_path


def process_pipeline(raw_path: Path) -> dict:
    """跑完整 pipeline: preprocess → digest → 写 staging → log pending apply.

    不 auto-apply 到 production wiki (Phase 2.4 default 保守).
    """
    result: dict[str, Any] = {
        "raw": str(raw_path),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stages": {},
    }

    # 1. preprocess
    docs_path = run_preprocess(raw_path)
    if docs_path is None:
        result["stages"]["preprocess"] = "failed_or_skipped"
        result["status"] = "failed"
        return result
    result["stages"]["preprocess"] = {"docs": str(docs_path)}

    # 2. digest (with_reviewer + write_to_staging)
    source_rel = docs_path.relative_to(DOCS_DIR).as_posix()
    log_event({"event": "digest_start", "source": source_rel})
    try:
        d = digest_source(source_rel, with_reviewer=True, write_to_staging=True)
    except Exception as e:
        result["stages"]["digest"] = f"failed: {e!r}"
        result["status"] = "failed"
        log_event({"event": "digest_fail", "source": source_rel, "err": repr(e)})
        return result

    result["stages"]["digest"] = {
        "verdict": (d.parsed or {}).get("verdict"),
        "feeds": (d.parsed or {}).get("feeds", []),
        "edits_count": len(((d.parsed or {}).get("edits") or [])),
        "validation_errors": d.validation_errors,
        "review_applied": d.review_applied,
        "staging_files": sorted(
            (d.staging_result or {}).get("appended", [])
            + (d.staging_result or {}).get("created", [])
        ),
    }
    result["status"] = "digested" if not d.validation_errors else "digested_with_errors"

    # 3. log pending apply（让 user 后续手动 wiki_apply_staging）
    log_pending_apply(source_rel, result)
    log_event({"event": "pipeline_done", "source": source_rel, "status": result["status"]})
    return result


def log_event(event: dict) -> None:
    """Append to journald via stderr + a local log."""
    msg = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}, ensure_ascii=False)
    print(msg, file=sys.stderr, flush=True)


def log_pending_apply(source: str, result: dict) -> None:
    """记下一个待 apply 的 staging。User 调 wiki_apply_staging 时检查。"""
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "result": result,
    }
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class RawFolderHandler(FileSystemEventHandler):
    """监控 raw/ 新文件。Stable 后触发 pipeline。"""

    def __init__(self):
        super().__init__()
        # 防重入：同时只处理一个文件 (Phase 3 改并发)
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()

    def on_created(self, event: FileSystemEvent):
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return
        # mv into raw/ 也算 created
        self._handle(Path(event.dest_path))

    def _handle(self, path: Path):
        # 过滤隐藏文件 / 临时文件
        if path.name.startswith(".") or path.name.endswith(".tmp"):
            return
        # 过滤已经 processed
        if already_processed(path):
            log_event({"event": "skip_already_processed", "raw": str(path)})
            return
        # in-flight 防重入
        key = str(path)
        with self._lock:
            if key in self._in_flight:
                return
            self._in_flight.add(key)

        try:
            log_event({"event": "new_file", "raw": str(path)})
            # 等文件 stable
            if not is_file_stable(path):
                log_event({"event": "skip_unstable", "raw": str(path)})
                return
            # 跑 pipeline
            result = process_pipeline(path)
            log_event({"event": "result_summary", "raw": str(path), "status": result.get("status")})
        except Exception as e:
            log_event({"event": "handler_exception", "raw": str(path), "err": repr(e)})
        finally:
            with self._lock:
                self._in_flight.discard(key)


def run_watcher(raw_dir: Path = RAW_DIR) -> None:
    """Long-running watcher entry. 阻塞直到 SIGTERM。"""
    if not raw_dir.exists():
        raise FileNotFoundError(f"raw_dir not exists: {raw_dir}")

    log_event({"event": "watcher_start", "raw_dir": str(raw_dir)})
    handler = RawFolderHandler()
    observer = Observer()
    observer.schedule(handler, str(raw_dir), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log_event({"event": "watcher_stop", "reason": "KeyboardInterrupt"})
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    run_watcher()
