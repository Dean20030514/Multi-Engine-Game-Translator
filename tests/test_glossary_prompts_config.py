#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Glossary / prompts / config tests — Glossary class + dedup + thread safety + Ren'Py scan, locked_terms protect/restore, build_system_prompt per-language, Config CLI/load/validation, lang_config.

Split from the monolithic ``tests/test_all.py`` in round 29; every test
function is copied byte-identical from its original location so test
behaviour is preserved.  Run standalone via ``python tests/test_glossary_prompts_config.py``
or collectively via ``python tests/test_all.py`` (which delegates to
``run_all()`` in each split module).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import glossary
from core import prompts


def test_glossary():
    g = glossary.Glossary()
    g.terms["Save Game"] = "保存游戏"
    g.characters["mc"] = "Main Character"
    g.memory["Hello world"] = "你好世界"
    g._memory_count["Hello world"] = 3  # 信心度 >= 2 才输出到 prompt
    text = g.to_prompt_text()
    assert "mc" in text
    assert "Save Game" in text
    assert "你好世界" in text
    # update_from_translations filtering
    g.update_from_translations(
        [
            {"original": "ab", "zh": "甲"},  # too short, skip
            {"original": "Hello friend", "zh": "Hello friend"},  # same, skip
            {"original": "1234", "zh": "一二三四"},  # digit, skip
            {"original": "Good morning everyone", "zh": "大家早上好"},  # OK
        ]
    )
    assert "ab" not in g.memory
    assert "Good morning everyone" in g.memory
    print("[OK] Glossary")


def test_glossary_dedup():
    """测试术语表去重：已在 terms 中的不重复加入 memory"""
    g = glossary.Glossary()
    g.terms["Save Game"] = "保存游戏"
    g.update_from_translations(
        [
            {"original": "Save Game", "zh": "存档"},  # 已在 terms 中，应跳过
            {"original": "Load Game", "zh": "读取存档"},  # 新的，应加入
        ]
    )
    assert "Save Game" not in g.memory
    assert "Load Game" in g.memory
    print("[OK] glossary dedup")


