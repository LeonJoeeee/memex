"""Tests for service.retriever — find_candidate_pages + read_page_summary.

用真 ripgrep + tmp_path wiki（不 mock subprocess）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from service.retriever import (
    build_user_prompt,
    find_candidate_pages,
    read_page_summary,
)


def _make_wiki(tmp_path: Path) -> Path:
    """Build a small fake wiki for retrieval tests."""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "entities").mkdir(parents=True)

    (wiki / "concepts" / "Reservoir.md").write_text("""---
title: Reservoir 现象
type: concept
---
# Reservoir
SEP transport with perpendicular diffusion. Mentions Buffett 偶尔.
""")

    (wiki / "entities" / "Buffett.md").write_text("""---
title: 巴菲特
type: entity
---
# Buffett
Berkshire Hathaway. Investing.
""")

    (wiki / "entities" / "Charlie.md").write_text("""---
title: Charlie Munger
type: entity
---
# Charlie
Vice chairman of Berkshire Hathaway.
""")

    return wiki


def test_find_candidate_pages_buffett_keywords(tmp_path):
    wiki = _make_wiki(tmp_path)
    source = "buffett 1996 letter discusses Berkshire and Charlie Munger"

    candidates = find_candidate_pages(source, wiki_dir=wiki, k=10)
    names = [p.name for p in candidates]
    # 应该包含 Buffett + Charlie + Reservoir (Buffett 也提)
    assert "Buffett.md" in names
    assert "Charlie.md" in names


def test_find_candidate_pages_no_match(tmp_path):
    wiki = _make_wiki(tmp_path)
    source = "Quantum chromodynamics gluon QCD lagrangian"

    candidates = find_candidate_pages(source, wiki_dir=wiki, k=10)
    # 没匹配，返回空 list
    assert candidates == []


def test_find_candidate_pages_respects_k(tmp_path):
    wiki = _make_wiki(tmp_path)
    source = "Berkshire Hathaway Charlie Munger Buffett"

    candidates = find_candidate_pages(source, wiki_dir=wiki, k=2)
    assert len(candidates) <= 2


def test_read_page_summary(tmp_path):
    p = tmp_path / "concept.md"
    lines = [f"line {i}" for i in range(100)]
    p.write_text("\n".join(lines))

    out = read_page_summary(p, max_lines=10, root=tmp_path)
    assert "line 0" in out
    assert "line 9" in out
    assert "line 50" not in out  # truncated at 10


def test_read_page_summary_missing_file(tmp_path):
    """Returns empty string for non-existent file (graceful)."""
    out = read_page_summary(tmp_path / "nope.md", root=tmp_path)
    assert out == ""


def test_build_user_prompt_includes_source_and_candidates(tmp_path):
    wiki = _make_wiki(tmp_path)
    src = tmp_path / "buffett_1996.md"
    src.write_text("# Buffett 1996 letter content with Charlie reference")

    # build_user_prompt 用 LLMWIKI_ROOT 计算 relative path，候选要在该 root 下
    # candidates 用绝对路径就 OK
    candidate = wiki / "entities" / "Buffett.md"

    import service.retriever as r
    # patch LLMWIKI_ROOT to tmp_path 让 relative_to 成功
    original = r.LLMWIKI_ROOT
    r.LLMWIKI_ROOT = tmp_path
    try:
        prompt = build_user_prompt(src, [candidate])
    finally:
        r.LLMWIKI_ROOT = original

    assert "Buffett 1996 letter content with Charlie reference" in prompt
    assert "docs/buffett_1996.md" in prompt
    assert "Buffett.md" in prompt
    assert "三铁律" in prompt or "JSON" in prompt
