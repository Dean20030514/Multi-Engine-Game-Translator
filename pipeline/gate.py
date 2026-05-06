#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline.gate -- Gate evaluation and reporting for the one-click pipeline."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from file_processor import read_file, validate_translation
from core.translation_db import TranslationDB
from translators.renpy_text_utils import (
    count_untranslated_dialogues_in_file,
    collect_untranslated_details,
)

from pipeline.helpers import list_rpy_files, _normalize_ws
from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)

# Round 39 M2 phase-2: reject glossary.json files above 50 MB before
# ``json.loads`` reads them.  Matches the cap used in
# ``core/glossary.py`` / ``core/translation_db.py`` for consistency.
# Exceeding the cap degrades gate checks the same way a malformed
# glossary does (locked-term / no-translate checks disabled +
# WARNING in the pipeline log per the r26 H-4 contract).
_MAX_GATE_GLOSSARY_SIZE = 50 * 1024 * 1024


def attribute_untranslated(
    translated_root: Path,
    db: TranslationDB,
) -> dict:
    """归因分析：对每个漏翻行查询 translation_db 判断根因。

    分类规则：
      - translation_db 中无记录 → ai_missing（AI 根本没返回）
      - 记录 status == "checker_dropped" → checker_dropped（AI 返回了但被校验丢弃）
      - 记录 status in (ok, warning, error) → write_fail（翻译了但回写失败）
      - 其他 → unknown

    匹配策略：先精确匹配 (file, original)，失败后 fallback 到
    空白标准化匹配，以应对 AI 返回文本与文件提取文本的微小空白差异。
    """
    db_lookup: dict[tuple[str, str], str] = {}
    db_lookup_norm: dict[tuple[str, str], str] = {}
    for entry in db.entries:
        f = entry.get("file", "")
        orig = entry.get("original", "")
        status = entry.get("status", "")
        if f and orig:
            db_lookup[(f, orig)] = status
            norm_key = (f, _normalize_ws(orig))
            if norm_key not in db_lookup_norm:
                db_lookup_norm[norm_key] = status

    ai_missing = 0
    checker_dropped = 0
    write_fail = 0
    unknown = 0
    fallback_matched = 0

    for trans_file in list_rpy_files(translated_root):
        rel = str(trans_file.relative_to(translated_root))
        for _line_no, original_text in collect_untranslated_details(trans_file):
            status = db_lookup.get((rel, original_text))
            if status is None:
                norm_status = db_lookup_norm.get((rel, _normalize_ws(original_text)))
                if norm_status is not None:
                    status = norm_status
                    fallback_matched += 1
            if status is None:
                ai_missing += 1
            elif status == "checker_dropped":
                checker_dropped += 1
            elif status in ("ok", "warning", "error"):
                write_fail += 1
            else:
                unknown += 1

    total = ai_missing + checker_dropped + write_fail + unknown
    return {
        "total": total,
        "ai_missing": ai_missing,
        "checker_dropped": checker_dropped,
        "write_fail": write_fail,
        "unknown": unknown,
        "db_entries_count": len(db.entries),
        "fallback_matched": fallback_matched,
    }


