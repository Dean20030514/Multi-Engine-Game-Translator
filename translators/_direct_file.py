#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Direct-mode file-level translation (round 23 A-H-4 split).

Carved out of ``translators/direct.py``. Contains two public-ish functions:

    translate_file            ← density-gated; full-file or targeted dispatch
    _translate_file_targeted  ← targeted path for low-density files

Both functions share the same 4-tuple return contract:
``(translated_count, warnings, checker_dropped, chunk_stats_list)``.

``translate_file`` is the primary caller of
``translators._direct_chunk._translate_chunk_with_retry``. The density check
delegates low-density files to ``_translate_file_targeted`` which uses the
retranslate-style prompt on only dialogue-bearing line windows.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import threading
from pathlib import Path
from typing import Optional

from core.api_client import APIClient
from core.glossary import Glossary
from core.prompts import (
    build_system_prompt,
    build_retranslate_system_prompt,
    build_retranslate_user_prompt,
)
from core.translation_db import TranslationDB
from core.translation_utils import (
    MIN_DIALOGUE_LENGTH,
    ProgressTracker,
    TranslationContext,
    _deduplicate_translations,
    _strip_char_prefix,
)
from file_processor import (
    SKIP_FILES_FOR_TRANSLATION,
    apply_translations,
    estimate_tokens,
    protect_placeholders,
    read_file,
    split_file,
    validate_translation,
    _filter_checked_translations,
    _restore_placeholders_in_translations,
)
from translators._direct_chunk import _translate_chunk_with_retry

# Round 26 PF-H-1: file-level parallel runs mutate ``quality_report`` from
# multiple threads. CPython dict ``__setitem__`` is GIL-atomic for stable
# hashes, but concurrent resizes can still expose torn state to any thread
# that iterates.  Serialise every write through this module-local lock so
# the invariant "after ``translate_file`` returns, ``quality_report``
# reflects that file's issues" holds even under parallelism.
_quality_report_lock = threading.Lock()

from translators.retranslator import (
    build_retranslate_chunks,
    calculate_dialogue_density,
)

logger = logging.getLogger("multi_engine_translator")


