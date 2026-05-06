#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-translation validation."""

from __future__ import annotations

import logging
import re
from typing import Optional

from file_processor.checker import (
    _extract_placeholder_sequence,
    MODEL_SPEAKING_PATTERNS,
)
from file_processor.patcher import (
    _count_unescaped_quote,
    _extract_first_quoted_text,
    _strip_double_quoted_segments,
)

logger = logging.getLogger(__name__)

# W442 触发阈值：中文字符占比低于此值视为疑似未翻译
MIN_CHINESE_RATIO = 0.05

# ============================================================
# 预编译正则（第 25 轮 PF-C-2）— 原为字面量 re.search/findall/sub 调用，
# 每翻译文件被 validate_translation 数百次命中，预编译节省 500-700ms/文件
# ============================================================
_RE_SINGLE_QUOTED_STR = re.compile(r"'[^'\\]*(?:\\.[^'\\]*)*'")
_RE_CODE_KEYWORD_LINE = re.compile(
    r"^(label|screen|jump|call|show|hide|scene|define|default|"
    r"init|python|style|transform)\s"
)
_RE_DOUBLE_QUOTED_STR = re.compile(r'"[^"]*"')
_RE_BRACKET_VAR = re.compile(r"\[(\w+)\]")
_RE_TAG_BRACE = re.compile(r"\{/?[a-zA-Z]+=?[^}]*\}")
_RE_COMMENT_TAG = re.compile(r"\{#[^}]+\}")
_RE_PRINTF_NAMED = re.compile(r"%\([^)]+\)[sd]")
_RE_DOUBLE_PUNCT = re.compile(r"[。！？]{2,}")


def _looks_untranslated_dialogue(text: str) -> bool:
    """启发式判断文本是否像未翻译英文对话。"""
    if len(text) < 20:
        return False
    _SKIP_TOKENS = ("/", "\\", ".png", ".jpg", ".webp", ".ttf", "#")
    if any(token in text for token in _SKIP_TOKENS):
        return False
    ascii_letters = sum(1 for c in text if ("a" <= c.lower() <= "z"))
    cn_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cn_chars == 0 and ascii_letters >= 12


# ============================================================
# 逐行检查子函数
# ============================================================


def _check_structural_integrity(
    orig: str,
    trans: str,
    line_num: int,
) -> list[dict]:
    """检查行级结构完整性：缩进、非字符串行、引号结构、代码关键字。"""
    issues: list[dict] = []

    # 缩进必须一致
    orig_indent = len(orig) - len(orig.lstrip())
    trans_indent = len(trans) - len(trans.lstrip())
    if orig_indent != trans_indent:
        issues.append(
            {
                "level": "error",
                "code": "E110_INDENT_CHANGED",
                "line": line_num,
                "message": f"缩进被改变: 原 {orig_indent} 空格, 译 {trans_indent} 空格",
            }
        )

    # 非字符串行不应被修改
    if '"' not in orig and "'" not in orig:
        if orig != trans:
            issues.append(
                {
                    "level": "error",
                    "code": "E120_NON_STRING_MODIFIED",
                    "line": line_num,
                    "message": f'非字符串行被修改: "{orig.strip()[:60]}" -> "{trans.strip()[:60]}"',
                }
            )

    # 双引号结构必须稳定
    if '"' in orig or '"' in trans:
        oq = _count_unescaped_quote(orig, '"')
        tq = _count_unescaped_quote(trans, '"')
        if oq != tq:
            issues.append(
                {
                    "level": "error",
                    "code": "E130_DQUOTE_MISMATCH",
                    "line": line_num,
                    "message": f"双引号结构变化: 原 {oq}, 译 {tq}",
                }
            )

    # 单引号检查（仅代码层，忽略对话内 apostrophe）
    orig_outside_dq = _strip_double_quoted_segments(orig)
    trans_outside_dq = _strip_double_quoted_segments(trans)
    has_sq_literal = (
        _RE_SINGLE_QUOTED_STR.search(orig_outside_dq) is not None
        or _RE_SINGLE_QUOTED_STR.search(trans_outside_dq) is not None
    )
    if has_sq_literal:
        oq = _count_unescaped_quote(orig_outside_dq, "'")
        tq = _count_unescaped_quote(trans_outside_dq, "'")
        if oq != tq:
            issues.append(
                {
                    "level": "error",
                    "code": "E131_SQUOTE_MISMATCH",
                    "line": line_num,
                    "message": f"单引号结构变化: 原 {oq}, 译 {tq}",
                }
            )

    # 代码关键字行结构保护
    stripped = orig.strip()
    if _RE_CODE_KEYWORD_LINE.match(stripped):
        orig_no_str = _RE_DOUBLE_QUOTED_STR.sub('""', orig)
        trans_no_str = _RE_DOUBLE_QUOTED_STR.sub('""', trans)
        if orig_no_str != trans_no_str:
            issues.append(
                {
                    "level": "error",
                    "code": "E140_CODE_STRUCT_CHANGED",
                    "line": line_num,
                    "message": f"代码结构被修改: {orig.strip()[:60]}",
                }
            )

    return issues


