#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""零 API 调用验证方案 a（strings 专用回写）和方案 b（original 对齐）的效果。

用法:
  python verify_alignment.py
  python verify_alignment.py --game-dir "E:/path/to/game" --db "path/to/translation_db.json" --old-output "path/to/stage2_translated/game"

流程:
  1. 读取原游戏目录 .rpy 与 translation_db 中的翻译条目
  2. 对每个有条目的文件用 apply_translations（含 strings 专用路径和 original 对齐）重新回写
  3. 回写结果输出到临时目录
  4. 对临时目录和旧输出分别跑 evaluate_gate，对比漏翻率
  5. 统计并打印：original 对齐命中条数、strings 专用路径处理条数、新旧漏翻率对比
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from file_processor import apply_translations, read_file
from pipeline.gate import evaluate_gate
from pipeline.helpers import list_rpy_files
from core.translation_db import TranslationDB


def _default_paths(script_dir: Path) -> dict:
    return {
        "game_dir": Path(
            os.environ.get(
                "TEST_GAME_DIR",
                r"E:\浏览器下载\TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed\game",
            )
        ),
        "db_path": script_dir
        / "output"
        / "projects"
        / "TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed"
        / "translation_db.json",
        "old_translated": script_dir
        / "output"
        / "projects"
        / "TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed"
        / "stage2_translated"
        / "game",
    }


def _entries_for_file(entries: list[dict], rel_path: str) -> list[dict]:
    """Build list of {line, original, zh} for apply_translations from DB entries."""
    out = []
    for e in entries:
        if str(e.get("file", "")).replace("/", "\\") != rel_path.replace("/", "\\"):
            continue
        line = int(e.get("line") or 0)
        original = (e.get("original") or "").strip()
        zh = (e.get("translation") or e.get("zh") or "").strip()
        if not line or not original:
            continue
        out.append({"line": line, "original": original, "zh": zh})
    return out


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    defaults = _default_paths(script_dir)

    parser = argparse.ArgumentParser(description="验证方案 a/b 回写与对齐效果（零 API 调用）")
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=defaults["game_dir"],
        help="原游戏目录（含 .rpy 的 game 目录）",
    )
    parser.add_argument(
        "--db", type=Path, default=defaults["db_path"], help="translation_db.json 路径"
    )
    parser.add_argument(
        "--old-output",
        type=Path,
        default=defaults["old_translated"],
        help="上次翻译输出目录（stage2_translated/game）",
    )
    parser.add_argument(
        "--temp-dir",
        type=Path,
        default=None,
        help="临时回写目录（默认：项目 output 下 verify_temp）",
    )
    args = parser.parse_args()

    game_dir = args.game_dir.resolve()
    db_path = args.db.resolve()
    old_translated = args.old_output.resolve()
    if args.temp_dir is not None:
        temp_dir = args.temp_dir.resolve()
    else:
        temp_dir = (
            script_dir
            / "output"
            / "projects"
            / "TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed"
            / "verify_temp"
        )
    temp_dir = temp_dir.resolve()

    if not game_dir.is_dir():
        print(f"[ERROR] 原游戏目录不存在: {game_dir}")
        sys.exit(1)
    if not db_path.is_file():
        print(f"[ERROR] translation_db 不存在: {db_path}")
        sys.exit(1)
    if not old_translated.is_dir():
        print(f"[ERROR] 上次翻译输出目录不存在: {old_translated}")
        sys.exit(1)

    # 加载 DB，按文件分组
    db = TranslationDB(db_path)
    db.load()
    by_file: dict[str, list[dict]] = {}
    for e in db.entries:
        f = str(e.get("file", "")).replace("/", "\\")
        if f not in by_file:
            by_file[f] = []
        by_file[f].append(e)

    # 列出上次输出中的所有 .rpy（保证新旧闸门同一批文件）
    old_rpy_files = list_rpy_files(old_translated)
    if not old_rpy_files:
        print("[ERROR] 上次翻译输出目录下未找到 .rpy 文件")
        sys.exit(1)

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    total_alignment = 0
    total_strings_applied = 0
    files_patched = 0
    files_copied = 0

    for trans_path in old_rpy_files:
        rel = str(trans_path.relative_to(old_translated))
        rel_norm = rel.replace("/", "\\")
        orig_path = game_dir / rel
        temp_path = temp_dir / rel

        if not orig_path.exists():
            print(f"[WARN] 原文件不存在，跳过: {rel}")
            continue

        entries = _entries_for_file(db.entries, rel_norm)
        if entries:
            content = read_file(orig_path)
            patched, _warnings, stats = apply_translations(content, entries)
            total_alignment += stats.get("alignment_count", 0)
            total_strings_applied += stats.get("strings_applied_count", 0)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(patched, encoding="utf-8")
            files_patched += 1
        else:
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(trans_path, temp_path)
            files_copied += 1

    print("\n--- 回写统计 ---")
    print(f"  重新回写（含对齐+strings）: {files_patched} 个文件")
    print(f"  直接复制（无 DB 条目）: {files_copied} 个文件")
    print(f"  original 对齐命中: {total_alignment} 条")
    print(f"  strings 专用路径处理: {total_strings_applied} 条")

    # 旧闸门（上次输出）
    print("\n--- 旧闸门（上次翻译输出）---")
    old_gate = evaluate_gate(game_dir, old_translated)
    old_ratio = old_gate.get("untranslated_ratio", 0.0)
    old_dialogue = old_gate.get("dialogue_total", 0)
    old_untrans = old_gate.get("untranslated_total", 0)
    print(f"  文件数: {old_gate.get('files', 0)}")
    print(f"  对话行总数: {old_dialogue}")
    print(f"  疑似未翻译行数: {old_untrans}")
    print(f"  漏翻率: {old_ratio:.2%}")
    print(f"  errors: {old_gate.get('errors', 0)}")

    # 新闸门（本次回写临时目录）
    print("\n--- 新闸门（重新回写后的临时目录）---")
    new_gate = evaluate_gate(game_dir, temp_dir)
    new_ratio = new_gate.get("untranslated_ratio", 0.0)
    new_dialogue = new_gate.get("dialogue_total", 0)
    new_untrans = new_gate.get("untranslated_total", 0)
    print(f"  文件数: {new_gate.get('files', 0)}")
    print(f"  对话行总数: {new_dialogue}")
    print(f"  疑似未翻译行数: {new_untrans}")
    print(f"  漏翻率: {new_ratio:.2%}")
    print(f"  errors: {new_gate.get('errors', 0)}")

    print("\n--- 新旧漏翻率对比 ---")
    print(f"  旧漏翻率: {old_ratio:.2%}  (未翻译 {old_untrans} / 对话行 {old_dialogue})")
    print(f"  新漏翻率: {new_ratio:.2%}  (未翻译 {new_untrans} / 对话行 {new_dialogue})")
    if old_dialogue and old_dialogue == new_dialogue:
        diff = old_untrans - new_untrans
        print(f"  疑似未翻译行数变化: {diff:+d}")
    print(f"\n临时目录: {temp_dir}")


if __name__ == "__main__":
    main()
