#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for ``translators.direct.translate_file`` (round 22 T-C-3).

Exercises the direct-mode file-level pipeline end-to-end with a mocked
``APIClient.translate`` — no real API call. Covers the happy path and the
resume / skip-done path. Intended to provide regression coverage before the
round 23 refactor of ``translators/direct.py`` (1301 → ~350 + 3 submodules).
"""

from __future__ import annotations

import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.api_client import APIClient, APIConfig
from core.glossary import Glossary
from core.translation_utils import ProgressTracker
from translators.direct import translate_file


_HAPPY_RPY = """label start:
    "Hello world."
    "Second line of dialogue."
    "Third line of dialogue."
    "Fourth line of dialogue."
    return
"""


def _build_client_with_mock(translate_side_effect) -> APIClient:
    """Construct an ``APIClient`` whose ``translate`` method is replaced."""
    config = APIConfig(
        provider="xai",
        api_key="test",
        model="grok",
        max_retries=1,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = APIClient(config)
    client.translate = mock.MagicMock(side_effect=translate_side_effect)
    return client


def test_translate_file_happy_path() -> None:
    """Mocked AI returns complete translations → output file reflects all four lines."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        game_dir = td_path / "game"
        game_dir.mkdir()
        rpy_path = game_dir / "script.rpy"
        rpy_path.write_text(_HAPPY_RPY, encoding="utf-8")
        output_dir = td_path / "out"

        def fake_translate(_system_prompt, _user_prompt):
            return [
                {"line": 2, "original": "Hello world.", "zh": "你好世界。"},
                {"line": 3, "original": "Second line of dialogue.", "zh": "第二行对话。"},
                {"line": 4, "original": "Third line of dialogue.", "zh": "第三行对话。"},
                {"line": 5, "original": "Fourth line of dialogue.", "zh": "第四行对话。"},
            ]

        client = _build_client_with_mock(fake_translate)
        glossary = Glossary()
        progress = ProgressTracker(td_path / "progress.json")

        count, _warnings, checker_dropped, _chunk_stats = translate_file(
            rpy_path=rpy_path,
            game_dir=game_dir,
            output_dir=output_dir,
            client=client,
            glossary=glossary,
            progress=progress,
        )

        assert count >= 4, f"expected >= 4 translations applied, got {count}"
        assert checker_dropped == 0, f"expected no checker drops, got {checker_dropped}"

        out_file = output_dir / "script.rpy"
        assert out_file.exists(), "output file was not written"
        translated = out_file.read_text(encoding="utf-8")
        assert "你好世界。" in translated, "first translation missing from output"
        assert "第二行对话。" in translated, "second translation missing from output"
        assert "第三行对话。" in translated, "third translation missing from output"
        assert "第四行对话。" in translated, "fourth translation missing from output"
        # Original English lines should be fully replaced, not duplicated.
        assert "Hello world." not in translated, "original English leaked into output"
    print("[OK] test_translate_file_happy_path")


def test_translate_file_resume_skips_done() -> None:
    """A file already marked complete in ProgressTracker is a no-op:
    no API call, no output file, 0 translations returned.

    This is the backbone of ``--resume`` behaviour; breaking it would make
    restarts re-translate (and re-pay for) already completed files.
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        game_dir = td_path / "game"
        game_dir.mkdir()
        rpy_path = game_dir / "script.rpy"
        rpy_path.write_text(_HAPPY_RPY, encoding="utf-8")
        output_dir = td_path / "out"

        client = _build_client_with_mock(lambda *_a: [])
        glossary = Glossary()
        progress = ProgressTracker(td_path / "progress.json")
        progress.mark_file_done("script.rpy")  # pretend we've been here before

        count, warnings, checker_dropped, chunk_stats = translate_file(
            rpy_path=rpy_path,
            game_dir=game_dir,
            output_dir=output_dir,
            client=client,
            glossary=glossary,
            progress=progress,
        )

        assert count == 0, f"expected 0 translations for done file, got {count}"
        assert warnings == [], f"expected no warnings, got {warnings}"
        assert checker_dropped == 0
        assert chunk_stats == []
        assert client.translate.call_count == 0, (
            "APIClient.translate must not be invoked for an already-done file"
        )
        assert not (output_dir / "script.rpy").exists(), (
            "done-file short-circuit should not write an output file"
        )
    print("[OK] test_translate_file_resume_skips_done")


if __name__ == "__main__":
    test_translate_file_happy_path()
    test_translate_file_resume_skips_done()
    print()
    print("=" * 40)
    print("ALL 2 DIRECT-PIPELINE TESTS PASSED")
    print("=" * 40)
