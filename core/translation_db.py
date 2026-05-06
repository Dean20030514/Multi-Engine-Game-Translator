#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translation DB — store per-line translation metadata for incremental workflows.

Thread-safety: all mutating and reading operations are guarded by a re-entrant
lock so that concurrent workers (e.g. ``engines/generic_pipeline.py`` running
``translation_db.upsert_entry`` from a ``ThreadPoolExecutor``) cannot corrupt
``self.entries`` / ``self._index``.

Durability: ``save()`` writes atomically via a temp file + ``os.replace`` so a
mid-write crash or Windows file-handle contention cannot leave a half-written
JSON payload on disk.

Incremental writes: a ``_dirty`` flag short-circuits ``save()`` when nothing
has changed since the last successful persist (previously every pipeline
report path re-serialised the entire DB regardless of changes).

Round 52 C4 BREAKING: schema v2 (round 34 multi-language ``language`` field
+ 4-tuple ``(file, line, original, language)`` index) retired.  Reverted to
v1 flat schema: 3-tuple ``(file, line, original)`` index, no per-entry
``language`` field.  Existing v2 DBs must be migrated via
``scripts/migrate_db_v2_to_v1.py``.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from safety.file_safety import check_fstat_size


class TranslationDB:
    """Lightweight JSON-based translation metadata store.

    Round 52 C4 BREAKING: entries de-duplicated by (file, line, original).
    Pre-r52 added a ``language`` field for multi-language buckets; that
    is retired now that only zh is supported.  Thread-safe.
    """

    #: On-disk schema version written by ``save()``.  Round 52 C4: reverted
    #: to v1 (no language field on entries).
    SCHEMA_VERSION: int = 1

    #: Round 37 M2: reject translation_db.json files above this size to bound
    #: memory usage.  A 50 MB DB would hold tens of thousands of entries even
    #: at verbose status / error_codes fields, so this is orders-of-magnitude
    #: headroom over legitimate use; anything larger is almost certainly
    #: malformed or an attacker-crafted artefact worth rejecting up front.
    _MAX_DB_FILE_SIZE: int = 50 * 1024 * 1024

    def __init__(self, path: Path):
        """Construct a TranslationDB backed by ``path``.

        Round 52 C4 BREAKING: ``default_language`` kwarg retired.  Pre-r52
        the kwarg drove v1→v2 schema upgrade on load; v2 schema is gone
        so this knob is no longer meaningful.

        Args:
            path: JSON file path.  Created on first ``save()``.
        """
        self.path = path
        self.version: int = 1  # loaded-version; save() always writes SCHEMA_VERSION
        self.entries: List[Dict[str, Any]] = []
        # Round 52 C4 BREAKING: 3-tuple key (file, line, original); v2's
        # 4-tuple language-aware key retired.
        self._index: Dict[Tuple[str, int, str], int] = {}
        # Re-entrant so ``add_entries`` may call ``upsert_entry`` without
        # deadlocking on the same thread.
        self._lock: threading.RLock = threading.RLock()
        # Skip no-op persistence when nothing has changed since last save/load.
        self._dirty: bool = False

    def _rebuild_index(self) -> None:
        """Rebuild the (file, line, original) -> position index.

        Caller must already hold ``self._lock``.  Round 52 C4 BREAKING:
        language field removed from key tuple.
        """
        self._index.clear()
        for idx, entry in enumerate(self.entries):
            file = str(entry.get("file", ""))
            raw_line = entry.get("line", 0)
            try:
                line = int(raw_line) if raw_line is not None else None
            except (TypeError, ValueError):
                line = None
            original = str(entry.get("original", ""))
            # Keep entries with line == 0 (generic pipeline uses 0 as a
            # placeholder when the source format has no meaningful line info).
            if file and line is not None and original:
                self._index[(file, line, original)] = idx

    def load(self) -> None:
        """Load existing DB from disk if present.

        Round 34: when the on-disk schema is v1 (or missing version) AND the
        caller constructed with ``default_language``, every entry without a
        ``language`` field is backfilled with the caller's default.  This
        prevents a subsequent upsert (which auto-fills from the same default)
        from creating a parallel ``(file,line,orig,"zh")`` duplicate of each
        existing ``(file,line,orig,None)`` entry.
        """
        with self._lock:
            if not self.path.exists():
                self.entries = []
                self._index = {}
                self._dirty = False
                return
            # Round 37 M2: bound memory before read.  Reject oversize DB
            # files the same way we treat corruption — drop to an empty
            # in-memory state without overwriting the on-disk copy, so
            # an operator can inspect and recover if needed.
            try:
                file_size = self.path.stat().st_size
            except OSError:
                file_size = 0
            if file_size > self._MAX_DB_FILE_SIZE:
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "[DB] %s too large (%d bytes > %d-byte cap), "
                    "refusing to load to protect memory",
                    self.path,
                    file_size,
                    self._MAX_DB_FILE_SIZE,
                )
                self.entries = []
                self._index = {}
                self._dirty = False
                return
            try:
                # Round 49 Step 2: TOCTOU defense via check_fstat_size.  The
                # path.stat() pre-check above is the fast path; this re-checks
                # the size on the actual open fd to defeat the attacker-grow-
                # between-stat-and-open race window.
                with open(self.path, encoding="utf-8") as f:
                    ok, fsize2 = check_fstat_size(f, self._MAX_DB_FILE_SIZE)
                    if not ok:
                        import logging as _logging

                        _logging.getLogger(__name__).warning(
                            "[DB] %s grew past cap after stat (TOCTOU?): "
                            "%d bytes > %d-byte cap, refusing to load",
                            self.path,
                            fsize2,
                            self._MAX_DB_FILE_SIZE,
                        )
                        self.entries = []
                        self._index = {}
                        self._dirty = False
                        return
                    data = json.loads(f.read())
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                # Corrupted or incompatible file; start fresh but do not overwrite immediately.
                self.entries = []
                self._index = {}
                self._dirty = False
                return
            if isinstance(data, dict):
                self.version = int(data.get("version", 1) or 1)
                raw_entries = data.get("entries", [])
                if isinstance(raw_entries, list):
                    self.entries = list(raw_entries)
                else:
                    self.entries = []
            else:
                self.entries = []
            # Round 52 C4 BREAKING: v1→v2 forced backfill retired.
            # Existing v2 entries' ``language`` field is now ignored on
            # read; if v2 file is loaded, the `language` field stays in
            # the dict (forward-compat read tolerance) but isn't used in
            # the 3-tuple index.  Use scripts/migrate_db_v2_to_v1.py to
            # strip ``language`` fields cleanly.
            self._rebuild_index()
            if not self._dirty:
                self._dirty = False

    def save(self) -> None:
        """Persist DB to disk atomically (temp file + ``os.replace``).

        No-ops when ``_dirty`` is ``False`` to avoid re-serialising an
        unchanged DB on every report pass.  Always writes ``version = SCHEMA_VERSION``
        so the on-disk file reflects the current code's schema after any
        successful save.
        """
        with self._lock:
            if not self._dirty:
                return
            payload = {
                "version": self.SCHEMA_VERSION,
                "entries": list(self.entries),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                os.replace(str(tmp), str(self.path))
            except OSError:
                # Best-effort cleanup of the temp file; re-raise so the caller
                # (pipeline/report layer) can record the failure.
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                raise
            self.version = self.SCHEMA_VERSION
            self._dirty = False

    def upsert_entry(self, entry: Dict[str, Any]) -> None:
        """Insert or update a single entry, de-duplicated by
        ``(file, line, original)``.

        Accepts ``line == 0`` (generic pipeline uses 0 as a placeholder).
        Silently drops entries missing file/original or with a non-integer line.

        Round 52 C4 BREAKING: language field auto-fill / dedup retired.
        """
        file = str(entry.get("file", ""))
        raw_line = entry.get("line", 0)
        try:
            line = int(raw_line) if raw_line is not None else None
        except (TypeError, ValueError):
            line = None
        original = str(entry.get("original", ""))
        if not file or line is None or not original:
            return
        key = (file, line, original)
        with self._lock:
            idx = self._index.get(key)
            if idx is not None:
                self.entries[idx] = entry
            else:
                self.entries.append(entry)
                self._index[key] = len(self.entries) - 1
            self._dirty = True

    def add_entries(self, entries: List[Dict[str, Any]]) -> None:
        """Bulk insert/update entries."""
        with self._lock:
            for e in entries:
                self.upsert_entry(e)

    def has_entry(self, file: str, line: int, original: str) -> bool:
        """Check if an entry with given ``(file, line, original)`` key exists.

        Round 52 C4 BREAKING: ``language`` kwarg retired.
        """
        with self._lock:
            return (file, line, original) in self._index

    def filter_by_status(
        self,
        statuses: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return entries filtered by status and/or files.

        Round 52 C4 BREAKING: ``language`` filter kwarg retired.
        """
        if statuses is not None:
            allowed_status = {s.lower() for s in statuses}
        else:
            allowed_status = None
        if files is not None:
            allowed_files = set(files)
        else:
            allowed_files = None

        with self._lock:
            snapshot = list(self.entries)

        result: List[Dict[str, Any]] = []
        for e in snapshot:
            if allowed_status is not None:
                s = str(e.get("status", "")).lower()
                if s not in allowed_status:
                    continue
            if allowed_files is not None:
                f = str(e.get("file", ""))
                if f not in allowed_files:
                    continue
            result.append(e)
        return result
