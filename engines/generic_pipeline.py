#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用翻译流水线：所有非 Ren'Py 引擎共用的翻译编排器。

流程：提取 → 分块 → 并发翻译 → 回写 → 报告。
基于 TranslatableUnit 而非 .rpy 文件，不替代 Ren'Py 的三条专用管线。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from safety.file_safety import check_fstat_size

logger = logging.getLogger("multi_engine_translator")

# Round 42 M2 phase-3: 50 MB cap on the progress.json reader.  Typical
# legitimate progress files are a few KB to a few hundred KB (one entry
# per completed chunk); anything approaching 50 MB is either corrupt or
# a non-progress file accidentally pointed at by ``--resume-file``.
# Matches the cap used by r37-r41 user-facing JSON loaders.
_MAX_PROGRESS_JSON_SIZE = 50 * 1024 * 1024


# ============================================================
# GenericChunk 数据类
# ============================================================


@dataclass
class GenericChunk:
    """通用翻译 chunk，按文件分组 + 条数/字符数拆分。"""

    chunk_id: int
    units: list = field(default_factory=list)  # list[TranslatableUnit]
    file_path: str = ""


def build_generic_chunks(
    units: list,
    max_size: int = 30,
    max_chars: int = 6000,
) -> list[GenericChunk]:
    """将 TranslatableUnit 列表按 file_path 分组、按条数/字符数拆块。"""
    # 按 file_path 分组
    by_file: dict[str, list] = {}
    for u in units:
        by_file.setdefault(u.file_path, []).append(u)

    chunks: list[GenericChunk] = []
    chunk_id = 0
    for file_path, file_units in by_file.items():
        current: list = []
        current_chars = 0
        for u in file_units:
            char_len = len(u.original)
            if current and (len(current) >= max_size or current_chars + char_len > max_chars):
                chunks.append(GenericChunk(chunk_id=chunk_id, units=current, file_path=file_path))
                chunk_id += 1
                current = []
                current_chars = 0
            current.append(u)
            current_chars += char_len
        if current:
            chunks.append(GenericChunk(chunk_id=chunk_id, units=current, file_path=file_path))
            chunk_id += 1
    return chunks


# ============================================================
# Prompt 构建
# ============================================================


def _build_generic_user_prompt(chunk: GenericChunk, target_lang: str = "zh") -> str:
    """构建通用 user prompt：JSON 数组格式。"""
    items = []
    for u in chunk.units:
        entry: dict[str, str] = {"id": u.id, "original": u.original}
        if u.speaker:
            entry["speaker"] = u.speaker
        if u.context:
            entry["context"] = u.context
        items.append(entry)
    header = (
        f"Translate the following {len(items)} text entries to {target_lang}.\n"
        f"Return a JSON array with the same 'id' and a '{target_lang}' field for the translation.\n"
        f"Do NOT translate placeholder tokens like __RENPY_PH_0__.\n\n"
    )
    return header + json.dumps(items, ensure_ascii=False, indent=2)


# ============================================================
# 翻译结果匹配
# ============================================================


def _match_translations_to_units(
    translations: list[dict],
    units: list,
    target_lang: str = "zh",
) -> int:
    """将 API 返回的翻译匹配到 TranslatableUnit，返回成功匹配数。"""
    # 翻译字段查找顺序
    field_names = [target_lang, "translation", "trans", "zh"]

    # 建立 id → unit 查找表
    id_map = {u.id: u for u in units}
    # 建立 original → unit 查找表（fallback）
    orig_map: dict[str, list] = {}
    for u in units:
        orig_map.setdefault(u.original.strip(), []).append(u)

    matched = 0
    for t in translations:
        # 提取翻译文本
        trans_text = ""
        for fn in field_names:
            val = t.get(fn, "")
            if val and isinstance(val, str) and val.strip():
                trans_text = val.strip()
                break
        if not trans_text:
            continue

        # 先按 id 匹配
        tid = t.get("id", "")
        unit = id_map.get(tid)
        if unit and unit.status == "pending":
            unit.translation = trans_text
            unit.status = "translated"
            matched += 1
            continue

        # fallback：按 original 匹配
        orig = (t.get("original", "") or "").strip()
        candidates = orig_map.get(orig, [])
        for u in candidates:
            if u.status == "pending":
                u.translation = trans_text
                u.status = "translated"
                matched += 1
                break

    return matched


