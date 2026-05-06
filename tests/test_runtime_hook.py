#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime-hook emitter tests — split from test_translation_state.py in
round 33 Commit 4 prep to respect the CLAUDE.md 800-line limit.

Covers the round 31 → 33 surface of ``core/runtime_hook_emitter.py``:
emit_runtime_hook, emit_if_requested, default_resources_fonts_dir,
UI whitelist sidecar, font auto-bundle, and gui_overrides.

NOTE: round 32 Subtask C tests (translations.json v1 / v2 schema +
inject_hook.rpy v2 reader markers, ``build_translations_map`` shape
contracts) live in ``tests/test_runtime_hook_v2_schema.py`` after the
round 46 Step 3 soft-limit split — they were extracted byte-identical
to keep both files comfortably below the 800-line limit and to isolate
the v2 schema surface for future schema_version=3 evolution.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_runtime_hook_emit_builds_map_and_copies_template():
    """Round 31 Tier C: ``emit_runtime_hook`` writes a sorted JSON map and
    copies the hook .rpy; only ``status == 'ok'`` entries contribute.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        entries = [
            {
                "file": "a.rpy",
                "line": 1,
                "original": "Hello",
                "translation": "你好",
                "status": "ok",
            },
            {
                "file": "a.rpy",
                "line": 2,
                "original": "World",
                "translation": "世界",
                "status": "ok",
            },
            # status != "ok" must be filtered out
            {
                "file": "a.rpy",
                "line": 3,
                "original": "Fail",
                "translation": "",
                "status": "dropped",
            },
            # missing translation must be filtered
            {"file": "a.rpy", "line": 4, "original": "Empty", "translation": "", "status": "ok"},
            # duplicate original keeps first
            {
                "file": "b.rpy",
                "line": 1,
                "original": "Hello",
                "translation": "别的",
                "status": "ok",
            },
        ]

        json_path, hook_path, count = emit_runtime_hook(out_game, entries)

        assert count == 2, f"expected 2 unique ok entries, got {count}"
        assert json_path.exists() and hook_path.exists()

        # JSON content: sorted keys, Unicode preserved, dedup kept first.
        loaded = _json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded == {"Hello": "你好", "World": "世界"}, f"unexpected map: {loaded!r}"

        # Hook file is a verbatim copy of the template — check a sentinel
        # comment from the template header.
        hook_content = hook_path.read_text(encoding="utf-8")
        assert "Inject Hook" in hook_content
        assert "RENPY_TL_INJECT" in hook_content
        assert "_tl_lookup" in hook_content
    print("[OK] runtime_hook_emit_builds_map_and_copies_template")


def test_runtime_hook_emit_if_requested_respects_flag():
    """Round 31 Tier C: ``emit_if_requested`` is a no-op unless the
    argparse namespace has ``emit_runtime_hook=True``.
    """
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace
    from core.runtime_hook_emitter import emit_if_requested
    from core.translation_db import TranslationDB

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        db = TranslationDB(out_dir / "translation_db.json")
        db.upsert_entry(
            {
                "file": "a.rpy",
                "line": 1,
                "original": "Hello",
                "translation": "你好",
                "status": "ok",
            }
        )

        # Flag off → no files emitted.
        args_off = SimpleNamespace(emit_runtime_hook=False)
        emit_if_requested(args_off, out_dir, db)
        assert not (out_dir / "game" / "translations.json").exists()
        assert not (out_dir / "game" / "zz_tl_inject_hook.rpy").exists()

        # Flag missing entirely → still no-op.
        args_none = SimpleNamespace()
        emit_if_requested(args_none, out_dir, db)
        assert not (out_dir / "game" / "translations.json").exists()

        # Flag on → emit.
        args_on = SimpleNamespace(emit_runtime_hook=True)
        emit_if_requested(args_on, out_dir, db)
        assert (out_dir / "game" / "translations.json").exists()
        assert (out_dir / "game" / "zz_tl_inject_hook.rpy").exists()
    print("[OK] runtime_hook_emit_if_requested_respects_flag")


def test_emit_runtime_hook_writes_ui_sidecar_when_extensions_set():
    """Round 32 Subtask A: ``emit_runtime_hook`` writes a sidecar
    ``ui_button_whitelist.json`` next to ``translations.json`` when
    ``ui_button_extensions`` is non-empty.  File has canonical
    ``{"extensions": [...]}`` shape with sorted tokens.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]

    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        # Deliberately mixed-case / whitespace: emitter must pass through the
        # already-normalised tokens verbatim (the normalisation happens on
        # the Python-side ``add_ui_button_whitelist`` path before we get here).
        emit_runtime_hook(
            out_game,
            entries,
            ui_button_extensions=["存档", "读档", "main hub"],
        )
        sidecar = out_game / "ui_button_whitelist.json"
        assert sidecar.is_file(), "sidecar ui_button_whitelist.json must be emitted"
        data = _json.loads(sidecar.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "extensions" in data
        # Sorted for stable diffs.
        assert data["extensions"] == sorted(["存档", "读档", "main hub"])
        # Primary translations.json + hook still emitted.
        assert (out_game / "translations.json").is_file()
        assert (out_game / "zz_tl_inject_hook.rpy").is_file()
    print("[OK] emit_runtime_hook_writes_ui_sidecar_when_extensions_set")


def test_emit_runtime_hook_skips_ui_sidecar_when_empty():
    """Round 32 Subtask A: empty / None ``ui_button_extensions`` must NOT
    create a sidecar file — default output stays byte-compatible with
    round 31 (translations.json + hook only).
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]

    for ext in (None, [], (), frozenset(), {""}):
        with tempfile.TemporaryDirectory() as td:
            out_game = Path(td) / "game"
            emit_runtime_hook(out_game, entries, ui_button_extensions=ext)
            assert not (out_game / "ui_button_whitelist.json").exists(), (
                f"sidecar must not be created for ui_button_extensions={ext!r}"
            )
            # But translations.json + hook still get emitted.
            assert (out_game / "translations.json").is_file()
            assert (out_game / "zz_tl_inject_hook.rpy").is_file()
    print("[OK] emit_runtime_hook_skips_ui_sidecar_when_empty")


def test_emit_runtime_hook_copies_font_when_path_given():
    """Round 32 Subtask B: ``emit_runtime_hook`` with a valid ``font_path``
    copies the font to ``<output_game>/fonts/tl_inject.ttf`` with bytes
    identical to the source.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Build a synthetic font file so the test doesn't depend on the
        # real ``resources/fonts/`` content (avoids ~10 MB I/O per run).
        fake_font = td_path / "MyFont.ttf"
        fake_font.write_bytes(b"TTF\x00MOCK-FONT-BYTES\x01\x02\x03")

        out_game = td_path / "output" / "game"
        emit_runtime_hook(out_game, entries, font_path=fake_font)

        dst = out_game / "fonts" / "tl_inject.ttf"
        assert dst.is_file(), "bundled font must land at fonts/tl_inject.ttf"
        assert dst.read_bytes() == fake_font.read_bytes()
        # Other artefacts still present.
        assert (out_game / "translations.json").is_file()
        assert (out_game / "zz_tl_inject_hook.rpy").is_file()
    print("[OK] emit_runtime_hook_copies_font_when_path_given")


def test_emit_runtime_hook_skips_font_when_none():
    """Round 32 Subtask B: ``font_path=None`` (default) and ``font_path``
    pointing at a non-existent file must NOT create the fonts directory —
    keeps round 31 default output byte-compatible.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]

    for font in (None, Path("/does/not/exist/font.ttf")):
        with tempfile.TemporaryDirectory() as td:
            out_game = Path(td) / "game"
            emit_runtime_hook(out_game, entries, font_path=font)
            assert not (out_game / "fonts").exists(), (
                f"fonts dir must not exist for font_path={font!r}"
            )
            # Primary artefacts still present.
            assert (out_game / "translations.json").is_file()
            assert (out_game / "zz_tl_inject_hook.rpy").is_file()
    print("[OK] emit_runtime_hook_skips_font_when_none")


def test_emit_runtime_hook_font_same_file_tolerated():
    """Round 32 Subtask B: passing a ``font_path`` that happens to equal the
    destination (e.g. user re-ran the emitter against its own output) must
    not raise ``shutil.SameFileError``.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]

    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        out_game.mkdir(parents=True, exist_ok=True)
        fonts_dir = out_game / "fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)
        same_file = fonts_dir / "tl_inject.ttf"
        same_file.write_bytes(b"MOCK-FONT")

        # Must not raise SameFileError; idempotent success.
        emit_runtime_hook(out_game, entries, font_path=same_file)
        assert same_file.read_bytes() == b"MOCK-FONT"
    print("[OK] emit_runtime_hook_font_same_file_tolerated")


