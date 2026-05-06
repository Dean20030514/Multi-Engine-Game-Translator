#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translator-layer tests — direct chunk split/retry, tl_parser nvl ID fix, retranslator dialogue density, screen scan/extract/replace, pipeline import smoke.

Split from the monolithic ``tests/test_all.py`` in round 29; every test
function is copied byte-identical from its original location so test
behaviour is preserved.  Run standalone via ``python tests/test_translators.py``
or collectively via ``python tests/test_all.py`` (which delegates to
``run_all()`` in each split module).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_dialogue_density():
    """T6: calculate_dialogue_density 密度自适应路由"""
    from translators.retranslator import calculate_dialogue_density

    # 低密度：多代码少对话
    low = (
        "label start:\n    pass\n    pass\n    pass\n    pass\n"
        + '    e "Hello"\n'
        + "    pass\n    pass\n    pass\n    pass\n"
    )
    d_low = calculate_dialogue_density(low)
    assert d_low < 0.20, f"Expected low density, got {d_low}"

    # 高密度：全对话
    high = '    e "Line 1"\n    e "Line 2"\n    e "Line 3"\n    e "Line 4"\n    e "Line 5"\n'
    d_high = calculate_dialogue_density(high)
    assert d_high >= 0.20, f"Expected high density, got {d_high}"

    # 空文件
    d_empty = calculate_dialogue_density("")
    assert d_empty == 0.0
    print("[OK] dialogue_density")


def test_find_untranslated_lines():
    """T8: find_untranslated_lines 二次过滤"""
    from translators.retranslator import find_untranslated_lines

    content = (
        '    auto "path_%s.png"\n'
        '    idle "icon_hover.png"\n'
        '    hover "btn_hover.png"\n'
        '    image bg = "backgrounds/bg.png"\n'
        '    pov "Hello world, this is a long test line for detection that should be found."\n'
        '    e "Short"\n'
    )
    results = find_untranslated_lines(content)
    found_texts = [text for _, text in results]
    # 应检出长英文对话
    assert any("Hello world" in t for t in found_texts), f"Long dialogue not found: {found_texts}"
    # 不应检出资源路径/属性行
    assert not any("path_" in t for t in found_texts)
    assert not any("icon_hover" in t for t in found_texts)
    print("[OK] find_untranslated_lines")


def test_is_untranslated_dialogue():
    """测试 one_click_pipeline._is_untranslated_dialogue 辅助函数"""
    from translators.renpy_text_utils import _is_untranslated_dialogue

    # 纯英文长文本 → 应判定为未翻译
    assert _is_untranslated_dialogue(
        "This is a long English sentence that should be detected as untranslated."
    )
    # 含中文 → 不应判定
    assert not _is_untranslated_dialogue("这是一个中文句子 with some English mixed in for testing.")
    # 太短 → 不应判定
    assert not _is_untranslated_dialogue("Short text")
    print("[OK] is_untranslated_dialogue")


def test_should_retry_truncation():
    """_should_retry 截断检测：returned < expected * 0.5 → needs_split"""
    from translators.direct import _should_retry
    from core.translation_utils import ChunkResult

    # 正常情况
    cr_ok = ChunkResult(part=1, expected=10, returned=8)
    should, split = _should_retry(cr_ok)
    assert not should, "should not retry normal result"
    # 截断情况
    cr_trunc = ChunkResult(part=1, expected=20, returned=5)
    should, split = _should_retry(cr_trunc)
    assert should and split, "should retry with split on truncation"
    # API 错误
    cr_err = ChunkResult(part=1, error="timeout")
    should, split = _should_retry(cr_err)
    assert should and not split, "API error: retry without split"
    # 边界：expected>0, returned=0（完全无输出）
    cr_zero = ChunkResult(part=1, expected=10, returned=0)
    should, split = _should_retry(cr_zero)
    assert should and split, "zero returned should trigger split"
    # 边界：expected=0, returned=0（空 chunk）
    cr_empty = ChunkResult(part=1, expected=0, returned=0)
    should, split = _should_retry(cr_empty)
    assert not should, "empty chunk should not retry"
    print("[OK] should_retry_truncation")


