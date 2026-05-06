#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round 53 W1 + W3 regression coverage for ``translators._tl_retry``.

Exercises the retry stage extracted from ``tl_mode.py`` in r53 W1 plus
the layer-6 LLM ID-space drift detection added in r53 W3:

  - ``detect_id_drift``: threshold boundaries, empty / all-missing / all-extra
  - ``_expected_id_set``: DialogueEntry vs StringEntry vs mixed lists
  - ``run_retry_stage``: end-to-end with a fake thread-safe APIClient,
    asserts ThreadPoolExecutor concurrency, per-chunk progress logging,
    adaptive chunk size (≤ 50 → 5/chunk; > 50 → 10/chunk), and that
    drift warnings fire when the LLM returns hallucinated / missing IDs.

Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from translators._tl_retry import (
    _expected_id_set,
    detect_id_drift,
    ID_DRIFT_THRESHOLD,
    run_retry_stage,
)
from translators.tl_parser import DialogueEntry, StringEntry


# ────────────────────────────────────────────────────────────────────
# detect_id_drift — threshold boundaries
# ────────────────────────────────────────────────────────────────────


def test_detect_id_drift_no_drift():
    """0% drift when expected == returned."""
    expected = {"a", "b", "c"}
    returned = {"a", "b", "c"}
    drifted, ratio, missing, extra = detect_id_drift(expected, returned)
    assert drifted is False
    assert ratio == 0.0
    assert missing == 0
    assert extra == 0
    print("[OK] detect_id_drift_no_drift")


def test_detect_id_drift_below_threshold():
    """5% drift (1 missing of 20) below 10% threshold → no warning."""
    expected = {f"id_{i}" for i in range(20)}
    returned = expected - {"id_0"}  # 1/20 missing
    drifted, ratio, missing, extra = detect_id_drift(expected, returned)
    assert drifted is False, f"5% should not exceed 10% threshold, got {ratio}"
    assert ratio == 0.05
    assert missing == 1
    assert extra == 0
    print("[OK] detect_id_drift_below_threshold")


def test_detect_id_drift_at_threshold():
    """Exactly 10% (2 missing of 20) does NOT trigger (strict >)."""
    expected = {f"id_{i}" for i in range(20)}
    returned = expected - {"id_0", "id_1"}  # 2/20 = 10%
    drifted, ratio, _, _ = detect_id_drift(expected, returned)
    assert drifted is False, f"strict > means 10% must not trigger, got {ratio}"
    assert ratio == 0.10
    print("[OK] detect_id_drift_at_threshold")


def test_detect_id_drift_above_threshold():
    """15% drift (3 missing of 20) triggers."""
    expected = {f"id_{i}" for i in range(20)}
    returned = expected - {"id_0", "id_1", "id_2"}
    drifted, ratio, missing, extra = detect_id_drift(expected, returned)
    assert drifted is True
    assert ratio == 0.15
    assert missing == 3
    assert extra == 0
    print("[OK] detect_id_drift_above_threshold")


def test_detect_id_drift_empty_expected():
    """Empty expected → no drift (avoid div-by-zero)."""
    drifted, ratio, missing, extra = detect_id_drift(set(), {"a"})
    assert drifted is False
    assert ratio == 0.0
    assert missing == 0
    assert extra == 0
    print("[OK] detect_id_drift_empty_expected")


def test_detect_id_drift_all_missing():
    """LLM returned nothing → 100% missing → drift detected."""
    expected = {"a", "b", "c"}
    drifted, ratio, missing, extra = detect_id_drift(expected, set())
    assert drifted is True
    assert ratio == 1.0
    assert missing == 3
    assert extra == 0
    print("[OK] detect_id_drift_all_missing")


