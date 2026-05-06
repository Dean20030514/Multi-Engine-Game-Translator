#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎检测器：目录特征扫描 + CLI 路由。

检测优先级（first match wins）：
1. Ren'Py — game/ 下有 .rpy/.rpa，或根目录有 .rpy
2. RPG Maker MV — www/data/System.json
3. RPG Maker MZ — data/System.json（无 www/ 层级）
4. RPG Maker VX/Ace — .rgss2a/.rgss3a 或 Data/*.rvdata*
5. CSV/JSONL — 不自动检测，仅通过 --engine csv 手动指定
"""

from __future__ import annotations

import enum
import logging
from collections import Counter
from pathlib import Path

logger = logging.getLogger("multi_engine_translator")


class EngineType(enum.Enum):
    """支持的引擎类型枚举。"""

    RENPY = "renpy"
    RPGMAKER_MV = "rpgmaker_mv"
    RPGMAKER_VXACE = "rpgmaker_vxace"
    CSV = "csv"
    JSONL = "jsonl"
    UNITY_XUNITY = "unity_xunity"  # Round 55
    UNKNOWN = "unknown"


def detect_engine_type(game_dir: Path) -> EngineType:
    """扫描目录特征，返回引擎类型枚举。纯检测，不实例化。"""
    game_dir = Path(game_dir)

    # 1. Ren'Py: game/ 下有 .rpy 或 .rpa；或根目录有 .rpy
    game_sub = game_dir / "game"
    if game_sub.is_dir():
        if any(game_sub.glob("*.rpy")) or any(game_sub.glob("*.rpa")):
            return EngineType.RENPY
    if any(game_dir.glob("*.rpy")):
        return EngineType.RENPY

    # 2. RPG Maker MV: www/data/System.json
    if (game_dir / "www" / "data" / "System.json").is_file():
        return EngineType.RPGMAKER_MV

    # 3. RPG Maker MZ: data/System.json（无 www/）
    if (game_dir / "data" / "System.json").is_file():
        return EngineType.RPGMAKER_MV  # MV 和 MZ 用同一引擎类

    # 4. RPG Maker VX/Ace: .rgss2a/.rgss3a 或 Data/*.rvdata*
    if any(game_dir.glob("*.rgss2a")) or any(game_dir.glob("*.rgss3a")):
        return EngineType.RPGMAKER_VXACE
    data_sub = game_dir / "Data"
    if data_sub.is_dir():
        if any(data_sub.glob("*.rvdata")) or any(data_sub.glob("*.rvdata2")):
            return EngineType.RPGMAKER_VXACE

    # 5. 未识别
    return EngineType.UNKNOWN


def _log_unknown_directory(game_dir: Path) -> None:
    """输出未识别目录的诊断信息。"""
    ext_counter: Counter = Counter()
    for f in game_dir.rglob("*"):
        if f.is_file():
            ext_counter[f.suffix.lower()] += 1
    top10 = ext_counter.most_common(10)
    if top10:
        logger.warning("[DETECT] 未能自动识别引擎类型。目录文件扩展名 Top 10:")
        for ext, count in top10:
            logger.warning(f"  {ext or '(无扩展名)':>12s}: {count}")
    logger.warning("[DETECT] 请使用 --engine 手动指定引擎类型")


def create_engine(engine_type: EngineType):
    """从枚举创建 Engine 实例。使用延迟导入，避免加载不需要的模块。

    Returns: EngineBase 实例，或 None（未知/未实现的引擎类型）。
    """
    if engine_type == EngineType.RENPY:
        from engines.renpy_engine import RenPyEngine

        return RenPyEngine()

    if engine_type == EngineType.RPGMAKER_MV:
        # RPG Maker MV/MZ 引擎（待实现）
        try:
            from engines.rpgmaker_engine import RPGMakerMVEngine

            return RPGMakerMVEngine()
        except ImportError:
            logger.error("[DETECT] RPG Maker 引擎模块尚未实现")
            return None

    if engine_type == EngineType.CSV:
        try:
            from engines.csv_engine import CSVEngine

            return CSVEngine()
        except ImportError:
            logger.error("[DETECT] CSV 引擎模块尚未实现")
            return None

    if engine_type == EngineType.JSONL:
        try:
            from engines.csv_engine import CSVEngine

            return CSVEngine()  # JSONL 复用 CSV 引擎
        except ImportError:
            logger.error("[DETECT] CSV/JSONL 引擎模块尚未实现")
            return None

    if engine_type == EngineType.RPGMAKER_VXACE:
        logger.error("[DETECT] RPG Maker VX/Ace 需要 rubymarshal 库，尚未实现")
        return None

    if engine_type == EngineType.UNITY_XUNITY:
        try:
            from engines.unity_xunity import UnityXUnityEngine

            return UnityXUnityEngine()
        except ImportError:
            logger.error("[DETECT] Unity XUnity 引擎模块加载失败")
            return None

    return None


def detect_engine(game_dir: Path):
    """检测目录引擎类型并返回 Engine 实例。

    Returns: EngineBase 实例，或 None。
    """
    engine_type = detect_engine_type(game_dir)
    if engine_type == EngineType.UNKNOWN:
        _log_unknown_directory(game_dir)
        return None
    logger.info(f"[DETECT] 检测到引擎: {engine_type.value}")
    return create_engine(engine_type)


# CLI --engine 参数到 EngineType 的映射
_MANUAL_MAP: dict[str, EngineType] = {
    "renpy": EngineType.RENPY,
    "rpgmaker": EngineType.RPGMAKER_MV,
    "rpgmaker_mv": EngineType.RPGMAKER_MV,
    "rpgmaker_mz": EngineType.RPGMAKER_MV,
    "csv": EngineType.CSV,
    "jsonl": EngineType.JSONL,
    # Round 55: Unity XUnity AutoTranslator (both names accepted)
    "unity": EngineType.UNITY_XUNITY,
    "unity_xunity": EngineType.UNITY_XUNITY,
}


def resolve_engine(engine_arg: str, game_dir: Path):
    """CLI --engine 参数路由。

    Args:
        engine_arg: "auto" / "renpy" / "rpgmaker" / "csv" / "jsonl"
        game_dir: 游戏根目录

    Returns: EngineBase 实例，或 None。
    """
    if engine_arg == "auto":
        return detect_engine(game_dir)

    engine_type = _MANUAL_MAP.get(engine_arg.lower())
    if engine_type is None:
        logger.error(f"[DETECT] 未知引擎类型: {engine_arg}")
        return None
    return create_engine(engine_type)