# ============================================================
# 进度管理
# ============================================================


def _load_progress(progress_path: Path) -> set[int]:
    """加载已完成的 chunk_id 集合。"""
    if not progress_path.exists():
        return set()
    try:
        size = progress_path.stat().st_size
    except OSError:
        size = 0
    if size > _MAX_PROGRESS_JSON_SIZE:
        logger.warning(
            f"[PIPELINE] 进度文件 {progress_path} 过大 "
            f"({size} > {_MAX_PROGRESS_JSON_SIZE})，视为损坏重置"
        )
        return set()
    try:
        # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
        with open(progress_path, encoding="utf-8") as f:
            ok, fsize2 = check_fstat_size(f, _MAX_PROGRESS_JSON_SIZE)
            if not ok:
                logger.warning(
                    f"[PIPELINE] 进度文件 {progress_path} stat 后增长到 "
                    f"{fsize2} 字节（疑似 TOCTOU 攻击），视为损坏重置"
                )
                return set()
            data = json.loads(f.read())
        return set(data.get("completed_chunks", []))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _save_progress(progress_path: Path, completed: set[int]) -> None:
    """原子写入进度文件。"""
    tmp = progress_path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps({"completed_chunks": sorted(completed)}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(progress_path))
    except OSError as e:
        logger.warning(f"[PIPELINE] 保存进度失败: {e}")


# ============================================================
# 主流水线
# ============================================================