def test_glossary_thread_safety():
    """测试术语表线程安全"""
    import threading

    g = glossary.Glossary()
    errors = []

    def updater(prefix):
        try:
            for i in range(50):
                g.update_from_translations(
                    [{"original": f"{prefix} text number {i}", "zh": f"{prefix} 文本 {i}"}]
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=updater, args=(f"T{t}",)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    assert len(g.memory) == 200  # 4 threads * 50 entries
    print(f"[OK] glossary thread safety: {len(g.memory)} entries")


def test_glossary_hyphenated_names():
    """连字符人名提取（如 Mary-Jane）"""
    g = glossary.Glossary()
    # 模拟翻译数据：Mary-Jane 出现 4 次，同译名"玛丽-简"
    translations = [
        {"original": f"Mary-Jane says hello {i}", "zh": f"玛丽-简说你好{i}"} for i in range(4)
    ]
    terms = g.extract_terms_from_translations(translations, min_freq=3)
    assert "Mary-Jane" in terms, f"Hyphenated name not extracted: {terms}"
    print("[OK] glossary_hyphenated_names")


def test_glossary_memory_confidence():
    """翻译记忆信心度过滤：出现 1 次的不输出到 prompt"""
    g = glossary.Glossary()
    g.update_from_translations(
        [
            {"original": "A long sentence for testing", "zh": "测试用的长句子"},
        ]
    )
    text = g.to_prompt_text()
    assert "测试用的长句子" not in text, "count=1 should not appear in prompt"
    # 再出现一次，count=2 → 应输出
    g.update_from_translations(
        [
            {"original": "A long sentence for testing", "zh": "测试用的长句子"},
        ]
    )
    text2 = g.to_prompt_text()
    assert "测试用的长句子" in text2, "count=2 should appear in prompt"
    print("[OK] glossary_memory_confidence")


def test_glossary_scan_renpy_directory():
    """``Glossary.scan_game_directory`` must extract ``define NAME = Character(...)``
    and ``define config.name = "..."`` from .rpy files (round 25 T-H-1).

    Previously the RPG Maker branch had targeted coverage via
    ``test_glossary_scan_rpgmaker`` but the Ren'Py regex path had none,
    leaving a silent-break risk: any regression in ``char_re`` /
    ``config_name_re`` would go undetected until a real game is translated.
    """
    import tempfile
    from pathlib import Path
    from core.glossary import Glossary

    fixture = (
        "# game/characters.rpy\n"
        'define mc = Character("Main Hero", color="#c8a")\n'
        'define e = Character("Eileen")\n'
        'define narrator = DynamicCharacter("旁白")\n'
        'define config.name = "Test Game"\n'
        'define config.version = "1.0.0"\n'
    )

    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td) / "game"
        game_dir.mkdir()
        (game_dir / "characters.rpy").write_text(fixture, encoding="utf-8")

        # 放一个应被跳过的 renpy/ 引擎目录文件（不应被扫描）
        renpy_dir = game_dir / "renpy"
        renpy_dir.mkdir()
        (renpy_dir / "engine.rpy").write_text(
            'define engine_internal = Character("Should NOT appear")\n',
            encoding="utf-8",
        )

        g = Glossary()
        g.scan_game_directory(str(game_dir))

        assert g.characters.get("mc") == "Main Hero", (
            f"expected mc → 'Main Hero', got {g.characters.get('mc')!r}"
        )
        assert g.characters.get("e") == "Eileen", (
            f"expected e → 'Eileen', got {g.characters.get('e')!r}"
        )
        assert g.characters.get("narrator") == "旁白", (
            f"expected narrator → '旁白', got {g.characters.get('narrator')!r}"
        )
        # renpy/ 目录应被跳过
        assert "engine_internal" not in g.characters, (
            f"engine file should be skipped, but got: {g.characters}"
        )
        # config.name / config.version 应进入 terms
        assert g.terms.get("__game_name__") == "Test Game", (
            f"expected terms['__game_name__'] = 'Test Game', got {g.terms.get('__game_name__')!r}"
        )
        assert g.terms.get("__game_version__") == "1.0.0", (
            f"expected version 1.0.0, got {g.terms.get('__game_version__')!r}"
        )
    print("[OK] test_glossary_scan_renpy_directory")


def test_locked_terms_protect_basic():
    """locked_terms: basic protection and restore."""
    from file_processor.checker import protect_locked_terms, restore_locked_terms

    terms = {"MyGame": "我的游戏", "Alice": "爱丽丝"}
    text = 'mc "Welcome to MyGame! Alice is here."'
    protected, mapping = protect_locked_terms(text, terms)
    assert "MyGame" not in protected
    assert "Alice" not in protected
    assert "__LOCKED_TERM_" in protected
    assert len(mapping) == 2
    # Restore with Chinese translations
    restored = restore_locked_terms(protected, mapping)
    assert "我的游戏" in restored
    assert "爱丽丝" in restored
    assert "__LOCKED_TERM_" not in restored
    print("[OK] test_locked_terms_protect_basic")


def test_locked_terms_word_boundary():
    """locked_terms: word boundary prevents partial matches."""
    from file_processor.checker import protect_locked_terms

    terms = {"Game": "游戏"}
    text = "GameOver is not the same as Game end"
    protected, mapping = protect_locked_terms(text, terms)
    # "Game" should match "Game end" but NOT "GameOver"
    assert "GameOver" in protected  # not replaced
    assert len(mapping) == 1
    assert "__LOCKED_TERM_0__" in protected
    # Check that "Game end" was partially replaced
    assert "__LOCKED_TERM_0__ end" in protected
    print("[OK] test_locked_terms_word_boundary")


