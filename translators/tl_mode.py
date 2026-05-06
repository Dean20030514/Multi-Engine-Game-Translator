#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tl-mode 翻译引擎入口：扫描 Ren'Py tl/<lang>/ 目录中的空翻译槽位，AI 翻译后精确回填。

第 24 轮 (A-H-4) 起本文件被拆为 3 个模块，保持 ``translators.tl_mode`` 公开
API（``run_tl_pipeline`` 等）不变：

    translators/
    ├── tl_mode.py             ← 本文件：入口 ``run_tl_pipeline`` + ``_translate_one_tl_chunk`` + re-export
    ├── _tl_patches.py         ← 游戏目录补丁（字体 / 语言切换 / rpyc 清理）
    └── _tl_dedup.py           ← 跨文件去重 + chunk 装配

使用方继续 ``from translators.tl_mode import run_tl_pipeline`` / ``dedup_tl_entries`` /
``_apply_tl_game_patches`` 等即可，re-export 在本文件下方统一维护。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import shutil
import threading
import time
from pathlib import Path

from core.api_client import APIClient, APIConfig
from core.glossary import Glossary
from core.prompts import build_tl_system_prompt, build_tl_user_prompt
from core.translation_db import TranslationDB
from core.translation_utils import (
    ProgressTracker,
    TranslationContext,
    _build_fallback_dicts,
    _match_string_entry_fallback,
)
from file_processor import (
    check_response_item,
    protect_placeholders,
    _filter_checked_translations,
    _restore_placeholders_in_translations,
)

# Re-export 兼容层：下游调用方 (main.py / engines/renpy_engine.py /
# tests/test_tl_dedup.py / tests/test_tl_pipeline.py / tools/translation_editor.py)
# 历史上从 ``translators.tl_mode`` 导入下列符号。A-H-4 拆分后符号实际定义在
# 子模块中，但 tl_mode.py 仍然暴露同名别名，确保零回归。
from translators._tl_dedup import (  # noqa: F401
    DEDUP_MIN_LENGTH,
    DedupResult,
    apply_dedup_translations,
    build_tl_chunks,
    dedup_tl_entries,
)
from translators._tl_patches import (  # noqa: F401
    _LANG_BUTTON_SNIPPET,
    _apply_tl_game_patches,
    _clean_rpyc,
    _inject_language_buttons,
)
# Round 53 W3: layer-6 LLM ID drift detection helpers.
# Hoisted to module top in r56 (M3) — _tl_retry does NOT import tl_mode,
# so there is no circular-import risk; the function-local import was a
# defensive carryover from W3's first cut.
from translators._tl_retry import detect_id_drift, _expected_id_set

logger = logging.getLogger("multi_engine_translator")


def _translate_one_tl_chunk(
    ctx: TranslationContext, rel_path: str, ci: int, chunk_text: str, chunk_entries: list,
) -> tuple[str, int, dict[str, str], int, list[str]]:
    """翻译单个 tl-mode chunk。

    原为 run_tl_pipeline() 内的嵌套函数，通过闭包捕获 client/system_prompt。
    重构后通过 TranslationContext 显式传参。

    Returns:
        (rel_path, ci, kept_items_dict, dropped_count, warnings)
    """
    protected_text, ph_mapping = protect_placeholders(chunk_text)
    user_prompt = build_tl_user_prompt(protected_text, len(chunk_entries))
    translations = ctx.client.translate(ctx.system_prompt, user_prompt)

    _restore_placeholders_in_translations(translations, ph_mapping, extra_keys=("id",))

    kept_items: dict[str, str] = {}
    dropped = 0
    warnings: list[str] = []
    returned_ids: set[str] = set()
    # Round 52 C4 BREAKING: lang_config / resolve_translation_field
    # retired.  Only zh target supported; AI response reader hard-coded
    # to ``t.get("zh", "")``.
    for t in translations:
        tid = t.get("id", "")
        if tid:
            returned_ids.add(tid)
        item_w = check_response_item(t)
        if item_w:
            dropped += 1
            warnings.extend(f"[CHECK-DROPPED] {w}" for w in item_w)
        else:
            zh = t.get("zh", "")
            if tid and zh:
                kept_items[tid] = zh

    # Round 53 W3 layer 6: LLM ID-space drift detection.
    expected_ids = _expected_id_set(chunk_entries)
    drifted, drift_ratio, n_missing, n_extra = detect_id_drift(
        expected_ids, returned_ids,
    )
    if drifted:
        warnings.append(
            f"[W3-DRIFT {drift_ratio:.0%}] {rel_path} chunk {ci}: "
            f"missing={n_missing} extra={n_extra} "
            f"(LLM ID 集偏离 expected > {int(0.10 * 100)}%, fallback 链需补救)"
        )

    return rel_path, ci, kept_items, dropped, warnings


