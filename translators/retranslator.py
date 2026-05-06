#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补翻引擎：扫描已翻译文件中残留的英文对话行，构建小 chunk 精准补翻。"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from core.api_client import APIClient, APIConfig
from file_processor import (
    apply_translations,
    validate_translation,
    read_file,
    protect_placeholders,
)
from core.glossary import Glossary
from core.prompts import build_retranslate_system_prompt, build_retranslate_user_prompt
from core.translation_db import TranslationDB
from core.translation_utils import (
    ProgressTracker,
    _strip_char_prefix,
    _deduplicate_translations,
)
from file_processor import (
    _restore_placeholders_in_translations,
    _filter_checked_translations,
)

logger = logging.getLogger("multi_engine_translator")


def calculate_dialogue_density(content: str) -> float:
    """计算文件中对话行占非空行的比例。

    用于全量翻译时自动选择翻译策略：
    高密度文件 → 整文件翻译（AI 自主识别）；
    低密度文件 → 定向翻译（工具指定哪些行翻译）。
    """
    from translators.renpy_text_utils import _is_user_visible_string_line

    non_empty = 0
    dialogue = 0
    for line in content.splitlines():
        if not line.strip():
            continue
        non_empty += 1
        if _is_user_visible_string_line(line):
            dialogue += 1
    return dialogue / non_empty if non_empty else 0.0


# ============================================================
# 补翻模式 (--retranslate)
# ============================================================


def find_untranslated_lines(content: str) -> list[tuple[int, str]]:
    """扫描文件内容，找出仍含英文对话的行。

    复用 one_click_pipeline._is_user_visible_string_line 判断用户可见性，
    再用中/英字符比判断是否仍为未翻译英文。

    Returns:
        [(0-based_line_index, quoted_english_text), ...]
    """
    from translators.renpy_text_utils import _is_user_visible_string_line

    # screen 属性关键字——引号后紧跟这些词说明是 UI 布局行而非对话
    _SCREEN_ATTR_KW = {
        "xalign",
        "yalign",
        "xpos",
        "ypos",
        "xsize",
        "ysize",
        "xoffset",
        "yoffset",
        "xanchor",
        "yanchor",
        "at",
        "align",
        "pos",
        "anchor",
        "size",
        "area",
    }

    results = []
    for i, line in enumerate(content.splitlines()):
        if not _is_user_visible_string_line(line):
            continue
        stripped = line.strip()

        # --- 二次过滤：排除非对话行 ---
        # auto 图片定义行：auto "path_%s.png"（来自 SAZMOD locations.rpy 等）
        if stripped.startswith('auto "'):
            continue
        # imagebutton 属性行：idle/hover/insensitive "image_name"
        if stripped.startswith(('idle "', 'hover "', 'insensitive "')):
            continue

        m = re.search(r'"([^"\\]*(?:\\.[^"\\]*)*)"', line)
        if not m:
            continue
        s = m.group(1)
        if len(s) < 20:
            continue
        if any(x in s for x in ("/", "\\", ".png", ".jpg", ".webp", ".ttf", ".webm")):
            continue

        # screen 布局行：text "..." 后紧跟 xalign/ypos 等属性
        # 样本：text "Davide" xalign .5 ypos 150
        after_quote = line[m.end() :]
        first_word = after_quote.split()[0] if after_quote.split() else ""
        if first_word.lower() in _SCREEN_ATTR_KW:
            continue

        cn = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
        en = sum(1 for c in s if "a" <= c.lower() <= "z")
        if cn == 0 and en >= 12:
            results.append((i, s))
    return results


def build_retranslate_chunks(
    all_lines: list[str],
    untranslated_indices: list[int],
    context: int = 3,
    max_per_chunk: int = 20,
) -> list[list[tuple[int, str, bool]]]:
    """将漏翻行分组为小 chunk，每个 chunk 附带上下文行。

    对非连续的漏翻行，合并重叠的上下文窗口，用 ``...`` 分隔符标记不连续区域。

    Returns:
        list of chunks; 每个 chunk 为 [(1-based_lineno, line_content, is_target), ...]
        分隔行以 lineno=0、content="..." 表示。
    """
    if not untranslated_indices:
        return []

    target_set = set(untranslated_indices)
    n_lines = len(all_lines)

    def _merge_ranges(indices: list[int]) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        for idx in sorted(indices):
            lo = max(0, idx - context)
            hi = min(n_lines - 1, idx + context)
            if ranges and lo <= ranges[-1][1] + 1:
                ranges[-1] = (ranges[-1][0], hi)
            else:
                ranges.append((lo, hi))
        return ranges

    chunks: list[list[tuple[int, str, bool]]] = []
    for start in range(0, len(untranslated_indices), max_per_chunk):
        group = untranslated_indices[start : start + max_per_chunk]
        ranges = _merge_ranges(group)
        chunk_lines: list[tuple[int, str, bool]] = []
        for ri, (lo, hi) in enumerate(ranges):
            if ri > 0:
                chunk_lines.append((0, "...", False))
            for idx in range(lo, hi + 1):
                chunk_lines.append((idx + 1, all_lines[idx], idx in target_set))
        chunks.append(chunk_lines)

    return chunks


