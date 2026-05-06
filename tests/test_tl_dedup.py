#!/usr/bin/env python3
"""Tests for tl-mode cross-file translation deduplication."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from translators.tl_parser import DialogueEntry, StringEntry
from translators.tl_mode import (
    dedup_tl_entries,
    apply_dedup_translations,
)


def _make_dlg(
    identifier: str,
    original: str,
    character: str = "",
    tl_file: str = "tl/chinese/test.rpy",
    tl_line: int = 1,
) -> DialogueEntry:
    return DialogueEntry(
        identifier=identifier,
        original=original,
        translation="",
        character=character,
        source_file="game/test.rpy",
        source_line=1,
        tl_file=tl_file,
        tl_line=tl_line,
        block_start_line=tl_line - 1,
    )


def _make_str(old: str, tl_file: str = "tl/chinese/test.rpy", tl_line: int = 1) -> StringEntry:
    return StringEntry(
        old=old,
        new="",
        source_file="game/test.rpy",
        source_line=1,
        tl_file=tl_file,
        tl_line=tl_line,
        block_start_line=tl_line - 1,
    )


# ---------------------------------------------------------------------------
# dedup_tl_entries tests
# ---------------------------------------------------------------------------


def test_dedup_basic():
    """Duplicate long dialogues are collapsed; short ones preserved."""
    long_text = "This is a long sentence that should be deduplicated across files."
    entries = [
        _make_dlg("id1", long_text, "mc", "file1.rpy", 10),
        _make_dlg("id2", long_text, "mc", "file2.rpy", 20),
        _make_dlg("id3", long_text, "mc", "file3.rpy", 30),
        _make_dlg("id4", "Hmm...", "mc", "file1.rpy", 40),  # short
        _make_dlg("id5", "Hmm...", "mc", "file2.rpy", 50),  # short — NOT deduped
    ]
    result = dedup_tl_entries(entries)

    # 3 long entries → 1 unique + 2 skipped
    # 2 short entries → 2 unique (no dedup)
    assert len(result.unique_entries) == 3  # 1 long + 2 short
    assert result.skipped_count == 2
    assert result.total_before == 5
    assert len(result.dedup_groups) == 1

    # Check that the group has the right structure
    key = ("mc", long_text)
    first_entry, dups = result.dedup_groups[key]
    assert first_entry.identifier == "id1"
    assert len(dups) == 2
    assert dups[0].identifier == "id2"
    assert dups[1].identifier == "id3"
    print("[OK] test_dedup_basic")


def test_dedup_different_speakers():
    """Same text with different speakers are NOT deduplicated."""
    long_text = "You should definitely go to the store and buy some groceries."
    entries = [
        _make_dlg("id1", long_text, "mc", "file1.rpy"),
        _make_dlg("id2", long_text, "girl", "file2.rpy"),
    ]
    result = dedup_tl_entries(entries)
    assert len(result.unique_entries) == 2
    assert result.skipped_count == 0
    print("[OK] test_dedup_different_speakers")


def test_dedup_string_entries():
    """StringEntry dedup works (speaker is always empty)."""
    long_text = "You already gave her flowers today. Come back tomorrow."
    entries = [
        _make_str(long_text, "file1.rpy", 10),
        _make_str(long_text, "file2.rpy", 20),
        _make_str(long_text, "file3.rpy", 30),
    ]
    result = dedup_tl_entries(entries)
    assert len(result.unique_entries) == 1
    assert result.skipped_count == 2
    print("[OK] test_dedup_string_entries")


def test_dedup_no_duplicates():
    """All unique entries — nothing to dedup."""
    entries = [
        _make_dlg("id1", "A" * 50, "mc"),
        _make_dlg("id2", "B" * 50, "mc"),
        _make_dlg("id3", "C" * 50, "girl"),
    ]
    result = dedup_tl_entries(entries)
    assert len(result.unique_entries) == 3
    assert result.skipped_count == 0
    assert len(result.dedup_groups) == 0
    print("[OK] test_dedup_no_duplicates")


def test_dedup_threshold():
    """Entries shorter than threshold are never deduplicated."""
    short = "Short line"  # < 40 chars
    entries = [
        _make_dlg("id1", short, "mc", "file1.rpy"),
        _make_dlg("id2", short, "mc", "file2.rpy"),
    ]
    result = dedup_tl_entries(entries, min_length=40)
    assert len(result.unique_entries) == 2
    assert result.skipped_count == 0
    print("[OK] test_dedup_threshold")


def test_dedup_custom_threshold():
    """Custom threshold works."""
    text = "Medium length"  # 13 chars
    entries = [
        _make_dlg("id1", text, "mc", "file1.rpy"),
        _make_dlg("id2", text, "mc", "file2.rpy"),
    ]
    # With threshold=10, this should dedup
    result = dedup_tl_entries(entries, min_length=10)
    assert len(result.unique_entries) == 1
    assert result.skipped_count == 1
    # With threshold=20, this should NOT dedup
    result2 = dedup_tl_entries(entries, min_length=20)
    assert len(result2.unique_entries) == 2
    assert result2.skipped_count == 0
    print("[OK] test_dedup_custom_threshold")


def test_dedup_mixed_types():
    """Mix of DialogueEntry and StringEntry."""
    long_text = "This is a sentence long enough to pass the dedup threshold easily."
    entries = [
        _make_dlg("id1", long_text, "mc", "file1.rpy"),
        _make_dlg("id2", "Hmm...", "mc", "file1.rpy"),
        _make_str("Hello world"),
        _make_dlg("id3", long_text, "mc", "file2.rpy"),  # dup of id1
    ]
    result = dedup_tl_entries(entries)
    assert len(result.unique_entries) == 3  # id1 + "Hmm..." + "Hello world"
    assert result.skipped_count == 1  # id3
    print("[OK] test_dedup_mixed_types")


# ---------------------------------------------------------------------------
# apply_dedup_translations tests
# ---------------------------------------------------------------------------


def test_apply_dedup_basic():
    """Apply dedup fills translations into file_translations."""
    long_text = "This is a long sentence that should be deduplicated across files."
    entries = [
        _make_dlg("id1", long_text, "mc", "tl/chinese/file1.rpy", 10),
        _make_dlg("id2", long_text, "mc", "tl/chinese/file2.rpy", 20),
        _make_dlg("id3", long_text, "mc", "tl/chinese/file3.rpy", 30),
    ]
    dedup = dedup_tl_entries(entries)

    # Simulate that id1 was translated
    game_dir = Path("/game")
    file_translations = {
        "tl/chinese/file1.rpy": {"id1": "这是一个应该在文件间去重的长句。"},
    }

    filled, log = apply_dedup_translations(dedup, file_translations, game_dir)
    assert filled == 2
    # Check that translations were injected for file2 and file3
    assert "id2" in file_translations.get("tl/chinese/file2.rpy", {})
    assert "id3" in file_translations.get("tl/chinese/file3.rpy", {})
    assert file_translations["tl/chinese/file2.rpy"]["id2"] == "这是一个应该在文件间去重的长句。"
    # Check log entries
    assert len(log) == 2
    assert log[0]["source_file"] == "tl/chinese/file1.rpy"
    assert log[0]["source_line"] == 10
    print("[OK] test_apply_dedup_basic")


def test_apply_dedup_no_translation():
    """If first_seen wasn't translated (API error), don't fill dups."""
    long_text = "A sentence that failed to translate via the API somehow."
    entries = [
        _make_dlg("id1", long_text, "mc", "file1.rpy"),
        _make_dlg("id2", long_text, "mc", "file2.rpy"),
    ]
    dedup = dedup_tl_entries(entries)
    file_translations: dict = {}  # nothing translated
    filled, log = apply_dedup_translations(dedup, file_translations, Path("/game"))
    assert filled == 0
    print("[OK] test_apply_dedup_no_translation")


def test_apply_dedup_string_entry():
    """StringEntry dedup uses old text as key."""
    long_text = "You already gave her flowers today. Come back later."
    entries = [
        _make_str(long_text, "file1.rpy", 10),
        _make_str(long_text, "file2.rpy", 20),
    ]
    dedup = dedup_tl_entries(entries)
    file_translations = {
        "file1.rpy": {long_text: "你今天已经送过花了。晚点再来吧。"},
    }
    filled, log = apply_dedup_translations(dedup, file_translations, Path("/game"))
    assert filled == 1
    assert long_text in file_translations.get("file2.rpy", {})
    print("[OK] test_apply_dedup_string_entry")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_dedup_basic()
    test_dedup_different_speakers()
    test_dedup_string_entries()
    test_dedup_no_duplicates()
    test_dedup_threshold()
    test_dedup_custom_threshold()
    test_dedup_mixed_types()
    test_apply_dedup_basic()
    test_apply_dedup_no_translation()
    test_apply_dedup_string_entry()

    print("\n=== 全部 TL 去重测试通过 ===")
