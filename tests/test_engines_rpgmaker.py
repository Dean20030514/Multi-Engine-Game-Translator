#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPG Maker MV / MZ engine tests (split from ``tests/test_engines.py``
in round 40 — one of four pre-existing > 800-line source files flagged
by HANDOFF r39→40 for structural cleanup).

Coverage (byte-identical copies of r12–r19 tests):
  * Detection: MV vs MZ vs non-RPGM
  * Data dir resolution (MV ``www/data`` vs MZ ``data``)
  * Event-command extraction (code 401 dialogue merge, 102 choices,
    405 scroll, 320 name change)
  * Database / System.json extraction
  * Writeback by event-command path + nested JSON-path navigation
  * Glossary auto-scan from ``Actors.json`` / ``System.json``

Moved to this dedicated file so ``tests/test_engines.py`` can stay
under the CLAUDE.md 800-line soft limit (962 → ~731 after the r40
extraction of this block).  RPG Maker is a self-contained engine
slice with its own test helpers (``_make_rpgm_mv_dir`` /
``_make_rpgm_mz_dir``), a clean cut point.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================
# Helpers
# ============================================================


def _make_rpgm_mv_dir(d):
    """创建最小 RPG Maker MV 目录结构。"""
    data = Path(d) / "www" / "data"
    data.mkdir(parents=True)
    (data / "System.json").write_text(
        '{"gameTitle":"TestGame","currencyUnit":"G","terms":{"basic":["Level","HP"],"commands":["Fight","Escape"],"params":["ATK","DEF"],"messages":{"alwaysDash":"Always Dash"}}}',
        encoding="utf-8",
    )
    return data


def _make_rpgm_mz_dir(d):
    """创建最小 RPG Maker MZ 目录结构。"""
    data = Path(d) / "data"
    data.mkdir()
    (data / "System.json").write_text(
        '{"gameTitle":"TestGame","currencyUnit":"G","terms":{"basic":[],"commands":[],"params":[],"messages":{}}}',
        encoding="utf-8",
    )
    return data


# ============================================================
# RPG Maker MV/MZ 测试
# ============================================================


def test_rpgm_detect_mv():
    """RPGMakerMVEngine.detect: MV 目录"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    with tempfile.TemporaryDirectory() as d:
        _make_rpgm_mv_dir(d)
        assert engine.detect(Path(d)) is True
    print("[OK] rpgm_detect_mv")


def test_rpgm_detect_mz():
    """RPGMakerMVEngine.detect: MZ 目录"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    with tempfile.TemporaryDirectory() as d:
        _make_rpgm_mz_dir(d)
        assert engine.detect(Path(d)) is True
    print("[OK] rpgm_detect_mz")


def test_rpgm_detect_false():
    """RPGMakerMVEngine.detect: 非 RPG Maker 目录"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    with tempfile.TemporaryDirectory() as d:
        assert engine.detect(Path(d)) is False
    print("[OK] rpgm_detect_false")


def test_rpgm_find_data_dir():
    """_find_data_dir: MV 和 MZ"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    with tempfile.TemporaryDirectory() as d:
        data = _make_rpgm_mv_dir(d)
        assert RPGMakerMVEngine._find_data_dir(Path(d)) == data
    with tempfile.TemporaryDirectory() as d:
        data = _make_rpgm_mz_dir(d)
        assert RPGMakerMVEngine._find_data_dir(Path(d)) == data
    print("[OK] rpgm_find_data_dir")


def test_rpgm_extract_401_merge():
    """事件指令: 连续 401 合并为一个对话 unit"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    cmds = [
        {"code": 101, "indent": 0, "parameters": ["Actor1", 0, 0, 2]},
        {"code": 401, "indent": 0, "parameters": ["Hello, traveler!"]},
        {"code": 401, "indent": 0, "parameters": ["Welcome to our town."]},
        {"code": 401, "indent": 0, "parameters": ["Please enjoy your stay."]},
        {"code": 0, "indent": 0, "parameters": []},
    ]
    units = engine._extract_event_commands(cmds, "Map001.json", "events[0].pages[0].list")
    assert len(units) == 1
    assert units[0].original == "Hello, traveler!\nWelcome to our town.\nPlease enjoy your stay."
    assert units[0].metadata["line_count"] == 3
    assert units[0].metadata["type"] == "dialogue"
    print("[OK] rpgm_extract_401_merge")


def test_rpgm_extract_102_choices():
    """事件指令: 102 选项提取"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    cmds = [
        {"code": 102, "indent": 0, "parameters": [["Yes", "No", "Maybe"], 0]},
        {"code": 0, "indent": 0, "parameters": []},
    ]
    units = engine._extract_event_commands(cmds, "Map001.json", "events[0].pages[0].list")
    assert len(units) == 3
    assert units[0].original == "Yes"
    assert units[2].original == "Maybe"
    assert units[0].metadata["type"] == "choice"
    print("[OK] rpgm_extract_102_choices")