def test_emit_if_requested_resolves_font_from_args_font_file():
    """Round 32 Subtask B: ``emit_if_requested`` resolves the font via
    ``core.font_patch.resolve_font`` (honouring ``args.font_file``) and
    forwards to the emitter so the bundled font appears in the output
    game directory even without a direct kwarg.
    """
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace
    from core.runtime_hook_emitter import emit_if_requested
    from core.translation_db import TranslationDB

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        fake_font = td_path / "CustomFont.ttf"
        fake_font.write_bytes(b"TTF\x00CUSTOM\x04\x05\x06")

        db = TranslationDB(td_path / "translation_db.json")
        db.upsert_entry(
            {
                "file": "a.rpy",
                "line": 1,
                "original": "Hello",
                "translation": "你好",
                "status": "ok",
            }
        )

        args = SimpleNamespace(
            emit_runtime_hook=True,
            font_file=str(fake_font),
        )
        emit_if_requested(args, td_path, db)

        dst = td_path / "game" / "fonts" / "tl_inject.ttf"
        assert dst.is_file()
        assert dst.read_bytes() == fake_font.read_bytes()
    print("[OK] emit_if_requested_resolves_font_from_args_font_file")


def test_emit_gui_overrides_rpy_when_font_config_has_overrides():
    """Round 33 Subtask 2: ``emit_runtime_hook(font_config=...)`` with a
    non-empty ``gui_overrides`` sub-dict produces
    ``zz_tl_inject_gui.rpy`` containing an ``init 999 python:`` block
    that assigns each override and is guarded by ``RENPY_TL_INJECT=1``.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]
    font_config = {
        "gui_overrides": {
            "gui.text_size": 22,
            "gui.name_text_size": 24,
            "gui.interface_text_size": 20.5,
        }
    }

    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        emit_runtime_hook(out_game, entries, font_config=font_config)

        gui_rpy = out_game / "zz_tl_inject_gui.rpy"
        assert gui_rpy.is_file(), "aux gui override .rpy must be emitted"
        content = gui_rpy.read_text(encoding="utf-8")
        assert "init 999 python:" in content
        # Env var guard so deploying the file with the game is safe.
        assert 'os.environ.get("RENPY_TL_INJECT") == "1"' in content
        assert "gui.text_size = 22" in content
        assert "gui.name_text_size = 24" in content
        assert "gui.interface_text_size = 20.5" in content
        # Sorted output for stable diffs.
        idx_interface = content.find("gui.interface_text_size")
        idx_name = content.find("gui.name_text_size")
        idx_text = content.find("gui.text_size")
        assert 0 < idx_interface < idx_name < idx_text
        # Primary artefacts still present.
        assert (out_game / "translations.json").is_file()
        assert (out_game / "zz_tl_inject_hook.rpy").is_file()
    print("[OK] emit_gui_overrides_rpy_when_font_config_has_overrides")


def test_emit_gui_overrides_rpy_skips_when_empty():
    """Round 33 Subtask 2: empty / None / missing ``gui_overrides`` must
    NOT create the aux .rpy — default output stays byte-compatible with
    round 32 when no gui tuning is requested.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]

    for cfg in (
        None,
        {},
        {"gui_overrides": {}},
        {"gui_overrides": None},
        {"no_gui_overrides_key": {"gui.text_size": 22}},
    ):
        with tempfile.TemporaryDirectory() as td:
            out_game = Path(td) / "game"
            emit_runtime_hook(out_game, entries, font_config=cfg)
            assert not (out_game / "zz_tl_inject_gui.rpy").exists(), (
                f"aux gui rpy must not exist for font_config={cfg!r}"
            )
            # Primary artefacts still present.
            assert (out_game / "translations.json").is_file()
            assert (out_game / "zz_tl_inject_hook.rpy").is_file()
    print("[OK] emit_gui_overrides_rpy_skips_when_empty")