def retranslate_file(
    rpy_path: Path,
    game_dir: Path,
    output_dir: Path,
    client: APIClient,
    glossary: Glossary,
    progress: ProgressTracker,
    genre: str = "adult",
    context_lines: int = 3,
    max_per_chunk: int = 20,
    *,
    translation_db: Optional[TranslationDB] = None,
    run_id: str = "",
    stage: str = "retranslate",
    provider: str = "",
    model: str = "",
) -> tuple[int, list[str]]:
    """补翻单个文件中残留的英文对话行。

    流程：扫描漏翻行 → 构建小 chunk → 发送专用 prompt → 逐条检查 → 回写。
    走 apply_translations + validate_translation 现有安全流程。

    Returns:
        (translated_count, warnings)
    """
    rel_path = str(rpy_path.relative_to(game_dir))

    if progress.is_file_done(rel_path):
        return 0, []

    content = read_file(rpy_path)
    all_lines = content.splitlines()

    untranslated = find_untranslated_lines(content)
    if not untranslated:
        progress.mark_file_done(rel_path)
        return 0, []

    logger.debug(f"  [RETRANSLATE] {rel_path}: {len(untranslated)} 行待补翻")

    indices = [idx for idx, _ in untranslated]
    chunks = build_retranslate_chunks(all_lines, indices, context_lines, max_per_chunk)

    # Round 52 C4 BREAKING: lang_config retired (zh-only).
    system_prompt = build_retranslate_system_prompt(
        glossary_text=glossary.to_prompt_text(),
    )

    all_translations: list[dict] = []
    all_warnings: list[str] = []

    for ci, chunk_lines in enumerate(chunks, 1):
        # 占位符保护：先在拼接的原始文本上检测模式，再逐行替换
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
        logger.debug(f"    [API ] 补翻块 {ci}/{len(chunks)} ({target_count} 行)")

        try:
            translations = client.translate(system_prompt, user_prompt)
        except Exception as e:
            warn = f"补翻块 {ci} API 调用失败: {e}"
            logger.error(f"    [ERROR] {warn}")
            all_warnings.append(warn)
            continue

        _restore_placeholders_in_translations(translations, ph_mapping)
        _strip_char_prefix(translations)

        kept, _, _, check_warns = _filter_checked_translations(translations)
        for w in check_warns:
            logger.debug(f"    {w}")
        all_warnings.extend(check_warns)

        if kept:
            logger.debug(f"    [OK  ] 补翻块 {ci}: 获得 {len(kept)} 条翻译")
        all_translations.extend(kept)

    if not all_translations:
        progress.mark_file_done(rel_path)
        return 0, all_warnings

    unique = _deduplicate_translations(all_translations)

    # 回写（走现有安全流程）
    patched, patch_warnings, _ = apply_translations(content, unique)
    all_warnings.extend(patch_warnings)

    issues = validate_translation(
        content,
        patched,
        rel_path,
        glossary_terms=glossary.terms,
        glossary_locked=glossary.locked_terms,
        glossary_no_translate=glossary.no_translate,
    )
    for issue in issues:
        if issue["level"] == "error":
            all_warnings.append(f"行 {issue['line']}: {issue['message']}")

    if translation_db is not None and unique:
        db_entries = []
        for item in unique:
            line_no = int(item.get("line") or 0)
            original = item.get("original", "") or ""
            # Round 52 C4 BREAKING: lang_config / resolve_translation_field
            # retired.  Hard-coded ``"zh"`` field read.
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

    # 原地补翻时自动备份原文件（.bak 已存在则不覆盖，保留最早备份）
    if out_path.resolve() == rpy_path.resolve():
        bak_path = out_path.with_suffix(out_path.suffix + ".bak")
        if not bak_path.exists():
            try:
                shutil.copy2(out_path, bak_path)
            except OSError as e:
                logger.warning(f"创建备份失败 {bak_path}: {e}")

    out_path.write_text(patched, encoding="utf-8")

    glossary.update_from_translations(unique)
    progress.mark_file_done(rel_path)

    return len(unique), all_warnings


