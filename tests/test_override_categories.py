#!/usr/bin/env python3
"""Tests for core.runtime_hook_emitter — ``_OVERRIDE_CATEGORIES`` dispatch
table, per-category regex whitelists, and per-category value-type policies
(round 34-38).

Split from ``tests/test_translation_state.py`` in round 39 because that
file crossed the CLAUDE.md 800-line soft limit (850 lines) after round 38
C3 added the ``test_gui_overrides_still_rejects_bool`` regression guard.
The override-category surface is a self-contained slice around the
``_OVERRIDE_CATEGORIES`` + ``_OVERRIDE_ALLOW_BOOL`` maps and the shared
``_sanitise_overrides`` sanitiser; moving the 4 related tests byte-
identical leaves the parent file at ~700 lines (well under the cap).

Coverage (byte-identical copies of the r34-r38 tests):
  * Round 34 C4 / Round 35 C4: dispatch-table extensibility guards
    (``test_override_categories_table_is_extensible``) + unknown-category
    skip (``test_sanitise_overrides_unknown_category_ignored``)
  * Round 35 C4 / Round 38 C3: ``config_overrides`` emits + bool widen
    (``test_config_overrides_emits_assignments``)
  * Round 38 C3: gui still rejects bool — per-category policy guard
    (``test_gui_overrides_still_rejects_bool``)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_sanitise_overrides_unknown_category_ignored():
    """Round 34 C4 / Round 35 C4: font_config sub-dicts whose key isn't
    registered in ``_OVERRIDE_CATEGORIES`` must be silently ignored by
    ``_emit_overrides_rpy`` — no aux rpy emitted for that category.
    Prevents a typo'd / malicious ``nvl_overrides`` from leaking into
    the generated init-999 block.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {"file": "a.rpy", "line": 1, "original": "Hello", "translation": "你好", "status": "ok"}
    ]
    # Mix: registered (``gui_overrides`` + ``config_overrides`` as of
    # round 35) + unregistered (``nvl_overrides``, ``style_overrides``,
    # ``foobar_overrides``) — only the registered ones should land.
    cfg = {
        "gui_overrides": {"gui.text_size": 22},
        "config_overrides": {"config.thoughtbubble_width": 400},
        "nvl_overrides": {"nvl.background": 1},
        "style_overrides": {"style.default.font_size": 20},
        "foobar_overrides": {"foobar.anything": 1},
    }
    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        emit_runtime_hook(out_game, entries, font_config=cfg)
        content = (out_game / "zz_tl_inject_gui.rpy").read_text(encoding="utf-8")
        # Registered categories land.
        assert "gui.text_size = 22" in content
        assert "config.thoughtbubble_width = 400" in content
        # Unregistered categories are silently dropped.
        assert "nvl.background" not in content
        assert "style.default.font_size" not in content
        assert "foobar.anything" not in content
    print("[OK] sanitise_overrides_unknown_category_ignored")


def test_override_categories_table_is_extensible():
    """Round 34 C4 / Round 35 C4: ``_OVERRIDE_CATEGORIES`` dispatch table
    registers ``gui_overrides`` + ``config_overrides`` (round 35 added the
    second category now that the infrastructure proven in prod).  Regression
    guard so a future commit that (a) renames the table, (b) silently relaxes
    any regex, or (c) auto-registers ``style_overrides`` without the Ren'Py
    init-timing review won't slip in unnoticed.
    """
    from core.runtime_hook_emitter import (
        _OVERRIDE_CATEGORIES,
        _SAFE_GUI_KEY,
        _SAFE_CONFIG_KEY,
    )

    assert isinstance(_OVERRIDE_CATEGORIES, dict)
    # Exactly two categories registered today (round 35).
    assert set(_OVERRIDE_CATEGORIES.keys()) == {"gui_overrides", "config_overrides"}
    # Identity-check each regex so the dispatch table stays pinned to
    # the same compiled pattern object (no silent behavioural drift).
    assert _OVERRIDE_CATEGORIES["gui_overrides"] is _SAFE_GUI_KEY
    assert _OVERRIDE_CATEGORIES["config_overrides"] is _SAFE_CONFIG_KEY

    # gui regex: accepts nested dot-paths, rejects attack shapes.
    gui_re = _OVERRIDE_CATEGORIES["gui_overrides"]
    for ok in ("gui.text_size", "gui.name_text_size", "gui.sub.nested"):
        assert gui_re.match(ok), f"gui regex unexpectedly rejects {ok!r}"
    for bad in (
        "gui.",
        "gui.test;drop",
        "style.default",
        "gui text_size",
        "import os",
        "gui.text_size + 1",
    ):
        assert gui_re.match(bad) is None, f"gui regex unexpectedly accepts {bad!r} (attack shape)"

    # config regex: Ren'Py ``config`` is a FLAT namespace (module-like
    # object), no nested ``config.sub.X`` form — regex rejects those
    # on purpose so operators don't end up with malformed assignments.
    cfg_re = _OVERRIDE_CATEGORIES["config_overrides"]
    for ok in ("config.thoughtbubble_width", "config.autosave", "config.log"):
        assert cfg_re.match(ok), f"config regex unexpectedly rejects {ok!r}"
    for bad in (
        "config.",
        "config.sub.nested",
        "config.test;drop",
        "gui.text_size",
        "config text_size",
        "config.x + 1",
    ):
        assert cfg_re.match(bad) is None, (
            f"config regex unexpectedly accepts {bad!r} (attack shape)"
        )
    print("[OK] override_categories_table_is_extensible")


