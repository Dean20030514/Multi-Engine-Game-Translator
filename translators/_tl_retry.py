#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tl-mode retry stage: parallel re-translation of unmatched entries.

Round 53 W1: extracted from ``translators/tl_mode.py`` to keep the main
pipeline file under the 800-line cap while adding ThreadPoolExecutor
parallelism + per-chunk progress logging + adaptive chunk size.

The retry stage runs after the main stage completes. It rescans the tl/
directory for entries still without translations (either AI returned ID
drift, fallback chain miss, or chunk-level error) and re-translates them
in small chunks. Round 52 baseline was a sequential nested ``for fpath:
for chunk:`` loop with zero progress output — under conditions like
27000+ residual entries this looked indistinguishable from a hung process
to operators (HANDOFF.md r52 W1 evidence).

Round 53 W1 changes:
- ThreadPoolExecutor (max_workers = ``args.workers``)
- Per-chunk ``[TL-RETRY n/N]`` log with kept / dropped counts
- Adaptive chunk size (≤ 50 entries → 5 per chunk; > 50 → 10) for throughput
- Cross-file chunk task list (one slow file does not block other files)

Round 53 W3 layer 6: optional LLM ID-space drift detection. Compares the
ID set sent in each chunk prompt to the ID set actually returned by the
LLM; if the symmetric-difference ratio exceeds ``ID_DRIFT_THRESHOLD``,
emit a warning. Pure observation — never aborts the chunk.

Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from pathlib import Path
from typing import Callable

from core.api_client import APIClient
from core.prompts import build_tl_user_prompt
from core.translation_utils import (
    _build_fallback_dicts,
    _match_string_entry_fallback,
)
from file_processor import (
    check_response_item,
    protect_placeholders,
    _restore_placeholders_in_translations,
)
from translators._tl_dedup import build_tl_chunks

logger = logging.getLogger("multi_engine_translator")

# Round 53 W3 layer 6: drift threshold (10% symmetric-difference ratio).
ID_DRIFT_THRESHOLD: float = 0.10

# Adaptive chunk size cutoff (Round 53 W1).
_ADAPTIVE_LARGE_THRESHOLD: int = 50
_ADAPTIVE_LARGE_CHUNK: int = 10
_ADAPTIVE_SMALL_CHUNK: int = 5


def detect_id_drift(
    expected_ids: set[str],
    returned_ids: set[str],
    threshold: float = ID_DRIFT_THRESHOLD,
) -> tuple[bool, float, int, int]:
    """Layer 6 (Round 53 W3): LLM ID-space drift detection.

    Compares the set of IDs the prompt requested against the set the LLM
    actually returned. If the symmetric-difference ratio (relative to the
    expected size) exceeds ``threshold``, the LLM is hallucinating IDs or
    silently dropping requested IDs at a rate that the 5-layer fallback
    chain (precise → strip → token → escape → tagstripped) cannot fully
    recover from. The caller should log this; the chunk itself is still
    processed normally.

    Parameters
    ----------
    expected_ids : set[str]
        Identifiers extracted from chunk_entries before the API call.
    returned_ids : set[str]
        Identifiers present in the LLM response.
    threshold : float
        Drift ratio threshold (0.10 = warn when >10% of expected IDs are
        either missing or extraneous).

    Returns
    -------
    (drift_detected, drift_ratio, missing_count, extra_count)
        ``drift_detected`` is True when ``drift_ratio > threshold``;
        ``drift_ratio`` is ``(|missing| + |extra|) / |expected|``.
        Returns ``(False, 0.0, 0, 0)`` when ``expected_ids`` is empty.
    """
    if not expected_ids:
        return False, 0.0, 0, 0
    missing = expected_ids - returned_ids
    extra = returned_ids - expected_ids
    drift_count = len(missing) + len(extra)
    drift_ratio = drift_count / len(expected_ids)
    return drift_ratio > threshold, drift_ratio, len(missing), len(extra)


