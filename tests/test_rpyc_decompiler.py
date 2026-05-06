#!/usr/bin/env python3
"""Tests for tools.rpyc_decompiler — RPYC binary format and text extraction."""

import io
import json
import pickle
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rpyc_decompiler import (
    RPYC2_HEADER,
    _RestrictedUnpickler,
    _detect_renpy_version,
    _find_renpy_python,
    _read_rpyc_data,
    _safe_unpickle,
    extract_strings_from_rpyc,
    extract_strings_standalone,
)


# ---------------------------------------------------------------------------
# Helpers: build synthetic .rpyc files
# ---------------------------------------------------------------------------


def _make_rpyc2(ast_data: bytes) -> bytes:
    """Build a minimal RPYC2 file with AST data in slot 1."""
    compressed = zlib.compress(ast_data)

    # Header: RPYC2_HEADER + slot entries
    # Slot entry: (slot_id: u32, start: u32, length: u32)
    # End marker: (0, 0, 0)

    data_start = len(RPYC2_HEADER) + 12 + 12  # header + slot1 + end_marker

    slot1 = struct.pack("III", 1, data_start, len(compressed))
    end_marker = struct.pack("III", 0, 0, 0)

    return RPYC2_HEADER + slot1 + end_marker + compressed


def _make_legacy_rpyc(ast_data: bytes) -> bytes:
    """Build a legacy (pre-RPYC2) file — just zlib-compressed data."""
    return zlib.compress(ast_data)


def _make_dummy_ast(
    say_texts: list[tuple[str, str]],
    menu_items: list[str] = None,
    translate_strings: list[tuple[str, str]] = None,
) -> bytes:
    """Build pickled AST that mimics real Ren'Py output.

    Uses pickletools to manually build a pickle stream that references
    renpy.ast classes — these will be intercepted by RestrictedUnpickler
    and replaced with DummyClass stubs at load time.
    """
    # We use pickle opcodes directly to create objects whose __module__
    # is "renpy.ast" without needing the real module at pickle time.
    # Strategy: build via a custom pickler that registers fake classes
    # temporarily in sys.modules.

    import types

    # Create a temporary fake renpy.ast module
    fake_renpy = types.ModuleType("renpy")
    fake_ast = types.ModuleType("renpy.ast")

    class Say:
        __module__ = "renpy.ast"
        __qualname__ = "Say"

    class Menu:
        __module__ = "renpy.ast"
        __qualname__ = "Menu"

    class TranslateString:
        __module__ = "renpy.ast"
        __qualname__ = "TranslateString"

    fake_ast.Say = Say
    fake_ast.Menu = Menu
    fake_ast.TranslateString = TranslateString
    fake_renpy.ast = fake_ast

    # Temporarily inject into sys.modules
    saved = {}
    for mod_name in ("renpy", "renpy.ast"):
        saved[mod_name] = sys.modules.get(mod_name)

    sys.modules["renpy"] = fake_renpy
    sys.modules["renpy.ast"] = fake_ast

    try:
        stmts = []
        for who, what in say_texts:
            node = Say()
            node.what = what
            node.who = who
            stmts.append(node)

        if menu_items:
            menu = Menu()
            menu.items = [(text, "True", []) for text in menu_items]
            stmts.append(menu)

        if translate_strings:
            for old, new in translate_strings:
                ts = TranslateString()
                ts.old = old
                ts.new = new
                ts.language = "chinese"
                stmts.append(ts)

        data = pickle.dumps(("checksum_placeholder", stmts), protocol=2)
    finally:
        # Restore sys.modules
        for mod_name, original in saved.items():
            if original is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = original

    return data


# ---------------------------------------------------------------------------
# Tests: RPYC binary format
# ---------------------------------------------------------------------------


def test_read_rpyc2_slot1():
    """Read slot 1 data from a RPYC2 file."""
    original = b"test AST data for slot 1"
    rpyc_data = _make_rpyc2(original)

    f = io.BytesIO(rpyc_data)
    result = _read_rpyc_data(f, slot=1)
    assert result == original
    print("[OK] test_read_rpyc2_slot1")


def test_read_rpyc2_missing_slot():
    """Requesting a non-existent slot returns None."""
    rpyc_data = _make_rpyc2(b"some data")
    f = io.BytesIO(rpyc_data)
    result = _read_rpyc_data(f, slot=2)
    assert result is None
    print("[OK] test_read_rpyc2_missing_slot")


def test_read_legacy_rpyc():
    """Read data from legacy (pre-RPYC2) format."""
    original = b"legacy AST data"
    rpyc_data = _make_legacy_rpyc(original)

    f = io.BytesIO(rpyc_data)
    result = _read_rpyc_data(f, slot=1)
    assert result == original
    print("[OK] test_read_legacy_rpyc")