def test_detect_id_drift_all_extra():
    """LLM returned hallucinated IDs that don't match expected → all-extra drift."""
    expected = {"a", "b", "c"}
    returned = {"x", "y", "z"}
    drifted, ratio, missing, extra = detect_id_drift(expected, returned)
    assert drifted is True
    # symmetric diff = 6, expected size = 3 → ratio = 2.0 > 0.10
    assert ratio == 2.0
    assert missing == 3
    assert extra == 3
    print("[OK] detect_id_drift_all_extra")


def test_detect_id_drift_custom_threshold():
    """Custom threshold parameter overrides default 10%."""
    expected = {f"id_{i}" for i in range(10)}
    returned = expected - {"id_0"}  # 10% drift
    # default threshold (0.10) does not trigger at exactly 10%
    drifted_default, _, _, _ = detect_id_drift(expected, returned)
    assert drifted_default is False
    # threshold 0.05 triggers
    drifted_strict, _, _, _ = detect_id_drift(expected, returned, threshold=0.05)
    assert drifted_strict is True
    print("[OK] detect_id_drift_custom_threshold")


# ────────────────────────────────────────────────────────────────────
# _expected_id_set
# ────────────────────────────────────────────────────────────────────


def _make_dialogue(identifier: str) -> DialogueEntry:
    return DialogueEntry(
        identifier=identifier,
        original=f"orig_{identifier}",
        translation="",
        character="",
        source_file="game/x.rpy",
        source_line=1,
        tl_file="game/tl/chinese/x.rpy",
        tl_line=2,
        block_start_line=1,
    )


def _make_string(old: str) -> StringEntry:
    return StringEntry(
        old=old,
        new="",
        source_file="game/x.rpy",
        source_line=1,
        tl_file="game/tl/chinese/x.rpy",
        tl_line=2,
        block_start_line=1,
    )


def test_expected_id_set_dialogue():
    """DialogueEntry uses identifier."""
    entries = [_make_dialogue("alpha"), _make_dialogue("beta")]
    ids = _expected_id_set(entries)
    assert ids == {"alpha", "beta"}
    print("[OK] expected_id_set_dialogue")


def test_expected_id_set_string():
    """StringEntry uses .old as ID."""
    entries = [_make_string("Hello"), _make_string("World")]
    ids = _expected_id_set(entries)
    assert ids == {"Hello", "World"}
    print("[OK] expected_id_set_string")


def test_expected_id_set_mixed():
    """Mixed DialogueEntry + StringEntry collects identifier and old together."""
    entries = [_make_dialogue("hello_001"), _make_string("Goodbye")]
    ids = _expected_id_set(entries)
    assert ids == {"hello_001", "Goodbye"}
    print("[OK] expected_id_set_mixed")


# ────────────────────────────────────────────────────────────────────
# run_retry_stage — end-to-end with fake APIClient
# ────────────────────────────────────────────────────────────────────


@dataclass
class _FakeAPIClient:
    """Thread-safe fake APIClient for retry stage tests.

    Each ``translate(system, user)`` call returns a translation list keyed
    by chunk_text token presence; tests can inspect ``calls`` post-run to
    assert per-chunk parallelism worked.
    """

    response_factory: callable
    _lock: threading.Lock = None
    calls: list = None

    def __post_init__(self):
        self._lock = threading.Lock()
        self.calls = []

    def translate(self, system_prompt: str, user_prompt: str) -> list[dict]:
        with self._lock:
            self.calls.append((system_prompt, user_prompt))
        return self.response_factory(user_prompt)


def _fake_fill_translation(_fpath: str, _matched: list) -> str:
    """Stub: pretend we wrote the file."""
    return "<filled>"


def test_run_retry_stage_empty_returns_zero():
    """Empty retry_all → (0, 0) with no API calls."""
    client = _FakeAPIClient(response_factory=lambda _u: [])
    with tempfile.TemporaryDirectory() as td:
        translated, filled = run_retry_stage(
            retry_all=[],
            client=client,
            system_prompt="sys",
            workers=1,
            game_dir=Path(td),
            fill_translation=_fake_fill_translation,
            DialogueEntry=DialogueEntry,
            modified_rpy_files=set(),
        )
    assert translated == 0
    assert filled == 0
    assert client.calls == []
    print("[OK] run_retry_stage_empty_returns_zero")


