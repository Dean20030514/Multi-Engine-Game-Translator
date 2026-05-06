#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文交互启动器：避免 .bat 编码问题"""

from __future__ import annotations

import getpass
import os
import shlex
import subprocess
import sys
from pathlib import Path


def ask(prompt: str, default: str = "") -> str:
    s = input(prompt).strip()
    s = _normalize_input(s)
    return s if s else default


def _normalize_input(s: str) -> str:
    """规范化用户输入：去首尾空白、常见中英文引号。"""
    if not s:
        return ""
    s = s.strip()
    # 去掉首尾常见引号（英文/中文）
    quote_chars = "\"'“”‘’"
    while len(s) >= 2 and s[0] in quote_chars and s[-1] in quote_chars:
        s = s[1:-1].strip()
    return s


def run(cmd: list[str], api_key: str = "") -> int:
    """Spawn the child process.

    API key is passed via a private environment variable rather than ``--api-key``
    to keep it off the process command line (Windows WMI / ``ps`` etc). The
    child (main.py / one_click_pipeline.py) reads and pops it immediately.
    """
    print("\n============================================================")
    print("执行命令:")
    # Legacy compatibility mask: 第 21 轮 (S-H-1) 起 launcher 不再把 --api-key
    # 写入 cmd（改走子进程 env），但保留下方的遮盖逻辑以兼容手工构造的 cmd。
    display_cmd = []
    skip_next = False
    for arg in cmd:
        if skip_next:
            display_cmd.append("****")
            skip_next = False
        elif arg == "--api-key":
            display_cmd.append(arg)
            skip_next = True
        else:
            display_cmd.append(arg)
    print(" ".join(shlex.quote(x) for x in display_cmd))
    print("============================================================\n")

    child_env = os.environ.copy()
    if api_key:
        child_env["_RENPY_TRANSLATOR_CHILD_API_KEY"] = api_key
    return subprocess.call(cmd, cwd=Path(__file__).parent, env=child_env)


