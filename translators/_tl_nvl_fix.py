#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tl-mode NVL translation-ID repair (round 24 A-H-4 split).

Carved out of ``translators/tl_parser.py``. Implements the niche but crucial
Ren'Py 8.6+ → 7.x compatibility shim: when 8.6 generates ``.tl`` templates
it defaults to ``config.tlid_only_considers_say = True`` and computes block
IDs from the Say statement only; 7.x included the preceding ``nvl clear``
in the hash, so 8.6-generated IDs are wrong when running on 7.x.

    _compute_say_only_hash    ← 8.6+ style hash (Say only)
    _compute_nvl_say_hash     ← 7.x style hash (nvl clear + Say)
    fix_nvl_translation_ids   ← single-file repair
    fix_nvl_ids_directory     ← directory-level aggregation

All four functions are independent of the main parser flow — they run as a
post-translation repair pass.
"""

from __future__ import annotations


import logging

import hashlib
import re
from pathlib import Path

logger = logging.getLogger("multi_engine_translator")


# 独立定义（避免从 tl_parser 循环导入）
_RE_DIALOGUE_HEADER = re.compile(r"^translate\s+\w+\s+(\w+)\s*:\s*$")
_RE_TRANSLATE_BLOCK = re.compile(r"^translate\s+\w+\s+\w+\s*:\s*$")


def _compute_say_only_hash(say_code: str) -> str:
    """计算仅含 Say 语句的翻译块哈希（8 位十六进制）。"""
    md5 = hashlib.md5()
    md5.update(say_code.encode("utf-8") + b"\r\n")
    return md5.hexdigest()[:8]


def _compute_nvl_say_hash(say_code: str) -> str:
    """计算含 nvl clear + Say 的翻译块哈希（8 位十六进制）。"""
    md5 = hashlib.md5()
    md5.update(b"nvl clear\r\n")
    md5.update(say_code.encode("utf-8") + b"\r\n")
    return md5.hexdigest()[:8]


def fix_nvl_translation_ids(file_path: str) -> dict:
    """修正 .tl 文件中含 nvl clear 的翻译块 ID。

    Ren'Py 8.6+ 生成 .tl 模板时默认只用 Say 语句计算哈希
    (``config.tlid_only_considers_say = True``)，但 Ren'Py 7.x 会把
    ``nvl clear`` 也纳入哈希。本函数检测 say-only ID 并替换为 nvl+say ID。

    算法：
    1. 扫描 ``translate <lang> <id>:`` 块，检测注释中是否有 ``# nvl clear``
    2. 提取紧随其后的 say 注释行（如 ``# s "text"``）作为 say_code
    3. 用 say_code 计算 say-only 哈希，与当前 ID 后缀比对（防止误改）
    4. 计算 nvl+say 哈希，替换 ID

    Returns dict: ``{"ids_fixed": int}``
    """
    content = Path(file_path).read_text(encoding="utf-8-sig")
    lines = content.splitlines()
    has_trailing_nl = content.endswith("\n")

    stats = {"ids_fixed": 0}
    i = 0

    while i < len(lines):
        m = _RE_DIALOGUE_HEADER.match(lines[i].strip())
        if not m or "strings" in lines[i]:
            i += 1
            continue

        header_idx = i
        identifier = m.group(1)
        i += 1

        # 收集块内注释
        has_nvl_clear = False
        say_code = None

        while i < len(lines):
            s = lines[i].strip()
            if s == "" or s.startswith("#"):
                if s == "# nvl clear":
                    has_nvl_clear = True
                elif has_nvl_clear and say_code is None and s.startswith("# "):
                    # nvl clear 后的第一条非 nvl-clear 注释 = say 语句
                    candidate = s[2:]  # 去掉 "# "
                    if candidate and candidate[0].isalpha() and '"' in candidate:
                        say_code = candidate
                i += 1
                continue
            # 遇到非空非注释行（代码行或下一个块），结束收集
            if _RE_TRANSLATE_BLOCK.match(s) or s.startswith("translate "):
                break
            i += 1

        if not has_nvl_clear or say_code is None:
            continue

        # 提取当前 ID 的哈希后缀（label_XXXXXXXX 中的 XXXXXXXX）
        underscore_pos = identifier.rfind("_")
        if underscore_pos == -1:
            continue
        current_hash = identifier[underscore_pos + 1 :]
        label_prefix = identifier[: underscore_pos + 1]

        # 验证当前 ID 确实是 say-only 哈希
        expected_say_only = _compute_say_only_hash(say_code)
        if current_hash != expected_say_only:
            continue

        # 计算 nvl+say 哈希
        new_hash = _compute_nvl_say_hash(say_code)
        if new_hash == current_hash:
            continue

        new_identifier = label_prefix + new_hash
        old_line = lines[header_idx]
        lines[header_idx] = old_line.replace(identifier, new_identifier, 1)
        stats["ids_fixed"] += 1

    if stats["ids_fixed"]:
        result = "\n".join(lines)
        if has_trailing_nl:
            result += "\n"
        Path(file_path).write_text(result, encoding="utf-8")

    return stats


def fix_nvl_ids_directory(tl_dir: str, lang: str) -> dict:
    """批量修正目录下所有 .tl 文件的 nvl clear 翻译块 ID。

    Returns aggregate stats: ``{"files": int, "ids_fixed": int}``
    """
    tl_path = Path(tl_dir) / lang
    if not tl_path.exists():
        return {"files": 0, "ids_fixed": 0}

    totals = {"files": 0, "ids_fixed": 0}
    for rpy in sorted(tl_path.rglob("*.rpy")):
        stats = fix_nvl_translation_ids(str(rpy))
        if stats["ids_fixed"]:
            totals["files"] += 1
            totals["ids_fixed"] += stats["ids_fixed"]

    if totals["files"]:
        logger.info(
            f"[TL-NVL-ID-FIX] 修正 {totals['files']} 个文件中 "
            f"{totals['ids_fixed']} 处 nvl clear 翻译块 ID"
        )
    return totals