def test_emit_gui_overrides_rpy_rejects_unsafe_keys():
    """Round 33 Subtask 2: keys that don't match ``^gui\\.[A-Za-z_]`` must
    be filtered out.  Guards against arbitrary-code injection via a
    malicious ``font_config.json``.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]
    hostile_config = {
        "gui_overrides": {
            # Safe: should land in the output.
            "gui.text_size": 22,
            # Unsafe: statement injection.
            'gui.test; import os; os.system("echo pwn")': 1,
            # Unsafe: not under gui.
            "import sys": 1,
            # Unsafe: expression.
            "gui.text_size + foo": 1,
            # Unsafe: empty.
            "": 99,
            # Unsafe: whitespace.
            "gui.text size": 1,
        }
    }

    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        emit_runtime_hook(out_game, entries, font_config=hostile_config)

        gui_rpy = out_game / "zz_tl_inject_gui.rpy"
        assert gui_rpy.is_file()
        content = gui_rpy.read_text(encoding="utf-8")
        # Only the safe key should appear.
        assert "gui.text_size = 22" in content
        # Attack vectors must NOT have leaked into the generated code.
        # (``import os`` legitimately appears in the env-guard wrapper,
        # so assert on the malicious payloads themselves.)
        assert "os.system" not in content
        assert "import sys" not in content
        assert "echo pwn" not in content
        assert "gui.text_size + foo" not in content
        assert "gui.test;" not in content  # the ``gui.test;`` injection key
        assert "gui.text size" not in content  # whitespace variant
    print("[OK] emit_gui_overrides_rpy_rejects_unsafe_keys")


def test_emit_gui_overrides_rpy_rejects_unsafe_values():
    """Round 33 Subtask 2: non-numeric values (str / list / dict / bool /
    None) must be filtered; bool is rejected even though Python's type
    system says ``isinstance(True, int)``.
    """
    import tempfile
    from pathlib import Path
    from core.runtime_hook_emitter import emit_runtime_hook

    entries = [
        {
            "file": "a.rpy",
            "line": 1,
            "original": "Hello",
            "translation": "你好",
            "status": "ok",
        }
    ]
    mixed_config = {
        "gui_overrides": {
            "gui.text_size": 22,  # ok — int
            "gui.name_text_size": 24.0,  # ok — float
            "gui.choice_text_size": "25",  # reject — str
            "gui.icon_size": [22],  # reject — list
            "gui.nvl_text_size": {"x": 22},  # reject — dict
            "gui.hide_bold": True,  # reject — bool
            "gui.hide_italic": False,  # reject — bool
            "gui.maybe_none": None,  # reject — None
        }
    }

    with tempfile.TemporaryDirectory() as td:
        out_game = Path(td) / "game"
        emit_runtime_hook(out_game, entries, font_config=mixed_config)

        content = (out_game / "zz_tl_inject_gui.rpy").read_text(encoding="utf-8")
        # Numeric values land.
        assert "gui.text_size = 22" in content
        assert "gui.name_text_size = 24.0" in content
        # Everything else is filtered out.
        assert "gui.choice_text_size" not in content
        assert "gui.icon_size" not in content
        assert "gui.nvl_text_size" not in content
        assert "gui.hide_bold" not in content
        assert "gui.hide_italic" not in content
        assert "gui.maybe_none" not in content
    print("[OK] emit_gui_overrides_rpy_rejects_unsafe_values")


def test_emit_if_requested_resolves_font_config():
    """Round 33 Subtask 2: ``emit_if_requested`` reads ``args.font_config``
    path, loads it via ``core.font_patch.load_font_config``, and forwards
    the dict to the emitter so ``zz_tl_inject_gui.rpy`` appears in output.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace
    from core.runtime_hook_emitter import emit_if_requested
    from core.translation_db import TranslationDB

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Write a minimal font_config.json with gui_overrides.
        cfg_path = td_path / "font_config.json"
        cfg_path.write_text(
            _json.dumps({"gui_overrides": {"gui.text_size": 26}}, ensure_ascii=False),
            encoding="utf-8",
        )

        db = TranslationDB(td_path / "translation_db.json")
        db.upsert_entry(
            {
                "file": "a.rpy",
                "line": 1,
                "original": "Hello",
                "translation": "你好",
                "status": "ok",
            }
        )

        args = SimpleNamespace(
            emit_runtime_hook=True,
            font_config=str(cfg_path),
            target_lang="zh",
        )
        emit_if_requested(args, td_path, db)

        gui_rpy = td_path / "game" / "zz_tl_inject_gui.rpy"
        assert gui_rpy.is_file()
        content = gui_rpy.read_text(encoding="utf-8")
        assert "gui.text_size = 26" in content

        # Absent args.font_config → no gui rpy.
        with tempfile.TemporaryDirectory() as td2:
            td2_path = Path(td2)
            db2 = TranslationDB(td2_path / "translation_db.json")
            db2.upsert_entry(
                {
                    "file": "a.rpy",
                    "line": 1,
                    "original": "Hi",
                    "translation": "你好",
                    "status": "ok",
                }
            )
            args_noconfig = SimpleNamespace(
                emit_runtime_hook=True,
                font_config="",
            )
            emit_if_requested(args_noconfig, td2_path, db2)
            assert not (td2_path / "game" / "zz_tl_inject_gui.rpy").exists()
            assert (td2_path / "game" / "translations.json").is_file()
    print("[OK] emit_if_requested_resolves_font_config")


