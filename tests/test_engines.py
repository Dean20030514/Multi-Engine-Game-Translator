#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎抽象层测试。覆盖 EngineProfile / TranslatableUnit / EngineDetector / RenPyEngine。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================
# EngineProfile 测试
# ============================================================


def test_profile_compile_placeholder_empty():
    """空占位符列表 → None"""
    from engines.engine_base import EngineProfile

    p = EngineProfile(name="test", display_name="Test", placeholder_patterns=[])
    assert p.compile_placeholder_re() is None
    print("[OK] profile_compile_placeholder_empty")


def test_profile_compile_placeholder_single():
    """单模式编译正确"""
    from engines.engine_base import EngineProfile

    p = EngineProfile(name="test", display_name="Test", placeholder_patterns=[r"\[\w+\]"])
    regex = p.compile_placeholder_re()
    assert regex is not None
    assert regex.search("[name]") is not None
    assert regex.search("hello") is None
    print("[OK] profile_compile_placeholder_single")


def test_profile_compile_placeholder_multi():
    """多模式用 | 合并"""
    from engines.engine_base import EngineProfile

    p = EngineProfile(
        name="test", display_name="Test", placeholder_patterns=[r"\[\w+\]", r"\{[^}]+\}"]
    )
    regex = p.compile_placeholder_re()
    assert regex is not None
    assert regex.search("[var]") is not None
    assert regex.search("{tag}") is not None
    assert regex.search("plain") is None
    print("[OK] profile_compile_placeholder_multi")


def test_profile_compile_skip_empty():
    """空 skip 列表 → None"""
    from engines.engine_base import EngineProfile

    p = EngineProfile(name="test", display_name="Test", skip_line_patterns=[])
    assert p.compile_skip_re() is None
    print("[OK] profile_compile_skip_empty")


def test_profile_compile_skip_pattern():
    """skip 模式编译正确"""
    from engines.engine_base import EngineProfile

    p = EngineProfile(
        name="test", display_name="Test", skip_line_patterns=[r"^\s*label\s+", r"^\s*screen\s+"]
    )
    regex = p.compile_skip_re()
    assert regex is not None
    assert regex.search("label start:") is not None
    assert regex.search("    screen main():") is not None
    assert regex.search('    "Hello"') is None
    print("[OK] profile_compile_skip_pattern")


def test_engine_profiles_registry():
    """ENGINE_PROFILES 字典完整性 + rpgmaker_mv/mz 指向同一实例"""
    from engines.engine_base import ENGINE_PROFILES

    assert "renpy" in ENGINE_PROFILES
    assert "rpgmaker_mv" in ENGINE_PROFILES
    assert "rpgmaker_mz" in ENGINE_PROFILES
    assert "csv" in ENGINE_PROFILES
    # MV 和 MZ 指向同一个 Profile 实例
    assert ENGINE_PROFILES["rpgmaker_mv"] is ENGINE_PROFILES["rpgmaker_mz"]
    print("[OK] engine_profiles_registry")


# ============================================================
# TranslatableUnit 测试
# ============================================================


def test_unit_defaults():
    """TranslatableUnit 默认值正确"""
    from engines.engine_base import TranslatableUnit

    u = TranslatableUnit(id="test_001", original="Hello", file_path="test.json")
    assert u.status == "pending"
    assert u.translation == ""
    assert u.context == ""
    assert u.speaker == ""
    assert u.metadata == {}
    print("[OK] unit_defaults")


def test_unit_fields():
    """TranslatableUnit 字段赋值和读取"""
    from engines.engine_base import TranslatableUnit

    u = TranslatableUnit(
        id="map1:ev3",
        original="Welcome!",
        file_path="Map001.json",
        speaker="Guard",
        context="near gate",
        translation="欢迎！",
        status="translated",
        metadata={"code": 401, "idx": 5},
    )
    assert u.id == "map1:ev3"
    assert u.speaker == "Guard"
    assert u.metadata["code"] == 401
    assert u.status == "translated"
    print("[OK] unit_fields")


