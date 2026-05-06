#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPG Maker MV/MZ 引擎：JSON 数据文件的提取与回写。

MV 和 MZ 的 JSON 格式完全一致，唯一区别是目录结构（MV 多一层 www/）。
第一版不处理 Code 356 插件指令和 JS 硬编码文本。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from engines.engine_base import EngineBase, EngineProfile, TranslatableUnit, RPGMAKER_MV_PROFILE
from safety.file_safety import check_fstat_size

logger = logging.getLogger("multi_engine_translator")

# Round 42 M2 phase-3: 50 MB cap on every RPG Maker data JSON read.
# Game-supplied JSON files (Map###.json / System.json / CommonEvents.json
# / Troops.json / the _DB_FIELDS set) are operator-controlled input — a
# pathologically huge or attacker-crafted file would OOM the extraction
# loop.  Legitimate RPG Maker MV/MZ data files are in the KB-low-MB
# range; 50 MB matches the cap chosen across the other user-facing JSON
# loaders (font_patch / translation_db / merge_v2 / translation_editor
# / config / glossary / review_generator / analyze_writeback / gate).
_MAX_RPGM_JSON_SIZE = 50 * 1024 * 1024

# ============================================================
# 数据库字段配置表
# ============================================================

_DB_FIELDS: dict[str, list[str]] = {
    "Actors.json": ["name", "nickname", "profile"],
    "Armors.json": ["name", "description"],
    "Weapons.json": ["name", "description"],
    "Items.json": ["name", "description"],
    "Skills.json": ["name", "description"],
    "States.json": ["name", "message1", "message2", "message3", "message4"],
    "Enemies.json": ["name"],
    "Classes.json": ["name"],
}

# System.json 中的简单字符串字段
_SYSTEM_STRING_FIELDS = ["gameTitle", "currencyUnit"]

# System.json 中的数组字段（每个元素可能是字符串或 null）
_SYSTEM_ARRAY_FIELDS = [
    "armorTypes", "elements", "equipTypes", "skillTypes", "weaponTypes",
]

