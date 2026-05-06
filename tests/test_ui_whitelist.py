#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI whitelist tests — split from ``tests/test_file_processor.py`` in
round 45 because the parent file reached 830 lines (over CLAUDE.md 800
soft limit) after the r32 configurable-whitelist feature plus the
r44 audit-tail oversize-file test.  The UI whitelist is a
self-contained public-API slice (``is_common_ui_button`` /
``load_ui_button_whitelist`` / ``clear_ui_button_whitelist`` /
``add_ui_button_whitelist`` / ``get_ui_button_whitelist_extensions`` /
``COMMON_UI_BUTTONS``) — a clean cut point.

Coverage (byte-identical copies of the r31 / r32 / r44 tests):
  * Round 31 Tier A-1: ``is_common_ui_button`` detector
    (case / whitespace / non-string)
  * Round 32 Commit 2: configurable sidecar loaders (.txt / .json),
    builtin-baseline isolation, clear/rebuild semantics,
    frozenset-rebind thread-safety contract
  * Round 44 audit-tail: 50 MB size cap on whitelist files

Leaves the r31 Tier A-2 placeholder-drift tests (``fix_chinese_
placeholder_drift`` + ``_filter_checked_translations_fixes_
placeholder_drift``) in ``test_file_processor.py`` — those cover
a different feature (placeholder normalisation), not UI whitelist.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_is_common_ui_button():
    """Round 31 Tier A-1: common UI button detector normalises case + whitespace."""
    from file_processor import is_common_ui_button, COMMON_UI_BUTTONS

    # Curated buttons from the imported competitor hook list must match.
    for word in ("OK", "Cancel", "Save", "Quit", "Main Menu", "Preferences"):
        assert is_common_ui_button(word), f"{word!r} should be detected"

    # Case-insensitive.
    assert is_common_ui_button("ok")
    assert is_common_ui_button("OK")
    assert is_common_ui_button("Ok")

    # Whitespace normalisation.
    assert is_common_ui_button("  Save  ")
    assert is_common_ui_button("main   menu")  # collapsed to "main menu"

    # Genuine dialogue must NOT match.
    assert not is_common_ui_button("Hello world")
    assert not is_common_ui_button("Save the cat")  # "save" alone matches, multi-word shouldn't

    # Empty / non-string handled gracefully.
    assert not is_common_ui_button("")
    assert not is_common_ui_button("   ")
    assert not is_common_ui_button(None)  # type: ignore[arg-type]
    assert not is_common_ui_button(42)  # type: ignore[arg-type]

    # Whitelist export has the expected shape.
    assert isinstance(COMMON_UI_BUTTONS, frozenset)
    assert "cancel" in COMMON_UI_BUTTONS  # all entries lowercased
    print("[OK] is_common_ui_button")


