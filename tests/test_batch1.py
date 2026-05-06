#!/usr/bin/env python3
"""Tests for Batch 1 features: RPA packer, default language, lint integration, JSON retry."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rpa_packer import (
    RPAPackError,
    pack_rpa,
    collect_files_for_packing,
    verify_archive,
)
from tools.rpa_unpacker import list_rpa, unpack_rpa
from pipeline.stages import _generate_default_language


# ============================================================
# RPA Packer tests
# ============================================================


def test_pack_basic():
    """Basic packing: single file, roundtrip verify."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # Create a file to pack
        src = td / "test.rpy"
        src.write_text('label start:\n    "Hello"\n', encoding="utf-8")

        archive = td / "test.rpa"
        count = pack_rpa({"test.rpy": src}, archive, xor_key=0)
        assert count == 1
        assert archive.exists()

        # Verify by listing
        entries = list_rpa(archive)
        assert len(entries) == 1
        assert "test.rpy" in entries
    print("[OK] test_pack_basic")


def test_pack_roundtrip():
    """Pack and unpack, verify content identical."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # Create multiple files
        content_a = b"Hello World\n"
        content_b = 'label start:\n    mc "你好"\n'.encode("utf-8")

        (td / "src").mkdir()
        (td / "src" / "a.rpy").write_bytes(content_a)
        (td / "src" / "b.rpy").write_bytes(content_b)

        file_map = {
            "tl/chinese/a.rpy": td / "src" / "a.rpy",
            "tl/chinese/b.rpy": td / "src" / "b.rpy",
        }
        archive = td / "test.rpa"
        count = pack_rpa(file_map, archive, xor_key=0x12345678)
        assert count == 2

        # Unpack and verify
        out = td / "unpacked"
        out.mkdir()
        unpack_rpa(archive, out, force=True)

        assert (out / "tl" / "chinese" / "a.rpy").read_bytes() == content_a
        assert (out / "tl" / "chinese" / "b.rpy").read_bytes() == content_b
    print("[OK] test_pack_roundtrip")


def test_pack_random_key():
    """Default random key: pack twice, both readable."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "file.rpy"
        src.write_text("test content", encoding="utf-8")

        a1 = td / "a1.rpa"
        a2 = td / "a2.rpa"
        pack_rpa({"file.rpy": src}, a1)  # random key
        pack_rpa({"file.rpy": src}, a2)  # different random key

        # Both should be listable
        assert len(list_rpa(a1)) == 1
        assert len(list_rpa(a2)) == 1

        # Keys should differ (read headers)
        h1 = a1.read_bytes()[:51]
        h2 = a2.read_bytes()[:51]
        # Extremely unlikely to be identical with random keys
        # (but not impossible, so we just check they're readable)
    print("[OK] test_pack_random_key")


def test_pack_nested_dirs():
    """Pack files with nested directory structure."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "src"
        (src / "tl" / "chinese" / "sub").mkdir(parents=True)
        (src / "tl" / "chinese" / "script.rpy").write_text("s1", encoding="utf-8")
        (src / "tl" / "chinese" / "sub" / "deep.rpy").write_text("s2", encoding="utf-8")

        file_map = {
            "tl/chinese/script.rpy": src / "tl" / "chinese" / "script.rpy",
            "tl/chinese/sub/deep.rpy": src / "tl" / "chinese" / "sub" / "deep.rpy",
        }
        archive = td / "test.rpa"
        count = pack_rpa(file_map, archive, xor_key=0)
        assert count == 2

        entries = list_rpa(archive)
        assert "tl/chinese/script.rpy" in entries
        assert "tl/chinese/sub/deep.rpy" in entries
    print("[OK] test_pack_nested_dirs")


def test_pack_empty_raises():
    """Packing empty file_map raises RPAPackError."""
    with tempfile.TemporaryDirectory() as td:
        try:
            pack_rpa({}, Path(td) / "empty.rpa")
            assert False, "should have raised"
        except RPAPackError:
            pass
    print("[OK] test_pack_empty_raises")


def test_pack_missing_file_skipped():
    """Missing files are skipped, but at least one valid file required."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "real.rpy"
        src.write_text("content", encoding="utf-8")

        archive = td / "test.rpa"
        count = pack_rpa(
            {
                "real.rpy": src,
                "ghost.rpy": td / "nonexistent.rpy",
            },
            archive,
            xor_key=0,
        )
        assert count == 1
        entries = list_rpa(archive)
        assert "real.rpy" in entries
        assert "ghost.rpy" not in entries
    print("[OK] test_pack_missing_file_skipped")


def test_pack_unicode_paths():
    """Pack files with Unicode characters in paths."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "中文脚本.rpy"
        src.write_text("你好世界", encoding="utf-8")

        archive = td / "test.rpa"
        count = pack_rpa({"tl/chinese/中文脚本.rpy": src}, archive, xor_key=0)
        assert count == 1

        out = td / "out"
        out.mkdir()
        unpack_rpa(archive, out, force=True)
        assert (out / "tl" / "chinese" / "中文脚本.rpy").read_text(encoding="utf-8") == "你好世界"
    print("[OK] test_pack_unicode_paths")


def test_pack_verify():
    """verify_archive succeeds on valid archive, fails on count mismatch."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "a.rpy"
        src.write_text("test", encoding="utf-8")

        archive = td / "test.rpa"
        pack_rpa({"a.rpy": src}, archive, xor_key=0)

        assert verify_archive(archive, 1) is True
        assert verify_archive(archive, 99) is False
    print("[OK] test_pack_verify")