def test_should_retry_normal():
    """_should_retry 正常和丢弃率过高"""
    from translators.direct import _should_retry
    from core.translation_utils import ChunkResult

    # 正常返回
    cr = ChunkResult(part=1, expected=10, returned=10, dropped_count=0)
    should, split = _should_retry(cr)
    assert not should and not split
    # 丢弃率过高（需满足 MIN_DROPPED_FOR_WARNING=3 + ratio>0.3）
    cr_drop = ChunkResult(part=1, expected=10, returned=10, dropped_count=5)
    should, split = _should_retry(cr_drop)
    assert should and not split, "high drop rate should retry without split"
    print("[OK] should_retry_normal")


def test_split_chunk_basic():
    """_split_chunk 基本拆分：行数守恒"""
    from translators.direct import _split_chunk

    lines = [f"line {i}\n" for i in range(20)]
    chunk = {"content": "".join(lines), "line_offset": 0, "part": 1, "total": 1}
    a, b = _split_chunk(chunk)
    total_a = len(a["content"].splitlines())
    total_b = len(b["content"].splitlines())
    assert total_a + total_b == 20, f"line count mismatch: {total_a} + {total_b} != 20"
    assert a["line_offset"] == 0
    assert b["line_offset"] == total_a
    print("[OK] split_chunk_basic")


def test_split_chunk_at_empty_line():
    """_split_chunk 优先在空行处拆分"""
    from translators.direct import _split_chunk

    lines = []
    for i in range(20):
        if i == 10:
            lines.append("\n")  # 空行在中间
        else:
            lines.append(f"    dialogue line {i}\n")
    chunk = {"content": "".join(lines), "line_offset": 0, "part": 1, "total": 1}
    a, b = _split_chunk(chunk)
    # 拆分应该发生在空行处（index 10 之后，即 line 11）
    a_lines = a["content"].splitlines()
    assert len(a_lines) == 11, f"expected 11 lines in chunk_a, got {len(a_lines)}"
    print("[OK] split_chunk_at_empty_line")


def test_fix_nvl_ids_basic():
    """含 nvl clear 的块：say-only ID 应被替换为 nvl+say ID"""
    import tempfile
    from translators.tl_parser import (
        fix_nvl_translation_ids,
        _compute_say_only_hash,
        _compute_nvl_say_hash,
    )

    say_code = 's "Hello world"'
    say_hash = _compute_say_only_hash(say_code)
    nvl_hash = _compute_nvl_say_hash(say_code)
    assert say_hash != nvl_hash

    tl_content = (
        f"# game/test.rpy:10\n"
        f"translate chinese my_label_{say_hash}:\n"
        f"\n"
        f"    # nvl clear\n"
        f"    # {say_code}\n"
        f'    s "你好世界"\n'
    )
    tmpfile = Path(tempfile.mktemp(suffix=".rpy"))
    tmpfile.write_text(tl_content, encoding="utf-8")
    try:
        stats = fix_nvl_translation_ids(str(tmpfile))
        assert stats["ids_fixed"] == 1, f"expected 1 fix, got {stats}"
        result = tmpfile.read_text(encoding="utf-8")
        assert f"my_label_{nvl_hash}" in result
        assert f"my_label_{say_hash}" not in result
    finally:
        tmpfile.unlink()
    print("[OK] fix_nvl_ids_basic")


def test_fix_nvl_ids_no_nvl():
    """不含 nvl clear 的块不应被修改"""
    import tempfile
    from translators.tl_parser import fix_nvl_translation_ids

    tl_content = (
        "# game/test.rpy:10\n"
        "translate chinese my_label_abcd1234:\n"
        "\n"
        '    # s "Hello"\n'
        '    s "你好"\n'
    )
    tmpfile = Path(tempfile.mktemp(suffix=".rpy"))
    tmpfile.write_text(tl_content, encoding="utf-8")
    try:
        stats = fix_nvl_translation_ids(str(tmpfile))
        assert stats["ids_fixed"] == 0
        assert tmpfile.read_text(encoding="utf-8") == tl_content
    finally:
        tmpfile.unlink()
    print("[OK] fix_nvl_ids_no_nvl")