def run_tl_pipeline(args: argparse.Namespace) -> None:
    """运行 tl-mode 翻译流水线。

    流程：scan_tl_directory → 提取空槽位 → 分 chunk → AI 翻译 → fill_translation 回填。
    """
    from translators.tl_parser import (
        scan_tl_directory,
        get_untranslated_entries,
        fill_translation,
        postprocess_tl_directory,
        fix_nvl_ids_directory,
        print_tl_stats,
        DialogueEntry,
        StringEntry,
    )

    game_dir = Path(args.game_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tl_lang = getattr(args, "tl_lang", "chinese") or "chinese"

    logger.info("=" * 60)
    logger.info("Ren'Py tl-mode 翻译")
    logger.info("=" * 60)
    logger.info(f"游戏目录: {game_dir}")
    logger.info(f"tl 语言: {tl_lang}")
    logger.info(f"API: {args.provider} / {args.model or '默认'}")
    logger.info("")

    # ── 0. 自动字体补丁 + 语言切换注入 ──
    font_config = getattr(args, "font_config", "") or None
    _apply_tl_game_patches(game_dir, tl_lang, font_config_path=Path(font_config) if font_config else None)
    logger.info("")

    # ── 1. 扫描 ──
    tl_dir = str(game_dir / "tl")
    results = scan_tl_directory(tl_dir, tl_lang)
    if not results:
        logger.info("[TL-MODE] 未找到 tl 文件，请确认路径是否正确")
        return
    print_tl_stats(results)

    untrans_dlg, untrans_str = get_untranslated_entries(results)
    total_untrans = len(untrans_dlg) + len(untrans_str)
    if total_untrans == 0:
        logger.info("\n[TL-MODE] 所有条目已翻译，无需操作")
        return

    logger.info(f"\n[TL-MODE] 待翻译: {len(untrans_dlg)} 个对话, {len(untrans_str)} 个字符串")

    # ── 初始化基础设施 ──
    config = APIConfig(
        provider=args.provider,
        api_key=args.api_key or "dummy",
        model=args.model or "",
        rpm=args.rpm,
        rps=args.rps,
        timeout=args.timeout,
        temperature=args.temperature,
        max_response_tokens=args.max_response_tokens,
        custom_module=getattr(args, "custom_module", ""),
    )
    client = APIClient(config)
    logger.info(f"[API ] 提供商: {config.provider}, 模型: {config.model}")

    glossary = Glossary()
    glossary_path = output_dir / "glossary.json"
    glossary.load(str(glossary_path))
    if args.dict:
        for dict_path in args.dict:
            if not Path(dict_path).exists():
                logger.warning(f"[WARN] 词典文件不存在，跳过: {dict_path}")
                continue
            glossary.load_dict(dict_path)

    # Round 52 C4 BREAKING: language-aware ProgressTracker namespace
    # retired (zh-only). language= kwarg removed.
    progress = ProgressTracker(output_dir / "tl_progress.json")
    if not args.resume and progress.data.get("completed_files"):
        progress.data = {"completed_files": [], "completed_chunks": {}, "stats": {}}
        progress.save()

    db_path = output_dir / "translation_db.json"
    # Round 52 C4 BREAKING: TranslationDB v2 schema retired.
    # default_language= kwarg removed; entries have no language field.
    translation_db = TranslationDB(db_path)
    translation_db.load()
    run_id = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    system_prompt = build_tl_system_prompt(
        glossary_text=glossary.to_prompt_text(),
        genre=args.genre,
        cot=getattr(args, 'cot', False),
    )

    # ── 1b. 自动回填不需要 AI 翻译的条目（纯空白/纯标点原文） ──
    auto_filled: list = []
    remaining_dlg: list = []
    remaining_str: list = []
    for e in untrans_dlg:
        if not e.original.strip():
            e.translation = e.original  # keep original whitespace
            auto_filled.append(e)
        else:
            remaining_dlg.append(e)
    for e in untrans_str:
        if not e.old.strip():
            e.new = e.old
            auto_filled.append(e)
        else:
            remaining_str.append(e)
    if auto_filled:
        logger.info(f"[TL-MODE] 自动回填 {len(auto_filled)} 条纯空白条目")
        af_by_file: dict[str, list] = {}
        for e in auto_filled:
            af_by_file.setdefault(e.tl_file, []).append(e)
        for fpath, af_entries in af_by_file.items():
            bak = Path(fpath + ".bak")
            if not bak.exists():
                try:
                    shutil.copy2(fpath, bak)
                except OSError as e:
                    logger.warning(f"创建备份失败 {bak}: {e}")
            modified = fill_translation(fpath, af_entries)
            Path(fpath).write_text(modified, encoding="utf-8")

    untrans_dlg = remaining_dlg
    untrans_str = remaining_str
    total_untrans = len(untrans_dlg) + len(untrans_str)
    if total_untrans == 0:
        logger.info("\n[TL-MODE] 所有条目已翻译或自动回填，无需 AI 操作")
        postprocess_tl_directory(str(game_dir / "tl"), tl_lang)
        fix_nvl_ids_directory(str(game_dir / "tl"), tl_lang)
        return

    # ── 1c. 跨文件翻译去重（仅 ≥ 40 字符的完整句子） ──
    all_entries_raw = list(untrans_dlg) + list(untrans_str)
    dedup = dedup_tl_entries(all_entries_raw)
    if dedup.skipped_count > 0:
        logger.info(f"[TL-DEDUP] 去重: {dedup.total_before} → {len(dedup.unique_entries)} 条 "
                     f"(跳过 {dedup.skipped_count} 条重复, "
                     f"{len(dedup.dedup_groups)} 组, 阈值 ≥{DEDUP_MIN_LENGTH} 字符)")
    all_entries = dedup.unique_entries

    # ── 2. 按文件分组 + 分 chunk ──
    by_file: dict[str, list] = {}
    for entry in all_entries:
        by_file.setdefault(entry.tl_file, []).append(entry)

    for entries in by_file.values():
        entries.sort(key=lambda e: e.tl_line)

    start_time = time.time()
    total_translated = 0
    total_checker_dropped = 0
    total_filled = 0
    total_fallback_matched = 0
    total_warnings: list[str] = []
    files_processed = 0
    workers = max(1, getattr(args, "workers", 1))

    # ── 2a. 收集所有待翻译 chunk ──
    all_chunk_tasks: list[tuple] = []
    file_meta: dict[str, tuple] = {}  # rel_path → (file_path, entries, total_chunks)

    for file_path, entries in by_file.items():
        rel_path = file_path
        try:
            rel_path = str(Path(file_path).relative_to(game_dir))
        except ValueError:
            pass

        if progress.is_file_done(rel_path):
            logger.debug(f"  [SKIP] {rel_path} (已完成)")
            continue

        chunks = build_tl_chunks(entries)
        file_meta[rel_path] = (file_path, entries, len(chunks))

        for ci, (chunk_text, chunk_entries) in enumerate(chunks, 1):
            if progress.is_chunk_done(rel_path, ci):
                continue
            all_chunk_tasks.append((rel_path, ci, chunk_text, chunk_entries))

    logger.info(f"\n[TL-MODE] {len(file_meta)} 个文件, "
          f"{len(all_chunk_tasks)} 个 chunk 待处理, "
          f"{workers} 线程并发")

    # ── 2b. 并发翻译 chunk ──
    file_translations: dict[str, dict[str, str]] = {}
    _lock = threading.Lock()
    _completed = [0]

    # 构建翻译上下文（替代嵌套函数闭包捕获）
    ctx = TranslationContext(
        client=client,
        system_prompt=system_prompt,
        rel_path="",
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        pending_futures: dict[concurrent.futures.Future, tuple] = {}
        task_iter = iter(all_chunk_tasks)
        total_tasks = len(all_chunk_tasks)
        tasks_exhausted = False

        def _submit_next() -> bool:
            """提交下一个任务到线程池。返回 False 表示已无更多任务。"""
            nonlocal tasks_exhausted
            if tasks_exhausted:
                return False
            try:
                rp, ci, text, entries = next(task_iter)
                t = file_meta[rp][2]
                fut = pool.submit(
                    _translate_one_tl_chunk, ctx, rp, ci, text, entries,
                )
                pending_futures[fut] = (rp, ci, len(entries), t)
                return True
            except StopIteration:
                tasks_exhausted = True
                return False

        # 初始提交：填满线程池
        for _ in range(min(workers * 2, total_tasks)):
            _submit_next()

        # 主循环：等待完成 → 收集结果 → 提交下一个
        while pending_futures:
            done, _ = concurrent.futures.wait(
                pending_futures, return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                rel_path, ci, _entry_count, total = pending_futures.pop(fut)
                try:
                    rp, _chunk_idx, kept_items, dropped, warnings = fut.result()
                    with _lock:
                        file_translations.setdefault(rp, {}).update(kept_items)
                        total_checker_dropped += dropped
                        total_warnings.extend(warnings)
                        _completed[0] += 1
                        n_completed = _completed[0]
                        n_kept = len(kept_items)
                    logger.info(f"  [{n_completed}/{total_tasks}] {rp} "
                         f"chunk {ci}/{total}: 保留 {n_kept} 条"
                         + (f", 丢弃 {dropped} 条" if dropped else ""))
                    progress.mark_chunk_done(rp, ci, [])
                except Exception as e:
                    with _lock:
                        total_warnings.append(f"{rel_path} chunk {ci}: {e}")
                        _completed[0] += 1
                        n_completed = _completed[0]
                    logger.error(f"  [{n_completed}/{total_tasks}] [ERROR] "
                          f"{rel_path} chunk {ci}/{total}: {e}")

                # 每完成一个就补提交一个（背压）
                _submit_next()

    # ── 2c. 去重翻译复用 ──
    if dedup.skipped_count > 0:
        dedup_filled, dedup_log = apply_dedup_translations(
            dedup, file_translations, game_dir,
        )
        if dedup_filled > 0:
            logger.info(f"[TL-DEDUP] 复用翻译: {dedup_filled} 条")
            # 去重的条目也需要加入 file_meta 的 entries 中以便回填
            for (_char, _text), (first_entry, dup_entries) in dedup.dedup_groups.items():
                for entry in dup_entries:
                    try:
                        rel_path = str(Path(entry.tl_file).relative_to(game_dir))
                    except ValueError:
                        rel_path = entry.tl_file
                    if rel_path in file_meta:
                        _fp, existing_entries, _tc = file_meta[rel_path]
                        if entry not in existing_entries:
                            existing_entries.append(entry)
                    else:
                        file_meta[rel_path] = (entry.tl_file, [entry], 0)

    # ── 3. 匹配 + 回填（串行，保证文件写入安全） ──
    modified_rpy_files: set[str] = set()

    for rel_path, (file_path, entries, _total_chunks) in file_meta.items():
        ft = file_translations.get(rel_path, {})
        if not ft:
            progress.mark_file_done(rel_path)
            files_processed += 1
            continue

        # 预建 fallback 查找表（O(1) 替代 O(n) 遍历）
        # Round 31 Tier A-3: build 4 dicts (adds ft_tagstripped for the L5 fallback)
        ft_stripped, ft_clean, ft_norm, ft_tagstripped = _build_fallback_dicts(ft)

        matched_entries: list = []
        db_entries: list[dict] = []
        for entry in entries:
            if isinstance(entry, DialogueEntry):
                zh = ft.get(entry.identifier)
                if zh:
                    entry.translation = zh
                    matched_entries.append(entry)
                    total_translated += 1
                    db_entries.append({
                        "file": rel_path,
                        "line": entry.tl_line,
                        "original": entry.original,
                        "translation": zh,
                        "status": "ok",
                        "error_codes": [],
                        "warning_codes": [],
                        "run_id": run_id,
                        "stage": "tl-mode",
                        "provider": config.provider,
                        "model": config.model,
                    })
            else:  # StringEntry — 五层 fallback（精确 → strip → 去令牌 → 转义 → 去标签，round 31 Tier A-3）
                zh, fb_level = _match_string_entry_fallback(
                    entry.old, ft, ft_stripped, ft_clean, ft_norm, ft_tagstripped,
                )
                if zh:
                    if fb_level:
                        total_fallback_matched += 1
                        logger.debug(f"  [TL-MATCH] fallback L{fb_level}: "
                              f"{entry.old[:40]!r}")
                    entry.new = zh
                    matched_entries.append(entry)
                    total_translated += 1
                    db_entries.append({
                        "file": rel_path,
                        "line": entry.tl_line,
                        "original": entry.old,
                        "translation": zh,
                        "status": "ok",
                        "error_codes": [],
                        "warning_codes": [],
                        "run_id": run_id,
                        "stage": "tl-mode",
                        "provider": config.provider,
                        "model": config.model,
                    })

        if db_entries and translation_db is not None:
            translation_db.add_entries(db_entries)

        # ── 4. 回填 ──
        if matched_entries:
            bak_path = Path(file_path + ".bak")
            if not bak_path.exists():
                try:
                    shutil.copy2(file_path, bak_path)
                except OSError as e:
                    logger.warning(f"创建备份失败 {bak_path}: {e}")

            modified_content = fill_translation(file_path, matched_entries)
            Path(file_path).write_text(modified_content, encoding="utf-8")
            total_filled += len(matched_entries)
            modified_rpy_files.add(rel_path)
            logger.debug(f"  [FILL] 回填 {len(matched_entries)} 条到 {rel_path}")

        progress.mark_file_done(rel_path)
        files_processed += 1

    # ── 4b. 重试未匹配条目（Round 53 W1: 拆到 _tl_retry.py，
    #         ThreadPoolExecutor 并发 + per-chunk progress + 自适应 chunk size） ──
    from translators._tl_retry import run_retry_stage

    retry_results = scan_tl_directory(str(game_dir / "tl"), tl_lang)
    retry_dlg, retry_str = get_untranslated_entries(retry_results)
    retry_all = [e for e in retry_dlg if e.original.strip()] + \
                [e for e in retry_str if e.old.strip()]
    if retry_all:
        logger.info(f"\n[TL-RETRY] {len(retry_all)} 条未匹配，重试中…")
        rt_translated, rt_filled = run_retry_stage(
            retry_all=retry_all,
            client=client,
            system_prompt=system_prompt,
            workers=workers,
            game_dir=game_dir,
            fill_translation=fill_translation,
            DialogueEntry=DialogueEntry,
            modified_rpy_files=modified_rpy_files,
        )
        total_translated += rt_translated
        total_filled += rt_filled

    # ── 4c. 后处理：修复 nvl clear 兼容性 + 空 translate 块 ──
    tl_dir = str(game_dir / "tl")
    postprocess_tl_directory(tl_dir, tl_lang)
    fix_nvl_ids_directory(tl_dir, tl_lang)

    # ── 4d. 清理 rpyc 缓存（全量清理，强制 Ren'Py 重编译） ──
    if not getattr(args, "no_clean_rpyc", False):
        _clean_rpyc(game_dir, None)

    # ── 5. 保存 & 报告 ──
    glossary.save(str(glossary_path))
    try:
        translation_db.save()
    except OSError as e:
        logger.warning(f"[WARN] 保存 translation_db 失败: {e}")

    # Round 31 Tier C: opt-in runtime-hook emit (skipped unless --emit-runtime-hook)
    try:
        from core.runtime_hook_emitter import emit_if_requested
        emit_if_requested(args, output_dir, translation_db)
    except ImportError:
        pass

    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info("tl-mode 翻译完成")
    logger.info("=" * 60)
    logger.info(f"[TL-MODE] 扫描: {len(results)} 个文件")
    logger.info(f"[TL-MODE] 待翻译: {len(untrans_dlg)} 个对话, {len(untrans_str)} 个字符串")
    logger.info(f"[TL-MODE] 翻译成功: {total_translated} 条")
    logger.info(f"[TL-MODE] Checker 丢弃: {total_checker_dropped} 条")
    logger.info(f"[TL-MODE] Fallback 匹配: {total_fallback_matched} 条")
    logger.info(f"[TL-MODE] 回填成功: {total_filled} 条")
    logger.info(f"[TL-MODE] 耗时: {elapsed / 60:.1f} 分钟")
    logger.info(f"[TL-MODE] API 用量: {client.usage.summary()}")

    report = {
        "mode": "tl-mode",
        "tl_lang": tl_lang,
        "total_files": len(results),
        "total_dialogues_scanned": sum(len(r.dialogues) for r in results),
        "total_strings_scanned": sum(len(r.strings) for r in results),
        "untranslated_dialogues": len(untrans_dlg),
        "untranslated_strings": len(untrans_str),
        "translated": total_translated,
        "checker_dropped": total_checker_dropped,
        "fallback_matched": total_fallback_matched,
        "filled": total_filled,
        "elapsed_minutes": round(elapsed / 60, 1),
        "provider": args.provider,
        "model": config.model,
        "api_requests": client.usage.total_requests,
        "input_tokens": client.usage.total_input_tokens,
        "output_tokens": client.usage.total_output_tokens,
        "estimated_cost_usd": round(client.usage.estimated_cost, 4),
    }
    report_path = output_dir / "tl_mode_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"[TL-MODE] 报告: {report_path}")