def run_generic_pipeline(engine, args) -> None:
    """通用翻译流水线入口。由 EngineBase.run() 默认调用。"""
    from core.api_client import APIClient, APIConfig
    from core.glossary import Glossary
    from core.translation_db import TranslationDB
    from file_processor import protect_placeholders, restore_placeholders, check_response_item
    from core.prompts import build_system_prompt

    game_dir = Path(args.game_dir)
    output_dir = Path(getattr(args, "output_dir", "output") or "output")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Round 52 C4 BREAKING: target_lang fixed to "zh"; lang_config retired.
    target_lang = "zh"
    profile = engine.profile

    # ── Stage 0: 提取 ──
    logger.info(f"\n[PIPELINE] 引擎: {profile.display_name}")
    logger.info("[PIPELINE] 提取可翻译文本...")
    units = engine.extract_texts(game_dir)
    if not units:
        logger.info("[PIPELINE] 未找到可翻译文本，退出")
        return

    files = set(u.file_path for u in units)
    total_chars = sum(len(u.original) for u in units)
    logger.info(
        f"[PIPELINE] 提取完成: {len(units)} 条文本, {len(files)} 个文件, {total_chars:,} 字符"
    )

    # dry-run 模式
    if getattr(args, "dry_run", False):
        logger.info(f"\n[DRY-RUN] {profile.display_name}: {len(units)} 条文本待翻译")
        logger.info("[DRY-RUN] 去掉 --dry-run 参数开始实际翻译。")
        return

    # ── Stage 1: 初始化 ──
    provider = getattr(args, "provider", "xai") or "xai"
    model = getattr(args, "model", "") or ""
    api_key = getattr(args, "api_key", "") or ""
    config = APIConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        custom_module=getattr(args, "custom_module", "") or "",
    )
    config.timeout = getattr(args, "timeout", 180.0) or 180.0
    config.temperature = getattr(args, "temperature", 0.1) or 0.1
    config.max_response_tokens = getattr(args, "max_response_tokens", 32768) or 32768

    config.rpm = getattr(args, "rpm", 60) or 60
    config.rps = getattr(args, "rps", 5) or 5
    client = APIClient(config)

    glossary = Glossary()
    glossary_path = output_dir / "glossary.json"
    glossary.load(str(glossary_path))
    if getattr(args, "dict", None):
        for dp in args.dict:
            if Path(dp).exists():
                glossary.load_dict(dp)
    # RPG Maker 引擎：自动从 Actors.json / System.json 提取角色名和系统术语
    if hasattr(glossary, "scan_rpgmaker_database") and profile.name in (
        "rpgmaker_mv",
        "rpgmaker_mz",
    ):
        try:
            glossary.scan_rpgmaker_database(game_dir)
        except Exception as e:
            logger.debug(f"[PIPELINE] RPG Maker 术语扫描失败（不影响翻译）: {e}")

    # Round 52 C4 BREAKING: default_language= retired (zh-only DB schema).
    translation_db = TranslationDB(output_dir / "translation_db.json")
    translation_db.load()

    # 构建 system prompt（带引擎 addon）
    glossary_text = glossary.to_prompt_text()
    genre = getattr(args, "genre", "adult") or "adult"
    system_prompt = build_system_prompt(
        genre=genre,
        glossary_text=glossary_text,
        engine_profile=profile,
    )

    # 占位符正则（引擎参数化）
    ph_patterns = profile.placeholder_patterns if profile.placeholder_patterns else None
    ph_re = profile.compile_placeholder_re()

    # 断点续传：从 translation_db 恢复已翻译的 unit
    progress_path = output_dir / "generic_progress.json"
    completed_chunks = _load_progress(progress_path)

    if translation_db.entries:
        # Round 52 C4 BREAKING: language-keyed resume retired (zh-only).
        # Index keyed by (file, original) only.
        db_index: dict[tuple[str, str], str] = {}
        for entry in translation_db.entries:
            key = (entry.get("file", ""), entry.get("original", ""))
            if entry.get("translation") and entry.get("status") == "ok":
                db_index[key] = entry["translation"]
        restored = 0
        for u in units:
            trans = db_index.get((u.file_path, u.original))
            if trans:
                u.translation = trans
                u.status = "translated"
                restored += 1
        if restored:
            logger.info(f"[PIPELINE] 从 translation_db 恢复 {restored} 条已翻译")

    # ── Stage 2: 分块 ──
    pending_units = [u for u in units if u.status == "pending"]
    logger.info(
        f"[PIPELINE] 待翻译: {len(pending_units)} 条（已完成 {len(units) - len(pending_units)} 条）"
    )

    chunks = build_generic_chunks(pending_units)
    remaining_chunks = [c for c in chunks if c.chunk_id not in completed_chunks]
    logger.info(
        f"[PIPELINE] 分块: {len(chunks)} 个 chunk（跳过 {len(chunks) - len(remaining_chunks)} 个已完成）"
    )

    if not remaining_chunks:
        logger.info("[PIPELINE] 所有 chunk 已完成，跳过翻译阶段")
    else:
        # ── Stage 3: 翻译 ──
        workers = max(1, getattr(args, "workers", 1) or 1)
        t0 = time.time()
        total_matched = 0

        def _translate_one_chunk(chunk: GenericChunk) -> int:
            """翻译单个 chunk，返回匹配数。"""
            # 构建 user prompt
            user_prompt = _build_generic_user_prompt(chunk, target_lang)

            # 占位符保护
            if ph_patterns:
                protected_prompt, ph_mapping = protect_placeholders(
                    user_prompt, patterns=ph_patterns
                )
            else:
                protected_prompt = user_prompt
                ph_mapping = []

            # API 调用
            try:
                translations = client.translate(system_prompt, protected_prompt)
            except Exception as e:
                logger.error(f"[PIPELINE] chunk {chunk.chunk_id} 翻译失败: {e}")
                return 0

            # 占位符还原
            if ph_mapping:
                for t in translations:
                    for key in ("id", "original", target_lang, "translation", "trans", "zh"):
                        val = t.get(key, "")
                        if val and isinstance(val, str):
                            t[key] = restore_placeholders(val, ph_mapping)

            # 逐条校验（Round 52 C4: lang_config kwarg retired, zh-only）
            valid = []
            for t in translations:
                warns = check_response_item(t, placeholder_re=ph_re)
                if not warns:
                    valid.append(t)

            # 匹配到 unit
            matched = _match_translations_to_units(valid, chunk.units, target_lang)

            # 记录到 translation_db
            for u in chunk.units:
                if u.status == "translated":
                    translation_db.upsert_entry(
                        {
                            "file": u.file_path,
                            "line": 0,
                            "original": u.original,
                            "translation": u.translation,
                            "status": "ok",
                            "error_codes": [],
                            "warning_codes": [],
                            "provider": provider,
                            "model": model,
                            "stage": "generic",
                        }
                    )

            return matched

        if workers <= 1:
            for chunk in remaining_chunks:
                m = _translate_one_chunk(chunk)
                total_matched += m
                completed_chunks.add(chunk.chunk_id)
                _save_progress(progress_path, completed_chunks)
                logger.debug(
                    f"  [CHUNK] {chunk.chunk_id + 1}/{len(chunks)}: 匹配 {m}/{len(chunk.units)} 条"
                )
        else:
            logger.info(f"[PIPELINE] 并发翻译: {workers} 线程")
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {executor.submit(_translate_one_chunk, c): c for c in remaining_chunks}
                for future in concurrent.futures.as_completed(future_map):
                    chunk = future_map[future]
                    try:
                        m = future.result()
                        total_matched += m
                        completed_chunks.add(chunk.chunk_id)
                        _save_progress(progress_path, completed_chunks)
                        logger.debug(
                            f"  [CHUNK] {chunk.chunk_id + 1}/{len(chunks)}: "
                            f"匹配 {m}/{len(chunk.units)} 条"
                        )
                    except Exception as e:
                        logger.error(f"  [CHUNK] {chunk.chunk_id} 失败: {e}")

        elapsed = time.time() - t0
        logger.info(f"[PIPELINE] 翻译完成: {total_matched} 条匹配, 耗时 {elapsed:.1f}s")

    # ── Stage 4: 回写 ──
    translated_units = [u for u in units if u.status == "translated"]
    if translated_units:
        logger.info(f"[PIPELINE] 回写 {len(translated_units)} 条翻译...")
        written = engine.write_back(game_dir, units, output_dir)
        logger.info(f"[PIPELINE] 成功写入 {written} 条")
    else:
        written = 0
        logger.info("[PIPELINE] 无翻译结果可回写")

    # ── Stage 5: 后处理 ──
    engine.post_process(game_dir, output_dir)

    # ── Stage 6: 报告 ──
    glossary.save(str(glossary_path))
    try:
        translation_db.save()
    except OSError as e:
        logger.warning(f"[PIPELINE] 保存 translation_db 失败: {e}")

    # Round 31 Tier C: opt-in runtime-hook emit (skipped unless --emit-runtime-hook)
    try:
        from core.runtime_hook_emitter import emit_if_requested

        emit_if_requested(args, output_dir, translation_db)
    except ImportError:
        pass

    translated_count = sum(1 for u in units if u.status == "translated")
    pending_count = sum(1 for u in units if u.status == "pending")
    report = {
        "engine": profile.display_name,
        "total": len(units),
        "translated": translated_count,
        "pending": pending_count,
        "translation_rate": round(translated_count / len(units), 4) if units else 0,
        "written": written,
        "api_usage": client.usage.to_dict() if hasattr(client, "usage") else {},
    }
    report_path = output_dir / "pipeline_report.json"
    try:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[PIPELINE] 报告: {report_path}")
    except OSError as e:
        logger.warning(f"[PIPELINE] 写入报告失败: {e}")

    logger.info(
        f"[PIPELINE] 完成: {translated_count}/{len(units)} 已翻译 "
        f"({report['translation_rate'] * 100:.1f}%), {written} 条写入"
    )