def evaluate_gate(original_root: Path, translated_root: Path) -> dict:
    """闸门：结构错误必须为 0；给出漏翻与长度异常统计。"""
    from pipeline.helpers import LEN_RATIO_LOWER, LEN_RATIO_UPPER

    errors = 0
    warnings = 0
    dialogue_total = 0
    untranslated_total = 0
    len_ratio_warnings = 0
    placeholder_order_warnings = 0
    code_histogram: dict[str, int] = {}
    error_histogram: dict[str, int] = {}
    warning_histogram: dict[str, int] = {}
    glossary_lock_errors = 0
    no_translate_errors = 0
    glossary_miss_warnings = 0
    placeholder_issues = 0

    # 尝试从翻译输出目录旁边加载 glossary.json，以便在闸门阶段也统计锁定术语和禁翻片段违规
    glossary_terms = None
    glossary_locked = None
    glossary_no_translate = None
    try:
        base_dir = translated_root
        # glossary.json 通常位于输出根目录（可能是 translated_root 或其父目录）
        if not (base_dir / "glossary.json").exists():
            base_dir = translated_root.parent
        glossary_path = base_dir / "glossary.json"
        if glossary_path.exists():
            # Round 39 M2: size-cap before read.  Oversized glossary
            # triggers the same degradation path as a malformed one
            # (disables locked-term / no-translate checks with a
            # WARNING; rest of the gate keeps running).
            try:
                glossary_size = glossary_path.stat().st_size
            except OSError:
                glossary_size = 0
            if glossary_size > _MAX_GATE_GLOSSARY_SIZE:
                raise OSError(
                    f"glossary.json too large "
                    f"({glossary_size} bytes > {_MAX_GATE_GLOSSARY_SIZE} cap)"
                )
            # Round 49 Step 2: TOCTOU defense via check_fstat_size.  Raises
            # OSError on cap violation so the existing except branch downstream
            # logs the gate degradation per the r26 H-4 contract.
            with open(glossary_path, encoding="utf-8") as f:
                ok, fsize2 = check_fstat_size(f, _MAX_GATE_GLOSSARY_SIZE)
                if not ok:
                    raise OSError(
                        f"glossary.json grew past cap after stat (TOCTOU?): "
                        f"{fsize2} bytes > {_MAX_GATE_GLOSSARY_SIZE} cap"
                    )
                data = json.loads(f.read())
            glossary_terms = data.get("terms", {}) or None
            locked_list = data.get("locked_terms", [])
            no_trans_list = data.get("no_translate", [])
            glossary_locked = set(locked_list) if locked_list else None
            glossary_no_translate = set(no_trans_list) if no_trans_list else None
    except (OSError, json.JSONDecodeError, KeyError) as e:
        # Round 26 H-4: a malformed glossary silently disables locked-term /
        # no-translate checks, which the user cannot otherwise detect. Upgrade
        # to WARNING so the pipeline log shows the degradation.
        logger.warning("[GATE] glossary 加载失败，锁定术语/禁翻检查已跳过: %s", e)
        glossary_terms = None
        glossary_locked = None
        glossary_no_translate = None

    translated_files = list_rpy_files(translated_root)
    for trans_file in translated_files:
        rel = trans_file.relative_to(translated_root)
        orig_file = original_root / rel
        if not orig_file.exists():
            # Round 26 M-1: surface the missing source file so the user can
            # see which translation has no origin to compare against,
            # instead of just counting into warnings silently.
            logger.warning("[GATE] 缺失原文件，跳过校验: %s", rel)
            warnings += 1
            continue

        issues = validate_translation(
            read_file(orig_file),
            read_file(trans_file),
            str(rel),
            glossary_terms=glossary_terms,
            glossary_locked=glossary_locked,
            glossary_no_translate=glossary_no_translate,
            len_ratio_lower=LEN_RATIO_LOWER,
            len_ratio_upper=LEN_RATIO_UPPER,
        )
        for issue in issues:
            level = issue.get("level")
            code = issue.get("code") or ""
            if level == "error":
                errors += 1
            elif level == "warning":
                warnings += 1

            if code:
                code_histogram[code] = code_histogram.get(code, 0) + 1
                if level == "error":
                    error_histogram[code] = error_histogram.get(code, 0) + 1
                elif level == "warning":
                    warning_histogram[code] = warning_histogram.get(code, 0) + 1

                if code == "E411_GLOSSARY_LOCK_MISS":
                    glossary_lock_errors += 1
                elif code == "E420_NO_TRANSLATE_CHANGED":
                    no_translate_errors += 1
                elif code == "W410_GLOSSARY_MISS":
                    glossary_miss_warnings += 1

                if code in {
                    "E210_VAR_MISSING",
                    "W211_VAR_EXTRA",
                    "E220_TEXT_TAG_MISMATCH",
                    "E230_MENU_ID_MISMATCH",
                    "E240_FMT_PLACEHOLDER_MISMATCH",
                    "W251_PLACEHOLDER_ORDER",
                }:
                    placeholder_issues += 1

        len_ratio_warnings += sum(1 for i in issues if i.get("code") == "W430_LEN_RATIO_SUSPECT")
        placeholder_order_warnings += sum(
            1 for i in issues if i.get("code") == "W251_PLACEHOLDER_ORDER"
        )

        d, u = count_untranslated_dialogues_in_file(trans_file)
        dialogue_total += d
        untranslated_total += u

    ratio = (untranslated_total / dialogue_total) if dialogue_total else 0.0
    len_ratio_warning_ratio = (len_ratio_warnings / dialogue_total) if dialogue_total else 0.0
    return {
        "files": len(translated_files),
        "errors": errors,
        "warnings": warnings,
        "dialogue_total": dialogue_total,
        "untranslated_total": untranslated_total,
        "untranslated_ratio": round(ratio, 6),
        "len_ratio_warnings": len_ratio_warnings,
        "len_ratio_warning_ratio": round(len_ratio_warning_ratio, 6),
        "placeholder_order_warnings": placeholder_order_warnings,
        "code_histogram": code_histogram,
        "error_histogram": error_histogram,
        "warning_histogram": warning_histogram,
        "glossary_lock_errors": glossary_lock_errors,
        "no_translate_errors": no_translate_errors,
        "glossary_miss_warnings": glossary_miss_warnings,
        "placeholder_issues": placeholder_issues,
    }


