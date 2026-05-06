#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translation application/patching."""

from __future__ import annotations

import logging
import re
from typing import Optional

from file_processor.checker import _extract_placeholder_sequence

logger = logging.getLogger(__name__)


# Regex for translate strings block: old "..." and new "..."
_RE_STRINGS_OLD = re.compile(r'^\s*old\s+"((?:[^"\\]|\\.)*)"\s*$')
_RE_STRINGS_NEW = re.compile(r'^\s*new\s+"((?:[^"\\]|\\.)*)"\s*$')
_RE_STRINGS_NEW_LINE = re.compile(r'^(\s*new\s+)"((?:[^"\\]|\\.)*)"(\s*)$')


def _parse_strings_blocks(lines: list[str]) -> tuple[dict, set]:
    """Parse translate <lang> strings: blocks; return (strings_pairs, strings_old_lines).

    strings_pairs: (old_line_1based, old_text) -> {"new_line": int, "old_text": str, "new_text": str}
    strings_old_lines: set of old line numbers (1-based) for alignment skip.
    """
    strings_pairs: dict = {}
    strings_old_lines: set = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if re.match(r"^translate\s+\w+\s+strings\s*:", stripped):
            i += 1
            while i < len(lines):
                old_m = _RE_STRINGS_OLD.match(lines[i])
                if old_m:
                    old_line_no = i + 1
                    old_text = old_m.group(1) if old_m.group(1) else ""
                    i += 1
                    if i < len(lines):
                        new_m = _RE_STRINGS_NEW.match(lines[i])
                        if new_m:
                            new_line_no = i + 1
                            new_text = new_m.group(1) if new_m.group(1) else ""
                            strings_pairs[(old_line_no, old_text)] = {
                                "new_line": new_line_no,
                                "old_text": old_text,
                                "new_text": new_text,
                            }
                            strings_old_lines.add(old_line_no)
                            i += 1
                            continue
                elif stripped.startswith("translate ") or (stripped and not line[0].isspace()):
                    break
                i += 1
            continue
        i += 1
    return strings_pairs, strings_old_lines


def _align_original_with_file(
    lines: list[str], item: dict, strings_old_lines: set
) -> tuple[dict, Optional[str]]:
    """Align item['original'] to the actual quoted text on the given line.
    Only exact match + prefix/suffix (threshold 0.8). Skip lines that are strings old lines.
    Returns (item, warning_msg or None). When aligned, warning_msg is '行 N: original 已对齐'.
    """
    line_num = int(item.get("line") or 0)
    original = item.get("original", "") or ""
    if not line_num or not original:
        return item, None
    if line_num in strings_old_lines:
        return item, None
    idx = line_num - 1
    if idx < 0 or idx >= len(lines):
        return item, None
    line = lines[idx]
    # Double-quoted and single-quoted segments (handle escapes)
    dq = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
    sq = re.findall(r"'((?:[^'\\]|\\.)*)'", line)
    candidates = dq + sq
    if not candidates:
        return item, None
    norm_orig = " ".join(original.split())
    best: Optional[str] = None
    best_score = 0.0
    for seg in candidates:
        norm_seg = " ".join(seg.split())
        if seg == original or norm_seg == norm_orig:
            best = seg
            best_score = 1.0
            break
        shorter, longer = (
            (norm_orig, norm_seg) if len(norm_orig) <= len(norm_seg) else (norm_seg, norm_orig)
        )
        if not shorter:
            continue
        if longer.startswith(shorter) or longer.endswith(shorter):
            score = len(shorter) / len(longer)
            if score >= 0.8 and score > best_score:
                best = seg
                best_score = score
    if best is not None and best_score >= 0.8:
        return dict(item, original=best), f"行 {line_num}: original 已对齐"
    return item, None


def _apply_strings_translations(
    lines: list[str], strings_items: list[dict], strings_pairs: dict
) -> tuple[int, list[str]]:
    """Apply translations for translate strings entries only; write to new "" lines.
    Returns (applied_count, warnings).
    """
    applied = 0
    warnings: list[str] = []
    for item in strings_items:
        line_num = item.get("line", 0)
        original = item.get("original", "")
        zh = item.get("zh", "")
        if not original or not zh:
            continue
        key = (line_num, original)
        pair = strings_pairs.get(key)
        if not pair:
            continue
        new_line_no = pair["new_line"]
        idx = new_line_no - 1
        if idx < 0 or idx >= len(lines):
            continue
        line_text = lines[idx]
        m = _RE_STRINGS_NEW_LINE.match(line_text)
        if not m:
            warnings.append(f"行 {new_line_no}: strings new 行格式异常，跳过")
            continue
        escaped_zh = _escape_for_renpy_string(zh, '"')
        new_line = m.group(1) + '"' + escaped_zh + '"' + m.group(3)
        lines[idx] = new_line
        applied += 1
    return applied, warnings


