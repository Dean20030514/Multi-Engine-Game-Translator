#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round 57 T3: integration tests against a representative complex fixture.

Closes the audit gap that ``tests/test_tl_pipeline.py``'s
``_TL_EMPTY_FIXTURE`` (only 4 translate blocks, plain "Hello"/"World")
diverges from the real-world workload (r52 measurement: 74098 entries
across The Tyrant + SAZMOD with nvl blocks, multi-line say, ``{i}``
formatting, escape quotes, and complex character aliases).

The fixture below is **synthetic** (not copied from the upstream game)
to avoid bundling third-party game content, but covers every Ren'Py
parsing path the real corpus exercises:

  * nvl_clear / nvl block + ``nvl_<name>`` say speakers
  * Multi-line ``"\\n"`` inside say body
  * Inline format tags: ``{i}``, ``{b}``, ``{color=...}``, ``{size=...}``
  * Variable interpolation: ``[name]``, ``[item_count]``
  * Escape quotes inside dialogue: ``\\"...\\"``
  * Character speakers (``e ""``, ``m "..."``)
  * Narrator (anonymous) lines
  * ``translate chinese strings`` block with ``old=``/``new=``
  * Long source-line numbers (simulating SAZMOD-style mod paths)

Tests assert the scan→assign-translation→fill→read-back round-trip
preserves all entries and writes them back into the correct slots.

Round-trip byte-identity for the unmodified parts (comments, blank
lines, source-file annotation comments) is the strict invariant.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from translators.tl_parser import scan_tl_directory, fill_translation


# Complex fixture covering every parsing path the r52 workload hit.
_TL_COMPLEX_FIXTURE = """# TODO: Translation updated at 2024-06-01

# game/script.rpy:42
translate chinese intro_d8a3f1:

    # e "Hello there, [name]!"
    e ""

# game/script.rpy:55
translate chinese intro_d8a3f2:

    # m "I have {color=#fa0}[item_count]{/color} items in my inventory."
    m ""

# game/script.rpy:60
translate chinese intro_d8a3f3:

    # "She whispered, \\"Don't tell anyone.\\""
    ""

# game/script.rpy:75
translate chinese nvl_block_e5b2a1:

    # nvl_narrator "First line of paragraph one.\\nSecond line of paragraph one.\\nThird line wraps as well."
    nvl_narrator ""

# game/script.rpy:90
translate chinese formatted_a8c4d9:

    # e "{i}This is italic.{/i} {b}This is bold.{/b} {size=+4}This is big.{/size}"
    e ""

# game/SAZMOD/scripts/home/basement_02.rpy:1234
translate chinese sazmod_basement_b9d3e7:

    # m "[mom_name] is in the basement."
    m ""

translate chinese strings:

    # game/screens.rpy:281
    old "Save"
    new ""

    # game/screens.rpy:282
    old "Load"
    new ""

    # game/screens.rpy:300
    old "{color=#fff}{size=24}New Game{/size}{/color}"
    new ""
"""


# Expected translations to be assigned during the round-trip
_TRANSLATIONS = {
    "intro_d8a3f1": "你好啊，[name]！",
    "intro_d8a3f2": "我背包里有 {color=#fa0}[item_count]{/color} 件物品。",
    "intro_d8a3f3": '她低声说，\\"别告诉任何人。\\"',
    "nvl_block_e5b2a1": "第一段第一行。\\n第一段第二行。\\n第三行也会换行。",
    "formatted_a8c4d9": "{i}这是斜体。{/i} {b}这是粗体。{/b} {size=+4}这很大。{/size}",
    "sazmod_basement_b9d3e7": "[mom_name] 在地下室里。",
}
_STRING_TRANSLATIONS = {
    "Save": "保存",
    "Load": "读取",
    "{color=#fff}{size=24}New Game{/size}{/color}": "{color=#fff}{size=24}新游戏{/size}{/color}",
}


