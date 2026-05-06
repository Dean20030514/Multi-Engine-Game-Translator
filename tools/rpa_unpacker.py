#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RPA Archive Unpacker
====================
Extract files from Ren'Py RPA archives (currently supports RPA-3.0).

This is a **pre-processing** tool: it produces .rpy / .rpyc files that can
then be fed into the main translation pipeline.  It lives in ``tools/`` and
is *not* part of the EngineBase abstraction.

Supported formats:
    - RPA-3.0 (current mainstream)
    - RPA-2.0 (legacy)

RPA-1.0, RPA-3.2, and other variants are not yet supported and will be
detected with a clear error message.

Usage:
    python -m tools.rpa_unpacker <archive.rpa> [--outdir <dir>] [--list]

    <archive.rpa>  Path to one or more .rpa files
    --outdir       Output directory (default: same directory as the .rpa)
    --list         Only list contents, do not extract
    --force        Overwrite existing files

Can also be imported::

    from tools.rpa_unpacker import unpack_rpa
    extracted = unpack_rpa(Path("game/archive.rpa"), Path("game/"))

License note — the RPA format handling is an independent clean-room
implementation based on public format documentation.  The renpy-translator
project (MIT, anonymousException 2024) provided the initial inspiration.

Pure standard library — no external dependencies.
"""

from __future__ import annotations

import argparse
import io
import logging
import pickle
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.pickle_safe import SafeUnpickler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RPA format constants
# ---------------------------------------------------------------------------

_RPA3_MAGIC = b"RPA-3.0 "
_RPA2_MAGIC = b"RPA-2.0 "

# Upper bound on the size of a single extracted archive entry. Entries are
# read into memory before being written to disk; without this guard a
# corrupted or hostile index that claims a multi-gigabyte length would
# allocate enough memory to OOM the host. 512 MiB is well above any
# legitimate Ren'Py asset (videos are usually streamed, not embedded).
_RPA_MAX_ENTRY_BYTES = 512 * 1024 * 1024

# Each index entry is a list of tuples: [(offset, length, prefix_bytes), ...]
# prefix_bytes may be empty (b"").  We always use the first tuple.
IndexEntry = List[Tuple[int, int, bytes]]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RPAError(Exception):
    """Base exception for RPA operations."""


class UnsupportedVersion(RPAError):
    """Raised when the archive version is not supported."""


class CorruptedArchive(RPAError):
    """Raised when the archive appears damaged or malformed."""


# ---------------------------------------------------------------------------
# Core: detect version, parse header, read index, extract files
# ---------------------------------------------------------------------------


def _detect_version(header_line: bytes) -> str:
    """Return version string ('3.0' or '2.0') from the first line of the archive."""
    if header_line.startswith(_RPA3_MAGIC):
        return "3.0"
    if header_line.startswith(_RPA2_MAGIC):
        return "2.0"
    # Detect other known versions for a clear error message
    if header_line.startswith(b"RPA-"):
        try:
            ver = header_line.split(b" ")[0].decode("ascii")
        except Exception:
            ver = "RPA-?"
        raise UnsupportedVersion(
            f"检测到 {ver} 格式，当前仅支持 RPA-3.0 和 RPA-2.0。此版本将在后续版本中支持。"
        )
    raise UnsupportedVersion("文件不是有效的 RPA 档案（未找到 RPA 头部标识）。")


def _parse_header(header_line: bytes) -> Tuple[str, int, Optional[int]]:
    """Parse the first line of the archive.

    Returns:
        (version, index_offset, key_or_none)

    RPA-3.0 header layout (ASCII)::

        RPA-3.0 <hex_offset> <hex_key>\n

    RPA-2.0 header layout::

        RPA-2.0 <hex_offset>\n
    """
    version = _detect_version(header_line)
    parts = header_line.split()

    try:
        if version == "3.0":
            if len(parts) < 3:
                raise CorruptedArchive("RPA-3.0 头部缺少 offset 或 key 字段。")
            offset = int(parts[1], 16)
            key = int(parts[2], 16)
            return version, offset, key

        if version == "2.0":
            if len(parts) < 2:
                raise CorruptedArchive("RPA-2.0 头部缺少 offset 字段。")
            offset = int(parts[1], 16)
            return version, offset, None

    except (ValueError, IndexError) as exc:
        raise CorruptedArchive(f"RPA 头部解析失败: {exc}") from exc

    # Should not reach here
    raise UnsupportedVersion(f"内部错误：未处理的版本 {version}")


def _deobfuscate_index(
    index: Dict[bytes, IndexEntry],
    key: int,
) -> Dict[str, Tuple[int, int, bytes]]:
    """Apply XOR deobfuscation and normalise the index to simple entries.

    Each index entry in the raw pickle is a list of (offset, length, prefix)
    tuples.  We take the first tuple and XOR offset/length with the key.

    Returns dict mapping filename (str) → (offset, length, prefix_bytes).
    """
    result: Dict[str, Tuple[int, int, bytes]] = {}
    for name_bytes, entries in index.items():
        # Normalise filename
        if isinstance(name_bytes, bytes):
            name = name_bytes.decode("utf-8", errors="replace")
        else:
            name = str(name_bytes)

        if not entries:
            logger.warning("索引条目为空，跳过: %s", name)
            continue

        entry = entries[0]
        # Handle 2-tuple (offset, length) or 3-tuple (offset, length, prefix)
        if len(entry) == 2:
            raw_offset, raw_length = entry
            prefix = b""
        else:
            raw_offset, raw_length, prefix = entry[0], entry[1], entry[2]

        offset = raw_offset ^ key
        length = raw_length ^ key

        result[name] = (offset, length, prefix if isinstance(prefix, bytes) else b"")
    return result


def _normalise_index_no_key(
    index: Dict[bytes, IndexEntry],
) -> Dict[str, Tuple[int, int, bytes]]:
    """Normalise index without deobfuscation (for RPA-2.0)."""
    result: Dict[str, Tuple[int, int, bytes]] = {}
    for name_bytes, entries in index.items():
        if isinstance(name_bytes, bytes):
            name = name_bytes.decode("utf-8", errors="replace")
        else:
            name = str(name_bytes)

        if not entries:
            continue

        entry = entries[0]
        if len(entry) == 2:
            offset, length = entry
            prefix = b""
        else:
            offset, length, prefix = entry[0], entry[1], entry[2]

        result[name] = (offset, length, prefix if isinstance(prefix, bytes) else b"")
    return result


def _read_index(
    archive_path: Path,
) -> Tuple[str, Dict[str, Tuple[int, int, bytes]]]:
    """Read and parse the archive index.

    Returns (version, normalised_index).
    """
    with open(archive_path, "rb") as f:
        header_line = f.readline()
        version, index_offset, key = _parse_header(header_line)

        # Seek to index and read remaining data
        f.seek(index_offset)
        raw_index_data = f.read()

    # Decompress (zlib) then unpickle
    try:
        decompressed = zlib.decompress(raw_index_data)
    except zlib.error as exc:
        raise CorruptedArchive(f"RPA 索引 zlib 解压失败（档案可能损坏）: {exc}") from exc

    try:
        index = SafeUnpickler(io.BytesIO(decompressed), encoding="bytes").load()
    except pickle.UnpicklingError as exc:
        raise CorruptedArchive(f"RPA 索引包含不受信任的对象类型，已拒绝加载: {exc}") from exc
    except Exception as exc:
        raise CorruptedArchive(f"RPA 索引 pickle 反序列化失败: {exc}") from exc

    if not isinstance(index, dict):
        raise CorruptedArchive(f"RPA 索引格式异常：期望 dict，实际 {type(index).__name__}")

    # Deobfuscate if key present (RPA-3.0)
    if key is not None:
        normalised = _deobfuscate_index(index, key)
    else:
        normalised = _normalise_index_no_key(index)

    return version, normalised


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_rpa(archive_path: Path) -> List[str]:
    """List all files in an RPA archive.

    Args:
        archive_path: Path to the .rpa file.

    Returns:
        Sorted list of filenames contained in the archive.

    Raises:
        RPAError: On any parsing error.
    """
    _, index = _read_index(archive_path)
    return sorted(index.keys())


def unpack_rpa(
    archive_path: Path,
    outdir: Path,
    *,
    force: bool = False,
    filter_ext: Optional[Tuple[str, ...]] = None,
) -> List[Path]:
    """Extract all (or filtered) files from an RPA archive.

    Args:
        archive_path: Path to the .rpa file.
        outdir: Directory to extract files into (preserving archive paths).
        force: Overwrite existing files if True.
        filter_ext: If provided, only extract files with these extensions
                    (e.g. ('.rpy', '.rpyc')).  Extensions must include dot.

    Returns:
        List of Paths to extracted files.

    Raises:
        RPAError: On any parsing/extraction error.
    """
    version, index = _read_index(archive_path)
    logger.info(
        "[RPA] 档案 %s (RPA-%s): 包含 %d 个文件",
        archive_path.name,
        version,
        len(index),
    )

    extracted: List[Path] = []

    with open(archive_path, "rb") as f:
        for name, (offset, length, prefix) in sorted(index.items()):
            # Extension filter
            if filter_ext:
                ext = Path(name).suffix.lower()
                if ext not in filter_ext:
                    continue

            dest = outdir / name

            # ZIP Slip guard: refuse any archive entry whose resolved path
            # escapes outdir (e.g. ``../../evil.py`` or absolute paths).
            try:
                dest.resolve().relative_to(outdir.resolve())
            except ValueError:
                logger.warning("[RPA] 跳过危险路径（疑似路径穿越 / ZIP Slip）: %s", name)
                continue

            # Skip if exists and not forcing
            if dest.exists() and not force:
                logger.debug("[RPA] 跳过（已存在）: %s", name)
                continue

            # Pre-read size bound: refuse absurdly large (or negative) entries
            # before any memory allocation.  A corrupted index could otherwise
            # steer f.read() into a multi-gigabyte allocation.
            if length < 0 or length > _RPA_MAX_ENTRY_BYTES:
                logger.warning(
                    "[RPA] 跳过异常大条目 (%d 字节，上限 %d): %s",
                    length,
                    _RPA_MAX_ENTRY_BYTES,
                    name,
                )
                continue

            # Ensure parent directory exists
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Read file data from archive
            f.seek(offset)
            data = prefix + f.read(length)

            dest.write_bytes(data)
            extracted.append(dest)
            logger.debug("[RPA] 已提取: %s (%d 字节)", name, len(data))

    logger.info("[RPA] 提取完成: %d 个文件 → %s", len(extracted), outdir)
    return extracted


def unpack_all_rpa_in_dir(
    game_dir: Path,
    *,
    force: bool = False,
    filter_ext: Optional[Tuple[str, ...]] = None,
) -> List[Path]:
    """Find and unpack all .rpa files under a game directory.

    Typically the game directory contains .rpa files directly (e.g.
    ``game/archive.rpa``, ``game/scripts.rpa``).

    Args:
        game_dir: The game directory to scan for .rpa files.
        force: Overwrite existing files if True.
        filter_ext: Only extract files matching these extensions.

    Returns:
        Combined list of all extracted file Paths.
    """
    rpa_files = sorted(game_dir.rglob("*.rpa"))
    if not rpa_files:
        logger.info("[RPA] 未在 %s 下找到 .rpa 档案", game_dir)
        return []

    logger.info("[RPA] 找到 %d 个 .rpa 档案", len(rpa_files))
    all_extracted: List[Path] = []

    for rpa_path in rpa_files:
        try:
            # Extract to the same directory as the .rpa file
            outdir = rpa_path.parent
            extracted = unpack_rpa(
                rpa_path,
                outdir,
                force=force,
                filter_ext=filter_ext,
            )
            all_extracted.extend(extracted)
        except RPAError as exc:
            logger.error("[RPA] 解包失败 %s: %s", rpa_path.name, exc)
            # fail-fast per file, but continue with other archives
            continue

    logger.info("[RPA] 全部完成: 共提取 %d 个文件", len(all_extracted))
    return all_extracted


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpa_unpacker",
        description="从 Ren'Py RPA 档案中提取文件（支持 RPA-3.0 / RPA-2.0）",
    )
    parser.add_argument(
        "archives",
        nargs="+",
        help="要解包的 .rpa 文件路径",
    )
    parser.add_argument(
        "--outdir",
        "-o",
        default=None,
        help="输出目录（默认: .rpa 文件所在目录）",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        dest="list_only",
        help="仅列出档案内容，不提取",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="覆盖已存在的文件",
    )
    parser.add_argument(
        "--scripts-only",
        action="store_true",
        help="仅提取脚本文件（.rpy / .rpyc）",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns 0 on success, 1 on error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    filter_ext = (".rpy", ".rpyc") if args.scripts_only else None
    exit_code = 0

    for archive_str in args.archives:
        archive_path = Path(archive_str)
        if not archive_path.exists():
            logger.error("文件不存在: %s", archive_path)
            exit_code = 1
            continue

        try:
            if args.list_only:
                files = list_rpa(archive_path)
                print(f"\n{archive_path.name} ({len(files)} 个文件):")
                for name in files:
                    print(f"  {name}")
            else:
                outdir = Path(args.outdir) if args.outdir else archive_path.parent
                extracted = unpack_rpa(
                    archive_path,
                    outdir,
                    force=args.force,
                    filter_ext=filter_ext,
                )
                print(f"{archive_path.name}: 已提取 {len(extracted)} 个文件 → {outdir}")
        except RPAError as exc:
            logger.error("解包失败 %s: %s", archive_path.name, exc)
            exit_code = 1
        except Exception as exc:
            logger.error("意外错误 %s: %s", archive_path.name, exc)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
