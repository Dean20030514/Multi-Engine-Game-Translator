#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目级配置文件支持：减少命令行参数记忆成本。

配置文件查找顺序：
1. --config path/to/config.json（CLI 显式指定）
2. <game-dir>/renpy_translate.json
3. <game-dir>/../renpy_translate.json
4. 不存在则使用默认值

优先级：CLI 参数(非None) > 配置文件 > 默认值

安全设计：API Key 不直接写入配置文件，使用 api_key_env 或 api_key_file。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from safety.file_safety import check_fstat_size

logger = logging.getLogger("multi_engine_translator")

# Round 38: reject renpy_translate.json config files above 50 MB to bound
# memory before ``json.loads`` reads the file.  Legitimate config files
# are a few hundred bytes to a few KB (a dict of CLI flag defaults); a
# 50 MB-plus file is almost certainly a malformed or attacker-crafted
# artefact that shouldn't blow up the process heap before parsing.  Cap
# matches the value used in ``core/font_patch.py`` / ``core/translation_
# db.py`` / ``tools/merge_translations_v2.py`` for consistency.
_MAX_CONFIG_FILE_SIZE = 50 * 1024 * 1024

# 所有可配置参数的默认值
DEFAULTS: dict[str, Any] = {
    "provider": "xai",
    "model": "",
    "genre": "adult",
    "workers": 1,
    "rpm": 60,
    "rps": 5,
    "timeout": 180.0,
    "temperature": 0.1,
    "max_chunk_tokens": 4000,
    "max_response_tokens": 32768,
    "target_lang": "zh",
    "min_dialogue_density": 0.20,
    "output_dir": "output",
    "tl_lang": "chinese",
}

# 配置文件搜索名
CONFIG_FILENAME = "renpy_translate.json"

# 配置值校验 schema：type / choices / min / max
_CONFIG_SCHEMA: dict[str, dict[str, Any]] = {
    "provider": {"type": str, "choices": ["xai", "grok", "openai", "deepseek", "claude", "gemini"]},
    "model": {"type": str},
    "workers": {"type": int, "min": 1, "max": 64},
    "rpm": {"type": int, "min": 0},
    "rps": {"type": int, "min": 0},
    "timeout": {"type": (int, float), "min": 1},
    "temperature": {"type": (int, float), "min": 0, "max": 2},
    "max_chunk_tokens": {"type": int, "min": 100, "max": 200000},
    "max_response_tokens": {"type": int, "min": 100},
    "min_dialogue_density": {"type": (int, float), "min": 0, "max": 1},
    "genre": {"type": str, "choices": ["adult", "visual_novel", "rpg", "general"]},
    "target_lang": {"type": str},
    "api_key_env": {"type": str},
    "api_key_file": {"type": str},
    "tl_lang": {"type": str},
    "exclude": {"type": list},
    "dict": {"type": list},
    "use_connection_pool": {"type": bool},
    # Round 32 Commit 2: UI-button whitelist extension files
    "ui_button_whitelist": {"type": list},
    # Round 32 Commit 4: translations.json schema version selector
    "runtime_hook_schema": {"type": str, "choices": ["v1", "v2"]},
}


