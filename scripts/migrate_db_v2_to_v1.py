#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round 52 C4 BREAKING migration: translation_db.json v2 → v1.

Pre-r52 the DB optionally carried a per-entry ``language`` field (v2
schema, round 34) so multi-language buckets could coexist.  Round 52 C4
retired multi-target language support; this script flattens existing v2
DBs to v1 by:

  1. Dropping every entry whose ``language`` is set to a non-zh value
     (ja / ko / zh-tw / etc).  Those translations are no longer
     reachable through the codebase.
  2. Stripping the ``language`` field from kept entries (zh entries +
     legacy entries with no language).
  3. Resetting the on-disk ``version`` to 1.

Idempotent: a v1 DB passes through unchanged.

Usage:
    python scripts/migrate_db_v2_to_v1.py <path-to-translation_db.json> [--dry-run]
    python scripts/migrate_db_v2_to_v1.py output/translation_db.json

A backup ``<path>.bak`` is created before the rewrite unless the DB is
already v1 (in which case nothing is written).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def migrate(path: Path, *, dry_run: bool = False) -> dict:
    """Return ``{kept, dropped, was_v1}`` summary; rewrites file in place."""
    if not path.is_file():
        raise FileNotFoundError(f"DB file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.loads(f.read())

    if not isinstance(data, dict):
        raise ValueError(f"Unexpected DB shape (top-level not dict): {path}")

    version = int(data.get("version", 1) or 1)
    raw_entries = data.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ValueError(f"Unexpected entries shape (not list): {path}")

    kept: list[dict] = []
    dropped = 0
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        lang = entry.get("language")
        if isinstance(lang, str) and lang and lang.lower() not in ("zh",):
            dropped += 1
            continue
        # Strip the language field (v1 has no such field).
        if "language" in entry:
            entry = {k: v for k, v in entry.items() if k != "language"}
        kept.append(entry)

    summary = {
        "kept": len(kept),
        "dropped": dropped,
        "was_v1": version == 1 and dropped == 0,
    }

    if summary["was_v1"]:
        # Already v1 → no-op
        return summary

    if dry_run:
        return summary

    # Backup + rewrite.
    bak = path.with_suffix(path.suffix + ".v2bak")
    if not bak.exists():
        shutil.copy2(str(path), str(bak))

    out = {"version": 1, "entries": kept}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="migrate_db_v2_to_v1",
        description="Migrate translation_db.json from v2 (multi-language) to v1 (zh-only).",
    )
    p.add_argument("path", type=Path, help="Path to translation_db.json")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing the file.",
    )
    args = p.parse_args(argv)

    summary = migrate(args.path, dry_run=args.dry_run)
    if summary["was_v1"]:
        print(f"[OK] {args.path}: already v1 (no-op)")
    else:
        action = "would write" if args.dry_run else "wrote"
        print(
            f"[OK] {args.path}: {action} v1 with {summary['kept']} entries; "
            f"dropped {summary['dropped']} non-zh entries; "
            f"backup at {args.path.with_suffix(args.path.suffix + '.v2bak')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