def test_unit_metadata_roundtrip():
    """metadata round-trip"""
    from engines.engine_base import TranslatableUnit

    meta = {"start_idx": 5, "line_count": 3, "type": "dialogue"}
    u = TranslatableUnit(id="t1", original="hi", file_path="f.json", metadata=meta)
    assert u.metadata is meta  # 同一引用
    u.metadata["extra"] = True
    assert meta["extra"] is True
    print("[OK] unit_metadata_roundtrip")


# ============================================================
# EngineDetector 测试
# ============================================================


def test_detect_renpy():
    """检测 Ren'Py 目录（有 game/*.rpy）"""
    from engines.engine_detector import detect_engine_type, EngineType

    with tempfile.TemporaryDirectory() as d:
        game = Path(d) / "game"
        game.mkdir()
        (game / "script.rpy").write_text("label start:", encoding="utf-8")
        assert detect_engine_type(Path(d)) == EngineType.RENPY
    print("[OK] detect_renpy")


def test_detect_renpy_root():
    """检测 Ren'Py 目录（根目录有 .rpy）"""
    from engines.engine_detector import detect_engine_type, EngineType

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "script.rpy").write_text("label start:", encoding="utf-8")
        assert detect_engine_type(Path(d)) == EngineType.RENPY
    print("[OK] detect_renpy_root")


def test_detect_rpgmaker_mv():
    """检测 RPG Maker MV（www/data/System.json）"""
    from engines.engine_detector import detect_engine_type, EngineType

    with tempfile.TemporaryDirectory() as d:
        data = Path(d) / "www" / "data"
        data.mkdir(parents=True)
        (data / "System.json").write_text("{}", encoding="utf-8")
        assert detect_engine_type(Path(d)) == EngineType.RPGMAKER_MV
    print("[OK] detect_rpgmaker_mv")


def test_detect_rpgmaker_mz():
    """检测 RPG Maker MZ（data/System.json，无 www/）"""
    from engines.engine_detector import detect_engine_type, EngineType

    with tempfile.TemporaryDirectory() as d:
        data = Path(d) / "data"
        data.mkdir()
        (data / "System.json").write_text("{}", encoding="utf-8")
        assert detect_engine_type(Path(d)) == EngineType.RPGMAKER_MV  # MZ 用同一枚举
    print("[OK] detect_rpgmaker_mz")


def test_detect_vxace():
    """检测 RPG Maker VX/Ace（.rgss3a）"""
    from engines.engine_detector import detect_engine_type, EngineType

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "Game.rgss3a").write_bytes(b"\x00")
        assert detect_engine_type(Path(d)) == EngineType.RPGMAKER_VXACE
    print("[OK] detect_vxace")


def test_detect_unknown():
    """未知目录"""
    from engines.engine_detector import detect_engine_type, EngineType

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "readme.txt").write_text("nothing", encoding="utf-8")
        assert detect_engine_type(Path(d)) == EngineType.UNKNOWN
    print("[OK] detect_unknown")


def test_create_engine_renpy():
    """create_engine: RENPY → RenPyEngine 实例"""
    from engines.engine_detector import create_engine, EngineType
    from engines.renpy_engine import RenPyEngine

    engine = create_engine(EngineType.RENPY)
    assert isinstance(engine, RenPyEngine)
    print("[OK] create_engine_renpy")


def test_create_engine_unknown():
    """create_engine: UNKNOWN → None"""
    from engines.engine_detector import create_engine, EngineType

    engine = create_engine(EngineType.UNKNOWN)
    assert engine is None
    print("[OK] create_engine_unknown")


def test_resolve_engine_auto_renpy():
    """resolve_engine: auto + Ren'Py 目录"""
    from engines.engine_detector import resolve_engine
    from engines.renpy_engine import RenPyEngine

    with tempfile.TemporaryDirectory() as d:
        game = Path(d) / "game"
        game.mkdir()
        (game / "script.rpy").write_text("label start:", encoding="utf-8")
        engine = resolve_engine("auto", Path(d))
        assert isinstance(engine, RenPyEngine)
    print("[OK] resolve_engine_auto_renpy")


