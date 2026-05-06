#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tl_parser self-test suite (round 24 A-H-4 split).

Carved out of ``translators/tl_parser.py``. Runs a self-contained battery of
~12 assertion groups against the tl parser: quote extraction, dialogue/string
block parsing, narrator handling, escape sequences, fill_translation edge
cases, and sanitize_translation boundary conditions.

Invoked by ``python -m translators.tl_parser --test`` (via the main block in
tl_parser.py) or directly via ``run_self_tests()``.
"""

from __future__ import annotations

import os
import tempfile


def run_self_tests() -> None:
    """Run the self-test battery. Prints a summary and sets no exit code.

    Failures are counted and reported but do not raise — the function is
    designed to be driven from the tl_parser CLI block.
    """
    from translators.tl_parser import (
        DialogueEntry,
        _sanitize_translation,
        extract_quoted_text,
        fill_translation,
        get_untranslated_entries,
        parse_tl_file,
    )

    passed = 0
    failed = 0

    def _assert(condition: bool, msg: str):
        nonlocal passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}")

    def _write_tmp(text: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8")
        f.write(text)
        f.close()
        return f.name

    print("运行自测...\n")

    # ── 1. extract_quoted_text ──
    print("[1] extract_quoted_text")
    _assert(extract_quoted_text('e ""') == "", "empty string")
    _assert(extract_quoted_text('e "Hello"') == "Hello", "simple text")
    _assert(extract_quoted_text('# e "Thank you"') == "Thank you", "comment text")
    _assert(extract_quoted_text(r'e "Hello \"World\""') == r"Hello \"World\"", "escaped quotes")
    _assert(extract_quoted_text(r'e "path\\to\\file"') == r"path\\to\\file", "escaped backslashes")
    _assert(extract_quoted_text("no quotes here") is None, "no quotes")
    _assert(extract_quoted_text('"Just narration"') == "Just narration", "narration")
    _assert(extract_quoted_text('"unclosed') is None, "unclosed quote")
    _assert(extract_quoted_text('old "First\\nSecond"') == "First\\nSecond", "newline escape")
    print()

    # ── 2. 正常对话块（未翻译 + 已翻译） ──
    print("[2] 对话块解析")
    dlg_text = (
        "# game/script.rpy:95\n"
        "translate chinese start_636ae3f5:\n"
        "\n"
        '    # e "Thank you for taking a look."\n'
        '    e ""\n'
        "\n"
        "# game/script.rpy:98\n"
        "translate chinese start_abcd1234:\n"
        "\n"
        '    # e "This is already translated."\n'
        '    e "这已经翻译过了。"\n'
    )
    p = _write_tmp(dlg_text)
    try:
        r = parse_tl_file(p)
        _assert(len(r.dialogues) == 2, f"expected 2 dialogues, got {len(r.dialogues)}")
        d0 = r.dialogues[0]
        _assert(d0.identifier == "start_636ae3f5", f"id={d0.identifier}")
        _assert(d0.original == "Thank you for taking a look.", f"orig={d0.original}")
        _assert(d0.translation == "", f'trans should be empty, got "{d0.translation}"')
        _assert(d0.character == "e", f"char={d0.character}")
        _assert(d0.source_file == "game/script.rpy", f"src={d0.source_file}")
        _assert(d0.source_line == 95, f"src_line={d0.source_line}")
        _assert(d0.tl_line == 5, f"tl_line={d0.tl_line}")
        _assert(d0.block_start_line == 2, f"block_start={d0.block_start_line}")

        d1 = r.dialogues[1]
        _assert(d1.translation == "这已经翻译过了。", f"trans={d1.translation}")
        _assert(d1.source_line == 98, f"src_line={d1.source_line}")

        ud, us = get_untranslated_entries([r])
        _assert(len(ud) == 1, f"untranslated dialogues: {len(ud)}")
    finally:
        os.unlink(p)
    print()

    # ── 3. 旁白（无 character） ──
    print("[3] 旁白（无 character）")
    nar_text = (
        "# game/script.rpy:10\n"
        "translate chinese narrator_0001:\n"
        "\n"
        '    # "You enter the dark room."\n'
        '    ""\n'
    )
    p = _write_tmp(nar_text)
    try:
        r = parse_tl_file(p)
        _assert(len(r.dialogues) == 1, f"count={len(r.dialogues)}")
        d = r.dialogues[0]
        _assert(d.character == "", f'char should be empty, got "{d.character}"')
        _assert(d.original == "You enter the dark room.", f"orig={d.original}")
        _assert(d.translation == "", "should be untranslated")
    finally:
        os.unlink(p)
    print()

    # ── 4. 字符串块 ──
    print("[4] 字符串块解析")
    str_text = (
        "translate chinese strings:\n"
        "\n"
        "    # game/screens.rpy:281\n"
        '    old "History"\n'
        '    new ""\n'
        "\n"
        "    # game/screens.rpy:283\n"
        '    old "Skip"\n'
        '    new "快进"\n'
        "\n"
        '    old "Save"\n'
        '    new ""\n'
    )
    p = _write_tmp(str_text)
    try:
        r = parse_tl_file(p)
        _assert(len(r.strings) == 3, f"expected 3 strings, got {len(r.strings)}")

        s0 = r.strings[0]
        _assert(s0.old == "History", f"old={s0.old}")
        _assert(s0.new == "", "new should be empty")
        _assert(s0.source_file == "game/screens.rpy", f"src={s0.source_file}")
        _assert(s0.source_line == 281, f"src_line={s0.source_line}")
        _assert(s0.tl_line == 5, f"tl_line={s0.tl_line}")

        s1 = r.strings[1]
        _assert(s1.old == "Skip", f"old={s1.old}")
        _assert(s1.new == "快进", f"new={s1.new}")
        _assert(s1.source_line == 283, f"src_line={s1.source_line}")

        s2 = r.strings[2]
        _assert(s2.source_file == "", "no source comment")
        _assert(s2.source_line == 0, "no source line")

        ud, us = get_untranslated_entries([r])
        _assert(len(us) == 2, f"untranslated strings: {len(us)}")
    finally:
        os.unlink(p)
    print()

    # ── 5. show/hide 跳过 + 复杂块 + python 块 ──
    print("[5] 非 say 跳过 + 复杂块 + python/style 块")
    mixed_text = (
        "# game/script.rpy:10\n"
        "translate chinese show_block:\n"
        "\n"
        "    show eileen happy\n"
        "    with dissolve\n"
        '    # e "Hello there!"\n'
        '    e ""\n'
        "\n"
        "# game/script.rpy:20\n"
        "translate chinese complex_block:\n"
        "\n"
        '    # e "Greetings"\n'
        "    if some_flag:\n"
        '        e "你好"\n'
        "    else:\n"
        '        e "您好"\n'
        "\n"
        "translate chinese python:\n"
        "    pass\n"
        "\n"
        "translate chinese style default:\n"
        '    font "DejaVuSans.ttf"\n'
    )
    p = _write_tmp(mixed_text)
    try:
        r = parse_tl_file(p)
        _assert(len(r.dialogues) == 1, f"expected 1 dialogue, got {len(r.dialogues)}")
        d = r.dialogues[0]
        _assert(d.identifier == "show_block", f"id={d.identifier}")
        _assert(d.original == "Hello there!", f"orig={d.original}")
        _assert(d.translation == "", "should be untranslated")
        _assert(d.character == "e", f"char={d.character}")
        _assert(d.tl_line == 7, f"tl_line={d.tl_line}")
    finally:
        os.unlink(p)
    print()

    # ── 6. fill_translation ──
    print("[6] fill_translation")
    fill_text = (
        "# game/script.rpy:95\n"
        "translate chinese start_636ae3f5:\n"
        "\n"
        '    # e "Hello"\n'
        '    e ""\n'
        "\n"
        "translate chinese strings:\n"
        "\n"
        '    old "Save"\n'
        '    new ""\n'
    )
    p = _write_tmp(fill_text)
    try:
        r = parse_tl_file(p)
        d = r.dialogues[0]
        s = r.strings[0]

        d.translation = "你好"
        s.new = "保存"
        modified = fill_translation(p, [d, s])

        _assert('e "你好"' in modified, "dialogue filled")
        _assert('new "保存"' in modified, "string filled")
        _assert('""' not in modified, "no empty strings left")
    finally:
        os.unlink(p)
    print()

    # ── 7. fill_translation 校验：已修改的行跳过 ──
    print("[7] fill_translation 跳过已修改行")
    skip_text = 'translate chinese strings:\n\n    old "Hello"\n    new "你好"\n'
    p = _write_tmp(skip_text)
    try:
        r = parse_tl_file(p)
        s = r.strings[0]
        _assert(s.new == "你好", "already translated")
        s.new = "哈喽"
        modified = fill_translation(p, [s])
        _assert('new "你好"' in modified, 'should NOT be overwritten (no "" on that line)')
    finally:
        os.unlink(p)
    print()

    # ── 8. 转义引号处理 ──
    print("[8] 转义引号")
    esc_text = (
        "# game/script.rpy:1\n"
        "translate chinese esc_block:\n"
        "\n"
        '    # e "She said \\"hello\\""\n'
        '    e ""\n'
    )
    p = _write_tmp(esc_text)
    try:
        r = parse_tl_file(p)
        _assert(len(r.dialogues) == 1, f"count={len(r.dialogues)}")
        d = r.dialogues[0]
        _assert(d.original == 'She said \\"hello\\"', f"orig={d.original!r}")
        _assert(d.translation == "", "untranslated")
    finally:
        os.unlink(p)
    print()

    # ── 9. extend / nvl 角色 ──
    print("[9] extend / nvl 角色")
    ext_text = (
        "# game/script.rpy:50\n"
        "translate chinese ext_block:\n"
        "\n"
        '    # extend "and goodbye."\n'
        '    extend ""\n'
    )
    p = _write_tmp(ext_text)
    try:
        r = parse_tl_file(p)
        _assert(len(r.dialogues) == 1, f"count={len(r.dialogues)}")
        d = r.dialogues[0]
        _assert(d.character == "extend", f"char={d.character}")
        _assert(d.original == "and goodbye.", f"orig={d.original}")
    finally:
        os.unlink(p)
    print()

    # ── 10. 无 source 注释的对话块 ──
    print("[10] 无 source 注释")
    nosrc_text = 'translate chinese no_source_block:\n\n    # e "No source line."\n    e ""\n'
    p = _write_tmp(nosrc_text)
    try:
        r = parse_tl_file(p)
        d = r.dialogues[0]
        _assert(d.source_file == "", f'src should be empty, got "{d.source_file}"')
        _assert(d.source_line == 0, f"src_line should be 0, got {d.source_line}")
    finally:
        os.unlink(p)
    print()

    # ── 11. _sanitize_translation 边界测试 ──
    print("[11] _sanitize_translation 边界")
    # 无引号 → 原样
    _assert(_sanitize_translation("你好世界") == "你好世界", "plain text unchanged")
    # ASCII 双引号包裹 → 剥离
    _assert(_sanitize_translation('"你好世界"') == "你好世界", "strip ASCII quotes")
    # 弯引号包裹 → 剥离
    _assert(_sanitize_translation("\u201c你好世界\u201d") == "你好世界", "strip curly quotes")
    # 全角引号包裹 → 剥离
    _assert(_sanitize_translation("\uff02你好世界\uff02") == "你好世界", "strip fullwidth quotes")
    # 双层引号 → 循环剥离
    _assert(_sanitize_translation('""你好世界""') == "你好世界", "strip double-layer quotes")
    # 元数据 [ID: xxx] → 清除
    _assert(_sanitize_translation("[ID: abc123] 你好世界") == "你好世界", "strip metadata ID")
    # 元数据 [Char: mc] → 清除
    _assert(_sanitize_translation("[Char: mc] 你好世界") == "你好世界", "strip metadata Char")
    # 内嵌 ASCII 引号 → 转义
    r = _sanitize_translation('他说"你好"')
    _assert('\\"' in r and "他说" in r, f"escape inner quotes: got {r!r}")
    # 单侧残存引号
    _assert(_sanitize_translation('你好世界"') == "你好世界", "strip trailing lone quote")
    _assert(_sanitize_translation('"你好世界') == "你好世界", "strip leading lone quote")
    # 空字符串
    _assert(_sanitize_translation("") == "", "empty string")
    # 纯引号
    _assert(_sanitize_translation('""') == "", "only quotes")
    print()

    # ── 12. fill_translation 边界测试 ──
    print("[12] fill_translation 边界")
    # 正常回填
    ft_text = '    e ""\n'
    p = _write_tmp(ft_text)
    try:
        entry = DialogueEntry(
            identifier="test",
            original="Hello",
            translation="你好",
            character="e",
            source_file="",
            source_line=0,
            tl_file=p,
            tl_line=1,
            block_start_line=0,
        )
        result = fill_translation(p, [entry])
        _assert('"你好"' in result, f"normal fill: got {result!r}")
    finally:
        os.unlink(p)

    # 多个 "" 只替换第一个
    ft_text2 = '    e "" id "test_id"\n'
    p = _write_tmp(ft_text2)
    try:
        entry = DialogueEntry(
            identifier="test",
            original="Hello",
            translation="你好",
            character="e",
            source_file="",
            source_line=0,
            tl_file=p,
            tl_line=1,
            block_start_line=0,
        )
        result = fill_translation(p, [entry])
        _assert(result.count('"你好"') == 1, f"only first empty replaced: {result!r}")
        _assert('"test_id"' in result, f"second quoted preserved: {result!r}")
    finally:
        os.unlink(p)

    # 行号越界 → 跳过（不崩溃）
    ft_text3 = '    e ""\n'
    p = _write_tmp(ft_text3)
    try:
        entry = DialogueEntry(
            identifier="test",
            original="Hello",
            translation="你好",
            character="e",
            source_file="",
            source_line=0,
            tl_file=p,
            tl_line=999,
            block_start_line=0,
        )
        result = fill_translation(p, [entry])
        _assert('""' in result, f"out-of-range skipped: {result!r}")
    finally:
        os.unlink(p)

    # 已有翻译（不含 ""）→ 跳过
    ft_text4 = '    e "已翻译"\n'
    p = _write_tmp(ft_text4)
    try:
        entry = DialogueEntry(
            identifier="test",
            original="Hello",
            translation="新翻译",
            character="e",
            source_file="",
            source_line=0,
            tl_file=p,
            tl_line=1,
            block_start_line=0,
        )
        result = fill_translation(p, [entry])
        _assert('"已翻译"' in result, f"already filled skipped: {result!r}")
        _assert('"新翻译"' not in result, f"should not overwrite: {result!r}")
    finally:
        os.unlink(p)

    # 含缩进和 character 前缀 → 保留
    ft_text5 = '    mc ""\n'
    p = _write_tmp(ft_text5)
    try:
        entry = DialogueEntry(
            identifier="test",
            original="Hello",
            translation="你好",
            character="mc",
            source_file="",
            source_line=0,
            tl_file=p,
            tl_line=1,
            block_start_line=0,
        )
        result = fill_translation(p, [entry])
        _assert(result.startswith('    mc "你好"'), f"indent+character preserved: {result!r}")
    finally:
        os.unlink(p)
    print()

    # ── 汇总 ──
    total = passed + failed
    print(f"\n{'=' * 40}")
    print(f"自测完成: {passed}/{total} 通过", end="")
    if failed:
        print(f", {failed} 失败")
    else:
        print(" OK")


if __name__ == "__main__":
    run_self_tests()
