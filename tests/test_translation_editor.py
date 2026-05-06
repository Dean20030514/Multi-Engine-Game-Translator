#!/usr/bin/env python3
"""Tests for tools.translation_editor — HTML export/import roundtrip."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.translation_editor import (
    export_html,
    import_edits,
    _extract_from_tl_dir,
    _extract_from_db,
    _escape_for_rpy,
)


# ============================================================
# Helpers
# ============================================================


def _make_tl_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


_SAMPLE_TL = """\
translate chinese start_abc12345:
    # game/script.rpy:10
    # e "Hello, world!"
    e ""

translate chinese strings:
    old "Start"
    new ""
"""

_SAMPLE_TL_FILLED = """\
translate chinese start_abc12345:
    # game/script.rpy:10
    # e "Hello, world!"
    e "你好世界"

translate chinese strings:
    old "Start"
    new "开始"
"""


# ============================================================
# Export tests
# ============================================================


def test_export_basic():
    """Export entries to HTML, verify it contains expected content."""
    entries = [
        {
            "source": "tl",
            "file": "game/tl/chinese/script.rpy",
            "line": 4,
            "original": "Hello, world!",
            "translation": "",
            "character": "e",
            "identifier": "start_abc",
            "source_file": "game/script.rpy",
            "source_line": 10,
        },
    ]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "test.html"
        count = export_html(entries, out)
        assert count == 1
        html_content = out.read_text(encoding="utf-8")
        assert "Hello, world!" in html_content
        assert "contenteditable" in html_content
        assert "exportEdits" in html_content
        assert "__METADATA__" not in html_content  # placeholder replaced
    print("[OK] test_export_basic")


def test_export_multiple():
    """Export multiple entries, verify metadata JSON is embedded."""
    entries = [
        {
            "source": "tl",
            "file": "a.rpy",
            "line": 1,
            "original": "One",
            "translation": "壹",
            "character": "",
            "identifier": "id1",
            "source_file": "a.rpy",
            "source_line": 1,
        },
        {
            "source": "tl",
            "file": "a.rpy",
            "line": 5,
            "original": "Two",
            "translation": "",
            "character": "mc",
            "identifier": "id2",
            "source_file": "a.rpy",
            "source_line": 5,
        },
        {
            "source": "db",
            "file": "b.rpy",
            "line": 3,
            "original": "Three",
            "translation": "叁",
            "character": "",
            "identifier": "",
            "source_file": "b.rpy",
            "source_line": 3,
        },
    ]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "multi.html"
        count = export_html(entries, out)
        assert count == 3
        html_content = out.read_text(encoding="utf-8")
        # Verify metadata JSON is parseable
        start = html_content.index('id="metadata">') + len('id="metadata">')
        end = html_content.index("</script>", start)
        meta = json.loads(html_content[start:end])
        assert len(meta) == 3
        assert meta[1]["character"] == "mc"
    print("[OK] test_export_multiple")


def test_export_empty():
    """Export with no entries returns 0."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "empty.html"
        count = export_html([], out)
        assert count == 0
    print("[OK] test_export_empty")


def test_export_html_escaping():
    """Special characters in text are properly HTML-escaped."""
    entries = [
        {
            "source": "tl",
            "file": "a.rpy",
            "line": 1,
            "original": '<script>alert("xss")</script>',
            "translation": "{color=#f00}red{/color}",
            "character": "",
            "identifier": "",
            "source_file": "",
            "source_line": 0,
        },
    ]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "xss.html"
        export_html(entries, out)
        content = out.read_text(encoding="utf-8")
        # The script tag should be escaped in the JSON metadata, not rendered
        assert (
            "<script>alert"
            not in content.split("</head>")[1].split('<script type="application/json"')[0]
        )
    print("[OK] test_export_html_escaping")


# ============================================================
# Extract from tl tests
# ============================================================