def collect_files_with_untranslated(translated_root: Path) -> list[Path]:
    result = []
    for p in list_rpy_files(translated_root):
        _, u = count_untranslated_dialogues_in_file(p)
        if u > 0:
            result.append(p)
    return result


# merge_incremental_results 已被 retranslate 模式替代（原地补翻，无需 merge）


def collect_strings_stats(root: Path) -> dict:
    """统计 translate ... strings: 块中的 old/new 条目翻译情况。

    规则说明：
    - 仅统计 `translate <lang> strings:` 块中的 `old`/`new` 对。
    - 当 `new` 为空或与 `old` 文本相同（忽略首尾空白）时，视为"未翻译"。
      这其中可能包含有意保留原文的条目，请结合具体项目判断。
    """
    files_info: list[dict] = []
    total_entries = 0
    total_translated = 0
    total_untranslated = 0

    for path in list_rpy_files(root):
        rel = path.relative_to(root)
        try:
            text = read_file(path)
        except OSError:
            continue

        in_strings = False
        current_old: str | None = None
        file_total = 0
        file_translated = 0
        file_untranslated = 0

        for line in text.splitlines():
            stripped = line.lstrip()

            # 1) 优先判断是否进入新的 translate 块（包括 strings 块）
            m_tr = re.match(r"^translate\s+(\w+)\s+(\w+)\s*:", stripped)
            if m_tr:
                lang, block_name = m_tr.groups()
                if block_name == "strings":
                    in_strings = True
                else:
                    # 新的非 strings translate 块，结束当前 strings 块
                    in_strings = False
                current_old = None
                continue

            if not in_strings:
                continue

            # 2) 在 strings 块内解析 old/new 行
            m_old = re.match(r'^\s*old\s+"(.*)"\s*$', line)
            if m_old:
                current_old = m_old.group(1)
                continue

            m_new = re.match(r'^\s*new\s+"(.*)"\s*$', line)
            if m_new and current_old is not None:
                new_text = m_new.group(1)
                file_total += 1
                total_entries += 1

                # new 为空或与 old 文本相同（忽略首尾空白）视为未翻译
                if not new_text.strip() or new_text.strip() == str(current_old).strip():
                    file_untranslated += 1
                    total_untranslated += 1
                else:
                    file_translated += 1
                    total_translated += 1

                current_old = None

        if file_total > 0:
            files_info.append(
                {
                    "file": str(rel),
                    "strings_total": file_total,
                    "strings_translated": file_translated,
                    "strings_untranslated": file_untranslated,
                }
            )

    summary = {
        "total_files_with_strings": len(files_info),
        "total_strings_entries": total_entries,
        "total_strings_translated": total_translated,
        "total_strings_untranslated": total_untranslated,
        "untranslated_ratio": round(
            (total_untranslated / total_entries) if total_entries else 0.0, 6
        ),
        "note": "统计基于 translate <lang> strings: 块；new 为空或与 old 相同（忽略首尾空白）视为未翻译，其中部分可能是有意保留原文。",
    }

    return {"summary": summary, "files": files_info}


