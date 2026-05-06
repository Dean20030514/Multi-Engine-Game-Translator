#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""direct-mode 翻译引擎入口：将完整 .rpy 文件发给 AI，由 AI 自行识别可翻译内容。

第 23 轮 (A-H-4) 起本文件被拆为 4 个模块，保持 ``translators.direct`` 公开
API（``run_pipeline`` 等）不变：

    translators/
    ├── direct.py              ← 本文件：入口 ``run_pipeline`` + 下层模块 re-export
    ├── _direct_chunk.py       ← chunk 级翻译与重试状态机
    ├── _direct_file.py        ← 文件级翻译与 targeted 子路径
    └── _direct_cli.py         ← dry-run 预览与统计

使用方只需继续 ``from translators.direct import run_pipeline`` / ``translate_file`` /
``_should_retry`` / ``_split_chunk`` 即可，re-export 在本文件下方统一维护。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import fnmatch
import json
import logging
import signal
import shutil
import sys
import time
import threading
from pathlib import Path

from core.api_client import APIClient, APIConfig
from core.glossary import Glossary
from core.translation_db import TranslationDB
from core.translation_utils import ProgressTracker, ProgressBar
from file_processor import estimate_tokens, read_file
from core.font_patch import apply_font_patch, resolve_font, default_resources_fonts_dir

# Re-export 兼容层：下游调用方 (main.py / engines/renpy_engine.py /
# tests/test_all.py / tests/test_batch1.py / tests/test_direct_pipeline.py)
# 历史上从 ``translators.direct`` 导入下列符号。A-H-4 拆分后符号实际定义在
# 子模块中，但 direct.py 仍然暴露同名别名，确保零回归。
from translators._direct_chunk import (  # noqa: F401
    _should_retry,
    _split_chunk,
    _translate_chunk,
    _translate_chunk_with_retry,
)
from translators._direct_cli import (
    _compute_file_dialogue_stats,
    _print_density_histogram,
    _print_term_scan_preview,
)
from translators._direct_file import (  # noqa: F401
    _translate_file_targeted,
    translate_file,
)

logger = logging.getLogger("multi_engine_translator")