def _build_writeback_diag_index(lines: list[str]) -> list[str]:
    """Pre-compute NFKC-normalised lines for ``_diagnose_writeback_failure``.

    Round 26 PF-H-3: the per-item diagnosis loop used to re-normalise every
    file line for every failed entry (``O(lines × failures)`` NFKC calls).
    Callers with many failures should build this index once via
    ``apply_translations`` and pass it as ``norm_lines`` to each
    ``_diagnose_writeback_failure`` call.
    """
    import unicodedata

    return [unicodedata.normalize("NFKC", line) for line in lines]


def _diagnose_writeback_failure(
    lines: list[str],
    item: dict,
    modified_lines: set[int],
    *,
    norm_lines: list[str] | None = None,
) -> dict:
    """分析单条回写失败的根因，返回诊断信息。

    失败类型：
      WF-01: 行号偏移过大（原文存在但不在 ±50 行内）
      WF-02: 原文被截断（AI 返回的 original 是文件中文本的子串）
      WF-03: 原文被修改（AI 返回的 original 与文件中任何行都不匹配）
      WF-04: 引号嵌套冲突（原文含转义引号）
      WF-05: 跨行文本（原文含换行符）
      WF-06: 重复原文冲突（同一原文已被其他匹配消费）
      WF-07: 编码不一致（Unicode 规范化差异）

    ``norm_lines`` is an optional pre-computed list of NFKC-normalised
    ``lines``; pass it when calling this in a loop over many items to
    avoid re-normalising the whole file for every failure.
    """
    import unicodedata

    line_num = item.get("line", 0)
    original = item.get("original", "")
    zh = item.get("zh", "")
    idx = line_num - 1

    diag: dict = {
        "line": line_num,
        "original": original[:100],
        "zh": zh[:100],
        "failure_type": "WF-08",  # 默认：其他
        "detail": "",
    }

    if not original:
        diag["failure_type"] = "WF-03"
        diag["detail"] = "original 为空"
        return diag

    # WF-05: 跨行文本
    if "\n" in original or '"""' in original:
        diag["failure_type"] = "WF-05"
        diag["detail"] = "原文含换行符或三引号"
        return diag

    # WF-04: 引号嵌套冲突
    if '\\"' in original or "\\'" in original:
        diag["failure_type"] = "WF-04"
        diag["detail"] = "原文含转义引号"
        # 不 return，可能还有更具体的原因，继续检查

    # 在全文中搜索原文（若未传入 norm_lines 则惰性计算一次）
    norm_original = unicodedata.normalize("NFKC", original)
    if norm_lines is None:
        norm_lines = [unicodedata.normalize("NFKC", line) for line in lines]
    found_at: list[int] = []
    for i, line in enumerate(lines):
        if original in line:
            found_at.append(i)
        elif norm_original in norm_lines[i]:
            found_at.append(i)

    if not found_at:
        # 全文都找不到 → 检查是否为截断
        for i, line in enumerate(lines):
            # 提取行中引号内文本
            quoted = _extract_first_quoted_text(line)
            if not quoted:
                continue
            # 前缀/后缀截断检测
            if len(original) >= 10 and (quoted.startswith(original) or quoted.endswith(original)):
                diag["failure_type"] = "WF-02"
                diag["detail"] = f"原文是行 {i + 1} 引号文本的截断（完整: {quoted[:60]}）"
                return diag
            # 包含关系
            if len(original) >= 10 and original in quoted and len(original) / len(quoted) >= 0.4:
                diag["failure_type"] = "WF-02"
                diag["detail"] = f"原文是行 {i + 1} 引号文本的子串"
                return diag

        # 完全不匹配
        if diag["failure_type"] == "WF-04":
            return diag  # 已标记为引号冲突
        diag["failure_type"] = "WF-03"
        diag["detail"] = "原文与文件中任何行都不匹配"
        return diag

    # 原文存在于文件中
    # WF-06: 检查是否被 modified_lines 消费
    if all(i in modified_lines for i in found_at):
        diag["failure_type"] = "WF-06"
        diag["detail"] = f"原文在 {len(found_at)} 处出现，全部已被其他翻译占用"
        return diag

    # WF-01: 行号偏移过大
    if found_at:
        nearest = min(found_at, key=lambda i: abs(i - idx))
        offset = abs(nearest - idx)
        if offset > 50:
            diag["failure_type"] = "WF-01"
            diag["detail"] = f"最近匹配在行 {nearest + 1}（偏移 {offset}）"
            return diag
        # 在 ±50 范围内但 _replace_string_in_line 失败
        # 可能是引号格式问题
        if diag["failure_type"] == "WF-04":
            return diag
        diag["failure_type"] = "WF-08"
        diag["detail"] = f"原文在行 {nearest + 1} 存在但 _replace_string_in_line 返回 None"
        return diag

    return diag


