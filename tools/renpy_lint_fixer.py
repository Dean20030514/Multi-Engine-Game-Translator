#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ren'Py Lint Integration + Auto-Fixer
=====================================
Calls the Ren'Py engine's built-in ``lint`` command to detect translation
errors that static validation cannot catch, then auto-fixes common issues.

This is a **supplementary** tool — it complements (not replaces) the 55+
static validation rules in ``file_processor/validator.py``.

Graceful degradation
--------------------
Lint requires a complete Ren'Py runtime:

    - ``game/`` directory exists
    - A Python interpreter is available under ``lib/``

When these conditions are not met (e.g. user only copied .rpy files), the
tool returns ``LintResult(available=False)`` and the caller silently falls
back to static validation.  No errors, no warnings, no blocking.

Error patterns handled
----------------------
Fixable syntax errors (substring match):
1. ``is not terminated with a newline``
2. ``end of line expected``
3. ``expects a non-empty block``
4. ``unknown statement``
5. ``expected statement``
6. ``Could not parse string``

Duplicate translation (dedicated regex):
7. ``A translation for ... already exists at``

Usage:
    python -m tools.renpy_lint_fixer <game_dir> [--max-passes 8]

Can also be imported::

    from tools.renpy_lint_fixer import run_lint, is_lint_available
    if is_lint_available(game_dir):
        result = run_lint(game_dir)

Pure standard library — no external dependencies.

Inspired by renpy-translator (MIT, anonymousException 2024).
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Reuse platform detection from rpyc_decompiler
from tools.rpyc_decompiler import _find_renpy_python

logger = logging.getLogger(__name__)

# Default subprocess timeout for lint (seconds).
# Large games may take several minutes.
DEFAULT_LINT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LintFix:
    """Record of a single fix applied."""

    file: str
    line: int
    description: str


@dataclass
class LintResult:
    """Result of a lint + fix pass."""

    available: bool = True
    passes: int = 0
    total_fixes: int = 0
    fixes: List[LintFix] = field(default_factory=list)
    errors_remaining: int = 0
    lint_output: str = ""


# ---------------------------------------------------------------------------
# Detection: is lint available?
# ---------------------------------------------------------------------------


def _find_game_executable(game_dir: Path) -> Optional[Path]:
    """Find a Ren'Py game executable (.exe on Windows, .sh on Linux, .app on macOS).

    The executable's directory should contain both the executable and a
    corresponding .py file (e.g. Game.exe + Game.py).
    """
    # Check game_dir itself
    search = game_dir
    if game_dir.name == "game":
        search = game_dir.parent

    # Look for .py files that indicate a Ren'Py launcher
    for py_file in search.glob("*.py"):
        # Common Ren'Py launcher names
        stem = py_file.stem
        # On Windows, check for .exe; on others, the .py IS the launcher
        exe = py_file.with_suffix(".exe")
        if exe.is_file():
            return exe
        # On Linux/macOS, the .sh or the file itself might be executable
        sh = py_file.with_suffix(".sh")
        if sh.is_file():
            return sh
        # The .py file itself can be used with the bundled python
        if py_file.is_file():
            return py_file

    return None


def _find_renpy_py(game_dir: Path) -> Optional[Path]:
    """Find the .py launcher script for Ren'Py (e.g. Game.py).

    This is the script passed to the bundled Python to run lint.
    """
    search = game_dir
    if game_dir.name == "game":
        search = game_dir.parent

    for py_file in search.glob("*.py"):
        # Skip obvious non-launcher files
        if py_file.name.startswith(("_", ".")):
            continue
        # A launcher .py typically has a matching executable or is in the project root
        if py_file.parent == search:
            return py_file

    return None


def is_lint_available(game_dir: Path) -> bool:
    """Check if Ren'Py lint can be executed for this game directory.

    Conditions:
        1. ``game/`` directory exists
        2. A Python interpreter found under ``lib/`` (via rpyc_decompiler)
    """
    # Resolve game directory
    if game_dir.name == "game":
        project_dir = game_dir.parent
    else:
        project_dir = game_dir
        game_sub = project_dir / "game"
        if not game_sub.is_dir():
            return False

    python_path = _find_renpy_python(project_dir)
    return python_path is not None


# ---------------------------------------------------------------------------
# Execute lint
# ---------------------------------------------------------------------------