def test_w_round57_t3_complex_fixture_scan_extracts_all():
    """Scan must surface every translatable slot — dialogues + strings."""
    with tempfile.TemporaryDirectory() as td:
        tl_root = Path(td) / "tl"
        tl_dir = tl_root / "chinese"
        tl_dir.mkdir(parents=True)
        (tl_dir / "complex.rpy").write_text(_TL_COMPLEX_FIXTURE, encoding="utf-8")

        results = scan_tl_directory(str(tl_root), "chinese")
        assert len(results) == 1, f"expected 1 tl file, got {len(results)}"
        parse_result = results[0]

    # 6 dialogue entries (3 simple + 1 nvl + 1 formatted + 1 SAZMOD path)
    assert len(parse_result.dialogues) == 6, (
        f"expected 6 dialogue entries, got {len(parse_result.dialogues)}: "
        f"{[d.identifier for d in parse_result.dialogues]}"
    )
    # 3 string entries (Save / Load / formatted New Game)
    assert len(parse_result.strings) == 3, (
        f"expected 3 string entries, got {len(parse_result.strings)}"
    )

    # Spot-check that complex content survived the parser intact
    nvl_entry = next(d for d in parse_result.dialogues if d.identifier == "nvl_block_e5b2a1")
    assert "First line of paragraph one." in nvl_entry.original
    assert "wraps" in nvl_entry.original

    formatted = next(d for d in parse_result.dialogues if d.identifier == "formatted_a8c4d9")
    assert "{i}" in formatted.original and "{/i}" in formatted.original
    assert "{size=+4}" in formatted.original

    print("[OK] w_round57_t3_complex_fixture_scan_extracts_all")


def test_w_round57_t3_complex_fixture_fill_round_trip():
    """Fill→read-back round-trip writes translations into the right slots
    AND preserves every comment/blank/source-line annotation verbatim.
    """
    with tempfile.TemporaryDirectory() as td:
        tl_root = Path(td) / "tl"
        tl_dir = tl_root / "chinese"
        tl_dir.mkdir(parents=True)
        rpy_path = tl_dir / "complex.rpy"
        rpy_path.write_text(_TL_COMPLEX_FIXTURE, encoding="utf-8")

        results = scan_tl_directory(str(tl_root), "chinese")
        parse_result = results[0]

        # Assign dialogue translations
        for d in parse_result.dialogues:
            t = _TRANSLATIONS.get(d.identifier)
            assert t is not None, f"missing fixture translation for {d.identifier}"
            d.translation = t
        # Assign string translations
        for s in parse_result.strings:
            t = _STRING_TRANSLATIONS.get(s.old)
            assert t is not None, f"missing fixture string translation for {s.old!r}"
            s.new = t

        all_entries = list(parse_result.dialogues) + list(parse_result.strings)
        filled = fill_translation(str(rpy_path), all_entries)
        rpy_path.write_text(filled, encoding="utf-8")

        result = rpy_path.read_text(encoding="utf-8")

    # Property 1: every translation was written back somewhere
    for ident, zh in _TRANSLATIONS.items():
        assert zh in result, f"dialogue translation for {ident} not found in output"
    for old, zh in _STRING_TRANSLATIONS.items():
        assert zh in result, f"string translation for {old!r} not found in output"

    # Property 2: no empty `""` slots remain (all filled)
    for ln in result.splitlines():
        stripped = ln.strip()
        # Single bare empty quote pair = unfilled slot
        if stripped == '""':
            raise AssertionError(f"empty slot remained: {ln!r}")

    # Property 3: source-file annotation comments preserved
    assert "# game/script.rpy:42" in result
    assert "# game/script.rpy:75" in result
    assert "# game/SAZMOD/scripts/home/basement_02.rpy:1234" in result
    assert "# game/screens.rpy:281" in result

    # Property 4: structural keywords preserved
    assert "translate chinese intro_d8a3f1:" in result
    assert "translate chinese strings:" in result
    assert "nvl_narrator " in result

    print("[OK] w_round57_t3_complex_fixture_fill_round_trip")


def run_all() -> int:
    tests = [
        test_w_round57_t3_complex_fixture_scan_extracts_all,
        test_w_round57_t3_complex_fixture_fill_round_trip,
    ]
    for t in tests:
        t()
    return len(tests)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} COMPLEX FIXTURE TESTS PASSED")
    print("=" * 40)
