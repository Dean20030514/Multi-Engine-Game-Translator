#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tl-mode game patches (round 24 A-H-4 split).

Carved out of ``translators/tl_mode.py``. Contains the three pre-translation
game-dir mutations invoked by ``run_tl_pipeline`` before it starts scanning
the tl/ directory:

    _clean_rpyc              ← purge .rpyc / .rpymc / .rpyb caches
    _apply_tl_game_patches   ← font patch + language switch setup (top-level)
    _inject_language_buttons ← inject Language radio into screen preferences()

Plus the shared snippet template ``_LANG_BUTTON_SNIPPET``.

Kept together because all three mutate the game directory (copy fonts, write
none_overlay.rpy, edit gui.rpy, inject language buttons) and are typically
called as a unit by ``_apply_tl_game_patches``.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from core.font_patch import resolve_font, default_resources_fonts_dir

logger = logging.getLogger("multi_engine_translator")

# Language switch button snippet injected into screen preferences()
_LANG_BUTTON_SNIPPET = """
                vbox:
                    style_prefix "radio"
                    label _("Language")
                    textbutton "English" action Language(None)
                    textbutton "中文" action Language("{lang}")
"""


def _clean_rpyc(game_dir: Path, modified_files: "set[str] | None" = None) -> None:
    """Delete Ren'Py cache files to force recompilation.

    Cleans: .rpyc (compiled scripts), .rpymc (compiled modules),
    .rpyb (bytecode cache in game/cache/).

    Args:
        game_dir: Game root directory.
        modified_files: If provided, only delete .rpyc for these .rpy relative paths.
            Otherwise fall back to full recursive cleanup.
    """
    count = 0
    if modified_files:
        for rpy_rel in modified_files:
            for suffix in (".rpyc", ".rpymc"):
                cache = game_dir / (rpy_rel + suffix[4:])  # .rpy → .rpyc / .rpymc
                if cache.is_file():
                    cache.unlink()
                    count += 1
        # .rpyb 位于 game/cache/，无法按文件名精确对应，做全量清理
        for f in game_dir.rglob("*.rpyb"):
            if f.is_file():
                f.unlink()
                count += 1
    else:
        for ext in ("*.rpyc", "*.rpymc", "*.rpyb"):
            for f in game_dir.rglob(ext):
                if f.is_file():
                    f.unlink()
                    count += 1
    if count:
        logger.info(f"[RPYC] 已清理 {count} 个缓存文件")