def translate_file(
    rpy_path: Path,
    game_dir: Path,
    output_dir: Path,
    client: APIClient,
    glossary: Glossary,
    progress: ProgressTracker,
    quality_report: Optional[dict[str, list[dict]]] = None,
    genre: str = "adult",
    max_tokens_per_chunk: int = 4000,
    workers: int = 1,
    *,
    translation_db: Optional[TranslationDB] = None,
    run_id: str = "",
    stage: str = "single",
    provider: str = "",
    model: str = "",
    min_dialogue_density: float = 0.20,
    cot: bool = False,
) -> tuple[int, list[str], int, list[dict]]:
    """翻译单个 RPY 文件

    Returns:
        (translated_count, warnings, checker_dropped, chunk_stats_list)
        checker_dropped: 因 ResponseChecker 未通过而被丢弃的条数（保留原文计漏翻）。
        chunk_stats_list: per-chunk 指标 [{"chunk_idx": N, "expected": X, "returned": Y, "dropped": D}, ...]
    """
    rel_path = str(rpy_path.relative_to(game_dir))

    # 纯配置/UI 文件——直接复制，不翻译
    if rpy_path.name in SKIP_FILES_FOR_TRANSLATION:
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        content = read_file(rpy_path)
        out_path.write_text(content, encoding="utf-8")
        progress.mark_file_done(rel_path)
        logger.debug(f"  [SKIP-CFG] {rel_path} (配置文件，跳过翻译)")
        return 0, [], 0, []

    # 断点续传：已完成则跳过
    if progress.is_file_done(rel_path):
        logger.debug(f"  [SKIP] {rel_path} (已完成)")
        return 0, [], 0, []

    content = read_file(rpy_path)
    tokens = estimate_tokens(content)
    logger.debug(f"  [FILE] {rel_path}  ({tokens:,} tokens)")

    # 密度检测：低密度文件走定向翻译，避免 AI 注意力被代码行稀释
    density = calculate_dialogue_density(content)
    if density < min_dialogue_density:
        logger.debug(
            f"    [DENSITY] 对话密度 {density * 100:.1f}% < {min_dialogue_density * 100:.0f}%，"
            f"使用定向翻译模式"
        )
        return _translate_file_targeted(
            rpy_path,
            game_dir,
            output_dir,
            content,
            rel_path,
            client,
            glossary,
            progress,
            quality_report,
            genre,
            translation_db=translation_db,
            run_id=run_id,
            stage=stage,
            provider=provider,
            model=model,
        )

    # 拆分大文件
    chunks = split_file(str(rpy_path), max_tokens_per_chunk)
    if len(chunks) > 1:
        logger.debug(f"    拆分为 {len(chunks)} 个块")

    # 构建 prompt（按题材 + 术语表 + 项目名）
    project_name = game_dir.parent.name if game_dir.name.lower() == "game" else game_dir.name
    system_prompt = build_system_prompt(
        genre=genre,
        glossary_text=glossary.to_prompt_text(),
        project_name=project_name,
        cot=cot,
    )

    # 加载已完成的翻译（断点续传，只加载一次避免重复）
    all_translations = list(progress.get_file_translations(rel_path))
    all_warnings = []
    all_dropped_items: list[dict] = []
    chunk_stats_list: list[dict] = []

    # 筛选待翻译的 chunk
    pending_chunks = [c for c in chunks if not progress.is_chunk_done(rel_path, c["part"])]
    done_chunks = len(chunks) - len(pending_chunks)
    if done_chunks > 0:
        logger.debug(f"    [SKIP] {done_chunks}/{len(chunks)} 个块已完成")

    total_checker_dropped = 0

    # 构建锁定术语映射（用于预替换保护）
    locked_terms_map: dict[str, str] = {}
    if glossary.locked_terms:
        for en_term in glossary.locked_terms:
            zh_term = glossary.terms.get(en_term, "")
            if en_term and zh_term:
                locked_terms_map[en_term] = zh_term

    # 构建翻译上下文（替代嵌套函数闭包捕获）
    ctx = TranslationContext(
        client=client,
        system_prompt=system_prompt,
        rel_path=rel_path,
        locked_terms_map=locked_terms_map,
    )

    if workers > 1 and len(pending_chunks) > 1:
        # 并发翻译多个 chunk
        _backpressure = threading.Semaphore(workers * 2)

        def _submit_with_backpressure(pool, fn, *args):
            _backpressure.acquire()
            future = pool.submit(fn, *args)
            future.add_done_callback(lambda _: _backpressure.release())
            return future

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                _submit_with_backpressure(executor, _translate_chunk_with_retry, ctx, c): c
                for c in pending_chunks
            }
            for future in concurrent.futures.as_completed(futures):
                cr = future.result()
                chunk_stats_list.append(
                    {
                        "chunk_idx": cr.part,
                        "expected": cr.expected,
                        "returned": cr.returned,
                        "dropped": cr.dropped_count,
                    }
                )
                if cr.error:
                    logger.error(f"    [ERROR] {cr.error}")
                    all_warnings.append(cr.error)
                else:
                    all_warnings.extend(cr.chunk_warnings)
                    total_checker_dropped += cr.dropped_count
                    progress.mark_chunk_done(rel_path, cr.part, cr.kept)
                    all_translations.extend(cr.kept)
                    all_dropped_items.extend(cr.dropped_items)
    else:
        # 顺序翻译
        for chunk in pending_chunks:
            cr = _translate_chunk_with_retry(ctx, chunk)
            chunk_stats_list.append(
                {
                    "chunk_idx": cr.part,
                    "expected": cr.expected,
                    "returned": cr.returned,
                    "dropped": cr.dropped_count,
                }
            )
            if cr.error:
                logger.error(f"    [ERROR] {cr.error}")
                all_warnings.append(cr.error)
                progress.save()
                continue
            all_warnings.extend(cr.chunk_warnings)
            total_checker_dropped += cr.dropped_count
            progress.mark_chunk_done(rel_path, cr.part, cr.kept)
            all_translations.extend(cr.kept)
            all_dropped_items.extend(cr.dropped_items)

    if not all_translations:
        # 没有需要翻译的内容，直接复制原文件
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        progress.mark_file_done(rel_path)
        return 0, [], total_checker_dropped, chunk_stats_list

    # 去重（多 chunk 可能有重叠）
    unique_translations = _deduplicate_translations(all_translations)

    # 应用翻译
    patched, patch_warnings, patch_stats = apply_translations(content, unique_translations)
    all_warnings.extend(patch_warnings)

    # 校验：同时传入术语表、锁定术语与禁翻片段
    issues = validate_translation(
        content,
        patched,
        rel_path,
        glossary_terms=glossary.terms,
        glossary_locked=glossary.locked_terms,
        glossary_no_translate=glossary.no_translate,
    )
    if quality_report is not None and issues:
        with _quality_report_lock:
            quality_report[rel_path] = issues
    for issue in issues:
        if issue["level"] == "error":
            all_warnings.append(f"行 {issue['line']}: {issue['message']}")

    # 将每条翻译写入 translation_db（可选）
    if translation_db is not None and unique_translations:
        per_line: dict[int, dict[str, list[str]]] = {}
        for issue in issues:
            line_no = int(issue.get("line") or 0)
            code = issue.get("code") or ""
            level = issue.get("level") or ""
            if not line_no or not code or level not in ("error", "warning"):
                continue
            bucket = per_line.setdefault(line_no, {"errors": [], "warnings": []})
            if level == "error":
                bucket["errors"].append(code)
            else:
                bucket["warnings"].append(code)

        db_entries: list[dict] = []
        for item in unique_translations:
            line_no = int(item.get("line") or 0)
            original = item.get("original", "") or ""
            zh = item.get("zh", "") or ""
            if not line_no or not original:
                continue
            info = per_line.get(line_no, {"errors": [], "warnings": []})
            err_codes = info["errors"]
            warn_codes = info["warnings"]
            if err_codes:
                status = "error"
            elif warn_codes:
                status = "warning"
            else:
                status = "ok"
            db_entries.append(
                {
                    "file": rel_path,
                    "line": line_no,
                    "original": original,
                    "translation": zh,
                    "status": status,
                    "error_codes": err_codes,
                    "warning_codes": warn_codes,
                    "run_id": run_id,
                    "stage": stage,
                    "provider": provider,
                    "model": model,
                }
            )
        if db_entries:
            translation_db.add_entries(db_entries)

    # 写入 checker 丢弃的条目（仅用于归因统计，不参与回写）
    if translation_db is not None and all_dropped_items:
        try:
            dropped_db_entries: list[dict] = []
            for item in all_dropped_items:
                line_no = int(item.get("line") or 0)
                original = item.get("original", "") or ""
                zh = item.get("zh", "") or ""
                if not line_no or not original:
                    continue
                # 若同一 key 已有 kept 条目，不覆盖
                if translation_db.has_entry(rel_path, line_no, original):
                    continue
                dropped_db_entries.append(
                    {
                        "file": rel_path,
                        "line": line_no,
                        "original": original,
                        "translation": zh,
                        "status": "checker_dropped",
                        "error_codes": [],
                        "warning_codes": [],
                        "run_id": run_id,
                        "stage": stage,
                        "provider": provider,
                        "model": model,
                    }
                )
            if dropped_db_entries:
                translation_db.add_entries(dropped_db_entries)
        except (OSError, ValueError, TypeError) as e:
            logger.debug(f"记录 checker_dropped 到 translation_db 失败: {e}")

    # 写入回写失败的条目（用于根因分析）
    wb_failures = patch_stats.get("writeback_failures", [])
    if translation_db is not None and wb_failures:
        try:
            wb_db_entries: list[dict] = []
            for diag in wb_failures:
                line_no = int(diag.get("line") or 0)
                original = diag.get("original", "") or ""
                zh = diag.get("zh", "") or ""
                if not line_no or not original:
                    continue
                if translation_db.has_entry(rel_path, line_no, original):
                    continue
                wb_db_entries.append(
                    {
                        "file": rel_path,
                        "line": line_no,
                        "original": original,
                        "translation": zh,
                        "status": "writeback_failed",
                        "error_codes": [],
                        "warning_codes": [],
                        "run_id": run_id,
                        "stage": stage,
                        "provider": provider,
                        "model": model,
                        "diagnostic": {
                            "failure_type": diag.get("failure_type", "WF-08"),
                            "detail": diag.get("detail", ""),
                        },
                    }
                )
            if wb_db_entries:
                translation_db.add_entries(wb_db_entries)
        except (OSError, ValueError, TypeError) as e:
            logger.debug(f"记录 writeback_failed 到 translation_db 失败: {e}")

    # 写出翻译后的文件
    out_path = output_dir / rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(patched, encoding="utf-8")

    # 更新术语表
    glossary.update_from_translations(unique_translations)

    # 标记完成
    progress.mark_file_done(rel_path)

    return len(unique_translations), all_warnings, total_checker_dropped, chunk_stats_list