def _exec_lint(
    game_dir: Path,
    timeout: int = DEFAULT_LINT_TIMEOUT,
) -> Optional[str]:
    """Execute Ren'Py lint and return the error output.

    Returns None if lint cannot be executed (graceful degradation).
    Returns the lint output string on success (may be empty = no errors).
    """
    if game_dir.name == "game":
        project_dir = game_dir.parent
    else:
        project_dir = game_dir

    python_path = _find_renpy_python(project_dir)
    if python_path is None:
        logger.debug("[LINT] Python 解释器不可用，跳过 lint")
        return None

    # Find the .py launcher
    renpy_py = _find_renpy_py(project_dir)
    if renpy_py is None:
        logger.debug("[LINT] 未找到 Ren'Py 启动脚本 (.py)，跳过 lint")
        return None

    # Build command: python -O game.py <game_dir> lint
    cmd = [
        str(python_path),
        "-O",
        str(renpy_py),
        str(project_dir),
        "lint",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(project_dir),
        )
    except subprocess.TimeoutExpired:
        logger.warning("[LINT] lint 超时（%d秒），跳过", timeout)
        return None
    except FileNotFoundError:
        logger.debug("[LINT] 无法执行: %s", python_path)
        return None
    except Exception as exc:
        logger.warning("[LINT] lint 执行异常: %s", exc)
        return None

    # Combine stdout and stderr
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return output


# ---------------------------------------------------------------------------
# Parse lint errors
# ---------------------------------------------------------------------------

# Patterns for fixable errors
_FIXABLE_PATTERNS = [
    "is not terminated with a newline",
    "end of line expected",
    "expects a non-empty block",
    "unknown statement",
    "expected statement",
    "Could not parse string",
]

_DUPLICATE_PATTERN = re.compile(r"Exception: A translation for (.+?) already exists at (.+)")

_ERROR_LOCATION = re.compile(r"(?:At\s+)?(.+?), line (\d+)")


def _parse_lint_errors(
    output: str,
    project_dir: Path,
) -> List[Tuple[Path, int, str]]:
    """Parse lint output into (file, line_number, error_type) tuples."""
    errors: List[Tuple[Path, int, str]] = []

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # Check for fixable patterns (use 'in' since lint output may have
        # trailing context like "(Check strings and parenthesis.)")
        for pattern in _FIXABLE_PATTERNS:
            if pattern in line:
                match = _ERROR_LOCATION.search(line)
                if match:
                    err_file = match.group(1).strip().strip('"')
                    err_line = int(match.group(2)) - 1  # 0-indexed
                    full_path = project_dir / err_file
                    if not full_path.is_file():
                        full_path = Path(err_file)
                    errors.append((full_path, err_line, pattern))
                break

        # Check for duplicate translation
        dup_match = _DUPLICATE_PATTERN.search(line)
        if dup_match:
            err_info = dup_match.group(2).strip().rstrip(".")
            if ":" in err_info:
                err_file, err_line_str = err_info.rsplit(":", 1)
                err_file = err_file.strip()
                try:
                    err_line = int(err_line_str.strip())
                    full_path = project_dir / err_file
                    errors.append((full_path, err_line, "duplicate translation"))
                except ValueError:
                    pass

    return errors


# ---------------------------------------------------------------------------
# Fix errors
# ---------------------------------------------------------------------------


def _remove_consecutive_empty_lines(lines: list[str]) -> list[str]:
    """Collapse consecutive empty lines into a single empty line."""
    result: list[str] = []
    prev_empty = False
    for line in lines:
        is_empty = line.strip() == ""
        if is_empty and prev_empty:
            continue
        result.append(line)
        prev_empty = is_empty
    return result


