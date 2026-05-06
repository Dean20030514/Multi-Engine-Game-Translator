#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RPYC Decompiler
===============
Decompile Ren'Py compiled script files (.rpyc / .rpymc) back into
readable .rpy source, enabling translation of games that ship without
source code.

This is a **pre-processing** tool in ``tools/``, independent of the
EngineBase abstraction.  Its output (.rpy files) feeds into the existing
translation pipeline.

Two-tier strategy
-----------------
**Tier 1 — Game-python decompilation** (preferred):
    Generates a tiny helper script, executes it with the Python interpreter
    bundled inside the Ren'Py game.  This produces perfect .rpy source via
    ``renpy.util.get_code()``.  Requires a complete game directory with
    ``lib/`` and ``renpy/`` present.

**Tier 2 — Standalone text extraction** (fallback):
    Uses a ``RestrictedUnpickler`` that replaces all ``renpy.*`` classes with
    dummy stubs, then walks the resulting AST to extract translatable text
    (say statements, menu items, translate-string entries).  Does *not*
    produce runnable .rpy source — instead outputs a structured JSON manifest
    of translatable strings.  Works without any Ren'Py runtime.

Platform support (Tier 1)
-------------------------
Ren'Py bundles a modified Python interpreter whose path varies by version
and platform:

    ======== =============== ====================================
    Platform Ren'Py 7.x      Ren'Py 8.x
    ======== =============== ====================================
    Windows  lib/py2-windows-x86_64/python.exe   lib/py3-windows-x86_64/python.exe
             lib/windows-x86_64/python.exe        (also windows-i686 for 32-bit)
    Linux    lib/py2-linux-x86_64/python          lib/py3-linux-x86_64/python
             lib/linux-x86_64/python
    macOS    (inside .app bundle)                 lib/py3-mac-universal/python
             lib/py2-mac-x86_64/pythonw
    ======== =============== ====================================

Usage:
    python -m tools.rpyc_decompiler <game_dir> [--outdir <dir>] [--fallback]

Can also be imported::

    from tools.rpyc_decompiler import decompile_game, extract_strings_standalone
    results = decompile_game(Path("GameDir/"), Path("output/"))

Pure standard library — no external dependencies.

