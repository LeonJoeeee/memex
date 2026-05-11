"""Integration tests for service.digest — full pipeline with mocked LLM."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.mock_llm import MockClient


def _make_fake_wiki(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal wiki+docs structure for tests."""
    docs = tmp_path / "docs"
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "entities").mkdir(parents=True)
    docs.mkdir()
    return docs, wiki


def _valid_digest_json() -> str:
    return json.dumps({
        "verdict": "digested",
        "summary": "test source about Buffett",
        "feeds": ["wiki/concepts/Buffett.md"],
        "edits": [
            {
                "target": "wiki/concepts/Buffett.md",
                "action": "create",
                "rationale": "new concept",
                "content": "---\ntitle: Buffett\ntype: concept\n---\n# Buffett\n[[X]] [[Y]]\n",
                "key_facts": ["fact 1"],
                "wikilinks_added": ["[[X]]", "[[Y]]"],
                "confidence": "high",
            }
        ],
        "caveat": [],
    })


def test_happy_path(tmp_path, monkeypatch):
    """LLM 一次返回 valid JSON → digest_source 成功."""
    docs, wiki = _make_fake_wiki(tmp_path)
    (docs / "test.md").write_text("# Source: Buffett 1996 letter\n\ncontent")

    # 关键: shared MockClient instance（call_llm 每次 call get_client，
    # 不 share 会让每次 call 都从全集 pop[0] = 同一 response）
    shared = MockClient([_valid_digest_json()])
    monkeypatch.setattr("service.llm.get_client", lambda: shared)

    from service.digest import digest_source
    result = digest_source(
        "test.md", docs_dir=docs, wiki_dir=wiki,
        with_reviewer=False, write_to_staging=False,
    )

    assert not result.parse_failed
    assert result.parsed["verdict"] == "digested"
    assert len(result.parsed["edits"]) == 1
    assert result.validation_errors == []


def test_parse_failed_unrecoverable(tmp_path, monkeypatch):
    """LLM 返回完全垃圾 → parse_failed=True，digest_source 不挂."""
    docs, wiki = _make_fake_wiki(tmp_path)
    (docs / "test.md").write_text("source content")

    shared = MockClient(["not json at all", "still not json", "nope"])
    monkeypatch.setattr("service.llm.get_client", lambda: shared)

    from service.digest import digest_source
    result = digest_source(
        "test.md", docs_dir=docs, wiki_dir=wiki,
        with_reviewer=False, max_retries=2,
    )
    assert result.parse_failed is True
    assert len(result.validation_errors) >= 1


def test_schema_retry(tmp_path, monkeypatch):
    """LLM 第一次缺 verdict (schema 错)，第二次 valid → retry 成功."""
    docs, wiki = _make_fake_wiki(tmp_path)
    (docs / "test.md").write_text("source")

    bad = json.dumps({"summary": "x", "feeds": [], "edits": []})  # missing verdict
    shared = MockClient([bad, _valid_digest_json()])
    monkeypatch.setattr("service.llm.get_client", lambda: shared)

    from service.digest import digest_source
    result = digest_source(
        "test.md", docs_dir=docs, wiki_dir=wiki,
        with_reviewer=False, max_retries=2,
    )
    # 重试成功 → 最后输出合规
    assert not result.parse_failed
    assert result.parsed["verdict"] == "digested"
    assert result.validation_errors == []


def test_reviewer_finds_issues_and_fix(tmp_path, monkeypatch):
    """Reviewer 找到 coverage issue → fix call 产生改进版."""
    docs, wiki = _make_fake_wiki(tmp_path)
    (docs / "test.md").write_text("buffett source")

    initial_digest = _valid_digest_json()  # 只有 1 个 edit
    review_with_issues = json.dumps({
        "pass": False,
        "summary": "缺 Munger 实体页 ingest",
        "coverage_issues": ["wiki/entities/Munger.md 应追加但 digest 漏了"],
        "accuracy_issues": [],
        "rule_violations": [],
        "frontmatter_issues": [],
        "wikilink_issues": [],
        "hallucination_risk": [],
        "suggested_additions": [{"target": "wiki/entities/Munger.md", "action": "append"}],
    })
    # Fix 后的 digest 有 2 个 edits
    fixed_digest = json.dumps({
        "verdict": "digested",
        "summary": "test",
        "feeds": ["wiki/concepts/Buffett.md", "wiki/entities/Munger.md"],
        "edits": [
            {
                "target": "wiki/concepts/Buffett.md",
                "action": "create",
                "content": "...",
                "confidence": "high",
            },
            {
                "target": "wiki/entities/Munger.md",
                "action": "append",
                "content": "...",
                "confidence": "high",
            },
        ],
        "caveat": [],
    })

    shared = MockClient([initial_digest, review_with_issues, fixed_digest])
    monkeypatch.setattr("service.llm.get_client", lambda: shared)

    from service.digest import digest_source
    result = digest_source(
        "test.md", docs_dir=docs, wiki_dir=wiki, with_reviewer=True,
    )
    assert result.review is not None
    assert result.review_applied is True
    assert len(result.parsed["edits"]) == 2  # fix 后加了 Munger
    assert result.validation_errors == []


def test_source_not_found(tmp_path):
    docs, wiki = _make_fake_wiki(tmp_path)
    from service.digest import digest_source
    with pytest.raises(FileNotFoundError):
        digest_source("missing.md", docs_dir=docs, wiki_dir=wiki)


if __name__ == "__main__":
    import inspect
    import tempfile

    fns = [
        (n, f) for n, f in inspect.getmembers(sys.modules[__name__])
        if n.startswith("test_") and callable(f)
    ]
    # Use pytest if available for monkeypatch
    try:
        sys.exit(pytest.main(["-v", __file__]))
    except Exception as e:
        print(f"pytest unavailable / failed: {e!r}")
        sys.exit(1)