def _fix_errors(
    errors: List[Tuple[Path, int, str]],
) -> List[LintFix]:
    """Apply fixes for parsed lint errors.

    Returns list of fixes applied.
    """
    fixes: List[LintFix] = []
    # Group by file
    by_file: dict[Path, list[Tuple[int, str]]] = {}
    for file_path, line_num, err_type in errors:
        by_file.setdefault(file_path, []).append((line_num, err_type))

    for file_path, file_errors in by_file.items():
        if not file_path.is_file():
            logger.warning("[LINT] 文件不存在，跳过: %s", file_path)
            continue

        try:
            lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except Exception as exc:
            logger.warning("[LINT] 无法读取 %s: %s", file_path, exc)
            continue

        modified = False
        # Sort by line number descending to avoid index shift
        for line_num, err_type in sorted(file_errors, key=lambda x: -x[0]):
            if line_num < 0 or line_num >= len(lines):
                continue

            current_line = lines[line_num]

            if err_type == "duplicate translation":
                # Remove the translate block entry (old + new pair)
                # The error line points to the 'translate' or 'old' line
                line_num_adj = line_num + 1  # error reports translate line, fix new line
                if line_num_adj < len(lines):
                    lines[line_num_adj] = "\n"
                lines[line_num] = "\n"
                if line_num > 0 and lines[line_num - 1].strip().startswith("#"):
                    lines[line_num - 1] = "\n"
                fixes.append(LintFix(str(file_path), line_num, "删除重复翻译条目"))
                modified = True

            elif err_type in ("unknown statement", "expected statement"):
                lines[line_num] = "\n"
                fixes.append(LintFix(str(file_path), line_num, "删除无效语句"))
                modified = True

            elif current_line.strip().startswith("old ") and line_num + 1 < len(lines):
                # Error on old/new pair — remove both
                lines[line_num] = "\n"
                if lines[line_num + 1].strip().startswith("new "):
                    lines[line_num + 1] = "\n"
                if line_num > 0 and lines[line_num - 1].strip().startswith("#"):
                    lines[line_num - 1] = "\n"
                fixes.append(LintFix(str(file_path), line_num, "删除错误的翻译对"))
                modified = True

            elif current_line.strip().startswith("new ") and line_num > 0:
                # Error on new line — remove old+new pair
                lines[line_num] = "\n"
                if lines[line_num - 1].strip().startswith("old "):
                    lines[line_num - 1] = "\n"
                if line_num > 1 and lines[line_num - 2].strip().startswith("#"):
                    lines[line_num - 2] = "\n"
                fixes.append(LintFix(str(file_path), line_num, "删除错误的翻译对"))
                modified = True

            elif current_line.strip().startswith("translate"):
                lines[line_num] = "\n"
                fixes.append(LintFix(str(file_path), line_num, "删除错误的 translate 块头"))
                modified = True

            else:
                # Generic fix: replace with empty string
                lines[line_num] = '    ""\n'
                fixes.append(LintFix(str(file_path), line_num, "替换为空字符串"))
                modified = True

        if modified:
            cleaned = _remove_consecutive_empty_lines(lines)
            file_path.write_text("".join(cleaned), encoding="utf-8")

    return fixes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_lint(
    game_dir: Path,
    *,
    max_passes: int = 8,
    timeout: int = DEFAULT_LINT_TIMEOUT,
) -> LintResult:
    """Run Ren'Py lint and auto-fix translation errors.

    Iterates up to ``max_passes`` times:  run lint → parse errors → fix →
    repeat until no errors remain or max passes reached.

    Args:
        game_dir: Game directory path.
        max_passes: Maximum lint→fix iterations.
        timeout: Per-lint-pass timeout in seconds.

    Returns:
        LintResult with details.  If ``available`` is False, lint could not
        run and the caller should silently fall back to static validation.
    """
    if not is_lint_available(game_dir):
        return LintResult(available=False)

    if game_dir.name == "game":
        project_dir = game_dir.parent
    else:
        project_dir = game_dir

    result = LintResult(available=True)

    for pass_num in range(1, max_passes + 1):
        logger.info("[LINT] 第 %d/%d 轮 lint...", pass_num, max_passes)

        output = _exec_lint(game_dir, timeout=timeout)
        if output is None:
            result.available = False
            return result

        result.lint_output = output
        errors = _parse_lint_errors(output, project_dir)

        if not errors:
            logger.info("[LINT] 无错误，lint 通过！")
            result.passes = pass_num
            return result

        logger.info("[LINT] 发现 %d 个错误，尝试修复...", len(errors))
        fixes = _fix_errors(errors)
        result.fixes.extend(fixes)
        result.total_fixes += len(fixes)
        result.passes = pass_num

        if not fixes:
            # Found errors but couldn't fix any — stop to prevent infinite loop
            result.errors_remaining = len(errors)
            logger.warning("[LINT] 发现 %d 个错误但无法自动修复", len(errors))
            return result

    # Ran out of passes
    output = _exec_lint(game_dir, timeout=timeout)
    if output:
        remaining = _parse_lint_errors(output, project_dir)
        result.errors_remaining = len(remaining)

    logger.info(
        "[LINT] 完成 %d 轮，共修复 %d 处，剩余 %d 个错误",
        result.passes,
        result.total_fixes,
        result.errors_remaining,
    )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="renpy_lint_fixer",
        description="运行 Ren'Py lint 并自动修复翻译错误",
    )
    parser.add_argument("game_dir", help="游戏目录路径")
    parser.add_argument("--max-passes", type=int, default=8, help="最大 lint 迭代次数（默认: 8）")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_LINT_TIMEOUT,
        help=f"每轮 lint 超时秒数（默认: {DEFAULT_LINT_TIMEOUT}）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    game_dir = Path(args.game_dir)
    if not game_dir.is_dir():
        logger.error("目录不存在: %s", game_dir)
        return 1

    if not is_lint_available(game_dir):
        print("Lint 不可用: 未检测到完整的 Ren'Py 运行时环境。")
        print("请确认游戏目录包含 lib/ 和 renpy/ 目录。")
        print("将回退到静态验证。")
        return 0

    result = run_lint(game_dir, max_passes=args.max_passes, timeout=args.timeout)

    if not result.available:
        print("Lint 不可用，已跳过。")
        return 0

    print("\nLint 完成:")
    print(f"  轮次: {result.passes}")
    print(f"  总修复: {result.total_fixes}")
    print(f"  剩余错误: {result.errors_remaining}")

    if result.fixes:
        print("\n修复详情:")
        for fix in result.fixes[:50]:
            print(f"  {fix.file}:{fix.line} — {fix.description}")
        if len(result.fixes) > 50:
            print(f"  ... 及其他 {len(result.fixes) - 50} 处修复")

    return 0 if result.errors_remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