def _apply_tl_game_patches(
    game_dir: Path, tl_lang: str, font_config_path: "Path | None" = None
) -> None:
    """Apply font patch and language switch to game directory for tl-mode.

    1. Copy Chinese font from resources/fonts/ into game dir.
    2. Generate tl/<lang>/none_overlay.rpy with font overrides (不直接修改 gui.rpy).
    3. Write chinese_language_patch.rpy with config.language setting.
    4. Inject Language radio buttons into all screen preferences() definitions.

    使用 translate None python: 覆盖模板，避免直接修改 gui.rpy。
    游戏更新 gui.rpy 不会丢失字体补丁。
    """
    from core.font_patch import load_font_config

    # Round 32: migrated from ``Path(__file__).parent / "resources" / "fonts"``
    # which was missing one ``.parent`` (translators/ is one level below root)
    # and silently returned None for the fonts dir on source-code runs.
    resources_fonts = default_resources_fonts_dir()
    font_path = resolve_font(resources_fonts)
    if not font_path:
        logger.info("[TL-PATCH] 未找到中文字体，跳过字体补丁")
        logger.info("[TL-PATCH] 请将 .ttf/.otf 字体文件放入 resources/fonts/ 目录")
        return

    font_name = font_path.name

    # 1. Copy font to game dir
    dst_font = game_dir / font_name
    if not dst_font.exists():
        shutil.copy2(font_path, dst_font)
        logger.info(f"[TL-PATCH] 复制字体: {font_name} -> game/")
    else:
        logger.info(f"[TL-PATCH] 字体已存在: {font_name}")

    # 2. 直接修改所有 gui.rpy 中的字体定义（define gui.*_font = "..."）
    #    这是最可靠的方式——style 系统在 init 阶段绑定字体，translate None python 太晚
    font_pattern = re.compile(
        r'^(\s*define\s+gui\.\w+_font\s*=\s*)["\']([^"\']*)["\'](\s*)$',
        re.MULTILINE,
    )
    gui_files = list(game_dir.rglob("gui.rpy"))
    for gui_rpy in gui_files:
        text = gui_rpy.read_text(encoding="utf-8")
        new_text, count = font_pattern.subn(
            lambda m: m.group(1) + '"' + font_name + '"' + m.group(3),
            text,
        )
        if count > 0:
            # 备份原文件（首次）
            bak = gui_rpy.with_suffix(".rpy.font_bak")
            if not bak.exists():
                shutil.copy2(gui_rpy, bak)
            gui_rpy.write_text(new_text, encoding="utf-8")
            rel = gui_rpy.relative_to(game_dir.parent) if game_dir.parent else gui_rpy
            logger.info(f"[TL-PATCH] 修改字体: {rel} ({count} 处 gui.*_font → {font_name})")

    # 如果有 font_config.json，应用额外的 gui_overrides
    config = load_font_config(font_config_path)
    overrides = config.get("gui_overrides", {})
    if overrides:
        for gui_rpy in gui_files:
            text = gui_rpy.read_text(encoding="utf-8")
            size_count = 0
            for var_name, value in overrides.items():
                var_pat = re.compile(
                    rf"^(\s*define\s+{re.escape(var_name)}\s*=\s*)[\d.]+(\s*)$",
                    re.MULTILINE,
                )
                text, n = var_pat.subn(rf"\g<1>{value}\2", text)
                size_count += n
            if size_count > 0:
                gui_rpy.write_text(text, encoding="utf-8")
                logger.info(f"[TL-PATCH] 应用 font_config 覆盖: {gui_rpy.name} ({size_count} 处)")

    # 3. 生成 none_overlay.rpy 作为翻译激活时的额外保障
    tl_dir = game_dir / "tl" / tl_lang
    tl_dir.mkdir(parents=True, exist_ok=True)

    overlay_lines = [
        "# none_overlay.rpy — 自动生成的字体覆盖模板",
        "# 作为 gui.rpy 直接修改的补充保障",
        "",
        "translate None python:",
        f'    gui.text_font = "{font_name}"',
        f'    gui.name_text_font = "{font_name}"',
        f'    gui.interface_text_font = "{font_name}"',
        f'    gui.button_text_font = "{font_name}"',
        f'    gui.choice_button_text_font = "{font_name}"',
    ]
    overlay_rpy = tl_dir / "none_overlay.rpy"
    overlay_rpy.write_text("\n".join(overlay_lines) + "\n", encoding="utf-8")
    logger.info(f"[TL-PATCH] 生成覆盖模板: {overlay_rpy.relative_to(game_dir.parent)}")

    # 3. Write chinese_language_patch.rpy (default language setting)
    patch_rpy = tl_dir / "chinese_language_patch.rpy"
    patch_content = f'init python:\n    config.language = "{tl_lang}"\n'
    patch_rpy.write_text(patch_content, encoding="utf-8")
    logger.info(f"[TL-PATCH] 写入语言补丁: {patch_rpy.relative_to(game_dir.parent)}")

    # 4. Inject language buttons into screen preferences()
    _inject_language_buttons(game_dir, tl_lang)


def _inject_language_buttons(game_dir: Path, tl_lang: str) -> None:
    """Find all screen preferences() in .rpy files and inject Language radio buttons."""
    snippet = _LANG_BUTTON_SNIPPET.replace("{lang}", tl_lang)
    marker = "action Language("

    for rpy in game_dir.rglob("*.rpy"):
        # Skip tl directory files
        try:
            rpy.relative_to(game_dir / "tl")
            continue
        except ValueError:
            pass

        text = rpy.read_text(encoding="utf-8-sig")
        if "screen preferences()" not in text:
            continue
        if marker in text:
            logger.info(f"[TL-PATCH] 语言按钮已存在: {rpy.relative_to(game_dir.parent)}")
            continue

        # Find the Skip section's closing line to insert after
        lines = text.splitlines(True)
        insert_idx = None
        in_skip = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if 'label _("Skip")' in stripped:
                in_skip = True
            if in_skip and stripped.startswith("textbutton") and "Transitions" in stripped:
                insert_idx = i + 1
                break

        if insert_idx is None:
            # Fallback: find after Rollback Side section
            for i, line in enumerate(lines):
                stripped = line.strip()
                if 'label _("Rollback Side")' in stripped:
                    # Find the last textbutton in this vbox
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if (
                            lines[j].strip().startswith("textbutton")
                            and "right" in lines[j].lower()
                        ):
                            insert_idx = j + 1
                            break
                    break

        if insert_idx is None:
            logger.info(f"[TL-PATCH] 无法定位注入点: {rpy.relative_to(game_dir.parent)}")
            continue

        # Create backup
        bak = rpy.with_suffix(".rpy.lang_bak")
        if not bak.exists():
            shutil.copy2(rpy, bak)

        lines.insert(insert_idx, snippet)
        rpy.write_text("".join(lines), encoding="utf-8")
        logger.info(f"[TL-PATCH] 注入语言按钮: {rpy.relative_to(game_dir.parent)}")
