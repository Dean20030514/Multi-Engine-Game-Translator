#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tl-mode cross-file deduplication + chunk assembly (round 24 A-H-4 split).

Carved out of ``translators/tl_mode.py``. Contains the four functions that
turn a flat list of ``DialogueEntry`` / ``StringEntry`` into AI-ready chunks
while avoiding duplicate translations of identical long sentences:

    DedupResult              ← dataclass for dedup output
    dedup_tl_entries         ← group by (speaker, text); short lines opt out
    apply_dedup_translations ← copy a group's translation to its duplicates
    build_tl_chunks          ← pack entries into chunk text/entry pairs

These are used in a three-step pipeline inside ``run_tl_pipeline``:
``dedup_tl_entries`` → ``build_tl_chunks`` → AI translate → ``apply_dedup_translations``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# 源文本长度阈值：仅对 ≥ 此长度的完整句子去重。
# 短语气词（"Hmm...", "...", "Huh?"）必须逐条翻译以保留上下文差异。
DEDUP_MIN_LENGTH = 40


@dataclass
class DedupResult:
    """去重结果"""

    unique_entries: list  # 需要发给 API 翻译的条目（去重后）
    dedup_groups: dict  # {(char, text) → (first_entry, [dup_entries])}
    skipped_count: int  # 被跳过（将复用翻译）的条目数
    total_before: int  # 去重前总数


def dedup_tl_entries(
    all_entries: list,
    min_length: int = DEDUP_MIN_LENGTH,
) -> DedupResult:
    """跨文件去重：相同 (speaker, original_text) 只翻译一次。

    仅对源文本长度 ≥ min_length 的条目去重。短句/语气词保留全部，
    因为 LLM 会根据上下文给出不同译法。

    Args:
        all_entries: DialogueEntry + StringEntry 混合列表。
        min_length: 源文本最小字符数。

    Returns:
        DedupResult，其中 unique_entries 为去重后需翻译的条目。
    """
    from translators.tl_parser import DialogueEntry, StringEntry

    unique: list = []
    # (char, text) → (first_entry, [dup_entries])
    groups: dict[tuple[str, str], tuple[object, list]] = {}
    skipped = 0

    for entry in all_entries:
        if isinstance(entry, DialogueEntry):
            char = entry.character or ""
            text = entry.original
        elif isinstance(entry, StringEntry):
            char = ""
            text = entry.old
        else:
            unique.append(entry)
            continue

        # 短文本不去重
        if len(text) < min_length:
            unique.append(entry)
            continue

        key = (char, text)
        if key not in groups:
            groups[key] = (entry, [])
            unique.append(entry)
        else:
            groups[key][1].append(entry)
            skipped += 1

    # 只保留有实际重复的 group
    dedup_groups = {k: v for k, v in groups.items() if v[1]}

    return DedupResult(
        unique_entries=unique,
        dedup_groups=dedup_groups,
        skipped_count=skipped,
        total_before=len(all_entries),
    )


def apply_dedup_translations(
    dedup_result: DedupResult,
    file_translations: dict[str, dict[str, str]],
    game_dir: Path,
) -> tuple[int, list[dict]]:
    """将已翻译条目的翻译复用到去重组中的其他条目。

    对于 dedup_groups 中的每个 (first_entry, [dup_entries])，查找
    first_entry 的翻译结果，然后注入到每个 dup_entry 所属文件的
    file_translations 中。后续回填循环会自动处理。

    Args:
        dedup_result: dedup_tl_entries 返回的去重结果。
        file_translations: {rel_path → {identifier_or_old: translation}}。
        game_dir: 游戏目录，用于计算相对路径。

    Returns:
        (filled_count, dedup_log) — dedup_log 记录复用来源，便于调试。
    """
    from translators.tl_parser import DialogueEntry, StringEntry

    filled = 0
    dedup_log: list[dict] = []

    # 构建 identifier/old → translation 的全局索引
    all_trans: dict[str, str] = {}
    for _rel, td in file_translations.items():
        all_trans.update(td)

    for (_char, text), (first_entry, dup_entries) in dedup_result.dedup_groups.items():
        if not dup_entries:
            continue

        # 查找 first_entry 的翻译
        translation = None
        source_file = ""
        source_line = 0

        if isinstance(first_entry, DialogueEntry):
            translation = all_trans.get(first_entry.identifier)
            source_file = first_entry.tl_file
            source_line = first_entry.tl_line
        elif isinstance(first_entry, StringEntry):
            translation = all_trans.get(first_entry.old)
            source_file = first_entry.tl_file
            source_line = first_entry.tl_line

        if not translation:
            continue

        # 将翻译注入到每个 dup_entry 所属文件的 file_translations
        for entry in dup_entries:
            try:
                rel_path = str(Path(entry.tl_file).relative_to(game_dir))
            except ValueError:
                rel_path = entry.tl_file

            if isinstance(entry, DialogueEntry):
                file_translations.setdefault(rel_path, {})[entry.identifier] = translation
            else:
                file_translations.setdefault(rel_path, {})[entry.old] = translation

            filled += 1
            dedup_log.append(
                {
                    "source_text": text[:80],
                    "translation": translation[:80],
                    "source_file": source_file,
                    "source_line": source_line,
                    "target_file": entry.tl_file,
                    "target_line": entry.tl_line,
                }
            )

    return filled, dedup_log


def build_tl_chunks(
    entries: list,
    max_per_chunk: int = 30,
) -> list[tuple[str, list]]:
    """将 DialogueEntry / StringEntry 列表打包为 AI 翻译 chunk。

    Returns:
        [(chunk_text, chunk_entries), ...] — chunk_text 为发给 AI 的文本,
        chunk_entries 为该 chunk 对应的条目列表（回填时使用）。
    """
    from translators.tl_parser import DialogueEntry

    chunks: list[tuple[str, list]] = []
    for start in range(0, len(entries), max_per_chunk):
        group = entries[start : start + max_per_chunk]
        lines: list[str] = []
        for entry in group:
            if isinstance(entry, DialogueEntry):
                char_part = f" [Char: {entry.character}]" if entry.character else " [Char: ]"
                text = entry.original
                multiline = " [MULTILINE]" if "\n" in text or "\\n" in text else ""
                lines.append(f"[ID: {entry.identifier}]{char_part}{multiline}")
                lines.append(f'"{text}"')
            else:
                text = entry.old
                multiline = " [MULTILINE]" if "\n" in text or "\\n" in text else ""
                lines.append(f"[STRING]{multiline}")
                lines.append(f'"{text}"')
            lines.append("")
        chunks.append(("\n".join(lines), group))
    return chunks