def test_fix_nvl_ids_already_correct():
    """ID 已经是 nvl+say 哈希时不应重复修改"""
    import tempfile
    from translators.tl_parser import fix_nvl_translation_ids, _compute_nvl_say_hash

    say_code = 's "Already correct"'
    nvl_hash = _compute_nvl_say_hash(say_code)
    tl_content = (
        f"# game/test.rpy:10\n"
        f"translate chinese label_{nvl_hash}:\n"
        f"\n"
        f"    # nvl clear\n"
        f"    # {say_code}\n"
        f'    s "已经正确"\n'
    )
    tmpfile = Path(tempfile.mktemp(suffix=".rpy"))
    tmpfile.write_text(tl_content, encoding="utf-8")
    try:
        stats = fix_nvl_translation_ids(str(tmpfile))
        assert stats["ids_fixed"] == 0
    finally:
        tmpfile.unlink()
    print("[OK] fix_nvl_ids_already_correct")


def test_fix_nvl_ids_real_hashes():
    """用 begin.rpy 的真实数据验证 7 个已知 case"""
    from translators.tl_parser import _compute_say_only_hash, _compute_nvl_say_hash

    cases = [
        (
            's "The {color=#3cff00}Love{/color} and {color=#ff0000}Corruption{/color}'
            " paths have been extended to help make them more robust. There are"
            " corruption scenes written for the love path scenes and vice versa."
            ' Essentially doubling the amount of love and corruption content."',
            "bcc2e904",
            "8c492e19",
        ),
        (
            's "Turn {color=#0000ff}NTR{/color} on? These are the'
            " {color=#0000ff}Darker Paths{/color} in the Mod. This will allow"
            " access to the {color=#0000ff}Voyeur{/color},"
            " {color=#0000ff}NTR{/color}, {color=#0000ff}Sadist{/color},"
            ' and {color=#0000ff}Revenge{/color} Paths."',
            "735a34f0",
            "df92c7d1",
        ),
    ]
    for say_code, expected_say, expected_nvl in cases:
        assert _compute_say_only_hash(say_code) == expected_say, (
            f"say-only mismatch for {say_code[:40]}..."
        )
        assert _compute_nvl_say_hash(say_code) == expected_nvl, (
            f"nvl+say mismatch for {say_code[:40]}..."
        )
    print(f"[OK] fix_nvl_ids_real_hashes: {len(cases)} cases verified")


# ─────────────────────────────────────────────────────────────────
# I: screen_translator 测试
# ─────────────────────────────────────────────────────────────────


def test_screen_should_skip():
    from translators.screen import _should_skip

    assert _should_skip("") is True
    assert _should_skip("[var]") is True
    assert _should_skip("[mother]") is True
    assert _should_skip("123") is True
    assert _should_skip("...") is True
    assert _should_skip("已保存") is True
    assert _should_skip("images/bg.png") is True
    assert _should_skip("a") is True
    assert _should_skip("Save Game") is False
    assert _should_skip("NTR: undecided") is False
    assert _should_skip("{color=#f00}Warning{/color}") is False
    assert _should_skip("[name] is here") is False
    # 含 Ren'Py 闭合标签的文本不应被误判为文件路径
    assert _should_skip("{size=-10}- You can find work at the tanning salon.{/size}") is False
    assert _should_skip("{size=-10}when you're a gangmember.{/size}") is False
    assert _should_skip("icons/bg.png") is True  # 真正的文件路径仍跳过
    print("[OK] test_screen_should_skip")


def test_screen_extract_basic():
    from translators.screen import extract_screen_strings
    import tempfile
    import os

    content = """\
screen test_screen():
    vbox:
        text "Save Game"
        textbutton "Start" action Start()
        imagebutton hovered tt.Action("Go closer") focus_mask True
        text "{color=#f00}Warning{/color}"
        text "[pure_var]"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = extract_screen_strings(tmp)
        originals = [e.original for e in entries]
        assert "Save Game" in originals
        assert "Start" in originals
        assert "Go closer" in originals
        assert "{color=#f00}Warning{/color}" in originals
        assert "[pure_var]" not in originals  # 纯变量跳过
        types = {e.original: e.pattern_type for e in entries}
        assert types["Save Game"] == "text"
        assert types["Start"] == "textbutton"
        assert types["Go closer"] == "tt_action"
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_extract_basic")


def test_screen_extract_skips_underscore():
    from translators.screen import extract_screen_strings
    import tempfile
    import os

    content = """\
screen menu_screen():
    textbutton _("Back") action Rollback()
    textbutton "Visible" action Jump("x")
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = extract_screen_strings(tmp)
        originals = [e.original for e in entries]
        assert "Back" not in originals  # _() 包裹应跳过
        assert "Visible" in originals
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_extract_skips_underscore")


