#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r'''Caller-integration TOCTOU regressions for ``safety/file_safety.py`` users.

r64 T1 fix: split from ``tests/test_file_safety.py`` (was 798 lines, near
the 800-line cap). Helper unit tests stay in ``test_file_safety.py``; the
16 caller-integration regressions across 12 user-facing JSON loader sites
move here (this file ~670 lines, cap-safe).

Mock-target consistency contract preserved: every regression must mock
``safety.file_safety.os.fstat`` (NOT the caller module's ``os.fstat``).
The CI Mock-target consistency check (\.github/workflows/test.yml) treats
this file the same as the original — fragment match ``grep -v file_safety``
already accommodates both filenames sharing the ``file_safety`` substring.

r67 M3 fix: this docstring is a raw triple-single-quoted string. Switching
to triple-single-quoted (rather than triple-double) avoids the meta-issue
where the fix description itself would re-introduce the bug it documents
(mentioning the original triple-double raw form embeds a literal closing
delimiter inside the docstring). The ``r`` prefix silences Python 3.12+
``SyntaxWarning: invalid escape sequence`` for the literal ``\.`` regex
in ``\.github/workflows`` above (becomes ``SyntaxError`` in 3.14).
'''

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================
# Round 49 Step 2 (Commit C4) expansion: TOCTOU regressions for the
# 12 user-facing JSON loader sites (8 modules) that adopted
# check_fstat_size in r49 — mirroring the r48 csv_engine pattern.
#
# Why these tests live HERE (not scattered across 5+ per-module test
# files): the r48 Step 3 audit found 1 CRITICAL where r47's TOCTOU
# regression mocked ``engines.csv_engine.os.fstat`` (the caller
# module) — but after r48 helper extract the actual fstat call lives
# in ``safety.file_safety.os.fstat``, so the mock missed and the test
# spuriously passed.  Centralising r49 expansion regressions in
# this file lets r49+ audits run a SINGLE grep over one file to
# verify every mock target points at ``safety.file_safety.os.fstat``,
# defeating the same trap class.  Two sites (gate / gui_dialogs)
# use lightweight import+constant+source-grep tests because their
# end-to-end fixtures are disproportionately heavy (pipeline gate
# requires complete fixture; gui_dialogs needs tkinter Vars).
# ============================================================


def test_load_font_config_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 1/12): TOCTOU regression for
    core.font_patch.load_font_config.

    Mock target MUST be ``safety.file_safety.os.fstat`` — see r48 Step 3
    CRITICAL fix (commit 34d9707) for the stale-mock-target trap.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.font_patch import load_font_config, _MAX_FONT_CONFIG_SIZE

    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "font_config.json"
        cfg.write_text(_json.dumps({"main_font": "test.ttf"}), encoding="utf-8")

        class FakeStat:
            st_size = _MAX_FONT_CONFIG_SIZE + 1

        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            result = load_font_config(str(cfg))

        assert result == {}, (
            f"check_fstat_size > cap must trigger empty-dict fallback; got {result!r}"
        )
    print("[OK] load_font_config_rejects_toctou_growth_attack")


def test_translation_db_load_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 2/12): TOCTOU regression for
    core.translation_db.TranslationDB.load.

    Mock target MUST be ``safety.file_safety.os.fstat`` — see r48 Step 3.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.translation_db import TranslationDB

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "tr.json"
        db_path.write_text(
            _json.dumps(
                {
                    "version": 2,
                    "entries": [
                        {
                            "file": "a.rpy",
                            "line": 1,
                            "original": "hi",
                            "translation": "你好",
                            "language": "zh",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = TranslationDB._MAX_DB_FILE_SIZE + 1

        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            db = TranslationDB(db_path)
            db.load()

        assert db.entries == [], (
            f"TOCTOU > cap must reject load (empty entries); got {len(db.entries)} entries"
        )
    print("[OK] translation_db_load_rejects_toctou_growth_attack")


def test_load_config_file_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 3/12): TOCTOU regression for
    core.config.Config._load_config_file.

    Mock target MUST be ``safety.file_safety.os.fstat`` — see r48 Step 3.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.config import Config, _MAX_CONFIG_FILE_SIZE

    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "renpy_translate.json"
        cfg.write_text(_json.dumps({"provider": "test_provider_dont_use"}), encoding="utf-8")

        class FakeStat:
            st_size = _MAX_CONFIG_FILE_SIZE + 1

        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            c = Config(game_dir=Path(td), config_path=str(cfg))

        # _file_config stays empty (the cap rejection skips the assignment).
        assert "provider" not in c._file_config, (
            f"TOCTOU > cap must skip config load; got _file_config={c._file_config!r}"
        )
    print("[OK] load_config_file_rejects_toctou_growth_attack")


def test_glossary_actors_json_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 4/12): TOCTOU regression for
    core.glossary.Glossary.scan_rpgmaker_database Actors.json branch.

    Round 50 1b method-name bug fix: r49 C4 wrote ``scan_game_directory``
    which is the Ren'Py .rpy character-define scanner — it does NOT
    read Actors.json.  Actors.json is handled by ``scan_rpgmaker_database``.
    Original test passed for the wrong reason (terms/characters empty
    because the wrong method was called; mock fstat never invoked).
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td)
        data_dir = game_dir / "data"
        data_dir.mkdir()
        actors_path = data_dir / "Actors.json"
        actors_path.write_text(
            _json.dumps(
                [
                    {"name": "Hero", "nickname": "H"},
                ]
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE + 1

        g = Glossary()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.scan_rpgmaker_database(str(game_dir))

        assert g.characters == {}, (
            f"TOCTOU > cap must skip Actors.json; got characters={g.characters!r}"
        )
    print("[OK] glossary_actors_json_rejects_toctou_growth_attack")


def test_glossary_system_json_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 5/12): TOCTOU regression for
    core.glossary.Glossary.scan_rpgmaker_database System.json branch.

    Round 50 1b method-name bug fix: was scan_game_directory (wrong);
    correct method is scan_rpgmaker_database.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td)
        data_dir = game_dir / "data"
        data_dir.mkdir()
        # Empty Actors.json so the Actors branch fast-paths through.
        (data_dir / "Actors.json").write_text(_json.dumps([]), encoding="utf-8")
        system_path = data_dir / "System.json"
        system_path.write_text(
            _json.dumps(
                {
                    "terms": {"basic": ["Attack", "Defend"]},
                }
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE + 1

        g = Glossary()
        before = dict(g.terms)
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.scan_rpgmaker_database(str(game_dir))

        assert g.terms == before, (
            f"TOCTOU > cap must skip System.json; terms changed: {before!r} -> {g.terms!r}"
        )
    print("[OK] glossary_system_json_rejects_toctou_growth_attack")


def test_glossary_load_system_terms_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 6/12): TOCTOU regression for
    core.glossary.Glossary.load_system_terms.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        st = Path(td) / "system_terms.json"
        st.write_text(_json.dumps({"Save": "存档", "Load": "读档"}), encoding="utf-8")

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE + 1

        g = Glossary()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.load_system_terms(str(st))

        assert g.terms == {}, f"TOCTOU > cap must skip system terms load; got terms={g.terms!r}"
    print("[OK] glossary_load_system_terms_rejects_toctou_growth_attack")


def test_glossary_load_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 7/12): TOCTOU regression for
    core.glossary.Glossary.load.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        gp = Path(td) / "glossary.json"
        gp.write_text(
            _json.dumps(
                {
                    "characters": {"hero": "英雄"},
                    "terms": {"hp": "生命值"},
                }
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE + 1

        g = Glossary()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.load(str(gp))

        assert g.characters == {} and g.terms == {}, (
            f"TOCTOU > cap must skip glossary load; got characters="
            f"{g.characters!r}, terms={g.terms!r}"
        )
    print("[OK] glossary_load_rejects_toctou_growth_attack")


def test_glossary_actors_json_accepts_size_at_cap_boundary():
    """Round 50 1b: TOCTOU success-path — file at cap exactly (≤ cap)
    must be accepted; characters dict populated normally (not fallback)."""
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td)
        data_dir = game_dir / "data"
        data_dir.mkdir()
        actors_path = data_dir / "Actors.json"
        actors_path.write_text(
            _json.dumps(
                [
                    {"name": "Hero", "nickname": "H"},
                ]
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE  # exactly at cap

        g = Glossary()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.scan_rpgmaker_database(str(game_dir))

        assert "hero" in g.characters and g.characters["hero"] == "Hero", (
            f"size == cap must allow load; got characters={g.characters!r}"
        )
    print("[OK] glossary_actors_json_accepts_size_at_cap_boundary")


def test_glossary_system_json_accepts_size_at_cap_boundary():
    """Round 50 1b: TOCTOU success-path for System.json branch."""
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td)
        data_dir = game_dir / "data"
        data_dir.mkdir()
        (data_dir / "Actors.json").write_text(_json.dumps([]), encoding="utf-8")
        system_path = data_dir / "System.json"
        system_path.write_text(
            _json.dumps(
                {
                    "terms": {"basic": ["Attack", "Defend"]},
                }
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE  # exactly at cap

        g = Glossary()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.scan_rpgmaker_database(str(game_dir))

        assert "Attack" in g.terms and "Defend" in g.terms, (
            f"size == cap must allow load; got terms={g.terms!r}"
        )
    print("[OK] glossary_system_json_accepts_size_at_cap_boundary")


def test_glossary_load_system_terms_accepts_size_at_cap_boundary():
    """Round 50 1b: TOCTOU success-path for load_system_terms."""
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        st = Path(td) / "system_terms.json"
        st.write_text(_json.dumps({"Save": "存档", "Load": "读档"}), encoding="utf-8")

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE  # exactly at cap

        g = Glossary()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.load_system_terms(str(st))

        assert g.terms == {"Save": "存档", "Load": "读档"}, (
            f"size == cap must allow load; got terms={g.terms!r}"
        )
    print("[OK] glossary_load_system_terms_accepts_size_at_cap_boundary")


def test_glossary_load_accepts_size_at_cap_boundary():
    """Round 50 1b: TOCTOU success-path for Glossary.load."""
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from core.glossary import Glossary, _MAX_GLOSSARY_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        gp = Path(td) / "glossary.json"
        gp.write_text(
            _json.dumps(
                {
                    "characters": {"hero": "英雄"},
                    "terms": {"hp": "生命值"},
                }
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = _MAX_GLOSSARY_JSON_SIZE  # exactly at cap

        g = Glossary()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            g.load(str(gp))

        assert g.characters == {"hero": "英雄"} and g.terms == {"hp": "生命值"}, (
            f"size == cap must allow load; got characters={g.characters!r}, terms={g.terms!r}"
        )
    print("[OK] glossary_load_accepts_size_at_cap_boundary")


def test_gate_glossary_uses_check_fstat_size_pattern():
    """Round 49 Step 2 (C4 site 8/12): lightweight regression for
    pipeline.gate glossary loader.

    Full e2e gate test requires a complete pipeline fixture
    (translated_root, db, metrics, helpers); this test pins the
    structural contract:
      1. pipeline.gate imports check_fstat_size from safety.file_safety
      2. _MAX_GATE_GLOSSARY_SIZE is the 50 MB family cap
      3. Source body uses ``check_fstat_size(f, _MAX_GATE_GLOSSARY_SIZE)``
         and raises OSError on cap violation (per r26 H-4 contract)

    Mock-target stale trap: when a future maintainer adds an end-to-end
    gate test, they MUST mock ``safety.file_safety.os.fstat`` (NOT
    ``pipeline.gate.os.fstat``) — see r48 Step 3 CRITICAL.
    """
    import inspect
    import pipeline.gate as gate_mod

    assert hasattr(gate_mod, "check_fstat_size"), (
        "pipeline.gate must import check_fstat_size from safety.file_safety"
    )
    assert gate_mod._MAX_GATE_GLOSSARY_SIZE == 50 * 1024 * 1024, (
        f"_MAX_GATE_GLOSSARY_SIZE must be 50 MB family cap; got {gate_mod._MAX_GATE_GLOSSARY_SIZE}"
    )

    src = inspect.getsource(gate_mod)
    # Round 49 Step 3 audit-fix (Coverage HIGH): strip comment-only
    # lines so a future maintainer who deletes the with-block but
    # leaves a residual ``# was: check_fstat_size(...)`` comment
    # cannot pass this regression spuriously.
    active_src = "\n".join(line for line in src.split("\n") if not line.lstrip().startswith("#"))
    assert "check_fstat_size(f, _MAX_GATE_GLOSSARY_SIZE)" in active_src, (
        "pipeline.gate must call check_fstat_size on the glossary fd (active code, not a comment)"
    )
    assert "raise OSError" in active_src and "TOCTOU" in active_src, (
        "pipeline.gate must raise OSError on cap violation so the "
        "r26 H-4 except branch logs the gate degradation"
    )
    print("[OK] gate_glossary_uses_check_fstat_size_pattern")


def test_rpgmaker_extract_texts_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 9/12): TOCTOU regression for
    engines.rpgmaker_engine.RPGMakerMVEngine.extract_texts.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from engines.rpgmaker_engine import RPGMakerMVEngine, _MAX_RPGM_JSON_SIZE

    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td)
        data_dir = game_dir / "data"
        data_dir.mkdir()
        # System.json is required for _find_data_dir() to recognise the dir.
        (data_dir / "System.json").write_text(
            _json.dumps(
                {
                    "terms": {"basic": []},
                    "gameTitle": "test",
                }
            ),
            encoding="utf-8",
        )
        # Plus a CommonEvents fixture so extract_texts enters the loader.
        (data_dir / "CommonEvents.json").write_text(
            _json.dumps(
                [
                    None,
                    {"id": 1, "name": "test", "list": []},
                ]
            ),
            encoding="utf-8",
        )

        class FakeStat:
            st_size = _MAX_RPGM_JSON_SIZE + 1

        engine = RPGMakerMVEngine()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            units = engine.extract_texts(game_dir)

        assert units == [], f"TOCTOU > cap must skip every JSON file; got {len(units)} units"
    print("[OK] rpgmaker_extract_texts_rejects_toctou_growth_attack")


def test_rpgmaker_write_back_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 10/12): TOCTOU regression for
    engines.rpgmaker_engine.RPGMakerMVEngine.write_back.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from engines.rpgmaker_engine import RPGMakerMVEngine, _MAX_RPGM_JSON_SIZE
    from engines.engine_base import TranslatableUnit

    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td)
        out_dir = game_dir / "output"
        out_dir.mkdir()
        data_dir = game_dir / "data"
        data_dir.mkdir()
        # System.json is required for _find_data_dir() to recognise the dir.
        (data_dir / "System.json").write_text(
            _json.dumps(
                {
                    "terms": {"basic": []},
                    "gameTitle": "test",
                }
            ),
            encoding="utf-8",
        )
        ce_path = data_dir / "CommonEvents.json"
        ce_path.write_text(
            _json.dumps(
                [
                    None,
                    {
                        "id": 1,
                        "name": "test",
                        "list": [
                            {"code": 401, "indent": 0, "parameters": ["Hello"]},
                        ],
                    },
                ]
            ),
            encoding="utf-8",
        )

        u = TranslatableUnit(
            id="rpgm:CommonEvents:1:0:Hello",
            file_path="data/CommonEvents.json",
            original="Hello",
            translation="你好",
            status="translated",
        )

        class FakeStat:
            st_size = _MAX_RPGM_JSON_SIZE + 1

        engine = RPGMakerMVEngine()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            written = engine.write_back(game_dir, [u], out_dir)

        # write_back must skip the file — no output produced.
        assert written == 0, f"TOCTOU > cap must skip write_back; got written={written}"
        out_ce = out_dir / "data" / "CommonEvents.json"
        assert not out_ce.exists(), (
            f"TOCTOU > cap must NOT write output; output file exists: {out_ce}"
        )
    print("[OK] rpgmaker_write_back_rejects_toctou_growth_attack")


def test_gui_dialogs_load_config_uses_check_fstat_size_pattern():
    """Round 49 Step 2 (C4 site 11/12): lightweight regression for
    gui_dialogs.AppDialogsMixin._load_config.

    Full e2e GUI test would require instantiating App with all
    tkinter Vars; this test pins the structural contract:
      1. gui_dialogs imports check_fstat_size from safety.file_safety
      2. _MAX_GUI_CONFIG_SIZE is the 50 MB family cap
      3. _load_config method body uses the helper

    Mock-target stale trap: future e2e GUI test MUST mock
    ``safety.file_safety.os.fstat`` (NOT ``gui_dialogs.os.fstat``).
    """
    import inspect
    import gui_dialogs

    assert hasattr(gui_dialogs, "check_fstat_size"), (
        "gui_dialogs must import check_fstat_size from safety.file_safety"
    )
    assert gui_dialogs._MAX_GUI_CONFIG_SIZE == 50 * 1024 * 1024, (
        f"_MAX_GUI_CONFIG_SIZE must be 50 MB family cap; got {gui_dialogs._MAX_GUI_CONFIG_SIZE}"
    )

    src = inspect.getsource(gui_dialogs.AppDialogsMixin._load_config)
    # Round 49 Step 3 audit-fix (Coverage HIGH): strip comment-only
    # lines so a comment-residual cannot make this test pass after
    # the active call has been deleted.
    active_src = "\n".join(line for line in src.split("\n") if not line.lstrip().startswith("#"))
    assert "check_fstat_size" in active_src, (
        "_load_config must call check_fstat_size for TOCTOU defense (active code, not a comment)"
    )
    assert "_MAX_GUI_CONFIG_SIZE" in active_src, (
        "_load_config must compare against _MAX_GUI_CONFIG_SIZE (active code, not a comment)"
    )
    print("[OK] gui_dialogs_load_config_uses_check_fstat_size_pattern")


def test_load_ui_button_whitelist_rejects_toctou_growth_attack():
    """Round 49 Step 2 (C4 site 12/12): TOCTOU regression for
    file_processor.checker.load_ui_button_whitelist.
    """
    import json as _json
    import tempfile
    from pathlib import Path
    from unittest import mock
    from file_processor import (
        load_ui_button_whitelist,
        clear_ui_button_whitelist,
        get_ui_button_whitelist_extensions,
    )

    clear_ui_button_whitelist()
    with tempfile.TemporaryDirectory() as td:
        wl_path = Path(td) / "wl.json"
        wl_path.write_text(_json.dumps(["存档", "读档"]), encoding="utf-8")

        # _MAX_UI_WHITELIST_SIZE is local to load_ui_button_whitelist;
        # use the family-canonical 50 MB to compute fake_size.
        family_cap = 50 * 1024 * 1024

        class FakeStat:
            st_size = family_cap + 1

        before = get_ui_button_whitelist_extensions()
        with mock.patch("safety.file_safety.os.fstat", lambda fd: FakeStat()):
            added = load_ui_button_whitelist([str(wl_path)])

        assert added == 0, f"TOCTOU > cap must skip whitelist load; got added={added}"
        after = get_ui_button_whitelist_extensions()
        assert after == before, (
            f"TOCTOU > cap must NOT mutate the whitelist set; before={before!r}, after={after!r}"
        )
    clear_ui_button_whitelist()
    print("[OK] load_ui_button_whitelist_rejects_toctou_growth_attack")


def run_all() -> int:
    """Run every caller-integration TOCTOU regression in this module.

    r64 T1 split: helper unit tests moved to ``tests/test_file_safety.py``.
    This file keeps only the 16 caller-integration regressions across
    the 12 user-facing JSON loader sites + 4 engine/UI sites.
    """
    tests = [
        # Round 49 Step 2 (C4): 12 expansion-site TOCTOU regressions
        test_load_font_config_rejects_toctou_growth_attack,
        test_translation_db_load_rejects_toctou_growth_attack,
        test_load_config_file_rejects_toctou_growth_attack,
        test_glossary_actors_json_rejects_toctou_growth_attack,
        test_glossary_system_json_rejects_toctou_growth_attack,
        test_glossary_load_system_terms_rejects_toctou_growth_attack,
        test_glossary_load_rejects_toctou_growth_attack,
        # Round 50 1b: TOCTOU success-path regressions (glossary 4 callers)
        test_glossary_actors_json_accepts_size_at_cap_boundary,
        test_glossary_system_json_accepts_size_at_cap_boundary,
        test_glossary_load_system_terms_accepts_size_at_cap_boundary,
        test_glossary_load_accepts_size_at_cap_boundary,
        test_gate_glossary_uses_check_fstat_size_pattern,
        test_rpgmaker_extract_texts_rejects_toctou_growth_attack,
        test_rpgmaker_write_back_rejects_toctou_growth_attack,
        test_gui_dialogs_load_config_uses_check_fstat_size_pattern,
        test_load_ui_button_whitelist_rejects_toctou_growth_attack,
    ]
    for t in tests:
        t()
    return len(tests)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} FILE SAFETY LOADER TESTS PASSED")
    print("=" * 40)