def test_locked_terms_longer_first():
    """locked_terms: longer terms matched first."""
    from file_processor.checker import protect_locked_terms

    terms = {"New York": "纽约", "New": "新"}
    text = "Visit New York and New Orleans"
    protected, mapping = protect_locked_terms(text, terms)
    # "New York" should be matched before "New"
    assert "New York" not in protected
    # mapping[0] should be the "New York" entry
    assert mapping[0][1] == "纽约"
    print("[OK] test_locked_terms_longer_first")


def test_locked_terms_empty():
    """locked_terms: empty terms dict does nothing."""
    from file_processor.checker import protect_locked_terms

    text = "Hello world"
    protected, mapping = protect_locked_terms(text, {})
    assert protected == text
    assert mapping == []
    # Also test with None-value terms
    protected2, mapping2 = protect_locked_terms(text, {"Key": ""})
    assert protected2 == text
    assert mapping2 == []
    print("[OK] test_locked_terms_empty")


def test_locked_terms_no_match():
    """locked_terms: no matching terms in text."""
    from file_processor.checker import protect_locked_terms

    terms = {"NotInText": "不在文中"}
    text = 'mc "Hello world"'
    protected, mapping = protect_locked_terms(text, terms)
    assert protected == text
    assert mapping == []
    print("[OK] test_locked_terms_no_match")


def test_locked_terms_multiple_occurrences():
    """locked_terms: same term appearing multiple times."""
    from file_processor.checker import protect_locked_terms, restore_locked_terms

    terms = {"Alice": "爱丽丝"}
    text = 'Alice said "Hi Alice" to Alice.'
    protected, mapping = protect_locked_terms(text, terms)
    assert protected.count("__LOCKED_TERM_0__") == 3
    restored = restore_locked_terms(protected, mapping)
    assert restored.count("爱丽丝") == 3
    print("[OK] test_locked_terms_multiple_occurrences")


def test_locked_terms_special_chars():
    """locked_terms: terms with regex special characters."""
    from file_processor.checker import protect_locked_terms, restore_locked_terms

    terms = {"C++": "C加加", "Mr.Smith": "史密斯先生"}
    text = "Learn C++ with Mr.Smith today"
    protected, mapping = protect_locked_terms(text, terms)
    restored = restore_locked_terms(protected, mapping)
    assert "C加加" in restored
    assert "史密斯先生" in restored
    print("[OK] test_locked_terms_special_chars")


def test_prompts():
    sp = prompts.build_system_prompt("adult", "## 测试术语表\n- hello → 你好")
    assert "成人" in sp
    assert "测试术语表" in sp
    assert "old" in sp.lower() or "new" in sp.lower()  # translate block handling
    assert "{#" in sp  # menu choice identifier
    up = prompts.build_user_prompt("test.rpy", 'label start:\n    "Hello"')
    assert "test.rpy" in up
    # with chunk_info
    up2 = prompts.build_user_prompt(
        "test.rpy", '"Hello"', {"part": 2, "total": 3, "line_offset": 100}
    )
    assert "2/3" in up2
    assert "101" in up2
    print("[OK] Prompts")


def test_prompt_zh_unchanged():
    """中文 prompt 零变更回归验证 (zh-only since round 52 C4)"""
    from core.prompts import build_system_prompt
    from core.glossary import Glossary

    g = Glossary()
    prompt = build_system_prompt("adult", g.to_prompt_text(), "TestProject")
    baseline = open("tests/zh_prompt_baseline.txt", "r", encoding="utf-8").read()
    assert prompt == baseline, "zh prompt changed!"
    print("[OK] prompt_zh_unchanged")


def test_positive_int_validation():
    """T52: CLI 参数校验函数"""
    from main import _positive_int, _positive_float, _ratio_float
    import argparse

    # 正常值
    assert _positive_int("5") == 5
    assert _positive_float("3.14") == 3.14
    assert _ratio_float("0.5") == 0.5
    # 非法值
    for fn, val in [
        (_positive_int, "0"),
        (_positive_int, "-1"),
        (_positive_float, "0"),
        (_ratio_float, "1.5"),
        (_ratio_float, "0"),
    ]:
        try:
            fn(val)
            assert False, f"应该抛出异常: {fn.__name__}({val})"
        except argparse.ArgumentTypeError:
            pass
    print("[OK] positive_int_validation")


