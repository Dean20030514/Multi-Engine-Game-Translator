#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV/JSONL/JSON engine tests — split from ``tests/test_engines.py``
in round 48 Step 5 to bring both files below the CLAUDE.md 800-line
soft limit.  test_engines.py grew to 1090 lines via accumulated CSV
hardening across r44 (size cap) / r46 (csv cap) / r47 (boundary +
TOCTOU code) / r48 (boundary expansion + L1 csv.Error + helper
extract + jsonl/json TOCTOU) — caught by user feedback at r48 end
("multiple files exceed 800; why didn't you alert me?"), revealing
a multi-round drift between the HANDOFF claim "all tests < 800
maintained" and reality.  See r48 Step 5 lessons in
_archive/CHANGELOG_RECENT_r50.md (Round 48 audit-tail section).

Covers all CSV/TSV/JSONL/JSON extract + write_back + 50 MB cap +
TOCTOU defense + csv.Error explicit catch tests for
``engines/csv_engine.py``.

NOTE: 21 CSV-specific tests live here.  Generic engine_base /
engine_detector / RenPyEngine / generic_pipeline / prompts addon /
checker.py custom_re tests stay in ``tests/test_engines.py``.

Tests are byte-identical to their pre-split forms.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================
# CSV 提取测试
# ============================================================

def test_csv_basic_extract():
    """CSV 基本提取"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "test.csv"
        csv_path.write_text(
            "id,original,speaker\nline_001,Hello,Guard\nline_002,World,NPC\n",
            encoding="utf-8",
        )
        units = engine.extract_texts(csv_path)
        assert len(units) == 2
        assert units[0].id == "line_001"
        assert units[0].original == "Hello"
        assert units[0].speaker == "Guard"
    print("[OK] csv_basic_extract")


def test_csv_column_aliases():
    """CSV 列名别名（source/text/en 匹配为 original）"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    for alias in ("source", "text", "en"):
        with tempfile.TemporaryDirectory() as d:
            csv_path = Path(d) / "test.csv"
            csv_path.write_text(f"key,{alias}\nk1,Hello\n", encoding="utf-8")
            units = engine.extract_texts(csv_path)
            assert len(units) == 1, f"alias '{alias}' failed"
            assert units[0].original == "Hello"
    print("[OK] csv_column_aliases")


def test_csv_no_id_column():
    """CSV 无 ID 列（自动用行号）"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "test.csv"
        csv_path.write_text("original\nHello\nWorld\n", encoding="utf-8")
        units = engine.extract_texts(csv_path)
        assert len(units) == 2
        assert "1" in units[0].id  # 自动生成含行号的 id
    print("[OK] csv_no_id_column")


def test_csv_utf8_bom():
    """CSV UTF-8 BOM 处理"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "test.csv"
        csv_path.write_bytes(b"\xef\xbb\xbfid,original\nk1,Hello\n")
        units = engine.extract_texts(csv_path)
        assert len(units) == 1
        assert units[0].original == "Hello"
    print("[OK] csv_utf8_bom")


def test_tsv_extract():
    """TSV 提取（tab 分隔）"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        tsv_path = Path(d) / "test.tsv"
        tsv_path.write_text("id\toriginal\nk1\tHello\n", encoding="utf-8")
        units = engine.extract_texts(tsv_path)
        assert len(units) == 1
        assert units[0].original == "Hello"
    print("[OK] tsv_extract")


def test_jsonl_basic_extract():
    """JSONL 基本提取"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        jsonl_path = Path(d) / "test.jsonl"
        jsonl_path.write_text(
            '{"id": "l1", "original": "Hello", "speaker": "Guard"}\n'
            '{"id": "l2", "original": "World"}\n',
            encoding="utf-8",
        )
        units = engine.extract_texts(jsonl_path)
        assert len(units) == 2
        assert units[0].speaker == "Guard"
    print("[OK] jsonl_basic_extract")


