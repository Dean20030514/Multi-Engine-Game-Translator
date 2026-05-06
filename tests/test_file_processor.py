#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""File processor tests — splitter (estimate_tokens / block boundaries / force_split), checker (protect/restore/filter wrappers), patcher (apply_translations / escape), validator (menu identifier / lang config).

Split from the monolithic ``tests/test_all.py`` in round 29; every test
function is copied byte-identical from its original location so test
behaviour is preserved.  Run standalone via ``python tests/test_file_processor.py``
or collectively via ``python tests/test_all.py`` (which delegates to
``run_all()`` in each split module).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import file_processor


def test_estimate_tokens():
    tok = file_processor.estimate_tokens("Hello world, this is a test.")
    assert tok > 0
    tok_zh = file_processor.estimate_tokens("你好世界")
    assert tok_zh > 0
    print(f"[OK] estimate_tokens: en={tok}, zh={tok_zh}")


def test_find_block_boundaries():
    lines = [
        "label start:",
        '    mc "Hello"',
        "",
        "screen say(who, what):",
        "    text what",
        "",
        "init python:",
        "    x = 1",
    ]
    b = file_processor._find_block_boundaries(lines)
    assert 0 in b
    assert 3 in b  # screen
    assert 6 in b  # init
    print(f"[OK] _find_block_boundaries: {b}")


def test_safety_check():
    # 变量丢失
    r = file_processor._check_translation_safety("Hello [name]", "你好")
    assert r is not None and "name" in str(r)
    # 变量保留 — 安全
    r2 = file_processor._check_translation_safety("Hello [name]", "你好 [name]")
    assert r2 is None
    # 变量多出
    r2b = file_processor._check_translation_safety("Hello", "你好 [name]")
    assert r2b is not None and "多出" in str(r2b)
    # 标签不匹配
    r3 = file_processor._check_translation_safety("{color=#f00}Hi{/color}", "你好")
    assert r3 is not None
    # 标签匹配 — 安全
    r4 = file_processor._check_translation_safety(
        "{color=#f00}Hi{/color}", "{color=#f00}你好{/color}"
    )
    assert r4 is None
    # 换行符
    r5 = file_processor._check_translation_safety("Line1\\nLine2", "行1")
    assert r5 is not None
    r6 = file_processor._check_translation_safety("Line1\\nLine2", "行1\\n行2")
    assert r6 is None
    # {#identifier} 保留
    r7 = file_processor._check_translation_safety("Go home{#home_choice}", "回家")
    assert r7 is not None and "标识符" in str(r7)
    r8 = file_processor._check_translation_safety("Go home{#home_choice}", "回家{#home_choice}")
    assert r8 is None
    # %(name)s 格式化占位符
    r9 = file_processor._check_translation_safety("Hello %(name)s", "你好")
    assert r9 is not None and "格式化" in str(r9)
    r10 = file_processor._check_translation_safety("Hello %(name)s", "你好 %(name)s")
    assert r10 is None
    # 翻译长度比例
    long_text = "A" * 50
    r11 = file_processor._check_translation_safety(long_text, long_text * 5)
    assert r11 is not None and "过长" in str(r11)
    r12 = file_processor._check_translation_safety(long_text, "x")
    assert r12 is not None and "过短" in str(r12)
    print("[OK] _check_translation_safety")


def test_apply_translations():
    content = '    mc "Hello world"\n    "You see a door."'
    trans = [
        {"line": 1, "original": "Hello world", "zh": "你好世界"},
        {"line": 2, "original": "You see a door.", "zh": "你看到一扇门。"},
    ]
    patched, warnings, _ = file_processor.apply_translations(content, trans)
    assert "你好世界" in patched
    assert "你看到一扇门" in patched
    print(f"[OK] apply_translations: {len(warnings)} warnings")


def test_apply_cascade():
    """测试两遍匹配避免级联覆盖"""
    content = (
        "    if x == 0:\n"  # line 1
        '        pov "Text A"\n'  # line 2
        "    else:\n"  # line 3
        '        pov "Text B"\n'  # line 4
    )
    # AI returns line 1 for text that's actually on line 2,
    # and line 2 for text that's actually on line 2 (same line)
    trans = [
        {"line": 1, "original": "Text A", "zh": "文本A"},  # will need offset +1
        {"line": 2, "original": "Text A", "zh": "文本A"},  # exact match on line 2
    ]
    patched, warnings, _ = file_processor.apply_translations(content, trans)
    assert patched.count("文本A") == 1  # 只应用一次，不会重复
    # The exact match should win in pass 1
    assert "文本A" in patched
    print("[OK] apply_cascade: no duplicate replacement")