def test_rpgm_extract_405_scroll():
    """事件指令: 连续 405 滚动文本合并"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    cmds = [
        {"code": 105, "indent": 0, "parameters": [2, False]},
        {"code": 405, "indent": 0, "parameters": ["Once upon a time..."]},
        {"code": 405, "indent": 0, "parameters": ["In a land far away."]},
        {"code": 0, "indent": 0, "parameters": []},
    ]
    units = engine._extract_event_commands(cmds, "Map001.json", "events[0].pages[0].list")
    assert len(units) == 1
    assert "Once upon a time..." in units[0].original
    assert units[0].metadata["code"] == 405
    print("[OK] rpgm_extract_405_scroll")


def test_rpgm_extract_320_name():
    """事件指令: 320 改名"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    cmds = [
        {"code": 320, "indent": 0, "parameters": [1, "Harold"]},
        {"code": 0, "indent": 0, "parameters": []},
    ]
    units = engine._extract_event_commands(cmds, "Map001.json", "events[0].pages[0].list")
    assert len(units) == 1
    assert units[0].original == "Harold"
    assert units[0].metadata["type"] == "name_change"
    print("[OK] rpgm_extract_320_name")


def test_rpgm_extract_database():
    """数据库: Actors.json 提取 name/nickname/profile"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    data = [None, {"id": 1, "name": "Harold", "nickname": "Hero", "profile": "A brave warrior."}]
    units = engine._extract_database(data, "Actors.json", ["name", "nickname", "profile"])
    assert len(units) == 3
    names = {u.original for u in units}
    assert "Harold" in names
    assert "Hero" in names
    assert "A brave warrior." in names
    print("[OK] rpgm_extract_database")


def test_rpgm_extract_system():
    """System.json 提取"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    engine = RPGMakerMVEngine()
    data = {
        "gameTitle": "My Game",
        "currencyUnit": "Gold",
        "armorTypes": ["", "Shield", "Helmet"],
        "terms": {
            "basic": ["Level", "HP"],
            "commands": ["Fight", "Escape"],
            "params": ["ATK"],
            "messages": {"alwaysDash": "Always Dash"},
        },
    }
    units = engine._extract_system(data, "System.json")
    ids = {u.id for u in units}
    assert "System.json:gameTitle" in ids
    assert "System.json:currencyUnit" in ids
    assert "System.json:armorTypes[1]" in ids
    assert "System.json:terms.basic[0]" in ids
    assert "System.json:terms.messages.alwaysDash" in ids
    print("[OK] rpgm_extract_system")


def test_rpgm_writeback_dialogue():
    """回写: 对话块（行数匹配）"""
    from engines.rpgmaker_engine import RPGMakerMVEngine
    from engines.engine_base import TranslatableUnit

    engine = RPGMakerMVEngine()
    data = {
        "events": [
            None,
            {
                "pages": [
                    {
                        "list": [
                            {"code": 101, "parameters": ["Actor1", 0, 0, 2]},
                            {"code": 401, "parameters": ["Hello!"]},
                            {"code": 401, "parameters": ["World!"]},
                            {"code": 0, "parameters": []},
                        ]
                    }
                ]
            },
        ],
    }
    unit = TranslatableUnit(
        id="test",
        original="Hello!\nWorld!",
        file_path="Map001.json",
        translation="你好！\n世界！",
        status="translated",
        metadata={
            "type": "dialogue",
            "code": 401,
            "start_idx": 1,
            "line_count": 2,
            "json_prefix": "events[1].pages[0].list",
        },
    )
    assert engine._patch_unit(data, unit)
    assert data["events"][1]["pages"][0]["list"][1]["parameters"][0] == "你好！"
    assert data["events"][1]["pages"][0]["list"][2]["parameters"][0] == "世界！"
    print("[OK] rpgm_writeback_dialogue")


def test_rpgm_writeback_dialogue_fewer_lines():
    """回写: 翻译行数 < 原行数（补空串）"""
    from engines.rpgmaker_engine import RPGMakerMVEngine
    from engines.engine_base import TranslatableUnit

    engine = RPGMakerMVEngine()
    data = {
        "events": [
            None,
            {
                "pages": [
                    {
                        "list": [
                            {"code": 401, "parameters": ["Line 1"]},
                            {"code": 401, "parameters": ["Line 2"]},
                            {"code": 401, "parameters": ["Line 3"]},
                        ]
                    }
                ]
            },
        ]
    }
    unit = TranslatableUnit(
        id="test",
        original="Line 1\nLine 2\nLine 3",
        file_path="Map.json",
        translation="第一行",
        status="translated",
        metadata={
            "type": "dialogue",
            "code": 401,
            "start_idx": 0,
            "line_count": 3,
            "json_prefix": "events[1].pages[0].list",
        },
    )
    assert engine._patch_unit(data, unit)
    cmds = data["events"][1]["pages"][0]["list"]
    assert cmds[0]["parameters"][0] == "第一行"
    assert cmds[1]["parameters"][0] == ""
    assert cmds[2]["parameters"][0] == ""
    print("[OK] rpgm_writeback_dialogue_fewer_lines")