def test_config_overrides_emits_assignments():
    """Round 35 C4 + Round 38 C3: a ``config_overrides`` sub-dict emits
    ``config.X = V`` assignments in the aux rpy's init 999 block.  Round 38
    C3 widens the accepted value types for config_overrides specifically
    to include ``bool`` (Ren'Py's ``config.*`` namespace has first-class
    boolean switches — ``config.autosave``, ``config.developer``,
    ``config.rollback_enabled`` etc.).  ``gui.*`` categories still reject
    bool (see ``test_gui_overrides_still_rejects_bool``).  Flat-namespace
    regex rejection (``config.sub.nested``) is unchanged.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {"file": "a.rpy", "line": 1, "original": "Hello", "translation": "你好", "status": "ok"}
    ]
    cfg = {
        "config_overrides": {
            "config.thoughtbubble_width": 400,
            "config.thoughtbubble_offset": 12.5,  # float OK
            "config.autosave": True,  # r38 C3: bool now ACCEPTED
            "config.developer": False,  # r38 C3: bool False also OK
            "config.sub.nested": 1,  # rejected by flat-namespace regex
        },
        # Gui entry coexists in the same file.
        "gui_overrides": {"gui.text_size": 22},
    }
    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        emit_runtime_hook(out_game, entries, font_config=cfg)
        content = (out_game / "zz_tl_inject_gui.rpy").read_text(encoding="utf-8")
        # Both categories land in the SAME init 999 block.
        assert "init 999 python:" in content
        assert "config.thoughtbubble_width = 400" in content
        assert "config.thoughtbubble_offset = 12.5" in content
        assert "gui.text_size = 22" in content
        # Round 38 C3: bool values emitted as Python literals (repr(True)
        # / repr(False) — valid Ren'Py Python).
        assert "config.autosave = True" in content
        assert "config.developer = False" in content
        # Flat-namespace regex still rejects dotted config keys.
        assert "config.sub.nested" not in content
    print("[OK] config_overrides_emits_assignments")


def test_gui_overrides_still_rejects_bool():
    """Round 38 C3: the bool policy is per-category.  ``gui_overrides``
    keeps its round-33 rejection of boolean values because no supported
    Ren'Py ``gui.*`` attribute legitimately expects a boolean (font
    sizes, layout measurements, color constants are all numeric /
    string).  Regression guard so the r38 config bool widening doesn't
    silently leak into gui and mask operator typos.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {"file": "a.rpy", "line": 1, "original": "Hello", "translation": "你好", "status": "ok"}
    ]
    cfg = {
        "gui_overrides": {
            "gui.text_size": 22,  # OK — int
            "gui.bad_flag": True,  # r38 C3: still REJECTED for gui
            "gui.another_flag": False,  # r38 C3: still REJECTED for gui
        },
        # Control: same bool values land under config_overrides.
        "config_overrides": {
            "config.autosave": True,
        },
    }
    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        emit_runtime_hook(out_game, entries, font_config=cfg)
        content = (out_game / "zz_tl_inject_gui.rpy").read_text(encoding="utf-8")
        # gui int OK, gui bools rejected.
        assert "gui.text_size = 22" in content
        assert "gui.bad_flag" not in content, "r38 C3: gui_overrides must still reject bool values"
        assert "gui.another_flag" not in content
        # Control: config_overrides DOES accept bool (proves policy is
        # per-category, not global).
        assert "config.autosave = True" in content
    print("[OK] gui_overrides_still_rejects_bool")


def run_all() -> int:
    """Run every test in this module; return test count."""
    tests = [
        # Round 34 Commit 4 / Round 35 Commit 4 (override dispatch table)
        test_sanitise_overrides_unknown_category_ignored,
        test_override_categories_table_is_extensible,
        # Round 35 Commit 4 (config_overrides registration)
        test_config_overrides_emits_assignments,
        # Round 38 C3 (bool per-category — gui still rejects)
        test_gui_overrides_still_rejects_bool,
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
