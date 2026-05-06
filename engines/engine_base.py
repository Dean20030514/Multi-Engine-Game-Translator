#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎抽象层：EngineProfile 参数化描述 + TranslatableUnit 文本单元 + EngineBase ABC。

设计原则：
- 浅抽象、参数化差异：引擎间差异通过 EngineProfile 数据类参数化
- Ren'Py 代码零改动：现有管线不重构，通过薄包装接入
- 零依赖约束不破坏：核心框架全部用标准库
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================
# EngineProfile — 引擎差异的参数化描述
# ============================================================


@dataclass
class EngineProfile:
    """引擎的参数化描述，让通用流水线根据引擎调整行为。

    placeholder_patterns 和 skip_line_patterns 存储正则字符串列表，
    通过 compile_*_re() 按需编译为单个 Pattern（用 | 合并）。
    """

    name: str  # 引擎标识符: "renpy" / "rpgmaker_mv" / "csv"
    display_name: str  # 用户可见名称: "RPG Maker MV/MZ"

    # 占位符正则列表，用于 protect_placeholders 参数化
    placeholder_patterns: list[str] = field(default_factory=list)
    # 不应翻译的行模式正则（整行匹配）
    skip_line_patterns: list[str] = field(default_factory=list)

    encoding: str = "utf-8"  # 文件默认编码
    max_line_length: int | None = None  # 译文行宽限制（None 表示无限制）
    prompt_addon_key: str = ""  # prompts.py 中引擎专属 prompt 片段的查找 key
    supports_context: bool = True  # 提取时是否提供上下文行
    context_lines: int = 3  # 上下文行数

    def compile_placeholder_re(self) -> re.Pattern | None:
        """将 placeholder_patterns 编译为单个正则，无模式时返回 None。"""
        if not self.placeholder_patterns:
            return None
        combined = "|".join(f"(?:{p})" for p in self.placeholder_patterns)
        return re.compile(combined)

    def compile_skip_re(self) -> re.Pattern | None:
        """将 skip_line_patterns 编译为单个正则，无模式时返回 None。"""
        if not self.skip_line_patterns:
            return None
        combined = "|".join(f"(?:{p})" for p in self.skip_line_patterns)
        return re.compile(combined)


# ============================================================
# TranslatableUnit — 所有非 Ren'Py 引擎共用的文本单元
# ============================================================


@dataclass
class TranslatableUnit:
    """可翻译文本单元。Ren'Py 不使用此类（有自己的 DialogueEntry/StringEntry 体系）。

    id 的唯一性由引擎负责保证：
    - RPG Maker: "Map001.json:events[3].pages[0].list[5]"
    - CSV: 行号或用户提供的 ID 列值

    metadata 是 extract → write_back 的桥梁：引擎在提取时存入定位信息，
    回写时根据这些信息精确替换。通用流水线不碰 metadata，只透传。
    """

    id: str  # 全局唯一标识
    original: str  # 原文
    file_path: str  # 来源文件相对路径

    context: str = ""  # 上下文（前后几行）
    speaker: str = ""  # 说话人/角色名
    metadata: dict[str, Any] = field(default_factory=dict)  # 引擎专属元数据
    translation: str = ""  # 翻译结果
    status: str = "pending"  # pending/translated/checker_dropped/ai_not_returned/skipped


# ============================================================
# EngineBase — 引擎抽象基类
# ============================================================


class EngineBase(ABC):
    """所有引擎的基类。子类必须实现 4 个抽象方法。

    Ren'Py 覆写 run() 委托给现有管线；其他引擎使用默认 run() 走通用流水线。
    """

    def __init__(self) -> None:
        self.profile: EngineProfile = self._default_profile()

    @abstractmethod
    def _default_profile(self) -> EngineProfile:
        """返回该引擎的默认 Profile。"""
        ...

    @abstractmethod
    def detect(self, game_dir: Path) -> bool:
        """检查目录是否属于该引擎。"""
        ...

    @abstractmethod
    def extract_texts(self, game_dir: Path, **kwargs) -> list[TranslatableUnit]:
        """从游戏文件中提取所有可翻译文本。"""
        ...

    @abstractmethod
    def write_back(
        self, game_dir: Path, units: list[TranslatableUnit], output_dir: Path, **kwargs
    ) -> int:
        """将翻译结果写回游戏文件，返回成功写入数。"""
        ...

    def post_process(self, game_dir: Path, output_dir: Path) -> None:
        """回写后的可选后处理（默认什么都不做）。"""
        pass

    def run(self, args) -> None:
        """运行完整翻译流水线。Ren'Py 覆写此方法，其他引擎走通用流水线。"""
        from engines.generic_pipeline import run_generic_pipeline

        run_generic_pipeline(self, args)

    def dry_run(self, game_dir: Path) -> dict:
        """dry-run 模式：提取文本并统计，不调用 API。"""
        units = self.extract_texts(game_dir)
        total_chars = sum(len(u.original) for u in units)
        files = set(u.file_path for u in units)
        return {
            "engine": self.profile.display_name,
            "files": len(files),
            "texts": len(units),
            "total_chars": total_chars,
        }


