#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py CLI helpers — symlink defense (r53 monitor #4) + path-traversal
sanitization (r57 S2).

Round 58 P1 / 800-line cap split: these tests were originally in
``tests/test_translators.py`` but ruff format bulk-formatting (r58) pushed
that file past 800 lines, triggering the pre-commit cap. The 6 main-CLI
tests were a natural unit to extract into their own module since they all
exercise ``main._maybe_warn_on_symlink`` / ``main._sanitize_user_path`` —
neither of which actually lives under ``translators/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_w_monitor4_symlink_warning_when_unflagged():
    """Round 53 monitor #4: ``_maybe_warn_on_symlink`` emits warning when
    --game-dir is a symlink and --allow-symlink is not set."""
    import argparse as _ap
    import logging
    from unittest import mock as _mock
    from main import _maybe_warn_on_symlink

    args = _ap.Namespace(
        game_dir="/fake/game",
        config="",
        allow_symlink=False,
    )
    captured: list[str] = []

    class _Cap(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Cap()
    logger = logging.getLogger("multi_engine_translator")
    logger.addHandler(handler)
    prev = logger.level
    logger.setLevel(logging.WARNING)
    try:
        with _mock.patch("main.Path") as MockPath:
            mock_path_instance = _mock.MagicMock()
            mock_path_instance.is_symlink.return_value = True
            mock_path_instance.resolve.return_value = "/real/target"
            MockPath.return_value = mock_path_instance
            _maybe_warn_on_symlink(args)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)

    drift = [m for m in captured if "monitor #4" in m or "symlink" in m]
    assert drift, f"expected symlink warning, got logs: {captured}"
    print("[OK] w_monitor4_symlink_warning_when_unflagged")


def test_w_monitor4_allow_symlink_suppresses_warning():
    """``--allow-symlink`` suppresses the warning (legitimate NAS / mount path)."""
    import argparse as _ap
    import logging
    from unittest import mock as _mock
    from main import _maybe_warn_on_symlink

    args = _ap.Namespace(
        game_dir="/fake/game",
        config="",
        allow_symlink=True,
    )
    captured: list[str] = []

    class _Cap(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Cap()
    logger = logging.getLogger("multi_engine_translator")
    logger.addHandler(handler)
    prev = logger.level
    logger.setLevel(logging.WARNING)
    try:
        with _mock.patch("main.Path") as MockPath:
            mock_path_instance = _mock.MagicMock()
            mock_path_instance.is_symlink.return_value = True
            MockPath.return_value = mock_path_instance
            _maybe_warn_on_symlink(args)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)

    drift = [m for m in captured if "monitor #4" in m or "symlink" in m]
    assert not drift, f"--allow-symlink should suppress warnings, got: {captured}"
    print("[OK] w_monitor4_allow_symlink_suppresses_warning")


def test_w_monitor4_no_warning_for_regular_path():
    """No warning when path is not a symlink (the common case)."""
    import argparse as _ap
    import logging
    from unittest import mock as _mock
    from main import _maybe_warn_on_symlink

    args = _ap.Namespace(
        game_dir="/regular/path",
        config="",
        allow_symlink=False,
    )
    captured: list[str] = []

    class _Cap(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Cap()
    logger = logging.getLogger("multi_engine_translator")
    logger.addHandler(handler)
    prev = logger.level
    logger.setLevel(logging.WARNING)
    try:
        with _mock.patch("main.Path") as MockPath:
            mock_path_instance = _mock.MagicMock()
            mock_path_instance.is_symlink.return_value = False
            MockPath.return_value = mock_path_instance
            _maybe_warn_on_symlink(args)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)

    drift = [m for m in captured if "monitor #4" in m or "symlink" in m]
    assert not drift, f"regular path must not warn, got: {captured}"
    print("[OK] w_monitor4_no_warning_for_regular_path")


def test_w_round57_s2_rejects_forbidden_resolved_path():
    """Round 57 S2: resolved path inside forbidden prefix is rejected.

    Mocks Path.resolve() so the test is platform-agnostic. The real
    cross-platform behaviour: on Linux ``/etc/passwd`` resolves to
    itself and triggers; on Windows ``/etc/passwd`` resolves to
    ``C:/etc/passwd`` (drive-letter prepended) which is NOT in the
    forbidden list, so we need to mock to test the matching logic
    rather than rely on raw input form.
    """
    from unittest import mock as _mock
    from pathlib import Path as _Path
    from main import _sanitize_user_path

    fake_resolved = _Path("/etc/passwd")
    with _mock.patch("main.Path") as MockPath:
        instance = _mock.MagicMock()
        instance.expanduser.return_value.resolve.return_value = fake_resolved
        MockPath.return_value = instance
        try:
            _sanitize_user_path("anything", "--game-dir")
        except SystemExit as e:
            assert e.code == 1, f"expected exit(1), got {e.code}"
            print("[OK] w_round57_s2_rejects_forbidden_resolved_path")
            return
    raise AssertionError("forbidden resolved path was NOT blocked")


def test_w_round57_s2_rejects_windows_system32():
    """Round 57 S2: Windows-form forbidden prefix rejection."""
    from unittest import mock as _mock
    from pathlib import PureWindowsPath
    from main import _sanitize_user_path

    fake_resolved = PureWindowsPath("C:\\Windows\\System32\\config\\SAM")
    with _mock.patch("main.Path") as MockPath:
        instance = _mock.MagicMock()
        instance.expanduser.return_value.resolve.return_value = fake_resolved
        MockPath.return_value = instance
        try:
            _sanitize_user_path("anything", "--config")
        except SystemExit:
            print("[OK] w_round57_s2_rejects_windows_system32")
            return
    raise AssertionError("Windows System32 path was NOT blocked")


def test_w_round57_s2_allows_legitimate_user_path():
    """Round 57 S2: legitimate user paths pass through unmolested."""
    import tempfile
    from pathlib import Path
    from main import _sanitize_user_path

    with tempfile.TemporaryDirectory() as td:
        # tempfile.TemporaryDirectory sits under /tmp on Linux or %TEMP%
        # on Windows — neither is in _FORBIDDEN_PATH_PREFIXES.
        result = _sanitize_user_path(td, "--game-dir")
        assert isinstance(result, Path)
        assert result.exists()
    print("[OK] w_round57_s2_allows_legitimate_user_path")


def run_all() -> int:
    tests = [
        test_w_monitor4_symlink_warning_when_unflagged,
        test_w_monitor4_allow_symlink_suppresses_warning,
        test_w_monitor4_no_warning_for_regular_path,
        test_w_round57_s2_rejects_forbidden_resolved_path,
        test_w_round57_s2_rejects_windows_system32,
        test_w_round57_s2_allows_legitimate_user_path,
    ]
    for t in tests:
        t()
    return len(tests)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} MAIN CLI TESTS PASSED")
    print("=" * 40)
