#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline.helpers -- Low-level utilities for the one-click pipeline."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


# ---- 常量（从 one_click_pipeline.py 迁入）----

RISK_KEYWORDS = [
    "screen",
    "gui",
    "options",
    "menu",
    "club",
    "dining",
    "living",
    "parents",
    "secret",
    "weekend",
    "v0",
    "help",
    "interaction",
]

MAX_FILE_RANK_SCORE = 200  # 文件大小评分上限
RISK_KEYWORD_SCORE = 80  # 命中风险关键词加分
SAZMOD_BONUS_SCORE = 30  # SAZMOD 模组额外加分

LEN_RATIO_LOWER = 0.15
LEN_RATIO_UPPER = 2.5


class StageError(RuntimeError):
    pass


def _print(msg: str) -> None:
    logger.info(msg)


def resolve_scan_root(game_dir: Path) -> Path:
    """与 main.py 保持一致：优先 game/，但根目录若有 rpy 则扫描整个根目录。"""
    if (game_dir / "game").exists():
        root_rpys = list(game_dir.glob("*.rpy"))
        if root_rpys:
            return game_dir
        return game_dir / "game"
    return game_dir


def list_rpy_files(scan_root: Path) -> list[Path]:
    return sorted([p for p in scan_root.rglob("*.rpy") if p.is_file()])


def score_file(rel_path: str, size: int) -> int:
    lower = rel_path.lower()
    score = min(size // 1024, MAX_FILE_RANK_SCORE)
    for k in RISK_KEYWORDS:
        if k in lower:
            score += RISK_KEYWORD_SCORE
    if "sazmod" in lower:
        score += SAZMOD_BONUS_SCORE
    return score


def pick_pilot_files(scan_root: Path, pilot_count: int) -> list[Path]:
    files = list_rpy_files(scan_root)
    ranked = sorted(
        files,
        key=lambda p: score_file(str(p.relative_to(scan_root)), p.stat().st_size),
        reverse=True,
    )
    return ranked[:pilot_count]


def copy_subset_to_input(scan_root: Path, files: Iterable[Path], dst_input: Path) -> None:
    if dst_input.exists():
        shutil.rmtree(dst_input)
    dst_input.mkdir(parents=True, exist_ok=True)
    for src in files:
        rel = src.relative_to(scan_root)
        dst = dst_input / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def run_main(
    game_dir: Path,
    output_dir: Path,
    provider: str,
    api_key: str,
    model: str,
    genre: str,
    workers: int,
    rpm: int,
    rps: int,
    timeout: float,
    max_chunk_tokens: int,
    max_response_tokens: int,
    log_file: Path,
    resume: bool,
    dict_paths: list[str] | None = None,
    excludes: list[str] | None = None,
    copy_assets: bool = False,
    target_lang: str = "zh",
    stage: str = "full",
    min_dialogue_density: float = 0.20,
    tl_mode: bool = False,
    tl_lang: str = "chinese",
) -> None:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "main.py"),
        "--game-dir",
        str(game_dir),
        "--output-dir",
        str(output_dir),
        "--provider",
        provider,
        "--api-key",
        api_key,
        "--genre",
        genre,
        "--workers",
        str(workers),
        "--rpm",
        str(rpm),
        "--rps",
        str(rps),
        "--timeout",
        str(timeout),
        "--max-chunk-tokens",
        str(max_chunk_tokens),
        "--max-response-tokens",
        str(max_response_tokens),
        "--log-file",
        str(log_file),
        "--stage",
        stage,
        "--min-dialogue-density",
        str(min_dialogue_density),
    ]
    if model:
        cmd += ["--model", model]
    if resume:
        cmd.append("--resume")
    if dict_paths:
        cmd += ["--dict", *dict_paths]
    if excludes:
        cmd += ["--exclude", *excludes]
    if copy_assets:
        cmd.append("--copy-assets")
    # Round 52 C4 BREAKING: --target-lang removed from main.py; argument
    # ``target_lang`` kept for backward-compat signature but ignored.
    _ = target_lang
    if tl_mode:
        cmd += ["--tl-mode", "--tl-lang", tl_lang]

    _print("\n[RUN ] " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent)
    if proc.returncode != 0:
        raise StageError(f"main.py 执行失败，退出码 {proc.returncode}")


def package_output(output_root: Path, package_name: str) -> Path:
    """将翻译结果打包为 zip，默认打包 output_root/game。"""
    src = output_root / "game"
    if not src.exists():
        src = output_root
    archive_base = output_root / package_name
    archive = shutil.make_archive(str(archive_base), "zip", root_dir=src)
    return Path(archive)


def _normalize_ws(s: str) -> str:
    """将连续空白压缩为单空格，去除首尾空白。"""
    return re.sub(r"\s+", " ", s.strip())
