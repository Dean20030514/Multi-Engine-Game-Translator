#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tl-mode file post-processing (round 24 A-H-4 split).

Carved out of ``translators/tl_parser.py``. Contains the two functions that
normalise tl files after AI translation but before they are handed to the
Ren'Py runtime:

    postprocess_tl_file       ← single file: remove ``nvl clear``, add ``pass`` to empties
    postprocess_tl_directory  ← directory-level aggregation

These fix Ren'Py 7.x/8.x compatibility issues that arise when AI occasionally
emits ``nvl clear`` inside translate blocks or leaves them empty after
filtering. Kept separate from the core parser because they operate on
already-translated output, not on source tl files.
"""
from __future__ import annotations


import logging

import re
from pathlib import Path
logger = logging.getLogger("multi_engine_translator")


# 与 tl_parser 共享的 translate 块头正则（单独定义避免循环依赖）。
_RE_TRANSLATE_BLOCK = re.compile(r'^translate\s+\w+\s+\w+\s*:\s*$')


def postprocess_tl_file(file_path: str) -> dict:
    """Post-process a tl file after fill_translation to fix Ren'Py compatibility issues.

    Fixes:
    1. Remove ``nvl clear`` from inside translate blocks (Ren'Py 7.x compat).
    2. Add ``pass`` to translate blocks left empty after removal.

    Returns dict with fix counts: {"nvl_removed": int, "pass_added": int}.
    """
    content = Path(file_path).read_text(encoding='utf-8-sig')
    lines = content.splitlines()
    has_trailing_nl = content.endswith('\n')

    new_lines: list[str] = []
    stats = {"nvl_removed": 0, "pass_added": 0}
    i = 0

    while i < len(lines):
        header = lines[i].strip()
        if _RE_TRANSLATE_BLOCK.match(header) and 'strings' not in header:
            new_lines.append(lines[i])
            i += 1

            block_lines: list[str] = []
            has_code = False
            while i < len(lines):
                s = lines[i].strip()
                if s == '' or s.startswith('#'):
                    block_lines.append(lines[i])
                    i += 1
                    continue
                if _RE_TRANSLATE_BLOCK.match(s) or s.startswith('translate '):
                    break
                if s == 'nvl clear':
                    stats["nvl_removed"] += 1
                    i += 1
                    continue
                has_code = True
                block_lines.append(lines[i])
                i += 1
            if not has_code:
                new_lines.append('    pass')
                stats["pass_added"] += 1
            new_lines.extend(block_lines)
        else:
            new_lines.append(lines[i])
            i += 1

    result = '\n'.join(new_lines)
    if has_trailing_nl:
        result += '\n'

    if stats["nvl_removed"] or stats["pass_added"]:
        Path(file_path).write_text(result, encoding='utf-8')

    return stats


def postprocess_tl_directory(tl_dir: str, lang: str) -> dict:
    """Post-process all tl files in a directory after translation.

    Returns aggregate stats.
    """
    tl_path = Path(tl_dir) / lang
    if not tl_path.exists():
        return {"files": 0, "nvl_removed": 0, "pass_added": 0}

    totals = {"files": 0, "nvl_removed": 0, "pass_added": 0}
    for rpy in sorted(tl_path.rglob("*.rpy")):
        stats = postprocess_tl_file(str(rpy))
        if stats["nvl_removed"] or stats["pass_added"]:
            totals["files"] += 1
            totals["nvl_removed"] += stats["nvl_removed"]
            totals["pass_added"] += stats["pass_added"]

    if totals["files"]:
        logger.info(f"[TL-POSTPROCESS] 修复 {totals['files']} 个文件: "
              f"移除 {totals['nvl_removed']} 处 nvl clear, "
              f"补 {totals['pass_added']} 处 pass")
    return totals
