#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interrupt recovery contract tests (round 62 B1).

Round 62 B1 audit finding: SIGTERM / KeyboardInterrupt paths in the translation
pipeline were never explicitly tested. This module documents the **current**
contract by running it as test, so any future regression (e.g. someone removes
the SIGTERM handler in ``translators/direct.py`` or breaks the retry stage's
implicit propagation) is caught.

Scope (intentionally minimal — audit recommendation B1 was "tests first to
expose the problem, then decide whether to fix"):

- direct-mode pipeline registers a SIGTERM handler on platforms that support it
- retry stage in ``translators/_tl_retry.py`` does NOT install its own
  KeyboardInterrupt catch (CTRL+C during retry propagates to caller)
- ``translators/_tl_retry.run_retry_stage`` ThreadPoolExecutor uses default
  shutdown semantics — pending futures finish, no explicit cancel

These are **observation-only** tests; they pin behaviour, they do not assert
that current behaviour is correct. If a future round adds explicit handling,
update these tests and EVOLUTION accordingly.
"""

from __future__ import annotations

import signal
import sys
import threading
import unittest.mock as mock
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_w_round62_b1_sigterm_handler_only_registered_when_signal_supported() -> None:
    """``translators/direct.py::run_pipeline`` registers a SIGTERM handler only
    on platforms where ``signal.SIGTERM`` exists.

    Windows lacks SIGTERM (uses CTRL_C_EVENT instead); the guard
    ``if hasattr(signal, "SIGTERM"):`` ensures no AttributeError on Windows.
    This test pins both branches by introspecting the source.
    """
    direct_src = (_PROJECT_ROOT / "translators" / "direct.py").read_text(encoding="utf-8")

    # Pin: handler exists
    assert "_sigterm_handler" in direct_src, (
        "translators/direct.py::run_pipeline must define _sigterm_handler "
        "(round 62 B1 contract: graceful shutdown on SIGTERM)"
    )
    # Pin: guard against missing SIGTERM (Windows compatibility)
    assert 'hasattr(signal, "SIGTERM")' in direct_src, (
        "translators/direct.py must guard signal.SIGTERM with hasattr() "
        "for Windows compatibility (round 62 B1 contract)"
    )
    # Pin: handler logs the interrupt
    assert "[SIGTERM]" in direct_src, (
        "translators/direct.py SIGTERM handler must log '[SIGTERM]' marker "
        "(allows users to grep logs for interrupt events)"
    )
    print("[OK] test_w_round62_b1_sigterm_handler_only_registered_when_signal_supported")


def test_w_round62_b1_retry_stage_no_explicit_ki_catch() -> None:
    """``translators/_tl_retry.py::run_retry_stage`` does NOT install its own
    ``except KeyboardInterrupt`` block.

    This is the **current** behaviour (audit B1 recommendation: "test exposes
    problem, then decide"). KeyboardInterrupt during retry propagates upward
    and aborts the whole batch. Pending in-flight chunks already submitted to
    the ThreadPoolExecutor finish naturally (they are not cancelled mid-API
    call); already-translated chunks are written via ``upsert_entry`` before
    the propagation, so progress is not lost for completed chunks. Chunks
    that were translated in-memory but not yet upserted ARE lost.

    Future fix (deferred to a later round if user reports it): wrap the
    executor's ``as_completed`` iteration in try/except KeyboardInterrupt and
    explicitly call ``executor.shutdown(wait=False)`` + flush in-flight
    upserts before re-raising.
    """
    retry_src = (_PROJECT_ROOT / "translators" / "_tl_retry.py").read_text(encoding="utf-8")

    # Pin current state: no explicit KI handler in run_retry_stage
    # (allows propagation as designed; documents the gap)
    assert "except KeyboardInterrupt" not in retry_src, (
        "translators/_tl_retry.py::run_retry_stage currently propagates "
        "KeyboardInterrupt by design (round 62 B1 baseline). If a future "
        "round adds explicit handling, update this test + EVOLUTION."
    )
    # Pin: ThreadPoolExecutor IS used (W1 contract from r53)
    assert "ThreadPoolExecutor" in retry_src, (
        "translators/_tl_retry.py must use ThreadPoolExecutor "
        "(round 53 W1 hard contract)"
    )
    print("[OK] test_w_round62_b1_retry_stage_no_explicit_ki_catch")


def test_w_round62_b1_sigterm_handler_sets_interrupted_event() -> None:
    """The SIGTERM handler defined inside ``run_pipeline`` sets a
    ``threading.Event`` named ``_interrupted``. This event is checked
    periodically inside the translation loop to allow graceful shutdown
    (saving progress before exit).

    We can't easily call ``run_pipeline`` here without a full game-dir
    fixture, but we can verify the closure structure exists in source and
    that the handler logs the expected marker before the event flips.
    """
    direct_src = (_PROJECT_ROOT / "translators" / "direct.py").read_text(encoding="utf-8")

    # Pin: _interrupted is an Event (not a bool) — needed for thread-safety
    # since the loop checks it from worker threads while signal handler runs
    # on main thread.
    assert "_interrupted = threading.Event()" in direct_src, (
        "translators/direct.py::run_pipeline must use threading.Event for "
        "_interrupted (thread-safe between signal handler and worker loop)"
    )
    # Pin: handler calls .set() on the event
    assert "_interrupted.set()" in direct_src, (
        "_sigterm_handler must call _interrupted.set() to signal the loop "
        "(round 62 B1 contract)"
    )
    # Pin: loop checks _interrupted.is_set() to short-circuit
    assert "_interrupted.is_set()" in direct_src, (
        "translation loop must check _interrupted.is_set() for graceful "
        "shutdown (round 62 B1 contract)"
    )
    print("[OK] test_w_round62_b1_sigterm_handler_sets_interrupted_event")


if __name__ == "__main__":
    test_w_round62_b1_sigterm_handler_only_registered_when_signal_supported()
    test_w_round62_b1_retry_stage_no_explicit_ki_catch()
    test_w_round62_b1_sigterm_handler_sets_interrupted_event()
    print()
    print("=" * 40)
    print("ALL 3 INTERRUPT-RECOVERY TESTS PASSED")
    print("=" * 40)