def test_default_resources_fonts_dir_points_to_project_root():
    """Round 32 Commit 1: ``default_resources_fonts_dir`` resolves to
    ``<project_root>/resources/fonts`` regardless of which caller imports it.

    Guards against the round 29 / round 32 class of bug where callers in
    subpackages used ``Path(__file__).parent`` with one too few ``.parent``
    steps and silently fell through to ``resolve_font``'s "fonts dir not
    found" warning branch on source-code runs (the bug only disappeared
    after PyInstaller bundled ``resources/`` at the expected relative path).
    """
    from core.font_patch import default_resources_fonts_dir

    fonts_dir = default_resources_fonts_dir()
    # Must be absolute so callers do not depend on process cwd.
    assert fonts_dir.is_absolute()
    # Must resolve to ``<project_root>/resources/fonts``.
    assert fonts_dir.name == "fonts"
    assert fonts_dir.parent.name == "resources"
    project_root = fonts_dir.parent.parent
    # Sanity: at project root we should see the canonical entry points.
    assert (project_root / "main.py").is_file()
    assert (project_root / "core" / "font_patch.py").is_file()
    # Directory should actually exist in a checked-out tree and contain at
    # least one bundled font (NotoSansSC-Regular.ttf per round 32 layout).
    assert fonts_dir.is_dir()
    ttf_files = list(fonts_dir.glob("*.ttf"))
    assert ttf_files, "resources/fonts/ must contain at least one .ttf"
    print("[OK] default_resources_fonts_dir_points_to_project_root")


