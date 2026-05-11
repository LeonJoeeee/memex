"""Unit tests for service.staging — frontmatter merge + apply edits."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from service.staging import (
    _add_to_yaml_list,
    apply_edits_to_staging,
    apply_frontmatter_update,
)


def test_add_to_yaml_list_existing_block():
    fm = """title: X
sources:
  - "docs/a.md"
  - "docs/b.md"
related:
  - "[[Y]]"
"""
    out = _add_to_yaml_list(fm, "sources", ["docs/c.md"])
    assert '"docs/c.md"' in out
    # 原有内容仍在
    assert '"docs/a.md"' in out
    assert '"docs/b.md"' in out


def test_add_to_yaml_list_dedup():
    fm = """sources:
  - "docs/a.md"
"""
    out = _add_to_yaml_list(fm, "sources", ["docs/a.md"])
    # 不重复添加
    assert out.count('"docs/a.md"') == 1


def test_add_to_yaml_list_new_field():
    fm = """title: X
"""
    out = _add_to_yaml_list(fm, "sources", ["docs/a.md"])
    assert "sources:" in out
    assert '"docs/a.md"' in out


def test_apply_frontmatter_update_sources_add():
    text = """---
title: X
sources:
  - "docs/a.md"
updated: 2026-01-01
---

# X body
"""
    fm_update = {"sources_add": ["docs/b.md"], "updated": "2026-05-11"}
    out = apply_frontmatter_update(text, fm_update)
    assert '"docs/b.md"' in out
    assert "updated: 2026-05-11" in out
    assert "updated: 2026-01-01" not in out
    assert "# X body" in out


def test_apply_frontmatter_update_no_frontmatter():
    text = "# Just a heading\n\nbody"
    fm_update = {"sources_add": ["docs/a.md"]}
    out = apply_frontmatter_update(text, fm_update)
    # 没 frontmatter，不动
    assert out == text


def test_apply_edits_to_staging_create(tmp_path):
    staging = tmp_path / ".staging"
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()

    parsed = {
        "edits": [
            {
                "target": "wiki/concepts/NewConcept.md",
                "action": "create",
                "content": "---\ntitle: NewConcept\n---\n# New",
            }
        ]
    }
    result = apply_edits_to_staging(parsed, staging_root=staging, wiki_root=wiki_root)
    assert len(result["created"]) == 1
    assert (staging / "concepts" / "NewConcept.md").exists()


def test_apply_edits_to_staging_invalid_target(tmp_path):
    staging = tmp_path / ".staging"
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()

    parsed = {
        "edits": [{"target": "not_wiki/X.md", "action": "create", "content": "x"}]
    }
    result = apply_edits_to_staging(parsed, staging_root=staging, wiki_root=wiki_root)
    assert len(result["errors"]) == 1


if __name__ == "__main__":
    import inspect
    fns = [
        (n, f) for n, f in inspect.getmembers(sys.modules[__name__])
        if n.startswith("test_") and callable(f)
    ]
    failed = 0
    for name, f in fns:
        # Manually inject tmp_path for those that need it
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