def test_extract_from_tl():
    """Extract entries from tl directory using tl_parser."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tl_dir = td / "tl" / "chinese"
        _make_tl_file(tl_dir / "script.rpy", _SAMPLE_TL)

        entries = _extract_from_tl_dir(tl_dir)
        assert len(entries) >= 1  # At least the dialogue entry
        # Check dialogue entry exists
        dialogue = [e for e in entries if e["original"] == "Hello, world!"]
        assert len(dialogue) == 1
        assert dialogue[0]["character"] == "e"
        assert dialogue[0]["source"] == "tl"
    print("[OK] test_extract_from_tl")


def test_extract_from_db():
    """Extract entries from translation_db.json."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        db_data = {
            "version": 1,
            "entries": [
                {
                    "file": "script.rpy",
                    "line": 10,
                    "original": "Hello",
                    "translation": "你好",
                    "status": "ok",
                },
                {
                    "file": "script.rpy",
                    "line": 20,
                    "original": "World",
                    "translation": "",
                    "status": "ok",
                },
            ],
        }
        db_path = td / "translation_db.json"
        db_path.write_text(json.dumps(db_data), encoding="utf-8")

        entries = _extract_from_db(db_path)
        assert len(entries) == 2
        assert entries[0]["original"] == "Hello"
        assert entries[0]["translation"] == "你好"
        assert entries[1]["translation"] == ""
    print("[OK] test_extract_from_db")


# ============================================================
# Import tests
# ============================================================


def test_import_tl_mode():
    """Import edits back into a tl file — replace existing translation."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tl_file = td / "script.rpy"
        tl_file.write_text(_SAMPLE_TL_FILLED, encoding="utf-8")

        edits = [
            {
                "source": "tl",
                "file": str(tl_file),
                "line": 4,  # Line with e "你好世界"
                "original": "Hello, world!",
                "old_translation": "你好世界",
                "new_translation": "你好，世界！",
                "identifier": "start_abc12345",
            },
        ]
        edits_path = td / "edits.json"
        edits_path.write_text(json.dumps(edits), encoding="utf-8")

        result = import_edits(edits_path, create_backup=True)
        assert result["applied"] == 1
        assert result["files_modified"] == 1

        content = tl_file.read_text(encoding="utf-8")
        assert "你好，世界！" in content
        assert "你好世界" not in content

        # Backup created
        assert (tl_file.with_suffix(".rpy.bak")).exists()
    print("[OK] test_import_tl_mode")


def test_import_empty_slot():
    """Import into empty tl slot (replace "")."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tl_file = td / "script.rpy"
        tl_file.write_text(_SAMPLE_TL, encoding="utf-8")

        edits = [
            {
                "source": "tl",
                "file": str(tl_file),
                "line": 4,  # Line with e ""
                "original": "Hello, world!",
                "old_translation": "",
                "new_translation": "你好世界",
            },
        ]
        edits_path = td / "edits.json"
        edits_path.write_text(json.dumps(edits), encoding="utf-8")

        result = import_edits(edits_path)
        assert result["applied"] == 1
        content = tl_file.read_text(encoding="utf-8")
        assert '"你好世界"' in content
    print("[OK] test_import_empty_slot")


def test_import_no_overwrite_backup():
    """Second import does not overwrite existing .bak."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tl_file = td / "script.rpy"
        tl_file.write_text(_SAMPLE_TL, encoding="utf-8")
        bak = tl_file.with_suffix(".rpy.bak")
        bak.write_text("original backup content", encoding="utf-8")

        edits = [
            {
                "source": "tl",
                "file": str(tl_file),
                "line": 4,
                "original": "Hello",
                "old_translation": "",
                "new_translation": "你好",
            }
        ]
        edits_path = td / "edits.json"
        edits_path.write_text(json.dumps(edits), encoding="utf-8")

        import_edits(edits_path)
        assert bak.read_text(encoding="utf-8") == "original backup content"
    print("[OK] test_import_no_overwrite_backup")


def test_import_db_mode():
    """Import edits with source='db' — match original text and replace."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rpy_file = td / "script.rpy"
        rpy_file.write_text(
            'label start:\n    mc "Hello world"\n    mc "Goodbye"\n',
            encoding="utf-8",
        )

        edits = [
            {
                "source": "db",
                "file": str(rpy_file),
                "line": 2,  # Line with "Hello world"
                "original": "Hello world",
                "old_translation": "",
                "new_translation": "你好世界",
            },
        ]
        edits_path = td / "edits.json"
        edits_path.write_text(json.dumps(edits), encoding="utf-8")

        result = import_edits(edits_path)
        assert result["applied"] == 1

        content = rpy_file.read_text(encoding="utf-8")
        assert "你好世界" in content
        assert "Goodbye" in content  # Other lines untouched
    print("[OK] test_import_db_mode")