def main() -> int:
    print("=" * 60)
    print("多引擎游戏汉化统一启动器")
    print("=" * 60)
    print("── Ren'Py ──")
    print("1. 主流程翻译（从头开始）")
    print("2. 主流程翻译（断点续跑）")
    print("3. 仅扫描与费用估算（Dry-run）")
    print("4. 一键流水线（试跑+闸门+全量+漏翻增量）")
    print("5. tl-mode 翻译（从头开始）")
    print("6. tl-mode 翻译（断点续跑）")
    print("── 其他引擎 ──")
    print("8. RPG Maker MV/MZ 翻译")
    print("9. CSV/JSONL 通用格式翻译")
    print("── 工具 ──")
    print("7. Ren'Py 7→8 升级扫描（检测 Python 2 / 旧 API 问题）")

    mode = ask("\n输入模式 [1-9]（默认4）: ", "4")
    if mode == "7":
        scan_dir = ask("游戏 game 目录路径: ")
        if not scan_dir:
            print("[错误] 必须提供路径")
            return 1
        scan_dir = str(Path(scan_dir).expanduser())
        do_fix = ask("自动修复？[y/N]（默认 N）: ", "n").lower() == "y"
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "tools" / "renpy_upgrade_tool.py"),
            scan_dir,
            "--backup",
        ]
        if do_fix:
            cmd.append("--fix")
        return run(cmd)

    game_dir = ask("游戏根目录路径: ")
    if not game_dir:
        print("[错误] 必须提供游戏目录路径")
        return 1

    game_dir = str(Path(game_dir).expanduser())

    output_dir = ask("输出目录（默认 output）: ", "output")
    provider = ask("提供商 [xai/openai/deepseek/claude/gemini]（默认 xai）: ", "xai").lower()
    model = ask("模型（默认 grok-4-1-fast-reasoning）: ", "grok-4-1-fast-reasoning")

    py = sys.executable

    if mode == "3":
        cmd = [
            py,
            "main.py",
            "--game-dir",
            game_dir,
            "--provider",
            provider,
            "--model",
            model,
            "--dry-run",
        ]
        return run(cmd)

    api_key = getpass.getpass("API 密钥（输入时不显示）: ").strip()
    if not api_key:
        print("[错误] 非 dry-run 模式必须提供 API 密钥")
        return 1

    genre = ask("翻译风格 [adult/visual_novel/rpg/general]（默认 adult）: ", "adult")
    rpm = ask("RPM 每分钟请求数（默认 600）: ", "600")
    rps = ask("RPS 每秒请求数（默认 10）: ", "10")

    if mode in ("5", "6"):
        tl_lang = ask("tl 语言目录名（默认 chinese）: ", "chinese")
        workers = ask("并发线程数（默认 5）: ", "5")
        use_screen = (
            ask("翻译 screen 裸英文？[y/N]（补充 tl 框架无法覆盖的 UI 文本）: ", "n").lower() == "y"
        )
        extra = ["--resume"] if mode == "6" else []
        if use_screen:
            extra.append("--tl-screen")
        cmd = [
            py,
            "-u",
            "main.py",
            "--game-dir",
            game_dir,
            "--output-dir",
            output_dir,
            "--provider",
            provider,
            "--model",
            model,
            "--genre",
            genre,
            "--rpm",
            rpm,
            "--rps",
            rps,
            "--workers",
            workers,
            "--tl-mode",
            "--tl-lang",
            tl_lang,
            *extra,
        ]
        return run(cmd, api_key=api_key)

    # ── 模式 8: RPG Maker MV/MZ ──
    if mode == "8":
        workers = ask("并发线程数（默认 3）: ", "3")
        cmd = [
            py,
            "main.py",
            "--engine",
            "rpgmaker",
            "--game-dir",
            game_dir,
            "--output-dir",
            output_dir,
            "--provider",
            provider,
            "--model",
            model,
            "--genre",
            genre,
            "--workers",
            workers,
            "--rpm",
            rpm,
            "--rps",
            rps,
        ]
        return run(cmd, api_key=api_key)

    # ── 模式 9: CSV/JSONL 通用格式 ──
    if mode == "9":
        engine = ask("格式类型 [csv/jsonl]（默认 csv）: ", "csv").lower()
        if engine not in ("csv", "jsonl"):
            engine = "csv"
        workers = ask("并发线程数（默认 3）: ", "3")
        cmd = [
            py,
            "main.py",
            "--engine",
            engine,
            "--game-dir",
            game_dir,
            "--output-dir",
            output_dir,
            "--provider",
            provider,
            "--model",
            model,
            "--workers",
            workers,
            "--rpm",
            rpm,
            "--rps",
            rps,
        ]
        return run(cmd, api_key=api_key)

    workers = ask("并发线程数（默认 3）: ", "3")

    if mode == "4":
        use_tl = (
            ask("使用 tl-mode？[y/N]（默认 N，选 y 则跳过试跑/补翻，直接 tl 翻译）: ", "n").lower()
            == "y"
        )
        cmd = [
            py,
            "one_click_pipeline.py",
            "--game-dir",
            game_dir,
            "--output-dir",
            output_dir,
            "--provider",
            provider,
            "--model",
            model,
            "--genre",
            genre,
            "--workers",
            workers,
            "--rpm",
            rpm,
            "--rps",
            rps,
            "--clean-output",
        ]
        if use_tl:
            tl_lang = ask("tl 语言目录名（默认 chinese）: ", "chinese")
            cmd += ["--tl-mode", "--tl-lang", tl_lang]
        else:
            pilot_count = ask("试跑文件数量（默认 20）: ", "20")
            gate_ratio = ask("闸门最大漏翻占比（默认 0.08）: ", "0.08")
            cmd += ["--pilot-count", pilot_count, "--gate-max-untranslated-ratio", gate_ratio]
        return run(cmd, api_key=api_key)

    extra = ["--resume"] if mode == "2" else []
    cmd = [
        py,
        "main.py",
        "--game-dir",
        game_dir,
        "--output-dir",
        output_dir,
        "--provider",
        provider,
        "--model",
        model,
        "--genre",
        genre,
        "--workers",
        workers,
        "--rpm",
        rpm,
        "--rps",
        rps,
        *extra,
    ]
    return run(cmd, api_key=api_key)


if __name__ == "__main__":
    raise SystemExit(main())
