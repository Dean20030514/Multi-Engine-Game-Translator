#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Font patch — copy font into output game dir and set gui.*_font in gui.rpy."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)


# Only .ttf and .otf are accepted; no hardcoded font names.
FONT_EXTENSIONS = (".ttf", ".otf")

# Round 37 M2: reject font_config JSON files above 50 MB to bound memory
# usage when the caller supplies an attacker-crafted or accidentally
# huge file.  Legitimate font_config.json is typically a few hundred
# bytes of gui_overrides / config_overrides — 50 MB is several orders
# of magnitude headroom.
_MAX_FONT_CONFIG_SIZE = 50 * 1024 * 1024


def default_resources_fonts_dir() -> Path:
    """Return canonical absolute path to ``resources/fonts/`` at project root.

    ``core/font_patch.py`` lives one level below the project root, so
    ``__file__.resolve().parent.parent`` climbs out of ``core/`` and into the
    project root, where ``resources/fonts/`` is checked in.  Round 29 fixed the
    same-class bug in ``tools/patch_font_now.py``; round 32 extracts this
    helper so all four callers share one canonical resolution path and cannot
    drift again.
    """
    return Path(__file__).resolve().parent.parent / "resources" / "fonts"


def resolve_font(
    resources_fonts_dir: Path,
    explicit_file: Optional[str] = None,
) -> Optional[Path]:
    """Resolve font file: use --font-file if given, else first .ttf/.otf in resources/fonts/.

    Returns Path to font file, or None on failure (warnings printed).
    """
    if explicit_file:
        path = Path(explicit_file).resolve()
        if not path.exists():
            logger.warning("--font-file 指向的文件不存在，跳过字体补丁: " + str(path))
            return None
        if path.suffix.lower() not in FONT_EXTENSIONS:
            logger.warning("--font-file 须为 .ttf 或 .otf，跳过字体补丁: " + str(path))
            return None
        return path

    if not resources_fonts_dir.exists():
        logger.warning("resources/fonts/ 不存在，跳过字体补丁")
        return None
    candidates: list[Path] = []
    # 优先选择 .ttf 再考虑 .otf，以兼容旧版 Ren'Py
    for ext in (".ttf", ".otf"):
        candidates.extend(resources_fonts_dir.glob("*" + ext))
    # .ttf 排前面（0），.otf 排后面（1），同扩展名内按文件名排序
    _ext_order = {".ttf": 0, ".otf": 1}
    candidates.sort(key=lambda p: (_ext_order.get(p.suffix.lower(), 9), p.name))
    if not candidates:
        logger.warning("resources/fonts/ 下未找到 .ttf 或 .otf 文件，跳过字体补丁")
        return None
    return candidates[0]


def load_font_config(config_path: "Path | None") -> dict:
    """加载字体配置文件（font_config.json）。

    返回配置字典，至少包含 gui_overrides。不存在或加载失败时返回空字典。

    配置示例::

        {
            "font_file": "path/to/font.ttf",
            "gui_overrides": {
                "gui.text_size": 22,
                "gui.name_text_size": 24,
                "gui.interface_text_size": 20
            }
        }
    """
    import json as _json
    if not config_path:
        return {}
    config_path = Path(config_path)
    if not config_path.is_file():
        logger.warning(f"font_config 文件不存在: {config_path}")
        return {}
    # Round 37 M2: bound memory before the full read.  A 51 MB font_config
    # is almost certainly malformed / malicious; reject early so an unwary
    # operator (or an untrusted artefact generator) cannot blow up the
    # process heap before JSON parsing even starts.
    try:
        file_size = config_path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > _MAX_FONT_CONFIG_SIZE:
        logger.warning(
            f"font_config 文件过大（{file_size} 字节 > "
            f"{_MAX_FONT_CONFIG_SIZE} 字节上限），跳过: {config_path}"
        )
        return {}
    try:
        # Round 49 Step 2: TOCTOU defense via safety.file_safety.check_fstat_size.
        # The path.stat() pre-check above is the fast path; this re-checks the
        # size on the actual open fd to defeat the attacker-grow-between-stat-
        # and-open race window.  Mirrors the pattern in engines/csv_engine.py.
        with open(config_path, encoding="utf-8") as f:
            ok, fsize2 = check_fstat_size(f, _MAX_FONT_CONFIG_SIZE)
            if not ok:
                logger.warning(
                    f"font_config 文件 stat 后增长到 {fsize2} 字节"
                    f"（疑似 TOCTOU 攻击），超过 {_MAX_FONT_CONFIG_SIZE} 字节上限，"
                    f"跳过: {config_path}"
                )
                return {}
            return _json.loads(f.read())
    except (OSError, _json.JSONDecodeError, ValueError) as e:
        logger.warning(f"font_config 加载失败: {e}")
        return {}


def apply_font_patch(
    output_game_dir: Path,
    source_game_dir: Path,
    font_path: Path,
    font_config_path: "Path | None" = None,
) -> None:
    """Copy font into output_game_dir and patch gui.*_font in gui.rpy.

    Only replaces define gui.XXX_font = "..." lines; other content unchanged.
    If gui.rpy is missing in output, copy from source_game_dir first.
    If font_config_path provided, also patches gui size/layout variables.
    """
    output_game_dir = output_game_dir.resolve()
    source_game_dir = source_game_dir.resolve()
    font_path = font_path.resolve()
    font_basename = font_path.name

    # Copy font
    output_game_dir.mkdir(parents=True, exist_ok=True)
    dst_font = output_game_dir / font_basename
    shutil.copy2(font_path, dst_font)
    logger.info(f"已复制字体: {font_basename} -> {output_game_dir}")

    gui_rpy = output_game_dir / "gui.rpy"
    if not gui_rpy.exists():
        source_gui = source_game_dir / "gui.rpy"
        if not source_gui.exists():
            logger.warning("输出目录与源目录均无 gui.rpy，无法写入字体变量")
            return
        shutil.copy2(source_gui, gui_rpy)
        logger.info("已从源目录复制 gui.rpy 至输出目录")

    # Replace only define gui.XXX_font = "..." (any quote, value unchanged except replaced with font_basename)
    pattern = re.compile(
        r'^(\s*define\s+gui\.\w+_font\s*=\s*)["\']([^"\']*)["\'](\s*)$',
        re.MULTILINE,
    )
    text = gui_rpy.read_text(encoding="utf-8")
    new_text, count = pattern.subn(
        lambda m: m.group(1) + '"' + font_basename + '"' + m.group(3),
        text,
    )
    if count == 0:
        logger.warning("gui.rpy 中未找到 gui.*_font 变量定义，未修改任何内容")
    else:
        logger.info(f"已更新 gui.rpy 中 {count} 处 gui.*_font 为 {font_basename}")

    # 可选：应用 font_config.json 中的 gui_overrides（字号/布局参数）
    config = load_font_config(font_config_path)
    overrides = config.get("gui_overrides", {})
    if overrides and new_text:
        size_count = 0
        for var_name, value in overrides.items():
            # 匹配 define gui.xxx = N 或 define gui.xxx = N.N
            var_pattern = re.compile(
                rf'^(\s*define\s+{re.escape(var_name)}\s*=\s*)[\d.]+(\s*)$',
                re.MULTILINE,
            )
            new_text, n = var_pattern.subn(rf'\g<1>{value}\2', new_text)
            size_count += n
        if size_count:
            logger.info(f"已更新 gui.rpy 中 {size_count} 处 gui 参数（font_config）")

    gui_rpy.write_text(new_text, encoding="utf-8")
