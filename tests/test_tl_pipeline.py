#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for ``translators.tl_mode`` main flow (round 22 T-H-2).

Exercises the tl-mode pipeline end-to-end with mocked side-effects. Covers:
  1. The scan → fill core loop (data layer of tl_mode).
  2. ``run_tl_pipeline`` short-circuiting when every slot is already filled.

Intended to provide regression coverage before the round 24 refactor of
``tl_mode.py`` (928 → ~350 + 2 submodules) and ``tl_parser.py`` (1106 → ~600
+ 2 submodules).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.api_client import APIClient
from translators.tl_parser import scan_tl_directory, fill_translation
from translators.tl_mode import run_tl_pipeline


_TL_EMPTY_FIXTURE = """# TODO: Translation updated at 2024-01-01

# game/script.rpy:3
translate chinese hello_001:

    # "Hello"
    ""

# game/script.rpy:4
translate chinese world_002:

    # "World"
    ""
"""


_TL_FILLED_FIXTURE = """# TODO: Translation updated at 2024-01-01

# game/script.rpy:3
translate chinese hello_001:

    # "Hello"
    "你好"

# game/script.rpy:4
translate chinese world_002:

    # "World"
    "世界"
"""


def _build_args(game_dir: Path, output_dir: Path) -> argparse.Namespace:
    """Build the minimal ``argparse.Namespace`` that ``run_tl_pipeline`` consults."""
    return argparse.Namespace(
        game_dir=str(game_dir),
        output_dir=str(output_dir),
        tl_lang="chinese",
        provider="xai",
        api_key="test",
        model="grok",
        rpm=0,
        rps=0,
        timeout=180.0,
        temperature=0.1,
        max_response_tokens=32768,
        max_chunk_tokens=4000,
        genre="adult",
        workers=1,
        dict=[],
        resume=False,
        cot=False,
        tl_screen=False,
        no_clean_rpyc=True,
        font_config="",
        verbose=False,
        custom_module="",
    )


def test_tl_scan_and_fill_cycle() -> None:
    """scan → set translation → fill → write → read-back must preserve content.

    This is the data-layer heart of tl-mode: if this breaks, AI translations
    will never reach disk. Tests the contract between ``scan_tl_directory``,
    ``DialogueEntry.translation``, and ``fill_translation``.
    """
    with tempfile.TemporaryDirectory() as td:
        tl_root = Path(td) / "tl"
        tl_dir = tl_root / "chinese"
        tl_dir.mkdir(parents=True)
        fpath = tl_dir / "dialogue.rpy"
        fpath.write_text(_TL_EMPTY_FIXTURE, encoding="utf-8")

        results = scan_tl_directory(str(tl_root), "chinese")
        assert len(results) == 1, f"expected 1 tl file, got {len(results)}"

        parse_result = results[0]
        assert len(parse_result.dialogues) == 2, (
            f"expected 2 dialogue entries, got {len(parse_result.dialogues)}"
        )
        # Every entry starts untranslated
        for e in parse_result.dialogues:
            assert e.translation == "", f"entry {e.identifier} should start empty"

        # Assign translations by identifier
        entries = list(parse_result.dialogues)
        for e in entries:
            if e.identifier == "hello_001":
                e.translation = "你好"
            elif e.identifier == "world_002":
                e.translation = "世界"
            else:
                raise AssertionError(f"unexpected identifier: {e.identifier}")

        filled_content = fill_translation(str(fpath), entries)
        fpath.write_text(filled_content, encoding="utf-8")

        result = fpath.read_text(encoding="utf-8")
        assert '"你好"' in result, "hello_001 translation not written back"
        assert '"世界"' in result, "world_002 translation not written back"
        # No untranslated slots should remain
        assert '    ""' not in result, "an empty slot was left untouched"
    print("[OK] test_tl_scan_and_fill_cycle")


def test_tl_pipeline_noop_when_fully_translated() -> None:
    """``run_tl_pipeline`` must short-circuit (no API call, no file change)
    when every entry is already translated.

    Guards two invariants: (1) the ``total_untrans == 0`` early-return path
    still works, (2) the pipeline does not spend tokens re-translating already
    completed work.
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        game_dir = td_path / "game"
        tl_dir = game_dir / "tl" / "chinese"
        tl_dir.mkdir(parents=True)
        (tl_dir / "dialogue.rpy").write_text(_TL_FILLED_FIXTURE, encoding="utf-8")
        output_dir = td_path / "out"

        args = _build_args(game_dir, output_dir)

        translate_mock = mock.MagicMock(return_value=[])

        # Mock side-effects we don't want touching disk outside td:
        #   - _apply_tl_game_patches: would try to patch game/gui.rpy
        #   - _inject_language_buttons: same
        #   - APIClient.translate: catch any API attempts as a hard failure
        with (
            mock.patch("translators.tl_mode._apply_tl_game_patches"),
            mock.patch("translators.tl_mode._inject_language_buttons"),
            mock.patch.object(APIClient, "translate", new=translate_mock),
        ):
            run_tl_pipeline(args)

        assert translate_mock.call_count == 0, (
            f"APIClient.translate must not be invoked when all slots filled, "
            f"got {translate_mock.call_count} calls"
        )

        # File content should be untouched (still contains the translations)
        final = (tl_dir / "dialogue.rpy").read_text(encoding="utf-8")
        assert '"你好"' in final
        assert '"世界"' in final
    print("[OK] test_tl_pipeline_noop_when_fully_translated")


if __name__ == "__main__":
    test_tl_scan_and_fill_cycle()
    test_tl_pipeline_noop_when_fully_translated()
    print()
    print("=" * 40)
    print("ALL 2 TL-PIPELINE TESTS PASSED")
    print("=" * 40)
