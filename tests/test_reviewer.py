"""Unit tests for service.reviewer — pass/fail judgment + prompt builder."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from service.reviewer import build_reviewer_prompt, has_meaningful_issues, is_pass


def test_is_pass_all_good():
    review = {
        "pass": True,
        "coverage_issues": [],
        "accuracy_issues": [],
        "rule_violations": [],
        "hallucination_risk": [],
        "frontmatter_issues": [],
    }
    assert is_pass(review) is True


def test_is_pass_explicit_false():
    review = {"pass": False, "accuracy_issues": []}
    assert is_pass(review) is False


def test_is_pass_critical_accuracy_overrides():
    """Even if pass=True, accuracy_issues 非空 → 实际不 pass."""
    review = {
        "pass": True,
        "accuracy_issues": ["digit 'L=265' but source said '26.5'"],
    }
    assert is_pass(review) is False


def test_is_pass_critical_rule_violation_overrides():
    review = {"pass": True, "rule_violations": ["X-notes.md is source-specific"]}
    assert is_pass(review) is False


def test_is_pass_critical_hallucination_overrides():
    review = {
        "pass": True,
        "hallucination_risk": ["claim 'X is from MIT' not in source"],
    }
    assert is_pass(review) is False


def test_is_pass_frontmatter_minor_does_not_override():
    """frontmatter / wikilink / coverage 是 minor 类，不会 override pass=True."""
    review = {
        "pass": True,
        "frontmatter_issues": ["sources_add 为空"],
        "wikilink_issues": ["缺 [[Y]]"],
        "coverage_issues": [],  # coverage 现在是 critical? 看 is_pass 实现
        "accuracy_issues": [],
        "rule_violations": [],
        "hallucination_risk": [],
    }
    assert is_pass(review) is True


def test_has_meaningful_issues_empty():
    review = {"pass": True}
    assert has_meaningful_issues(review) is False


def test_has_meaningful_issues_coverage():
    review = {"coverage_issues": ["missing X"]}
    assert has_meaningful_issues(review) is True


def test_has_meaningful_issues_suggested_additions():
    review = {"suggested_additions": [{"target": "wiki/X.md"}]}
    assert has_meaningful_issues(review) is True


def test_build_reviewer_prompt_includes_all_parts(tmp_path, monkeypatch):
    src_path = tmp_path / "src.md"
    src_path.write_text("# Source\n\nbuffett 1996 letter content")

    # Make fake candidates inside tmp_path (will patch LLMWIKI_ROOT to tmp_path)
    cand_dir = tmp_path / "wiki" / "concepts"
    cand_dir.mkdir(parents=True)
    candidate = cand_dir / "Buffett.md"
    candidate.write_text("---\ntitle: Buffett\n---\n\n# Buffett page")

    # service.reviewer uses LLMWIKI_ROOT for path resolution → patch to tmp_path
    monkeypatch.setattr("service.reviewer.LLMWIKI_ROOT", tmp_path)

    digest_parsed = {
        "verdict": "digested",
        "summary": "test",
        "feeds": ["wiki/concepts/Buffett.md"],
        "edits": [{"target": "wiki/concepts/Buffett.md", "action": "append"}],
    }

    prompt = build_reviewer_prompt(
        src_path.read_text(), digest_parsed, [candidate], "src.md"
    )
    assert "buffett 1996 letter content" in prompt
    assert "Buffett page" in prompt
    assert '"verdict": "digested"' in prompt
    assert "docs/src.md" in prompt
    assert "JSON" in prompt or "json" in prompt


if __name__ == "__main__":
    import inspect
    import tempfile

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
