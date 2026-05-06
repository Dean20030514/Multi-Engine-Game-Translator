#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unity XUnity AutoTranslator engine.

Round 55: handles XUAT-exported translation files. The engine deliberately
does NOT parse Unity AssetBundles or .dll resources — it only reads /
writes the plain-text translation files that XUAT itself produces, which
is how the vast majority of Unity fan-translation workflows operate.

XUAT file format
================

Each line is one of:

  1. Empty / whitespace-only   → preserved verbatim on write-back
  2. Comment ``// ...``         → preserved verbatim on write-back
  3. Translation entry          ``original=translation``
                                — split on the FIRST ``=`` only, so
                                  ``key=value=foo`` parses as
                                  ``original="key", translation="value=foo"``
  4. Regex rule                 ``r:"<pattern>"="<replacement>"``
                                — pattern is a Unity-side runtime regex,
                                  must NOT be translated; replacement is
                                  user-authored, fed to the LLM
  5. Malformed                  → logged at debug level, skipped

Round-trip byte-identity
========================

``write_back`` reads the original file, walks line-by-line, and only
mutates lines that have a corresponding translated unit. Comments,
blanks, malformed lines, line ordering, line endings, and the BOM (if
present) are preserved. This is asserted by
``tests/test_unity_xunity_engine.py::test_write_back_roundtrip``.

Hard contract (CLAUDE.md maintenance rule, Round 55)
====================================================

- ``=`` parsing MUST use ``str.partition('=')`` (split on first only).
  Switching to ``split('=')`` breaks payloads with ``=`` in original.
- ``//`` comment lines MUST round-trip preserve.
- Regex rules: pattern preserved verbatim, ONLY replacement translated.

Round 56 M1: regex backreference placeholder protection
=======================================================

When a regex rule's replacement is empty, the pattern itself is fed to
the LLM as ``original`` (with metadata flagging ``line_type ==
"regex_rule"``). The LLM may break regex metacharacters during
translation — e.g. ``Item: (\\d+)`` coming back as ``物品: (数字)``
destroys the runtime regex. The :data:`UNITY_XUNITY_PROFILE`
``placeholder_patterns`` protect the common metacharacters (``\\d``
``\\w`` ``\\s`` ``\\b`` ``\\1``-``\\9``) before the prompt reaches the
model and restore them on the response. Authors of regex rules should
still review AI output for the surviving regex literals (parentheses,
brackets, dots) — this protection is best-effort, not a guarantee.

Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from safety.file_safety import check_fstat_size
from engines.engine_base import (
    EngineBase,
    EngineProfile,
    TranslatableUnit,
    UNITY_XUNITY_PROFILE,
)

logger = logging.getLogger("multi_engine_translator")

# OOM cap — matches the 50 MB cap used across r37-r53 user-facing
# loaders. Real-world XUAT files top out at a few MB even for very
# large games; 50 MB is a generous margin while still defending against
# adversarial / corrupt input.
_MAX_XUAT_FILE_SIZE: int = 50 * 1024 * 1024

# Supported file extensions (XUAT defaults to .txt)
_XUAT_EXTENSIONS: frozenset[str] = frozenset({".txt"})

# Regex rule line: r:"<pattern>"="<replacement>"
# Both pattern and replacement are double-quoted; we use a raw regex to
# extract the two payloads while honouring backslash-escaped quotes.
_REGEX_RULE_LINE = re.compile(r'^r:"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"\s*$')


# ────────────────────────────────────────────────────────────────────
# Parsed line representation
# ────────────────────────────────────────────────────────────────────


@dataclass
class _ParsedLine:
    """One parsed line of an XUAT file.

    ``raw`` is the original text without trailing newline. The
    line_ending attribute captures whether the source used ``\\r\\n``
    or ``\\n`` so write_back can preserve it exactly.
    """

    line_no: int  # 1-based
    line_type: str  # "blank" / "comment" / "translation" / "regex_rule" / "malformed"
    raw: str  # original text without trailing newline
    line_ending: str  # "\n" or "\r\n"
    original: str = ""  # parsed original (translation / regex_rule only)
    translation: str = ""  # parsed translation (translation / regex_rule only)
    regex_pattern: str = ""  # filled when line_type == "regex_rule"


def _parse_lines(text: str) -> list[_ParsedLine]:
    """Parse the entire file body into ordered _ParsedLine records.

    Detects per-line ending so write_back can preserve original CRLF/LF
    mixing. Empty trailing line (file ends with newline) is dropped to
    avoid emitting a spurious extra newline on round-trip.
    """
    parsed: list[_ParsedLine] = []
    pos = 0
    line_no = 0
    n = len(text)
    while pos < n:
        # Find end of this logical line (LF or CRLF)
        nl = text.find("\n", pos)
        if nl == -1:
            chunk = text[pos:]
            ending = ""
            pos = n
        else:
            chunk = text[pos:nl]
            ending = "\n"
            if chunk.endswith("\r"):
                chunk = chunk[:-1]
                ending = "\r\n"
            pos = nl + 1
        line_no += 1
        parsed.append(_classify_line(line_no, chunk, ending))
    return parsed