def run_retranslate_pipeline(args: argparse.Namespace) -> None:
    """运行漏翻补翻流水线。

    扫描 --game-dir 中的已翻译 .rpy 文件，提取残留英文对话行，
    构建小 chunk 发送专用 prompt，将补翻结果回写到 --output-dir。
    """
    game_dir = Path(args.game_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Ren'Py 漏翻补翻模式")
    logger.info("=" * 60)
    logger.info(f"扫描目录: {game_dir}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"API: {args.provider} / {args.model or '默认'}")
    if game_dir.resolve() == output_dir.resolve():
        logger.warning("[WARN] 输入输出目录相同，将原地覆写已翻译文件。如未备份请 Ctrl+C 中止。")
    logger.info("")

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

    # 补翻使用独立进度文件，不干扰主翻译进度
    # Round 52 C4 BREAKING: language= / default_language= kwargs retired.
    progress = ProgressTracker(output_dir / "retranslate_progress.json")
    if not args.resume and progress.data.get("completed_files"):
        progress.data = {"completed_files": [], "completed_chunks": {}, "stats": {}}
        progress.save()

    db_path = output_dir / "translation_db.json"
    translation_db = TranslationDB(db_path)
    translation_db.load()
    run_id = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    # 扫描 .rpy 文件，排除引擎目录
    rpy_files = sorted(game_dir.rglob("*.rpy"))
    filtered = []
    for f in rpy_files:
        parts = f.relative_to(game_dir).parts
        if parts and parts[0].lower() in ("renpy", "lib", "__pycache__"):
            continue
        filtered.append(f)
    rpy_files = filtered

    if not rpy_files:
        logger.error("[ERROR] 未找到 .rpy 文件")
        return

    # 预扫描：统计各文件漏翻行数
    logger.info(f"[SCAN] 扫描 {len(rpy_files)} 个文件的漏翻行...")
    files_with_untranslated: list[tuple[Path, int]] = []
    total_untranslated = 0
    for f in rpy_files:
        content = read_file(f)
        ut = find_untranslated_lines(content)
        if ut:
            files_with_untranslated.append((f, len(ut)))
            total_untranslated += len(ut)

    if not files_with_untranslated:
        logger.info("[INFO] 未发现漏翻行，无需补翻")
        return

    done_count = sum(
        1 for f, _ in files_with_untranslated if progress.is_file_done(str(f.relative_to(game_dir)))
    )
    logger.info(
        f"[SCAN] 发现 {total_untranslated} 行漏翻，分布在 "
        f"{len(files_with_untranslated)} 个文件中"
        f"（已完成 {done_count} 个）"
    )

    start_time = time.time()
    total_translated = 0
    total_warnings: list[str] = []

    for i, (rpy_path, n_ut) in enumerate(files_with_untranslated, 1):
        rel = rpy_path.relative_to(game_dir)
        logger.info(f"\n[{i}/{len(files_with_untranslated)}] {rel} ({n_ut} 行)")

        try:
            count, warnings = retranslate_file(
                rpy_path,
                game_dir,
                output_dir,
                client,
                glossary,
                progress,
                genre=args.genre,
                translation_db=translation_db,
                run_id=run_id,
                stage="retranslate",
                provider=config.provider,
                model=config.model,
            )
            total_translated += count
            total_warnings.extend(warnings)
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
        except Exception as e:
            msg = f"文件 {rel} 补翻失败: {e}"
            logger.error(f"  [ERROR] {msg}")
            total_warnings.append(msg)

        if i % 5 == 0:
            glossary.save(str(glossary_path))

    # 最终保存
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
    logger.info("补翻完成")
    logger.info("=" * 60)
    logger.info(f"补翻条目: {total_translated}")
    logger.info(f"警告: {len(total_warnings)}")
    logger.info(f"耗时: {elapsed / 60:.1f} 分钟")
    logger.info(f"API 用量: {client.usage.summary()}")

    report = {
        "mode": "retranslate",
        "total_untranslated_scanned": total_untranslated,
        "files_with_untranslated": len(files_with_untranslated),
        "total_translated": total_translated,
        "total_warnings": len(total_warnings),
        "elapsed_minutes": round(elapsed / 60, 1),
        "provider": args.provider,
        "model": config.model,
        "api_requests": client.usage.total_requests,
        "input_tokens": client.usage.total_input_tokens,
        "output_tokens": client.usage.total_output_tokens,
        "estimated_cost_usd": round(client.usage.estimated_cost, 4),
    }
    report_path = output_dir / "retranslate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"补翻报告: {report_path}")
