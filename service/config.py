"""memex configuration.

Phase 1: 硬编码路径（指向 llm-wiki 当前部署）。
Phase 4 (开箱即用): 改成 yaml + env var load，用户给 base_url + api_key + wiki_path。
"""
from __future__ import annotations

from pathlib import Path

# Wiki 数据源（Phase 4 改 config）
LLMWIKI_ROOT = Path("/home/leon/llm-wiki")
DOCS_DIR = LLMWIKI_ROOT / "docs"
WIKI_DIR = LLMWIKI_ROOT / "wiki"
INDEX_FILE = LLMWIKI_ROOT / "INDEX.md"

# memex 自身路径
MEMEX_ROOT = Path(__file__).parent.parent
STAGING_DIR = MEMEX_ROOT / ".staging"
ARTIFACT_DIR = MEMEX_ROOT  # spike output JSON 落这里

# Retrieval defaults
DEFAULT_CANDIDATE_COUNT = 15
DEFAULT_PAGE_SUMMARY_LINES = 40
KEYWORD_NOISE = {
    "The", "This", "These", "Figure", "Table", "Section", "Available",
    "Online", "Received", "Accepted", "January", "February", "March",
    "April", "May", "June", "July", "August", "September", "October",
    "November", "December", "And", "But", "For", "With", "From",
}
KEYWORD_MAX = 25