def _classify_line(line_no: int, raw: str, line_ending: str) -> _ParsedLine:
    """Classify one raw line and extract original/translation if any."""
    stripped = raw.strip()

    # Blank
    if not stripped:
        return _ParsedLine(line_no=line_no, line_type="blank", raw=raw, line_ending=line_ending)

    # Comment (XUAT uses //; we also accept # for tolerance though XUAT itself
    # doesn't emit it — keep // as the canonical form on write-back)
    if stripped.startswith("//"):
        return _ParsedLine(line_no=line_no, line_type="comment", raw=raw, line_ending=line_ending)

    # Regex rule: r:"<pattern>"="<replacement>"
    m = _REGEX_RULE_LINE.match(stripped)
    if m:
        return _ParsedLine(
            line_no=line_no,
            line_type="regex_rule",
            raw=raw,
            line_ending=line_ending,
            original=m.group(2),  # the replacement text is what gets translated
            translation=m.group(2),  # placeholder until LLM fills
            regex_pattern=m.group(1),
        )

    # Plain translation entry: split on FIRST '=' only.
    # Hard contract (Round 55): MUST use partition('='), not split('=').
    if "=" not in raw:
        return _ParsedLine(line_no=line_no, line_type="malformed", raw=raw, line_ending=line_ending)
    original, _, translation = raw.partition("=")
    if not original:
        # Lines like ``=foo`` have empty original — treat as malformed
        # rather than silently dropping the value.
        return _ParsedLine(line_no=line_no, line_type="malformed", raw=raw, line_ending=line_ending)
    return _ParsedLine(
        line_no=line_no,
        line_type="translation",
        raw=raw,
        line_ending=line_ending,
        original=original,
        translation=translation,
    )


# ────────────────────────────────────────────────────────────────────
# Engine
# ────────────────────────────────────────────────────────────────────