def run_all() -> int:
    """Run every runtime-hook test in this module; return test count."""
    tests = [
        # Round 31 Tier C (runtime-hook emitter basics)
        test_runtime_hook_emit_builds_map_and_copies_template,
        test_runtime_hook_emit_if_requested_respects_flag,
        # Round 32 Commit 1 (default_resources_fonts_dir helper)
        test_default_resources_fonts_dir_points_to_project_root,
        # Round 32 Subtask A (UI whitelist sidecar)
        test_emit_runtime_hook_writes_ui_sidecar_when_extensions_set,
        test_emit_runtime_hook_skips_ui_sidecar_when_empty,
        # Round 32 Subtask B (font auto-bundle in emit_runtime_hook)
        test_emit_runtime_hook_copies_font_when_path_given,
        test_emit_runtime_hook_skips_font_when_none,
        test_emit_runtime_hook_font_same_file_tolerated,
        test_emit_if_requested_resolves_font_from_args_font_file,
        # Round 33 Subtask 2 (--font-config → zz_tl_inject_gui.rpy)
        test_emit_gui_overrides_rpy_when_font_config_has_overrides,
        test_emit_gui_overrides_rpy_skips_when_empty,
        test_emit_gui_overrides_rpy_rejects_unsafe_keys,
        test_emit_gui_overrides_rpy_rejects_unsafe_values,
        test_emit_if_requested_resolves_font_config,
        # NOTE: Round 32 Subtask C tests (translations.json v1/v2 schema +
        # inject_hook.rpy v2 markers) live in
        # ``tests/test_runtime_hook_v2_schema.py`` after the round 46 Step 3
        # soft-limit split — see this module's docstring.
        # NOTE: Round 34 Commit 1 ``entry_language_filter`` tests live in
        # ``tests/test_runtime_hook_filter.py`` (kept out of this file to
        # respect the CLAUDE.md 800-line soft limit after round 33's split).
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