def test_config_load_and_defaults():
    """config.json 加载 + 默认值填充"""
    from pathlib import Path as _Path
    from core.config import Config, DEFAULTS
    import tempfile

    # 无配置文件时使用默认值
    cfg = Config(game_dir=_Path(tempfile.gettempdir()), cli_args=None)
    assert cfg.get("workers") == DEFAULTS["workers"]
    assert cfg.get("rpm") == DEFAULTS["rpm"]
    assert cfg.get("nonexistent", 42) == 42
    assert not cfg.has_config_file()
    print("[OK] config_load_and_defaults")


def test_config_cli_override():
    """CLI 参数覆盖配置文件和默认值"""
    from pathlib import Path as _Path
    from core.config import Config
    import types
    import tempfile

    # ��拟 CLI args
    cli = types.SimpleNamespace(workers=8, rpm=None, rps=None, api_key="")
    cfg = Config(game_dir=_Path(tempfile.gettempdir()), cli_args=cli)
    assert cfg.get("workers") == 8  # CLI 覆盖
    assert cfg.get("rpm") == 60  # CLI=None → 默认值
    print("[OK] config_cli_override")


def test_config_file_load():
    """配置文件正常加载"""
    from pathlib import Path as _Path
    from core.config import Config
    import tempfile
    import os
    import json

    # 创建临时配置文件
    tmpdir = tempfile.mkdtemp()
    cfg_path = _Path(tmpdir) / "renpy_translate.json"
    cfg_path.write_text(json.dumps({"workers": 10, "rpm": 999}), encoding="utf-8")
    try:
        cfg = Config(game_dir=_Path(tmpdir), cli_args=None)
        assert cfg.has_config_file()
        assert cfg.get("workers") == 10
        assert cfg.get("rpm") == 999
        assert cfg.get("rps") == 5  # 配置文件未设置 → 默认值
        print("[OK] config_file_load")
    finally:
        cfg_path.unlink()
        os.rmdir(tmpdir)


def test_config_validation():
    """配置文件 schema 校验：类型/范围/未知键"""
    from pathlib import Path as _Path
    from core.config import Config
    import tempfile
    import os
    import json

    # --- 1. 合法配置无警告 ---
    tmpdir = tempfile.mkdtemp()
    cfg_path = _Path(tmpdir) / "renpy_translate.json"
    cfg_path.write_text(
        json.dumps({"workers": 4, "rpm": 30, "temperature": 0.5, "provider": "openai"}),
        encoding="utf-8",
    )
    try:
        cfg = Config(game_dir=_Path(tmpdir), cli_args=None)
        warns = cfg.validate()
        assert warns == [], f"expected no warnings, got {warns}"
    finally:
        cfg_path.unlink()
        os.rmdir(tmpdir)
    print("[OK] config_validation: valid config")

    # --- 2. 类型错误 ---
    tmpdir = tempfile.mkdtemp()
    cfg_path = _Path(tmpdir) / "renpy_translate.json"
    cfg_path.write_text(json.dumps({"workers": "abc"}), encoding="utf-8")
    try:
        cfg = Config(game_dir=_Path(tmpdir), cli_args=None)
        warns = cfg.validate()
        assert any("类型错误" in w for w in warns), f"expected type error warning, got {warns}"
    finally:
        cfg_path.unlink()
        os.rmdir(tmpdir)
    print("[OK] config_validation: type error")

    # --- 3. 范围越界 ---
    tmpdir = tempfile.mkdtemp()
    cfg_path = _Path(tmpdir) / "renpy_translate.json"
    cfg_path.write_text(json.dumps({"workers": 999}), encoding="utf-8")
    try:
        cfg = Config(game_dir=_Path(tmpdir), cli_args=None)
        warns = cfg.validate()
        assert any("值过大" in w for w in warns), f"expected range warning, got {warns}"
    finally:
        cfg_path.unlink()
        os.rmdir(tmpdir)
    print("[OK] config_validation: range violation")

    # --- 4. 未知键 ---
    tmpdir = tempfile.mkdtemp()
    cfg_path = _Path(tmpdir) / "renpy_translate.json"
    cfg_path.write_text(json.dumps({"totally_unknown_key": 123}), encoding="utf-8")
    try:
        cfg = Config(game_dir=_Path(tmpdir), cli_args=None)
        warns = cfg.validate()
        assert any("未知配置项" in w for w in warns), f"expected unknown key warning, got {warns}"
    finally:
        cfg_path.unlink()
        os.rmdir(tmpdir)
    print("[OK] config_validation: unknown key")


