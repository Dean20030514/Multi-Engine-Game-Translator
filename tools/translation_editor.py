#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translation Editor — Interactive HTML Review & Edit Tool
=========================================================

Export translated Ren'Py files to an interactive HTML page where reviewers
can search, filter, and **edit** translations in a browser, then import the
changes back into the ``.rpy`` files.

Supports two data sources:
    - **tl-mode**: Reads ``tl/<lang>/*.rpy`` via ``tl_parser`` (DialogueEntry /
      StringEntry with precise ``tl_line`` positioning).
    - **translation_db**: Reads ``translation_db.json`` produced by direct-mode
      or the one-click pipeline (entries with file / line / original / translation).

Export produces a self-contained HTML file; import reads a JSON file that the
HTML page's "Export Edits" button generates.

Usage::

    # Export (tl-mode)
    python -m tools.translation_editor --export --tl-dir game/tl/chinese --output review.html

    # Export (from translation_db.json)
    python -m tools.translation_editor --export --db translation_db.json --output review.html

    # Import edits back
    python -m tools.translation_editor --import-json edits.json

Pure standard library — no external dependencies.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)

# Round 37 M2 + Round 38: 50 MB cap applied to every user-supplied JSON
# path that enters the editor.  Originally added in round 37 as
# ``_MAX_V2_APPLY_SIZE`` (gated ``_apply_v2_edits`` only); round 38
# generalises the cap to cover the other two entry points that also
# read operator-supplied paths — ``_extract_from_db`` (v1 / v2 DB
# input) and ``import_edits`` (the ``translation_edits.json`` payload).
# Legitimate artefacts for all three sites sit well under the cap; the
# gate bounds memory against attacker-crafted or accidentally-huge
# input.  Matches the cap in ``tools/merge_translations_v2.py`` /
# ``core/translation_db.py`` / ``core/font_patch.py`` for cross-module
# consistency.
_MAX_EDITOR_INPUT_SIZE = 50 * 1024 * 1024
# Backward-compat alias: round 37 M2 introduced this name for the
# ``_apply_v2_edits`` site.  Kept as an alias so external readers /
# tests referencing the old name keep working.
_MAX_V2_APPLY_SIZE = _MAX_EDITOR_INPUT_SIZE


# ============================================================
# Data extraction
# ============================================================


def _extract_from_tl_dir(tl_dir: Path) -> List[Dict[str, Any]]:
    """Extract translation entries from tl/<lang>/ directory using tl_parser."""
    from translators.tl_parser import parse_tl_file

    entries: List[Dict[str, Any]] = []
    rpy_files = sorted(tl_dir.rglob("*.rpy"))
    if not rpy_files:
        logger.warning("No .rpy files found in %s", tl_dir)
        return entries

    for rpy in rpy_files:
        result = parse_tl_file(str(rpy))
        for d in result.dialogues:
            entries.append(
                {
                    "source": "tl",
                    "file": str(rpy),
                    "line": d.tl_line,
                    "original": d.original,
                    "translation": d.translation,
                    "character": d.character,
                    "identifier": d.identifier,
                    "source_file": d.source_file,
                    "source_line": d.source_line,
                }
            )
        for s in result.strings:
            entries.append(
                {
                    "source": "tl",
                    "file": str(rpy),
                    "line": s.tl_line,
                    "original": s.old,
                    "translation": s.new,
                    "character": "",
                    "identifier": "",
                    "source_file": s.source_file,
                    "source_line": s.source_line,
                }
            )
    return entries


def _extract_from_db(
    db_path: Path,
    *,
    v2_lang: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract translation entries from ``translation_db.json`` OR from a
    v2 ``translations.json`` envelope (round 33 Subtask 3).

    Auto-detects the v2 envelope via ``_schema_version`` and routes to
    :func:`_extract_from_v2_envelope`.  For v1 legacy ``translation_db.json``
    the behaviour is byte-identical to round 32.

    Args:
        db_path: Path to the JSON file.  Accepts either the flat v1
            ``translation_db.json`` shape (``{"entries": [...]}``) or a v2
            envelope (``{"_schema_version": 2, "translations": {...}}``).
        v2_lang: For v2 input, which language bucket to populate the
            ``translation`` field with (and therefore which bucket edits
            will write back to).  Defaults to the envelope's
            ``default_lang``.  Ignored for v1 inputs.

    Round 38 M2: rejects oversized inputs above ``_MAX_EDITOR_INPUT_SIZE``
    (50 MB) via an empty-entries return so downstream ``main()`` surfaces
    "No entries found to export" to the operator instead of OOMing on
    the full read.
    """
    # Round 38 M2: size-cap before read.
    try:
        file_size = db_path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > _MAX_EDITOR_INPUT_SIZE:
        logger.warning(
            "[DB-EXPORT] %s too large (%d bytes > %d-byte cap), refusing to load",
            db_path,
            file_size,
            _MAX_EDITOR_INPUT_SIZE,
        )
        return []
    # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
    with open(db_path, encoding="utf-8") as f:
        ok, fsize2 = check_fstat_size(f, _MAX_EDITOR_INPUT_SIZE)
        if not ok:
            logger.warning(
                "[DB-EXPORT] %s grew past cap after stat (TOCTOU?): "
                "%d bytes > %d, refusing to load",
                db_path,
                fsize2,
                _MAX_EDITOR_INPUT_SIZE,
            )
            return []
        data = json.loads(f.read())
    if isinstance(data, dict) and data.get("_schema_version") == 2:
        return _extract_from_v2_envelope(data, db_path, lang=v2_lang)
    raw_entries = data.get("entries", []) if isinstance(data, dict) else []
    entries: List[Dict[str, Any]] = []
    for e in raw_entries:
        entries.append(
            {
                "source": "db",
                "file": e.get("file", ""),
                "line": e.get("line", 0),
                "original": e.get("original", ""),
                "translation": e.get("translation", ""),
                "character": "",
                "identifier": "",
                "source_file": e.get("file", ""),
                "source_line": e.get("line", 0),
            }
        )
    return entries


def _extract_from_v2_envelope(
    data: Dict[str, Any],
    db_path: Path,
    *,
    lang: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract entries from a v2 ``translations.json`` envelope (round 33 Subtask 3).

    Produces one row per original string, whose ``translation`` field comes
    from ``translations[original][lang]``.  ``lang`` defaults to the
    envelope's ``default_lang`` when ``None``.  If the chosen language has
    no translation for a given original, ``translation`` is an empty string
    (the HTML renders it as "(empty)" the same as any untranslated row).

    Extra per-entry keys kept for the round-trip:
        * ``v2_path`` — the source file (so ``import_edits`` can write back
          without a CLI flag).
        * ``v2_lang`` — which bucket this entry's ``translation`` came from.
        * ``v2_langs_seen`` — sorted list of every language key present
          in the envelope (surfaced in the editor's v2 banner so
          operators know which other buckets exist).
    """
    default_lang = str(data.get("default_lang") or "zh")
    target_lang = lang or default_lang
    translations = data.get("translations", {})
    if not isinstance(translations, dict):
        return []

    all_langs: set[str] = set()
    for bucket in translations.values():
        if isinstance(bucket, dict):
            for k in bucket:
                if isinstance(k, str):
                    all_langs.add(k)
    langs_seen = sorted(all_langs)

    entries: List[Dict[str, Any]] = []
    for i, original in enumerate(sorted(translations.keys()), start=1):
        if not isinstance(original, str):
            continue
        bucket = translations.get(original)
        if not isinstance(bucket, dict):
            continue
        t = bucket.get(target_lang, "")
        if not isinstance(t, str):
            t = ""
        entries.append(
            {
                "source": "v2",
                "file": str(db_path),
                "line": i,  # synthetic index so the HTML sorts deterministically
                "original": original,
                "translation": t,
                "character": "",
                "identifier": "",
                "source_file": str(db_path),
                "source_line": i,
                "v2_path": str(db_path),
                "v2_lang": target_lang,
                "v2_default_lang": default_lang,
                "v2_langs_seen": langs_seen,
                # Round 34 Commit 3: expose full per-language bucket dict so the
                # HTML can swap translations in place when the operator picks a
                # different language from the in-page dropdown (no need to re-run
                # the CLI with a different ``--v2-lang``).  Values may be empty
                # strings for languages that don't have a translation for this
                # ``original`` — HTML renders those as "(empty)" just like v1.
                "languages": {
                    k: v for k, v in bucket.items() if isinstance(k, str) and isinstance(v, str)
                },
            }
        )
    return entries


# ============================================================
# HTML generation
# ============================================================

# Round 34 Commit 3: extracted to ``tools/_translation_editor_html.py`` so
# this module stays under the CLAUDE.md 800-line soft limit after the v2
# multi-language switch UI landed.  Import aliased to the original private
# name so the rest of this file stays byte-identical.
from tools._translation_editor_html import HTML_TEMPLATE as _HTML_TEMPLATE


def export_html(
    entries: List[Dict[str, Any]],
    output_path: Path,
) -> int:
    """Generate an interactive HTML editor from translation entries.

    Returns the number of entries written.
    """
    if not entries:
        logger.warning("No entries to export")
        return 0

    # Sanitize entries for JSON embedding
    safe_entries = []
    for e in entries:
        safe = {
            "source": e.get("source", ""),
            "file": e.get("file", ""),
            "line": e.get("line", 0),
            "original": e.get("original", ""),
            "translation": e.get("translation", ""),
            "character": e.get("character", ""),
            "identifier": e.get("identifier", ""),
            "source_file": e.get("source_file", ""),
            "source_line": e.get("source_line", 0),
        }
        # Round 33 Subtask 3 + Round 34 Commit 3: preserve v2 envelope
        # routing keys (only present for ``source == "v2"`` rows; harmless
        # for others).  ``languages`` is the full ``{lang: translation}``
        # bucket dict used by the in-page dropdown to swap translations
        # without re-running the CLI with a different ``--v2-lang``.
        for v2_key in (
            "v2_path",
            "v2_lang",
            "v2_default_lang",
            "v2_langs_seen",
            "languages",
        ):
            if v2_key in e:
                safe[v2_key] = e[v2_key]
        safe_entries.append(safe)

    metadata_json = json.dumps(safe_entries, ensure_ascii=False)
    html_content = _HTML_TEMPLATE.replace("__METADATA__", metadata_json)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    logger.info("Exported %d entries to %s", len(safe_entries), output_path)
    return len(safe_entries)


# ============================================================
# Import edits
# ============================================================


def import_edits(
    edits_path: Path,
    *,
    create_backup: bool = True,
) -> Dict[str, int]:
    """Import edits from the JSON file exported by the HTML editor.

    Supports two modes based on ``source`` field:
        - ``"tl"``: Uses ``tl_parser.fill_translation`` approach — replaces
          the string at exact ``tl_line`` in the file.
        - ``"db"``: Uses ``patcher.apply_translations`` approach — matches
          by line number and original text in the source .rpy file.

    Args:
        edits_path: Path to the ``translation_edits.json`` file.
        create_backup: Whether to create ``.bak`` backups before modifying.

    Returns:
        ``{"applied": N, "skipped": N, "files_modified": N}``

    Round 38 M2: oversized edits.json above ``_MAX_EDITOR_INPUT_SIZE``
    (50 MB) returns the empty-result shape with a warning so the CLI's
    "Import complete: 0 applied, 0 skipped" output is still well-formed.
    """
    # Round 38 M2: size-cap before read.
    try:
        file_size = edits_path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > _MAX_EDITOR_INPUT_SIZE:
        logger.warning(
            "[IMPORT] %s too large (%d bytes > %d-byte cap), refusing to load",
            edits_path,
            file_size,
            _MAX_EDITOR_INPUT_SIZE,
        )
        return {"applied": 0, "skipped": 0, "files_modified": 0}
    # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
    with open(edits_path, encoding="utf-8") as f:
        ok, fsize2 = check_fstat_size(f, _MAX_EDITOR_INPUT_SIZE)
        if not ok:
            logger.warning(
                "[IMPORT] %s grew past cap after stat (TOCTOU?): %d bytes > %d, refusing to load",
                edits_path,
                fsize2,
                _MAX_EDITOR_INPUT_SIZE,
            )
            return {"applied": 0, "skipped": 0, "files_modified": 0}
        edits = json.loads(f.read())
    if not edits:
        return {"applied": 0, "skipped": 0, "files_modified": 0}

    applied = 0
    skipped = 0
    files_modified = 0

    # Round 33 Subtask 3: v2 envelope edits are grouped by v2_path (the
    # JSON file) and written via a dedicated ``_apply_v2_edits`` helper.
    # The regex-based .rpy editor path stays unchanged for tl/db sources.
    v2_edits = [e for e in edits if e.get("source") == "v2"]
    non_v2_edits = [e for e in edits if e.get("source") != "v2"]
    if v2_edits:
        v2_stats = _apply_v2_edits(v2_edits, create_backup=create_backup)
        applied += v2_stats["applied"]
        skipped += v2_stats["skipped"]
        files_modified += v2_stats["files_modified"]
    if not non_v2_edits:
        return {"applied": applied, "skipped": skipped, "files_modified": files_modified}

    # Group edits by file
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for edit in non_v2_edits:
        f = edit.get("file", "")
        if not f:
            continue
        by_file.setdefault(f, []).append(edit)

    for filepath_str, file_edits in sorted(by_file.items()):
        filepath = Path(filepath_str)
        if not filepath.is_file():
            logger.warning("File not found, skipping %d edits: %s", len(file_edits), filepath)
            skipped += len(file_edits)
            continue

        # Backup
        if create_backup:
            bak = filepath.with_suffix(filepath.suffix + ".bak")
            if not bak.exists():
                shutil.copy2(filepath, bak)

        content = filepath.read_text(encoding="utf-8-sig")
        lines = content.splitlines()
        has_trailing_nl = content.endswith("\n")
        file_changed = False

        for edit in file_edits:
            new_trans = edit.get("new_translation", "").strip()
            if not new_trans:
                skipped += 1
                continue

            line_idx = edit.get("line", 0) - 1  # 1-based → 0-based
            if line_idx < 0 or line_idx >= len(lines):
                logger.warning("Line %d out of range in %s", edit.get("line", 0), filepath)
                skipped += 1
                continue

            source = edit.get("source", "tl")
            line = lines[line_idx]

            if source == "tl":
                # tl-mode: replace the quoted string at tl_line
                old_trans = edit.get("old_translation", "")
                if old_trans:
                    # Replace old translation with new
                    target = f'"{old_trans}"'
                    replacement = f'"{_escape_for_rpy(new_trans)}"'
                    if target in line:
                        lines[line_idx] = line.replace(target, replacement, 1)
                        applied += 1
                        file_changed = True
                        continue
                # Fallback: replace empty "" or any first quoted string
                if '""' in line:
                    lines[line_idx] = line.replace('""', f'"{_escape_for_rpy(new_trans)}"', 1)
                    applied += 1
                    file_changed = True
                else:
                    # Try replacing first quoted string
                    m = re.search(r'"([^"]*)"', line)
                    if m:
                        old_q = f'"{m.group(1)}"'
                        lines[line_idx] = line.replace(old_q, f'"{_escape_for_rpy(new_trans)}"', 1)
                        applied += 1
                        file_changed = True
                    else:
                        logger.warning(
                            "Cannot find quoted string at line %d in %s",
                            edit.get("line", 0),
                            filepath,
                        )
                        skipped += 1

            else:
                # db/direct-mode: match original text and replace
                original = edit.get("original", "")
                if original and original in line:
                    escaped = _escape_for_rpy(new_trans)
                    lines[line_idx] = line.replace(original, escaped, 1)
                    applied += 1
                    file_changed = True
                else:
                    logger.warning(
                        "Original text not found at line %d in %s", edit.get("line", 0), filepath
                    )
                    skipped += 1

        if file_changed:
            result = "\n".join(lines)
            if has_trailing_nl:
                result += "\n"
            filepath.write_text(result, encoding="utf-8")
            files_modified += 1

    return {"applied": applied, "skipped": skipped, "files_modified": files_modified}


def _escape_for_rpy(text: str) -> str:
    """Escape text for safe embedding in a Ren'Py quoted string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _apply_v2_edits(
    v2_edits: List[Dict[str, Any]],
    *,
    create_backup: bool = True,
) -> Dict[str, int]:
    """Apply ``source: "v2"`` edits by rewriting the target v2 envelope JSON
    file(s) in place (round 33 Subtask 3).

    Groups edits by ``v2_path`` so each v2 JSON file is loaded, updated, and
    written atomically once.  Updates only ``translations[original][lang]``
    — every other key / bucket / sibling language is preserved byte-for-byte.

    An edit is skipped (with a warning) when:
        * the ``v2_path`` resolves to a path outside the current working
          directory (round 37 M4 defensive check — prevents a crafted
          edits.json from hijacking writes to system files);
        * the ``v2_path`` file is larger than 50 MB (round 37 M2 memory
          cap — the editor process heap stays bounded);
        * the ``v2_path`` file no longer exists or is not a v2 envelope;
        * the ``new_translation`` field is empty or missing;
        * the referenced ``original`` key is not in the envelope's
          ``translations`` dict (rename from browser, or stale edit).

    Round 37 M5: an empty-string ``new_translation`` — produced when an
    operator clears a cell in the HTML editor (typically in side-by-side
    mode) and exports edits — is treated as SKIP, not DELETE.  The
    dominant use case is refining existing translations, and accidental
    whitespace-clearing would be destructive without explicit
    confirmation.  To remove a translation bucket entirely, edit the
    v2 JSON file directly.  The side-by-side toolbar label carries a
    ``title`` tooltip reminding operators of this semantic.
    """
    applied = 0
    skipped = 0
    files_modified = 0

    # Round 37 M4: compute trust anchor once.  The operator is expected
    # to invoke ``--import-json`` from a directory that is an ancestor
    # of the v2 envelope(s) being edited — typically the project root
    # or the output directory.  A resolved v2_path outside this anchor
    # is treated as a stale or hostile edit and skipped with a warning
    # (not raised, because a single bad edit shouldn't abort the whole
    # import batch).
    try:
        trust_root: Optional[Path] = Path.cwd().resolve()
    except OSError:
        # Round 41 audit tail: the prior silent fallback to ``None`` let the
        # CWD whitelist below silently disable itself, so an operator could
        # not tell apart "trust root is my project root" from "every edit is
        # accepted unconditionally because cwd() failed".  Log a warning so
        # the degradation is visible in the same log stream as the per-edit
        # skip warnings below.
        logger.warning(
            "[V2-EDIT] Path.cwd().resolve() failed — CWD whitelist "
            "disabled, edits outside the project tree will NOT be rejected"
        )
        trust_root = None

    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for edit in v2_edits:
        p = edit.get("v2_path") or edit.get("file") or ""
        if not p:
            skipped += 1
            continue
        # Round 37 M4: path-prefix whitelist.  Resolve the path (follows
        # symlinks, normalises ``..``) and require it to be within
        # ``trust_root``.
        if trust_root is not None:
            try:
                resolved = Path(p).resolve()
            except OSError:
                logger.warning(
                    "[V2-EDIT] cannot resolve v2_path, skipping: %r",
                    p,
                )
                skipped += 1
                continue
            try:
                resolved.relative_to(trust_root)
            except ValueError:
                logger.warning(
                    "[V2-EDIT] v2_path outside CWD %s, skipping: %s",
                    trust_root,
                    resolved,
                )
                skipped += 1
                continue
        by_path.setdefault(p, []).append(edit)

    for path_str, path_edits in sorted(by_path.items()):
        path = Path(path_str)
        if not path.is_file():
            logger.warning("[V2-EDIT] file not found, skipping %d edits: %s", len(path_edits), path)
            skipped += len(path_edits)
            continue
        # Round 37 M2: bound memory on the envelope read.  Even after M4
        # path whitelisting (CWD-rooted only), a legitimate CWD file can
        # be malformed / huge — this protects the editor process heap.
        try:
            file_size = path.stat().st_size
        except OSError:
            file_size = 0
        if file_size > _MAX_V2_APPLY_SIZE:
            logger.warning(
                "[V2-EDIT] %s too large (%d bytes > %d-byte cap), skipping %d edits",
                path,
                file_size,
                _MAX_V2_APPLY_SIZE,
                len(path_edits),
            )
            skipped += len(path_edits)
            continue
        try:
            # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
            with open(path, encoding="utf-8") as f:
                ok, fsize2 = check_fstat_size(f, _MAX_V2_APPLY_SIZE)
                if not ok:
                    logger.warning(
                        "[V2-EDIT] %s grew past cap after stat (TOCTOU?): "
                        "%d bytes > %d, skipping %d edits",
                        path,
                        fsize2,
                        _MAX_V2_APPLY_SIZE,
                        len(path_edits),
                    )
                    skipped += len(path_edits)
                    continue
                data = json.loads(f.read())
        except (OSError, ValueError) as e:
            logger.warning("[V2-EDIT] cannot read %s: %s", path, e)
            skipped += len(path_edits)
            continue
        if not isinstance(data, dict) or data.get("_schema_version") != 2:
            logger.warning(
                "[V2-EDIT] %s is not a v2 envelope, skipping %d edits",
                path,
                len(path_edits),
            )
            skipped += len(path_edits)
            continue
        translations = data.get("translations")
        if not isinstance(translations, dict):
            logger.warning("[V2-EDIT] %s missing ``translations`` dict", path)
            skipped += len(path_edits)
            continue

        if create_backup:
            bak = path.with_suffix(path.suffix + ".bak")
            if not bak.exists():
                shutil.copy2(path, bak)

        path_changed = False
        for edit in path_edits:
            original = edit.get("original", "")
            lang = edit.get("v2_lang") or data.get("default_lang") or "zh"
            new_trans = edit.get("new_translation", "")
            if not isinstance(new_trans, str) or not new_trans.strip():
                skipped += 1
                continue
            if not isinstance(original, str) or original not in translations:
                logger.warning(
                    "[V2-EDIT] original %r not found in %s, skipping",
                    original,
                    path,
                )
                skipped += 1
                continue
            bucket = translations[original]
            if not isinstance(bucket, dict):
                bucket = {}
                translations[original] = bucket
            bucket[lang] = new_trans
            applied += 1
            path_changed = True

        if path_changed:
            # Atomic write mirrors core/runtime_hook_emitter._write_json_atomic
            # so an interrupted run never truncates the envelope.
            import os as _os

            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            _os.replace(str(tmp_path), str(path))
            files_modified += 1

    return {"applied": applied, "skipped": skipped, "files_modified": files_modified}


# ============================================================
# CLI
# ============================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive HTML translation editor — export, edit in browser, import back",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--export", action="store_true", help="Export translations to interactive HTML"
    )
    group.add_argument(
        "--import-json", type=str, metavar="PATH", help="Import edits from JSON file"
    )

    parser.add_argument("--tl-dir", type=str, help="tl/<lang>/ directory for tl-mode export")
    parser.add_argument(
        "--db",
        type=str,
        help="translation_db.json path for direct-mode export (auto-detects v2 translations.json)",
    )
    parser.add_argument(
        "--v2-lang",
        type=str,
        default=None,
        metavar="LANG",
        help="For v2 envelope input: which language bucket to edit "
        "(default: envelope's default_lang)",
    )
    parser.add_argument(
        "--output", "-o", default="translation_editor.html", help="Output HTML path"
    )
    parser.add_argument("--no-backup", action="store_true", help="Skip .bak backup on import")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.export:
        entries: List[Dict[str, Any]] = []
        if args.tl_dir:
            entries = _extract_from_tl_dir(Path(args.tl_dir))
        elif args.db:
            entries = _extract_from_db(Path(args.db), v2_lang=args.v2_lang)
        else:
            parser.error("--export requires --tl-dir or --db")
            return

        if not entries:
            print("No entries found to export", file=sys.stderr)
            sys.exit(1)

        count = export_html(entries, Path(args.output))
        print(f"Exported {count} entries to {args.output}")

    elif args.import_json:
        result = import_edits(Path(args.import_json), create_backup=not args.no_backup)
        print(
            f"Import complete: {result['applied']} applied, "
            f"{result['skipped']} skipped, {result['files_modified']} files modified"
        )


if __name__ == "__main__":
    main()
