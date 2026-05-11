"""memex configuration loader.

优先级（从高到低）:
1. 环境变量 (MEMEX_WIKI_PATH / MEMEX_BASE_URL / MEMEX_API_KEY / etc.)
2. ~/.config/memex/memex.yaml
3. <repo>/memex.yaml
4. 硬编码 fallback (当前 dev 部署)

设计原则：dev 时硬编码 fallback 仍指向 /home/leon/llm-wiki/，开源后用户给
yaml + env 即可。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

MEMEX_ROOT = Path(__file__).parent.parent

_CONFIG_PATHS = [
    Path.home() / ".config" / "memex" / "memex.yaml",
    MEMEX_ROOT / "memex.yaml",
]


def _load_config() -> dict:
    """Find first existing config file and load it."""
    for p in _CONFIG_PATHS:
        if p.exists():
            try:
                with p.open(encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError) as e:
                print(f"WARN: failed to load {p}: {e}")
    return {}


_cfg = _load_config()


def _get(dotted_path: str, default: Any = None, env: str | None = None) -> Any:
    """Lookup config value with env var override + nested dict navigation."""
    if env:
        v = os.environ.get(env)
        if v is not None and v != "":
            return v
    cur: Any = _cfg
    for key in dotted_path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
    return cur if cur is not None else default


# --- Wiki paths ---
LLMWIKI_ROOT = Path(_get("wiki.path", "/home/leon/llm-wiki", env="MEMEX_WIKI_PATH"))
DOCS_DIR = LLMWIKI_ROOT / _get("wiki.docs_subdir", "docs")
WIKI_DIR = LLMWIKI_ROOT / _get("wiki.wiki_subdir", "wiki")
INDEX_FILE = LLMWIKI_ROOT / _get("wiki.index_file", "INDEX.md")
RAW_DIR = LLMWIKI_ROOT / _get("wiki.raw_subdir", "raw")

# --- memex 自身路径 ---
STAGING_DIR = MEMEX_ROOT / ".staging"
ARTIFACT_DIR = MEMEX_ROOT

# --- LLM provider ---
LLM_BASE_URL = _get(
    "llm.base_url",
    "https://token-plan-sgp.xiaomimimo.com/v1",
    env="MEMEX_BASE_URL",
)
LLM_API_KEY_ENV = _get(
    "llm.api_key_env", "XIAOMI_API_KEY", env="MEMEX_API_KEY_ENV"
)
LLM_API_KEY_DIRECT = os.environ.get("MEMEX_API_KEY", "")  # direct override

DEFAULT_MODEL = _get(
    "llm.default_model", "mimo-v2.5", env="MEMEX_DEFAULT_MODEL"
)

# --- MCP ---
MCP_PORT = int(_get("mcp.port", 18766, env="MEMEX_MCP_PORT"))
MCP_HOST = _get("mcp.host", "127.0.0.1", env="MEMEX_MCP_HOST")

# --- Retrieval defaults ---
DEFAULT_CANDIDATE_COUNT = int(_get("retrieval.candidates", 15))
DEFAULT_PAGE_SUMMARY_LINES = int(_get("retrieval.page_summary_lines", 40))
KEYWORD_NOISE = set(_get("retrieval.keyword_noise", [
    "The", "This", "These", "Figure", "Table", "Section", "Available",
    "Online", "Received", "Accepted", "January", "February", "March",
    "April", "May", "June", "July", "August", "September", "October",
    "November", "December", "And", "But", "For", "With", "From",
]))
KEYWORD_MAX = int(_get("retrieval.keyword_max", 25))


def get_api_key() -> str:
    """Resolve API key from (priority):
    1. MEMEX_API_KEY (direct)
    2. env var named by LLM_API_KEY_ENV (e.g. XIAOMI_API_KEY)
    3. legacy: /home/leon/llm-wiki/tools/_env.py load_mimo_env()
    """
    if LLM_API_KEY_DIRECT:
        return LLM_API_KEY_DIRECT
    key = os.environ.get(LLM_API_KEY_ENV, "")
    if key:
        return key
    # Legacy fallback for current dev deployment
    try:
        import sys
        legacy = Path("/home/leon/llm-wiki/tools")
        if legacy.exists():
            if str(legacy) not in sys.path:
                sys.path.insert(0, str(legacy))
            from _env import load_mimo_env  # type: ignore
            key, _ = load_mimo_env()
            if key:
                return key
    except Exception:
        pass
    raise RuntimeError(
        f"No API key found. Set env var {LLM_API_KEY_ENV} (or MEMEX_API_KEY), "
        f"or provide memex.yaml with llm.api_key_env / write a .env in repo root."
    )


def get_base_url() -> str:
    """Resolve base_url. Same fallback chain as get_api_key for legacy."""
    if os.environ.get("MEMEX_BASE_URL"):
        return os.environ["MEMEX_BASE_URL"]
    if _get("llm.base_url"):
        return _get("llm.base_url")
    # Legacy fallback
    try:
        import sys
        legacy = Path("/home/leon/llm-wiki/tools")
        if legacy.exists():
            if str(legacy) not in sys.path:
                sys.path.insert(0, str(legacy))
            from _env import load_mimo_env  # type: ignore
            _, base = load_mimo_env()
            if base:
                return base
    except Exception:
        pass
    return LLM_BASE_URL  # final fallback default
