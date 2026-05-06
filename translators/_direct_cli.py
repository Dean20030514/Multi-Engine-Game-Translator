#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Direct-mode dry-run preview helpers (round 23 A-H-4 split).

Carved out of ``translators/direct.py`` to keep the entry module under the
800-line ceiling. These functions are only consulted by ``run_pipeline`` in
its ``--dry-run --verbose`` branch; they do no API calls and have no side
effects beyond logging.
"""

from __future__ import annotations

import logging
from pathlib import Path

from file_processor import read_file

logger = logging.getLogger("multi_engine_translator")


def _compute_file_dialogue_stats(filepath: Path) -> tuple[int, float]:
    """Return ``(dialogue_line_count, density)`` for a single .rpy file.

    Used to pre-classify each file as "dense enough for full-file translation"
    vs "better served by targeted line-level translation" during dry-run.
    """
    # Imported lazily to sidestep any circular-import risk — ``renpy_text_utils``
    # and ``retranslator`` live in the same package.
    from translators.retranslator import calculate_dialogue_density
    from translators.renpy_text_utils import _is_user_visible_string_line

    content = read_file(filepath)
    density = calculate_dialogue_density(content)
    dlg_count = sum(1 for line in content.splitlines() if _is_user_visible_string_line(line))
    return dlg_count, density


def _print_density_histogram(densities: list[float]) -> None:
    """Render a 5-bucket text histogram of per-file dialogue densities."""
    if not densities:
        return
    buckets = [0] * 5  # [0-20%, 20-40%, 40-60%, 60-80%, 80-100%]
    labels = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]
    for d in densities:
        idx = min(int(d * 5), 4)
        buckets[idx] += 1
    max_count = max(buckets) if buckets else 1
    logger.info("\n对话密度分布:")
    for label, count in zip(labels, buckets):
        bar_len = count * 30 // max_count if max_count else 0
        bar = "#" * bar_len
        logger.info(f"  {label:>8s} | {bar:<30s} {count}")


def _print_term_scan_preview(glossary) -> None:
    """Show a short summary of glossary extraction results before translation."""
    n_chars = len(getattr(glossary, "characters", {}))
    n_terms = len(getattr(glossary, "terms", {}))
    n_locked = len(getattr(glossary, "locked_terms", []))
    n_notrans = len(getattr(glossary, "no_translate", []))
    logger.info("\n术语扫描预览:")
    logger.info(f"  角色名: {n_chars} 个")
    logger.info(f"  术语表: {n_terms} 条" + (f"（其中锁定 {n_locked} 条）" if n_locked else ""))
    if n_notrans:
        logger.info(f"  禁翻片段: {n_notrans} 条")