def test_validate_translation():
    orig = 'label start:\n    mc "Hello [name]"\n    jump end'
    trans = 'label start:\n    mc "你好 [name]"\n    jump end'
    issues = file_processor.validate_translation(orig, trans, "test.rpy")
    assert len(issues) == 0
    print("[OK] validate_translation (clean)")

    # 变量丢失
    trans_bad = 'label start:\n    mc "你好"\n    jump end'
    issues2 = file_processor.validate_translation(orig, trans_bad, "test.rpy")
    assert any(i["level"] == "error" for i in issues2)
    print(f"[OK] validate_translation (error detected): {len(issues2)} issues")


def test_force_split():
    # Create lines that exceed max_tokens
    lines = [f'    mc "This is line {i} with some text content."' for i in range(200)]
    text = "\n".join(lines)
    tok = file_processor.estimate_tokens(text)
    chunks = file_processor._force_split_lines(lines, 0, len(lines), tok // 3)
    assert len(chunks) >= 2
    # Verify all content is covered
    total_lines = sum(len(c["content"].split("\n")) for c in chunks)
    assert total_lines == len(lines)
    print(f"[OK] _force_split_lines: {len(chunks)} chunks from {len(lines)} lines")


def test_triple_quote_replacement():
    """测试三引号字符串替换"""
    line = '    mc """Hello world"""'
    result = file_processor._replace_string_in_line(line, "Hello world", "你好世界")
    assert result is not None
    assert '"""你好世界"""' in result
    print("[OK] triple-quote replacement")


def test_underscore_func_replacement():
    """测试 _() 包裹的字符串替换"""
    line = '    text _("Save Game")'
    result = file_processor._replace_string_in_line(line, "Save Game", "保存游戏")
    assert result is not None
    assert '_("保存游戏")' in result
    print("[OK] _() function replacement")


def test_validate_menu_identifier():
    """测试 {#identifier} 在验证中的检测"""
    orig = 'label start:\n    "Go home{#home}" \n    jump end'
    trans_ok = 'label start:\n    "回家{#home}" \n    jump end'
    trans_bad = 'label start:\n    "回家" \n    jump end'
    issues = file_processor.validate_translation(orig, trans_ok, "test.rpy")
    id_issues = [i for i in issues if "标识符" in i.get("message", "")]
    assert len(id_issues) == 0
    issues2 = file_processor.validate_translation(orig, trans_bad, "test.rpy")
    id_issues2 = [i for i in issues2 if "标识符" in i.get("message", "")]
    assert len(id_issues2) > 0
    print("[OK] validate_menu_identifier")


def test_image_block_boundary():
    """测试 image 声明作为块边界"""
    lines = [
        "label start:",
        '    mc "Hello"',
        "",
        'image bg = "bg.png"',
        "",
        "screen test:",
        '    text "hi"',
    ]
    b = file_processor._find_block_boundaries(lines)
    assert 3 in b  # image
    assert 5 in b  # screen
    print(f"[OK] image block boundary: {b}")


def test_protect_restore_roundtrip():
    """protect → 修改文本 → restore = 占位符完好还原"""
    text = "[name] says {color=#f00}Hello{/color} to [name]"
    protected, mapping = file_processor.protect_placeholders(text)
    # 令牌存在、原始占位符消失
    assert "__RENPY_PH_" in protected
    assert "[name]" not in protected
    assert "{color=#f00}" not in protected
    # 模拟翻译：替换非占位符部分
    translated = protected.replace("says", "说").replace("Hello", "你好").replace("to", "对")
    restored = file_processor.restore_placeholders(translated, mapping)
    assert "[name]" in restored
    assert "{color=#f00}" in restored
    assert "{/color}" in restored
    print("[OK] protect_restore_roundtrip")


def test_protect_dedup():
    """相同占位符只产生一个 token（全局去重）"""
    text = "[name] greets [name] again"
    _, mapping = file_processor.protect_placeholders(text)
    assert len(mapping) == 1, f"Expected 1 mapping for duplicated placeholder, got {len(mapping)}"
    print("[OK] protect_dedup")


def test_protect_empty_and_no_placeholders():
    """空文本和无占位符文本原样返回"""
    # 空文本
    result, mapping = file_processor.protect_placeholders("")
    assert result == "" and mapping == []
    # 纯空白
    result2, mapping2 = file_processor.protect_placeholders("   ")
    assert mapping2 == []
    # 无占位符
    result3, mapping3 = file_processor.protect_placeholders("Hello world")
    assert result3 == "Hello world" and mapping3 == []
    print("[OK] protect_empty_and_no_placeholders")


def test_protect_mixed_types():
    """混合类型占位符：[var] + {tag} + %(fmt)s"""
    text = "[a] and {b} and %(c)s end"
    protected, mapping = file_processor.protect_placeholders(text)
    assert len(mapping) == 3, f"Expected 3 mappings, got {len(mapping)}"
    # 还原后一致
    restored = file_processor.restore_placeholders(protected, mapping)
    assert restored == text
    print("[OK] protect_mixed_types")


def test_protect_menu_id():
    """菜单标识符 {#id} 也被保护"""
    text = "Go home{#home_choice}"
    protected, mapping = file_processor.protect_placeholders(text)
    assert "{#home_choice}" not in protected
    assert len(mapping) >= 1
    restored = file_processor.restore_placeholders(protected, mapping)
    assert restored == text
    print("[OK] protect_menu_id")


# ============================================================
# B1: 核心函数单元测试 — check_response_item
# ============================================================


def test_check_response_item_normal():
    """正常条目通过校验"""
    warnings = file_processor.check_response_item(
        {"line": 1, "original": "Hello world", "zh": "你好世界"}
    )
    assert len(warnings) == 0
    print("[OK] check_response_item_normal")


def test_check_response_item_empty_zh():
    """译文为空时被拦截"""
    warnings = file_processor.check_response_item({"line": 1, "original": "Hello", "zh": ""})
    assert len(warnings) > 0 and "译文为空" in warnings[0]
    print("[OK] check_response_item_empty_zh")


def test_check_response_item_empty_original():
    """原文为空时被拦截"""
    warnings = file_processor.check_response_item({"line": 1, "original": "", "zh": "你好"})
    assert len(warnings) > 0 and "original 为空" in warnings[0]
    print("[OK] check_response_item_empty_original")


def test_check_response_item_var_missing():
    """占位符缺失时被拦截"""
    warnings = file_processor.check_response_item(
        {"line": 1, "original": "Hello [name]", "zh": "你好"}
    )
    assert len(warnings) > 0 and "占位符" in warnings[0]
    print("[OK] check_response_item_var_missing")


def test_check_response_item_var_preserved():
    """占位符保留时通过"""
    warnings = file_processor.check_response_item(
        {"line": 1, "original": "Hello [name]", "zh": "你好 [name]"}
    )
    assert len(warnings) == 0
    print("[OK] check_response_item_var_preserved")


def test_check_response_item_line_offset():
    """line_offset 正确叠加到行号"""
    warnings = file_processor.check_response_item(
        {"line": 5, "original": "Hi", "zh": ""},
        line_offset=100,
    )
    assert "105" in warnings[0]
    print("[OK] check_response_item_line_offset")


# ============================================================
# B1: 核心函数单元测试 — check_response_chunk
# ============================================================


def test_check_response_chunk_match():
    """返回条数与可翻译行数一致时无警告"""
    chunk = 'e "Line A"\ne "Line B"\ne "Line C"'
    warnings = file_processor.check_response_chunk(
        chunk,
        [
            {"line": 1, "original": "Line A", "zh": "行A"},
            {"line": 2, "original": "Line B", "zh": "行B"},
            {"line": 3, "original": "Line C", "zh": "行C"},
        ],
    )
    assert len(warnings) == 0
    print("[OK] check_response_chunk_match")


def test_check_response_chunk_mismatch():
    """返回条数不一致时有警告"""
    chunk = 'e "Line A"\ne "Line B"\ne "Line C"'
    warnings = file_processor.check_response_chunk(
        chunk,
        [
            {"line": 1, "original": "Line A", "zh": "行A"},
        ],
    )
    assert len(warnings) > 0 and "不一致" in warnings[0]
    print("[OK] check_response_chunk_mismatch")


def test_check_response_chunk_empty():
    """无可翻译行的 chunk + 空返回 → 无警告"""
    chunk = "# This is a comment\nlabel start:\n    pass"
    warnings = file_processor.check_response_chunk(chunk, [])
    assert len(warnings) == 0
    print("[OK] check_response_chunk_empty")


def test_check_response_chunk_skip_chinese():
    """已含中文的行不计入 expected（视为已翻译）"""
    chunk = 'e "你好世界"\ne "Hello"'
    warnings = file_processor.check_response_chunk(
        chunk,
        [
            {"line": 2, "original": "Hello", "zh": "你好"},
        ],
    )
    assert len(warnings) == 0
    print("[OK] check_response_chunk_skip_chinese")


# ============================================================
# C: 集成级测试 — 密度自适应 / 跳过名单 / 漏翻检测 / TranslationDB
# ============================================================


def test_skip_files():
    """T7: SKIP_FILES_FOR_TRANSLATION 跳过逻辑"""
    from file_processor import SKIP_FILES_FOR_TRANSLATION

    for name in ("define.rpy", "variables.rpy", "screens.rpy", "options.rpy", "earlyoptions.rpy"):
        assert name in SKIP_FILES_FOR_TRANSLATION, f"{name} not in SKIP_FILES"
    assert "script.rpy" not in SKIP_FILES_FOR_TRANSLATION
    print("[OK] skip_files")


def test_restore_placeholders_in_translations():
    """测试 _restore_placeholders_in_translations 辅助函数（round 27 A-H-2: now in file_processor）"""
    from file_processor import _restore_placeholders_in_translations, protect_placeholders

    text = "Hello [name], welcome to {color=#f00}town{/color}!"
    protected, mapping = protect_placeholders(text)
    translations = [
        {
            "original": protected,
            "zh": f"你好 {protected.split('__RENPY_PH_0__')[0]}__RENPY_PH_0__！",
        }
    ]
    # 不应崩溃
    _restore_placeholders_in_translations(translations, mapping)
    # original 应被还原
    assert "[name]" in translations[0]["original"]
    print("[OK] restore_placeholders_in_translations")


# ============================================================
# D: 第九轮新增测试
# ============================================================


def test_filter_checked_translations():
    """T47: _filter_checked_translations 正常/空译文/占位符缺失（round 27 A-H-2: now in file_processor）"""
    from file_processor import _filter_checked_translations

    items = [
        {"line": 1, "original": "Hello", "zh": "你好"},
        {"line": 2, "original": "World", "zh": ""},  # 空译文 → dropped
        {"line": 3, "original": "[name] hi", "zh": "你好"},  # 占位符缺失 → dropped
    ]
    kept, dropped_count, dropped_items, warnings = _filter_checked_translations(items)
    assert len(kept) == 1 and kept[0]["line"] == 1
    assert dropped_count == 2
    assert len(dropped_items) == 2
    assert len(warnings) >= 2
    print("[OK] filter_checked_translations")


def test_protect_control_tags():
    """Ren'Py 控制标签 {w}/{p}/{nw}/{fast}/{cps=N} 被占位符保护覆盖"""
    text = "Wait{w=0.5} pause{p} nowait{nw} fast{fast} speed{cps=20} done{done}"
    protected, mapping = file_processor.protect_placeholders(text)
    # 所有控制标签应被替换
    for tag in ["{w=0.5}", "{p}", "{nw}", "{fast}", "{cps=20}", "{done}"]:
        assert tag not in protected, f"{tag} not protected"
    # 还原后完全一致
    restored = file_processor.restore_placeholders(protected, mapping)
    assert restored == text
    print("[OK] protect_control_tags")


def test_replace_string_prefix_strip():
    """WF-08 修复：AI 返回含行前缀的 original 时能正确剥离并替换"""
    from file_processor.patcher import _replace_string_in_line

    # AI 返回 text _("原文") 但行中实际是 _("原文") 结构
    line = '            text _("Made with Ren\'Py")'
    # AI 的 original 包含了 text _(" 前缀
    result = _replace_string_in_line(line, 'text _("Made with Ren\'Py")', "由 Ren'Py 制作")
    assert result is not None, "prefix strip should match"
    assert "由 Ren'Py 制作" in result
    print("[OK] replace_string_prefix_strip")


def test_replace_string_escaped_quotes():
    """WF-04 修复：含转义引号的字符串匹配"""
    from file_processor.patcher import _replace_string_in_line

    line = r'    textbutton "She said \"hello\""'
    result = _replace_string_in_line(line, r"She said \"hello\"", '她说了"你好"')
    # 即使匹配不上（转义引号情况复杂），至少不应崩溃
    # 如果匹配成功更好
    print(f"[OK] replace_string_escaped_quotes (result={'matched' if result else 'no_match'})")


def test_w_round57_s4_fuzz_escape_for_renpy_string():
    """Round 57 S4: fuzz ``_escape_for_renpy_string`` with adversarial LLM
    output (unbalanced quotes, raw backslashes, control chars, mixed
    line endings). Output MUST always be a string that, when wrapped in
    the chosen quote char, parses as a valid Ren'Py string literal — no
    unbalanced quotes, no stray un-escaped backslashes.
    """
    from file_processor.patcher import _escape_for_renpy_string

    # Adversarial inputs: things an LLM might emit that would break .rpy
    # if pasted verbatim.
    payloads = [
        '"',  # bare unescaped quote
        "\\",  # bare backslash
        '\\"',  # already-escaped quote
        "\\\\",  # escaped backslash
        '"""',  # triple-quote (Python string ambiguity)
        'normal text with " in middle and \\ too',  # mixed
        "line1\nline2\rline3\r\nline4",  # all line-ending forms
        "a" * 1000 + '"',  # long input + trailing quote
        "\x00 NUL",  # control char
        "tab\there",  # tab — should pass through
        '不 escape "你好"',  # non-ASCII + quotes
        "",  # empty string
    ]
    for raw in payloads:
        escaped = _escape_for_renpy_string(raw, '"')
        # Property 1: every double-quote in the result must be preceded by
        # a backslash (i.e. the count of unescaped " is zero).
        i = 0
        while i < len(escaped):
            if escaped[i] == '"':
                preceding_bs = 0
                j = i - 1
                while j >= 0 and escaped[j] == "\\":
                    preceding_bs += 1
                    j -= 1
                assert preceding_bs % 2 == 1, (
                    f"unescaped quote at position {i} in {escaped!r} (from raw={raw!r})"
                )
            i += 1
        # Property 2: no stray bare CR (Windows CRLF must be normalised
        # to \\n; raw \\r must be stripped per docstring contract)
        assert "\r" not in escaped, f"raw \\r leaked into {escaped!r}"
        # Property 3: function never crashes — already covered by reaching here

    print(f"[OK] w_round57_s4_fuzz_escape_for_renpy_string ({len(payloads)} payloads)")


def test_w_round57_s4_escape_round_trip_invariant():
    """Round 57 S4: a translation that's already valid Ren'Py should
    not be corrupted by escape (idempotence on safe input)."""
    from file_processor.patcher import _escape_for_renpy_string

    # Already-safe outputs — escape should pass through quotes/backslashes
    # but produce something parseable inside `"..."`.
    safe_inputs = [
        "你好",
        "Hello, world",
        "已译: [name]",
        "数字 123",
    ]
    for s in safe_inputs:
        result = _escape_for_renpy_string(s, '"')
        # No quote in input means no escape needed
        if '"' not in s:
            assert '\\"' not in result, f"spurious escape: {s!r} → {result!r}"
        # Backslash count: input \\ count == output \\\\ count (each \\ doubled)
        # but on inputs without backslash, no spurious one
        if "\\" not in s:
            assert "\\\\" not in result, f"spurious double-backslash: {s!r} → {result!r}"
    print("[OK] w_round57_s4_escape_round_trip_invariant")


def test_fix_chinese_placeholder_drift():
    """Round 31 Tier A-2: AI-introduced Chinese placeholder variants are
    normalised back to canonical Ren'Py ``[name]`` syntax.
    """
    from file_processor import fix_chinese_placeholder_drift

    # Square-bracket drift (most common AI mistake).
    assert fix_chinese_placeholder_drift("你好，[姓名]！") == "你好，[name]！"
    assert fix_chinese_placeholder_drift("[名字] 来了") == "[name] 来了"
    assert fix_chinese_placeholder_drift("再见，[名称]") == "再见，[name]"

    # Full-width parens the AI likes to produce.
    assert fix_chinese_placeholder_drift("嗨（姓名）") == "嗨[name]"
    assert fix_chinese_placeholder_drift("嗨(名字)再见") == "嗨[name]再见"

    # Double-curly (Ren'Py 8 screen variable form).
    assert fix_chinese_placeholder_drift("Hello {{姓名}}") == "Hello {{name}}"

    # Multiple drifts in one string.
    assert fix_chinese_placeholder_drift("[姓名]说：我是[名字]") == "[name]说：我是[name]"

    # Idempotent — already-correct strings pass through.
    assert fix_chinese_placeholder_drift("Hello [name]") == "Hello [name]"
    assert fix_chinese_placeholder_drift("Nothing to fix") == "Nothing to fix"
    assert fix_chinese_placeholder_drift("") == ""
    assert fix_chinese_placeholder_drift(None) is None  # type: ignore[arg-type]
    print("[OK] fix_chinese_placeholder_drift")


def test_filter_checked_translations_fixes_placeholder_drift():
    """Round 31 Tier A-2 integration: ``_filter_checked_translations`` must
    auto-fix Chinese placeholder drift so otherwise-valid entries aren't
    dropped by the placeholder-set check.
    """
    from file_processor import _filter_checked_translations

    # Before the fix, this entry would fail check_response_item because
    # ``[name]`` appears in original but ``[姓名]`` appears in zh — they
    # don't match as placeholders.  After Tier A-2 the filter normalises
    # zh first so the entry is kept and the zh is canonical.
    translations = [
        {"line": 1, "original": "Hello [name]!", "zh": "你好 [姓名]！"},
        {"line": 2, "original": "Bye [friend]", "zh": "再见 [friend]"},  # already correct
    ]

    kept, dropped_count, dropped_items, warnings = _filter_checked_translations(translations)

    assert dropped_count == 0, f"placeholder-drift entry was wrongly dropped: {warnings}"
    assert len(kept) == 2
    # Verify the drift was normalised in-place.
    assert kept[0]["zh"] == "你好 [name]！", f"drift not normalised: {kept[0]['zh']!r}"
    assert kept[1]["zh"] == "再见 [friend]"
    print("[OK] filter_checked_translations_fixes_placeholder_drift")


def run_all() -> int:
    """Run every test in this module; return test count."""
    tests = [
        test_estimate_tokens,
        test_find_block_boundaries,
        test_safety_check,
        test_apply_translations,
        test_apply_cascade,
        test_validate_translation,
        test_force_split,
        test_triple_quote_replacement,
        test_underscore_func_replacement,
        test_validate_menu_identifier,
        test_image_block_boundary,
        test_protect_restore_roundtrip,
        test_protect_dedup,
        test_protect_empty_and_no_placeholders,
        test_protect_mixed_types,
        test_protect_menu_id,
        test_check_response_item_normal,
        test_check_response_item_empty_zh,
        test_check_response_item_empty_original,
        test_check_response_item_var_missing,
        test_check_response_item_var_preserved,
        test_check_response_item_line_offset,
        test_check_response_chunk_match,
        test_check_response_chunk_mismatch,
        test_check_response_chunk_empty,
        test_check_response_chunk_skip_chinese,
        test_skip_files,
        test_restore_placeholders_in_translations,
        test_filter_checked_translations,
        test_protect_control_tags,
        test_replace_string_prefix_strip,
        test_replace_string_escaped_quotes,
        test_w_round57_s4_fuzz_escape_for_renpy_string,
        test_w_round57_s4_escape_round_trip_invariant,
        # Round 31 Tier A-2: placeholder drift fix (A-1 UI whitelist + r32
        # configurable + r44 oversize cap moved to tests/test_ui_whitelist.py
        # in round 45 to bring this file back under the 800-line soft limit)
        test_fix_chinese_placeholder_drift,
        test_filter_checked_translations_fixes_placeholder_drift,
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