def test_run_retry_stage_basic_translates():
    """Basic case: 3 entries → 1 chunk → all translated + filled."""
    entries = [_make_dialogue(f"id_{i}") for i in range(3)]

    def _factory(user_prompt: str) -> list[dict]:
        # Return zh for all 3 IDs (must echo original to pass check_response_item)
        return [{"id": f"id_{i}", "original": f"orig_id_{i}", "zh": f"译文_{i}"} for i in range(3)]

    client = _FakeAPIClient(response_factory=_factory)
    with tempfile.TemporaryDirectory() as td:
        # Create the tl file so write_text doesn't crash
        tl_file = Path(td) / "tl_x.rpy"
        tl_file.write_text("placeholder", encoding="utf-8")
        for e in entries:
            e.tl_file = str(tl_file)

        modified: set[str] = set()
        translated, filled = run_retry_stage(
            retry_all=entries,
            client=client,
            system_prompt="sys",
            workers=1,
            game_dir=Path(td),
            fill_translation=_fake_fill_translation,
            DialogueEntry=DialogueEntry,
            modified_rpy_files=modified,
        )
    assert translated == 3, f"expected 3 translated, got {translated}"
    assert filled == 3, f"expected 3 filled, got {filled}"
    assert len(client.calls) == 1, "3 entries fit in 1 chunk (size 5)"
    print("[OK] run_retry_stage_basic_translates")


def test_run_retry_stage_adaptive_chunk_size():
    """> 50 entries triggers chunk size 10, ≤ 50 keeps 5."""
    # 51 entries in same file → adaptive triggers → ceil(51/10) = 6 chunks
    entries = [_make_dialogue(f"id_{i}") for i in range(51)]

    def _factory(_u: str) -> list[dict]:
        return []  # we only care about call count, not translations

    client = _FakeAPIClient(response_factory=_factory)
    with tempfile.TemporaryDirectory() as td:
        tl_file = Path(td) / "big.rpy"
        tl_file.write_text("x", encoding="utf-8")
        for e in entries:
            e.tl_file = str(tl_file)

        run_retry_stage(
            retry_all=entries,
            client=client,
            system_prompt="sys",
            workers=2,
            game_dir=Path(td),
            fill_translation=_fake_fill_translation,
            DialogueEntry=DialogueEntry,
            modified_rpy_files=set(),
        )
    # 51 entries / 10-per-chunk = 6 chunks (5 full + 1 partial)
    assert len(client.calls) == 6, (
        f"51 entries with adaptive chunk size 10 should produce 6 chunks, got {len(client.calls)}"
    )

    # 50 entries → keeps 5/chunk → 10 chunks
    entries_small = [_make_dialogue(f"id_{i}") for i in range(50)]
    client2 = _FakeAPIClient(response_factory=_factory)
    with tempfile.TemporaryDirectory() as td:
        tl_file = Path(td) / "small.rpy"
        tl_file.write_text("x", encoding="utf-8")
        for e in entries_small:
            e.tl_file = str(tl_file)

        run_retry_stage(
            retry_all=entries_small,
            client=client2,
            system_prompt="sys",
            workers=2,
            game_dir=Path(td),
            fill_translation=_fake_fill_translation,
            DialogueEntry=DialogueEntry,
            modified_rpy_files=set(),
        )
    assert len(client2.calls) == 10, (
        f"50 entries with chunk size 5 should produce 10 chunks, got {len(client2.calls)}"
    )
    print("[OK] run_retry_stage_adaptive_chunk_size")