def test_resolve_engine_manual_renpy():
    """resolve_engine: renpy 显式指定"""
    from engines.engine_detector import resolve_engine
    from engines.renpy_engine import RenPyEngine

    with tempfile.TemporaryDirectory() as d:
        engine = resolve_engine("renpy", Path(d))
        assert isinstance(engine, RenPyEngine)
    print("[OK] resolve_engine_manual_renpy")


# ============================================================
# RenPyEngine 测试
# ============================================================


def test_renpy_engine_detect_true():
    """RenPyEngine.detect: 有 .rpy 返回 True"""
    from engines.renpy_engine import RenPyEngine

    engine = RenPyEngine()
    with tempfile.TemporaryDirectory() as d:
        game = Path(d) / "game"
        game.mkdir()
        (game / "script.rpy").write_text("label start:", encoding="utf-8")
        assert engine.detect(Path(d)) is True
    print("[OK] renpy_engine_detect_true")


def test_renpy_engine_detect_false():
    """RenPyEngine.detect: 无 .rpy 返回 False"""
    from engines.renpy_engine import RenPyEngine

    engine = RenPyEngine()
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "readme.txt").write_text("nothing", encoding="utf-8")
        assert engine.detect(Path(d)) is False
    print("[OK] renpy_engine_detect_false")


def test_renpy_engine_extract_raises():
    """RenPyEngine.extract_texts: 抛 NotImplementedError"""
    from engines.renpy_engine import RenPyEngine

    engine = RenPyEngine()
    try:
        engine.extract_texts(Path("."))
        assert False, "should raise NotImplementedError"
    except NotImplementedError:
        pass
    print("[OK] renpy_engine_extract_raises")


def test_renpy_engine_writeback_raises():
    """RenPyEngine.write_back: 抛 NotImplementedError"""
    from engines.renpy_engine import RenPyEngine

    engine = RenPyEngine()
    try:
        engine.write_back(Path("."), [], Path("."))
        assert False, "should raise NotImplementedError"
    except NotImplementedError:
        pass
    print("[OK] renpy_engine_writeback_raises")


def test_renpy_engine_profile():
    """RenPyEngine.profile.name == 'renpy'"""
    from engines.renpy_engine import RenPyEngine

    engine = RenPyEngine()
    assert engine.profile.name == "renpy"
    assert engine.profile.display_name == "Ren'Py"
    print("[OK] renpy_engine_profile")


# ============================================================
# EngineBase 测试
# ============================================================


def test_engine_base_dry_run():
    """EngineBase.dry_run 默认实现"""
    from engines.engine_base import EngineBase, EngineProfile, TranslatableUnit

    class MockEngine(EngineBase):
        def _default_profile(self):
            return EngineProfile(name="mock", display_name="Mock")

        def detect(self, game_dir):
            return False

        def extract_texts(self, game_dir, **kw):
            return [
                TranslatableUnit(id="1", original="Hello", file_path="a.json"),
                TranslatableUnit(id="2", original="World", file_path="a.json"),
                TranslatableUnit(id="3", original="Test", file_path="b.json"),
            ]

        def write_back(self, game_dir, units, output_dir, **kw):
            return 0

    engine = MockEngine()
    result = engine.dry_run(Path("."))
    assert result["texts"] == 3
    assert result["files"] == 2
    assert result["total_chars"] == len("Hello") + len("World") + len("Test")
    print("[OK] engine_base_dry_run")


# ============================================================
# generic_pipeline 测试
# ============================================================


def test_build_generic_chunks_single():
    """build_generic_chunks: 30 条 → 1 chunk"""
    from engines.generic_pipeline import build_generic_chunks
    from engines.engine_base import TranslatableUnit

    units = [
        TranslatableUnit(id=f"u{i}", original=f"line {i}", file_path="a.csv") for i in range(25)
    ]
    chunks = build_generic_chunks(units, max_size=30)
    assert len(chunks) == 1
    assert len(chunks[0].units) == 25
    print("[OK] build_generic_chunks_single")


