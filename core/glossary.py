#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语表管理 — 保证跨文件翻译一致性"""

from __future__ import annotations

import csv
import json
import logging
import re
import string
import threading
from pathlib import Path
from typing import Optional

from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)


MAX_MEMORY_ENTRIES = 10000  # 翻译记忆最大条目数

# Round 38: reject oversized glossary / RPG Maker data JSON inputs above
# 50 MB before ``json.loads``.  Applies to all four JSON readers in this
# module (Actors.json / System.json for RPGM auto-detect, the
# project-level UI terms table, and the main glossary file).  Legitimate
# glossary artefacts are typically a few KB to a few hundred KB (tens
# of thousands of (en, zh) pairs still fit easily); a 50 MB JSON is
# almost certainly malformed / attacker-crafted and worth rejecting
# before the full read.  Cap matches ``core/font_patch.py`` /
# ``core/translation_db.py`` / ``tools/merge_translations_v2.py``.
_MAX_GLOSSARY_JSON_SIZE = 50 * 1024 * 1024


def _json_file_too_large(path: Path) -> bool:
    """Round 38 M2 helper: return True if ``path`` exists but is above
    the ``_MAX_GLOSSARY_JSON_SIZE`` cap.  Logs a warning at the call site
    when True so callers can ``return``/``continue`` with context; the
    helper itself stays side-effect-free apart from that log line.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size > _MAX_GLOSSARY_JSON_SIZE:
        logger.warning(
            "[GLOSSARY] JSON file too large (%d bytes > %d-byte cap), "
            "skipping: %s", size, _MAX_GLOSSARY_JSON_SIZE, path,
        )
        return True
    return False


class Glossary:
    """术语表：从游戏文件中自动提取 + 手动维护"""

    def __init__(self):
        self._lock = threading.Lock()
        # 角色变量 → 显示名（从 define 提取）
        self.characters: dict[str, str] = {}
        # 通用术语 en → zh
        self.terms: dict[str, str] = {}
        # 翻译记忆：已翻译的 en → zh（相同原文保持翻译一致）
        self.memory: dict[str, str] = {}
        # 翻译记忆出现次数（信心度），仅 count >= 2 的才输出到 prompt
        self._memory_count: dict[str, int] = {}
        # 术语锁定：这些 key 出现在文本中时，必须使用 terms[key] 作为译名（应少而精）
        self.locked_terms: set[str] = set()
        # 禁翻片段：这些字符串在原文中出现时，译文必须保持同样的英文片段（大小写不敏感）
        self.no_translate: set[str] = set()

    def scan_game_directory(self, game_dir: str) -> None:
        """扫描游戏目录，提取角色定义和关键信息"""
        game_path = Path(game_dir)
        if not game_path.exists():
            logger.warning(f"游戏目录不存在: {game_dir}")
            return

        # 匹配 define xxx = Character("Name", ...) 和 DynamicCharacter
        char_re = re.compile(
            r'^\s*define\s+(\w+)\s*=\s*(?:Character|DynamicCharacter)\s*\(\s*["\']([^"\']+)["\']',
            re.MULTILINE
        )
        # 匹配 define config.name = "..."
        config_name_re = re.compile(
            r'^\s*define\s+config\.name\s*=\s*["\']([^"\']+)["\']',
            re.MULTILINE
        )        # 匹配 define config.version = "..."  (不翻译，但可用于报告)
        config_ver_re = re.compile(
            r'^\s*define\s+config\.version\s*=\s*["\']((?:[^"\']|\\.)*)["\'\)]',
            re.MULTILINE
        )
        for rpy in game_path.rglob('*.rpy'):
            # 跳过引擎自带文件
            try:
                rel_parts = rpy.relative_to(game_path).parts
            except ValueError:
                continue
            if rel_parts and rel_parts[0].lower() in ('renpy', 'lib', '__pycache__'):
                continue

            try:
                content = rpy.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                try:
                    content = rpy.read_text(encoding='latin-1')
                except (UnicodeDecodeError, OSError):
                    continue

            for m in char_re.finditer(content):
                var_name = m.group(1)
                display_name = m.group(2)
                self.characters[var_name] = display_name

            for m in config_name_re.finditer(content):
                self.terms['__game_name__'] = m.group(1)

            for m in config_ver_re.finditer(content):
                self.terms['__game_version__'] = m.group(1)

        if self.characters:
            logger.info(f"扫描到 {len(self.characters)} 个角色定义")
            # 将角色显示名也加入术语表，避免不同翻译
            for var, name in self.characters.items():
                if name and len(name) > 1 and name not in self.terms:
                    # 不自动翻译角色名 — 只做记录，由 prompt 中提示 AI
                    pass

    def scan_rpgmaker_database(self, game_dir) -> None:
        """从 RPG Maker data/ 目录提取角色名和系统术语。

        读取 Actors.json 提取角色名（name, nickname），
        读取 System.json 提取系统术语（terms.basic, terms.commands, terms.params）。
        """
        import json as _json
        game_dir = Path(game_dir)

        # 定位 data 目录（MV: www/data/, MZ: data/）
        data_dir = None
        for candidate in [game_dir / "www" / "data", game_dir / "data"]:
            if candidate.is_dir():
                data_dir = candidate
                break
        if data_dir is None:
            return

        # Actors.json → characters
        actors_path = data_dir / "Actors.json"
        if actors_path.is_file() and not _json_file_too_large(actors_path):
            try:
                # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
                # _json_file_too_large above is the path-based fast path; this
                # re-checks the size on the actual fd to defeat attacker-grow-
                # between-stat-and-open.  ``actors = None`` on failure so the
                # isinstance check below skips the loop without raising.
                with open(actors_path, encoding="utf-8") as f:
                    ok, fsize2 = check_fstat_size(f, _MAX_GLOSSARY_JSON_SIZE)
                    if not ok:
                        logger.warning(
                            "[GLOSSARY] Actors.json grew past cap after stat "
                            "(TOCTOU?): %d bytes > %d, skipping: %s",
                            fsize2, _MAX_GLOSSARY_JSON_SIZE, actors_path,
                        )
                        actors = None
                    else:
                        actors = _json.loads(f.read())
                if isinstance(actors, list):
                    with self._lock:
                        for actor in actors:
                            if not actor or not isinstance(actor, dict):
                                continue
                            name = (actor.get("name") or "").strip()
                            nickname = (actor.get("nickname") or "").strip()
                            if name and len(name) > 1:
                                self.characters[name.lower()] = name
                            if nickname and len(nickname) > 1 and nickname != name:
                                self.characters[nickname.lower()] = nickname
                    logger.debug(f"[RPGM] Actors.json: {len(self.characters)} 个角色名")
            except (OSError, _json.JSONDecodeError) as e:
                logger.debug(f"[RPGM] 读取 Actors.json 失败: {e}")

        # System.json → terms
        system_path = data_dir / "System.json"
        if system_path.is_file() and not _json_file_too_large(system_path):
            try:
                # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
                with open(system_path, encoding="utf-8") as f:
                    ok, fsize2 = check_fstat_size(f, _MAX_GLOSSARY_JSON_SIZE)
                    if not ok:
                        logger.warning(
                            "[GLOSSARY] System.json grew past cap after stat "
                            "(TOCTOU?): %d bytes > %d, skipping: %s",
                            fsize2, _MAX_GLOSSARY_JSON_SIZE, system_path,
                        )
                        system = {}
                    else:
                        system = _json.loads(f.read())
                terms = system.get("terms") or {}
                added = 0
                with self._lock:
                    for arr_name in ("basic", "commands", "params"):
                        arr = terms.get(arr_name) or []
                        if isinstance(arr, list):
                            for val in arr:
                                if val and isinstance(val, str) and val.strip() and len(val) > 1:
                                    key = val.strip()
                                    if key not in self.terms:
                                        self.terms[key] = ""  # 空译名，由 AI 翻译
                                        added += 1
                if added:
                    logger.debug(f"[RPGM] System.json: 新增 {added} 条系统术语")
            except (OSError, _json.JSONDecodeError) as e:
                logger.debug(f"[RPGM] 读取 System.json 失败: {e}")

    def load_dict(self, filepath: str) -> None:
        """加载外部词典（支持 CSV 和 JSONL 格式）

        CSV 格式：每行 "english,chinese" 或 "english\tchinese"
        JSONL 格式：每行 {"en": "...", "zh": "..."}
        """
        path = Path(filepath)
        if not path.exists():
            logger.warning(f"词典文件不存在: {filepath}")
            return

        count = 0
        suffix = path.suffix.lower()
        text = path.read_text(encoding='utf-8')

        if suffix == '.jsonl':
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    en = obj.get('en', obj.get('original', obj.get('source', '')))
                    zh = obj.get('zh', obj.get('translation', obj.get('target', '')))
                    if en and zh:
                        self.terms[en] = zh
                        count += 1
                except json.JSONDecodeError:
                    continue
        elif suffix in ('.csv', '.tsv', '.txt'):
            delimiter = '\t' if suffix == '.tsv' else ','
            for row in csv.reader(text.splitlines(), delimiter=delimiter):
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    # 跳过表头
                    if row[0].lower() in ('en', 'english', 'source', 'original'):
                        continue
                    self.terms[row[0].strip()] = row[1].strip()
                    count += 1
        else:
            logger.warning(f"不支持的词典格式: {suffix}")
            return

        logger.info(f"加载词典 {path.name}: {count} 条术语")

    def load_system_terms(self, filepath: str) -> None:
        """加载项目级系统 UI 术语（JSON 格式：{英文: 中文}）

        这些术语通常用于菜单、存读档、设置等固定文案，优先级高于自动记忆。
        """
        path = Path(filepath)
        if not path.exists():
            return
        # Round 38 M2: path-based size-cap fast path before read.
        if _json_file_too_large(path):
            return

        try:
            # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
            with open(path, encoding='utf-8') as f:
                ok, fsize2 = check_fstat_size(f, _MAX_GLOSSARY_JSON_SIZE)
                if not ok:
                    logger.warning(
                        "[GLOSSARY] system terms JSON grew past cap after stat "
                        "(TOCTOU?): %d bytes > %d, skipping: %s",
                        fsize2, _MAX_GLOSSARY_JSON_SIZE, path,
                    )
                    return
                data = json.loads(f.read())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            logger.warning(f"系统 UI 术语表解析失败: {filepath}")
            return

        added = 0
        if isinstance(data, dict):
            for en, zh in data.items():
                if isinstance(en, str) and isinstance(zh, str) and en.strip() and zh.strip():
                    self.terms[en] = zh
                    added += 1

        if added:
            logger.info(f"加载系统 UI 术语: {added} 条")

    def load(self, filepath: str) -> None:
        """加载术语表（JSON 格式）"""
        path = Path(filepath)
        if not path.exists():
            return
        # Round 38 M2: path-based size-cap fast path before read.
        if _json_file_too_large(path):
            return
        # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
        with open(path, encoding='utf-8') as f:
            ok, fsize2 = check_fstat_size(f, _MAX_GLOSSARY_JSON_SIZE)
            if not ok:
                logger.warning(
                    "[GLOSSARY] glossary JSON grew past cap after stat "
                    "(TOCTOU?): %d bytes > %d, skipping: %s",
                    fsize2, _MAX_GLOSSARY_JSON_SIZE, path,
                )
                return
            data = json.loads(f.read())
        self.characters.update(data.get('characters', {}))
        self.terms.update(data.get('terms', {}))
        self.memory.update(data.get('memory', {}))
        # 新字段向下兼容：旧版本 glossary.json 没有这些字段时，默认空集合
        self.locked_terms = set(data.get('locked_terms', []))
        self.no_translate = set(data.get('no_translate', []))
        logger.info(f"加载术语表: {len(self.characters)} 角色, "
                    f"{len(self.terms)} 术语, {len(self.memory)} 翻译记忆, "
                    f"{len(self.locked_terms)} 锁定术语, {len(self.no_translate)} 禁翻片段")

    def save(self, filepath: str) -> None:
        """保存术语表"""
        with self._lock:
            data = {
                'characters': self.characters,
                'terms': self.terms,
                'memory': self.memory,
                # locked_terms / no_translate 主要由高级用户少量维护，避免滥用
                'locked_terms': sorted(self.locked_terms),
                'no_translate': sorted(self.no_translate),
            }
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def update_from_translations(self, translations: list[dict]) -> None:
        """从翻译结果中更新翻译记忆（过滤低质量/太短的条目）"""
        with self._lock:
            for item in translations:
                original = item.get('original', '')
                zh = item.get('zh', '')
                if not original or not zh:
                    continue
                if len(original) <= 3:
                    continue
                if original == zh:
                    continue
                if original.strip().isdigit():
                    continue
                # 跳过纯标点符号
                if all(c in string.punctuation + string.whitespace for c in original):
                    continue
                # 跳过已在固定术语表中的条目（避免重复）
                if original in self.terms:
                    continue
                self.memory[original] = zh
                self._memory_count[original] = self._memory_count.get(original, 0) + 1

            # 超过上限时淘汰低频条目
            if len(self.memory) > MAX_MEMORY_ENTRIES:
                self._evict_low_frequency()

    def _evict_low_frequency(self) -> None:
        """淘汰低频翻译记忆条目，保留高频条目。必须在持有 _lock 时调用。"""
        target = MAX_MEMORY_ENTRIES * 3 // 4  # 淘汰到 75%
        # 按计数升序排列，淘汰低频
        sorted_keys = sorted(self._memory_count, key=lambda k: self._memory_count.get(k, 0))
        to_remove = len(self.memory) - target
        for key in sorted_keys[:to_remove]:
            self.memory.pop(key, None)
            self._memory_count.pop(key, None)

    def get_consistent_translation(self, original: str) -> str | None:
        """返回置信度 ≥2 的已有翻译，用于术语一致性检查。"""
        with self._lock:
            if original in self.memory and self._memory_count.get(original, 0) >= 2:
                return self.memory[original]
            return None

    def extract_terms_from_translations(self, translations: list[dict], min_freq: int = 3) -> dict[str, str]:
        """从翻译结果中自动提取高频专有名词（人名/地名），返回 {en: zh} 词典。

        策略：
        1. 从原文中提取首字母大写的英文单词（≥2 字母，排除句首/Ren'Py 关键字）
        2. 在对应译文中查找该词的翻译（通过位置对应或高频共现）
        3. 同一英文词 → 同一中文翻译出现 ≥ min_freq 次 → 加入术语
        """
        from collections import Counter

        # Ren'Py 关键字和常见英文词不应提取为术语
        _STOP_WORDS = {
            "The", "This", "That", "What", "When", "Where", "Which", "Who", "How",
            "And", "But", "For", "Not", "You", "Your", "Her", "His", "She", "Are",
            "Was", "Were", "Has", "Have", "Had", "Can", "Could", "Would", "Should",
            "Will", "Did", "Does", "May", "Just", "Then", "Than", "Very", "Only",
            "Also", "Some", "Any", "All", "Both", "Each", "Every", "Such", "Much",
            "Well", "Now", "Here", "There", "Why", "Yes", "Yeah", "Okay",
            "True", "False", "None", "Character", "DynamicCharacter",
            "Jump", "Call", "Show", "Hide", "Scene", "Menu", "Return",
            "Good", "Bad", "New", "Old", "Big", "Little", "Great",
        }
        _stop_lower = {w.lower() for w in _STOP_WORDS}

        # 匹配首字母大写词，含连字符人名（如 Mary-Jane）
        _word_re = re.compile(r'\b([A-Z][a-z]{1,15}(?:-[A-Z][a-z]{1,15})*)\b')

        def _zh_ngrams(text: str, min_len: int = 2, max_len: int = 5) -> list[str]:
            """从中文文本中提取所有 2~5 字的连续中文子串。"""
            runs = re.findall(r'[\u4e00-\u9fff]+', text)
            ngrams = []
            for run in runs:
                for n in range(min_len, min(max_len + 1, len(run) + 1)):
                    for i in range(len(run) - n + 1):
                        ngrams.append(run[i:i + n])
            return ngrams

        # 1. 收集：每个大写词出现时，对应译文中有哪些中文 n-gram
        word_zh_segments: dict[str, Counter] = {}

        for item in translations:
            original = item.get('original', '')
            zh = item.get('zh', '')
            if not original or not zh:
                continue
            words = set(_word_re.findall(original))
            ngrams = _zh_ngrams(zh)
            if not ngrams:
                continue
            for w in words:
                if w.lower() in _stop_lower:
                    continue
                if w in self.characters or w in self.terms:
                    continue
                if w not in word_zh_segments:
                    word_zh_segments[w] = Counter()
                for seg in ngrams:
                    word_zh_segments[w][seg] += 1

        # 2. 统计每个英文词出现了多少次（句子级频次）
        word_freq: Counter = Counter()
        for item in translations:
            original = item.get('original', '')
            if not original:
                continue
            for w in set(_word_re.findall(original)):
                if w.lower() not in _stop_lower and w not in self.characters and w not in self.terms:
                    word_freq[w] += 1

        # 3. 筛选：词频 ≥ min_freq，且最频繁的中文 n-gram 出现在 ≥ 50% 的句子中
        new_terms: dict[str, str] = {}
        for en, seg_counts in word_zh_segments.items():
            freq = word_freq.get(en, 0)
            if freq < min_freq:
                continue
            best_zh, best_count = seg_counts.most_common(1)[0]
            # best_count 是 n-gram 出现次数，freq 是句子数；best_count 应 ≥ freq*0.5
            if best_count < freq * 0.5:
                continue
            if len(best_zh) < 2:
                continue
            new_terms[en] = best_zh

        return new_terms

    def auto_add_terms(self, new_terms: dict[str, str]) -> int:
        """将自动提取的术语加入 terms（跳过已有的）。返回新增条数。"""
        added = 0
        with self._lock:
            for en, zh in new_terms.items():
                if en not in self.terms and en not in self.characters:
                    self.terms[en] = zh
                    added += 1
        if added:
            logger.info(f"[GLOSS] 自动提取 {added} 条术语")
        return added

    def to_prompt_text(self) -> str:
        """生成用于 prompt 的术语表文本"""
        with self._lock:
            return self._to_prompt_text_unlocked()

    def _to_prompt_text_unlocked(self) -> str:
        """内部实现（无锁）"""
        parts = []

        if self.characters:
            parts.append("### 角色变量（方括号内的变量名，绝对不能翻译）")
            for var, name in sorted(self.characters.items()):
                parts.append(f"- [{var}] = {name}")

        if self.terms:
            parts.append("\n### 固定术语")
            for en, zh in sorted(self.terms.items()):
                if not en.startswith('__'):
                    parts.append(f"- {en} → {zh}")

        # 锁定术语：这些 key 出现在原文中时，AI 必须使用指定译名（建议数量少而精）
        if self.locked_terms:
            parts.append("\n### 锁定术语（出现时必须严格使用指定译名）")
            for en in sorted(self.locked_terms):
                zh = self.terms.get(en, "")
                if not zh:
                    continue
                parts.append(f"- {en} → {zh}  （必须使用此译名，不得随意改动）")

        # 禁翻片段：这些英文片段在原文中出现时，必须保持英文不翻译
        if self.no_translate:
            parts.append("\n### 禁翻片段（出现时保持原文英文，不要翻译）")
            for s in sorted(self.no_translate):
                parts.append(f"- {s}")

        # 翻译记忆：分高置信度（必须遵循）和普通参考
        if self.memory:
            # 高置信度（count ≥ 3）：作为必须遵循的翻译约束
            mandatory = sorted(
                [(en, zh) for en, zh in self.memory.items()
                 if len(en) > 10 and self._memory_count.get(en, 1) >= 3],
                key=lambda x: self._memory_count.get(x[0], 1),
                reverse=True
            )
            if mandatory:
                parts.append("\n### 确定翻译（必须严格遵循，保持跨文件一致）")
                char_budget = 1500
                used = 0
                for en, zh in mandatory:
                    entry = f'- "{en}" → "{zh}"'
                    if used + len(entry) > char_budget:
                        break
                    parts.append(entry)
                    used += len(entry)

            # 普通参考（count ≥ 2 但 < 3）：作为翻译参考
            reference = sorted(
                [(en, zh) for en, zh in self.memory.items()
                 if len(en) > 10 and self._memory_count.get(en, 1) == 2],
                key=lambda x: len(x[0]),
                reverse=True
            )
            if reference:
                parts.append("\n### 翻译参考（请尽量保持一致）")
                char_budget = 1500
                used = 0
                for en, zh in reference:
                    entry = f'- "{en}" → "{zh}"'
                    if used + len(entry) > char_budget:
                        break
                    parts.append(entry)
                    used += len(entry)

        return '\n'.join(parts) if parts else ""