def test_config_file_rejects_oversized():
    """Round 38 M2: ``Config._load_config_file`` skips config.json files
    above the 50 MB cap (via ``stat().st_size`` check before ``json.loads``)
    and falls through to the next search path or defaults.  Bounds memory
    when an operator accidentally points ``--config`` at a huge non-config
    file, or when an attacker-crafted repo ships a bloated config.json.
    """
    import tempfile
    from pathlib import Path
    from core.config import Config

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        big_path = td_path / "renpy_translate.json"
        # 51 MB sparse file — stat() reports 51 MB, actual disk use ~0
        # on NTFS / ext4.  The size gate fires before the read.
        with open(big_path, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        # CLI explicit path points at the oversized file → skip + defaults.
        cfg = Config(game_dir=td_path, config_path=str(big_path))
        # On oversized + no fallback config, file_config stays empty and the
        # resolver returns DEFAULTS for any queried key.
        assert cfg._file_config == {}, (
            "M2: oversized config file must be skipped (file_config empty)"
        )
    print("[OK] test_config_file_rejects_oversized")


def test_glossary_load_rejects_oversized():
    """Round 38 M2: ``Glossary.load`` skips oversized glossary JSON files
    above the 50 MB cap (via the module-level ``_json_file_too_large``
    helper).  Legitimate glossaries are a few KB to a few hundred KB even
    at tens of thousands of (en, zh) pairs; 50 MB+ is almost certainly
    malformed or attacker-crafted.  The helper gates all four JSON readers
    in ``core.glossary`` so one load() test exercises the shared path.
    """
    import tempfile
    from pathlib import Path
    from core.glossary import Glossary

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        big_path = td_path / "big_glossary.json"
        with open(big_path, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        g = Glossary()
        # Sanity — starts empty.
        assert g.terms == {}
        g.load(str(big_path))
        # Oversized path → skip.  Glossary still empty (no raise, no parse).
        assert g.terms == {}, "M2: oversized glossary must leave terms empty"
        assert g.characters == {}
    print("[OK] test_glossary_load_rejects_oversized")


def test_w_round58_a1_resolve_args_from_config_fills_defaults():
    """Round 58 A1: resolve_args_from_config fills argparse Namespace
    from a Config file with documented three-layer precedence.

    Verifies the helper that was extracted from main.py inline code
    produces identical behaviour: scalar fields filled from config
    when CLI didn't set them, defaults when neither has it.
    """
    import argparse
    import tempfile
    import json
    from pathlib import Path as _Path
    from core.config import Config, resolve_args_from_config

    with tempfile.TemporaryDirectory() as td:
        td_p = _Path(td)
        cfg_path = td_p / "renpy_translate.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "workers": 8,
                    "rpm": 100,
                    "model": "deepseek-chat",
                    "dict": ["my_dict.csv"],
                }
            ),
            encoding="utf-8",
        )

        # Simulate `args` after argparse: most fields None (CLI didn't set)
        args = argparse.Namespace(
            game_dir=str(td),
            output_dir=None,
            provider=None,
            model=None,
            genre=None,
            workers=None,
            file_workers=None,
            rpm=None,
            rps=None,
            timeout=None,
            temperature=None,
            max_chunk_tokens=None,
            max_response_tokens=None,
            min_dialogue_density=None,
            tl_lang=None,
            dict=None,
            exclude=None,
            ui_button_whitelist=None,
        )

        cfg = Config(game_dir=td_p, cli_args=args)
        resolve_args_from_config(args, cfg)

        # Config-supplied fields: take config values
        assert args.workers == 8, f"workers: {args.workers}"
        assert args.rpm == 100, f"rpm: {args.rpm}"
        assert args.model == "deepseek-chat", f"model: {args.model}"
        assert args.dict == ["my_dict.csv"], f"dict: {args.dict}"
        # Config-missing fields: take helper defaults
        assert args.output_dir == "output"
        assert args.provider == "xai"
        assert args.genre == "adult"
        assert args.timeout == 180.0
        assert args.temperature == 0.1
        # r52 C4 BREAKING: target_lang always "zh"
        assert args.target_lang == "zh"

    print("[OK] w_round58_a1_resolve_args_from_config_fills_defaults")


