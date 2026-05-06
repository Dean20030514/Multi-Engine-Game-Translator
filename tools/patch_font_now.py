#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-off font patch: apply font to existing translation output without re-running the pipeline.

Run from project root. After running, copy stage2_translated/game contents into the game's game folder.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.font_patch import resolve_font, apply_font_patch, default_resources_fonts_dir

# Already-translated output (stage2_translated/game)
OUTPUT_GAME = Path(
    os.environ.get(
        "PATCH_OUTPUT_GAME",
        r"output\projects\TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed\stage2_translated\game",
    )
)
# Original game directory (game subdir)
SOURCE_GAME = Path(
    os.environ.get(
        "TEST_GAME_DIR",
        r"E:\浏览器下载\TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed\game",
    )
)

if __name__ == "__main__":
    # Round 29 fixed a ``Path(__file__).parent`` bug here; round 32 extracts
    # the canonical ``default_resources_fonts_dir()`` helper in
    # ``core/font_patch.py`` so all four callers share one resolution path.
    resources_fonts = default_resources_fonts_dir()
    font = resolve_font(resources_fonts, None)
    if font:
        apply_font_patch(OUTPUT_GAME, SOURCE_GAME, font)
        print("字体补丁完成")
    else:
        print("未找到字体，请将 .ttf 或 .otf 放入 resources/fonts/ 后重试")