def apply_translations(
    original_content: str, translations: list[dict]
) -> tuple[str, list[str], dict]:
    """将翻译结果应用到原始文件

    核心安全策略：只替换引号内的字符串内容，绝不修改代码结构
    四遍匹配策略：精确 -> 近偏移 -> 远偏移 -> 全文扫描
    安全检查可自动修复常见变量问题

    Args:
        original_content: 原始文件内容
        translations: [{"line": N, "original": "...", "zh": "..."}, ...]

    Returns:
        (patched_content, warnings, stats)
        stats: {"alignment_count": int, "strings_applied_count": int}
    """
    lines = original_content.split("\n")
    warnings = []
    applied = 0
    skipped = 0
    auto_fixed = 0
    alignment_count = 0
    strings_applied_count = 0

    # 解析 translate strings 块，供专用回写与对齐跳过
    strings_pairs, strings_old_lines = _parse_strings_blocks(lines)

    # 预过滤：original 对齐 -> 安全检查（支持自动修复）
    safe_items = []
    for item in translations:
        line_num = item.get("line", 0)
        original = item.get("original", "")
        zh = item.get("zh", "")

        if not original or not zh:
            continue

        # 方案 b：用该行真实引号文本覆盖 AI 返回的 original（strings 的 old 行不参与对齐）
        item, align_msg = _align_original_with_file(lines, item, strings_old_lines)
        if align_msg:
            warnings.append(align_msg)
            alignment_count += 1
        original = item.get("original", "")
        zh = item.get("zh", "")

        issue = _check_translation_safety(original, zh)
        if issue:
            # 语义变更：W251（占位符顺序不一致）仅告警，仍允许应用翻译，不跳过
            if "W251" in issue:
                safe_items.append(item)
                warnings.append(f"行 {line_num}: {issue}，已应用翻译")
                continue
            # 尝试自动修复变量/标签问题
            fixed_zh = _auto_fix_translation(original, zh)
            if fixed_zh and fixed_zh != zh:
                recheck = _check_translation_safety(original, fixed_zh)
                if not recheck:
                    item = dict(item, zh=fixed_zh)
                    auto_fixed += 1
                else:
                    warnings.append(f"行 {line_num}: 安全检查失败 - {issue}")
                    skipped += 1
                    continue
            else:
                warnings.append(f"行 {line_num}: 安全检查失败 - {issue}")
                skipped += 1
                continue
        safe_items.append(item)

    # 方案 a：translate strings 专用回写，不经过 _replace_string_in_line
    strings_items = []
    normal_items = []
    for item in safe_items:
        key = (item.get("line", 0), item.get("original", ""))
        if key in strings_pairs:
            strings_items.append(item)
        else:
            normal_items.append(item)
    applied_strings, strings_warnings = _apply_strings_translations(
        lines, strings_items, strings_pairs
    )
    applied += applied_strings
    strings_applied_count = applied_strings
    warnings.extend(strings_warnings)

    # 记录已应用的 (行号, 原文) 对 -- 允许同行多次翻译不同文本
    applied_pairs = set()
    # 记录已被修改的行号集合 -- 第四遍全文扫描时跳过已修改行，防止同一原文多次出现时误替换
    modified_lines: set[int] = set()

    def _try_apply(try_idx: int, original: str, zh: str, full_scan: bool = False) -> bool:
        """尝试在指定行应用翻译。full_scan=True 时跳过已修改行。"""
        if try_idx < 0 or try_idx >= len(lines):
            return False
        if (try_idx, original) in applied_pairs:
            return False
        if full_scan and try_idx in modified_lines:
            return False
        new_line = _replace_string_in_line(lines[try_idx], original, zh)
        if new_line is not None:
            lines[try_idx] = new_line
            applied_pairs.add((try_idx, original))
            modified_lines.add(try_idx)
            return True
        return False

    # 回写失败诊断：记录四遍匹配全部失败的条目及失败类型
    writeback_failures: list[dict] = []

    # 第一遍：精确行号匹配（仅 normal 条目）
    remaining = []
    for item in normal_items:
        line_num = item.get("line", 0)
        original = item.get("original", "")
        zh = item.get("zh", "")
        idx = line_num - 1
        if _try_apply(idx, original, zh):
            applied += 1
        else:
            remaining.append(item)

    # 第二遍：近偏移搜索（+-5行范围）-- 不报警告
    still_remaining = []
    for item in remaining:
        line_num = item.get("line", 0)
        original = item.get("original", "")
        zh = item.get("zh", "")
        idx = line_num - 1
        found = False

        for delta in [-1, 1, -2, 2, -3, 3, -4, 4, -5, 5]:
            if _try_apply(idx + delta, original, zh):
                found = True
                applied += 1
                break

        if not found:
            still_remaining.append(item)

    # 第三遍：远偏移搜索（+-50行范围）-- 不报警告
    far_remaining = []
    for item in still_remaining:
        line_num = item.get("line", 0)
        original = item.get("original", "")
        zh = item.get("zh", "")
        idx = line_num - 1
        found = False

        for try_idx in range(max(0, idx - 50), min(len(lines), idx + 51)):
            if _try_apply(try_idx, original, zh):
                found = True
                applied += 1
                break

        if not found:
            far_remaining.append(item)

    # 第四遍：全文扫描（针对仍未匹配的项）
    # full_scan=True：跳过已被前面 pass 修改过的行，防止同一原文多次出现时误替换到错误位置
    # Round 26 PF-H-3: pre-compute NFKC-normalised lines once for all
    # failure diagnoses in this file instead of re-normalising per item.
    norm_lines_for_diag: list[str] | None = None
    for item in far_remaining:
        line_num = item.get("line", 0)
        original = item.get("original", "")
        zh = item.get("zh", "")
        found = False

        for try_idx in range(len(lines)):
            if _try_apply(try_idx, original, zh, full_scan=True):
                found = True
                applied += 1
                break

        if not found:
            warnings.append(f'行 {line_num}: 未找到原文 "{original[:50]}"')
            skipped += 1
            # 诊断：分析失败原因
            if norm_lines_for_diag is None:
                norm_lines_for_diag = _build_writeback_diag_index(lines)
            diag = _diagnose_writeback_failure(
                lines,
                item,
                modified_lines,
                norm_lines=norm_lines_for_diag,
            )
            writeback_failures.append(diag)

    parts = [f"应用 {applied}"]
    if skipped:
        parts.append(f"跳过 {skipped}")
    if auto_fixed:
        parts.append(f"自动修复 {auto_fixed}")
    if applied > 0 or skipped > 0:
        logger.debug(f"[PATCH] {', '.join(parts)} 条翻译")

    stats = {
        "alignment_count": alignment_count,
        "strings_applied_count": strings_applied_count,
        "writeback_failures": writeback_failures,
    }
    return "\n".join(lines), warnings, stats