# ============================================================
# 内置 Profile 常量
# ============================================================

RENPY_PROFILE = EngineProfile(
    name="renpy",
    display_name="Ren'Py",
    placeholder_patterns=[
        r"\[\w+\]",  # [variable]
        r"\{[^}]+\}",  # {tag}, {color=#fff}, {w}, {p}, etc.
        r"%\(\w+\)[sd]",  # %(name)s, %(count)d
    ],
    skip_line_patterns=[
        r"^\s*label\s+",
        r"^\s*screen\s+",
        r"^\s*init\s+",
    ],
    prompt_addon_key="renpy",
    context_lines=5,
)

RPGMAKER_MV_PROFILE = EngineProfile(
    name="rpgmaker_mv",
    display_name="RPG Maker MV/MZ",
    placeholder_patterns=[
        r"\\V\[\d+\]",  # \V[n] 游戏变量
        r"\\N\[\d+\]",  # \N[n] 角色名
        r"\\P\[\d+\]",  # \P[n] 队伍成员名
        r"\\C\[\d+\]",  # \C[n] 颜色
        r"\\I\[\d+\]",  # \I[n] 图标
        r"\\G",  # \G 货币单位
        r"\\\{",  # \{ 放大文字
        r"\\\}",  # \} 缩小文字
        r"\\!",  # \! 等待按键
        r"\\\.",  # \. 等待 1/4 秒
        r"\\\|",  # \| 等待 1 秒
        r"\\>",  # \> 瞬间显示开
        r"\\<",  # \< 瞬间显示关
    ],
    prompt_addon_key="rpgmaker",
    supports_context=True,
    context_lines=3,
)

CSV_PROFILE = EngineProfile(
    name="csv",
    display_name="CSV/JSONL",
    placeholder_patterns=[],  # 用户可通过 CLI --placeholder-regex 自定义
    prompt_addon_key="generic",
    supports_context=False,
    context_lines=0,
)

# Round 55: Unity XUnity AutoTranslator engine.
# Round 56 M1: regex backreference placeholder protection.
#   When a regex_rule line is pending translation we feed the pattern
#   itself to the LLM as ``original`` (so the model sees context). The
#   pattern often contains regex metacharacters whose semantics the LLM
#   may break by translating them as literal text — e.g. ``\d`` in
#   ``Item: (\d+)`` could come back as a Chinese-localised substring,
#   destroying the runtime regex when written into the rule's
#   replacement slot. The patterns below protect the most common regex
#   tokens via ``protect_placeholders`` so the LLM round-trips them
#   verbatim. The pattern is still preserved in ``write_back`` via
#   metadata (hard contract #13); placeholder protection only improves
#   the *replacement* quality.
UNITY_XUNITY_PROFILE = EngineProfile(
    name="unity_xunity",
    display_name="Unity (XUnity AutoTranslator)",
    placeholder_patterns=[
        # Round 56 M1: regex character-class shorthands (\d, \w, \s, \b)
        r"\\d",
        r"\\D",
        r"\\w",
        r"\\W",
        r"\\s",
        r"\\S",
        r"\\b",
        r"\\B",
        # Round 56 M1: regex backreferences (\1 .. \9)
        r"\\[1-9]",
    ],
    skip_line_patterns=[],
    prompt_addon_key="generic",
    supports_context=False,
    context_lines=0,
)

# 引擎 Profile 注册表
ENGINE_PROFILES: dict[str, EngineProfile] = {
    "renpy": RENPY_PROFILE,
    "rpgmaker_mv": RPGMAKER_MV_PROFILE,
    "rpgmaker_mz": RPGMAKER_MV_PROFILE,  # MZ 和 MV 格式完全一致
    "csv": CSV_PROFILE,
    "jsonl": CSV_PROFILE,  # JSONL 复用 CSV Profile
    "unity_xunity": UNITY_XUNITY_PROFILE,
}