def test_run_retry_stage_drift_warning_logged():
    """When LLM drops > 10% of expected IDs, drift warning is logged."""
    entries = [_make_dialogue(f"id_{i}") for i in range(20)]

    # Return only 15 of 20 IDs → 5/20 = 25% drift > 10%
    def _factory(_u: str) -> list[dict]:
        return [{"id": f"id_{i}", "original": f"orig_id_{i}", "zh": f"译_{i}"} for i in range(15)]

    client = _FakeAPIClient(response_factory=_factory)

    captured: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _CaptureHandler()
    logger = logging.getLogger("multi_engine_translator")
    prev_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        with tempfile.TemporaryDirectory() as td:
            tl_file = Path(td) / "drift.rpy"
            tl_file.write_text("x", encoding="utf-8")
            for e in entries:
                e.tl_file = str(tl_file)

            run_retry_stage(
                retry_all=entries,
                client=client,
                system_prompt="sys",
                workers=1,
                game_dir=Path(td),
                fill_translation=_fake_fill_translation,
                DialogueEntry=DialogueEntry,
                modified_rpy_files=set(),
            )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)

    # Look for W3-DRIFT marker in any captured log
    drift_messages = [r.getMessage() for r in captured if "W3-DRIFT" in r.getMessage()]
    assert len(drift_messages) > 0, "drift warning [W3-DRIFT] must appear when 25% of IDs drop"
    print("[OK] run_retry_stage_drift_warning_logged")


def test_run_retry_stage_progress_logging():
    """Per-chunk [TL-RETRY n/N] progress messages are emitted."""
    entries = [_make_dialogue(f"id_{i}") for i in range(10)]

    def _factory(_u: str) -> list[dict]:
        return []

    client = _FakeAPIClient(response_factory=_factory)
    captured: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _CaptureHandler()
    logger = logging.getLogger("multi_engine_translator")
    prev_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with tempfile.TemporaryDirectory() as td:
            tl_file = Path(td) / "prog.rpy"
            tl_file.write_text("x", encoding="utf-8")
            for e in entries:
                e.tl_file = str(tl_file)

            run_retry_stage(
                retry_all=entries,
                client=client,
                system_prompt="sys",
                workers=1,
                game_dir=Path(td),
                fill_translation=_fake_fill_translation,
                DialogueEntry=DialogueEntry,
                modified_rpy_files=set(),
            )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)

    # 10 entries / chunk size 5 → 2 chunks → expect [TL-RETRY 1/2] and [TL-RETRY 2/2]
    progress_msgs = [m for m in captured if "[TL-RETRY" in m and "/2]" in m]
    assert len(progress_msgs) >= 2, f"expected ≥2 [TL-RETRY n/2] progress lines, got: {captured}"
    print("[OK] run_retry_stage_progress_logging")


# ────────────────────────────────────────────────────────────────────
# Threshold sanity check
# ────────────────────────────────────────────────────────────────────


def test_id_drift_threshold_constant_value():
    """Module-level threshold constant is 10% (matches HANDOFF.md spec)."""
    assert ID_DRIFT_THRESHOLD == 0.10
    print("[OK] id_drift_threshold_constant_value")


# ────────────────────────────────────────────────────────────────────


def run_all() -> int:
    tests = [
        test_detect_id_drift_no_drift,
        test_detect_id_drift_below_threshold,
        test_detect_id_drift_at_threshold,
        test_detect_id_drift_above_threshold,
        test_detect_id_drift_empty_expected,
        test_detect_id_drift_all_missing,
        test_detect_id_drift_all_extra,
        test_detect_id_drift_custom_threshold,
        test_expected_id_set_dialogue,
        test_expected_id_set_string,
        test_expected_id_set_mixed,
        test_run_retry_stage_empty_returns_zero,
        test_run_retry_stage_basic_translates,
        test_run_retry_stage_adaptive_chunk_size,
        test_run_retry_stage_drift_warning_logged,
        test_run_retry_stage_progress_logging,
        test_id_drift_threshold_constant_value,
    ]
    for t in tests:
        t()
    return len(tests)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} TESTS PASSED")
    print("=" * 40)