def _expected_id_set(chunk_entries: list) -> set[str]:
    """Collect the ID set the prompt expects the LLM to return.

    DialogueEntry uses ``identifier`` as ID; StringEntry uses ``old`` (the
    English source text) as the de-facto ID since it is the natural key
    in the LLM JSON response.
    """
    ids: set[str] = set()
    for e in chunk_entries:
        ident = getattr(e, "identifier", None) or getattr(e, "old", None)
        if ident:
            ids.add(ident)
    return ids


def _translate_one_retry_chunk(
    client: APIClient,
    system_prompt: str,
    fpath: str,
    ci: int,
    total: int,
    chunk_text: str,
    chunk_entries: list,
) -> tuple[str, int, int, dict[str, str], int, set[str], set[str]]:
    """Translate a single retry chunk.

    Returns
    -------
    (fpath, ci, total, kept_dict, dropped_count, expected_ids, returned_ids)
    """
    ptext, phmap = protect_placeholders(chunk_text)
    up = build_tl_user_prompt(ptext, len(chunk_entries))
    ts = client.translate(system_prompt, up)
    _restore_placeholders_in_translations(ts, phmap, extra_keys=("id",))

    expected_ids = _expected_id_set(chunk_entries)
    returned_ids: set[str] = set()
    kept: dict[str, str] = {}
    dropped = 0
    for t in ts:
        tid = t.get("id", "")
        if tid:
            returned_ids.add(tid)
        item_warnings = check_response_item(t)
        if item_warnings:
            dropped += 1
            continue
        if tid and t.get("zh"):
            kept[tid] = t["zh"]

    return fpath, ci, total, kept, dropped, expected_ids, returned_ids