def _translate_file_targeted(
    rpy_path: Path,
    game_dir: Path,
    output_dir: Path,
    content: str,
    rel_path: str,
    client: APIClient,
    glossary: Glossary,
    progress: ProgressTracker,
    quality_report: Optional[dict[str, list[dict]]] = None,
    genre: str = "adult",
    *,
    translation_db: Optional[TranslationDB] = None,
    run_id: str = "",
    stage: str = "single",
    provider: str = "",
    model: str = "",
) -> tuple[int, list[str], int, list[dict]]:
    """低密度文件的定向翻译：提取对话行+上下文，走 retranslate 风格 prompt。

    与 retranslate_file 的区别：
    - 输入是未翻译的英文原文件（全量阶段），不是已翻译文件
    - 检测所有 _is_user_visible_string_line 的行（而非仅检测残留英文）
    - 输出到 output_dir（可能与 game_dir 不同）
    - 返回值与 translate_file 一致的 4-tuple
    """
    from translators.renpy_text_utils import _is_user_visible_string_line

    all_lines = content.splitlines()

    # 提取所有对话行的 0-based 索引
    dialogue_indices: list[int] = []
    for i, line in enumerate(all_lines):
        if _is_user_visible_string_line(line):
            m = re.search(r'"([^"\\]*(?:\\.[^"\\]*)*)"', line)
            if m and len(m.group(1)) >= MIN_DIALOGUE_LENGTH:
                dialogue_indices.append(i)

    if not dialogue_indices:
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        progress.mark_file_done(rel_path)
        return 0, [], 0, []

    chunks = build_retranslate_chunks(all_lines, dialogue_indices, context=3, max_per_chunk=20)
    logger.debug(f"    [TARGETED] {len(dialogue_indices)} 行对话，{len(chunks)} 个 chunk")

    system_prompt = build_retranslate_system_prompt(glossary_text=glossary.to_prompt_text())

    all_translations: list[dict] = []
    all_warnings: list[str] = []
    chunk_stats_list: list[dict] = []
    total_checker_dropped = 0

    for ci, chunk_lines in enumerate(chunks, 1):
        raw_for_detect = "\n".join(line for _, line, _ in chunk_lines if line != "...")
        _, ph_mapping = protect_placeholders(raw_for_detect)

        if ph_mapping:
            inv = {orig: token for token, orig in ph_mapping}
            protected: list[tuple[int, str, bool]] = []
            for lineno, line, is_target in chunk_lines:
                if line == "...":
                    protected.append((lineno, line, is_target))
                    continue
                pl = line
                for orig, tok in inv.items():
                    pl = pl.replace(orig, tok)
                protected.append((lineno, pl, is_target))
        else:
            protected = list(chunk_lines)

        user_prompt = build_retranslate_user_prompt(rel_path, protected)
        target_count = sum(1 for _, _, t in chunk_lines if t)
        logger.debug(f"    [API ] 定向块 {ci}/{len(chunks)} ({target_count} 行)")

        try:
            translations = client.translate(system_prompt, user_prompt)
        except Exception as e:
            warn = f"定向块 {ci} API 调用失败: {e}"
            logger.error(f"    [ERROR] {warn}")
            all_warnings.append(warn)
            chunk_stats_list.append(
                {"chunk_idx": ci, "expected": target_count, "returned": 0, "dropped": 0}
            )
            continue

        _restore_placeholders_in_translations(translations, ph_mapping)
        _strip_char_prefix(translations)

        kept, dropped, _, check_warns = _filter_checked_translations(translations)
        all_warnings.extend(check_warns)
        total_checker_dropped += dropped

        chunk_stats_list.append(
            {
                "chunk_idx": ci,
                "expected": target_count,
                "returned": len(translations),
                "dropped": dropped,
            }
        )

        if kept:
            logger.debug(f"    [OK  ] 定向块 {ci}: 获得 {len(kept)} 条翻译")
        all_translations.extend(kept)

    if not all_translations:
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        progress.mark_file_done(rel_path)
        return 0, all_warnings, total_checker_dropped, chunk_stats_list

    unique = _deduplicate_translations(all_translations)

    patched, patch_warnings, patch_stats_t = apply_translations(content, unique)
    all_warnings.extend(patch_warnings)

    issues = validate_translation(
        content,
        patched,
        rel_path,
        glossary_terms=glossary.terms,
        glossary_locked=glossary.locked_terms,
        glossary_no_translate=glossary.no_translate,
    )
    if quality_report is not None and issues:
        with _quality_report_lock:
            quality_report[rel_path] = issues
    for issue in issues:
        if issue["level"] == "error":
            all_warnings.append(f"行 {issue['line']}: {issue['message']}")

    # 写入回写失败诊断（定向翻译模式）
    wb_failures_t = patch_stats_t.get("writeback_failures", [])
    if translation_db is not None and wb_failures_t:
        try:
            for diag in wb_failures_t:
                line_no = int(diag.get("line") or 0)
                original = diag.get("original", "") or ""
                zh = diag.get("zh", "") or ""
                if not line_no or not original:
                    continue
                if translation_db.has_entry(rel_path, line_no, original):
                    continue
                translation_db.upsert_entry(
                    {
                        "file": rel_path,
                        "line": line_no,
                        "original": original,
                        "translation": zh,
                        "status": "writeback_failed",
                        "error_codes": [],
                        "warning_codes": [],
                        "run_id": run_id,
                        "stage": stage,
                        "provider": provider,
                        "model": model,
                        "diagnostic": {
                            "failure_type": diag.get("failure_type", "WF-08"),
                            "detail": diag.get("detail", ""),
                        },
                    }
                )
        except (OSError, ValueError, TypeError) as e:
            logger.debug(f"记录 writeback_failed 到 translation_db 失败: {e}")

    if translation_db is not None and unique:
        db_entries = []
        for item in unique:
            line_no = int(item.get("line") or 0)
            original = item.get("original", "") or ""
            zh = item.get("zh", "") or ""
            if not line_no or not original:
                continue
            db_entries.append(
                {
                    "file": rel_path,
                    "line": line_no,
                    "original": original,
                    "translation": zh,
                    "status": "ok",
                    "error_codes": [],
                    "warning_codes": [],
                    "run_id": run_id,
                    "stage": stage,
                    "provider": provider,
                    "model": model,
                }
            )
        if db_entries:
            translation_db.add_entries(db_entries)

    out_path = output_dir / rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(patched, encoding="utf-8")

    glossary.update_from_translations(unique)
    progress.mark_file_done(rel_path)

    return len(unique), all_warnings, total_checker_dropped, chunk_stats_list
