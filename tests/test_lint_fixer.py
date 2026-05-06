#!/usr/bin/env python3
"""Tests for tools.renpy_lint_fixer — lint error parsing and auto-fix logic."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.renpy_lint_fixer import (
    _fix_errors,
    _parse_lint_errors,
    _remove_consecutive_empty_lines,
    is_lint_available,
)


# ---------------------------------------------------------------------------
# Tests: consecutive empty line cleanup
# ---------------------------------------------------------------------------


def test_remove_consecutive_empty_lines():
    """Collapse multiple empty lines into one."""
    lines = ["a\n", "\n", "\n", "\n", "b\n", "\n", "c\n"]
    result = _remove_consecutive_empty_lines(lines)
    assert result == ["a\n", "\n", "b\n", "\n", "c\n"]
    print("[OK] test_remove_consecutive_empty_lines")


def test_remove_consecutive_no_change():
    """No change when there are no consecutive empty lines."""
    lines = ["a\n", "\n", "b\n", "\n", "c\n"]
    result = _remove_consecutive_empty_lines(lines)
    assert result == lines
    print("[OK] test_remove_consecutive_no_change")


# ---------------------------------------------------------------------------
# Tests: lint error parsing
# ---------------------------------------------------------------------------


def test_parse_lint_termination_error():
    """Parse 'not terminated with a newline' error."""
    output = (
        "At script.rpy, line 42: is not terminated with a newline. (Check strings and parenthesis.)"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = _parse_lint_errors(output, Path(tmpdir))
    assert len(errors) == 1
    assert errors[0][1] == 41  # 0-indexed (line 42 → 41)
    assert "terminated" in errors[0][2]
    print("[OK] test_parse_lint_termination_error")


def test_parse_lint_end_of_line():
    """Parse 'end of line expected' error."""
    output = "At tl/chinese/script.rpy, line 15: end of line expected."
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = _parse_lint_errors(output, Path(tmpdir))
    assert len(errors) == 1
    assert errors[0][1] == 14
    print("[OK] test_parse_lint_end_of_line")


def test_parse_lint_empty_block():
    """Parse 'expects a non-empty block' error."""
    output = "At game/script.rpy, line 100: expects a non-empty block."
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = _parse_lint_errors(output, Path(tmpdir))
    assert len(errors) == 1
    assert errors[0][1] == 99
    print("[OK] test_parse_lint_empty_block")


def test_parse_lint_unknown_statement():
    """Parse 'unknown statement' error."""
    output = "At screens.rpy, line 5: unknown statement"
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = _parse_lint_errors(output, Path(tmpdir))
    assert len(errors) == 1
    assert "unknown" in errors[0][2]
    print("[OK] test_parse_lint_unknown_statement")


def test_parse_lint_duplicate_translation():
    """Parse duplicate translation error."""
    output = "Exception: A translation for start_12345 already exists at tl/chinese/script.rpy:42."
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = _parse_lint_errors(output, Path(tmpdir))
    assert len(errors) == 1
    assert errors[0][1] == 42
    assert "duplicate" in errors[0][2]
    print("[OK] test_parse_lint_duplicate_translation")


def test_parse_lint_multiple_errors():
    """Parse multiple errors from lint output."""
    output = """
Some info line
At script.rpy, line 10: end of line expected.
Some other info
At script.rpy, line 20: unknown statement
Exception: A translation for test_123 already exists at tl/zh/screens.rpy:5.
At screens.rpy, line 30: expected statement.
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = _parse_lint_errors(output, Path(tmpdir))
    assert len(errors) == 4
    print("[OK] test_parse_lint_multiple_errors")


def test_parse_lint_no_errors():
    """No errors in clean lint output."""
    output = "Lint complete. No errors found."
    with tempfile.TemporaryDirectory() as tmpdir:
        errors = _parse_lint_errors(output, Path(tmpdir))
    assert errors == []
    print("[OK] test_parse_lint_no_errors")