def write_report_summary_md(
    project_out_root: Path,
    report: dict,
    gate_max_untranslated_ratio: float,
) -> None:
    """基于 pipeline_report.json 的结构化概要，生成 report_summary.md。"""
    final_gate = report.get("stages", {}).get("final_gate") or {}
    pilot_gate = report.get("stages", {}).get("pilot", {}).get("gate") or {}
    full_gate = report.get("stages", {}).get("full", {}).get("gate") or {}
    strings_stats = report.get("stages", {}).get("strings_stats", {})
    cfg = report.get("config", {})

    errors = int(final_gate.get("errors", 0))
    warnings = int(final_gate.get("warnings", 0))
    untranslated_ratio = float(final_gate.get("untranslated_ratio", 0.0))
    glossary_lock_errors = int(final_gate.get("glossary_lock_errors", 0))
    no_translate_errors = int(final_gate.get("no_translate_errors", 0))
    glossary_miss_warnings = int(final_gate.get("glossary_miss_warnings", 0))
    placeholder_issues = int(final_gate.get("placeholder_issues", 0))
    # ResponseChecker 丢弃条数（全量 + 补翻轮，来自 main 的 report.json）
    full_stage = report.get("stages", {}).get("full") or {}
    rt_stage = report.get("stages", {}).get("retranslate") or {}
    total_checker_dropped = int(full_stage.get("checker_dropped", 0)) + int(
        rt_stage.get("checker_dropped", 0)
    )

    # 三级结论：绿 / 黄 / 红
    classification = "red"
    classification_label = "红色（不建议进入测试）"
    reason_parts: list[str] = []

    if errors == 0:
        if (
            untranslated_ratio <= gate_max_untranslated_ratio
            and glossary_lock_errors == 0
            and no_translate_errors == 0
        ):
            classification = "green"
            classification_label = "绿色（可直接进入测试）"
        else:
            classification = "yellow"
            classification_label = "黄色（可在人工确认后进入测试）"
    else:
        classification = "red"
        classification_label = "红色（存在结构性错误，不建议测试）"

    if errors > 0:
        reason_parts.append(f"存在 {errors} 条 error")
    if untranslated_ratio > gate_max_untranslated_ratio:
        reason_parts.append(
            f"漏翻比例 {untranslated_ratio:.2%} 超过阈值 {gate_max_untranslated_ratio:.2%}"
        )
    if glossary_lock_errors > 0:
        reason_parts.append(f"锁定术语违例 {glossary_lock_errors} 条")
    if no_translate_errors > 0:
        reason_parts.append(f"禁翻片段违例 {no_translate_errors} 条")
    if not reason_parts:
        reason_parts.append("未命中阻断性条件")

    code_hist = final_gate.get("warning_histogram") or {}
    # 仅展示最终闸门的 warning code 分布，按数量降序取前 10 个
    top_warning_items = sorted(code_hist.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # strings 统计概要（可选）
    strings_summary = strings_stats.get("summary") or {}

    lines: list[str] = []
    lines.append("# Ren'Py 翻译质量概要")
    lines.append("")
    lines.append(
        "**本报告基于全量翻译 + 漏翻增量轮之后的最终闸门结果，用于判断当前补丁是否适合进入测试。**"
    )
    lines.append("")
    lines.append(f"- **总体结论**：{classification_label}")
    lines.append(f"- **关键理由**：{'; '.join(reason_parts)}")
    lines.append(f"- **闸门阈值（漏翻比例）**：{gate_max_untranslated_ratio:.2%}")
    lines.append("")

    lines.append("## 最终闸门总览（Stage 4）")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 检查文件数 | {final_gate.get('files', 0)} |")
    lines.append(f"| 错误数（error） | {errors} |")
    lines.append(f"| 警告数（warning） | {warnings} |")
    lines.append(f"| 对话行总数 | {final_gate.get('dialogue_total', 0)} |")
    lines.append(f"| 疑似未翻译行数 | {final_gate.get('untranslated_total', 0)} |")
    lines.append(f"| 漏翻比例 | {untranslated_ratio:.2%} |")
    lines.append(f"| 占位符/标签相关问题数 | {placeholder_issues} |")
    lines.append(f"| ResponseChecker 丢弃条数（未写入译文） | {total_checker_dropped} |")
    lines.append(f"| 锁定术语违例数（E411） | {glossary_lock_errors} |")
    lines.append(f"| 禁翻片段违例数（E420） | {no_translate_errors} |")
    lines.append(f"| 术语表未命中告警数（W410） | {glossary_miss_warnings} |")
    lines.append("")

    lines.append("## Warning Code 分布（最终闸门）")
    lines.append("")
    if top_warning_items:
        for code, count in top_warning_items:
            lines.append(f"- **{code}**: {count}")
    else:
        lines.append("- 无 warning code 统计（可能所有问题均为 error 或无告警）。")
    lines.append("")

    lines.append("## 术语与占位符质量")
    lines.append("")
    lines.append(f"- **锁定术语违例（E411_GLOSSARY_LOCK_MISS）**：{glossary_lock_errors} 条")
    lines.append(f"- **禁翻片段违例（E420_NO_TRANSLATE_CHANGED）**：{no_translate_errors} 条")
    lines.append(f"- **术语表未命中告警（W410_GLOSSARY_MISS）**：{glossary_miss_warnings} 条")
    lines.append(f"- **占位符/标签/菜单 ID/格式化占位符相关问题合计**：{placeholder_issues} 条")
    lines.append("")

    lines.append("## 试跑 vs 全量/最终闸门 对比")
    lines.append("")
    lines.append(
        "| 阶段 | 文件数 | 错误数 | 警告数 | 漏翻比例 | 长度异常告警数 | 占位符顺序告警数 |"
    )
    lines.append(
        "|------|--------|--------|--------|----------|----------------|------------------|"
    )
    lines.append(
        "| 试跑 (pilot) | {files} | {errors} | {warnings} | {ratio:.4f} | {len_warns} | {ph_warns} |".format(
            files=pilot_gate.get("files", 0),
            errors=pilot_gate.get("errors", 0),
            warnings=pilot_gate.get("warnings", 0),
            ratio=pilot_gate.get("untranslated_ratio", 0.0),
            len_warns=pilot_gate.get("len_ratio_warnings", 0),
            ph_warns=pilot_gate.get("placeholder_order_warnings", 0),
        )
    )
    lines.append(
        "| 全量 (full) | {files} | {errors} | {warnings} | {ratio:.4f} | {len_warns} | {ph_warns} |".format(
            files=full_gate.get("files", 0),
            errors=full_gate.get("errors", 0),
            warnings=full_gate.get("warnings", 0),
            ratio=full_gate.get("untranslated_ratio", 0.0),
            len_warns=full_gate.get("len_ratio_warnings", 0),
            ph_warns=full_gate.get("placeholder_order_warnings", 0),
        )
    )
    lines.append(
        "| 最终 (final) | {files} | {errors} | {warnings} | {ratio:.4f} | {len_warns} | {ph_warns} |".format(
            files=final_gate.get("files", 0),
            errors=errors,
            warnings=warnings,
            ratio=untranslated_ratio,
            len_warns=final_gate.get("len_ratio_warnings", 0),
            ph_warns=final_gate.get("placeholder_order_warnings", 0),
        )
    )
    lines.append("")

    if strings_summary:
        lines.append("## translate strings 覆盖概览")
        lines.append("")
        lines.append(
            f"- 含 strings 块的文件数：{strings_summary.get('total_files_with_strings', 0)}"
        )
        lines.append(f"- 总 entries：{strings_summary.get('total_strings_entries', 0)}")
        lines.append(f"- 已翻译：{strings_summary.get('total_strings_translated', 0)}")
        lines.append(f"- 未翻译：{strings_summary.get('total_strings_untranslated', 0)}")
        lines.append(f"- 未翻比例：{strings_summary.get('untranslated_ratio', 0.0):.2%}")
        note = strings_summary.get("note")
        if note:
            lines.append(f"- 说明：{note}")
        lines.append("")

    # 漏翻归因分析
    attribution = report.get("stages", {}).get("attribution") or {}
    attr_total = int(attribution.get("total", 0))
    if attr_total > 0:
        lines.append("## 漏翻归因分析")
        lines.append("")
        lines.append("| 归因类别 | 条数 | 占漏翻总数 |")
        lines.append("|----------|------|-----------|")
        for label, key in [
            ("AI 未返回", "ai_missing"),
            ("Checker 丢弃", "checker_dropped"),
            ("回写失败", "write_fail"),
            ("未知", "unknown"),
        ]:
            cnt = int(attribution.get(key, 0))
            pct = cnt / attr_total * 100 if attr_total else 0
            lines.append(f"| {label} | {cnt} | {pct:.1f}% |")
        lines.append("")
        db_count = int(attribution.get("db_entries_count", 0))
        lines.append(f"- translation_db 条目数：{db_count}")
        note = attribution.get("note")
        if note:
            lines.append(f"- 注意：{note}")
        lines.append("")
    elif attribution:
        lines.append("## 漏翻归因分析")
        lines.append("")
        note = attribution.get("note")
        if note:
            lines.append(f"- {note}")
        else:
            lines.append("- 无漏翻条目需要归因。")
        lines.append("")

    # chunk_stats 概览
    full_chunk_stats = report.get("stages", {}).get("full", {}).get("chunk_stats") or {}
    cs_expected = int(full_chunk_stats.get("total_expected", 0))
    cs_returned = int(full_chunk_stats.get("total_returned", 0))
    cs_dropped = int(full_chunk_stats.get("total_dropped", 0))
    if cs_expected > 0:
        lines.append("## Chunk 级指标概览（全量阶段）")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        n_chunks = len(full_chunk_stats.get("per_chunk", []))
        lines.append(f"| Chunk 总数 | {n_chunks} |")
        lines.append(f"| 预期可翻译行数 (expected) | {cs_expected} |")
        ret_pct = cs_returned / cs_expected * 100
        lines.append(f"| AI 实际返回条数 (returned) | {cs_returned} ({ret_pct:.1f}%) |")
        drop_pct = cs_dropped / cs_returned * 100 if cs_returned else 0
        lines.append(f"| Checker 丢弃条数 (dropped) | {cs_dropped} ({drop_pct:.1f}%) |")
        lines.append("")

    # 补翻阶段概览
    rt_data = report.get("stages", {}).get("retranslate") or {}
    if rt_data.get("mode") == "retranslate" and rt_data.get("total_translated", 0) > 0:
        lines.append("## 补翻阶段概览")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 扫描到漏翻行数 | {rt_data.get('total_untranslated_scanned', 0)} |")
        lines.append(f"| 涉及文件数 | {rt_data.get('retranslated_files', 0)} |")
        lines.append(f"| 补翻成功条数 | {rt_data.get('total_translated', 0)} |")
        lines.append(f"| API 请求数 | {rt_data.get('api_requests', 0)} |")
        rt_cost = rt_data.get("estimated_cost_usd", 0)
        if rt_cost:
            lines.append(f"| 估计费用 | ${rt_cost:.4f} |")
        lines.append("")

    # 简单的后续建议
    lines.append("## 建议动作")
    lines.append("")
    if classification == "green":
        lines.append("- 当前结果整体符合闸门要求，**可以直接打包进入测试环境**。")
        lines.append(
            "- 若有精力，可优先根据 Warning Code 分布处理高频风格类告警（如长度比例、中文占比等）。"
        )
    elif classification == "yellow":
        lines.append(
            "- 建议先针对上文列出的关键问题（术语违例、漏翻比例偏高等）做抽样人工复查，确认风险可接受后再进入测试。"
        )
    else:
        lines.append(
            "- 存在结构性错误或严重术语/禁翻违例，**不建议直接进入测试**，请先修正问题后重新运行一键流水线。"
        )

    summary_path = project_out_root / "report_summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