def _replace_string_in_line(line: str, original: str, replacement: str) -> Optional[str]:
    """在一行中替换引号内的字符串内容

    只替换引号内的文本，保持引号和周围代码不变。
    支持 Ren'Py 格式标签 ({i}, {b}, {color}, 等)。
    支持 AI 截断的模糊匹配。
    """
    # 统一先做字符串安全转义，避免把译文中的引号直接注入代码结构
    safe_replacement_dq = _escape_for_renpy_string(replacement, '"')
    safe_replacement_sq = _escape_for_renpy_string(replacement, "'")

    # === 阶段 1：精确匹配 ===
    for quote in ('"', "'"):
        pattern = f"{quote}{original}{quote}"
        if pattern in line:
            safe_replacement = safe_replacement_dq if quote == '"' else safe_replacement_sq
            return line.replace(pattern, f"{quote}{safe_replacement}{quote}", 1)

    # 尝试处理转义引号
    escaped = original.replace('"', '\\"')
    if escaped != original and f'"{escaped}"' in line:
        return line.replace(f'"{escaped}"', f'"{safe_replacement_dq}"', 1)

    # 尝试三引号
    if f'"""{original}"""' in line:
        return line.replace(f'"""{original}"""', f'"""{safe_replacement_dq}"""', 1)

    # 尝试 _() 包裹
    if f'_("{original}")' in line:
        return line.replace(f'_("{original}")', f'_("{safe_replacement_dq}")', 1)

    # === 阶段 1b：AI 返回了含 Ren'Py 行前缀的 original（如 'text _("...'），剥离后重试 ===
    stripped_original = original
    for prefix_pattern in (
        r'^(?:text\s+)?_\(\s*"',  # text _(" 或 _("
        r'^\s*text\s+"',  # text "
        r'^\s*textbutton\s+"',  # textbutton "
    ):
        m = re.match(prefix_pattern, stripped_original)
        if m:
            stripped_original = stripped_original[m.end() :]
            # 去掉可能的尾部引号/括号
            stripped_original = stripped_original.rstrip('"').rstrip(")").rstrip('"')
            break
    if stripped_original != original and stripped_original:
        # 用剥离后的原文重试阶段1
        for quote in ('"', "'"):
            pattern = f"{quote}{stripped_original}{quote}"
            if pattern in line:
                safe_replacement = safe_replacement_dq if quote == '"' else safe_replacement_sq
                return line.replace(pattern, f"{quote}{safe_replacement}{quote}", 1)
        if f'_("{stripped_original}")' in line:
            return line.replace(f'_("{stripped_original}")', f'_("{safe_replacement_dq}")', 1)

    # === 阶段 2：标准化空白匹配 ===
    norm_original = " ".join(original.split())
    if norm_original != original:
        for quote in ('"', "'"):
            pattern = f"{quote}{norm_original}{quote}"
            if pattern in line:
                safe_replacement = safe_replacement_dq if quote == '"' else safe_replacement_sq
                return line.replace(pattern, f"{quote}{safe_replacement}{quote}", 1)

    # === 阶段 3：从行中提取引号内文本，尝试高级匹配 ===
    # 找到行中所有引号内的文本段（支持转义引号 \"）
    quoted_parts = re.findall(r'"((?:[^"\\]|\\.)+)"', line)
    if not quoted_parts:
        return None

    for line_text in quoted_parts:
        # 3a. 精确比较
        if line_text == original:
            return line.replace(f'"{line_text}"', f'"{safe_replacement_dq}"', 1)

        # 3b. 标准化空白比较
        if " ".join(line_text.split()) == norm_original:
            return line.replace(f'"{line_text}"', f'"{safe_replacement_dq}"', 1)

        # 3c. Ren'Py 格式标签处理：去掉标签后比较
        stripped_text = re.sub(r"\{/?[^}]+\}", "", line_text)
        if not stripped_text:
            continue

        norm_stripped = " ".join(stripped_text.split())
        if stripped_text == original or norm_stripped == norm_original:
            # 提取前缀标签和后缀标签，翻译时保留标签结构
            prefix_m = re.match(r"((?:\{[^}]+\})+)", line_text)
            prefix_tags = prefix_m.group(0) if prefix_m else ""
            suffix_m = re.search(r"((?:\{/[^}]+\})+)$", line_text)
            suffix_tags = suffix_m.group(0) if suffix_m else ""
            new_text = prefix_tags + safe_replacement_dq + suffix_tags
            return line.replace(f'"{line_text}"', f'"{new_text}"', 1)

        # 3d. 标签子串匹配 -- 原文是被标签包裹的更大文本的一部分
        tag_wrapped_re = re.compile(r"(\{[^/][^}]*\})" + re.escape(original) + r"(\{/[^}]+\})")
        tw_match = tag_wrapped_re.search(line_text)
        if tw_match:
            old_segment = tw_match.group(0)
            new_segment = tw_match.group(1) + replacement + tw_match.group(2)
            new_line_text = line_text.replace(old_segment, new_segment, 1)
            return line.replace(f'"{line_text}"', f'"{new_line_text}"', 1)

        # 3e. AI 截断匹配 -- AI 可能只返回了部分文本
        if len(original) >= 15:
            # AI 的文本可能是原文去掉标签后截断的前缀
            if stripped_text.startswith(original) or norm_stripped.startswith(norm_original):
                # 如果有标签且 AI 覆盖了足够多的原文，视为有效的截断匹配
                has_tags = line_text != stripped_text
                ratio = len(original) / len(stripped_text) if stripped_text else 0
                if has_tags and ratio >= 0.7:
                    prefix_m = re.match(r"((?:\{[^}]+\})+)", line_text)
                    prefix_tags = prefix_m.group(0) if prefix_m else ""
                    suffix_m = re.search(r"((?:\{/[^}]+\})+)$", line_text)
                    suffix_tags = suffix_m.group(0) if suffix_m else ""
                    new_text = prefix_tags + safe_replacement_dq + suffix_tags
                    return line.replace(f'"{line_text}"', f'"{new_text}"', 1)
                # 无标签时，截断前缀不安全，跳过
                continue
            # 反过来：AI 返回完整但源文件更长（AI 省略了几个词）
            if original.startswith(stripped_text[:15]) and len(original) > len(stripped_text):
                # AI 返回的更长，不安全匹配
                continue
            # AI 截断了文本末尾（警告中显示50字符截断）
            if len(original) >= 45 and stripped_text.startswith(original[:40]):
                prefix_m = re.match(r"((?:\{[^}]+\})+)", line_text)
                prefix_tags = prefix_m.group(0) if prefix_m else ""
                suffix_m = re.search(r"((?:\{/[^}]+\})+)$", line_text)
                suffix_tags = suffix_m.group(0) if suffix_m else ""
                new_text = prefix_tags + safe_replacement_dq + suffix_tags
                return line.replace(f'"{line_text}"', f'"{new_text}"', 1)

    # === 阶段 3f：用剥离前缀后的 original 在 quoted_parts 中再找一次 ===
    if stripped_original != original and stripped_original and quoted_parts:
        norm_stripped_orig = " ".join(stripped_original.split())
        for line_text in quoted_parts:
            if line_text == stripped_original:
                return line.replace(f'"{line_text}"', f'"{safe_replacement_dq}"', 1)
            if " ".join(line_text.split()) == norm_stripped_orig:
                return line.replace(f'"{line_text}"', f'"{safe_replacement_dq}"', 1)
            # 去标签后比较
            stripped_lt = re.sub(r"\{/?[^}]+\}", "", line_text)
            if (
                stripped_lt == stripped_original
                or " ".join(stripped_lt.split()) == norm_stripped_orig
            ):
                prefix_m = re.match(r"((?:\{[^}]+\})+)", line_text)
                prefix_tags = prefix_m.group(0) if prefix_m else ""
                suffix_m = re.search(r"((?:\{/[^}]+\})+)$", line_text)
                suffix_tags = suffix_m.group(0) if suffix_m else ""
                new_text = prefix_tags + safe_replacement_dq + suffix_tags
                return line.replace(f'"{line_text}"', f'"{new_text}"', 1)

    return None