def test_rpgm_patch_by_json_path():
    """_patch_by_json_path: 嵌套路径赋值"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    data = {"terms": {"basic": ["Level", "HP", "MP"]}}
    assert RPGMakerMVEngine._patch_by_json_path(data, "terms.basic[1]", "生命值")
    assert data["terms"]["basic"][1] == "生命值"
    # 顶层字段
    data2 = {"gameTitle": "Old"}
    assert RPGMakerMVEngine._patch_by_json_path(data2, "gameTitle", "新标题")
    assert data2["gameTitle"] == "新标题"
    print("[OK] rpgm_patch_by_json_path")


def test_rpgm_navigate_to_node():
    """_navigate_to_node: 复杂路径导航"""
    from engines.rpgmaker_engine import RPGMakerMVEngine

    data = {"events": [None, {"pages": [{"list": [{"code": 401}]}]}]}
    result = RPGMakerMVEngine._navigate_to_node(data, "events[1].pages[0].list")
    assert isinstance(result, list)
    assert result[0]["code"] == 401
    print("[OK] rpgm_navigate_to_node")


def test_glossary_scan_rpgmaker():
    """glossary.scan_rpgmaker_database: 从 Actors.json 提取角色名"""
    from core.glossary import Glossary

    g = Glossary()
    with tempfile.TemporaryDirectory() as d:
        data = _make_rpgm_mv_dir(d)
        (data / "Actors.json").write_text(
            '[null, {"id": 1, "name": "Harold", "nickname": "Hero"}]',
            encoding="utf-8",
        )
        g.scan_rpgmaker_database(d)
        assert "harold" in g.characters
        assert "hero" in g.characters
        # System.json terms
        assert len(g.terms) > 0  # Level, HP, Fight, Escape, ATK, DEF
    print("[OK] glossary_scan_rpgmaker")


def test_rpgm_extract_rejects_oversized_json():
    """Round 42 M2 phase-3: ``RPGMakerMVEngine.extract_texts`` skips any
    ``*.json`` file above ``_MAX_RPGM_JSON_SIZE`` (50 MB) with a warning
    rather than letting ``json.loads`` OOM the process.  Legitimate RPG
    Maker MV/MZ data files are in the KB-low-MB range; 50 MB+ is almost
    certainly malformed or adversarial.  Uses a 51 MB sparse file so the
    test runs instantly without consuming disk.
    """
    from engines.rpgmaker_engine import RPGMakerMVEngine

    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "www" / "data"
        data.mkdir(parents=True)
        # Legitimate small System.json so ``_find_data_dir`` succeeds.
        (data / "System.json").write_text('{"gameTitle":"X"}', encoding="utf-8")
        # 51 MB sparse Map001.json — oversized, must be skipped.
        big_map = data / "Map001.json"
        with open(big_map, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        engine = RPGMakerMVEngine()
        units = engine.extract_texts(Path(td))
        # Key invariant: extract_texts returns without raising and no
        # unit originates from the oversized Map001.json (it was skipped
        # before parse).
        for u in units:
            assert "Map001" not in u.file_path, (
                f"M2 phase-3: oversized Map001.json must be skipped, found unit from it: {u}"
            )
    print("[OK] test_rpgm_extract_rejects_oversized_json")


# ============================================================
# Runner
# ============================================================

if __name__ == "__main__":
    test_rpgm_detect_mv()
    test_rpgm_detect_mz()
    test_rpgm_detect_false()
    test_rpgm_find_data_dir()
    test_rpgm_extract_401_merge()
    test_rpgm_extract_102_choices()
    test_rpgm_extract_405_scroll()
    test_rpgm_extract_320_name()
    test_rpgm_extract_database()
    test_rpgm_extract_system()
    test_rpgm_writeback_dialogue()
    test_rpgm_writeback_dialogue_fewer_lines()
    test_rpgm_patch_by_json_path()
    test_rpgm_navigate_to_node()
    test_glossary_scan_rpgmaker()
    # Round 42 — M2 phase-3 oversize cap
    test_rpgm_extract_rejects_oversized_json()

    print()
    print("=" * 40)
    print("ALL 16 RPG MAKER ENGINE TESTS PASSED")
    print("=" * 40)