def _check_placeholders_and_tags(
    orig: str,
    trans: str,
    line_num: int,
) -> list[dict]:
    """检查变量引用、文本标签、菜单ID、格式化占位符、占位符顺序。"""
    issues: list[dict] = []

    # 变量引用 [var]
    orig_vars = set(_RE_BRACKET_VAR.findall(orig))
    trans_vars = set(_RE_BRACKET_VAR.findall(trans))
    missing = orig_vars - trans_vars
    if missing:
        issues.append(
            {
                "level": "error",
                "code": "E210_VAR_MISSING",
                "line": line_num,
                "message": f"变量丢失: {missing}",
            }
        )
    extra = trans_vars - orig_vars
    if extra:
        issues.append(
            {
                "level": "warning",
                "code": "W211_VAR_EXTRA",
                "line": line_num,
                "message": f"变量多出: {extra}",
            }
        )

    # Ren'Py 文本标签 {tag}
    orig_tags = _RE_TAG_BRACE.findall(orig)
    trans_tags = _RE_TAG_BRACE.findall(trans)
    if sorted(orig_tags) != sorted(trans_tags):
        issues.append(
            {
                "level": "error",
                "code": "E220_TEXT_TAG_MISMATCH",
                "line": line_num,
                "message": f"文本标签不匹配: 原={orig_tags}, 译={trans_tags}",
            }
        )

    # 菜单标识符 {#id}
    orig_ids = _RE_COMMENT_TAG.findall(orig)
    trans_ids = _RE_COMMENT_TAG.findall(trans)
    if sorted(orig_ids) != sorted(trans_ids):
        issues.append(
            {
                "level": "error",
                "code": "E230_MENU_ID_MISMATCH",
                "line": line_num,
                "message": f"菜单标识符不匹配: 原={orig_ids}, 译={trans_ids}",
            }
        )

    # 转义换行符 \n
    orig_escaped_nl = orig.count("\\n")
    trans_escaped_nl = trans.count("\\n")
    if orig_escaped_nl != trans_escaped_nl:
        issues.append(
            {
                "level": "warning",
                "code": "W310_ESCAPED_NL_MISMATCH",
                "line": line_num,
                "message": f"行内转义换行符数量不一致: 原 {orig_escaped_nl}, 译 {trans_escaped_nl}",
            }
        )

    # Python 百分号格式化占位符
    orig_fmt = set(_RE_PRINTF_NAMED.findall(orig))
    trans_fmt = set(_RE_PRINTF_NAMED.findall(trans))
    if orig_fmt != trans_fmt:
        issues.append(
            {
                "level": "error",
                "code": "E240_FMT_PLACEHOLDER_MISMATCH",
                "line": line_num,
                "message": f"格式化占位符不匹配: 原={orig_fmt}, 译={trans_fmt}",
            }
        )

    # 占位符顺序
    orig_seq = _extract_placeholder_sequence(orig)
    trans_seq = _extract_placeholder_sequence(trans)
    if set(orig_seq) == set(trans_seq) and orig_seq != trans_seq:
        issues.append(
            {
                "level": "warning",
                "code": "W251_PLACEHOLDER_ORDER",
                "line": line_num,
                "message": "占位符顺序与原文不一致（集合相同，可能因语序调整）",
            }
        )

    return issues


