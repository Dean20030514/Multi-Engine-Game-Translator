#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Direct-mode chunk-level translation primitives (round 23 A-H-4 split).

Carved out of ``translators/direct.py`` to keep the entry module under the
800-line ceiling. Contains the four tightly-coupled functions that implement
"send one chunk to the LLM, decide if we need to retry, split if truncated":

    _translate_chunk          ← single-pass chunk translation (no retry)
    _should_retry             ← classifier: do we retry? split on retry?
    _split_chunk              ← two-way binary split with label/blank-line boundary
    _translate_chunk_with_retry  ← orchestrator used by ``translate_file``

These stay together because ``_translate_chunk_with_retry`` calls all three
of the others in a single control flow. Splitting further would scatter the
state machine across files without benefit.
"""

from __future__ import annotations

import logging

from file_processor import (
    protect_placeholders,
    protect_locked_terms,
    check_response_chunk,
    estimate_tokens,
    _count_translatable_lines_in_chunk,
    _find_block_boundaries,
)
from core.prompts import build_user_prompt
from core.translation_utils import (
    ChunkResult,
    TranslationContext,
    CHECKER_DROP_RATIO_THRESHOLD,
    MIN_DROPPED_FOR_WARNING,
)
from file_processor import (
    _restore_placeholders_in_translations,
    _restore_locked_terms_in_translations,
    _filter_checked_translations,
)

logger = logging.getLogger("multi_engine_translator")


def _translate_chunk(ctx: TranslationContext, chunk: dict) -> ChunkResult:
    """翻译单个 chunk，返回 ChunkResult。

    原为 translate_file() 内的嵌套函数，通过闭包捕获 client/system_prompt/rel_path。
    重构后通过 TranslationContext 显式传参。
    """
    part = chunk["part"]
    chunk_info = {
        "part": part,
        "total": chunk["total"],
        "line_offset": chunk["line_offset"],
    }
    expected_count = _count_translatable_lines_in_chunk(chunk["content"])
    # 占位符保护
    protected_content, ph_mapping = protect_placeholders(chunk["content"])
    # 锁定术语预替换（在占位符保护之后，避免干扰 Ren'Py 语法占位符）
    lt_mapping: list[tuple[str, str]] = []
    if ctx.locked_terms_map:
        protected_content, lt_mapping = protect_locked_terms(
            protected_content, ctx.locked_terms_map
        )
    user_prompt = build_user_prompt(ctx.rel_path, protected_content, chunk_info)
    logger.debug(
        f"    [API ] 块 {part}/{chunk['total']}  ({estimate_tokens(chunk['content']):,} tokens)"
    )
    try:
        translations = ctx.client.translate(ctx.system_prompt, user_prompt)
    except Exception as e:
        return ChunkResult(part=part, error=f"块 {part} API 调用失败: {e}", expected=expected_count)
    # 锁定术语还原（先于占位符还原，避免令牌冲突）
    if lt_mapping:
        _restore_locked_terms_in_translations(translations, lt_mapping)
    # 占位符还原
    _restore_placeholders_in_translations(translations, ph_mapping)
    # Chunk 级检查（条数一致）
    chunk_warnings = check_response_chunk(protected_content, translations)
    for w in chunk_warnings:
        logger.debug(f"    [CHECK] {w}")
    # 逐条检查
    kept, dropped_count, dropped_items, check_warns = _filter_checked_translations(translations)
    for w in check_warns:
        logger.debug(f"    {w}")
    if not translations:
        logger.debug(f"    [INFO] 块 {part}: 无需翻译的内容")
    else:
        logger.debug(
            f"    [OK  ] 块 {part}: 获得 {len(translations)} 条翻译"
            + (f", 丢弃 {dropped_count} 条" if dropped_count else "")
        )
    return ChunkResult(
        part=part,
        kept=kept,
        chunk_warnings=chunk_warnings + check_warns,
        dropped_count=dropped_count,
        expected=expected_count,
        returned=len(translations),
        dropped_items=dropped_items,
    )


def _should_retry(cr: ChunkResult) -> tuple[bool, bool]:
    """判断 chunk 是否需要重试。

    Returns: (should_retry, needs_split)
        needs_split=True 表示应拆分后重试而非原样重试（疑似输出截断）。
    """
    if cr.error:
        return True, False
    if (
        cr.returned > 0
        and cr.dropped_count >= MIN_DROPPED_FOR_WARNING
        and cr.dropped_count / cr.returned > CHECKER_DROP_RATIO_THRESHOLD
    ):
        return True, False
    # 截断检测：返回条数 < 期望的 50%，强烈暗示 AI 输出被截断
    if cr.expected > 0 and cr.returned < cr.expected * 0.5:
        return True, True
    # JSON 解析全部失败：返回 0 条且期望 > 0，可能是 AI 输出过大或格式混乱，拆分后重试
    if cr.expected > 0 and cr.returned == 0 and not cr.error:
        return True, True
    return False, False


def _split_chunk(chunk: dict) -> tuple[dict, dict]:
    """将 chunk 二分为两个子 chunk。

    拆分点优先级：label/screen 边界 > 空行 > 直接二等分。
    只做一层拆分（不递归），避免复杂度爆炸。
    """
    lines = chunk["content"].splitlines(keepends=True)
    total_lines = len(lines)
    if total_lines < 2:
        # 无法拆分，返回原 chunk 和空 chunk
        empty = {
            "content": "",
            "line_offset": chunk["line_offset"] + total_lines,
            "part": chunk["part"],
            "total": chunk["total"],
        }
        return chunk, empty

    mid = total_lines // 2
    search_start = max(1, mid - total_lines // 4)
    search_end = min(total_lines - 1, mid + total_lines // 4)
    best_split = mid  # fallback: 直接二等分

    # 优先级 1：label/screen/init 边界
    boundaries = _find_block_boundaries(lines)
    found_boundary = False
    for b in boundaries:
        if search_start <= b <= search_end:
            best_split = b
            found_boundary = True
            break

    if not found_boundary:
        # 优先级 2：空行（从中间向外搜索）
        for i in range(mid, search_end):
            if not lines[i].strip():
                best_split = i + 1
                break
        else:
            for i in range(mid - 1, search_start - 1, -1):
                if not lines[i].strip():
                    best_split = i + 1
                    break

    content_a = "".join(lines[:best_split])
    content_b = "".join(lines[best_split:])
    base_offset = chunk["line_offset"]

    chunk_a = {
        "content": content_a,
        "line_offset": base_offset,
        "part": chunk["part"],
        "total": chunk["total"],
    }
    if "prev_context" in chunk:
        chunk_a["prev_context"] = chunk["prev_context"]

    chunk_b = {
        "content": content_b,
        "line_offset": base_offset + best_split,
        "part": chunk["part"],
        "total": chunk["total"],
    }
    # chunk_b 的上下文 = chunk_a 末尾 5 行
    context_lines = lines[max(0, best_split - 5) : best_split]
    chunk_b["prev_context"] = "".join(context_lines)

    return chunk_a, chunk_b


def _translate_chunk_with_retry(
    ctx: TranslationContext, chunk: dict, max_retries: int = 1
) -> ChunkResult:
    """带自动重试的 chunk 翻译。截断时自动拆分重试。"""
    cr = _translate_chunk(ctx, chunk)
    for attempt in range(max_retries):
        should, needs_split = _should_retry(cr)
        if not should:
            break

        if needs_split:
            # 截断：拆分 chunk 后分别翻译，合并结果
            logger.debug(
                f"    [SPLIT] 块 {chunk['part']}: 返回 {cr.returned}/{cr.expected}，"
                f"疑似截断，拆分重试"
            )
            chunk_a, chunk_b = _split_chunk(chunk)
            cr_a = _translate_chunk(ctx, chunk_a)
            cr_b = (
                _translate_chunk(ctx, chunk_b)
                if chunk_b["content"]
                else ChunkResult(part=chunk["part"])
            )
            cr = ChunkResult(
                part=chunk["part"],
                kept=cr_a.kept + cr_b.kept,
                chunk_warnings=cr_a.chunk_warnings + cr_b.chunk_warnings,
                dropped_count=cr_a.dropped_count + cr_b.dropped_count,
                expected=cr_a.expected + cr_b.expected,
                returned=cr_a.returned + cr_b.returned,
                dropped_items=cr_a.dropped_items + cr_b.dropped_items,
            )
            break  # 拆分只做一层
        else:
            reason = cr.error or f"丢弃率过高 ({cr.dropped_count}/{cr.returned})"
            logger.debug(f"    [RETRY] 块 {chunk['part']}: {reason}，第 {attempt + 1} 次重试")
            cr = _translate_chunk(ctx, chunk)
    return cr