def test_build_generic_chunks_split():
    """build_generic_chunks: 60 条 → 2 chunks"""
    from engines.generic_pipeline import build_generic_chunks
    from engines.engine_base import TranslatableUnit

    units = [
        TranslatableUnit(id=f"u{i}", original=f"line {i}", file_path="a.csv") for i in range(60)
    ]
    chunks = build_generic_chunks(units, max_size=30)
    assert len(chunks) == 2
    assert len(chunks[0].units) + len(chunks[1].units) == 60
    print("[OK] build_generic_chunks_split")


def test_build_generic_chunks_by_file():
    """build_generic_chunks: 按 file_path 分组"""
    from engines.generic_pipeline import build_generic_chunks
    from engines.engine_base import TranslatableUnit

    units = [
        TranslatableUnit(id="a1", original="Hello", file_path="a.csv"),
        TranslatableUnit(id="b1", original="World", file_path="b.csv"),
        TranslatableUnit(id="a2", original="Foo", file_path="a.csv"),
    ]
    chunks = build_generic_chunks(units, max_size=30)
    # a.csv 的 2 条在一个 chunk，b.csv 的 1 条在另一个 chunk
    assert len(chunks) == 2
    print("[OK] build_generic_chunks_by_file")


def test_match_translations_to_units():
    """翻译结果匹配到 TranslatableUnit"""
    from engines.generic_pipeline import _match_translations_to_units
    from engines.engine_base import TranslatableUnit

    units = [
        TranslatableUnit(id="k1", original="Hello", file_path="a.csv"),
        TranslatableUnit(id="k2", original="World", file_path="a.csv"),
    ]
    translations = [
        {"id": "k1", "zh": "你好"},
        {"id": "k2", "zh": "世界"},
    ]
    matched = _match_translations_to_units(translations, units, "zh")
    assert matched == 2
    assert units[0].translation == "你好"
    assert units[0].status == "translated"
    print("[OK] match_translations_to_units")


def test_match_translations_fallback():
    """翻译结果 id 不匹配时按 original fallback"""
    from engines.generic_pipeline import _match_translations_to_units
    from engines.engine_base import TranslatableUnit

    units = [TranslatableUnit(id="k1", original="Hello", file_path="a.csv")]
    translations = [{"id": "wrong_id", "original": "Hello", "zh": "你好"}]
    matched = _match_translations_to_units(translations, units, "zh")
    assert matched == 1
    assert units[0].translation == "你好"
    print("[OK] match_translations_fallback")


# ============================================================
# patcher/checker 参数化测试
# ============================================================


def test_protect_placeholders_custom_patterns():
    """protect_placeholders(patterns=RPG Maker) 正确保护"""
    from file_processor import protect_placeholders

    rpg_patterns = [r"\\V\[\d+\]", r"\\N\[\d+\]"]
    text = r"Hello \V[1], I am \N[2]"
    protected, mapping = protect_placeholders(text, patterns=rpg_patterns)
    assert r"\V[1]" not in protected
    assert "__RENPY_PH_" in protected
    assert len(mapping) == 2
    print("[OK] protect_placeholders_custom_patterns")


def test_protect_placeholders_default_unchanged():
    """protect_placeholders(patterns=None) 行为不变"""
    from file_processor import protect_placeholders

    text = "Hello [name], you have {color=#f00}red{/color} text"
    protected, mapping = protect_placeholders(text)
    assert "[name]" not in protected
    assert "__RENPY_PH_" in protected
    print("[OK] protect_placeholders_default_unchanged")


def test_check_response_item_custom_re():
    """check_response_item(placeholder_re=custom) 使用自定义正则"""
    import re
    from file_processor import check_response_item

    custom_re = re.compile(r"(\\V\[\d+\])")
    # 占位符一致 → 通过
    item_ok = {"original": r"Hi \V[1]", "zh": r"嗨 \V[1]"}
    assert check_response_item(item_ok, placeholder_re=custom_re) == []
    # 占位符缺失 → 不通过
    item_bad = {"original": r"Hi \V[1]", "zh": "嗨"}
    warns = check_response_item(item_bad, placeholder_re=custom_re)
    assert len(warns) > 0
    print("[OK] check_response_item_custom_re")