def test_pack_large_file():
    """Pack a relatively large file (1 MB) to test offset handling."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        data = b"A" * (1024 * 1024)
        src = td / "big.bin"
        src.write_bytes(data)

        archive = td / "big.rpa"
        pack_rpa({"big.bin": src}, archive, xor_key=0xCAFEBABE)

        out = td / "out"
        out.mkdir()
        unpack_rpa(archive, out, force=True)
        assert (out / "big.bin").read_bytes() == data
    print("[OK] test_pack_large_file")


def test_collect_files():
    """collect_files_for_packing finds tl/ files and fonts."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        game = td / "game"
        (game / "tl" / "chinese").mkdir(parents=True)
        (game / "tl" / "chinese" / "script.rpy").write_text("s", encoding="utf-8")
        (game / "myfont.ttf").write_bytes(b"\x00\x01")
        (game / "default_language.rpy").write_text("init", encoding="utf-8")

        fm = collect_files_for_packing(td, "chinese")
        assert "tl/chinese/script.rpy" in fm
        assert "myfont.ttf" in fm
        assert "default_language.rpy" in fm
    print("[OK] test_collect_files")


# ============================================================
# Default language tests
# ============================================================


def test_default_language_basic():
    """Generates correct default_language.rpy for zh."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        result = _generate_default_language(td, "zh")
        assert result is True
        content = (td / "default_language.rpy").read_text(encoding="utf-8")
        assert 'config.default_language = "chinese"' in content
    print("[OK] test_default_language_basic")


def test_default_language_ja():
    """Generates correct default_language.rpy for Japanese."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        result = _generate_default_language(td, "ja")
        assert result is True
        content = (td / "default_language.rpy").read_text(encoding="utf-8")
        assert 'config.default_language = "japanese"' in content
    print("[OK] test_default_language_ja")


def test_default_language_ko():
    """Generates correct default_language.rpy for Korean."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        result = _generate_default_language(td, "ko")
        assert result is True
        content = (td / "default_language.rpy").read_text(encoding="utf-8")
        assert 'config.default_language = "korean"' in content
    print("[OK] test_default_language_ko")


def test_default_language_zh_tw():
    """Generates correct default_language.rpy for Traditional Chinese."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        result = _generate_default_language(td, "zh-tw")
        assert result is True
        content = (td / "default_language.rpy").read_text(encoding="utf-8")
        assert 'config.default_language = "traditional_chinese"' in content
    print("[OK] test_default_language_zh_tw")


def test_default_language_no_overwrite():
    """Does not overwrite existing default_language.rpy."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        existing = td / "default_language.rpy"
        existing.write_text("custom config", encoding="utf-8")

        result = _generate_default_language(td, "zh")
        assert result is False
        assert existing.read_text(encoding="utf-8") == "custom config"
    print("[OK] test_default_language_no_overwrite")


def test_pack_header_format():
    """Packed archive starts with RPA-3.0 magic bytes."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "test.rpy"
        src.write_text("content", encoding="utf-8")
        archive = td / "test.rpa"
        pack_rpa({"test.rpy": src}, archive, xor_key=0)

        header = archive.read_bytes()[:8]
        assert header == b"RPA-3.0 ", f"Header mismatch: {header!r}"
    print("[OK] test_pack_header_format")


# ============================================================
# JSON parse failure retry test
# ============================================================


def test_should_retry_json_parse_failure():
    """returned=0 with expected>0 and no error triggers split retry."""
    from core.translation_utils import ChunkResult
    from translators.direct import _should_retry

    # JSON parse returned nothing, expected 10 items
    cr = ChunkResult(part=1, expected=10, returned=0)
    should, needs_split = _should_retry(cr)
    assert should is True
    assert needs_split is True

    # Normal case: returned matches expected
    cr2 = ChunkResult(part=1, expected=10, returned=10)
    should2, needs_split2 = _should_retry(cr2)
    assert should2 is False
    assert needs_split2 is False
    print("[OK] test_should_retry_json_parse_failure")


# ============================================================
# Lint integration test
# ============================================================


def test_lint_repair_unavailable():
    """_run_lint_repair_phase handles unavailable lint gracefully."""
    from pipeline.stages import _run_lint_repair_phase

    with tempfile.TemporaryDirectory() as td:
        report = {"stages": {}}
        _run_lint_repair_phase(Path(td), report)
        assert report["stages"]["lint_repair"]["skipped"] is True
    print("[OK] test_lint_repair_unavailable")


# ============================================================
# Runner
# ============================================================

ALL_TESTS = [
    # RPA packer (10)
    test_pack_basic,
    test_pack_roundtrip,
    test_pack_random_key,
    test_pack_nested_dirs,
    test_pack_empty_raises,
    test_pack_missing_file_skipped,
    test_pack_unicode_paths,
    test_pack_verify,
    test_pack_large_file,
    test_collect_files,
    # Default language (5)
    test_default_language_basic,
    test_default_language_ja,
    test_default_language_ko,
    test_default_language_zh_tw,
    test_default_language_no_overwrite,
    # RPA header format (1)
    test_pack_header_format,
    # JSON retry (1)
    test_should_retry_json_parse_failure,
    # Lint integration (1)
    test_lint_repair_unavailable,
]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for t in ALL_TESTS:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    total = passed + failed
    if failed:
        print(f"\n{passed}/{total} PASSED, {failed} FAILED")
        sys.exit(1)
    else:
        print(f"\nALL {total} BATCH-1 TESTS PASSED")