# ---------------------------------------------------------------------------
# Tests: error fixing
# ---------------------------------------------------------------------------


def test_fix_old_new_pair():
    """Fix error on an old/new translation pair."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        test_file = tmpdir / "script.rpy"
        test_file.write_text(
            "    # comment\n"
            '    old "Hello"\n'
            '    new "你好\n'  # Missing closing quote — error on this line
            "\n"
            '    old "World"\n'
            '    new "世界"\n',
            encoding="utf-8",
        )

        errors = [(test_file, 1, "end of line expected")]
        fixes = _fix_errors(errors)

        assert len(fixes) >= 1
        content = test_file.read_text(encoding="utf-8")
        # The old line should have been removed
        assert '    old "Hello"' not in content
        print("[OK] test_fix_old_new_pair")


def test_fix_unknown_statement():
    """Fix unknown statement by removing the line."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        test_file = tmpdir / "script.rpy"
        test_file.write_text(
            'label start:\n    GARBAGE_STATEMENT\n    "Hello"\n',
            encoding="utf-8",
        )

        errors = [(test_file, 1, "unknown statement")]
        fixes = _fix_errors(errors)

        assert len(fixes) == 1
        content = test_file.read_text(encoding="utf-8")
        assert "GARBAGE_STATEMENT" not in content
        assert '"Hello"' in content
        print("[OK] test_fix_unknown_statement")


def test_fix_translate_block():
    """Fix error on a translate block header."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        test_file = tmpdir / "script.rpy"
        test_file.write_text(
            'translate chinese BADBLOCK:\n    "test"\n',
            encoding="utf-8",
        )

        errors = [(test_file, 0, "Could not parse string")]
        fixes = _fix_errors(errors)

        assert len(fixes) >= 1
        content = test_file.read_text(encoding="utf-8")
        assert "BADBLOCK" not in content
        print("[OK] test_fix_translate_block")


def test_fix_preserves_other_content():
    """Fixing errors preserves unrelated content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        test_file = tmpdir / "script.rpy"
        original_lines = [
            "label start:\n",
            '    "Good line 1"\n',
            "    BAD_LINE\n",
            '    "Good line 2"\n',
        ]
        test_file.write_text("".join(original_lines), encoding="utf-8")

        errors = [(test_file, 2, "unknown statement")]
        _fix_errors(errors)

        content = test_file.read_text(encoding="utf-8")
        assert '"Good line 1"' in content
        assert '"Good line 2"' in content
        assert "BAD_LINE" not in content
        print("[OK] test_fix_preserves_other_content")


# ---------------------------------------------------------------------------
# Tests: lint availability detection
# ---------------------------------------------------------------------------


def test_lint_not_available_empty_dir():
    """Lint not available for empty directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        (tmpdir / "game").mkdir()
        assert not is_lint_available(tmpdir)
    print("[OK] test_lint_not_available_empty_dir")


def test_lint_not_available_no_game_dir():
    """Lint not available when game/ doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert not is_lint_available(Path(tmpdir))
    print("[OK] test_lint_not_available_no_game_dir")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Cleanup tests
    test_remove_consecutive_empty_lines()
    test_remove_consecutive_no_change()

    # Parsing tests
    test_parse_lint_termination_error()
    test_parse_lint_end_of_line()
    test_parse_lint_empty_block()
    test_parse_lint_unknown_statement()
    test_parse_lint_duplicate_translation()
    test_parse_lint_multiple_errors()
    test_parse_lint_no_errors()

    # Fixing tests
    test_fix_old_new_pair()
    test_fix_unknown_statement()
    test_fix_translate_block()
    test_fix_preserves_other_content()

    # Availability tests
    test_lint_not_available_empty_dir()
    test_lint_not_available_no_game_dir()

    print("\n=== 全部 Lint 修复测试通过 ===")