def test_import_missing_file():
    """Import skips edits for non-existent files."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        edits = [
            {
                "source": "tl",
                "file": str(td / "ghost.rpy"),
                "line": 1,
                "original": "x",
                "old_translation": "",
                "new_translation": "y",
            }
        ]
        edits_path = td / "edits.json"
        edits_path.write_text(json.dumps(edits), encoding="utf-8")

        result = import_edits(edits_path)
        assert result["skipped"] == 1
        assert result["applied"] == 0
    print("[OK] test_import_missing_file")


def test_import_empty_new_translation():
    """Import skips edits with empty new_translation."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tl_file = td / "script.rpy"
        tl_file.write_text(_SAMPLE_TL, encoding="utf-8")

        edits = [
            {
                "source": "tl",
                "file": str(tl_file),
                "line": 4,
                "original": "Hello",
                "old_translation": "",
                "new_translation": "",
            }
        ]
        edits_path = td / "edits.json"
        edits_path.write_text(json.dumps(edits), encoding="utf-8")

        result = import_edits(edits_path)
        assert result["skipped"] == 1
    print("[OK] test_import_empty_new_translation")


# ============================================================
# Utility tests
# ============================================================


def test_escape_for_rpy():
    """Escape quotes and backslashes for Ren'Py strings."""
    assert _escape_for_rpy("hello") == "hello"
    assert _escape_for_rpy('he said "hi"') == 'he said \\"hi\\"'
    assert _escape_for_rpy("path\\to\\file") == "path\\\\to\\\\file"
    print("[OK] test_escape_for_rpy")


# ============================================================
# Round 38 M2 — 50 MB size-cap on editor JSON inputs
# ============================================================


def test_extract_from_db_rejects_oversized_file():
    """Round 38 M2: ``_extract_from_db`` skips db files above the 50 MB
    cap before reading.  Returns an empty list so ``main()`` surfaces
    "No entries found to export" instead of the process OOMing on a
    huge input (attacker-crafted or accidentally-passed).
    """
    with tempfile.TemporaryDirectory() as td:
        big_path = Path(td) / "big_db.json"
        with open(big_path, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        entries = _extract_from_db(big_path)
        assert entries == [], "M2: oversized db file must return empty entries"
    print("[OK] test_extract_from_db_rejects_oversized_file")


def test_import_edits_rejects_oversized_file():
    """Round 38 M2: ``import_edits`` rejects oversized
    ``translation_edits.json`` payloads via the 50 MB cap, returning the
    empty-result shape so the CLI's summary print stays well-formed
    (``0 applied, 0 skipped, 0 files_modified``).
    """
    with tempfile.TemporaryDirectory() as td:
        big_path = Path(td) / "big_edits.json"
        with open(big_path, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        result = import_edits(big_path, create_backup=False)
        assert result == {"applied": 0, "skipped": 0, "files_modified": 0}, (
            "M2: oversized edits file must return empty-result shape"
        )
    print("[OK] test_import_edits_rejects_oversized_file")


# ============================================================
# Runner
# ============================================================

ALL_TESTS = [
    test_export_basic,
    test_export_multiple,
    test_export_empty,
    test_export_html_escaping,
    test_extract_from_tl,
    test_extract_from_db,
    test_import_tl_mode,
    test_import_empty_slot,
    test_import_db_mode,
    test_import_no_overwrite_backup,
    test_import_missing_file,
    test_import_empty_new_translation,
    test_escape_for_rpy,
    # Round 38 M2 — 50 MB size-cap on editor JSON inputs
    test_extract_from_db_rejects_oversized_file,
    test_import_edits_rejects_oversized_file,
    # Round 33-37 v2 envelope / side-by-side / M4 / M5 tests moved to
    # ``tests/test_translation_editor_v2.py`` in round 38 to keep this
    # file under the CLAUDE.md 800-line soft limit.  Run both files
    # standalone (or the v2 file alone after a v2-surface change).
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
        print(f"\nALL {total} TRANSLATION EDITOR TESTS PASSED")
