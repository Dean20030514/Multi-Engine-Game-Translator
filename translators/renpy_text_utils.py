#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ren'Py 文本分析工具函数。

从 one_click_pipeline.py 提取的公共函数，供 direct_translator / retranslator /
one_click_pipeline 等模块共享，消除反向依赖。
"""

from __future__ import annotations

import re
from pathlib import Path

from file_processor import read_file, SKIP_FILES_FOR_TRANSLATION

# ============================================================
# 可配置阈值常量
# ============================================================

MIN_UNTRANSLATED_TEXT_LENGTH = 20  # 疑似漏翻最小文本长度
# Round 53 W4: ``MIN_ENGLISH_CHARS_FOR_UNTRANSLATED`` hard-codes the
# leakage-detection rule to ASCII letters, which makes direct-mode
# implicitly English-source-only. Non-English source games (ja/ko/etc)
# should use tl-mode (which is source-language agnostic). See
# ``CLAUDE.md`` §"已知限制" + ``README.md`` §source language assumption.
MIN_ENGLISH_CHARS_FOR_UNTRANSLATED = 12  # 疑似漏翻最小英文字符数 (English-source only)


# ============================================================
# 行级文本判定
# ============================================================


def _is_user_visible_string_line(line: str) -> bool:
    """判断该行是否大概率是用户可见文本，而不是代码标识符。"""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False

    lower = stripped.lower()

    # 明确排除：典型代码/配置字符串行
    if any(
        k in lower
        for k in (
            "style_prefix",
            "id ",
            " action ",
            "action ",
            "jump(",
            "call(",
            "setvariable(",
            "setfield(",
            "showmenu(",
            "use ",
            "add ",
            "image ",
            "build.classify",
            "build.archive",
            "label ",
            "screen ",
            "transform ",
        )
    ):
        return False

    # 明确包含：角色对话/旁白
    if re.match(r'^\s*(?:[A-Za-z_]\w*\s+)?"', line):
        return True

    # 界面可见文本
    if re.search(r'\b(text|textbutton)\s+"', line):
        return True
    if 'renpy.notify("' in line:
        return True
    if re.search(r'_\("', line):
        return True

    return False


def _is_untranslated_dialogue(text: str) -> bool:
    """判断一段对话文本是否为疑似未翻译的英文。"""
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en = sum(1 for c in text if "a" <= c.lower() <= "z")
    return (
        cn == 0
        and en >= MIN_ENGLISH_CHARS_FOR_UNTRANSLATED
        and len(text) >= MIN_UNTRANSLATED_TEXT_LENGTH
    )


def _extract_dialogue_text(line: str) -> str | None:
    """从一行代码中提取用户可见的对话文本，不符合条件返回 None。"""
    if not _is_user_visible_string_line(line):
        return None
    m = re.search(r'"([^"\\]*(?:\\.[^"\\]*)*)"', line)
    if not m:
        return None
    s = m.group(1)
    if len(s) < 8:
        return None
    if any(x in s for x in ("/", "\\", ".png", ".jpg", ".webp", ".ttf", "#")):
        return None
    return s


# ============================================================
# 文件级统计
# ============================================================


def count_untranslated_dialogues_in_file(path: Path) -> tuple[int, int]:
    """返回 (对话行总数, 疑似未翻译英文对话行数)。"""
    if path.name in SKIP_FILES_FOR_TRANSLATION:
        return 0, 0
    dialogue = 0
    untranslated = 0
    try:
        text = read_file(path)
    except OSError:
        return 0, 0

    for line in text.splitlines():
        s = _extract_dialogue_text(line)
        if s is None:
            continue
        dialogue += 1
        if _is_untranslated_dialogue(s):
            untranslated += 1
    return dialogue, untranslated


def collect_untranslated_details(path: Path) -> list[tuple[int, str]]:
    """返回 [(行号, 原文文本), ...] 对于疑似未翻译的英文对话行。"""
    if path.name in SKIP_FILES_FOR_TRANSLATION:
        return []
    result: list[tuple[int, str]] = []
    try:
        text = read_file(path)
    except OSError:
        return []
    for i, line in enumerate(text.splitlines(), 1):
        s = _extract_dialogue_text(line)
        if s is None:
            continue
        if _is_untranslated_dialogue(s):
            result.append((i, s))
    return result