License note — inspired by renpy-translator (MIT, anonymousException 2024).
RPYC binary format handling is based on public Ren'Py source.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (shared with Tier 2 via ``tools/_rpyc_shared.py``)
# ---------------------------------------------------------------------------
#
# Round 40 split: the RPYC2 format header + slot constants and the Tier 1 /
# Tier 2 pickle whitelist used to live in this module.  They were moved
# to ``tools/_rpyc_shared.py`` in round 40 so Tier 2 could be extracted
# to its own module without a circular import (main <-> tier2).  Re-
# exported at module level below for any legacy caller / test that
# imported them from ``tools.rpyc_decompiler`` directly.
from tools._rpyc_shared import (
    _SHARED_WHITELIST,
    _WHITELIST_TIER1_PY2_EXTRAS,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RPYCError(Exception):
    """Base exception for RPYC operations."""


class NoRenpyRuntime(RPYCError):
    """Ren'Py runtime not found — cannot use Tier 1."""


_MAX_RPYC_RESULT_SIZE = 50 * 1024 * 1024
"""Round 45 audit-tail: 50 MB cap on the JSON result file produced by
the Tier 1 game-python subprocess (``_decompile_helper.py``'s
``_results.json``).  The subprocess is controlled code (we generate it
from :func:`_render_decompile_helper`), but its output scales with the
number + size of .rpyc files in the target game.  Matches the
50 MB cap used across r37-r44 user-facing + internal JSON loaders for
cross-module consistency."""


class DecompileError(RPYCError):
    """Decompilation failed."""


# ---------------------------------------------------------------------------
# Platform + version detection (Tier 1)
# ---------------------------------------------------------------------------


def _find_renpy_python(game_dir: Path) -> Optional[Path]:
    """Locate the Python interpreter bundled with a Ren'Py game.

    Searches platform-specific paths for both Ren'Py 7.x (Python 2) and
    8.x (Python 3).  Returns the first valid executable found, or None.
    """
    lib_dir = game_dir / "lib"
    if not lib_dir.is_dir():
        return None

    system = platform.system().lower()  # 'windows', 'linux', 'darwin'
    machine = platform.machine().lower()  # 'amd64', 'x86_64', 'arm64', etc.

    # Normalise machine names
    if machine in ("amd64", "x86_64"):
        arch = "x86_64"
    elif machine in ("i386", "i686"):
        arch = "i686"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        arch = machine

    exe_name = "python.exe" if system == "windows" else "python"

    # Build candidate paths (higher priority first)
    candidates: list[str] = []

    if system == "windows":
        candidates = [
            f"py3-windows-{arch}",
            f"windows-{arch}",
            f"py2-windows-{arch}",
        ]
        # Also try 32-bit on 64-bit Windows
        if arch == "x86_64":
            candidates.extend(
                [
                    "py3-windows-i686",
                    "windows-i686",
                    "py2-windows-i686",
                ]
            )
    elif system == "linux":
        candidates = [
            f"py3-linux-{arch}",
            f"linux-{arch}",
            f"py2-linux-{arch}",
        ]
    elif system == "darwin":
        candidates = [
            "py3-mac-universal",
            f"py3-mac-{arch}",
            f"mac-{arch}",
            "py2-mac-x86_64",
        ]
        # macOS may use pythonw
        for cand in list(candidates):
            p = lib_dir / cand / "pythonw"
            if p.is_file():
                return p

    for cand in candidates:
        p = lib_dir / cand / exe_name
        if p.is_file():
            return p

    # Last resort: glob for any python executable under lib/
    for p in lib_dir.rglob(exe_name):
        if p.is_file():
            return p

    return None


def _detect_renpy_version(game_dir: Path) -> Optional[str]:
    """Try to detect Ren'Py version from the game directory.

    Returns '7' or '8' (or None if unknown).
    """
    python_path = _find_renpy_python(game_dir)
    if python_path is None:
        return None
    parent = python_path.parent.name.lower()
    if "py3" in parent:
        return "8"
    if "py2" in parent:
        return "7"
    return None


def _find_renpy_base(game_dir: Path) -> Optional[Path]:
    """Find the Ren'Py base directory (contains renpy/ module).

    Typically this is the game directory's parent, or the game directory
    itself if it contains a 'renpy' subdirectory.
    """
    # Check game_dir/renpy/
    if (game_dir / "renpy" / "__init__.py").is_file():
        return game_dir
    # Check parent (game_dir is usually 'game/' inside the Ren'Py project)
    parent = game_dir.parent
    if (parent / "renpy" / "__init__.py").is_file():
        return parent
    # Check game_dir itself for typical game structure
    if game_dir.name == "game":
        project_root = game_dir.parent
        if (project_root / "renpy" / "__init__.py").is_file():
            return project_root
    return None


# ---------------------------------------------------------------------------
# Tier 1: Game-python decompilation
# ---------------------------------------------------------------------------

# This script is injected into the game's Python environment.
# It uses renpy's own code generation to produce perfect .rpy output.
#
# The ``{SAFE_BUILTINS_JSON}`` / ``{SAFE_COLLECTIONS_JSON}`` / ``{SAFE_CODECS_JSON}``
# / ``{SAFE_COPYREG_JSON}`` placeholders are formatted in by
# ``_render_decompile_helper()`` from ``_SHARED_WHITELIST`` + the Python-2
# extras, so Tier 1 and Tier 2 cannot drift silently.
_DECOMPILE_HELPER_TEMPLATE = textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    # Auto-generated decompile helper - executed by game's bundled Python.
    # Compatible with Python 2.7 (Ren'Py 7.x) and Python 3.x (Ren'Py 8.x).
    # Whitelist is injected from the parent process's ``_SHARED_WHITELIST``
    # so Tier 1 and Tier 2 cannot drift out of sync.  See
    # ``tools/rpyc_decompiler._SHARED_WHITELIST`` / ``_WHITELIST_TIER1_PY2_EXTRAS``.
    import io, json, os, pickle, struct, sys, zlib

    RPYC2_HEADER = b"RENPY RPC2"

    # Whitelist unpickler: allow real renpy/store classes (needed by
    # renpy.util.get_code) plus primitive containers; reject os/subprocess/
    # builtins.eval and anything else a malicious .rpyc might try to invoke.
    _SAFE_BUILTINS = frozenset({SAFE_BUILTINS_JSON})
    _SAFE_COLLECTIONS = frozenset({SAFE_COLLECTIONS_JSON})
    _SAFE_CODECS = frozenset({SAFE_CODECS_JSON})
    _SAFE_COPYREG = frozenset({SAFE_COPYREG_JSON})

    class _SafeUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if module.startswith(("renpy", "store")):
                return pickle.Unpickler.find_class(self, module, name)
            if module in ("builtins", "__builtin__") and name in _SAFE_BUILTINS:
                return pickle.Unpickler.find_class(self, module, name)
            if module == "collections" and name in _SAFE_COLLECTIONS:
                return pickle.Unpickler.find_class(self, module, name)
            if module == "_codecs" and name in _SAFE_CODECS:
                return pickle.Unpickler.find_class(self, module, name)
            if module in ("copyreg", "copy_reg") and name in _SAFE_COPYREG:
                return pickle.Unpickler.find_class(self, module, name)
            raise pickle.UnpicklingError(
                "Refused to load {0}.{1} (not in safe whitelist)".format(module, name)
            )

    def read_rpyc_data(f, slot):
        f.seek(0)
        header = f.read(1024)
        if header[:len(RPYC2_HEADER)] != RPYC2_HEADER:
            if slot != 1:
                return None
            f.seek(0)
            return zlib.decompress(f.read())
        pos = len(RPYC2_HEADER)
        while True:
            if pos + 12 > len(header):
                return None
            s, start, length = struct.unpack("III", header[pos:pos+12])
            if s == slot:
                break
            if s == 0:
                return None
            pos += 12
        f.seek(start)
        return zlib.decompress(f.read(length))

    def decompile_file(rpyc_path):
        with open(rpyc_path, "rb") as f:
            for slot in [1, 2]:
                data = read_rpyc_data(f, slot)
                if data:
                    _, stmts = _SafeUnpickler(io.BytesIO(data)).load()
                    import renpy.util
                    return renpy.util.get_code(stmts)
                f.seek(0)
        return None

    def main():
        manifest = json.loads(sys.argv[1])
        results = {}
        for rpyc_path in manifest["files"]:
            try:
                code = decompile_file(rpyc_path)
                if code is not None:
                    results[rpyc_path] = {"ok": True, "code": code}
                else:
                    results[rpyc_path] = {"ok": False, "error": "no AST data"}
            except Exception as e:
                results[rpyc_path] = {"ok": False, "error": str(e)}
        # Write results to output file
        out_path = manifest["output"]
        with io.open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False)

    main()