class Config:
    """配置管理器：配置文件 + CLI 参数合并。

    用法：
        config = Config(game_dir=Path(args.game_dir), cli_args=args)
        workers = config.get("workers")  # CLI > 配置文件 > 默认值
        api_key = config.resolve_api_key()
    """

    def __init__(self, game_dir: Path, cli_args: Any = None, config_path: str = ""):
        self._cli_args = cli_args
        self._file_config: dict[str, Any] = {}
        self._load_config_file(game_dir, config_path)

    def _load_config_file(self, game_dir: Path, explicit_path: str) -> None:
        """按优先级查找并加载配置文件。"""
        search_paths: list[Path] = []

        # 1. CLI 显式指定
        if explicit_path:
            search_paths.append(Path(explicit_path))

        # 2. 游戏目录下
        if game_dir:
            search_paths.append(game_dir / CONFIG_FILENAME)
            # 3. 游戏目录的父目录
            search_paths.append(game_dir.parent / CONFIG_FILENAME)

        for p in search_paths:
            if p.exists():
                # Round 38: size-cap before read to bound memory.  Skip + warn
                # oversized files the same way we handle parse errors.
                try:
                    file_size = p.stat().st_size
                except OSError:
                    file_size = 0
                if file_size > _MAX_CONFIG_FILE_SIZE:
                    logger.warning(
                        f"[CONFIG] 配置文件过大（{file_size} 字节 > "
                        f"{_MAX_CONFIG_FILE_SIZE} 字节上限），跳过: {p}"
                    )
                    continue
                try:
                    # Round 49 Step 2: TOCTOU defense via check_fstat_size.
                    with open(p, encoding="utf-8") as f:
                        ok, fsize2 = check_fstat_size(f, _MAX_CONFIG_FILE_SIZE)
                        if not ok:
                            logger.warning(
                                f"[CONFIG] 配置文件 stat 后增长到 {fsize2} 字节"
                                f"（疑似 TOCTOU 攻击），超过 "
                                f"{_MAX_CONFIG_FILE_SIZE} 字节上限，跳过: {p}"
                            )
                            continue
                        data = json.loads(f.read())
                    if isinstance(data, dict):
                        self._file_config = data
                        logger.info(f"[CONFIG] 已加载配置文件: {p}")
                        self.validate()
                        return
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"[CONFIG] 配置文件解析失败: {p}: {e}")

    def validate(self) -> list[str]:
        """校验 _file_config 中的值，返回警告列表（同时 log.warning）。

        不会拒绝加载，只记录警告，方便用户排查错误配置。
        """
        warnings: list[str] = []
        for key, value in self._file_config.items():
            # 未知键
            if key not in _CONFIG_SCHEMA and key not in DEFAULTS:
                msg = f"[CONFIG] 未知配置项: '{key}'"
                warnings.append(msg)
                logger.warning(msg)
                continue

            schema = _CONFIG_SCHEMA.get(key)
            if schema is None:
                # 在 DEFAULTS 中但不在 schema 中（如 output_dir），跳过
                continue

            # 类型检查
            expected_type = schema["type"]
            if not isinstance(value, expected_type):
                msg = (
                    f"[CONFIG] '{key}' 类型错误: 期望 {expected_type}, 实际 {type(value).__name__}"
                )
                warnings.append(msg)
                logger.warning(msg)
                continue  # 类型不对则跳过范围检查

            # choices 检查
            if "choices" in schema and value not in schema["choices"]:
                msg = f"[CONFIG] '{key}' 值无效: '{value}', 可选值: {schema['choices']}"
                warnings.append(msg)
                logger.warning(msg)

            # min / max 范围检查
            if "min" in schema and value < schema["min"]:
                msg = f"[CONFIG] '{key}' 值过小: {value}, 最小值: {schema['min']}"
                warnings.append(msg)
                logger.warning(msg)
            if "max" in schema and value > schema["max"]:
                msg = f"[CONFIG] '{key}' 值过大: {value}, 最大值: {schema['max']}"
                warnings.append(msg)
                logger.warning(msg)

        return warnings

    def get(self, key: str, default: Any = None) -> Any:
        """三层合并：CLI(非None) > 配置文件 > DEFAULTS > default。

        argparse 参数应使用 default=None，这样未传入的参数自然为 None，
        不会覆盖配置文件中的值。
        """
        # 1. CLI 参数（非 None 才使用）
        if self._cli_args is not None:
            cli_val = getattr(self._cli_args, key, None)
            if cli_val is not None:
                return cli_val

        # 2. 配置文件
        if key in self._file_config:
            return self._file_config[key]

        # 3. 默认值
        return DEFAULTS.get(key, default)

    def resolve_api_key(self) -> str:
        """解析 API Key：CLI > 环境变量（配置文件指定）> 密钥文件 > 空。

        配置文件中使用 api_key_env 或 api_key_file，不直接存储明文密钥。
        """
        # 1. CLI 直接传入
        if self._cli_args is not None:
            cli_key = getattr(self._cli_args, "api_key", None)
            if cli_key:
                return cli_key

        # 2. 配置文件中的环境变量名
        env_var = self._file_config.get("api_key_env", "")
        if env_var:
            key = os.environ.get(env_var, "")
            if key:
                return key

        # 3. 配置文件中的密钥文件路径
        key_file = self._file_config.get("api_key_file", "")
        if key_file:
            return self._read_api_key_file(key_file)

        return ""

    # 敏感系统目录（S-H-3：拒绝 api_key_file 指向这些路径，防配置文件诱导任意文件读取）
    _SENSITIVE_PREFIXES = [
        Path("C:/Windows"),
        Path("/etc"),
        Path("/proc"),
        Path("/sys"),
        Path("/root"),
    ]
    # api_key_file 大小上限（Key 通常 < 200 字节，8 KB 留足余量同时防止误读大文件）
    _MAX_API_KEY_FILE_BYTES = 8 * 1024

    @classmethod
    def _read_api_key_file(cls, key_file: str) -> str:
        """Safely read an API key from a file path given in the config.

        Rejects paths pointing at common sensitive system directories and
        caps file size at ``_MAX_API_KEY_FILE_BYTES`` to prevent a malicious
        config file from inducing arbitrary-file reads (S-H-3 hardening).
        Returns an empty string on any safety / I/O failure and logs a warning.
        """
        try:
            p = Path(key_file).expanduser().resolve(strict=False)
        except (OSError, ValueError) as e:
            logger.warning("[CONFIG] api_key_file 路径解析失败，跳过: %s", e)
            return ""

        for sp in cls._SENSITIVE_PREFIXES:
            try:
                p.relative_to(sp)
            except ValueError:
                continue
            logger.warning("[CONFIG] api_key_file 指向敏感系统目录 (%s)，已拒绝: %s", sp, p)
            return ""

        if not p.exists():
            return ""

        try:
            size = p.stat().st_size
        except OSError as e:
            logger.warning("[CONFIG] api_key_file 无法 stat: %s", e)
            return ""
        if size > cls._MAX_API_KEY_FILE_BYTES:
            logger.warning(
                "[CONFIG] api_key_file 大小 %d 字节超过 %d 上限，疑似误配置，拒绝",
                size,
                cls._MAX_API_KEY_FILE_BYTES,
            )
            return ""

        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning("[CONFIG] api_key_file 读取失败: %s", e)
            return ""

    @property
    def file_config(self) -> dict[str, Any]:
        """返回配置文件中的原始数据（只读）。"""
        return dict(self._file_config)

    def has_config_file(self) -> bool:
        """是否加载了配置文件。"""
        return bool(self._file_config)


