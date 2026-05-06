#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟测试：直接调用 file_processor / one_click_pipeline 的校验与统计逻辑，对测试方案 (_archive/TEST_PLAN_r50.md) 中的功能点做断言。"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# Windows 下避免 validate_translation 内 print 的 Unicode 编码错误
if hasattr(sys.stdout, "buffer"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# 保证从项目根可导入
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from file_processor import (
    validate_translation,
    _extract_placeholder_sequence,
    read_file,
)
from pipeline.gate import collect_strings_stats


TESTS_DIR = Path(__file__).resolve().parent
# 仅含 sample_strings.rpy 的隔离子目录，避免 script.rpy 等污染 strings 统计
STRINGS_ONLY_DIR = TESTS_DIR / "fixtures" / "strings_only"


def test_w430_len_ratio_suspect_triggered():
    """W430：译文长度比例过短时触发（原文>=20、译文>=5 才检查，比例 < 0.3 触发）。"""
    # 原文 25 字、译文 5 字 -> 比例 0.2 < 0.3
    orig = 'label start:\n    e "abcdefghijklmnopqrstuvwxy"\n'
    trans = 'label start:\n    e "一二三四五"\n'
    issues = validate_translation(
        orig,
        trans,
        "t.rpy",
        len_ratio_lower=0.3,
        len_ratio_upper=2.5,
    )
    codes = [i["code"] for i in issues]
    assert "W430_LEN_RATIO_SUSPECT" in codes, f"Expected W430 in issues, got: {codes}"


def test_w440_model_speaking_triggered():
    """W440：译文含模型自我描述时触发。"""
    orig = read_file(TESTS_DIR / "sample_triggers.rpy")
    trans = read_file(TESTS_DIR / "sample_triggers_trans.rpy")
    issues = validate_translation(orig, trans, "sample_triggers.rpy")
    codes = [i["code"] for i in issues]
    assert "W440_MODEL_SPEAKING" in codes, f"Expected W440 in issues, got: {codes}"


def test_w441_punct_mix_triggered():
    """W441：译文中英标点连续混用时触发。"""
    orig = read_file(TESTS_DIR / "sample_triggers.rpy")
    trans = read_file(TESTS_DIR / "sample_triggers_trans.rpy")
    issues = validate_translation(orig, trans, "sample_triggers.rpy")
    codes = [i["code"] for i in issues]
    assert "W441_PUNCT_MIX" in codes, f"Expected W441 in issues, got: {codes}"


def test_w442_suspect_english_output_triggered():
    """W442：译文中文占比极低时触发。"""
    orig = read_file(TESTS_DIR / "sample_triggers.rpy")
    trans = read_file(TESTS_DIR / "sample_triggers_trans.rpy")
    issues = validate_translation(orig, trans, "sample_triggers.rpy")
    codes = [i["code"] for i in issues]
    assert "W442_SUSPECT_ENGLISH_OUTPUT" in codes, f"Expected W442 in issues, got: {codes}"


def test_w251_placeholder_order_triggered():
    """W251：占位符集合相同但顺序不同时触发。"""
    orig = read_file(TESTS_DIR / "sample_triggers.rpy")
    trans = read_file(TESTS_DIR / "sample_triggers_trans.rpy")
    issues = validate_translation(orig, trans, "sample_triggers.rpy")
    codes = [i["code"] for i in issues]
    assert "W251_PLACEHOLDER_ORDER" in codes, f"Expected W251 in issues, got: {codes}"


def test_e411_glossary_lock_miss_triggered():
    """E411：原文含锁定术语但译文未用规定译名时触发。"""
    orig = read_file(TESTS_DIR / "sample_triggers.rpy")
    trans = read_file(TESTS_DIR / "sample_triggers_trans.rpy")
    with open(TESTS_DIR / "glossary_test.json", encoding="utf-8") as f:
        data = json.load(f)
    terms = data.get("terms", {})
    locked = set(data.get("locked_terms", []))
    issues = validate_translation(
        orig,
        trans,
        "sample_triggers.rpy",
        glossary_terms=terms,
        glossary_locked=locked,
    )
    codes = [i["code"] for i in issues]
    assert "E411_GLOSSARY_LOCK_MISS" in codes, f"Expected E411 in issues, got: {codes}"


def test_e420_no_translate_changed_triggered():
    """E420：原文含禁翻片段但译文中缺失时触发。"""
    orig = read_file(TESTS_DIR / "sample_triggers.rpy")
    trans = read_file(TESTS_DIR / "sample_triggers_trans.rpy")
    no_translate = set(
        json.load(open(TESTS_DIR / "glossary_test.json", encoding="utf-8")).get("no_translate", [])
    )
    issues = validate_translation(
        orig,
        trans,
        "sample_triggers.rpy",
        glossary_no_translate=no_translate,
    )
    codes = [i["code"] for i in issues]
    assert "E420_NO_TRANSLATE_CHANGED" in codes, f"Expected E420 in issues, got: {codes}"


def test_e420_case_insensitive_when_kept():
    """E420：禁翻片段在译文中保留（大小写不同）时不触发。"""
    orig_lines = ['    e "Version is v1.0 released today."']
    trans_lines = ['    e "版本是 V1.0 今日发布。"']
    no_translate = {"v1.0"}
    issues = validate_translation(
        "\n".join(orig_lines),
        "\n".join(trans_lines),
        "test.rpy",
        glossary_no_translate=no_translate,
    )
    e420 = [i for i in issues if i.get("code") == "E420_NO_TRANSLATE_CHANGED"]
    assert len(e420) == 0, (
        f"E420 should not fire when no_translate kept (case-insensitive), got: {e420}"
    )


def test_extract_placeholder_sequence_nested_order():
    """占位符提取：嵌套场景下从左到右顺序正确。"""
    text = "{color=#f00}[name]{/color}"
    seq = _extract_placeholder_sequence(text)
    assert seq == ["{color=#f00}", "[name]", "{/color}"], f"Expected nested order, got: {seq}"


def test_collect_strings_stats_summary():
    """strings 统计：使用隔离子目录，summary 总数与单文件统计一致。"""
    assert STRINGS_ONLY_DIR.is_dir(), f"fixtures/strings_only not found: {STRINGS_ONLY_DIR}"
    result = collect_strings_stats(STRINGS_ONLY_DIR)
    summary = result["summary"]
    assert summary["total_strings_entries"] == 6, f"Expected 6 entries, got: {summary}"
    assert summary["total_strings_translated"] == 3 and summary["total_strings_untranslated"] == 3
    assert summary["untranslated_ratio"] == 0.5
    assert "note" in summary and "未翻译" in summary["note"]
    files_info = result.get("files", [])
    assert len(files_info) == 1 and files_info[0]["strings_total"] == 6
    assert files_info[0]["strings_translated"] == 3 and files_info[0]["strings_untranslated"] == 3


def test_w430_boundary_below_lower():
    """W430 边界：比例 < len_ratio_lower 时触发（需原文>=20、译文>=5 才做比例检查）。"""
    orig = 'e "abcdefghijklmnopqrstuvwxy"'  # 26 字
    trans = 'e "一二三四五"'  # 5 字 -> 5/26≈0.19 < 0.3
    issues = validate_translation(orig, trans, "t.rpy", len_ratio_lower=0.3, len_ratio_upper=2.5)
    assert any(i["code"] == "W430_LEN_RATIO_SUSPECT" for i in issues), (
        "W430 should fire when ratio < 0.3"
    )


def test_w430_boundary_at_upper():
    """W430 边界：比例 > len_ratio_upper 时触发。"""
    orig = 'e "abcdefghijklmnopqrst"'  # 20 字
    trans = 'e "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一"'  # 51 字 -> 51/20=2.55>2.5
    issues = validate_translation(orig, trans, "t.rpy", len_ratio_lower=0.3, len_ratio_upper=2.5)
    assert any(i["code"] == "W430_LEN_RATIO_SUSPECT" for i in issues), (
        "W430 should fire when ratio > 2.5"
    )


def test_w251_order_vs_set_same_order_no_w251():
    """W251：占位符集合相同且顺序相同时不触发。"""
    orig = 'e "First [var_a] and [var_b] end."'
    trans = 'e "先是 [var_a] 再 [var_b] 结束。"'
    issues = validate_translation(orig, trans, "t.rpy")
    w251 = [i for i in issues if i.get("code") == "W251_PLACEHOLDER_ORDER"]
    assert len(w251) == 0, f"W251 should not fire when order same, got: {w251}"


def run_all():
    runners = [
        ("W430 长度比例告警", test_w430_len_ratio_suspect_triggered),
        ("W440 模型自我描述", test_w440_model_speaking_triggered),
        ("W441 标点混用", test_w441_punct_mix_triggered),
        ("W442 中文占比极低", test_w442_suspect_english_output_triggered),
        ("W251 占位符顺序", test_w251_placeholder_order_triggered),
        ("E411 锁定术语未命中", test_e411_glossary_lock_miss_triggered),
        ("E420 禁翻片段被修改", test_e420_no_translate_changed_triggered),
        ("E420 禁翻大小写不敏感保留", test_e420_case_insensitive_when_kept),
        ("占位符提取嵌套顺序", test_extract_placeholder_sequence_nested_order),
        ("strings 统计 summary", test_collect_strings_stats_summary),
        ("W430 边界低于下限", test_w430_boundary_below_lower),
        ("W430 边界高于上限", test_w430_boundary_at_upper),
        ("W251 顺序相同不触发", test_w251_order_vs_set_same_order_no_w251),
    ]
    failed = []
    for name, fn in runners:
        try:
            fn()
        except AssertionError as e:
            failed.append((name, str(e)))
    if failed:
        for name, reason in failed:
            print(f"FAIL: {name} — {reason}")
        return False
    print("All tests passed")
    return True


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