def test_read_legacy_rpyc_slot2():
    """Legacy format only has slot 1."""
    rpyc_data = _make_legacy_rpyc(b"data")
    f = io.BytesIO(rpyc_data)
    result = _read_rpyc_data(f, slot=2)
    assert result is None
    print("[OK] test_read_legacy_rpyc_slot2")


def test_read_corrupted_rpyc():
    """Corrupted zlib data returns None."""
    # Valid RPYC2 header but garbage data
    bad_data = RPYC2_HEADER + struct.pack("III", 1, 34, 10) + struct.pack("III", 0, 0, 0)
    bad_data += b"NOT_VALID_Z"  # garbage at offset 34

    f = io.BytesIO(bad_data)
    result = _read_rpyc_data(f, slot=1)
    assert result is None
    print("[OK] test_read_corrupted_rpyc")


# ---------------------------------------------------------------------------
# Tests: RestrictedUnpickler
# ---------------------------------------------------------------------------


def test_restricted_unpickler():
    """RestrictedUnpickler substitutes renpy classes with DummyClass."""
    ast_data = _make_dummy_ast([("mc", "Hello world")])
    unpickled = _safe_unpickle(ast_data)
    assert isinstance(unpickled, tuple)
    assert len(unpickled) == 2
    stmts = unpickled[1]
    assert len(stmts) == 1
    assert stmts[0].what == "Hello world"
    assert stmts[0].who == "mc"
    print("[OK] test_restricted_unpickler")


# ---------------------------------------------------------------------------
# Tests: text extraction from AST
# ---------------------------------------------------------------------------


def test_extract_say_statements():
    """Extract say statement text from a .rpyc file."""
    ast_data = _make_dummy_ast(
        [
            ("mc", "Hello, how are you?"),
            ("girl", "I'm fine, thanks!"),
            (None, "The narrator speaks."),
        ]
    )
    rpyc_data = _make_rpyc2(ast_data)

    with tempfile.NamedTemporaryFile(suffix=".rpyc", delete=False) as f:
        f.write(rpyc_data)
        tmp = Path(f.name)

    try:
        strings = extract_strings_from_rpyc(tmp)
        assert len(strings) == 3

        # Check say entries
        say_entries = [s for s in strings if s["type"] == "say"]
        assert len(say_entries) == 3
        assert say_entries[0]["text"] == "Hello, how are you?"
        assert say_entries[0]["who"] == "mc"
        assert say_entries[1]["text"] == "I'm fine, thanks!"
        assert say_entries[2]["text"] == "The narrator speaks."
        print("[OK] test_extract_say_statements")
    finally:
        tmp.unlink()


def test_extract_menu_items():
    """Extract menu choice text from a .rpyc file."""
    ast_data = _make_dummy_ast(
        say_texts=[],
        menu_items=["Go to the park", "Stay home", "Call a friend"],
    )
    rpyc_data = _make_rpyc2(ast_data)

    with tempfile.NamedTemporaryFile(suffix=".rpyc", delete=False) as f:
        f.write(rpyc_data)
        tmp = Path(f.name)

    try:
        strings = extract_strings_from_rpyc(tmp)
        menu_entries = [s for s in strings if s["type"] == "menu"]
        assert len(menu_entries) == 3
        assert menu_entries[0]["text"] == "Go to the park"
        assert menu_entries[1]["text"] == "Stay home"
        assert menu_entries[2]["text"] == "Call a friend"
        print("[OK] test_extract_menu_items")
    finally:
        tmp.unlink()


def test_extract_translate_strings():
    """Extract translate string entries from a .rpyc file."""
    ast_data = _make_dummy_ast(
        say_texts=[],
        translate_strings=[
            ("Start", "开始"),
            ("Settings", "设置"),
        ],
    )
    rpyc_data = _make_rpyc2(ast_data)

    with tempfile.NamedTemporaryFile(suffix=".rpyc", delete=False) as f:
        f.write(rpyc_data)
        tmp = Path(f.name)

    try:
        strings = extract_strings_from_rpyc(tmp)
        ts_entries = [s for s in strings if s["type"] == "translate_string"]
        assert len(ts_entries) == 2
        assert ts_entries[0]["old"] == "Start"
        assert ts_entries[0]["new"] == "开始"
        assert ts_entries[0]["language"] == "chinese"
        print("[OK] test_extract_translate_strings")
    finally:
        tmp.unlink()


def test_extract_mixed_content():
    """Extract from a .rpyc with mixed content types."""
    ast_data = _make_dummy_ast(
        say_texts=[("mc", "Choose wisely.")],
        menu_items=["Option A", "Option B"],
        translate_strings=[("Quit", "退出")],
    )
    rpyc_data = _make_rpyc2(ast_data)

    with tempfile.NamedTemporaryFile(suffix=".rpyc", delete=False) as f:
        f.write(rpyc_data)
        tmp = Path(f.name)

    try:
        strings = extract_strings_from_rpyc(tmp)
        types = {s["type"] for s in strings}
        assert "say" in types
        assert "menu" in types
        assert "translate_string" in types
        print("[OK] test_extract_mixed_content")
    finally:
        tmp.unlink()