def _escape_for_renpy_string(text: str, quote: str = '"') -> str:
    """将译文转义为可安全写入 Ren'Py 字符串的内容。"""
    escaped = text.replace("\\", "\\\\").replace("\r", "")
    escaped = escaped.replace("\n", r"\n")
    if quote == '"':
        escaped = escaped.replace('"', r"\"")
    else:
        escaped = escaped.replace("'", r"\\'")
    return escaped


def _count_unescaped_quote(line: str, quote: str) -> int:
    """统计一行内未被反斜杠转义的引号数量。"""
    count = 0
    escaped = False
    for ch in line:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == quote:
            count += 1
    return count


def _extract_first_quoted_text(line: str) -> Optional[str]:
    """提取行内首个双引号字符串内容。"""
    m = re.search(r'"((?:[^"\\]|\\.)*)"', line)
    return m.group(1) if m else None


def _strip_double_quoted_segments(line: str) -> str:
    """移除双引号字符串片段，避免将对话中的英文缩写单引号误判为结构变化。"""
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)


def _auto_fix_translation(original: str, zh: str) -> Optional[str]:
    """尝试自动修复翻译中的变量/标签问题

    常见问题：AI 翻译了变量名（如 [mother] -> [母亲]），或丢失/多出变量。
    """
    # 修复变量：将原文中的变量占位符恢复到译文中
    orig_vars = re.findall(r"\[\w+\]", original)
    zh_vars = re.findall(r"\[\w+\]", zh)
    orig_var_names = set(re.findall(r"\[(\w+)\]", original))
    zh_var_names = set(re.findall(r"\[(\w+)\]", zh))

    fixed = zh
    missing = orig_var_names - zh_var_names
    extra = zh_var_names - orig_var_names

    if missing and extra and len(missing) == len(extra):
        # AI 可能翻译了变量名，逐个替换回来
        # 尝试按位置匹配
        for extra_var in list(extra):
            # 找最可能对应的原始变量
            for miss_var in list(missing):
                zh_pattern = f"[{extra_var}]"
                if zh_pattern in fixed:
                    fixed = fixed.replace(zh_pattern, f"[{miss_var}]", 1)
                    extra.discard(extra_var)
                    missing.discard(miss_var)
                    break
    elif missing and not extra:
        # 变量丢失：AI 删除了变量引用，无法安全修复
        return None

    # 修复标签：确保 Ren'Py 标签匹配
    orig_tags = re.findall(r"\{/?[a-z]+=?[^}]*\}", original, re.I)
    zh_tags = re.findall(r"\{/?[a-z]+=?[^}]*\}", fixed, re.I)
    if sorted(orig_tags) != sorted(zh_tags):
        # 如果原文有标签但译文没有，AI 可能故意移除了（因为我们会在匹配时重新加上）
        # 不自动修复标签
        if not orig_tags and zh_tags:
            # 译文多出标签，尝试移除
            fixed = re.sub(r"\{/?[a-z]+=?[^}]*\}", "", fixed, flags=re.I)
        else:
            return None

    return fixed if fixed != zh else None


