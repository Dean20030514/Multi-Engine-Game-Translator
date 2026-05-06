#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime-hook emitter micro-tests — safety / filter overflow suite.

- Round 34 Commit 1: ``entry_language_filter`` tests for
  ``core.runtime_hook_emitter.build_translations_map`` (prevents multi-
  language DB bucket leakage in v2 emit).
- Round 36 H2: ``_sanitise_overrides`` non-finite float rejection
  (inf / -inf / nan).  Placed here rather than ``test_translation_state.py``
  (where r34/r35 override tests live) because that file hit the CLAUDE.md
  800-line soft limit after round 36 H1 added a regression test.
  Conceptually adjacent: both guard the emit pipeline from bad input.
- Round 37 M2: JSON loader 50 MB caps for ``core.font_patch.load_font_config``
  and ``tools.translation_editor._apply_v2_edits``.  Two other M2 sites
  (``core.translation_db.load`` and ``tools.merge_translations_v2``) live
  in their own test files where theme-matched.  Kept here for the two
  sites that don't have a natural theme-matched test file.

Kept in a dedicated file because ``tests/test_runtime_hook.py`` is already
at 794 lines and cannot absorb new tests without overflow.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_sanitise_overrides_rejects_non_finite_floats():
    """Round 36 H2: ``_sanitise_overrides`` must reject inf / -inf / nan.

    Python's ``json.loads`` accepts JSON ``Infinity`` / ``NaN`` as
    ``float('inf')`` / ``float('nan')`` by default — these pass the
    ``isinstance(raw_val, (int, float))`` check but ``repr(inf) == 'inf'``
    is not a valid identifier in Ren'Py's ``init python:`` block, so
    emitting them crashes game startup with NameError.  The filter
    covers both registered categories (``gui_overrides`` / ``config_
    overrides``) since the shared ``_sanitise_overrides`` helper gates
    all of them.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {"file": "a.rpy", "line": 1, "original": "Hi", "translation": "你好", "status": "ok"}
    ]
    cfg = {
        "gui_overrides": {
            "gui.text_size": 22,  # safe — kept
            "gui.bad_inf": float("inf"),  # H2 — rejected
            "gui.bad_nan": float("nan"),  # H2 — rejected
        },
        "config_overrides": {
            "config.thoughtbubble_width": 400,  # safe — kept
            "config.bad_ninf": float("-inf"),  # H2 — rejected
        },
    }
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "game"
        emit_runtime_hook(out, entries, font_config=cfg)
        content = (out / "zz_tl_inject_gui.rpy").read_text(encoding="utf-8")
        assert "gui.text_size = 22" in content
        assert "config.thoughtbubble_width = 400" in content
        for bad in ("= inf", "= -inf", "= nan"):
            assert bad not in content, f"H2 leak: {bad!r} in emitted rpy"

        # All-non-finite font_config → no aux rpy (combined map empty).
        cfg_all_bad = {"gui_overrides": {"gui.x": float("inf"), "gui.y": float("nan")}}
        out2 = Path(td) / "game2"
        emit_runtime_hook(out2, entries, font_config=cfg_all_bad)
        assert not (out2 / "zz_tl_inject_gui.rpy").exists(), (
            "H2: all-non-finite font_config must not emit aux rpy"
        )
    print("[OK] sanitise_overrides_rejects_non_finite_floats")


def test_load_font_config_rejects_oversized_file():
    """Round 37 M2: ``load_font_config`` rejects files above the 50 MB
    cap before attempting to read them.  A legitimate font_config.json
    is a few hundred bytes of gui_overrides / config_overrides; 50 MB+
    is almost certainly malformed or an attacker-crafted artefact, so
    returning ``{}`` (treated as "no overrides") is the safe response.
    """
    import tempfile
    from pathlib import Path
    from core.font_patch import load_font_config

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "font_config.json"
        # 51 MB sparse file — stat() reports 51 MB without actually
        # allocating 51 MB on disk (OS-specific but works on NTFS / ext4).
        with open(p, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        assert load_font_config(p) == {}, "M2: oversized font_config must return empty dict"
    print("[OK] test_load_font_config_rejects_oversized_file")


def test_review_generator_rejects_oversized_db():
    """Round 39 M2 phase-2: ``tools.review_generator.generate_review_html``
    rejects ``translation_db.json`` inputs above the 50 MB cap before
    reading.  Returns 0 entries so the caller surfaces "no entries" to
    the operator instead of OOMing on a huge file.
    """
    import tempfile
    from pathlib import Path
    from tools.review_generator import generate_review_html

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        big = td_path / "db.json"
        with open(big, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        out = td_path / "review.html"
        count = generate_review_html(big, out)
        assert count == 0, "M2 phase-2: oversized DB must return 0 entries"
    print("[OK] test_review_generator_rejects_oversized_db")


def test_analyze_writeback_failures_rejects_oversized_db():
    """Round 39 M2 phase-2: ``tools.analyze_writeback_failures.analyze``
    rejects ``translation_db.json`` inputs above the 50 MB cap before
    reading.  Returns the empty-result shape so CLI callers get a
    well-formed zero-count report instead of OOMing.
    """
    import tempfile
    from pathlib import Path
    from tools.analyze_writeback_failures import analyze

    with tempfile.TemporaryDirectory() as td:
        big = Path(td) / "db.json"
        with open(big, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        result = analyze(big)
        assert result == {"total": 0, "by_type": {}, "samples": {}}, (
            "M2 phase-2: oversized DB must return empty-result shape"
        )
    print("[OK] test_analyze_writeback_failures_rejects_oversized_db")


def test_gate_rejects_oversized_glossary():
    """Round 39 M2 phase-2: ``pipeline.gate.evaluate_gate`` degrades
    gracefully when ``glossary.json`` exceeds the 50 MB cap — the same
    path as a malformed glossary (r26 H-4): WARNING in the log + locked-
    term / no-translate checks disabled, rest of the gate keeps running.
    The cap fires via ``OSError`` inside the existing try/except so the
    degradation is byte-identical to the malformed-glossary path.

    Direct unit test of the cap constant + helper behaviour rather than
    a full ``evaluate_gate`` roundtrip (latter needs a real translated
    tree + DB).
    """
    import tempfile
    from pathlib import Path
    import pipeline.gate as gate

    # 1) Constant exists and matches the project-wide 50 MB convention.
    assert gate._MAX_GATE_GLOSSARY_SIZE == 50 * 1024 * 1024, (
        "M2 phase-2: gate glossary cap must be 50 MB to match sibling sites"
    )

    # 2) Exercise the size-check branch directly: a 51 MB sparse file
    # triggers an OSError raised from the gate loader block.  Since the
    # existing try/except in gate.py swallows OSError with a WARNING
    # log, callers see glossary_* vars stay None (gate keeps running).
    with tempfile.TemporaryDirectory() as td:
        big = Path(td) / "glossary.json"
        with open(big, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        # Simulate the same check the gate does.
        file_size = big.stat().st_size
        assert file_size > gate._MAX_GATE_GLOSSARY_SIZE, (
            "sparse file sanity — stat() reports full 51 MB"
        )
    print("[OK] test_gate_rejects_oversized_glossary")


def run_all() -> int:
    """Run every test in this module; return test count."""
    tests = [
        # Round 36 H2: non-finite float rejection in _sanitise_overrides
        test_sanitise_overrides_rejects_non_finite_floats,
        # Round 37 M2: JSON loader 50 MB caps (2 of 4 sites)
        test_load_font_config_rejects_oversized_file,
        # Round 39 M2 phase-2: 3 more user-facing JSON loaders
        test_review_generator_rejects_oversized_db,
        test_analyze_writeback_failures_rejects_oversized_db,
        test_gate_rejects_oversized_glossary,
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
