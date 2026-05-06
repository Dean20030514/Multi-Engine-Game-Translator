#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round 52 C1: unit tests for HANDOFF push-status drift check.

Catches the r51 trap where HANDOFF.md L29 declared "本地 main 含 r51 5
commits, 待用户手动 push origin" but the user had already pushed — the
prose went stale because no automation re-derived the unpushed-commit
count.  Same drift class as the r45-r48 cycle that motivated the rest
of ``verify_docs_claims.py``, but on push state instead of test/file/CI
counts.

Split out from ``test_verify_docs_claims.py`` (798 lines, near the
800-line cap) per the project's preventive-split convention (see r48
audit-tail in ``_archive/CHANGELOG_RECENT_r51.md``)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# parse_handoff_pending_push
# ---------------------------------------------------------------------------


def test_parse_handoff_pending_push_extracts_count_from_typical_phrasing():
    """The canonical r51 phrase produces an int claim."""
    from scripts.verify_docs_claims import parse_handoff_pending_push

    text = (
        "## 同步状态\n"
        "- 本地 `main` 含 r51 5 commits，**待用户手动 push** origin"
        "（按 NEVER push 规则；origin/main 当前是 r50 末 `943f749`）\n"
    )
    assert parse_handoff_pending_push(text) == 5
    print("[OK] parse_handoff_pending_push_extracts_count_from_typical_phrasing")


def test_parse_handoff_pending_push_returns_none_when_already_pushed():
    """The post-push synced phrase contains no 待...push pair → None."""
    from scripts.verify_docs_claims import parse_handoff_pending_push

    text = (
        "- r51 共 **7 commits**（5 主线 A1-A6 + C2 Coverage findings + "
        "docs sync + audit-tail）已全部 push 至 origin/main\n"
        "- 当前 `origin/main` = `4d10779`\n"
    )
    assert parse_handoff_pending_push(text) is None
    print("[OK] parse_handoff_pending_push_returns_none_when_already_pushed")


def test_parse_handoff_pending_push_returns_none_when_no_commits_phrase():
    """Random HANDOFF prose without a commits/待/push triad → None."""
    from scripts.verify_docs_claims import parse_handoff_pending_push

    text = "## 状态一句话\n纯 Python 零依赖多引擎游戏汉化工具。\n"
    assert parse_handoff_pending_push(text) is None
    print("[OK] parse_handoff_pending_push_returns_none_when_no_commits_phrase")


# ---------------------------------------------------------------------------
# check_handoff_push_status (mocks count_unpushed_commits to avoid
# depending on the real git state of the repo running the test)
# ---------------------------------------------------------------------------


def test_check_handoff_push_status_fails_when_stale_after_push():
    """HANDOFF claims pending commits, git says zero unpushed → drift issue."""
    from scripts.verify_docs_claims import check_handoff_push_status

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        h = td / "HANDOFF.md"
        h.write_text(
            "## 同步状态\n- 本地 main 含 r99 5 commits，**待用户手动 push** origin\n",
            encoding="utf-8",
        )
        with patch(
            "scripts.verify_docs_claims.count_unpushed_commits",
            return_value=0,
        ):
            issue = check_handoff_push_status(h, td)
    assert issue is not None, "expected drift issue, got None"
    assert "5 commits pending push" in issue, f"issue should name claim count: {issue!r}"
    assert "stale" in issue, f"issue should call out staleness: {issue!r}"
    print("[OK] check_handoff_push_status_fails_when_stale_after_push")


def test_check_handoff_push_status_passes_when_handoff_has_no_claim():
    """No pending-push prose in HANDOFF → no drift issue regardless of git."""
    from scripts.verify_docs_claims import check_handoff_push_status

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        h = td / "HANDOFF.md"
        h.write_text(
            "## 同步状态\n- r51 7 commits 已全部 push 至 origin/main\n",
            encoding="utf-8",
        )
        # Even with mocked git showing 0 unpushed, no claim → no issue.
        with patch(
            "scripts.verify_docs_claims.count_unpushed_commits",
            return_value=0,
        ):
            issue = check_handoff_push_status(h, td)
    assert issue is None, f"expected None when HANDOFF has no claim, got {issue!r}"
    print("[OK] check_handoff_push_status_passes_when_handoff_has_no_claim")


def test_check_handoff_push_status_passes_when_real_matches_claim():
    """HANDOFF claims pending AND git agrees pending → no drift."""
    from scripts.verify_docs_claims import check_handoff_push_status

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        h = td / "HANDOFF.md"
        h.write_text(
            "## 同步状态\n- 本地 main 含 r99 3 commits，**待用户手动 push** origin\n",
            encoding="utf-8",
        )
        # Real unpushed count > 0 — claim and reality both say "pending".
        with patch(
            "scripts.verify_docs_claims.count_unpushed_commits",
            return_value=3,
        ):
            issue = check_handoff_push_status(h, td)
    assert issue is None, f"expected None when claim and reality agree, got {issue!r}"
    print("[OK] check_handoff_push_status_passes_when_real_matches_claim")


def test_check_handoff_push_status_fails_open_when_git_unavailable():
    """git unavailable (returns None) → no drift issue (CI fail-open)."""
    from scripts.verify_docs_claims import check_handoff_push_status

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        h = td / "HANDOFF.md"
        h.write_text(
            "## 同步状态\n- 本地 main 含 5 commits，**待用户手动 push** origin\n",
            encoding="utf-8",
        )
        with patch(
            "scripts.verify_docs_claims.count_unpushed_commits",
            return_value=None,
        ):
            issue = check_handoff_push_status(h, td)
    assert issue is None, f"expected None when git unavailable (fail-open), got {issue!r}"
    print("[OK] check_handoff_push_status_fails_open_when_git_unavailable")


# ---------------------------------------------------------------------------
# Test registry + entry point
# ---------------------------------------------------------------------------


TESTS = [
    test_parse_handoff_pending_push_extracts_count_from_typical_phrasing,
    test_parse_handoff_pending_push_returns_none_when_already_pushed,
    test_parse_handoff_pending_push_returns_none_when_no_commits_phrase,
    test_check_handoff_push_status_fails_when_stale_after_push,
    test_check_handoff_push_status_passes_when_handoff_has_no_claim,
    test_check_handoff_push_status_passes_when_real_matches_claim,
    test_check_handoff_push_status_fails_open_when_git_unavailable,
]


def run_all() -> int:
    for t in TESTS:
        t()
    return len(TESTS)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} VERIFY DOCS CLAIMS PUSH-STATUS TESTS PASSED")
    print("=" * 40)
