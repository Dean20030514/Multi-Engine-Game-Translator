#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RPA Archive Packer
==================
Pack files into Ren'Py RPA-3.0 archives for translation mod distribution.

This is the reverse of ``tools/rpa_unpacker.py`` — it creates ``.rpa``
archives that Ren'Py can load as translation patches.

Typical usage: collect ``tl/<lang>/*.rpy`` + font files + ``default_language.rpy``
into a single ``.rpa`` that players drop into the ``game/`` directory.

Supported format:
    - RPA-3.0 (current mainstream)

RPA-3.0 archive layout::

    RPA-3.0 <hex_index_offset> <hex_xor_key>\\n
    [file data: raw bytes of each file, concatenated]
    [index: zlib(pickle({path_bytes: [(offset^key, length^key, b"")], ...}))]

Usage:
    python -m tools.rpa_packer <file_or_dir> ... --output <archive.rpa>

    <file_or_dir>   Files or directories to pack (relative paths preserved)
    --output        Output .rpa path (default: CN_patch.rpa)
    --base-dir      Base directory for computing relative paths
    --xor-key       Fixed XOR key (hex); default: random (matches Ren'Py behaviour)

Can also be imported::

    from tools.rpa_packer import pack_rpa
    pack_rpa(file_map, Path("CN_patch.rpa"))

Pure standard library — no external dependencies.
"""

from __future__ import annotations

import argparse
import logging
import pickle
import random
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RPA-3.0 format constants
# ---------------------------------------------------------------------------

_RPA3_MAGIC = b"RPA-3.0 "

# Placeholder header: 51 bytes should be enough for any realistic offset/key.
# Format: "RPA-3.0 XXXXXXXXXXXXXXXX XXXXXXXX\n"
# We write a placeholder first, then seek back and overwrite with real values.
_HEADER_PLACEHOLDER_LEN = 51


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RPAPackError(Exception):
    """Base exception for RPA packing operations."""


# ---------------------------------------------------------------------------
# Core packing logic
# ---------------------------------------------------------------------------


def pack_rpa(
    file_map: Dict[str, Path],
    output_path: Path,
    *,
    xor_key: Optional[int] = None,
) -> int:
    """Pack files into an RPA-3.0 archive.

    Args:
        file_map: Mapping of ``{archive_path: local_file_path}``.
            ``archive_path`` is the path *inside* the archive (e.g.
            ``"tl/chinese/script.rpy"``), and ``local_file_path`` is the
            actual file on disk to read.
        output_path: Where to write the ``.rpa`` file.
        xor_key: XOR key for index obfuscation.  ``None`` (default) generates
            a random key, matching Ren'Py's ``archiver.py`` behaviour.
            Pass a fixed value (e.g. ``0``) for deterministic output in tests.

    Returns:
        Number of files packed.

    Raises:
        RPAPackError: If no files to pack, or I/O errors occur.
    """
    if not file_map:
        raise RPAPackError("没有文件需要打包")

    if xor_key is None:
        xor_key = random.randint(0, 0xFFFFFFFF)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # index: {path_bytes: [(offset ^ key, length ^ key, b"")]}
    index: Dict[bytes, List[Tuple[int, int, bytes]]] = {}

    with open(output_path, "wb") as f:
        # Write placeholder header — will be overwritten at the end
        f.write(b"\x00" * _HEADER_PLACEHOLDER_LEN)

        # Write file data sequentially
        for archive_path, local_path in sorted(file_map.items()):
            if not local_path.is_file():
                logger.warning("跳过不存在的文件: %s", local_path)
                continue

            data = local_path.read_bytes()
            offset = f.tell()
            length = len(data)
            f.write(data)

            # Store index entry with XOR obfuscation
            path_key = archive_path.encode("utf-8")
            index[path_key] = [(offset ^ xor_key, length ^ xor_key, b"")]

            logger.debug("  packed: %s (%d bytes @ offset %d)", archive_path, length, offset)

        if not index:
            raise RPAPackError("没有有效文件被打包（所有文件均不存在）")

        # Write index
        index_offset = f.tell()
        index_data = zlib.compress(pickle.dumps(index, protocol=2))
        f.write(index_data)

        # Seek back and write real header
        header = f"{_RPA3_MAGIC.decode()}{index_offset:016x} {xor_key:08x}\n".encode("ascii")
        if len(header) > _HEADER_PLACEHOLDER_LEN:
            raise RPAPackError(
                f"RPA header 超出预留空间: {len(header)} > {_HEADER_PLACEHOLDER_LEN}"
            )
        # Pad to placeholder length to avoid shifting file data
        header = header.ljust(_HEADER_PLACEHOLDER_LEN, b"\x00")
        f.seek(0)
        f.write(header)

    count = len(index)
    logger.info("打包完成: %s (%d 个文件)", output_path, count)
    return count


def collect_files_for_packing(
    game_dir: Path,
    tl_lang: str = "chinese",
    *,
    include_fonts: bool = True,
    include_default_lang: bool = True,
    include_hooks: bool = True,
) -> Dict[str, Path]:
    """Collect translation-related files from a game directory for packing.

    Scans for:
        - ``tl/<lang>/**/*.rpy`` — translation files
        - ``*.ttf``, ``*.otf`` etc. — font files (optional)
        - ``default_language.rpy`` — default language setting (optional)
        - Hook scripts (``hook_*.rpy``) — language switcher etc. (optional)

    Args:
        game_dir: The ``game/`` directory (or its parent).
        tl_lang: Translation language subdirectory name.
        include_fonts: Whether to include font files.
        include_default_lang: Whether to include default_language.rpy.
        include_hooks: Whether to include hook scripts.

    Returns:
        ``{archive_relative_path: local_file_path}`` mapping.
    """
    # Resolve to the game/ subdirectory
    if game_dir.name != "game":
        game_sub = game_dir / "game"
        if game_sub.is_dir():
            game_dir = game_sub

    file_map: Dict[str, Path] = {}

    # 1. Translation files: tl/<lang>/**/*.rpy
    tl_dir = game_dir / "tl" / tl_lang
    if tl_dir.is_dir():
        for rpy in tl_dir.rglob("*.rpy"):
            rel = rpy.relative_to(game_dir)
            file_map[rel.as_posix()] = rpy
    else:
        logger.warning("翻译目录不存在: %s", tl_dir)

    # 2. Font files
    _FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2", ".ttc"}
    if include_fonts:
        for f in game_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in _FONT_EXTS:
                rel = f.relative_to(game_dir)
                file_map[rel.as_posix()] = f

    # 3. default_language.rpy
    if include_default_lang:
        dl = game_dir / "default_language.rpy"
        if dl.is_file():
            file_map["default_language.rpy"] = dl

    # 4. Hook scripts
    if include_hooks:
        for hook in game_dir.glob("hook_*.rpy"):
            if hook.is_file():
                file_map[hook.name] = hook

    return file_map


def verify_archive(archive_path: Path, expected_count: int) -> bool:
    """Verify a packed RPA archive by listing its contents.

    Uses ``rpa_unpacker.list_rpa`` to ensure the archive is readable
    and contains the expected number of files.

    Returns True if verification passes.
    """
    from tools.rpa_unpacker import list_rpa

    try:
        entries = list_rpa(archive_path)
        if len(entries) != expected_count:
            logger.error(
                "RPA 验证失败: 期望 %d 个文件，实际 %d 个",
                expected_count,
                len(entries),
            )
            return False
        logger.info("RPA 验证通过: %d 个文件", len(entries))
        return True
    except Exception as e:
        logger.error("RPA 验证异常: %s", e)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_file_map_from_paths(
    paths: List[str],
    base_dir: Optional[Path],
) -> Dict[str, Path]:
    """Build file_map from CLI positional arguments."""
    file_map: Dict[str, Path] = {}
    for p_str in paths:
        p = Path(p_str).resolve()
        if p.is_file():
            if base_dir:
                try:
                    rel = p.relative_to(base_dir)
                except ValueError:
                    rel = Path(p.name)
            else:
                rel = Path(p.name)
            file_map[rel.as_posix()] = p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    if base_dir:
                        try:
                            rel = f.relative_to(base_dir)
                        except ValueError:
                            rel = f.relative_to(p)
                    else:
                        rel = f.relative_to(p)
                    file_map[rel.as_posix()] = f
        else:
            logger.warning("路径不存在: %s", p)
    return file_map


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pack files into RPA-3.0 archives for Ren'Py translation mods",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to pack (use --game-dir for auto-collection)",
    )
    parser.add_argument(
        "--game-dir",
        type=str,
        default=None,
        help="Auto-collect translation files from game directory",
    )
    parser.add_argument(
        "--tl-lang",
        default="chinese",
        help="Translation language subdirectory (default: chinese)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="CN_patch.rpa",
        help="Output .rpa path (default: CN_patch.rpa)",
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Base directory for computing relative paths inside archive",
    )
    parser.add_argument(
        "--xor-key",
        type=str,
        default=None,
        help="Fixed XOR key in hex (e.g. 0xDEADBEEF); default: random",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip post-pack verification",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    xor_key = None
    if args.xor_key is not None:
        xor_key = int(args.xor_key, 0)  # Accepts 0x prefix

    # Build file map
    if args.game_dir:
        file_map = collect_files_for_packing(
            Path(args.game_dir).resolve(),
            args.tl_lang,
        )
    elif args.paths:
        base = Path(args.base_dir).resolve() if args.base_dir else None
        file_map = _build_file_map_from_paths(args.paths, base)
    else:
        parser.error("需要指定 --game-dir 或待打包文件/目录路径")
        return

    if not file_map:
        print("没有找到可打包的文件", file=sys.stderr)
        sys.exit(1)

    print(f"准备打包 {len(file_map)} 个文件到 {args.output}")
    for archive_path in sorted(file_map):
        print(f"  {archive_path}")

    output = Path(args.output)
    count = pack_rpa(file_map, output, xor_key=xor_key)

    if not args.no_verify:
        ok = verify_archive(output, count)
        if not ok:
            print("打包验证失败！", file=sys.stderr)
            sys.exit(1)

    print(f"打包完成: {output} ({count} 个文件, {output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