def _check_glossary_compliance(
    orig: str,
    trans: str,
    line_num: int,
    glossary_terms: dict | None,
    glossary_locked: set[str] | None,
    glossary_no_translate: set[str] | None,
) -> list[dict]:
    """检查术语锁定、禁翻片段、漏翻疑似。"""
    issues: list[dict] = []

    # 术语表命中检查
    if glossary_terms:
        for src_term, dst_term in glossary_terms.items():
            if not src_term or not dst_term or str(src_term).startswith("__"):
                continue
            if src_term.lower() in orig.lower() and dst_term not in trans:
                if glossary_locked and src_term in glossary_locked:
                    issues.append(
                        {
                            "level": "error",
                            "code": "E411_GLOSSARY_LOCK_MISS",
                            "line": line_num,
                            "message": f'锁定术语未命中: "{src_term}" -> 必须包含 "{dst_term}"',
                        }
                    )
                else:
                    issues.append(
                        {
                            "level": "warning",
                            "code": "W410_GLOSSARY_MISS",
                            "line": line_num,
                            "message": f'术语表未命中: "{src_term}" -> 建议包含 "{dst_term}"',
                        }
                    )

    # 漏翻疑似
    if orig == trans:
        orig_text = _extract_first_quoted_text(orig)
        if orig_text and _looks_untranslated_dialogue(orig_text):
            issues.append(
                {
                    "level": "warning",
                    "code": "W420_SUSPECT_UNTRANSLATED",
                    "line": line_num,
                    "message": "疑似未翻译英文对话",
                }
            )

    # 禁翻片段检查
    if glossary_no_translate:
        orig_lower = orig.lower()
        trans_lower = trans.lower()
        for s in glossary_no_translate:
            if not s:
                continue
            key = str(s)
            if key.lower() in orig_lower and key.lower() not in trans_lower:
                issues.append(
                    {
                        "level": "error",
                        "code": "E420_NO_TRANSLATE_CHANGED",
                        "line": line_num,
                        "message": f'禁翻片段被修改: "{key}" 应保持英文不翻译',
                    }
                )

    return issues


def _check_quality_heuristics(
    orig: str,
    trans: str,
    line_num: int,
    len_ratio_lower: float,
    len_ratio_upper: float,
) -> list[dict]:
    """检查翻译风格、长度比例、中文占比等质量启发规则。

    Round 52 C4 BREAKING: lang_config kwarg retired (zh-only).
    """
    issues: list[dict] = []

    # W440: 模型自我描述/多余解释
    trans_lower = trans.lower()
    for pat in MODEL_SPEAKING_PATTERNS:
        if pat and pat in trans_lower:
            issues.append(
                {
                    "level": "warning",
                    "code": "W440_MODEL_SPEAKING",
                    "line": line_num,
                    "message": "译文疑似包含模型自我描述或多余解释，请改为纯对白/叙述文本",
                }
            )
            break

    # W441: 中英标点连续混用
    if any(p in trans for p in ("。.", ".。", "？?", "?？", "！!", "!！")):
        issues.append(
            {
                "level": "warning",
                "code": "W441_PUNCT_MIX",
                "line": line_num,
                "message": "译文中存在明显的中英标点连续混用（如 。. / ？? / ！!），建议统一为中文标点",
            }
        )

    # 长度比例与中文占比
    orig_text = _extract_first_quoted_text(orig)
    trans_text = _extract_first_quoted_text(trans)
    if orig_text and trans_text:
        # W430: 长度比例异常
        if len(orig_text) >= 20 and len(trans_text) >= 5:
            ratio = len(trans_text) / len(orig_text) if len(orig_text) else 0.0
            if ratio < len_ratio_lower or ratio > len_ratio_upper:
                issues.append(
                    {
                        "level": "warning",
                        "code": "W430_LEN_RATIO_SUSPECT",
                        "line": line_num,
                        "message": f"译文长度比例异常: x{ratio:.2f}（原 {len(orig_text)} 字，译 {len(trans_text)} 字）",
                    }
                )

        # W442: 中文占比极低（zh-only since round 52 C4）
        if len(orig_text) >= 25 and len(trans_text) >= 15:
            target_ratio = sum(1 for c in trans_text if "一" <= c <= "鿿") / len(trans_text)
            if target_ratio < MIN_CHINESE_RATIO:
                issues.append(
                    {
                        "level": "warning",
                        "code": "W442_SUSPECT_ENGLISH_OUTPUT",
                        "line": line_num,
                        "message": f"译文中中文字符占比极低（{target_ratio:.1%}），疑似未翻译",
                    }
                )

    return issues


# Ren'Py 控制标签正则（必须原样保留的文本标签）
_CONTROL_TAG_RE = re.compile(r"\{(?:w|p|nw|fast|cps=\d+)\}")

# Ren'Py 关键字/标识符（不应出现中文翻译的位置）
_RENPY_CODE_KEYWORDS = {
    "label",
    "screen",
    "init",
    "define",
    "default",
    "transform",
    "style",
    "python",
    "image",
    "jump",
    "call",
    "return",
    "pass",
    "show",
    "hide",
    "scene",
    "with",
    "play",
    "stop",
    "queue",
    "if",
    "elif",
    "else",
    "for",
    "while",
    "menu",
    "nvl",
    "window",
}


