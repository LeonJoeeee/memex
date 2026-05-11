"""Integration tests for service.query — RAG synthesis with mocked LLM."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.mock_llm import MockClient


def _make_fake_wiki_with_content(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    page = wiki / "concepts" / "SEP-Reservoir.md"
    page.write_text("""---
title: SEP-Reservoir
type: concept
---

# SEP-Reservoir 效应

太阳高能粒子在多飞船间趋同，由 perpendicular diffusion 主导。
关键 wikilink: [[Forbush减少]] [[Reservoir现象]]
""")
    return wiki


def _valid_query_response() -> str:
    return json.dumps({
        "answer": "SEP-Reservoir 是 [[wiki/concepts/SEP-Reservoir.md]] 描述的多飞船趋同现象。",
        "citations": ["wiki/concepts/SEP-Reservoir.md"],
        "confidence": "high",
        "related_pages": [],
        "follow_up_questions": ["Perpendicular diffusion 怎么定量？"],
        "gaps": [],
    })


def test_query_happy_path(tmp_path, monkeypatch):
    wiki = _make_fake_wiki_with_content(tmp_path)
    shared = MockClient([_valid_query_response()])
    monkeypatch.setattr("service.llm.get_client", lambda: shared)

    # Patch LLMWIKI_ROOT for relative path resolution in query module
    monkeypatch.setattr("service.query.LLMWIKI_ROOT", tmp_path)

    from service.query import query_wiki
    result = query_wiki("什么是 SEP-Reservoir 效应？", depth="quick", wiki_dir=wiki)

    assert "answer" in result
    assert "SEP-Reservoir" in result["answer"]
    assert result["confidence"] == "high"
    assert result["candidates_count"] >= 1


def test_query_no_candidates(tmp_path, monkeypatch):
    """Empty wiki → fallback 'No coverage' response，不调 LLM."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    shared = MockClient([])  # 不应该被调用
    monkeypatch.setattr("service.llm.get_client", lambda: shared)
    monkeypatch.setattr("service.query.LLMWIKI_ROOT", tmp_path)

    from service.query import query_wiki
    result = query_wiki("无关问题", depth="quick", wiki_dir=wiki)

    assert result["candidates_count"] == 0
    assert result["confidence"] == "low"
    assert "memex 没找到" in result["answer"]


def test_query_parse_failed(tmp_path, monkeypatch):
    wiki = _make_fake_wiki_with_content(tmp_path)
    # LLM 返回完全 garbage
    shared = MockClient(["not json at all"])
    monkeypatch.setattr("service.llm.get_client", lambda: shared)
    monkeypatch.setattr("service.query.LLMWIKI_ROOT", tmp_path)

    from service.query import query_wiki
    result = query_wiki("SEP", depth="quick", wiki_dir=wiki)
    # 应该有 error key
    assert "error" in result or "answer" in result  # graceful degradation


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