def test_extract_empty_rpyc():
    """Extract from a .rpyc with no translatable content."""
    ast_data = _make_dummy_ast(say_texts=[])
    rpyc_data = _make_rpyc2(ast_data)

    with tempfile.NamedTemporaryFile(suffix=".rpyc", delete=False) as f:
        f.write(rpyc_data)
        tmp = Path(f.name)

    try:
        strings = extract_strings_from_rpyc(tmp)
        assert strings == []
        print("[OK] test_extract_empty_rpyc")
    finally:
        tmp.unlink()


def test_extract_unicode_content():
    """Extract Unicode text (CJK, emoji) from a .rpyc file."""
    ast_data = _make_dummy_ast(
        [
            ("主角", "你好世界！这是一个测试。"),
            ("narrator", "日本語テスト"),
        ]
    )
    rpyc_data = _make_rpyc2(ast_data)

    with tempfile.NamedTemporaryFile(suffix=".rpyc", delete=False) as f:
        f.write(rpyc_data)
        tmp = Path(f.name)

    try:
        strings = extract_strings_from_rpyc(tmp)
        assert len(strings) == 2
        assert strings[0]["text"] == "你好世界！这是一个测试。"
        assert strings[0]["who"] == "主角"
        assert strings[1]["text"] == "日本語テスト"
        print("[OK] test_extract_unicode_content")
    finally:
        tmp.unlink()


# ---------------------------------------------------------------------------
# Tests: standalone extraction (directory mode)
# ---------------------------------------------------------------------------


def test_extract_strings_standalone():
    """Extract strings from a directory of .rpyc files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        game_dir = tmpdir / "game"
        game_dir.mkdir()

        # Create two .rpyc files
        ast1 = _make_dummy_ast([("mc", "File 1 text")])
        ast2 = _make_dummy_ast([("girl", "File 2 text")])

        (game_dir / "script.rpyc").write_bytes(_make_rpyc2(ast1))
        (game_dir / "chapter1.rpyc").write_bytes(_make_rpyc2(ast2))

        result = extract_strings_standalone(tmpdir)
        assert len(result) == 2
        total = sum(len(v) for v in result.values())
        assert total == 2
        print("[OK] test_extract_strings_standalone")


def test_extract_strings_standalone_json_output():
    """Write extraction results to JSON file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        game_dir = tmpdir / "game"
        game_dir.mkdir()

        ast_data = _make_dummy_ast([("mc", "Test text")])
        (game_dir / "test.rpyc").write_bytes(_make_rpyc2(ast_data))

        json_out = tmpdir / "output.json"
        result = extract_strings_standalone(tmpdir, output_json=json_out)

        assert json_out.exists()
        loaded = json.loads(json_out.read_text(encoding="utf-8"))
        assert len(loaded) == 1
        # Verify JSON content matches result
        for key in result:
            assert key in loaded
        print("[OK] test_extract_strings_standalone_json_output")


# ---------------------------------------------------------------------------
# Tests: platform detection
# ---------------------------------------------------------------------------


def test_find_renpy_python_not_found():
    """No Python found in empty directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _find_renpy_python(Path(tmpdir))
        assert result is None
        print("[OK] test_find_renpy_python_not_found")


def test_find_renpy_python_with_lib():
    """Find Python executable in simulated lib/ structure."""
    import platform as plat

    system = plat.system().lower()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        lib_dir = tmpdir / "lib"

        if system == "windows":
            py_dir = lib_dir / "py3-windows-x86_64"
            py_dir.mkdir(parents=True)
            py_exe = py_dir / "python.exe"
        elif system == "linux":
            py_dir = lib_dir / "py3-linux-x86_64"
            py_dir.mkdir(parents=True)
            py_exe = py_dir / "python"
        elif system == "darwin":
            py_dir = lib_dir / "py3-mac-universal"
            py_dir.mkdir(parents=True)
            py_exe = py_dir / "python"
        else:
            print(f"[SKIP] test_find_renpy_python_with_lib: unsupported platform {system}")
            return

        py_exe.write_text("fake python")

        result = _find_renpy_python(tmpdir)
        assert result is not None
        assert result.name in ("python.exe", "python")
        print("[OK] test_find_renpy_python_with_lib")


def test_detect_renpy_version():
    """Detect Ren'Py version from Python path patterns."""
    import platform as plat

    system = plat.system().lower()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Test Ren'Py 8.x (py3)
        if system == "windows":
            py3_dir = tmpdir / "lib" / "py3-windows-x86_64"
            exe_name = "python.exe"
        elif system == "linux":
            py3_dir = tmpdir / "lib" / "py3-linux-x86_64"
            exe_name = "python"
        else:
            print(f"[SKIP] test_detect_renpy_version: platform {system}")
            return

        py3_dir.mkdir(parents=True)
        (py3_dir / exe_name).write_text("fake")

        version = _detect_renpy_version(tmpdir)
        assert version == "8"
        print("[OK] test_detect_renpy_version")