def run_retry_stage(
    retry_all: list,
    client: APIClient,
    system_prompt: str,
    workers: int,
    game_dir: Path,
    fill_translation: Callable[[str, list], str],
    DialogueEntry: type,
    modified_rpy_files: set[str],
) -> tuple[int, int]:
    """Run the retry stage with ThreadPoolExecutor + per-chunk logging.

    Parameters
    ----------
    retry_all : list
        Mixed list of unmatched DialogueEntry / StringEntry objects.
    client : APIClient
        Pre-configured API client (shared across threads — APIClient is
        designed to be thread-safe for translate() calls).
    system_prompt : str
        Prebuilt system prompt for the LLM.
    workers : int
        Max concurrent threads (matches ``args.workers``).
    game_dir : Path
        Game root for computing relative paths in ``modified_rpy_files``.
    fill_translation : Callable
        ``translators.tl_parser.fill_translation`` (passed to break the
        circular import — _tl_retry.py is imported by tl_mode.py).
    DialogueEntry : type
        ``translators.tl_parser.DialogueEntry`` for isinstance checks.
    modified_rpy_files : set[str]
        Output set; relative paths of files that were re-written.

    Returns
    -------
    (translated_count, filled_count)
    """
    if not retry_all:
        return 0, 0

    # Group entries by file
    retry_by_file: dict[str, list] = {}
    for e in retry_all:
        retry_by_file.setdefault(e.tl_file, []).append(e)

    # Build a flat task list across all files (so one file's slow API call
    # cannot starve other files' progress)
    all_tasks: list[tuple[str, int, int, str, list]] = []
    for fpath, r_entries in retry_by_file.items():
        r_entries.sort(key=lambda e: e.tl_line)
        max_per_chunk = (
            _ADAPTIVE_LARGE_CHUNK
            if len(r_entries) > _ADAPTIVE_LARGE_THRESHOLD
            else _ADAPTIVE_SMALL_CHUNK
        )
        r_chunks = build_tl_chunks(r_entries, max_per_chunk=max_per_chunk)
        total = len(r_chunks)
        for ci, (chunk_text, chunk_entries) in enumerate(r_chunks, 1):
            all_tasks.append((fpath, ci, total, chunk_text, chunk_entries))

    total_chunks = len(all_tasks)
    if total_chunks == 0:
        return 0, 0

    logger.info(
        f"[TL-RETRY] {total_chunks} 个 retry chunk 待处理, "
        f"{workers} 线程并发, "
        f"自适应 chunk size (> {_ADAPTIVE_LARGE_THRESHOLD} 条 → "
        f"{_ADAPTIVE_LARGE_CHUNK}/chunk, ≤ → {_ADAPTIVE_SMALL_CHUNK}/chunk)"
    )

    # Per-file kept dict + per-chunk drift log
    file_kept: dict[str, dict[str, str]] = {}
    drift_warn_count = 0
    _lock = threading.Lock()
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _translate_one_retry_chunk,
                client,
                system_prompt,
                fpath,
                ci,
                total,
                ctext,
                centries,
            ): (fpath, ci, total)
            for fpath, ci, total, ctext, centries in all_tasks
        }
        for fut in concurrent.futures.as_completed(futures):
            fpath_meta, ci_meta, total_meta = futures[fut]
            try:
                fpath, ci, total, kept, dropped, expected_ids, returned_ids = fut.result()
            except Exception as e:
                with _lock:
                    completed += 1
                    n = completed
                logger.error(
                    f"  [TL-RETRY {n}/{total_chunks}] {Path(fpath_meta).name} "
                    f"chunk {ci_meta}/{total_meta}: ERROR {e}"
                )
                continue

            drifted, drift_ratio, n_missing, n_extra = detect_id_drift(
                expected_ids,
                returned_ids,
            )

            with _lock:
                file_kept.setdefault(fpath, {}).update(kept)
                completed += 1
                n = completed
                if drifted:
                    drift_warn_count += 1

            msg = (
                f"  [TL-RETRY {n}/{total_chunks}] {Path(fpath).name} "
                f"chunk {ci}/{total}: 保留 {len(kept)} 条"
            )
            if dropped:
                msg += f", 丢弃 {dropped} 条"
            if drifted:
                msg += f"  [W3-DRIFT {drift_ratio:.0%}] missing={n_missing} extra={n_extra}"
            logger.info(msg)

    if drift_warn_count > 0:
        logger.warning(
            f"[TL-RETRY] {drift_warn_count}/{total_chunks} chunk 触发 W3 ID drift "
            f"(>{int(ID_DRIFT_THRESHOLD * 100)}% 漂移) — 提示 LLM 在 retry 路径上"
            f"出现异常 ID 集；fallback 链已尽力恢复"
        )

    # Per-file 5-layer fallback match + write back
    total_translated = 0
    total_filled = 0

    for fpath, r_entries in retry_by_file.items():
        r_kept = file_kept.get(fpath, {})
        if not r_kept:
            continue

        # Round 31 Tier A-3: 4-dict build + L5 tag-stripped fallback
        r_stripped, r_clean, r_norm, r_tagstripped = _build_fallback_dicts(r_kept)
        r_matched: list = []
        for entry in r_entries:
            if isinstance(entry, DialogueEntry):
                zh = r_kept.get(entry.identifier)
                if zh:
                    entry.translation = zh
                    r_matched.append(entry)
                    total_translated += 1
            else:  # StringEntry
                zh, _fb_level = _match_string_entry_fallback(
                    entry.old,
                    r_kept,
                    r_stripped,
                    r_clean,
                    r_norm,
                    r_tagstripped,
                )
                if zh:
                    entry.new = zh
                    r_matched.append(entry)
                    total_translated += 1

        if r_matched:
            modified = fill_translation(fpath, r_matched)
            Path(fpath).write_text(modified, encoding="utf-8")
            total_filled += len(r_matched)
            try:
                modified_rpy_files.add(str(Path(fpath).relative_to(game_dir)))
            except ValueError:
                pass  # absolute path — skip the relative-tracking optimisation
            logger.debug(f"  [TL-RETRY] 回填 {len(r_matched)} 条到 {Path(fpath).name}")

    return total_translated, total_filled