""")


def _render_decompile_helper() -> str:
    """Fill the Tier 1 helper template with the shared whitelist.

    Injects ``_SHARED_WHITELIST`` (plus Python-2 extras for builtins) as JSON
    lists so the helper's ``_SAFE_BUILTINS`` / ``_SAFE_COLLECTIONS`` /
    ``_SAFE_CODECS`` / ``_SAFE_COPYREG`` frozensets are derived from the
    single source of truth at the top of this file.
    """
    builtins_list = sorted(
        set(_SHARED_WHITELIST["builtins"]) | set(_WHITELIST_TIER1_PY2_EXTRAS.get("builtins", []))
    )
    replacements = {
        "{SAFE_BUILTINS_JSON}": json.dumps(builtins_list),
        "{SAFE_COLLECTIONS_JSON}": json.dumps(sorted(_SHARED_WHITELIST["collections"])),
        "{SAFE_CODECS_JSON}": json.dumps(sorted(_SHARED_WHITELIST["_codecs"])),
        "{SAFE_COPYREG_JSON}": json.dumps(sorted(_SHARED_WHITELIST["copyreg"])),
    }
    rendered = _DECOMPILE_HELPER_TEMPLATE
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def _run_decompile_with_game_python(
    python_path: Path,
    renpy_base: Path,
    rpyc_files: list[Path],
    output_dir: Path,
    timeout: int = 300,
) -> dict[str, str]:
    """Run decompilation using the game's bundled Python.

    Returns dict mapping rpyc_path_str → rpy_code_str (only successes).
    Failures are logged as warnings.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        script_path = tmpdir / "_decompile_helper.py"
        result_path = tmpdir / "_results.json"

        script_path.write_text(_render_decompile_helper(), encoding="utf-8")

        manifest = {
            "files": [str(p) for p in rpyc_files],
            "output": str(result_path),
        }
        manifest_json = json.dumps(manifest, ensure_ascii=False)

        # Build environment — ensure renpy is importable
        env = os.environ.copy()
        renpy_base_str = str(renpy_base)
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = renpy_base_str + os.pathsep + env["PYTHONPATH"]
        else:
            env["PYTHONPATH"] = renpy_base_str

        cmd = [str(python_path), str(script_path), manifest_json]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                cwd=str(renpy_base),
            )
        except subprocess.TimeoutExpired:
            raise DecompileError(f"反编译超时（{timeout}秒）。游戏可能过大或 Python 解释器无响应。")
        except FileNotFoundError:
            raise NoRenpyRuntime(f"无法执行 Python 解释器: {python_path}")

        if proc.returncode != 0:
            stderr = proc.stderr[:500] if proc.stderr else "(无错误输出)"
            logger.warning("[RPYC] 游戏 Python 返回非零退出码 %d: %s", proc.returncode, stderr)

        if not result_path.is_file():
            stderr = proc.stderr[:500] if proc.stderr else "(无错误输出)"
            raise DecompileError(f"反编译辅助脚本未产生输出。stderr: {stderr}")

        # Round 45 audit-tail: 50 MB cap on the subprocess-produced
        # result JSON.  Prevents a runaway helper (e.g. a game with
        # thousands of MB-scale .rpyc files) from OOMing the host when
        # we json.loads the whole file at once.  See r44 security audit.
        try:
            result_size = result_path.stat().st_size
        except OSError:
            result_size = 0
        if result_size > _MAX_RPYC_RESULT_SIZE:
            raise DecompileError(
                f"反编译辅助脚本输出过大 ({result_size} 字节 > "
                f"{_MAX_RPYC_RESULT_SIZE} 字节上限)。游戏可能异常，"
                f"或 helper 脚本产生了意外输出。"
            )

        results_raw = json.loads(result_path.read_text(encoding="utf-8"))

    successes: dict[str, str] = {}
    for rpyc_path_str, result in results_raw.items():
        if result.get("ok"):
            successes[rpyc_path_str] = result["code"]
        else:
            logger.warning(
                "[RPYC] 反编译失败 %s: %s", rpyc_path_str, result.get("error", "unknown")
            )

    return successes