def run_pipeline(args: argparse.Namespace) -> None:
    """运行完整翻译流水线"""
    # SIGTERM 优雅终止支持（非 Windows 平台；Windows 使用 GUI 发送的 CTRL_C_EVENT）
    _interrupted = threading.Event()

    def _sigterm_handler(signum, frame):
        _interrupted.set()
        logger.info("[SIGTERM] 收到终止信号，正在保存进度...")

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sigterm_handler)

    game_dir = Path(args.game_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Ren'Py 整文件翻译工具")
    logger.info("=" * 60)
    logger.info(f"游戏目录: {game_dir}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"API: {args.provider} / {args.model or '默认'}")
    # Round 53 W4: direct-mode source-language assumption.
    #   ``translators/renpy_text_utils.py::MIN_ENGLISH_CHARS_FOR_UNTRANSLATED``
    #   hard-codes 12 ASCII letters as the leakage-detection threshold,
    #   so direct-mode is implicitly English-source-only. Non-English
    #   source games (ja/ko/etc) should use tl-mode, which scans tl/
    #   directory slots and is source-language agnostic.
    logger.info(
        "[NOTE] direct-mode 假设源语言为 English；非英语源游戏请改用 tl-mode "
        "（详见 README §source language assumption）"
    )
    logger.info("")

    # 初始化 API 客户端
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
    logger.info(f"[API ] 速率限制: RPM={args.rpm}, RPS={args.rps}")
    if args.workers > 1:
        logger.info(f"[API ] chunk 并发线程: {args.workers}")
    file_workers = getattr(args, "file_workers", 1) or 1
    if file_workers > 1:
        logger.info(f"[API ] 文件级并行: {file_workers} 个文件同时翻译")

    # 初始化术语表
    glossary = Glossary()
    glossary_path = output_dir / "glossary.json"
    glossary.load(str(glossary_path))
    glossary.scan_game_directory(str(game_dir))

    # 加载外部词典
    if args.dict:
        for dict_path in args.dict:
            if not Path(dict_path).exists():
                logger.warning(f"[WARN] 词典文件不存在，跳过: {dict_path}")
                continue
            glossary.load_dict(dict_path)

    # 加载项目级系统 UI 术语（可选）
    system_terms_path = output_dir / "system_ui_terms.json"
    glossary.load_system_terms(str(system_terms_path))

    logger.info(
        f"[GLOSS] {len(glossary.characters)} 角色, "
        f"{len(glossary.terms)} 术语, "
        f"{len(glossary.memory)} 翻译记忆"
    )

    # 初始化进度追踪
    # Round 52 C4 BREAKING: language= / default_language= kwargs retired.
    progress = ProgressTracker(output_dir / "progress.json")
    if not args.resume and progress.data.get("completed_files"):
        logger.info(f"[INFO] 发现旧进度（已完成 {len(progress.data['completed_files'])} 个文件）")
        logger.info("[INFO] 清除旧进度，从头开始（如需续传请加 --resume）")
        progress.data = {"completed_files": [], "completed_chunks": {}, "stats": {}}
        progress.save()

    # 初始化 translation DB（用于增量与重翻统计）
    db_path = output_dir / "translation_db.json"
    translation_db = TranslationDB(db_path)
    translation_db.load()
    # 以时间戳标记本次运行；足够区分不同批次
    run_id = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    stage = getattr(args, "stage", "single") or "single"

    # 扫描 RPY 文件
    rpy_files = sorted(game_dir.rglob("*.rpy"))
    if not rpy_files:
        logger.error("[ERROR] 未找到 .rpy 文件")
        return

    # 自动排除 Ren'Py 引擎自带文件（renpy/ 目录）
    engine_excluded = 0
    filtered = []
    for f in rpy_files:
        rel = str(f.relative_to(game_dir))
        # 排除 renpy/ 和 lib/ 引擎目录
        parts = f.relative_to(game_dir).parts
        if parts and parts[0].lower() in ("renpy", "lib", "__pycache__"):
            engine_excluded += 1
            continue
        filtered.append(f)
    if engine_excluded:
        logger.info(f"[EXCL] 自动排除 {engine_excluded} 个引擎文件 (renpy/, lib/)")
    rpy_files = filtered

    if not rpy_files:
        logger.error("[ERROR] 排除引擎文件后未找到 .rpy 文件")
        return

    # 排除指定模式的文件
    if args.exclude:
        before = len(rpy_files)
        rpy_files = [
            f
            for f in rpy_files
            if not any(fnmatch.fnmatch(str(f.relative_to(game_dir)), pat) for pat in args.exclude)
        ]
        excluded = before - len(rpy_files)
        if excluded:
            logger.info(f"[EXCL] 排除了 {excluded} 个匹配的文件")

    # tl 优先模式：若启用且检测到 tl/ 目录中的 .rpy，则仅翻译 tl 下的脚本
    if args.tl_priority:
        tl_files = [
            f
            for f in rpy_files
            if f.relative_to(game_dir).parts and f.relative_to(game_dir).parts[0] == "tl"
        ]
        if tl_files:
            logger.info(
                f"[MODE] 启用 tl 优先模式：检测到 {game_dir / 'tl'}，仅翻译 tl 下的脚本，共 {len(tl_files)} 个文件"
            )
            rpy_files = tl_files
        else:
            logger.warning(
                f"[WARN] 启用了 --tl-priority 但在 {game_dir / 'tl'} 下未找到 .rpy 文件，将回退为翻译所有非引擎脚本，请检查路径是否正确"
            )

    # 按大小排序（小文件优先，便于快速积累翻译记忆）
    rpy_files.sort(key=lambda f: f.stat().st_size)

    total_files = len(rpy_files)
    done_files = sum(1 for f in rpy_files if progress.is_file_done(str(f.relative_to(game_dir))))
    logger.info(f"\n[SCAN] 共 {total_files} 个 .rpy 文件, 已完成 {done_files} 个")

    # 延迟估算 token ―― 只统计未完成文件的 token
    remaining_files = [
        f for f in rpy_files if not progress.is_file_done(str(f.relative_to(game_dir)))
    ]
    if remaining_files:
        remaining_tokens = sum(estimate_tokens(read_file(f)) for f in remaining_files)
        logger.info(f"[SCAN] 剩余约 {remaining_tokens:,} tokens")
    else:
        remaining_tokens = 0

    # --dry-run: 仅展示待翻译信息，不实际调用 API
    if args.dry_run:
        from core.api_client import get_pricing, is_reasoning_model

        logger.info("\n" + "=" * 60)
        logger.info("[DRY-RUN] 以下文件将被翻译:")
        logger.info("=" * 60)
        file_stats = []
        max_chunk = getattr(args, "max_chunk_tokens", 4000) or 4000
        total_chunks = 0
        for f in remaining_files:
            rel = f.relative_to(game_dir)
            tok = estimate_tokens(read_file(f))
            n_chunks = max(1, tok // max_chunk + (1 if tok % max_chunk else 0))
            total_chunks += n_chunks
            file_stats.append((rel, tok, f.stat().st_size, n_chunks))
            logger.info(
                f"  {rel}  ({tok:,} tokens, {f.stat().st_size / 1024:.0f} KB"
                + (f", {n_chunks} chunks)" if n_chunks > 1 else ")")
            )

        # 统计分布
        if file_stats:
            small = sum(1 for _, t, _, _ in file_stats if t <= 10000)
            medium = sum(1 for _, t, _, _ in file_stats if 10000 < t <= 50000)
            large = sum(1 for _, t, _, _ in file_stats if t > 50000)
            logger.info(
                f"\n文件分布: 小(≤10K tokens): {small}, 中(10-50K): {medium}, 大(>50K): {large}"
            )
            logger.info(f"预计 API 调用次数: {total_chunks}")

            # 显示最大的 5 个文件
            top5 = sorted(file_stats, key=lambda x: x[1], reverse=True)[:5]
            logger.info("\n最大文件:")
            for rel, tok, _, nc in top5:
                logger.info(f"  {rel}: {tok:,} tokens (约 {nc} 个 chunk)")

        # ---- 精确费用估算 ----
        price_in, price_out, price_exact = get_pricing(config.provider, config.model)
        reasoning = is_reasoning_model(config.model)

        # 输入 = 文件内容 + 每次请求的 system prompt 开销
        # system prompt 约 1500-2000 tokens，加上 user prompt 包装 ≈ 2000 tokens/request
        sys_prompt_overhead = 2000
        total_input = remaining_tokens + total_chunks * sys_prompt_overhead

        # 输出：整文件翻译的 JSON 输出 ≈ 原文件 token 数的 60%
        # （约 40% 行可翻译，每条包含 original + zh + JSON 结构）
        visible_output = int(remaining_tokens * 0.6)

        # 推理模型的 thinking tokens 通常是可见输出的 3~5 倍
        if reasoning:
            reasoning_tokens = visible_output * 4
            total_output = visible_output + reasoning_tokens
        else:
            reasoning_tokens = 0
            total_output = visible_output

        est_cost = (total_input * price_in + total_output * price_out) / 1_000_000

        # 如果用户通过 CLI 覆盖了价格
        if hasattr(args, "input_price") and args.input_price is not None:
            price_in = args.input_price
        if hasattr(args, "output_price") and args.output_price is not None:
            price_out = args.output_price
        if (
            hasattr(args, "input_price")
            and args.input_price is not None
            or hasattr(args, "output_price")
            and args.output_price is not None
        ):
            est_cost = (total_input * price_in + total_output * price_out) / 1_000_000

        logger.info(f"\n{'=' * 40}")
        logger.info(f"模型: {config.model}")
        logger.info(f"定价: ${price_in:.2f} / ${price_out:.2f} 每百万 tokens (input/output)")
        if not price_exact:
            logger.info(f"[!] 模型 '{config.model}' 未在定价表中精确匹配，使用提供商兜底价格")
            logger.info("   建议用 --input-price / --output-price 手动指定准确价格")
        if reasoning:
            logger.info("[*] 推理模型: thinking tokens 会显著增加输出费用")
        logger.info(f"{'=' * 40}")
        logger.info(f"剩余文件: {len(remaining_files)}")
        logger.info(f"API 调用次数: ~{total_chunks}")
        logger.info(
            f"估计输入 tokens: ~{total_input:,} (内容 {remaining_tokens:,} + 提示词开销 {total_chunks * sys_prompt_overhead:,})"
        )
        logger.info(f"估计可见输出 tokens: ~{visible_output:,}")
        if reasoning:
            logger.info(f"估计推理 tokens: ~{reasoning_tokens:,} (thinking)")
            logger.info(f"估计总输出 tokens: ~{total_output:,}")
        logger.info(f"\n>>> 估计费用: ${est_cost:.2f}")
        if reasoning:
            low = est_cost * 0.6
            high = est_cost * 1.5
            logger.info(f"   (推理 token 波动大，实际范围约 ${low:.2f} ~ ${high:.2f})")
        # ---- verbose 增强详情 ----
        if getattr(args, "verbose", False) and file_stats:
            logger.info("\n" + "=" * 60)
            logger.info("[DRY-RUN] 详细分析（--verbose）")
            logger.info("=" * 60)

            densities = []
            min_density = getattr(args, "min_dialogue_density", 0.20) or 0.20
            for rel, tok, _size, n_chunks in file_stats:
                fpath = game_dir / rel
                try:
                    dlg_count, density = _compute_file_dialogue_stats(fpath)
                except (OSError, ValueError, UnicodeDecodeError):
                    logger.debug(f"dry-run 文件统计失败: {fpath}", exc_info=True)
                    dlg_count, density = 0, 0.0
                densities.append(density)
                strategy = "定向" if density < min_density else "全文"
                est_file_cost = (
                    (tok + sys_prompt_overhead) * price_in + int(tok * 0.6) * price_out
                ) / 1_000_000
                logger.info(
                    f"  {rel}: {dlg_count} 对话行, 密度 {density * 100:.1f}%, "
                    f"~${est_file_cost:.4f}, 策略={strategy}"
                )

            _print_density_histogram(densities)
            _print_term_scan_preview(glossary)

        logger.info("\n去掉 --dry-run 参数开始实际翻译。")
        return

    logger.info("")

    # 设置日志文件：开一次句柄、复用，避免每条日志都 open/close
    # （Windows 上 NTFS 元数据更新 + Defender 实时扫描让 open/close 格外贵）
    log_fp = None
    if hasattr(args, "log_file") and args.log_file:
        _log_path = Path(args.log_file)
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_fp = open(_log_path, "a", encoding="utf-8")
        except OSError as e:
            logger.warning(f"[LOG] 无法打开日志文件 {_log_path}: {e}")
            log_fp = None

    def log(msg: str):
        """同时输出到控制台和日志文件"""
        if log_fp is not None:
            try:
                log_fp.write(msg + "\n")
                log_fp.flush()
            except OSError:
                pass

    # 开始翻译
    start_time = time.time()
    total_translated = 0
    total_checker_dropped = 0
    total_warnings = []
    files_done_this_run = 0
    quality_report: dict[str, list[dict]] = {}
    all_chunk_stats: list[dict] = []

    # 进度条（仅非 quiet 模式下显示）
    show_progress_bar = not getattr(args, "quiet", False) and not getattr(args, "dry_run", False)
    progress_bar = ProgressBar(total_files) if show_progress_bar and total_files > 0 else None

    # -- 共用的单文件翻译函数 --
    _results_lock = threading.Lock()

    def _translate_one_file(i: int, rpy_path: Path):
        """翻译单个文件，返回 (count, warnings, checker_dropped, chunk_stats) 或异常。"""
        nonlocal total_translated, total_checker_dropped, files_done_this_run

        rel = rpy_path.relative_to(game_dir)
        done_count = len(progress.data.get("completed_files", []))
        pct = done_count / total_files * 100 if total_files > 0 else 0

        # ETA 计算
        eta_str = ""
        if files_done_this_run > 0:
            elapsed_so_far = time.time() - start_time
            remaining_files_count = total_files - done_count
            avg_time_per_file = elapsed_so_far / files_done_this_run
            eta_seconds = remaining_files_count * avg_time_per_file
            if eta_seconds > 3600:
                eta_str = f" | ETA {eta_seconds / 3600:.1f}h"
            elif eta_seconds > 60:
                eta_str = f" | ETA {eta_seconds / 60:.0f}min"
            else:
                eta_str = f" | ETA {eta_seconds:.0f}s"

        logger.info(f"\n[{i}/{total_files}] ({pct:.0f}%{eta_str}) {rel}")
        log(f"[{i}/{total_files}] ({pct:.0f}%) {rel}")

        count, warnings, checker_dropped, file_chunk_stats = translate_file(
            rpy_path,
            game_dir,
            output_dir / "game",
            client,
            glossary,
            progress,
            quality_report,
            genre=args.genre,
            max_tokens_per_chunk=args.max_chunk_tokens,
            workers=args.workers,
            translation_db=translation_db,
            run_id=run_id,
            stage=stage,
            provider=config.provider,
            model=config.model,
            min_dialogue_density=getattr(args, "min_dialogue_density", 0.20),
            cot=getattr(args, "cot", False),
        )
        return count, warnings, checker_dropped, file_chunk_stats

    def _collect_result(count, warnings, checker_dropped, file_chunk_stats):
        """线程安全地汇总单个文件的翻译结果。"""
        nonlocal total_translated, total_checker_dropped, files_done_this_run
        with _results_lock:
            total_translated += count
            total_checker_dropped += checker_dropped
            total_warnings.extend(warnings)
            all_chunk_stats.extend(file_chunk_stats)
            files_done_this_run += 1
            if progress_bar:
                progress_bar.cost = client.usage.estimated_cost
                progress_bar.update(1)

    if file_workers > 1 and len(rpy_files) > 1:
        # ── 文件级并行翻译 ──
        logger.info(f"[并行] 启用文件级并行: {file_workers} 个文件同时翻译")
        with concurrent.futures.ThreadPoolExecutor(max_workers=file_workers) as executor:
            futures: dict[concurrent.futures.Future, Path] = {}
            for i, rpy_path in enumerate(rpy_files, 1):
                if _interrupted.is_set():
                    break
                fut = executor.submit(_translate_one_file, i, rpy_path)
                futures[fut] = rpy_path

            for fut in concurrent.futures.as_completed(futures):
                rpy_path = futures[fut]
                rel = rpy_path.relative_to(game_dir)
                try:
                    count, warnings, checker_dropped, file_chunk_stats = fut.result()
                    _collect_result(count, warnings, checker_dropped, file_chunk_stats)
                except KeyboardInterrupt:
                    logger.info("\n[中断] 保存进度...")
                    glossary.save(str(glossary_path))
                    progress.save()
                    try:
                        translation_db.save()
                    except OSError as e:
                        logger.debug(f"中断时保存 translation_db 失败: {e}")
                    logger.info("[中断] 进度已保存，可用 --resume 继续")
                    sys.exit(1)
                except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as e:
                    msg = f"文件 {rel} 处理失败: {e}"
                    logger.error(f"  [ERROR] {msg}")
                    with _results_lock:
                        total_warnings.append(msg)

            # 定期保存术语表
            glossary.save(str(glossary_path))
    else:
        # ── 顺序翻译（默认） ──
        for i, rpy_path in enumerate(rpy_files, 1):
            if _interrupted.is_set():
                logger.info("[SIGTERM] 翻译中断，已保存进度。使用 --resume 继续。")
                break

            try:
                count, warnings, checker_dropped, file_chunk_stats = _translate_one_file(
                    i, rpy_path
                )
                _collect_result(count, warnings, checker_dropped, file_chunk_stats)
            except KeyboardInterrupt:
                logger.info("\n[中断] 保存进度...")
                glossary.save(str(glossary_path))
                progress.save()
                try:
                    translation_db.save()
                except OSError as e:
                    logger.debug(f"中断时保存 translation_db 失败: {e}")
                logger.info("[中断] 进度已保存，可用 --resume 继续")
                sys.exit(1)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as e:
                rel = rpy_path.relative_to(game_dir)
                msg = f"文件 {rel} 处理失败: {e}"
                logger.error(f"  [ERROR] {msg}")
                total_warnings.append(msg)
                continue

            # 定期保存术语表
            if i % 5 == 0:
                glossary.save(str(glossary_path))

    if progress_bar:
        progress_bar.finish()

    # 最终保存
    glossary.save(str(glossary_path))
    try:
        translation_db.save()
    except OSError as e:
        logger.warning(f"[WARN] 保存 translation_db.json 失败: {e}")

    # Round 31 Tier C: opt-in runtime-hook emit (skipped unless --emit-runtime-hook)
    try:
        from core.runtime_hook_emitter import emit_if_requested

        emit_if_requested(args, output_dir, translation_db)
    except ImportError:
        pass

    # 复制非 .rpy 文件（可选）
    if args.copy_assets:
        logger.info("\n[复制] 复制非 .rpy 文件...")
        asset_count = 0
        for src in game_dir.rglob("*"):
            if src.is_file() and src.suffix.lower() not in (".rpy", ".rpyc", ".rpymc", ".rpyb"):
                rel = src.relative_to(game_dir)
                dst = output_dir / "game" / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy2(src, dst)
                    asset_count += 1
        if asset_count:
            logger.info(f"[复制] 复制了 {asset_count} 个资源文件")

    # 自动字体补丁（可选）
    # Round 32: migrated from ``Path(__file__).parent / "resources" / "fonts"``
    # which was missing one ``.parent`` (translators/ is one level below root)
    # and silently returned None for the fonts dir on source-code runs.
    if getattr(args, "patch_font", False):
        resources_fonts = default_resources_fonts_dir()
        font_path = resolve_font(resources_fonts, args.font_file or None)
        if font_path:
            apply_font_patch(output_dir / "game", game_dir, font_path)
        # resolve_font 内部已打印警告，此处无需再报错

    # 总结
    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info("翻译完成")
    logger.info("=" * 60)
    logger.info(f"文件数: {total_files}")
    logger.info(f"翻译条目: {total_translated}")
    logger.info(f"Checker 丢弃（未写入译文）: {total_checker_dropped}")

    # per-chunk 指标摘要
    if all_chunk_stats:
        try:
            cs_total_expected = sum(c["expected"] for c in all_chunk_stats)
            cs_total_returned = sum(c["returned"] for c in all_chunk_stats)
            cs_total_dropped = sum(c["dropped"] for c in all_chunk_stats)
            ret_pct = (cs_total_returned / cs_total_expected * 100) if cs_total_expected else 0
            drop_pct = (cs_total_dropped / cs_total_returned * 100) if cs_total_returned else 0
            logger.info(
                f"[STATS] Chunks: {len(all_chunk_stats)} | "
                f"Expected: {cs_total_expected} | "
                f"Returned: {cs_total_returned} ({ret_pct:.1f}%) | "
                f"Dropped: {cs_total_dropped} ({drop_pct:.1f}%)"
            )
        except (ZeroDivisionError, KeyError, TypeError) as e:
            logger.debug(f"chunk 统计汇总计算失败: {e}")

    logger.info(f"警告: {len(total_warnings)}")
    logger.info(f"耗时: {elapsed / 60:.1f} 分钟")
    logger.info(f"API 用量: {client.usage.summary()}")
    logger.info(f"输出目录: {output_dir / 'game'}")

    if total_warnings:
        warnings_path = output_dir / "warnings.txt"
        warnings_path.write_text("\n".join(total_warnings), encoding="utf-8")
        logger.info(f"警告详情: {warnings_path}")

    # 保存质量检查报告（按文件归档）
    if quality_report:
        quality_path = output_dir / "quality_report.json"
        quality_path.write_text(
            json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"质量报告: {quality_path}")

    # 汇总 chunk_stats
    chunk_stats_summary = {}
    if all_chunk_stats:
        try:
            chunk_stats_summary = {
                "total_expected": sum(c["expected"] for c in all_chunk_stats),
                "total_returned": sum(c["returned"] for c in all_chunk_stats),
                "total_dropped": sum(c["dropped"] for c in all_chunk_stats),
                "per_chunk": all_chunk_stats,
            }
        except (KeyError, TypeError) as e:
            logger.debug(f"chunk 统计写入 report 失败: {e}")

    # 保存翻译报告
    report = {
        "total_files": total_files,
        "total_translated": total_translated,
        "total_checker_dropped": total_checker_dropped,
        "total_warnings": len(total_warnings),
        "elapsed_minutes": round(elapsed / 60, 1),
        "provider": args.provider,
        "model": config.model,
        "workers": args.workers,
        "file_workers": file_workers,
        "api_requests": client.usage.total_requests,
        "input_tokens": client.usage.total_input_tokens,
        "output_tokens": client.usage.total_output_tokens,
        "estimated_cost_usd": round(client.usage.estimated_cost, 4),
        "chunk_stats": chunk_stats_summary,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"翻译报告: {report_path}")

    # 关闭日志句柄（sys.exit 分支依赖 OS 在进程退出时自动回收；此处显式 close
    # 处理正常路径的优雅收尾，也便于 run_pipeline 被其他模块多次调用时不泄漏句柄）
    if log_fp is not None:
        try:
            log_fp.close()
        except OSError:
            pass