def test_json_array_fallback():
    """JSON 数组 fallback"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        json_path = Path(d) / "test.json"
        json_path.write_text(
            '[{"id": "a1", "original": "Hello"}, {"id": "a2", "original": "World"}]',
            encoding="utf-8",
        )
        units = engine.extract_texts(json_path)
        assert len(units) == 2
    print("[OK] json_array_fallback")


def test_csv_write_back():
    """CSV write_back 输出包含翻译列"""
    from engines.csv_engine import CSVEngine
    from engines.engine_base import TranslatableUnit
    engine = CSVEngine()
    units = [
        TranslatableUnit(id="k1", original="Hello", file_path="test.csv",
                         translation="你好", status="translated",
                         metadata={"source_format": "csv"}),
    ]
    with tempfile.TemporaryDirectory() as d:
        written = engine.write_back(Path("."), units, Path(d), target_lang="zh")
        assert written == 1
        out = Path(d) / "translations_zh.csv"
        assert out.exists()
        content = out.read_text(encoding="utf-8-sig")
        assert "你好" in content
    print("[OK] csv_write_back")


def test_jsonl_write_back():
    """JSONL write_back"""
    from engines.csv_engine import CSVEngine
    from engines.engine_base import TranslatableUnit
    engine = CSVEngine()
    units = [
        TranslatableUnit(id="k1", original="Hello", file_path="test.jsonl",
                         translation="你好", status="translated",
                         metadata={"source_format": "jsonl"}),
    ]
    with tempfile.TemporaryDirectory() as d:
        written = engine.write_back(Path("."), units, Path(d), target_lang="zh")
        assert written == 1
        out = Path(d) / "translations_zh.jsonl"
        assert out.exists()
        line = out.read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert obj["zh"] == "你好"
    print("[OK] jsonl_write_back")


def test_csv_directory_scan():
    """CSV 目录扫描提取"""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "a.csv").write_text("original\nHello\n", encoding="utf-8")
        (Path(d) / "b.jsonl").write_text('{"original": "World"}\n', encoding="utf-8")
        (Path(d) / "readme.txt").write_text("ignore me", encoding="utf-8")
        units = engine.extract_texts(Path(d))
        assert len(units) == 2
    print("[OK] csv_directory_scan")


def test_csv_engine_rejects_oversized_json():
    """Round 44 audit-tail: CSVEngine._extract_json_or_jsonl and
    _extract_jsonl skip operator-supplied files above
    _MAX_CSV_JSON_SIZE (50 MB) with a warning rather than loading the
    whole file into memory.  Uses a 51 MB sparse file so the test runs
    instantly without consuming disk; verifies the cap semantics + the
    mixed-directory scan still extracts from the other files."""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        # Legitimate small file — must still be extracted
        (Path(d) / "small.csv").write_text(
            "original\nHello\n", encoding="utf-8",
        )
        # 51 MB sparse oversized JSONL — must be skipped
        big_jsonl = Path(d) / "big.jsonl"
        with open(big_jsonl, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        # 51 MB sparse oversized JSON — must be skipped
        big_json = Path(d) / "big.json"
        with open(big_json, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        units = engine.extract_texts(Path(d))
        # Only the small.csv entry should extract; big.jsonl / big.json
        # are both skipped by the cap gate.
        rel_files = {u.file_path for u in units}
        assert "big.jsonl" not in rel_files, (
            "oversized .jsonl must be skipped, got units: "
            f"{[u.file_path for u in units]}"
        )
        assert "big.json" not in rel_files, (
            "oversized .json must be skipped, got units: "
            f"{[u.file_path for u in units]}"
        )
        # Small file unaffected.
        assert len(units) == 1, (
            f"expected 1 unit from small.csv, got {len(units)}: "
            f"{[u.file_path for u in units]}"
        )
    print("[OK] csv_engine_rejects_oversized_json")


def test_csv_engine_rejects_oversized_csv():
    """Round 46 Step 4 (G1): CSVEngine._extract_csv skips operator-
    supplied .csv / .tsv files above _MAX_CSV_JSON_SIZE (50 MB) with
    a warning rather than streaming the whole file into the
    accumulated units list.  The r44 audit-tail covered _extract_jsonl
    and _extract_json_or_jsonl but missed _extract_csv; closed by the
    round 45 audit's optional MEDIUM list.  Uses a 51 MB sparse file
    so the test runs instantly without consuming disk."""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        # Legitimate small file — must still be extracted
        (Path(d) / "small.csv").write_text(
            "original\nHello\n", encoding="utf-8",
        )
        # 51 MB sparse oversized .csv — must be skipped
        big_csv = Path(d) / "big.csv"
        with open(big_csv, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")
        # 51 MB sparse oversized .tsv — must be skipped
        big_tsv = Path(d) / "big.tsv"
        with open(big_tsv, "wb") as f:
            f.seek(51 * 1024 * 1024 - 1)
            f.write(b"\0")

        units = engine.extract_texts(Path(d))
        rel_files = {u.file_path for u in units}
        assert "big.csv" not in rel_files, (
            "oversized .csv must be skipped, got units: "
            f"{[u.file_path for u in units]}"
        )
        assert "big.tsv" not in rel_files, (
            "oversized .tsv must be skipped, got units: "
            f"{[u.file_path for u in units]}"
        )
        assert len(units) == 1, (
            f"expected 1 unit from small.csv, got {len(units)}: "
            f"{[u.file_path for u in units]}"
        )
    print("[OK] csv_engine_rejects_oversized_csv")


def test_csv_engine_accepts_exact_cap_csv():
    """Round 47 Step 2 (G1 boundary): exact-cap-size CSV must NOT
    trigger the cap because the operator is ``>`` not ``>=`` (line 219
    of csv_engine.py).  Pins this contract — a future change to ``>=``
    would silently reject many legitimate large CSVs at the boundary.
    Uses mock.patch on _MAX_CSV_JSON_SIZE so we don't need a real
    50 MB file."""
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        exact_csv = Path(d) / "exact.csv"
        # Build a small valid CSV; remember its exact size for cap mock
        exact_csv.write_text("original\nHello\n", encoding="utf-8")
        size = exact_csv.stat().st_size
        with mock.patch("engines.csv_engine._MAX_CSV_JSON_SIZE", size):
            units = engine.extract_texts(Path(d))
        originals = [u.original for u in units if u.file_path == "exact.csv"]
        assert "Hello" in originals, (
            f"exact-cap-size CSV (file_size == cap) must NOT trigger > cap; "
            f"expected 'Hello' in extracted units, got {originals}"
        )
    print("[OK] csv_engine_accepts_exact_cap_csv")


def test_csv_engine_handles_empty_csv():
    """Round 47 Step 2 (G1 boundary): empty 0-byte CSV file must not
    crash the cap check or csv.DictReader.  Returns 0 units (no header
    means csv.DictReader.fieldnames is None -> early return [])."""
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        empty_csv = Path(d) / "empty.csv"
        empty_csv.write_bytes(b"")  # exactly 0 bytes
        assert empty_csv.stat().st_size == 0
        units = engine.extract_texts(Path(d))
        empty_units = [u for u in units if u.file_path == "empty.csv"]
        assert len(empty_units) == 0, (
            f"empty 0-byte CSV must yield 0 units, got {len(empty_units)}"
        )
    print("[OK] csv_engine_handles_empty_csv")


def test_csv_engine_handles_stat_oserror_fail_open():
    """Round 47 Step 2 (G1 boundary): Path.stat() OSError must trigger
    the fail-open path (fsize=0 < cap), so the file goes through normal
    csv.DictReader processing rather than being skipped.  Pins the
    intentional fail-open design.  The post-open os.fstat() (r47 D3
    defense) is unaffected because it uses the open file descriptor."""
    import os as _os
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        target_csv = Path(d) / "target.csv"
        target_csv.write_text("original\nHello\n", encoding="utf-8")
        # Selectively raise OSError only for target.csv path.stat()
        original_stat = Path.stat
        def _selective_stat(self, *, follow_symlinks=True):
            if self.name == "target.csv":
                raise OSError("simulated stat failure")
            return original_stat(self, follow_symlinks=follow_symlinks)
        with mock.patch.object(Path, "stat", _selective_stat):
            units = engine.extract_texts(Path(d))
        originals = [u.original for u in units if u.file_path == "target.csv"]
        assert "Hello" in originals, (
            f"stat() OSError fail-open: file must still be processed via "
            f"normal path; got originals={originals}"
        )
    print("[OK] csv_engine_handles_stat_oserror_fail_open")


def test_csv_engine_rejects_toctou_growth_attack():
    """Round 47 Step 2 (D3 TOCTOU defense): if a file appears small at
    Path.stat() but has grown to > cap by the time of the post-open
    os.fstat() inside the with-open block, the file must be rejected.
    Pins the new TOCTOU defense added in round 47 Step 2."""
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        target_csv = Path(d) / "toctou.csv"
        target_csv.write_text("original\nHello\n", encoding="utf-8")
        small_cap = 100  # mock cap

        # Mock os.fstat to return huge size — simulates "file grew
        # between Path.stat() and open()".  The real Path.stat() above
        # returns the actual small size (~ 15 bytes < 100 cap), so the
        # pre-open gate passes; the post-open fstat() now sees > cap.
        # Round 48 audit-fix: namespace correction for r47 test after
        # round 48 Step 2 helper extraction — the actual fstat call
        # moved from `engines.csv_engine.os.fstat` (r47 inline) to
        # `safety.file_safety.os.fstat` (r48 helper).  The original mock
        # target was r47-correct but r48-stale, causing this test to
        # spuriously pass without actually intercepting fstat.
        # Caught by round 48 Step 3 security audit.
        class _LargeStatResult:
            st_size = 99999  # > small_cap = 100
        def _patched_os_fstat(fd):
            return _LargeStatResult()

        with mock.patch("safety.file_safety.os.fstat", _patched_os_fstat), \
             mock.patch("engines.csv_engine._MAX_CSV_JSON_SIZE", small_cap):
            units = engine.extract_texts(Path(d))

        originals = [u.original for u in units if u.file_path == "toctou.csv"]
        assert "Hello" not in originals, (
            "TOCTOU defense: file that grew past cap between stat and "
            f"open must be rejected; got originals={originals}"
        )
    print("[OK] csv_engine_rejects_toctou_growth_attack")


def test_csv_engine_accepts_cap_minus_1_csv():
    """Round 48 Step 1 (G1.1 boundary expansion): file size = cap-1
    must NOT trigger ``> cap``.  Together with r47's
    ``test_csv_engine_accepts_exact_cap_csv`` (== cap) and the new
    ``test_csv_engine_rejects_cap_plus_1_csv`` below, fully pins the
    lower / equal / upper edges of the ``>`` operator contract."""
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        cm1_csv = Path(d) / "cap_minus_1.csv"
        cm1_csv.write_text("original\nHello\n", encoding="utf-8")
        size = cm1_csv.stat().st_size
        # mock cap = size + 1 -> file_size = cap - 1
        with mock.patch("engines.csv_engine._MAX_CSV_JSON_SIZE", size + 1):
            units = engine.extract_texts(Path(d))
        originals = [u.original for u in units if u.file_path == "cap_minus_1.csv"]
        assert "Hello" in originals, (
            f"cap-1 file size must NOT trigger > cap; "
            f"expected 'Hello' in extracted units, got {originals}"
        )
    print("[OK] csv_engine_accepts_cap_minus_1_csv")


def test_csv_engine_rejects_cap_plus_1_csv():
    """Round 48 Step 1 (G1.1 boundary expansion): file size = cap+1
    MUST trigger ``> cap`` and reject.  The smallest size that should
    be rejected — the upper edge of the ``>`` operator contract."""
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        cp1_csv = Path(d) / "cap_plus_1.csv"
        cp1_csv.write_text("original\nHello\n", encoding="utf-8")
        size = cp1_csv.stat().st_size
        # mock cap = size - 1 -> file_size = cap + 1
        with mock.patch("engines.csv_engine._MAX_CSV_JSON_SIZE", size - 1):
            units = engine.extract_texts(Path(d))
        originals = [u.original for u in units if u.file_path == "cap_plus_1.csv"]
        assert "Hello" not in originals, (
            f"cap+1 file size must trigger > cap and reject; "
            f"expected empty, got {originals}"
        )
    print("[OK] csv_engine_rejects_cap_plus_1_csv")


def test_csv_engine_logs_csv_error_distinct_from_generic():
    """Round 48 Step 1 (L1 informational): when csv.DictReader raises
    csv.Error (typically on TOCTOU truncation or malformed CSV mid-
    row), the explicit ``except csv.Error`` branch must catch it
    BEFORE the generic ``except Exception`` falls through.  Verified
    via mock injecting csv.Error and checking the operator-facing
    log message uses "CSV 解析错误" (CSV-specific) rather than
    "解析失败" (generic).  Closes the round 47 audit's 1 LOW
    informational gap."""
    import csv
    import logging
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "bad.csv"
        target.write_text("original\nHello\n", encoding="utf-8")

        # Patch _extract_csv to raise csv.Error (simulates DictReader
        # crashing on a truncated row inside extract_texts try/except).
        def _raise_csv_error(self, filepath, delimiter=","):
            raise csv.Error("simulated truncation: line missing field")

        with mock.patch.object(CSVEngine, "_extract_csv", _raise_csv_error):
            # Capture logger output to verify the CSV-specific message
            # branch fired (not the generic "解析失败" fallback).
            captured: list[str] = []

            class _CaptureHandler(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    captured.append(record.getMessage())

            handler = _CaptureHandler(level=logging.ERROR)
            logger = logging.getLogger("multi_engine_translator")
            logger.addHandler(handler)
            try:
                units = engine.extract_texts(Path(d))
            finally:
                logger.removeHandler(handler)

        # No units extracted (csv.Error caught, return []).
        assert not [u for u in units if u.file_path == "bad.csv"], (
            "csv.Error must result in 0 units for the failing file"
        )
        # The CSV-specific log message branch fired.
        csv_error_msgs = [m for m in captured if "CSV 解析错误" in m]
        generic_fail_msgs = [m for m in captured if "解析失败" in m]
        assert csv_error_msgs, (
            f"csv.Error must trigger the explicit 'CSV 解析错误' branch; "
            f"captured={captured}"
        )
        assert not generic_fail_msgs, (
            f"csv.Error must NOT fall through to generic '解析失败' branch; "
            f"captured={captured}"
        )
    print("[OK] csv_engine_logs_csv_error_distinct_from_generic")


def test_csv_engine_rejects_jsonl_toctou_growth_attack():
    """Round 48 Step 2 (D method scope expansion): jsonl extractor must
    reject files that grew between Path.stat() and open() so the
    post-open fstat sees > cap.  Mirrors r47 Step 2's csv TOCTOU test
    but for the _extract_jsonl path (which reads entire file via
    f.read() before splitting lines — without fstat re-check, attacker
    can OOM the host with a sparse-then-grown file)."""
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        target_jsonl = Path(d) / "toctou.jsonl"
        target_jsonl.write_text(
            '{"original": "Hello"}\n', encoding="utf-8"
        )
        small_cap = 100  # mock cap

        # Mock check_fstat_size to return (False, huge) — simulates
        # "file grew between Path.stat and open" inside _extract_jsonl.
        # Path.stat() above returns the actual small size, passing the
        # pre-open gate; the post-open helper now sees > cap.
        def _patched_check(file_obj, max_size):
            return (False, 99999)  # ok=False, size=99999

        with mock.patch("engines.csv_engine.check_fstat_size", _patched_check), \
             mock.patch("engines.csv_engine._MAX_CSV_JSON_SIZE", small_cap):
            units = engine.extract_texts(Path(d))

        originals = [u.original for u in units if u.file_path == "toctou.jsonl"]
        assert "Hello" not in originals, (
            "JSONL TOCTOU defense: file that grew past cap between stat "
            f"and open must be rejected; got originals={originals}"
        )
    print("[OK] csv_engine_rejects_jsonl_toctou_growth_attack")


def test_csv_engine_rejects_json_toctou_growth_attack():
    """Round 48 Step 2 (D method scope expansion): .json dispatch must
    reject files that grew between Path.stat() and open() so the
    post-open fstat sees > cap.  The .json path reads the entire file
    via f.read() before json.loads(); same TOCTOU surface as
    _extract_jsonl, mitigated via the same helper."""
    from unittest import mock
    from engines.csv_engine import CSVEngine
    engine = CSVEngine()
    with tempfile.TemporaryDirectory() as d:
        target_json = Path(d) / "toctou.json"
        target_json.write_text(
            '[{"original": "Hello"}]', encoding="utf-8"
        )
        small_cap = 100  # mock cap

        def _patched_check(file_obj, max_size):
            return (False, 99999)

        with mock.patch("engines.csv_engine.check_fstat_size", _patched_check), \
             mock.patch("engines.csv_engine._MAX_CSV_JSON_SIZE", small_cap):
            units = engine.extract_texts(Path(d))

        originals = [u.original for u in units if u.file_path == "toctou.json"]
        assert "Hello" not in originals, (
            ".json TOCTOU defense: file that grew past cap between stat "
            f"and open must be rejected; got originals={originals}"
        )
    print("[OK] csv_engine_rejects_json_toctou_growth_attack")



def run_all() -> int:
    """Run every CSV/JSONL/JSON engine test in this module."""
    tests = [
        # Basic CSV/TSV/JSONL/JSON extract + write_back + dir scan
        test_csv_basic_extract,
        test_csv_column_aliases,
        test_csv_no_id_column,
        test_csv_utf8_bom,
        test_tsv_extract,
        test_jsonl_basic_extract,
        test_json_array_fallback,
        test_csv_write_back,
        test_jsonl_write_back,
        test_csv_directory_scan,
        # Round 44 audit-tail: CSV/JSON 50 MB cap
        test_csv_engine_rejects_oversized_json,
        # Round 46 Step 4 (G1): CSV/TSV 50 MB cap (audit-tail follow-up)
        test_csv_engine_rejects_oversized_csv,
        # Round 47 Step 2 (G1 boundary + D3 TOCTOU defense)
        test_csv_engine_accepts_exact_cap_csv,
        test_csv_engine_handles_empty_csv,
        test_csv_engine_handles_stat_oserror_fail_open,
        test_csv_engine_rejects_toctou_growth_attack,
        # Round 48 Step 1 (G1.1 boundary expansion + L1 csv.Error branch)
        test_csv_engine_accepts_cap_minus_1_csv,
        test_csv_engine_rejects_cap_plus_1_csv,
        test_csv_engine_logs_csv_error_distinct_from_generic,
        # Round 48 Step 2 (D method scope expansion): TOCTOU defense for jsonl/json
        test_csv_engine_rejects_jsonl_toctou_growth_attack,
        test_csv_engine_rejects_json_toctou_growth_attack,
    ]
    for t in tests:
        t()
    return len(tests)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} CSV ENGINE TESTS PASSED")
    print("=" * 40)