def _check_translation_safety(original: str, zh: str) -> Optional[str]:
    """检查翻译是否安全（不会破坏游戏）

    Returns:
        问题描述字符串，如果安全返回 None
    """
    # 检查变量占位符是否保留
    orig_vars = set(re.findall(r"\[(\w+)\]", original))
    zh_vars = set(re.findall(r"\[(\w+)\]", zh))
    missing_vars = orig_vars - zh_vars
    if missing_vars:
        return f"变量丢失: {missing_vars}"
    extra_vars = zh_vars - orig_vars
    if extra_vars:
        return f"变量多出: {extra_vars}"

    # 检查 Ren'Py 标签是否保留
    orig_tags = re.findall(r"\{/?[a-z]+=?[^}]*\}", original, re.I)
    zh_tags = re.findall(r"\{/?[a-z]+=?[^}]*\}", zh, re.I)
    if sorted(orig_tags) != sorted(zh_tags):
        return f"标签不匹配: 原={orig_tags}, 译={zh_tags}"

    # 检查换行符数量是否一致（统一用字面量 '\n' 比较）
    if original.count("\\n") != zh.count("\\n"):
        return f"换行符数量不匹配: 原={original.count(chr(92) + 'n')}, 译={zh.count(chr(92) + 'n')}"

    # 检查 {#identifier} 菜单标识符是否保留
    orig_ids = re.findall(r"\{#[^}]+\}", original)
    zh_ids = re.findall(r"\{#[^}]+\}", zh)
    if sorted(orig_ids) != sorted(zh_ids):
        return f"菜单标识符不匹配: 原={orig_ids}, 译={zh_ids}"

    # 检查 %(name)s 格式化占位符是否保留
    orig_fmt = set(re.findall(r"%\([^)]+\)[sd]", original))
    zh_fmt = set(re.findall(r"%\([^)]+\)[sd]", zh))
    if orig_fmt != zh_fmt:
        return f"格式化占位符不匹配: 原={orig_fmt}, 译={zh_fmt}"

    # 检查翻译长度比例是否合理（只对较长文本检查）
    if len(original) > 30:
        ratio = len(zh) / len(original)
        if ratio > 3.0:
            return f"译文异常过长 (x{ratio:.1f})，可能包含多余内容"
        if ratio < 0.05:
            return f"译文异常过短 (x{ratio:.2f})，可能截断"

    # 占位符顺序校验：仅在集合已一致时执行，顺序不同标 W251（语义：允许 apply，仅告警）
    orig_seq = _extract_placeholder_sequence(original)
    zh_seq = _extract_placeholder_sequence(zh)
    if set(orig_seq) == set(zh_seq) and orig_seq != zh_seq:
        return "占位符顺序与原文不一致 (W251)"

    return None