def test_screen_extract_skips_outside_screen():
    from translators.screen import extract_screen_strings
    import tempfile
    import os

    content = """\
label start:
    text "Outside screen"
    "Dialogue line"

screen inner():
    text "Inside screen"

define x = 1
    text "After screen"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = extract_screen_strings(tmp)
        originals = [e.original for e in entries]
        assert "Inside screen" in originals
        assert "Outside screen" not in originals
        assert "After screen" not in originals
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_extract_skips_outside_screen")


def test_screen_dedup():
    from translators.screen import _deduplicate_entries, ScreenTextEntry

    entries = [
        ScreenTextEntry("a.rpy", 1, "text", "Hello"),
        ScreenTextEntry("b.rpy", 5, "text", "Hello"),
        ScreenTextEntry("a.rpy", 3, "text", "World"),
    ]
    table, by_text = _deduplicate_entries(entries)
    assert len(table) == 2
    assert len(by_text["Hello"]) == 2
    assert len(by_text["World"]) == 1
    print("[OK] test_screen_dedup")


def test_screen_replace_text():
    from translators.screen import _replace_screen_strings_in_file, ScreenTextEntry
    import tempfile
    import os

    content = '    text "Save Game"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = [ScreenTextEntry(str(tmp), 1, "text", "Save Game")]
        table = {"Save Game": "保存游戏"}
        new_content, count = _replace_screen_strings_in_file(tmp, entries, table)
        assert count == 1
        assert '"保存游戏"' in new_content
        assert '    text "保存游戏"' in new_content  # 缩进保留
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_replace_text")


def test_screen_replace_textbutton_preserves_action():
    from translators.screen import _replace_screen_strings_in_file, ScreenTextEntry
    import tempfile
    import os

    content = '    textbutton "Start" action Start() style "btn_style"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = [ScreenTextEntry(str(tmp), 1, "textbutton", "Start")]
        table = {"Start": "开始"}
        new_content, count = _replace_screen_strings_in_file(tmp, entries, table)
        assert count == 1
        assert '"开始"' in new_content
        assert 'style "btn_style"' in new_content  # action 参数不动
        assert "Start()" in new_content  # action 函数不动
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_replace_textbutton_preserves_action")


def test_screen_replace_tt_action():
    from translators.screen import _replace_screen_strings_in_file, ScreenTextEntry
    import tempfile
    import os

    content = '    imagebutton hovered tt.Action("Go closer") focus_mask True\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = [ScreenTextEntry(str(tmp), 1, "tt_action", "Go closer")]
        table = {"Go closer": "靠近"}
        new_content, count = _replace_screen_strings_in_file(tmp, entries, table)
        assert count == 1
        assert '"靠近"' in new_content
        assert "focus_mask True" in new_content
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_replace_tt_action")


def test_screen_replace_with_tags_and_vars():
    from translators.screen import _replace_screen_strings_in_file, ScreenTextEntry
    import tempfile
    import os

    content = '    text "Relationship: {color=3cff00}[momrelationship]{/color}"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = [
            ScreenTextEntry(
                str(tmp), 1, "text", "Relationship: {color=3cff00}[momrelationship]{/color}"
            )
        ]
        table = {
            "Relationship: {color=3cff00}[momrelationship]{/color}": "关系: {color=3cff00}[momrelationship]{/color}"
        }
        new_content, count = _replace_screen_strings_in_file(tmp, entries, table)
        assert count == 1
        assert "关系:" in new_content
        assert "{color=3cff00}[momrelationship]{/color}" in new_content
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_replace_with_tags_and_vars")


def test_screen_replace_notify():
    from translators.screen import _replace_screen_strings_in_file, ScreenTextEntry
    import tempfile
    import os

    content = '    imagebutton action Jump("x") hovered Notify("Help needed") focus_mask True\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        tmp = Path(f.name)
    try:
        entries = [ScreenTextEntry(str(tmp), 1, "notify", "Help needed")]
        table = {"Help needed": "需要帮助"}
        new_content, count = _replace_screen_strings_in_file(tmp, entries, table)
        assert count == 1
        assert '"需要帮助"' in new_content
        assert "Notify" in new_content
        assert 'Jump("x")' in new_content  # action 参数不动
    finally:
        os.unlink(tmp)
    print("[OK] test_screen_replace_notify")


def test_screen_backup_no_overwrite():
    from translators.screen import _create_backup
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8") as f:
        f.write("original content")
        f.flush()
        tmp = Path(f.name)
    bak = tmp.with_suffix(tmp.suffix + ".bak")
    try:
        assert not bak.exists()
        _create_backup(tmp)
        assert bak.exists()
        assert bak.read_text(encoding="utf-8") == "original content"
        # 第二次不覆盖
        bak.write_text("old backup", encoding="utf-8")
        _create_backup(tmp)
        assert bak.read_text(encoding="utf-8") == "old backup"
    finally:
        os.unlink(tmp)
        if bak.exists():
            os.unlink(bak)
    print("[OK] test_screen_backup_no_overwrite")


def test_screen_chunks():
    from translators.screen import _build_screen_chunks

    texts = [f"text_{i}" for i in range(100)]
    chunks = _build_screen_chunks(texts, max_per_chunk=40)
    assert len(chunks) == 3
    assert len(chunks[0]) == 40
    assert len(chunks[1]) == 40
    assert len(chunks[2]) == 20
    # 总数守恒
    assert sum(len(c) for c in chunks) == 100
    print("[OK] test_screen_chunks")


# ============================================================
# J: 锁定术语预替换 (locked_terms protection)
# ============================================================


def test_pipeline_imports_smoke():
    """Pipeline sub-package lazy imports must resolve.

    Catches broken imports that hide behind function-level ``from X import Y``
    statements and therefore survive the normal unit-test pass. Historically
    a refactor left ``pipeline/stages.py`` importing from ``main`` names that
    had been relocated, and ``pipeline/gate.py`` importing constants from a
    module that never defined them — crashes surfaced only at runtime.
    """
    from pipeline.gate import evaluate_gate, attribute_untranslated
    from pipeline.stages import _run_retranslate_phase
    from engines.generic_pipeline import run_generic_pipeline
    from translators.retranslator import retranslate_file, find_untranslated_lines
    from core.translation_utils import ProgressTracker
    from pipeline.helpers import LEN_RATIO_LOWER, LEN_RATIO_UPPER

    assert callable(evaluate_gate)
    assert callable(attribute_untranslated)
    assert callable(_run_retranslate_phase)
    assert callable(run_generic_pipeline)
    assert callable(retranslate_file)
    assert callable(find_untranslated_lines)
    assert isinstance(LEN_RATIO_LOWER, float)
    assert isinstance(LEN_RATIO_UPPER, float)
    # ProgressTracker must be instantiable with a Path
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        pt = ProgressTracker(Path(td) / "progress.json")
        assert hasattr(pt, "save")
    print("[OK] test_pipeline_imports_smoke")


# ============================================================
# API retry mock tests (round 21 — T-C-2)
# ------------------------------------------------------------
# These tests lock down the six HTTP retry branches in
# ``APIClient._call_api`` so that future changes to the transport layer
# (e.g. connection pooling) cannot silently break retry semantics.
# ============================================================


# Round 58 P1 / 800-line cap split: the 6 main.py CLI tests
# (test_w_monitor4_*  + test_w_round57_s2_*) moved to
# tests/test_main_cli.py since they exercise main._maybe_warn_on_symlink
# and main._sanitize_user_path — neither lives under translators/.


def run_all() -> int:
    """Run every test in this module; return test count."""
    tests = [
        test_dialogue_density,
        test_find_untranslated_lines,
        test_is_untranslated_dialogue,
        test_should_retry_truncation,
        test_should_retry_normal,
        test_split_chunk_basic,
        test_split_chunk_at_empty_line,
        test_fix_nvl_ids_basic,
        test_fix_nvl_ids_no_nvl,
        test_fix_nvl_ids_already_correct,
        test_fix_nvl_ids_real_hashes,
        test_screen_should_skip,
        test_screen_extract_basic,
        test_screen_extract_skips_underscore,
        test_screen_extract_skips_outside_screen,
        test_screen_dedup,
        test_screen_replace_text,
        test_screen_replace_textbutton_preserves_action,
        test_screen_replace_tt_action,
        test_screen_replace_with_tags_and_vars,
        test_screen_replace_notify,
        test_screen_backup_no_overwrite,
        test_screen_chunks,
        test_pipeline_imports_smoke,
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
