"""Unit tests for service.config — yaml load + env override + fallback."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 必须在 import config 之前清掉 env，避免 dev 环境污染
_ENV_KEYS = [
    "MEMEX_WIKI_PATH", "MEMEX_BASE_URL", "MEMEX_API_KEY",
    "MEMEX_API_KEY_ENV", "MEMEX_DEFAULT_MODEL",
    "MEMEX_MCP_PORT", "MEMEX_MCP_HOST",
]


def _reset_env():
    for k in _ENV_KEYS:
        os.environ.pop(k, None)


def _reimport_config():
    """重新 import service.config 让它 reload."""
    sys.modules.pop("service.config", None)
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import service.config as cfg
    return cfg


def test_env_override_wiki_path(tmp_path):
    _reset_env()
    os.environ["MEMEX_WIKI_PATH"] = str(tmp_path)
    cfg = _reimport_config()
    assert cfg.LLMWIKI_ROOT == tmp_path
    assert cfg.DOCS_DIR == tmp_path / "docs"
    assert cfg.WIKI_DIR == tmp_path / "wiki"
    assert cfg.RAW_DIR == tmp_path / "raw"
    _reset_env()


def test_env_override_mcp():
    _reset_env()
    os.environ["MEMEX_MCP_PORT"] = "19999"
    os.environ["MEMEX_MCP_HOST"] = "0.0.0.0"
    cfg = _reimport_config()
    assert cfg.MCP_PORT == 19999
    assert cfg.MCP_HOST == "0.0.0.0"
    _reset_env()


def test_env_override_base_url():
    _reset_env()
    os.environ["MEMEX_BASE_URL"] = "https://example.com/v1"
    cfg = _reimport_config()
    assert cfg.get_base_url() == "https://example.com/v1"
    _reset_env()


def test_env_override_api_key():
    _reset_env()
    os.environ["MEMEX_API_KEY"] = "sk-test-direct-override"
    cfg = _reimport_config()
    assert cfg.get_api_key() == "sk-test-direct-override"
    _reset_env()


def test_env_api_key_via_named_env():
    _reset_env()
    os.environ["TEST_PROVIDER_KEY"] = "sk-named-env-key"
    os.environ["MEMEX_API_KEY_ENV"] = "TEST_PROVIDER_KEY"
    cfg = _reimport_config()
    assert cfg.get_api_key() == "sk-named-env-key"
    os.environ.pop("TEST_PROVIDER_KEY", None)
    _reset_env()


def test_default_model_fallback():
    _reset_env()
    cfg = _reimport_config()
    # 默认 "mimo-v2.5"
    assert cfg.DEFAULT_MODEL == "mimo-v2.5"


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