# Tier 2 chain extracted to tools/_rpyc_tier2.py in round 40.
# Re-exported below so callers / tests that used to import these
# symbols from tools.rpyc_decompiler continue to work.
from tools._rpyc_tier2 import (
    extract_strings_from_rpyc,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def decompile_game(
    game_dir: Path,
    output_dir: Optional[Path] = None,
    *,
    timeout: int = 300,
    force: bool = False,
) -> Tuple[List[Path], List[Path]]:
    """Decompile all .rpyc files in a game directory (Tier 1).

    Requires the game to have a complete Ren'Py runtime (lib/ + renpy/).

    Args:
        game_dir: Path to the game directory (or its parent project dir).
        output_dir: Where to write .rpy files (default: alongside .rpyc).
        timeout: Max seconds for the subprocess.
        force: Overwrite existing .rpy files.

    Returns:
        (succeeded_paths, failed_paths) — lists of .rpy file Paths.

    Raises:
        NoRenpyRuntime: If no bundled Python found.
    """
    python_path = _find_renpy_python(game_dir)
    if python_path is None:
        # Try parent directory (game_dir might be 'game/' subfolder)
        if game_dir.name == "game":
            python_path = _find_renpy_python(game_dir.parent)
        if python_path is None:
            raise NoRenpyRuntime(
                f"未在 {game_dir} 找到 Ren'Py 捆绑的 Python 解释器。"
                f"请确认游戏目录包含完整的 lib/ 目录。"
            )
        # Adjust: the project root is the parent
        renpy_base = _find_renpy_base(game_dir.parent)
    else:
        renpy_base = _find_renpy_base(game_dir)

    if renpy_base is None:
        raise NoRenpyRuntime("未找到 renpy/ 模块目录。请确认游戏目录结构完整。")

    # Collect .rpyc files
    rpyc_files: list[Path] = []
    search_dir = game_dir if game_dir.name == "game" else game_dir / "game"
    if not search_dir.is_dir():
        search_dir = game_dir

    for p in search_dir.rglob("*.rpyc"):
        # Skip if .rpy already exists and not forcing
        rpy_path = p.with_suffix(".rpy")
        if rpy_path.exists() and not force:
            continue
        rpyc_files.append(p)

    # Also collect .rpymc files
    for p in search_dir.rglob("*.rpymc"):
        rpym_path = p.with_suffix(".rpym")
        if rpym_path.exists() and not force:
            continue
        rpyc_files.append(p)

    if not rpyc_files:
        logger.info("[RPYC] 没有需要反编译的 .rpyc 文件")
        return [], []

    logger.info("[RPYC] 找到 %d 个 .rpyc 文件，使用 %s 进行反编译", len(rpyc_files), python_path)

    # Run decompilation
    successes = _run_decompile_with_game_python(
        python_path,
        renpy_base,
        rpyc_files,
        output_dir or search_dir,
        timeout,
    )

    succeeded: list[Path] = []
    failed: list[Path] = []

    for rpyc_path in rpyc_files:
        rpyc_str = str(rpyc_path)
        if rpyc_str in successes:
            # Determine output path
            if output_dir:
                rel = rpyc_path.relative_to(search_dir)
                rpy_path = output_dir / rel.with_suffix(
                    ".rpy" if rpyc_path.suffix == ".rpyc" else ".rpym"
                )
            else:
                rpy_path = rpyc_path.with_suffix(".rpy" if rpyc_path.suffix == ".rpyc" else ".rpym")

            rpy_path.parent.mkdir(parents=True, exist_ok=True)
            rpy_path.write_text(successes[rpyc_str], encoding="utf-8")
            succeeded.append(rpy_path)
            logger.debug("[RPYC] 已反编译: %s", rpy_path)
        else:
            failed.append(rpyc_path)

    logger.info("[RPYC] 反编译完成: 成功 %d, 失败 %d", len(succeeded), len(failed))
    return succeeded, failed


def extract_strings_standalone(
    game_dir: Path,
    output_json: Optional[Path] = None,
) -> Dict[str, list[dict]]:
    """Extract translatable strings from all .rpyc files (Tier 2 fallback).

    Does not require Ren'Py runtime.  Produces a JSON manifest of
    translatable strings rather than .rpy source code.

    Args:
        game_dir: Directory containing .rpyc files.
        output_json: If provided, write results to this JSON file.

    Returns:
        Dict mapping relative_path → list of string entries.
    """
    search_dir = game_dir if game_dir.name == "game" else game_dir / "game"
    if not search_dir.is_dir():
        search_dir = game_dir

    rpyc_files = sorted(search_dir.rglob("*.rpyc"))
    rpyc_files.extend(sorted(search_dir.rglob("*.rpymc")))

    if not rpyc_files:
        logger.info("[RPYC] 未找到 .rpyc 文件")
        return {}

    logger.info("[RPYC] 独立模式: 提取 %d 个 .rpyc 文件的文本", len(rpyc_files))

    all_strings: Dict[str, list[dict]] = {}
    total_count = 0

    for rpyc_path in rpyc_files:
        try:
            rel = rpyc_path.relative_to(search_dir)
        except ValueError:
            rel = rpyc_path
        strings = extract_strings_from_rpyc(rpyc_path)
        if strings:
            all_strings[str(rel)] = strings
            total_count += len(strings)

    logger.info("[RPYC] 提取完成: %d 个文件, %d 条文本", len(all_strings), total_count)

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(all_strings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[RPYC] 结果已写入: %s", output_json)

    return all_strings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpyc_decompiler",
        description="反编译 Ren'Py .rpyc 文件（支持 Tier 1 游戏 Python / Tier 2 独立模式）",
    )
    parser.add_argument(
        "game_dir",
        help="游戏目录路径（包含 game/ 子目录或直接包含 .rpyc 文件）",
    )
    parser.add_argument(
        "--outdir",
        "-o",
        default=None,
        help="输出目录（默认: .rpyc 文件所在目录）",
    )
    parser.add_argument(
        "--fallback",
        action="store_true",
        help="强制使用 Tier 2 独立模式（不需要 Ren'Py 运行时）",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Tier 2 模式的 JSON 输出文件路径",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="覆盖已存在的 .rpy 文件",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Tier 1 反编译超时秒数（默认: 300）",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="跳过法律确认提示",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns 0 on success, 1 on error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    game_dir = Path(args.game_dir)
    if not game_dir.is_dir():
        logger.error("目录不存在: %s", game_dir)
        return 1

    # Legal confirmation
    if not args.confirm:
        print("=" * 60)
        print("此工具将反编译 .rpyc 文件。")
        print("请确认您有权对目标游戏进行此操作。")
        print("部分游戏开发者明确禁止反编译，风险由用户承担。")
        print("=" * 60)
        try:
            response = input("继续请按回车，取消请按 Ctrl+C: ")
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return 0

    outdir = Path(args.outdir) if args.outdir else None

    if args.fallback:
        # Tier 2
        json_out = (
            Path(args.json_out)
            if args.json_out
            else (outdir / "rpyc_strings.json" if outdir else game_dir / "rpyc_strings.json")
        )
        strings = extract_strings_standalone(game_dir, json_out)
        total = sum(len(v) for v in strings.values())
        print(f"Tier 2 提取完成: {len(strings)} 个文件, {total} 条文本 → {json_out}")
        return 0

    # Tier 1 (with fallback to Tier 2)
    try:
        succeeded, failed = decompile_game(
            game_dir,
            outdir,
            timeout=args.timeout,
            force=args.force,
        )
        print(f"Tier 1 反编译完成: 成功 {len(succeeded)}, 失败 {len(failed)}")

        if failed:
            print("\n以下文件反编译失败:")
            for p in failed[:20]:
                print(f"  {p}")
            if len(failed) > 20:
                print(f"  ... 及其他 {len(failed) - 20} 个文件")

        return 0 if not failed else 1

    except NoRenpyRuntime as exc:
        logger.warning("[RPYC] Tier 1 不可用: %s", exc)
        logger.info("[RPYC] 自动降级到 Tier 2（独立文本提取）...")

        json_out = (
            Path(args.json_out)
            if args.json_out
            else (outdir / "rpyc_strings.json" if outdir else game_dir / "rpyc_strings.json")
        )
        strings = extract_strings_standalone(game_dir, json_out)
        total = sum(len(v) for v in strings.values())
        print(f"Tier 2 提取完成: {len(strings)} 个文件, {total} 条文本 → {json_out}")
        return 0

    except DecompileError as exc:
        logger.error("[RPYC] 反编译错误: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