def test_w_round58_a1_resolve_args_target_lang_hardcoded_zh():
    """Round 58 A1 (r52 C4 BREAKING): target_lang is always "zh" no
    matter what config says — multi-target language was retired."""
    import argparse
    import tempfile
    import json
    from pathlib import Path as _Path
    from core.config import Config, resolve_args_from_config

    with tempfile.TemporaryDirectory() as td:
        td_p = _Path(td)
        cfg_path = td_p / "renpy_translate.json"
        # Adversarial config trying to set non-zh target
        cfg_path.write_text(
            json.dumps({"target_lang": "ja"}),
            encoding="utf-8",
        )

        args = argparse.Namespace(
            game_dir=str(td),
            output_dir=None,
            provider=None,
            model=None,
            genre=None,
            workers=None,
            file_workers=None,
            rpm=None,
            rps=None,
            timeout=None,
            temperature=None,
            max_chunk_tokens=None,
            max_response_tokens=None,
            min_dialogue_density=None,
            tl_lang=None,
            dict=None,
            exclude=None,
            ui_button_whitelist=None,
        )

        cfg = Config(game_dir=td_p, cli_args=args)
        resolve_args_from_config(args, cfg)

        assert args.target_lang == "zh", (
            f"r52 C4 BREAKING contract violated: target_lang={args.target_lang!r}, "
            "must always be 'zh' regardless of config"
        )
    print("[OK] w_round58_a1_resolve_args_target_lang_hardcoded_zh")


def run_all() -> int:
    """Run every test in this module; return test count."""
    tests = [
        test_glossary,
        test_glossary_dedup,
        test_glossary_thread_safety,
        test_glossary_hyphenated_names,
        test_glossary_memory_confidence,
        test_glossary_scan_renpy_directory,
        test_locked_terms_protect_basic,
        test_locked_terms_word_boundary,
        test_locked_terms_longer_first,
        test_locked_terms_empty,
        test_locked_terms_no_match,
        test_locked_terms_multiple_occurrences,
        test_locked_terms_special_chars,
        test_prompts,
        test_prompt_zh_unchanged,
        test_positive_int_validation,
        test_config_load_and_defaults,
        test_config_cli_override,
        test_config_file_load,
        test_config_validation,
        # Round 38 M2: 50 MB size-cap gates on user-supplied JSON paths
        test_config_file_rejects_oversized,
        test_glossary_load_rejects_oversized,
        # Round 58 A1: shared config-resolver helper
        test_w_round58_a1_resolve_args_from_config_fills_defaults,
        test_w_round58_a1_resolve_args_target_lang_hardcoded_zh,
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
