#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Meta-runner — discovers and runs every ``tests/test_*.py`` module.

r64 S1 fix: extended from 11-module hand-curated import list to **all**
``tests/test_*.py`` files (37 currently). Pre-commit hook now sees the
full ~498 test surface instead of just 191 (~39% gap closed).

Implementation: subprocess-run each test file. This avoids inter-file
import-order issues and matches CI behavior (CI runs each file via
``python tests/test_X.py``).

Historical context:
- r29 (113 tests, 2539-line monolith) → split into 5 focused modules
  + 49-line meta-runner (1st-gen import + call ``run_all()``)
- r33-r60 added ~6 more modules to the import list
- r64 S1 audit found 24/35 test files NOT in meta-runner — pre-commit
  hook only ran 191/485 tests (~39%); regressions in non-imported
  test files (incl. r61 T1 fix verification + r62 B1 interrupt tests
  themselves) silently passed pre-commit until CI catch.
- r64 S1 rewrite: subprocess-discover-and-run pattern. ~3.5s vs
  prior 0.68s; absolute time still well under the 5s pre-commit budget.

Each ``tests/test_*.py`` module remains independently runnable via
``python tests/test_X.py`` (entry point unchanged for IDE / CI).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TESTS_DIR.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Files that are NOT regression test modules (exclude from auto-discovery):
_NON_TEST_FILES = {
    "test_all.py",  # this meta-runner itself
    # r64 S1 audit-tail: test_single.py is a *manual integration script*
    # that prompts ``input("请输入 xAI API Key: ")`` — not a unit test;
    # belongs under ``scripts/`` but kept in tests/ for historical reasons.
    # Excluded from auto-discovery to keep meta-runner non-interactive.
    "test_single.py",
}


def _discover_test_files() -> list[Path]:
    """Return every ``tests/test_*.py`` file (sorted) excluding this runner."""
    return sorted(
        p
        for p in _TESTS_DIR.glob("test_*.py")
        if p.name not in _NON_TEST_FILES
    )


# Regex to extract "ALL N TESTS" / "ALL N FILE SAFETY TESTS" / etc. from
# each module's tail summary line. Each test module ends with a banner like:
#     ========================================
#     ALL 5 FILE SAFETY HELPER TESTS PASSED
#     ========================================
# r67 H1 fix: previous character class ``[A-Z_ ]`` rejected ``-`` and
# digits, causing ``ALL 18 BATCH-1 TESTS PASSED`` / ``ALL 8 RED-TEAM
# TESTS PASSED`` / ``ALL 14 FILE SAFETY C5 EXPANSION TESTS PASSED`` /
# etc. to silently report 0 tests across 7 modules (96 tests miscounted).
# The Chinese banner ``=== 全部 X 测试通过 ===`` (3 modules) is also
# matched via a fallback pattern.
_PASS_BANNER_RE = re.compile(
    r"ALL\s+(\d+)\s+[A-Z_\-0-9 ]*?(?:TESTS?|TEST)\s+PASSED",
    re.IGNORECASE,
)
# Fallback for Chinese banner ``=== 全部 RPA 解包测试通过 ===`` etc.
# Count is not embedded in this banner format, so callers fall back to
# parsing per-line ``[OK] test_xxx`` markers when the Chinese banner
# matches. This keeps ``returncode == 0`` as the authoritative pass
# signal while restoring accurate counts.
_PASS_BANNER_ZH_RE = re.compile(r"全部\s*[一-鿿 A-Za-z_\-0-9]*?\s*测试\s*通过")
# Per-test [OK] line counter (used when the Chinese banner matches).
_OK_LINE_RE = re.compile(r"^\s*\[OK\]\s+\w", re.MULTILINE)


def _run_one(test_file: Path) -> tuple[bool, int, str]:
    """Run a single test module via subprocess.

    Returns ``(ok, test_count, tail_output)`` where ``test_count`` is parsed
    from the module's banner (best-effort; falls back to 0 if the module
    uses a non-standard summary).
    """
    proc = subprocess.run(
        [sys.executable, str(test_file)],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
        encoding="utf-8",
        errors="replace",
    )
    ok = proc.returncode == 0
    # Parse "ALL N ... PASSED" from combined stdout/stderr tail.
    output = proc.stdout + proc.stderr
    count = _count_tests(output)
    tail = "\n".join(output.splitlines()[-15:]) if output else ""
    return ok, count, tail


def _count_tests(output: str) -> int:
    """Best-effort test count from a module's combined stdout+stderr.

    r67 H1: try English ``ALL N ... PASSED`` banner first; if absent
    (Chinese banner ``=== 全部 X 测试通过 ===`` or non-standard format),
    fall back to counting ``[OK] test_xxx`` markers. Returns 0 only when
    neither pattern produces evidence of tests (subprocess returncode is
    the authoritative pass signal — count is informational).
    """
    last_count = 0
    has_zh_banner = False
    for line in output.splitlines():
        m = _PASS_BANNER_RE.search(line)
        if m:
            last_count = int(m.group(1))
        if _PASS_BANNER_ZH_RE.search(line):
            has_zh_banner = True
    if last_count:
        return last_count
    if has_zh_banner:
        return len(_OK_LINE_RE.findall(output))
    return 0


def main() -> int:
    """Run every test file, print per-file status, return total count.

    Exits with non-zero status if any test file fails (pre-commit hook
    relies on this to block bad commits).
    """
    files = _discover_test_files()
    print(f"Meta-runner: discovered {len(files)} test files")
    print("=" * 60)

    total_tests = 0
    total_files_passed = 0
    failures: list[tuple[Path, str]] = []
    start = time.perf_counter()

    for f in files:
        ok, n, tail = _run_one(f)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {f.name:48s} ({n:3d} tests)")
        if ok:
            total_tests += n
            total_files_passed += 1
        else:
            failures.append((f, tail))

    elapsed = time.perf_counter() - start

    print("=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} test file(s):")
        for path, tail in failures:
            print(f"\n--- {path.name} tail ---")
            print(tail)
        print()
        print("=" * 60)
        print(f"META-RUNNER FAILED ({total_files_passed}/{len(files)} files OK in {elapsed:.1f}s)")
        print("=" * 60)
        return 1

    print(f"ALL {total_tests} TESTS PASSED across {total_files_passed} files in {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
