#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV/JSONL 通用格式引擎：读写 CSV、TSV、JSONL、JSON 数组。

让用户能用任何外部工具（Translator++、VNTextPatch、GARbro 等）提取文本，
导出为 CSV/JSONL，用本工具做 AI 翻译 + 质量校验，再用原工具回灌。
零依赖（csv 和 json 都是标准库）。
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from safety.file_safety import check_fstat_size
from engines.engine_base import EngineBase, EngineProfile, TranslatableUnit, CSV_PROFILE

logger = logging.getLogger("multi_engine_translator")

# Round 44 audit-tail: 50 MB cap on operator-supplied CSV/JSONL/JSON
# files.  Missed by r37-r43 M2 phases which focused on `.json` loaders;
# the CSV engine's text-mode readers (`_extract_jsonl` /
# `_extract_json_or_jsonl`) consume the whole file into memory before
# parse, so a 1 GB misconfigured or adversarial input would OOM the
# host before the dispatcher even decides which format to try.  Matches
# the 50 MB cap used across r37-r43 user-facing loaders.
_MAX_CSV_JSON_SIZE = 50 * 1024 * 1024

# ============================================================
# 列名别名集合（大小写不敏感匹配）
# ============================================================

_ORIGINAL_ALIASES = {"original", "source", "text", "en", "english", "src"}
_ID_ALIASES = {"id", "key", "identifier", "index"}
_SPEAKER_ALIASES = {"speaker", "character", "char", "name"}
_CONTEXT_ALIASES = {"context", "note", "comment", "description"}
_FILE_ALIASES = {"file", "filename", "path", "source_file"}

# 支持的文件扩展名
_CSV_EXTENSIONS = {".csv", ".tsv"}
_JSON_EXTENSIONS = {".json", ".jsonl"}
_ALL_EXTENSIONS = _CSV_EXTENSIONS | _JSON_EXTENSIONS


def _find_column(headers: list[str], aliases: set[str]) -> str | None:
    """在 CSV 表头中按别名集合找到实际列名（大小写不敏感）。"""
    for h in headers:
        if h.strip().lower() in aliases:
            return h
    return None


def _resolve_field(obj: dict, aliases: set[str]) -> str:
    """在 JSON 对象中按别名集合找到字段值。"""
    for key, val in obj.items():
        if key.strip().lower() in aliases and val and isinstance(val, str):
            return val.strip()
    return ""