class RPGMakerMVEngine(EngineBase):
    """RPG Maker MV/MZ 引擎。"""

    def _default_profile(self) -> EngineProfile:
        return RPGMAKER_MV_PROFILE

    def detect(self, game_dir: Path) -> bool:
        """检查是否为 RPG Maker MV/MZ 项目。"""
        return (self._find_data_dir(game_dir) is not None)

    # ============================================================
    # 目录定位
    # ============================================================

    @staticmethod
    def _find_data_dir(game_dir: Path) -> Path | None:
        """定位 data/ 目录（MV: www/data/, MZ: data/）。"""
        for candidate in [game_dir / "www" / "data", game_dir / "data"]:
            if candidate.is_dir() and (candidate / "System.json").is_file():
                return candidate
        return None

    # ============================================================
    # 提取
    # ============================================================

    def extract_texts(self, game_dir: Path, **kwargs) -> list[TranslatableUnit]:
        """提取所有可翻译文本。"""
        game_dir = Path(game_dir)
        data_dir = self._find_data_dir(game_dir)
        if data_dir is None:
            logger.error("[RPGM] 找不到 data/ 目录")
            return []

        units: list[TranslatableUnit] = []

        for json_path in sorted(data_dir.glob("*.json")):
            filename = json_path.name
            rel = str(json_path.relative_to(game_dir))

            try:
                json_size = json_path.stat().st_size
            except OSError:
                json_size = 0
            if json_size > _MAX_RPGM_JSON_SIZE:
                logger.warning(
                    f"[RPGM] 跳过 {filename}: 文件 {json_size} 字节 "
                    f"超过 {_MAX_RPGM_JSON_SIZE} 字节上限"
                )
                continue

            try:
                # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
                with open(json_path, encoding="utf-8") as f:
                    ok, fsize2 = check_fstat_size(f, _MAX_RPGM_JSON_SIZE)
                    if not ok:
                        logger.warning(
                            f"[RPGM] 跳过 {filename}: 文件 stat 后增长到 {fsize2} 字节"
                            f"（疑似 TOCTOU 攻击），超过 {_MAX_RPGM_JSON_SIZE} 字节上限"
                        )
                        continue
                    data = json.loads(f.read())
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"[RPGM] 跳过 {filename}: {e}")
                continue

            if filename.startswith("Map") and filename != "MapInfos.json":
                units.extend(self._extract_map(data, rel))
            elif filename == "CommonEvents.json":
                units.extend(self._extract_common_events(data, rel))
            elif filename == "Troops.json":
                units.extend(self._extract_troops(data, rel))
            elif filename == "System.json":
                units.extend(self._extract_system(data, rel))
            elif filename in _DB_FIELDS:
                units.extend(self._extract_database(data, rel, _DB_FIELDS[filename]))

        logger.info(f"[RPGM] 提取 {len(units)} 条文本")
        return units

    # ============================================================
    # Map 提取
    # ============================================================

    def _extract_map(self, data: dict, rel: str) -> list[TranslatableUnit]:
        """解析 MapXXX.json。"""
        units: list[TranslatableUnit] = []
        # displayName
        dn = data.get("displayName", "")
        if dn and isinstance(dn, str) and dn.strip():
            units.append(TranslatableUnit(
                id=f"{rel}:displayName", original=dn.strip(), file_path=rel,
                metadata={"type": "field", "json_path": "displayName"},
            ))
        # events
        events = data.get("events") or []
        for ei, event in enumerate(events):
            if not event or not isinstance(event, dict):
                continue
            pages = event.get("pages") or []
            for pi, page in enumerate(pages):
                if not page or not isinstance(page, dict):
                    continue
                cmd_list = page.get("list") or []
                prefix = f"events[{ei}].pages[{pi}].list"
                units.extend(self._extract_event_commands(cmd_list, rel, prefix))
        return units

    # ============================================================
    # CommonEvents / Troops 提取
    # ============================================================

    def _extract_common_events(self, data: list, rel: str) -> list[TranslatableUnit]:
        """解析 CommonEvents.json。"""
        units: list[TranslatableUnit] = []
        if not isinstance(data, list):
            return units
        for ei, event in enumerate(data):
            if not event or not isinstance(event, dict):
                continue
            cmd_list = event.get("list") or []
            prefix = f"[{ei}].list"
            units.extend(self._extract_event_commands(cmd_list, rel, prefix))
        return units

    def _extract_troops(self, data: list, rel: str) -> list[TranslatableUnit]:
        """解析 Troops.json。"""
        units: list[TranslatableUnit] = []
        if not isinstance(data, list):
            return units
        for ti, troop in enumerate(data):
            if not troop or not isinstance(troop, dict):
                continue
            # troop name
            name = troop.get("name", "")
            if name and isinstance(name, str) and name.strip():
                units.append(TranslatableUnit(
                    id=f"{rel}:[{ti}].name", original=name.strip(), file_path=rel,
                    metadata={"type": "field", "json_path": f"[{ti}].name"},
                ))
            # troop pages → event commands
            pages = troop.get("pages") or []
            for pi, page in enumerate(pages):
                if not page or not isinstance(page, dict):
                    continue
                cmd_list = page.get("list") or []
                prefix = f"[{ti}].pages[{pi}].list"
                units.extend(self._extract_event_commands(cmd_list, rel, prefix))
        return units

    # ============================================================
    # 事件指令解析（核心）
    # ============================================================

    def _extract_event_commands(self, cmd_list: list, rel: str,
                                prefix: str) -> list[TranslatableUnit]:
        """遍历 command list，按 code 分发提取。处理 401/405 连续合并。"""
        units: list[TranslatableUnit] = []
        i = 0
        while i < len(cmd_list):
            cmd = cmd_list[i]
            if not isinstance(cmd, dict):
                i += 1
                continue
            code = cmd.get("code", 0)
            params = cmd.get("parameters") or []

            # 连续 401（Show Text）合并
            if code == 401:
                start_idx = i
                lines = []
                while i < len(cmd_list):
                    c = cmd_list[i]
                    if not isinstance(c, dict) or c.get("code") != 401:
                        break
                    p = c.get("parameters") or []
                    lines.append(p[0] if p and isinstance(p[0], str) else "")
                    i += 1
                text = "\n".join(lines)
                if text.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:{prefix}[{start_idx}]",
                        original=text, file_path=rel,
                        metadata={
                            "type": "dialogue", "code": 401,
                            "start_idx": start_idx, "line_count": len(lines),
                            "json_prefix": prefix,
                        },
                    ))
                continue

            # 连续 405（Show Scrolling Text）合并
            if code == 405:
                start_idx = i
                lines = []
                while i < len(cmd_list):
                    c = cmd_list[i]
                    if not isinstance(c, dict) or c.get("code") != 405:
                        break
                    p = c.get("parameters") or []
                    lines.append(p[0] if p and isinstance(p[0], str) else "")
                    i += 1
                text = "\n".join(lines)
                if text.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:{prefix}[{start_idx}]",
                        original=text, file_path=rel,
                        metadata={
                            "type": "dialogue", "code": 405,
                            "start_idx": start_idx, "line_count": len(lines),
                            "json_prefix": prefix,
                        },
                    ))
                continue

            # 102（Show Choices）
            if code == 102 and params:
                choices = params[0] if isinstance(params[0], list) else []
                for ci, choice_text in enumerate(choices):
                    if choice_text and isinstance(choice_text, str) and choice_text.strip():
                        units.append(TranslatableUnit(
                            id=f"{rel}:{prefix}[{i}].choices[{ci}]",
                            original=choice_text.strip(), file_path=rel,
                            metadata={
                                "type": "choice", "cmd_idx": i,
                                "choice_idx": ci, "json_prefix": prefix,
                            },
                        ))

            # 402（When [Choice]）
            elif code == 402 and len(params) >= 2:
                text = params[1]
                if text and isinstance(text, str) and text.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:{prefix}[{i}].when",
                        original=text.strip(), file_path=rel,
                        metadata={
                            "type": "choice_when", "cmd_idx": i,
                            "json_prefix": prefix,
                        },
                    ))

            # 320（Change Name）/ 324（Change Nickname）
            elif code in (320, 324) and len(params) >= 2:
                text = params[1]
                if text and isinstance(text, str) and text.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:{prefix}[{i}].name",
                        original=text.strip(), file_path=rel,
                        metadata={
                            "type": "name_change", "cmd_idx": i,
                            "param_idx": 1, "json_prefix": prefix,
                        },
                    ))

            i += 1
        return units

    # ============================================================
    # 数据库提取
    # ============================================================

    def _extract_database(self, data: list, rel: str,
                          fields: list[str]) -> list[TranslatableUnit]:
        """通用数据库文件提取（Actors/Items/Skills 等）。"""
        units: list[TranslatableUnit] = []
        if not isinstance(data, list):
            return units
        for idx, obj in enumerate(data):
            if not obj or not isinstance(obj, dict):
                continue
            for field in fields:
                val = obj.get(field, "")
                if val and isinstance(val, str) and val.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:[{idx}].{field}",
                        original=val.strip(), file_path=rel,
                        metadata={
                            "type": "database",
                            "json_path": f"[{idx}].{field}",
                        },
                    ))
        return units

    # ============================================================
    # System.json 提取
    # ============================================================

    def _extract_system(self, data: dict, rel: str) -> list[TranslatableUnit]:
        """System.json 专属提取。"""
        units: list[TranslatableUnit] = []

        # 简单字符串字段
        for field in _SYSTEM_STRING_FIELDS:
            val = data.get(field, "")
            if val and isinstance(val, str) and val.strip():
                units.append(TranslatableUnit(
                    id=f"{rel}:{field}", original=val.strip(), file_path=rel,
                    metadata={"type": "field", "json_path": field},
                ))

        # 数组字段
        for field in _SYSTEM_ARRAY_FIELDS:
            arr = data.get(field) or []
            if not isinstance(arr, list):
                continue
            for i, val in enumerate(arr):
                if val and isinstance(val, str) and val.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:{field}[{i}]", original=val.strip(), file_path=rel,
                        metadata={"type": "field", "json_path": f"{field}[{i}]"},
                    ))

        # terms 嵌套
        terms = data.get("terms") or {}
        if not isinstance(terms, dict):
            return units

        # terms.messages (dict)
        messages = terms.get("messages") or {}
        if isinstance(messages, dict):
            for key, val in messages.items():
                if val and isinstance(val, str) and val.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:terms.messages.{key}",
                        original=val.strip(), file_path=rel,
                        metadata={"type": "field", "json_path": f"terms.messages.{key}"},
                    ))

        # terms.commands / terms.params / terms.basic (arrays)
        for arr_name in ("commands", "params", "basic"):
            arr = terms.get(arr_name) or []
            if not isinstance(arr, list):
                continue
            for i, val in enumerate(arr):
                if val and isinstance(val, str) and val.strip():
                    units.append(TranslatableUnit(
                        id=f"{rel}:terms.{arr_name}[{i}]",
                        original=val.strip(), file_path=rel,
                        metadata={"type": "field", "json_path": f"terms.{arr_name}[{i}]"},
                    ))

        return units

    # ============================================================
    # 回写
    # ============================================================

    def write_back(self, game_dir: Path, units: list[TranslatableUnit],
                   output_dir: Path, **kwargs) -> int:
        """将翻译结果写回 JSON 文件。"""
        game_dir = Path(game_dir)
        output_dir = Path(output_dir)
        data_dir = self._find_data_dir(game_dir)
        if data_dir is None:
            logger.error("[RPGM] write_back: 找不到 data/ 目录")
            return 0

        # 按 file_path 分组
        by_file: dict[str, list[TranslatableUnit]] = {}
        for u in units:
            if u.status == "translated" and u.translation:
                by_file.setdefault(u.file_path, []).append(u)

        written = 0
        for rel_path, file_units in by_file.items():
            src_path = game_dir / rel_path
            if not src_path.is_file():
                logger.warning(f"[RPGM] 源文件不存在: {src_path}")
                continue

            try:
                src_size = src_path.stat().st_size
            except OSError:
                src_size = 0
            if src_size > _MAX_RPGM_JSON_SIZE:
                logger.warning(
                    f"[RPGM] 回写跳过 {rel_path}: 文件 {src_size} 字节 "
                    f"超过 {_MAX_RPGM_JSON_SIZE} 字节上限"
                )
                continue

            try:
                # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
                with open(src_path, encoding="utf-8") as f:
                    ok, fsize2 = check_fstat_size(f, _MAX_RPGM_JSON_SIZE)
                    if not ok:
                        logger.warning(
                            f"[RPGM] 回写跳过 {rel_path}: 文件 stat 后增长到 {fsize2} 字节"
                            f"（疑似 TOCTOU 攻击），超过 {_MAX_RPGM_JSON_SIZE} 字节上限"
                        )
                        continue
                    data = json.loads(f.read())
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"[RPGM] 读取失败 {rel_path}: {e}")
                continue

            file_written = 0
            for u in file_units:
                try:
                    if self._patch_unit(data, u):
                        file_written += 1
                except Exception as e:
                    logger.debug(f"[RPGM] 回写失败 {u.id}: {e}")

            if file_written > 0:
                # 确定输出路径
                out_path = output_dir / rel_path
                out_path.parent.mkdir(parents=True, exist_ok=True)

                # .bak 备份
                if out_path.exists():
                    bak = out_path.with_suffix(out_path.suffix + ".bak")
                    if not bak.exists():
                        shutil.copy2(out_path, bak)

                self._write_json(data, out_path)
                written += file_written

        logger.info(f"[RPGM] 写入 {written} 条翻译")
        return written

    def _patch_unit(self, data: Any, unit: TranslatableUnit) -> bool:
        """回写单条翻译到 JSON 数据。"""
        meta = unit.metadata
        utype = meta.get("type", "")

        if utype == "dialogue":
            return self._patch_dialogue(data, unit)
        elif utype == "choice":
            return self._patch_choice(data, unit)
        elif utype == "choice_when":
            return self._patch_choice_when(data, unit)
        elif utype == "name_change":
            return self._patch_name_change(data, unit)
        elif utype in ("field", "database"):
            json_path = meta.get("json_path", "")
            if json_path:
                return self._patch_by_json_path(data, json_path, unit.translation)
        return False

    def _patch_dialogue(self, data: Any, unit: TranslatableUnit) -> bool:
        """回写对话块（401/405 连续指令）。"""
        meta = unit.metadata
        prefix = meta.get("json_prefix", "")
        start_idx = meta.get("start_idx", 0)
        line_count = meta.get("line_count", 1)
        code = meta.get("code", 401)

        # 导航到 command list
        cmd_list = self._navigate_to_node(data, prefix)
        if not isinstance(cmd_list, list):
            return False

        # 拆分翻译
        trans_lines = unit.translation.split("\n")

        for li in range(line_count):
            idx = start_idx + li
            if idx >= len(cmd_list):
                break
            cmd = cmd_list[idx]
            if not isinstance(cmd, dict) or cmd.get("code") != code:
                break
            params = cmd.get("parameters") or []
            if params:
                if li < len(trans_lines):
                    params[0] = trans_lines[li]
                else:
                    params[0] = ""  # 翻译行数不足，填空
        return True

    def _patch_choice(self, data: Any, unit: TranslatableUnit) -> bool:
        """回写选项文本。"""
        meta = unit.metadata
        prefix = meta.get("json_prefix", "")
        cmd_idx = meta.get("cmd_idx", 0)
        choice_idx = meta.get("choice_idx", 0)

        cmd_list = self._navigate_to_node(data, prefix)
        if not isinstance(cmd_list, list) or cmd_idx >= len(cmd_list):
            return False
        cmd = cmd_list[cmd_idx]
        params = cmd.get("parameters") or []
        if params and isinstance(params[0], list) and choice_idx < len(params[0]):
            params[0][choice_idx] = unit.translation
            return True
        return False

    def _patch_choice_when(self, data: Any, unit: TranslatableUnit) -> bool:
        """回写 When [Choice] 文本。"""
        meta = unit.metadata
        prefix = meta.get("json_prefix", "")
        cmd_idx = meta.get("cmd_idx", 0)

        cmd_list = self._navigate_to_node(data, prefix)
        if not isinstance(cmd_list, list) or cmd_idx >= len(cmd_list):
            return False
        cmd = cmd_list[cmd_idx]
        params = cmd.get("parameters") or []
        if len(params) >= 2:
            params[1] = unit.translation
            return True
        return False

    def _patch_name_change(self, data: Any, unit: TranslatableUnit) -> bool:
        """回写 Change Name / Change Nickname。"""
        meta = unit.metadata
        prefix = meta.get("json_prefix", "")
        cmd_idx = meta.get("cmd_idx", 0)
        param_idx = meta.get("param_idx", 1)

        cmd_list = self._navigate_to_node(data, prefix)
        if not isinstance(cmd_list, list) or cmd_idx >= len(cmd_list):
            return False
        cmd = cmd_list[cmd_idx]
        params = cmd.get("parameters") or []
        if len(params) > param_idx:
            params[param_idx] = unit.translation
            return True
        return False

    # ============================================================
    # JSON path 导航
    # ============================================================

    @staticmethod
    def _navigate_to_node(data: Any, path: str) -> Any:
        """按 JSON path 导航到节点。支持 [n] 索引和 .key 混合。

        示例路径: "events[3].pages[0].list", "[1].name", "terms.messages"
        """
        if not path:
            return data
        node = data
        # 分割路径为 token
        parts: list[str] = []
        current = ""
        for ch in path:
            if ch == ".":
                if current:
                    parts.append(current)
                current = ""
            elif ch == "[":
                if current:
                    parts.append(current)
                current = "["
            elif ch == "]":
                current += "]"
                parts.append(current)
                current = ""
            else:
                current += ch
        if current:
            parts.append(current)

        for part in parts:
            if part.startswith("[") and part.endswith("]"):
                # 数组索引
                try:
                    idx = int(part[1:-1])
                    node = node[idx]
                except (ValueError, IndexError, TypeError):
                    return None
            else:
                # 字典 key
                if isinstance(node, dict):
                    node = node.get(part)
                else:
                    return None
            if node is None:
                return None
        return node

    @staticmethod
    def _patch_by_json_path(data: Any, path: str, value: Any) -> bool:
        """按 JSON path 导航并赋值。"""
        if not path:
            return False
        # 分离最后一级和前缀路径
        # 找到最后一个 . 或 [ 的位置
        last_dot = path.rfind(".")
        last_bracket = path.rfind("[")
        split_pos = max(last_dot, last_bracket)

        if split_pos <= 0:
            # 顶层字段
            if isinstance(data, dict):
                data[path] = value
                return True
            return False

        if path[split_pos] == ".":
            parent_path = path[:split_pos]
            key = path[split_pos + 1:]
            parent = RPGMakerMVEngine._navigate_to_node(data, parent_path)
            if isinstance(parent, dict):
                parent[key] = value
                return True
        else:
            # [n] 索引
            end = path.find("]", split_pos)
            parent_path = path[:split_pos]
            try:
                idx = int(path[split_pos + 1:end])
            except ValueError:
                return False
            parent = RPGMakerMVEngine._navigate_to_node(data, parent_path)
            if isinstance(parent, list) and 0 <= idx < len(parent):
                parent[idx] = value
                return True
        return False

    @staticmethod
    def _write_json(data: Any, out_path: Path) -> None:
        """以紧凑格式写出 JSON（与 RPG Maker 原始格式一致）。"""
        out_path.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    # ============================================================
    # 后处理
    # ============================================================

    def post_process(self, game_dir: Path, output_dir: Path) -> None:
        """输出字体安装提示。"""
        logger.info(
            "\n[RPGM] 翻译完成。如需显示中文，请手动安装中文字体：\n"
            "  1. 将中文字体（如 NotoSansSC-Regular.ttf）放入 www/fonts/ 或 fonts/ 目录\n"
            "  2. 修改 css/game.css 或 js/plugins.js 中的字体配置\n"
            "  3. 参考: https://forums.rpgmakerweb.com/index.php?threads/how-to-change-font.48735/"
        )