def test_load_ui_button_whitelist_txt():
    """Round 32 Commit 2: .txt whitelist loader honours UTF-8-sig, skips
    ``#`` comments + blank lines, and feeds ``is_common_ui_button``.
    """
    import tempfile
    from pathlib import Path
    from file_processor import (
        clear_ui_button_whitelist,
        load_ui_button_whitelist,
        is_common_ui_button,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()

    # Content includes a BOM, a comment, a blank line, mixed case, and
    # whitespace variants we expect to normalise to the same token.
    content = (
        "\ufeff# customised UI buttons\n存档\n读档\n\n  Main Hub  \n# trailing comment\nProceed\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write(content)
        tmp_path = f.name
    try:
        added = load_ui_button_whitelist([tmp_path])
        # 4 distinct tokens: 存档 / 读档 / main hub / proceed (comments + blanks skipped)
        assert added == 4, f"expected 4 new entries, got {added}"

        # Python-side lookups must now succeed (including normalisation).
        assert is_common_ui_button("存档")
        assert is_common_ui_button("读档")
        assert is_common_ui_button("main hub")
        assert is_common_ui_button("Main Hub")  # case-insensitive
        assert is_common_ui_button("  main   hub  ")  # whitespace collapse
        assert is_common_ui_button("Proceed")
        assert is_common_ui_button("proceed")

        # Baseline entries are still recognised.
        assert is_common_ui_button("OK")
        assert is_common_ui_button("Save")

        # Unrelated strings still fail.
        assert not is_common_ui_button("Hello world")

        # Replaying the same file is a no-op.
        added_again = load_ui_button_whitelist([tmp_path])
        assert added_again == 0

        # Extensions snapshot is a frozenset containing just the new tokens.
        ext = get_ui_button_whitelist_extensions()
        assert isinstance(ext, frozenset)
        assert "存档" in ext
        assert "main hub" in ext
        # Baseline must NOT leak into the extension snapshot.
        assert "ok" not in ext
    finally:
        Path(tmp_path).unlink()
        clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_txt")


def test_load_ui_button_whitelist_json():
    """Round 32 Commit 2: .json whitelist loader accepts top-level list of
    strings and rejects other shapes with a warning.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from file_processor import (
        clear_ui_button_whitelist,
        load_ui_button_whitelist,
        is_common_ui_button,
    )

    clear_ui_button_whitelist()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
        _json.dump(["存档", "读档", "Proceed", 42, None, "  back to menu  "], f, ensure_ascii=False)
        good_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
        _json.dump({"not": "a list"}, f)
        bad_path = f.name
    try:
        # Good file: list with 3 strings (non-strings silently dropped).
        added = load_ui_button_whitelist([good_path])
        # 存档 / 读档 / proceed / back to menu = 4 distinct tokens
        assert added == 4, f"expected 4 new entries, got {added}"
        assert is_common_ui_button("存档")
        assert is_common_ui_button("Proceed")
        assert is_common_ui_button("Back to Menu")

        # Bad shape: warning path, nothing added.
        added_bad = load_ui_button_whitelist([bad_path])
        assert added_bad == 0

        # Missing file: warning path, nothing added.
        added_missing = load_ui_button_whitelist(["/does/not/exist/ever.json"])
        assert added_missing == 0
    finally:
        Path(good_path).unlink()
        Path(bad_path).unlink()
        clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_json")


def test_ui_button_whitelist_builtin_untouched():
    """Round 32 Commit 2: loading extensions must not mutate the baseline
    ``COMMON_UI_BUTTONS`` frozenset — it stays the same object identity
    and the same contents.
    """
    from file_processor import (
        clear_ui_button_whitelist,
        add_ui_button_whitelist,
        COMMON_UI_BUTTONS,
    )

    clear_ui_button_whitelist()
    baseline_id = id(COMMON_UI_BUTTONS)
    baseline_len = len(COMMON_UI_BUTTONS)

    add_ui_button_whitelist(["扩展按钮 A", "扩展按钮 B"])

    # Re-import to simulate a fresh reader — the module-level constant
    # must still be the exact same frozenset object.
    from file_processor import COMMON_UI_BUTTONS as COMMON_UI_BUTTONS_RELOADED

    assert id(COMMON_UI_BUTTONS_RELOADED) == baseline_id
    assert len(COMMON_UI_BUTTONS_RELOADED) == baseline_len
    assert "扩展按钮 A".lower() not in COMMON_UI_BUTTONS_RELOADED

    clear_ui_button_whitelist()
    print("[OK] ui_button_whitelist_builtin_untouched")


def test_clear_ui_button_whitelist_restores_baseline():
    """Round 32 Commit 2: ``clear_ui_button_whitelist`` drops every
    extension while keeping the baseline untouched.
    """
    from file_processor import (
        clear_ui_button_whitelist,
        add_ui_button_whitelist,
        is_common_ui_button,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()
    add_ui_button_whitelist(["存档", "读档"])
    assert is_common_ui_button("存档")
    assert len(get_ui_button_whitelist_extensions()) == 2

    clear_ui_button_whitelist()
    assert not is_common_ui_button("存档")
    assert not is_common_ui_button("读档")
    assert get_ui_button_whitelist_extensions() == frozenset()

    # Baseline must still be reachable after clear.
    assert is_common_ui_button("OK")
    assert is_common_ui_button("Save")
    print("[OK] clear_ui_button_whitelist_restores_baseline")


def test_ui_button_whitelist_rebinds_frozenset():
    """Round 32 Commit 2: ``_ui_button_extensions`` is REBOUND, not mutated,
    on every add/clear.  This is the thread-safety contract — a worker
    thread that captured a reference to the previous frozenset must still
    see a stable snapshot while the main thread extends the whitelist.
    """
    from file_processor import (
        clear_ui_button_whitelist,
        add_ui_button_whitelist,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()
    snap_empty = get_ui_button_whitelist_extensions()
    assert isinstance(snap_empty, frozenset)

    add_ui_button_whitelist(["alpha"])
    snap_alpha = get_ui_button_whitelist_extensions()
    # Rebind: different object identity from the empty snapshot.
    assert snap_alpha is not snap_empty
    # Prior snapshot is unchanged (frozenset, not mutated).
    assert snap_empty == frozenset()
    assert snap_alpha == frozenset({"alpha"})

    add_ui_button_whitelist(["beta"])
    snap_both = get_ui_button_whitelist_extensions()
    assert snap_both is not snap_alpha
    assert snap_alpha == frozenset({"alpha"})  # still immutable
    assert snap_both == frozenset({"alpha", "beta"})

    clear_ui_button_whitelist()
    print("[OK] ui_button_whitelist_rebinds_frozenset")


def test_load_ui_button_whitelist_rejects_oversized_file():
    """Round 44 audit-tail: load_ui_button_whitelist skips
    operator-supplied UI whitelist files above the 50 MB cap with a
    warning rather than loading the whole file into memory.  Missed by
    the r37-r43 M2 phases because r32's whitelist loader pre-dated the
    size-gate idiom.  Uses a 51 MB sparse file to exercise the cap
    without consuming disk."""
    import tempfile
    from pathlib import Path
    from file_processor import (
        clear_ui_button_whitelist,
        load_ui_button_whitelist,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()

    with tempfile.TemporaryDirectory() as td:
        # Oversized .json whitelist — should be skipped entirely.
        big_path = Path(td) / "huge_whitelist.json"
        with open(big_path, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        added = load_ui_button_whitelist([str(big_path)])
        assert added == 0, (
            f"oversized whitelist file must be skipped (no entries added), got added={added}"
        )
        # Extensions snapshot should remain empty (no new entries).
        assert get_ui_button_whitelist_extensions() == frozenset(), (
            "oversized whitelist must not populate extensions"
        )

    clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_rejects_oversized_file")


def test_load_ui_button_whitelist_mixed_directory():
    """Round 46 Step 4 (G2): ``load_ui_button_whitelist`` with a mixed
    list — small valid files + oversized rogue files — must load
    entries from the small files while silently skipping the oversized
    ones, rather than failing the whole batch.  Closes the round 45
    audit's optional MEDIUM gap on per-file granularity guarantees
    when an operator passes a directory containing both legitimate
    small overrides and accidental large files.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from file_processor import (
        clear_ui_button_whitelist,
        load_ui_button_whitelist,
        is_common_ui_button,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)

        # Small legitimate .txt — should be loaded (2 valid tokens after
        # blank/comment skip).
        small_txt = td_path / "small.txt"
        small_txt.write_text(
            "round46_a\n# comment line\n\nround46_b\n",
            encoding="utf-8",
        )

        # Small legitimate .json — should be loaded (1 valid string,
        # non-string entries dropped per existing .json loader contract).
        small_json = td_path / "small.json"
        small_json.write_text(
            _json.dumps(["round46_c", 42, None], ensure_ascii=False),
            encoding="utf-8",
        )

        # Oversized .json (51 MB sparse) — must be skipped by size cap.
        big_json = td_path / "big.json"
        with open(big_json, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        # Oversized .txt (51 MB sparse) — must be skipped by size cap.
        big_txt = td_path / "big.txt"
        with open(big_txt, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        # Mix the order to prove ordering does not influence per-file
        # gating (small entries before / between / after oversized files).
        added = load_ui_button_whitelist(
            [
                str(small_txt),
                str(big_json),
                str(small_json),
                str(big_txt),
            ]
        )

        # 3 valid tokens added: round46_a + round46_b (small.txt) +
        # round46_c (small.json).  Oversized files contributed 0.
        assert added == 3, (
            f"expected 3 entries (2 from small.txt + 1 from small.json), "
            f"got {added}; oversized .json/.txt should be silently "
            f"skipped without aborting the batch"
        )
        # Per-file granularity: small entries are reachable.
        assert is_common_ui_button("round46_a")
        assert is_common_ui_button("round46_b")
        assert is_common_ui_button("round46_c")
        ext = get_ui_button_whitelist_extensions()
        assert "round46_a" in ext
        assert "round46_b" in ext
        assert "round46_c" in ext
        # No bytes from the oversized files leaked into extensions.
        assert "\x00" not in "".join(ext), (
            "oversized sparse-file null bytes must not pollute extensions"
        )

    clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_mixed_directory")


def test_load_ui_button_whitelist_order_invariant():
    """Round 47 Step 2 (G2 LOW gap): the file load order must not affect
    the final whitelist contents.  Three permutations of small + big
    files must produce the same extension set and added count.  Pins
    the invariant that ``load_ui_button_whitelist`` processes files
    independently (via per-file ``add_ui_button_whitelist`` which uses
    frozenset union — order-insensitive by definition)."""
    import json as _json
    import tempfile
    from pathlib import Path
    from file_processor import (
        clear_ui_button_whitelist,
        load_ui_button_whitelist,
        get_ui_button_whitelist_extensions,
    )

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        small_txt = td_path / "small.txt"
        small_txt.write_text("alpha\nbeta\n", encoding="utf-8")
        big_json = td_path / "big.json"
        with open(big_json, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        small_json = td_path / "small.json"
        small_json.write_text(_json.dumps(["gamma"], ensure_ascii=False), encoding="utf-8")

        files = [str(small_txt), str(big_json), str(small_json)]
        # 3 representative permutations: forward / backward / big-first
        permutations_to_test = [
            (files[0], files[1], files[2]),
            (files[2], files[1], files[0]),
            (files[1], files[0], files[2]),
        ]

        expected_ext = None
        expected_added = None
        for perm in permutations_to_test:
            clear_ui_button_whitelist()
            added = load_ui_button_whitelist(list(perm))
            ext = get_ui_button_whitelist_extensions()
            if expected_ext is None:
                expected_ext = ext
                expected_added = added
            assert ext == expected_ext, (
                f"order {perm}: extension set differs;\n  got      {ext}\n  expected {expected_ext}"
            )
            assert added == expected_added, (
                f"order {perm}: added count {added} != expected {expected_added}"
            )

    clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_order_invariant")


def test_load_ui_button_whitelist_dedupes_cross_files():
    """Round 47 Step 2 (G2 LOW gap): the same token appearing in
    multiple files must be deduplicated; the final extension set
    contains each token exactly once.  Verified end-to-end through
    ``load_ui_button_whitelist`` → ``add_ui_button_whitelist`` →
    frozenset union (which is naturally idempotent).  Also pins the
    ``added`` return value semantics: it counts NET NEW tokens added
    across the whole batch, not per-file additions."""
    import tempfile
    from pathlib import Path
    from file_processor import (
        clear_ui_button_whitelist,
        load_ui_button_whitelist,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Two .txt files both containing "shared_token" + each their
        # own unique token.  Total unique tokens across batch: 3.
        file_a = td_path / "a.txt"
        file_a.write_text("shared_token\nunique_a\n", encoding="utf-8")
        file_b = td_path / "b.txt"
        file_b.write_text("shared_token\nunique_b\n", encoding="utf-8")

        added = load_ui_button_whitelist([str(file_a), str(file_b)])

        ext = get_ui_button_whitelist_extensions()
        assert "shared_token" in ext
        assert "unique_a" in ext
        assert "unique_b" in ext
        # Exactly 3 unique tokens — shared_token deduped across files.
        assert len(ext) == 3, f"expected 3 unique tokens (shared deduped), got {len(ext)}: {ext}"
        # added = net new across batch = 3 (shared_token + unique_a +
        # unique_b); the 2nd file's "shared_token" contributes 0.
        assert added == 3, (
            f"expected added=3 (net new across batch), got {added}; "
            f"the 2nd file's duplicate shared_token must contribute 0"
        )

    clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_dedupes_cross_files")


def test_load_ui_button_whitelist_normalization_dedupes_cross_files():
    """Round 48 Step 1 (G2.1): tokens varying only in case + whitespace
    must be normalised (via ``_normalise_ui_button``: lower + strip +
    whitespace-collapse) then deduplicated across files via frozenset
    union.  Tests the interaction r47 audit identified as a coverage
    gap — r47 G2 dedup test only used identical strings ('shared_token'),
    not case/whitespace variations.

    Tokens "Save", "save", "  Save  ", "Save Game", "save  game",
    " Save Game " across 3 files all normalise to either "save" or
    "save game" → final extension set has exactly 2 unique tokens.
    """
    import tempfile
    from pathlib import Path
    from file_processor import (
        clear_ui_button_whitelist,
        load_ui_button_whitelist,
        is_common_ui_button,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # 3 files with case + whitespace variations of 2 tokens
        file_a = td_path / "a.txt"
        file_a.write_text("Save\nSave Game\n", encoding="utf-8")
        file_b = td_path / "b.txt"
        file_b.write_text("save\n  Save  \n", encoding="utf-8")
        file_c = td_path / "c.txt"
        file_c.write_text("save  game\n Save Game \n", encoding="utf-8")

        added = load_ui_button_whitelist([str(file_a), str(file_b), str(file_c)])

        # Two distinct normalised tokens across the 6 raw input strings.
        ext = get_ui_button_whitelist_extensions()
        assert "save" in ext, (
            f"normalised 'save' (from Save/save/  Save  ) must be in extensions: {ext}"
        )
        assert "save game" in ext, (
            f"normalised 'save game' (from Save Game/save  game/ Save Game ) "
            f"must be in extensions: {ext}"
        )
        assert len(ext) == 2, (
            f"expected 2 unique normalised tokens (save + save game), got {len(ext)}: {ext}"
        )
        # added counter = 2 net new (case/whitespace variations all dedup
        # to 2 normalised tokens; subsequent additions return 0)
        assert added == 2, f"expected added=2 (case/whitespace all dedup), got {added}"

        # All 6 raw variations resolve via is_common_ui_button (the
        # lookup also normalises before checking, so case/whitespace
        # variations of either stored token still match).
        for variation in (
            "Save",
            "save",
            "  Save  ",
            "SAVE",
            "Save Game",
            "save  game",
            " Save Game ",
            "SAVE GAME",
        ):
            assert is_common_ui_button(variation), (
                f"variation {variation!r} should match the normalised "
                f"stored form via is_common_ui_button"
            )

    clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_normalization_dedupes_cross_files")


def test_normalise_ui_button_does_not_apply_unicode_nfc_nfd_normalisation():
    """Round 49 Step 1 (r48 audit LOW Coverage closure): pin the
    ASCII-dominant design choice for ``_normalise_ui_button``.

    The normaliser is documented as case-fold + whitespace-collapse only;
    it deliberately does NOT apply Unicode NFC/NFD/NFKC/NFKD normalisation.
    Regression: precomposed and decomposed forms of the same logical
    character must remain DISTINCT tokens.  If a future refactor adds
    ``unicodedata.normalize(...)``, this test will fail and the change
    must be reviewed against the design rationale in the checker
    docstring before merging.

    Cross-script / accent-fuzz alias resolution belongs in
    ``core.lang_config.resolve_translation_field`` via
    ``lang_config.field_aliases``, not in the button-name normaliser.
    Operators needing NFC/NFD interop must pre-normalise their input
    before calling ``add_ui_button_whitelist``.
    """
    from file_processor.checker import _normalise_ui_button
    from file_processor import (
        is_common_ui_button,
        add_ui_button_whitelist,
        clear_ui_button_whitelist,
    )

    # NFC: precomposed "é" as the single codepoint U+00E9.
    nfc_form = "café"
    # NFD: decomposed "é" as e (U+0065) + combining acute accent (U+0301).
    nfd_form = "café"

    # Test fixture sanity: visually identical but codepoint-distinct.
    assert nfc_form != nfd_form, "test fixture: NFC and NFD strings must differ at codepoint level"
    assert len(nfc_form) == 4 and len(nfd_form) == 5, (
        f"test fixture: NFC len should be 4 and NFD len should be 5, "
        f"got {len(nfc_form)} / {len(nfd_form)}"
    )

    # Core assertion: normaliser does NOT collapse NFC and NFD to the
    # same token (which Unicode normalisation would).
    nfc_normalised = _normalise_ui_button(nfc_form)
    nfd_normalised = _normalise_ui_button(nfd_form)
    assert nfc_normalised != nfd_normalised, (
        f"_normalise_ui_button must NOT apply Unicode normalisation; "
        f"NFC {nfc_normalised!r} and NFD {nfd_normalised!r} should differ "
        f"(see _normalise_ui_button docstring: ASCII-dominant by design)"
    )

    # End-to-end: storing NFC form must NOT match a lookup of NFD form.
    clear_ui_button_whitelist()
    try:
        added = add_ui_button_whitelist([nfc_form])
        assert added == 1, f"NFC token should be added as 1 new entry, got added={added}"

        # NFC lookup hits the stored NFC token.
        assert is_common_ui_button(nfc_form), (
            f"NFC form {nfc_form!r} must match its own stored entry"
        )

        # NFD lookup of the same visual character does NOT hit (deliberate).
        assert not is_common_ui_button(nfd_form), (
            f"NFD {nfd_form!r} must NOT match stored NFC {nfc_form!r} — "
            f"operator must pre-normalise input if NFC/NFD interop is needed"
        )
    finally:
        clear_ui_button_whitelist()

    print("[OK] normalise_ui_button_does_not_apply_unicode_nfc_nfd_normalisation")


ALL_TESTS = [
    # Round 31 Tier A-1
    test_is_common_ui_button,
    # Round 32 Commit 2
    test_load_ui_button_whitelist_txt,
    test_load_ui_button_whitelist_json,
    test_ui_button_whitelist_builtin_untouched,
    test_clear_ui_button_whitelist_restores_baseline,
    test_ui_button_whitelist_rebinds_frozenset,
    # Round 44 audit-tail
    test_load_ui_button_whitelist_rejects_oversized_file,
    # Round 46 Step 4 (G2): per-file granularity in mixed-directory load
    test_load_ui_button_whitelist_mixed_directory,
    # Round 47 Step 2 (G2 LOW gap): order invariance + cross-file dedup
    test_load_ui_button_whitelist_order_invariant,
    test_load_ui_button_whitelist_dedupes_cross_files,
    # Round 48 Step 1 (G2.1 audit gap): normalization-dedup interaction
    test_load_ui_button_whitelist_normalization_dedupes_cross_files,
    # Round 49 Step 1 (r48 audit LOW Coverage closure): NFC/NFD design choice
    test_normalise_ui_button_does_not_apply_unicode_nfc_nfd_normalisation,
]


def run_all() -> int:
    """Run every test in this module; return test count.

    Added in round 45 audit fix: aligns this suite with the pattern
    used by all 22 other independent test suites so integrators can
    treat them uniformly.  Runtime is unchanged.
    """
    for t in ALL_TESTS:
        t()
    return len(ALL_TESTS)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} UI WHITELIST TESTS PASSED")
    print("=" * 40)