def test_whitelist_tier1_tier2_consistent():
    """Tier 1 (helper-script) and Tier 2 (_RestrictedUnpickler) whitelists
    must both derive from ``_SHARED_WHITELIST`` (round 26 H-2).

    Rationale: the previous implementation kept two independent copies of
    ``_SAFE_BUILTINS`` / ``_SAFE_COLLECTIONS`` / ``_SAFE_CODECS`` /
    ``_SAFE_COPYREG`` in sync only by comment.  This test scrapes the
    rendered Tier 1 helper script back out and compares it against Tier 2
    so they can never drift silently again.
    """
    import json as _json
    import re as _re
    from tools.rpyc_decompiler import (
        _SHARED_WHITELIST,
        _WHITELIST_TIER1_PY2_EXTRAS,
        _render_decompile_helper,
    )

    rendered = _render_decompile_helper()

    def _extract(name: str) -> set:
        m = _re.search(rf"{name} = frozenset\((\[[^\]]+\])\)", rendered)
        assert m, f"Tier 1 {name} not found in rendered helper"
        return set(_json.loads(m.group(1)))

    tier1_builtins = _extract("_SAFE_BUILTINS")
    tier1_collections = _extract("_SAFE_COLLECTIONS")
    tier1_codecs = _extract("_SAFE_CODECS")
    tier1_copyreg = _extract("_SAFE_COPYREG")

    # Tier 1 = shared builtins + Py2 extras (long/unicode).
    expected_tier1_builtins = set(_SHARED_WHITELIST["builtins"]) | set(
        _WHITELIST_TIER1_PY2_EXTRAS.get("builtins", [])
    )
    assert tier1_builtins == expected_tier1_builtins, (
        f"Tier 1 builtins drift: expected {expected_tier1_builtins}, got {tier1_builtins}"
    )

    # All other categories must match the shared whitelist exactly.
    assert tier1_collections == set(_SHARED_WHITELIST["collections"])
    assert tier1_codecs == set(_SHARED_WHITELIST["_codecs"])
    assert tier1_copyreg == set(_SHARED_WHITELIST["copyreg"])

    # Tier 2 must match the shared whitelist verbatim (no Py2 extras).
    assert _RestrictedUnpickler._SAFE_BUILTINS == frozenset(_SHARED_WHITELIST["builtins"])
    assert _RestrictedUnpickler._SAFE_COLLECTIONS == frozenset(_SHARED_WHITELIST["collections"])
    assert _RestrictedUnpickler._SAFE_CODECS == frozenset(_SHARED_WHITELIST["_codecs"])
    assert _RestrictedUnpickler._SAFE_COPYREG == frozenset(_SHARED_WHITELIST["copyreg"])

    # The non-builtins categories must be identical between tiers.
    assert tier1_collections == set(_RestrictedUnpickler._SAFE_COLLECTIONS)
    assert tier1_codecs == set(_RestrictedUnpickler._SAFE_CODECS)
    assert tier1_copyreg == set(_RestrictedUnpickler._SAFE_COPYREG)

    # Builtins: Tier 1 should be Tier 2 ∪ Py2 extras.
    assert tier1_builtins == (
        set(_RestrictedUnpickler._SAFE_BUILTINS)
        | set(_WHITELIST_TIER1_PY2_EXTRAS.get("builtins", []))
    )

    print("[OK] test_whitelist_tier1_tier2_consistent")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Binary format tests
    test_read_rpyc2_slot1()
    test_read_rpyc2_missing_slot()
    test_read_legacy_rpyc()
    test_read_legacy_rpyc_slot2()
    test_read_corrupted_rpyc()

    # Unpickler tests
    test_restricted_unpickler()

    # Text extraction tests
    test_extract_say_statements()
    test_extract_menu_items()
    test_extract_translate_strings()
    test_extract_mixed_content()
    test_extract_empty_rpyc()
    test_extract_unicode_content()

    # Standalone directory extraction
    test_extract_strings_standalone()
    test_extract_strings_standalone_json_output()

    # Platform detection
    test_find_renpy_python_not_found()
    test_find_renpy_python_with_lib()
    test_detect_renpy_version()

    # Whitelist sync (round 26 H-2)
    test_whitelist_tier1_tier2_consistent()

    print("\n=== 全部 RPYC 反编译测试通过 ===")