class UnityXUnityEngine(EngineBase):
    """Unity XUnity AutoTranslator engine."""

    def _default_profile(self) -> EngineProfile:
        return UNITY_XUNITY_PROFILE

    def detect(self, game_dir: Path) -> bool:
        """Manual-only — XUAT files live in many locations and are often
        copied out for hand-management. Auto-detection would over-trigger.
        Use ``--engine unity`` (or ``--engine unity_xunity``) explicitly.
        """
        return False

    # ────────────────────────────────────────────────────────────────
    # Extract
    # ────────────────────────────────────────────────────────────────

    def extract_texts(self, game_dir: Path, **kwargs) -> list[TranslatableUnit]:
        """Extract translation entries (and regex-rule replacements).

        ``game_dir`` may be either:
          * a single ``.txt`` file (typical when the user manages their
            XUAT translation file by hand)
          * a directory; recursively scans for ``.txt`` files
        """
        target = Path(game_dir)
        units: list[TranslatableUnit] = []

        if target.is_file():
            units.extend(self._extract_file(target))
        elif target.is_dir():
            for f in sorted(target.rglob("*")):
                if f.is_file() and f.suffix.lower() in _XUAT_EXTENSIONS:
                    units.extend(self._extract_file(f))
        else:
            logger.error(f"[XUAT] 路径不存在: {target}")
            return units

        translatable = [u for u in units if u.status == "pending"]
        logger.info(
            f"[XUAT] 提取 {len(translatable)} 条待翻译（共扫描 {len(units)} 条 entry，含已译条目）"
        )
        return translatable

    def _extract_file(self, file_path: Path) -> Iterator[TranslatableUnit]:
        """Read one XUAT file and yield TranslatableUnit per pending entry."""
        try:
            stat = file_path.stat()
        except OSError as e:
            logger.warning(f"[XUAT] stat 失败 {file_path}: {e}")
            return
        if stat.st_size > _MAX_XUAT_FILE_SIZE:
            logger.warning(
                f"[XUAT] 文件 {file_path} 过大 ({stat.st_size} > {_MAX_XUAT_FILE_SIZE})，跳过"
            )
            return

        try:
            # ``utf-8-sig`` strips BOM when present; we re-detect BOM at
            # write_back time from the raw bytes so the round-trip is
            # byte-identical regardless of whether the source had one.
            with open(file_path, encoding="utf-8-sig") as f:
                ok, fsize2 = check_fstat_size(f, _MAX_XUAT_FILE_SIZE)
                if not ok:
                    logger.warning(
                        f"[XUAT] 文件 {file_path} stat 后增长到 {fsize2} 字节（疑似 TOCTOU），跳过"
                    )
                    return
                text = f.read()
        except OSError as e:
            logger.warning(f"[XUAT] 读取失败 {file_path}: {e}")
            return

        parsed = _parse_lines(text)
        rule_warned = False
        rel_path = str(file_path)
        malformed_warned: set[int] = set()

        for line in parsed:
            if line.line_type in ("blank", "comment", "malformed"):
                if line.line_type == "malformed" and line.line_no not in malformed_warned:
                    logger.debug(
                        f"[XUAT] {file_path}:{line.line_no} 格式异常，跳过: {line.raw[:80]!r}"
                    )
                    malformed_warned.add(line.line_no)
                continue

            if line.line_type == "regex_rule":
                if not rule_warned:
                    logger.info(
                        f"[XUAT] {file_path} 含正则规则；pattern 将保留不翻译，"
                        f"仅 replacement 提交给 LLM"
                    )
                    rule_warned = True
                if line.translation.strip():
                    yield TranslatableUnit(
                        id=f"{rel_path}#L{line.line_no}",
                        original=line.translation,
                        file_path=rel_path,
                        translation=line.translation,
                        status="translated",
                        metadata={
                            "line_no": line.line_no,
                            "line_type": "regex_rule",
                            "regex_pattern": line.regex_pattern,
                        },
                    )
                else:
                    yield TranslatableUnit(
                        id=f"{rel_path}#L{line.line_no}",
                        original=line.regex_pattern,  # context for the LLM
                        file_path=rel_path,
                        status="pending",
                        metadata={
                            "line_no": line.line_no,
                            "line_type": "regex_rule",
                            "regex_pattern": line.regex_pattern,
                        },
                    )
                continue

            # plain translation
            if line.translation.strip():
                yield TranslatableUnit(
                    id=f"{rel_path}#L{line.line_no}",
                    original=line.original,
                    file_path=rel_path,
                    translation=line.translation,
                    status="translated",
                    metadata={"line_no": line.line_no, "line_type": "translation"},
                )
            else:
                yield TranslatableUnit(
                    id=f"{rel_path}#L{line.line_no}",
                    original=line.original,
                    file_path=rel_path,
                    status="pending",
                    metadata={"line_no": line.line_no, "line_type": "translation"},
                )

    # ────────────────────────────────────────────────────────────────
    # Write-back
    # ────────────────────────────────────────────────────────────────

    def write_back(
        self, game_dir: Path, units: list[TranslatableUnit], output_dir: Path, **kwargs
    ) -> int:
        """Write translated units back, preserving comments / blanks / order.

        Output goes to ``output_dir/<relative_path>``. The original input
        file is never modified. BOM presence is preserved from the
        source file.
        """
        out_root = Path(output_dir)
        out_root.mkdir(parents=True, exist_ok=True)

        # Index translated units by file → line_no → translation
        by_file: dict[str, dict[int, str]] = {}
        for u in units:
            if u.status != "translated":
                continue
            line_no = u.metadata.get("line_no")
            if not isinstance(line_no, int):
                continue
            translation = (u.translation or "").rstrip("\n").rstrip("\r")
            by_file.setdefault(u.file_path, {})[line_no] = translation

        written = 0
        for src_path_str, line_map in by_file.items():
            src_path = Path(src_path_str)
            try:
                raw_bytes = src_path.read_bytes()
            except OSError as e:
                logger.warning(f"[XUAT] 重读源文件失败 {src_path}: {e}")
                continue

            has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
            text = raw_bytes.decode("utf-8-sig" if has_bom else "utf-8", errors="replace")
            parsed = _parse_lines(text)

            buf: list[str] = []
            for line in parsed:
                new_translation = line_map.get(line.line_no)

                if new_translation is None or line.line_type not in ("translation", "regex_rule"):
                    buf.append(line.raw + line.line_ending)
                    continue

                if line.line_type == "translation":
                    buf.append(f"{line.original}={new_translation}{line.line_ending}")
                else:  # regex_rule
                    # Hard contract: pattern preserved verbatim; only
                    # replacement is rebuilt. Mirror the source escape
                    # convention by passing the new translation through
                    # the same double-quote envelope without re-escaping
                    # — the LLM is expected to emit clean text.
                    pattern = line.regex_pattern
                    buf.append(f'r:"{pattern}"="{new_translation}"' + line.line_ending)

                written += 1

            # Resolve output path: try to make src relative to game_dir;
            # if that fails (absolute path outside game_dir), just use
            # the file basename.
            try:
                rel = src_path.relative_to(Path(game_dir))
            except ValueError:
                rel = Path(src_path.name)
            out_path = out_root / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                out_bytes = "".join(buf).encode("utf-8")
                if has_bom:
                    out_bytes = b"\xef\xbb\xbf" + out_bytes
                tmp = out_path.with_suffix(out_path.suffix + ".tmp")
                tmp.write_bytes(out_bytes)
                os.replace(str(tmp), str(out_path))
                logger.info(f"[XUAT] 写入 {out_path}（{len(line_map)} 条已替换）")
            except OSError as e:
                logger.warning(f"[XUAT] 写入失败 {out_path}: {e}")

        return written