def test_check_response_item_default_unchanged():
    """check_response_item(placeholder_re=None) 行为不变"""
    from file_processor import check_response_item

    item = {"original": "Hello [name]", "zh": "你好 [name]"}
    assert check_response_item(item) == []
    print("[OK] check_response_item_default_unchanged")


# ============================================================
# prompts addon 测试
# ============================================================


def test_prompt_addon_none():
    """build_system_prompt(engine_profile=None) 零变更"""
    from core.prompts import build_system_prompt

    base = build_system_prompt(genre="adult")
    with_none = build_system_prompt(genre="adult", engine_profile=None)
    assert base == with_none
    print("[OK] prompt_addon_none")


def test_prompt_addon_rpgmaker():
    """build_system_prompt(engine_profile=rpgmaker) 包含 addon"""
    from core.prompts import build_system_prompt
    from engines.engine_base import RPGMAKER_MV_PROFILE

    result = build_system_prompt(genre="adult", engine_profile=RPGMAKER_MV_PROFILE)
    assert "\\V[n]" in result or "RPG Maker" in result
    print("[OK] prompt_addon_rpgmaker")


# ============================================================
# Runner
# ============================================================

if __name__ == "__main__":
    # EngineProfile
    test_profile_compile_placeholder_empty()
    test_profile_compile_placeholder_single()
    test_profile_compile_placeholder_multi()
    test_profile_compile_skip_empty()
    test_profile_compile_skip_pattern()
    test_engine_profiles_registry()
    # TranslatableUnit
    test_unit_defaults()
    test_unit_fields()
    test_unit_metadata_roundtrip()
    # EngineDetector
    test_detect_renpy()
    test_detect_renpy_root()
    test_detect_rpgmaker_mv()
    test_detect_rpgmaker_mz()
    test_detect_vxace()
    test_detect_unknown()
    test_create_engine_renpy()
    test_create_engine_unknown()
    test_resolve_engine_auto_renpy()
    test_resolve_engine_manual_renpy()
    # RenPyEngine
    test_renpy_engine_detect_true()
    test_renpy_engine_detect_false()
    test_renpy_engine_extract_raises()
    test_renpy_engine_writeback_raises()
    test_renpy_engine_profile()
    # EngineBase
    test_engine_base_dry_run()
    # Round 48 Step 5: 21 CSV/JSONL/JSON-specific engine tests moved
    # to tests/test_csv_engine.py to bring this file back under the
    # CLAUDE.md 800-line soft limit (1090 -> 557).  See r48 Step 5
    # split commit + _archive/CHANGELOG_RECENT_r50.md (Round 48
    # audit-tail) for full lessons learned re multi-round drift
    # between "all tests < 800" claim and reality.
    # generic_pipeline
    test_build_generic_chunks_single()
    test_build_generic_chunks_split()
    test_build_generic_chunks_by_file()
    test_match_translations_to_units()
    test_match_translations_fallback()
    # patcher/checker parameterization
    test_protect_placeholders_custom_patterns()
    test_protect_placeholders_default_unchanged()
    test_check_response_item_custom_re()
    test_check_response_item_default_unchanged()
    # prompts addon
    test_prompt_addon_none()
    test_prompt_addon_rpgmaker()
    # Round 40: RPG Maker MV/MZ tests (15) moved to
    # tests/test_engines_rpgmaker.py to bring this file under the
    # CLAUDE.md 800-line soft limit (962 -> 694).

    print()
    print("=" * 40)
    # Note: number = main block test_*() invocations (which equals
    # the ``^def test_`` count in this file).  Round 47 had a brief
    # +1 drift from r46 Step 4 baseline math (49 -> 53 was claimed,
    # actually 48 -> 52 + 1 over-count); r48 Step 1 corrected.
    # Round 48 Step 5: 21 CSV-specific tests extracted to
    # tests/test_csv_engine.py — count drops 57 -> 36 here, with
    # the 21 split tests now reported separately in csv_engine suite.
    print("ALL 36 ENGINE TESTS PASSED")
    print("=" * 40)
