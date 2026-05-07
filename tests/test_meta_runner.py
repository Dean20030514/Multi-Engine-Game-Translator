#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the meta-runner banner parser.

r67 H1 fix verification: the previous regex ``[A-Z_ ]*?`` rejected
hyphens and digits, causing 7 English banners (BATCH-1, RED-TEAM,
DIRECT-PIPELINE, INTERRUPT-RECOVERY, TL-PIPELINE, FILE SAFETY C5,
PUSH-STATUS) plus 3 Chinese banners (=== 全部 X 测试通过 ===) to
silently miscount as 0 tests across 10 modules / 96 tests.

These tests pin the fixed parser against every currently observed
banner format in the repo. New banner formats that don't match either
the English or Chinese pattern should still pass via subprocess
returncode (authoritative), but counts will be 0 — add a fallback
pattern here when that happens.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_all import _count_tests  # noqa: E402


def test_count_classic_banner() -> None:
    out = "...\n========================================\nALL 5 FILE SAFETY HELPER TESTS PASSED\n========================================\n"
    assert _count_tests(out) == 5


def test_count_banner_with_hyphen() -> None:
    out = "ALL 18 BATCH-1 TESTS PASSED\n"
    assert _count_tests(out) == 18


def test_count_banner_with_digit_in_name() -> None:
    out = "ALL 14 FILE SAFETY C5 EXPANSION TESTS PASSED\n"
    assert _count_tests(out) == 14


def test_count_red_team_banner() -> None:
    out = "ALL 8 RED-TEAM TESTS PASSED\n"
    assert _count_tests(out) == 8


def test_count_push_status_banner() -> None:
    out = "ALL 7 VERIFY DOCS CLAIMS PUSH-STATUS TESTS PASSED\n"
    assert _count_tests(out) == 7


def test_count_zh_banner_falls_back_to_ok_lines() -> None:
    out = (
        "[OK] test_one\n"
        "[OK] test_two\n"
        "[OK] test_three\n"
        "\n"
        "=== 全部 RPA 解包测试通过 ===\n"
    )
    assert _count_tests(out) == 3


def test_count_zh_banner_lint_format() -> None:
    out = (
        "[OK] test_a\n"
        "[OK] test_b\n"
        "=== 全部 Lint 修复测试通过 ===\n"
    )
    assert _count_tests(out) == 2


def test_count_no_banner_returns_zero() -> None:
    # No banner of either form -> 0 (subprocess returncode is authoritative).
    out = "some random output without any banner\n"
    assert _count_tests(out) == 0


def test_count_takes_last_banner_when_multiple() -> None:
    # If a module prints multiple banners (rare but possible in nested
    # subprocess output), the LAST count wins.
    out = "ALL 3 EARLY TESTS PASSED\nALL 10 FINAL TESTS PASSED\n"
    assert _count_tests(out) == 10


def test_count_case_insensitive() -> None:
    out = "all 4 tests passed\n"
    assert _count_tests(out) == 4


def main() -> int:
    tests = [
        test_count_classic_banner,
        test_count_banner_with_hyphen,
        test_count_banner_with_digit_in_name,
        test_count_red_team_banner,
        test_count_push_status_banner,
        test_count_zh_banner_falls_back_to_ok_lines,
        test_count_zh_banner_lint_format,
        test_count_no_banner_returns_zero,
        test_count_takes_last_banner_when_multiple,
        test_count_case_insensitive,
    ]
    for t in tests:
        t()
        print(f"[OK] {t.__name__}")
    print()
    print("=" * 40)
    print(f"ALL {len(tests)} META-RUNNER PARSER TESTS PASSED")
    print("=" * 40)
    return 0


if __name__ == "__main__":
    sys.exit(main())
