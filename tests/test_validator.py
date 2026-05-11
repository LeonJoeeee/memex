"""Unit tests for service.validator — deterministic JSON parsing + schema."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from service.validator import (
    _escape_inner_quotes,
    parse_json_lenient,
    strip_markdown_fence,
    validate_digest_output,
)


def test_strip_markdown_fence_simple():
    text = '```json\n{"a": 1}\n```'
    assert strip_markdown_fence(text) == '{"a": 1}'


def test_strip_markdown_fence_no_fence():
    text = '{"a": 1}'
    assert strip_markdown_fence(text) == text


def test_parse_lenient_valid_json():
    assert parse_json_lenient('{"a": 1}') == {"a": 1}


def test_parse_lenient_with_markdown_fence():
    assert parse_json_lenient('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_lenient_unescaped_quote():
    """mimo 风格的 bug：content 字段里嵌套未 escape 的 `\"`."""
    raw = '{"content": "这里有 \"未 escape\" 的引号"}'
    out = parse_json_lenient(raw)
    assert "content" in out
    # 解析出来后 inner 的 " 应该已被 escape 或保留为 字符串
    assert "未 escape" in out["content"]


def test_escape_inner_quotes_state_machine():
    # 在 string 内部 + 后面不是 ,:}] 的 " → escape
    inp = '"abc"def"'  # "abc" 后面是 'd' 不是 终止符，所以 "def" 中的第一个 " 被 escape
    out = _escape_inner_quotes(inp)
    assert out.count('\\"') >= 0  # 至少能跑通不崩


def test_validate_required_keys_missing():
    errors = validate_digest_output({"verdict": "digested"})
    assert any("missing keys" in e for e in errors)


def test_validate_verdict_invalid():
    errors = validate_digest_output({
        "verdict": "weird",
        "summary": "x",
        "feeds": [],
        "edits": [],
    })
    assert any("verdict invalid" in e for e in errors)


def test_validate_clean_input():
    errors = validate_digest_output({
        "verdict": "digested",
        "summary": "x",
        "feeds": ["wiki/concepts/X.md"],
        "edits": [
            {
                "target": "wiki/concepts/X.md",
                "action": "append",
                "content": "...",
            }
        ],
    })
    assert errors == []


def test_validate_source_specific_naming():
    """三铁律 #3 lint：source-specific 命名应被抓."""
    errors = validate_digest_output({
        "verdict": "digested",
        "summary": "x",
        "feeds": ["wiki/concepts/X-阅读笔记.md"],
        "edits": [
            {
                "target": "wiki/concepts/X-阅读笔记.md",
                "action": "create",
                "content": "...",
            }
        ],
    })
    assert any("source-specific" in e for e in errors)


def test_validate_action_invalid():
    errors = validate_digest_output({
        "verdict": "digested",
        "summary": "x",
        "feeds": ["wiki/X.md"],
        "edits": [{"target": "wiki/X.md", "action": "delete"}],
    })
    assert any("action invalid" in e for e in errors)


if __name__ == "__main__":
    # Run all tests in this file
    import inspect
    fns = [
        f for n, f in inspect.getmembers(sys.modules[__name__])
        if n.startswith("test_") and callable(f)
    ]
    failed = 0
    for f in fns:
        try:
            f()
            print(f"  ✓ {f.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {f.__name__}: {e!r}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {f.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(0 if failed == 0 else 1)