class CSVEngine(EngineBase):
    """CSV/JSONL 通用格式引擎。"""

    def _default_profile(self) -> EngineProfile:
        return CSV_PROFILE

    def detect(self, game_dir: Path) -> bool:
        """CSV 不自动检测，必须通过 --engine csv 手动指定。"""
        return False

    def extract_texts(self, game_dir: Path, **kwargs) -> list[TranslatableUnit]:
        """提取 CSV/JSONL/JSON 文件中的可翻译文本。

        game_dir 可以是单文件或目录：
        - 单文件：按扩展名分发
        - 目录：扫描所有支持的文件
        """
        game_dir = Path(game_dir)
        units: list[TranslatableUnit] = []

        if game_dir.is_file():
            units.extend(self._extract_file(game_dir))
        elif game_dir.is_dir():
            for f in sorted(game_dir.rglob("*")):
                if f.is_file() and f.suffix.lower() in _ALL_EXTENSIONS:
                    units.extend(self._extract_file(f))
        else:
            logger.error(f"[CSV] 路径不存在: {game_dir}")

        logger.info(f"[CSV] 提取 {len(units)} 条文本")
        return units

    def write_back(
        self, game_dir: Path, units: list[TranslatableUnit], output_dir: Path, **kwargs
    ) -> int:
        """将翻译结果写出为新文件（不修改输入文件）。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        translated = [u for u in units if u.status == "translated" and u.translation]
        if not translated:
            return 0

        target_lang = kwargs.get("target_lang", "zh")

        # 按源格式分组
        csv_units = [u for u in translated if u.metadata.get("source_format") in ("csv", "tsv")]
        jsonl_units = [
            u for u in translated if u.metadata.get("source_format") in ("jsonl", "json")
        ]

        written = 0
        if csv_units:
            written += self._write_csv(csv_units, output_dir, target_lang)
        if jsonl_units:
            written += self._write_jsonl(jsonl_units, output_dir, target_lang)

        # 如果没有明确分类，默认按 CSV 输出
        other = [
            u
            for u in translated
            if u.metadata.get("source_format") not in ("csv", "tsv", "jsonl", "json")
        ]
        if other:
            written += self._write_csv(other, output_dir, target_lang)

        return written

    # ============================================================
    # 文件提取分发
    # ============================================================

    def _extract_file(self, filepath: Path) -> list[TranslatableUnit]:
        """按扩展名分发到对应的解析方法。"""
        ext = filepath.suffix.lower()
        rel = filepath.name
        try:
            if ext == ".csv":
                return self._extract_csv(filepath, delimiter=",")
            elif ext == ".tsv":
                return self._extract_csv(filepath, delimiter="\t")
            elif ext == ".jsonl":
                return self._extract_jsonl(filepath)
            elif ext == ".json":
                return self._extract_json_or_jsonl(filepath)
        except csv.Error as e:
            # Round 48 Step 1 (L1 informational): explicit catch for
            # csv.DictReader errors before falling through to the
            # generic Exception handler.  Most common trigger: a
            # TOCTOU truncation between Path.stat() and open() leaves
            # the file mid-row, so DictReader raises csv.Error on the
            # malformed line.  Separating CSV-specific errors from
            # generic IO failures gives clearer operator-facing logs
            # ("CSV 解析错误" vs "解析失败").  Closes the round 47
            # audit's 1 LOW informational gap.
            logger.error(f"[CSV] CSV 解析错误 {rel}: {e}")
        except Exception as e:
            logger.error(f"[CSV] 解析失败 {rel}: {e}")
        return []

    # ============================================================
    # CSV/TSV 提取
    # ============================================================

    def _extract_csv(self, filepath: Path, delimiter: str = ",") -> list[TranslatableUnit]:
        """读 CSV/TSV 文件，通过列名别名解析构建 TranslatableUnit。"""
        units: list[TranslatableUnit] = []
        rel = filepath.name
        source_format = "tsv" if delimiter == "\t" else "csv"

        # Round 46 Step 4 (G1): size cap matching _extract_jsonl /
        # _extract_json_or_jsonl siblings.  ``csv.DictReader`` streams
        # the file but a multi-GB CSV with millions of small rows would
        # still consume large memory in the accumulated ``units`` list.
        # 50 MB+ is almost certainly adversarial or misconfigured input.
        # The r37-r44 size-cap sweep covered .jsonl / .json but missed
        # .csv / .tsv; closed by the round 45 audit's optional MEDIUM.
        # Round 46 Step 5 (security audit notes): the stat() check has
        # known TOCTOU race + fail-open on stat OSError.  Both were
        # ACCEPTABLE per the r37-r44 design philosophy (operator trust
        # model + streaming reduces realistic blast radius to ~150 MB
        # peak even if cap is bypassed).  Round 47 Step 2 (D3) added
        # stat-after-open via os.fstat() to MITIGATE the TOCTOU race
        # within the with-open block — see the post-open check below.
        # Bypass vector status (4 total): symlink MITIGATED (stat
        # follows symlinks) / OSError fail-open ACCEPTABLE (intended
        # design) / units accumulation ACCEPTABLE (legitimate CSVs <<
        # 50 MB) / TOCTOU MITIGATED (r47 stat-after-open).
        try:
            fsize = filepath.stat().st_size
        except OSError:
            fsize = 0
        if fsize > _MAX_CSV_JSON_SIZE:
            logger.warning(
                f"[CSV] 跳过 {rel}: 文件 {fsize} 字节 超过 {_MAX_CSV_JSON_SIZE} 字节上限"
            )
            return units

        # 使用文件对象读取，正确处理多行带引号的 CSV 值
        with open(filepath, encoding="utf-8-sig", newline="") as f:
            # Round 47 Step 2 (D3 TOCTOU defense) → Round 48 Step 2
            # (helper extract): re-check size after open via
            # ``check_fstat_size`` (delegates to os.fstat on the open
            # fd, with intentional fail-open on OSError).  If fstat
            # sees > cap, the file grew between the path.stat() above
            # and this open() — adversarial, skip.  Cost: one extra
            # fstat() syscall on the open fd (microseconds).  Closes
            # the r46 Step 5 security audit's TOCTOU LOW-severity
            # bypass vector.  See safety/file_safety.py for the helper.
            ok, fsize2 = check_fstat_size(f, _MAX_CSV_JSON_SIZE)
            if not ok:
                logger.warning(
                    f"[CSV] 跳过 {rel}: 文件在 stat 后增长到 {fsize2} 字节 "
                    f"（疑似 TOCTOU 攻击），超过 {_MAX_CSV_JSON_SIZE} 字节上限"
                )
                return units

            reader = csv.DictReader(f, delimiter=delimiter)

            if not reader.fieldnames:
                logger.warning(f"[CSV] {rel}: 无表头")
                return []

            headers = list(reader.fieldnames)
            orig_col = _find_column(headers, _ORIGINAL_ALIASES)
            if orig_col is None:
                logger.error(
                    f"[CSV] {rel}: 找不到原文列。表头: {headers}。支持的别名: {_ORIGINAL_ALIASES}"
                )
                return []

            id_col = _find_column(headers, _ID_ALIASES)
            speaker_col = _find_column(headers, _SPEAKER_ALIASES)
            context_col = _find_column(headers, _CONTEXT_ALIASES)
            file_col = _find_column(headers, _FILE_ALIASES)

            for idx, row in enumerate(reader, 1):
                original = (row.get(orig_col, "") or "").strip()
                if not original:
                    continue

                unit_id = (row.get(id_col, "") or "").strip() if id_col else ""
                if not unit_id:
                    unit_id = f"{rel}:{idx}"

                units.append(
                    TranslatableUnit(
                        id=unit_id,
                        original=original,
                        file_path=rel,
                        speaker=(row.get(speaker_col, "") or "").strip() if speaker_col else "",
                        context=(row.get(context_col, "") or "").strip() if context_col else "",
                        metadata={
                            "source_format": source_format,
                            "source_file": str(filepath),
                            "row_index": idx,
                            "file_ref": (row.get(file_col, "") or "").strip() if file_col else "",
                        },
                    )
                )

        logger.debug(f"  [CSV] {rel}: {len(units)} 条")
        return units

    # ============================================================
    # JSONL 提取
    # ============================================================

    def _extract_jsonl(self, filepath: Path) -> list[TranslatableUnit]:
        """读 JSONL 文件，每行一个 JSON 对象。"""
        units: list[TranslatableUnit] = []
        rel = filepath.name
        # Round 44 audit-tail: cap operator-controlled JSONL files at 50 MB.
        # Missed by the r37-r43 M2 phases which focused on .json loaders.
        # Legitimate translation source files sit in KB-low-MB range;
        # 50 MB+ is almost certainly adversarial or misconfigured input.
        try:
            fsize = filepath.stat().st_size
        except OSError:
            fsize = 0
        if fsize > _MAX_CSV_JSON_SIZE:
            logger.warning(
                f"[JSONL] 跳过 {rel}: 文件 {fsize} 字节 超过 {_MAX_CSV_JSON_SIZE} 字节上限"
            )
            return units
        # Round 48 Step 2 (D method scope expansion): TOCTOU defense
        # via fstat after open, mirroring r47 Step 2's csv defense.
        # _extract_jsonl reads the entire file into memory via f.read();
        # without fstat re-check, an attacker can grow the file between
        # the Path.stat() above and the open() below to OOM the host.
        # See safety/file_safety.py for the shared helper.
        with open(filepath, encoding="utf-8-sig") as f:
            ok, fsize2 = check_fstat_size(f, _MAX_CSV_JSON_SIZE)
            if not ok:
                logger.warning(
                    f"[JSONL] 跳过 {rel}: 文件在 stat 后增长到 {fsize2} 字节 "
                    f"（疑似 TOCTOU 攻击），超过 {_MAX_CSV_JSON_SIZE} 字节上限"
                )
                return units
            text = f.read()

        for idx, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    unit = self._obj_to_unit(obj, rel, idx, "jsonl", str(filepath))
                    if unit:
                        units.append(unit)
            except json.JSONDecodeError as e:
                logger.debug(f"  [JSONL] {rel} 行 {idx}: JSON 解析失败: {e}")

        logger.debug(f"  [JSONL] {rel}: {len(units)} 条")
        return units

    def _extract_json_or_jsonl(self, filepath: Path) -> list[TranslatableUnit]:
        """.json 文件：先尝试 JSON 数组，再尝试 JSONL 格式。"""
        rel = filepath.name
        # Round 44 audit-tail: same 50 MB cap as _extract_jsonl above.
        # The .json path is the first dispatch target for ambiguous
        # ``.json`` files (could be either array or JSONL); either shape
        # is operator-controlled and merits the gate.
        try:
            fsize = filepath.stat().st_size
        except OSError:
            fsize = 0
        if fsize > _MAX_CSV_JSON_SIZE:
            logger.warning(
                f"[JSON] 跳过 {rel}: 文件 {fsize} 字节 超过 {_MAX_CSV_JSON_SIZE} 字节上限"
            )
            return []
        # Round 48 Step 2 (D method scope expansion): same TOCTOU
        # defense as _extract_jsonl above; the .json dispatch reads
        # the entire file via f.read() before json.loads(), and an
        # attacker can grow the file between Path.stat() and open()
        # to OOM the host.  See safety/file_safety.py.
        with open(filepath, encoding="utf-8-sig") as f:
            ok, fsize2 = check_fstat_size(f, _MAX_CSV_JSON_SIZE)
            if not ok:
                logger.warning(
                    f"[JSON] 跳过 {rel}: 文件在 stat 后增长到 {fsize2} 字节 "
                    f"（疑似 TOCTOU 攻击），超过 {_MAX_CSV_JSON_SIZE} 字节上限"
                )
                return []
            text = f.read()

        # 尝试 JSON 数组
        try:
            data = json.loads(text)
            if isinstance(data, list):
                units = []
                for idx, obj in enumerate(data, 1):
                    if isinstance(obj, dict):
                        unit = self._obj_to_unit(obj, rel, idx, "json", str(filepath))
                        if unit:
                            units.append(unit)
                if units:
                    logger.debug(f"  [JSON] {rel}: {len(units)} 条（JSON 数组）")
                    return units
        except json.JSONDecodeError:
            pass

        # fallback: JSONL
        return self._extract_jsonl(filepath)

    # ============================================================
    # JSON 对象 → TranslatableUnit
    # ============================================================

    def _obj_to_unit(
        self, obj: dict, rel: str, idx: int, source_format: str, source_file: str
    ) -> TranslatableUnit | None:
        """将一个 JSON 对象转为 TranslatableUnit（含别名解析）。"""
        original = _resolve_field(obj, _ORIGINAL_ALIASES)
        if not original:
            return None

        unit_id = _resolve_field(obj, _ID_ALIASES)
        if not unit_id:
            unit_id = f"{rel}:{idx}"

        return TranslatableUnit(
            id=unit_id,
            original=original,
            file_path=rel,
            speaker=_resolve_field(obj, _SPEAKER_ALIASES),
            context=_resolve_field(obj, _CONTEXT_ALIASES),
            metadata={
                "source_format": source_format,
                "source_file": source_file,
                "row_index": idx,
                "file_ref": _resolve_field(obj, _FILE_ALIASES),
            },
        )

    # ============================================================
    # 回写
    # ============================================================

    def _write_csv(self, units: list[TranslatableUnit], output_dir: Path, target_lang: str) -> int:
        """输出翻译结果为 CSV 文件（UTF-8 BOM）。"""
        out_path = output_dir / f"translations_{target_lang}.csv"
        fieldnames = ["id", "original", "speaker", "context", target_lang]

        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for u in units:
                writer.writerow(
                    {
                        "id": u.id,
                        "original": u.original,
                        "speaker": u.speaker,
                        "context": u.context,
                        target_lang: u.translation,
                    }
                )

        logger.info(f"[CSV] 写入 {len(units)} 条到 {out_path}")
        return len(units)

    def _write_jsonl(
        self, units: list[TranslatableUnit], output_dir: Path, target_lang: str
    ) -> int:
        """输出翻译结果为 JSONL 文件。"""
        out_path = output_dir / f"translations_{target_lang}.jsonl"

        with open(out_path, "w", encoding="utf-8") as f:
            for u in units:
                entry = {
                    "id": u.id,
                    "original": u.original,
                    target_lang: u.translation,
                }
                if u.speaker:
                    entry["speaker"] = u.speaker
                if u.context:
                    entry["context"] = u.context
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info(f"[JSONL] 写入 {len(units)} 条到 {out_path}")
        return len(units)