def _check_control_tags_and_keywords(
    orig: str,
    trans: str,
    line_num: int,
) -> list[dict]:
    """检查控制标签保留、过度翻译、连续标点等问题。"""
    issues: list[dict] = []

    # E250: 控制标签损坏（{w}, {p}, {nw}, {fast}, {cps=N} 必须原样保留）
    orig_tags = _CONTROL_TAG_RE.findall(orig)
    if orig_tags:
        trans_tags = _CONTROL_TAG_RE.findall(trans)
        for tag in orig_tags:
            if tag not in trans_tags:
                issues.append(
                    {
                        "level": "error",
                        "code": "E250_CONTROL_TAG_DAMAGED",
                        "line": line_num,
                        "message": f"Ren'Py 控制标签 {tag} 在译文中缺失或被修改",
                    }
                )
                break  # 同一行只报一次

    # W460: 可能过度翻译（Ren'Py 关键字出现了中文翻译）
    # 仅在行首出现的关键字后跟中文时触发
    orig_stripped = orig.strip()
    trans_stripped = trans.strip()
    if orig_stripped != trans_stripped:
        for kw in _RENPY_CODE_KEYWORDS:
            if orig_stripped.startswith(kw + " ") or orig_stripped.startswith(kw + ":"):
                # 原文以关键字开头，检查译文是否把关键字翻译了
                if not trans_stripped.startswith(kw + " ") and not trans_stripped.startswith(
                    kw + ":"
                ):
                    # 译文不再以该关键字开头，可能被翻译了
                    cn_in_prefix = any(
                        "\u4e00" <= c <= "\u9fff" for c in trans_stripped[: len(kw) + 5]
                    )
                    if cn_in_prefix:
                        issues.append(
                            {
                                "level": "warning",
                                "code": "W460_POSSIBLE_OVERTRANSLATION",
                                "line": line_num,
                                "message": f"Ren'Py 关键字 '{kw}' 可能被过度翻译",
                            }
                        )
                        break

    # W470: 连续标点（。。、！！、？？等）
    trans_text = _extract_first_quoted_text(trans) or ""
    if trans_text:
        if _RE_DOUBLE_PUNCT.search(trans_text):
            issues.append(
                {
                    "level": "warning",
                    "code": "W470_CONSECUTIVE_PUNCTUATION",
                    "line": line_num,
                    "message": "译文存在连续中文标点（如 。。、！！），建议简化",
                }
            )

    return issues


# ============================================================
# 主校验入口
# ============================================================


def validate_translation(
    original_content: str,
    translated_content: str,
    filename: str = "",
    glossary_terms: Optional[dict] = None,
    glossary_locked: Optional[set[str]] = None,
    glossary_no_translate: Optional[set[str]] = None,
    len_ratio_lower: float = 0.3,
    len_ratio_upper: float = 2.5,
) -> list[dict]:
    """全面校验翻译后的文件（规则化质量检查）

    Round 52 C4 BREAKING: lang_config kwarg retired (zh-only).

    Returns:
        [{"level": "error"|"warning", "line": N, "message": "..."}]
    """
    issues: list[dict] = []
    orig_lines = original_content.split("\n")
    trans_lines = translated_content.split("\n")

    # 行数必须一致
    if len(orig_lines) != len(trans_lines):
        issues.append(
            {
                "level": "error",
                "code": "E100_LINE_COUNT_MISMATCH",
                "line": 0,
                "message": f"行数不一致: 原 {len(orig_lines)} 行, 译 {len(trans_lines)} 行",
            }
        )
        return issues  # 行数不一致，后续检查无意义

    for i, (orig, trans) in enumerate(zip(orig_lines, trans_lines), 1):
        issues.extend(_check_structural_integrity(orig, trans, i))
        issues.extend(_check_placeholders_and_tags(orig, trans, i))
        issues.extend(
            _check_glossary_compliance(
                orig,
                trans,
                i,
                glossary_terms,
                glossary_locked,
                glossary_no_translate,
            )
        )
        issues.extend(
            _check_quality_heuristics(
                orig,
                trans,
                i,
                len_ratio_lower,
                len_ratio_upper,
            )
        )
        issues.extend(_check_control_tags_and_keywords(orig, trans, i))

    # 统计
    errors = sum(1 for i in issues if i["level"] == "error")
    warnings = sum(1 for i in issues if i["level"] == "warning")
    if issues:
        logger.info(f"[VALIDATE] {filename}: {errors} 错误, {warnings} 警告")
    else:
        logger.info(f"[VALIDATE] {filename}: OK 通过")

    return issues