# ============================================================
# Round 58 A1: shared CLI-args + config-file resolver
# ============================================================


def resolve_args_from_config(args, cfg: "Config") -> None:
    """Merge ``Config`` values into argparse ``Namespace`` in place.

    Round 58 A1 — extracted from inline code in ``main.py::main()`` so
    the GUI / one-click pipeline / future entry points share the same
    three-layer precedence (CLI > config file > defaults). Originally
    duplicated inline; this helper is the single source of truth.

    Three-layer precedence applied here:
        1. CLI args explicitly set (non-``None``) → kept
        2. CLI args missing (``None``) → filled from config file
        3. Both missing → argparse default / hardcoded constant

    Round 52 C4 BREAKING: ``target_lang`` is hardcoded to ``"zh"``
    regardless of any config-file value.

    Note: ``args.game_dir`` is *not* touched here — callers are
    expected to have already sanitized it (r57 S2
    ``_sanitize_user_path``) and resolved any "game/" subdir
    auto-detection before invoking this helper.

    Note: API key resolution has its own multi-source precedence
    (CLI > ``_RENPY_TRANSLATOR_CHILD_API_KEY`` env > config
    ``api_key_env`` / ``api_key_file`` / ``api_key``) and is not
    handled here — see :func:`Config.resolve_api_key` for that
    chain.

    See ``docs/REFERENCE.md`` §7a for the documented precedence.
    """
    # Scalar config fields with defaults
    args.output_dir = cfg.get("output_dir", "output")
    args.provider = cfg.get("provider", "xai")
    args.model = cfg.get("model", "")
    args.genre = cfg.get("genre", "adult")
    args.workers = cfg.get("workers", 1)
    args.file_workers = cfg.get("file_workers", 1)
    args.rpm = cfg.get("rpm", 60)
    args.rps = cfg.get("rps", 5)
    args.timeout = cfg.get("timeout", 180.0)
    args.temperature = cfg.get("temperature", 0.1)
    args.max_chunk_tokens = cfg.get("max_chunk_tokens", 4000)
    args.max_response_tokens = cfg.get("max_response_tokens", 32768)

    # Round 52 C4 BREAKING: target_lang fixed to "zh".
    args.target_lang = "zh"

    args.min_dialogue_density = cfg.get("min_dialogue_density", 0.20)
    args.tl_lang = cfg.get("tl_lang", "chinese")

    # List-valued config fields — only fill if CLI didn't provide.
    if args.dict is None:
        args.dict = cfg.get("dict", []) or []
    if args.exclude is None:
        args.exclude = cfg.get("exclude", []) or []
    if getattr(args, "ui_button_whitelist", None) is None:
        args.ui_button_whitelist = cfg.get("ui_button_whitelist", []) or []
