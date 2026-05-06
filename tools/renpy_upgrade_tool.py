#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ren'Py 7.x → 8.x Upgrade Assistant
====================================
Scans .rpy files for common Python 2 → Python 3 incompatibilities
and attempts to auto-fix them.

Usage:
    python renpy_upgrade_tool.py <project_game_directory> [--fix] [--backup]

    --fix       Apply fixes automatically (without this flag, only scan and report)
    --backup    Create .bak backup files before modifying (recommended with --fix)

Examples:
    python renpy_upgrade_tool.py ./game                 # Scan only, report issues
    python renpy_upgrade_tool.py ./game --fix --backup  # Fix issues with backups

Can also be imported and called programmatically::

    from tools.renpy_upgrade_tool import scan_directory, print_report, apply_fixes
    results, n = scan_directory("path/to/game")
    print_report(results, n)
"""

from __future__ import annotations

import os
import re
import sys
import shutil
import argparse
from datetime import datetime
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Rule definitions
# Each rule: (id, description, regex_pattern, replacement_or_None, severity)
#   severity: "error" = will definitely break, "warning" = might break
#   replacement = None means "cannot auto-fix, manual review needed"
# ---------------------------------------------------------------------------

RULES = []


def rule(rule_id, description, pattern, replacement, severity="error"):
    RULES.append(
        {
            "id": rule_id,
            "description": description,
            "pattern": re.compile(pattern),
            "replacement": replacement,
            "severity": severity,
        }
    )


# ---- Python 2 print statement → print() function ----
# Matches: print "text"  /  print 'text'  /  print variable
# Avoids: print(...)  which is already correct
# Only match inside python/init python blocks or inline $ lines
rule(
    "PY3-001",
    'print statement → print() function: print "x" should be print("x")',
    r"(?<=\$\s)print\s+(?!\()(.*)",
    lambda m: f"print({m.group(1).strip()})",
    "error",
)

rule(
    "PY3-001b",
    "print statement → print() function (in python block)",
    r"^(\s+)print\s+(?!\()(.+)",
    lambda m: f"{m.group(1)}print({m.group(2).strip()})",
    "error",
)

# ---- dict.has_key(x) → x in dict ----
rule(
    "PY3-002",
    "dict.has_key(x) → x in dict",
    r"(\w+)\.has_key\(([^)]+)\)",
    lambda m: f"{m.group(2).strip()} in {m.group(1)}",
    "error",
)

# ---- <> operator → != ----
rule(
    "PY3-003",
    "<> operator → != operator",
    r"(?<!=)\s*<>\s*(?!=)",
    " != ",
    "error",
)

# ---- xrange() → range() ----
rule(
    "PY3-004",
    "xrange() → range()",
    r"\bxrange\s*\(",
    "range(",
    "error",
)

# ---- raw_input() → input() ----
rule(
    "PY3-005",
    "raw_input() → input()",
    r"\braw_input\s*\(",
    "input(",
    "error",
)

# ---- dict.iterkeys() / itervalues() / iteritems() ----
rule(
    "PY3-006a",
    ".iterkeys() → .keys()",
    r"\.iterkeys\s*\(\)",
    ".keys()",
    "error",
)
rule(
    "PY3-006b",
    ".itervalues() → .values()",
    r"\.itervalues\s*\(\)",
    ".values()",
    "error",
)
rule(
    "PY3-006c",
    ".iteritems() → .items()",
    r"\.iteritems\s*\(\)",
    ".items()",
    "error",
)

# ---- unicode() → str() ----
rule(
    "PY3-007",
    "unicode() → str()",
    r"\bunicode\s*\(",
    "str(",
    "error",
)

# ---- long type → int ----
rule(
    "PY3-008",
    "long() → int() (Python 3 unified int/long)",
    r"\blong\s*\(",
    "int(",
    "warning",
)

# ---- except Exception, e → except Exception as e ----
rule(
    "PY3-009",
    "except X, e → except X as e",
    r"except\s+(\w+)\s*,\s*(\w+)\s*:",
    lambda m: f"except {m.group(1)} as {m.group(2)}:",
    "error",
)

# ---- raise with string ----
rule(
    "PY3-010",
    'raise "string" → raise Exception("string")',
    r'raise\s+"([^"]*)"',
    lambda m: f'raise Exception("{m.group(1)}")',
    "error",
)
rule(
    "PY3-010b",
    "raise 'string' → raise Exception('string')",
    r"raise\s+'([^']*)'",
    lambda m: f"raise Exception('{m.group(1)}')",
    "error",
)

# ---- Integer division (spaced operator like `a / b`, avoids paths & strings) ----
rule(
    "PY3-011",
    "Integer division: / may return float in Python 3 (review manually)",
    r"(?<=[\w)\]])\s+/\s+(?=[\w(])",
    None,
    "warning",
)

# ---- apply() removed ----
rule(
    "PY3-012",
    "apply(func, args) → func(*args)",
    r"\bapply\s*\(\s*(\w+)\s*,\s*([^)]+)\)",
    lambda m: f"{m.group(1)}(*{m.group(2).strip()})",
    "error",
)

# ---- reduce() moved to functools ----
rule(
    "PY3-013",
    "reduce() moved to functools.reduce() in Python 3",
    r"(?<!functools\.)\breduce\s*\(",
    None,  # Needs manual fix — add "from functools import reduce"
    "warning",
)

# ---- map/filter return iterators, not lists ----
rule(
    "PY3-014",
    "map()/filter() returns iterator in Python 3, may need list() wrapper",
    r"\b(?:map|filter)\s*\(",
    None,
    "warning",
)

# ---- Ren'Py specific: old-style ui. calls ----
rule(
    "RENPY-001",
    "Deprecated ui.* function call (use screen language instead)",
    r"\bui\.(text|button|add|image|imagebutton|textbutton|bar|vbar|"
    r"hbox|vbox|grid|fixed|frame|window|null|timer|input|key|"
    r"side|viewport|imagemap|hotspot|hotbar)\s*\(",
    None,  # Cannot auto-fix — needs manual screen rewrite
    "warning",
)

# ---- Ren'Py: style.* direct access (old style) ----
rule(
    "RENPY-002",
    "Old style property access: style.default.* (use style prefix in screens)",
    r"\bstyle\.default\.\w+",
    None,
    "warning",
)

# ---- Ren'Py: im.Composite / im.* image manipulators ----
rule(
    "RENPY-003",
    "im.* image manipulators may be deprecated, consider Transform()",
    r"\bim\.(Composite|Scale|Crop|Flip|Grayscale|Sepia|Alpha|"
    r"MatrixColor|FactorScale)\s*\(",
    None,
    "warning",
)

# ---- Ren'Py: layout.* functions ----
rule(
    "RENPY-004",
    "layout.* functions are deprecated in Ren'Py 8",
    r"\blayout\.(yesno_screen|navigation|imagemap_navigation)\s*\(",
    None,
    "warning",
)

# ---- Ren'Py: config.keymap old entries ----
rule(
    "RENPY-005",
    "Check config.keymap — some key names changed in Ren'Py 8",
    r"\bconfig\.keymap\s*\[",
    None,
    "warning",
)

# ---- tuple parameter unpacking (Python 3 removed) ----
rule(
    "PY3-015",
    "Tuple parameter unpacking removed in Python 3: def f((a,b))",
    r"def\s+\w+\s*\([^)]*\([^)]+\)[^)]*\)",
    None,
    "error",
)

# ---- exec statement ----
rule(
    "PY3-016",
    "exec as statement → exec() function",
    r"(?<=\s)exec\s+(?!\()",
    None,
    "warning",
)

# ---- basestring removed ----
rule(
    "PY3-017",
    "basestring removed in Python 3, use str instead",
    r"\bbasestring\b",
    "str",
    "error",
)

# ---- cmp() removed ----
rule(
    "PY3-018",
    "cmp() removed in Python 3",
    r"\bcmp\s*\(",
    None,
    "warning",
)

# ---- sorted() with cmp parameter ----
rule(
    "PY3-019",
    "sorted()/list.sort() cmp parameter removed in Python 3, use key=",
    r"sorted\s*\([^)]*cmp\s*=",
    None,
    "warning",
)


# ---------------------------------------------------------------------------
# Special multi-line rule: RENPY-020
# show image_name: with trailing colon but NO ATL block following.
# Ren'Py 7 tolerates this; Ren'Py 8 / Generate Translations raises
# "show statement expects a non-empty block".
# Fix: remove the trailing colon.
# This cannot be a single-line regex rule because we must look ahead to
# determine whether an ATL block (indented xpos/ypos/etc.) follows.
# ---------------------------------------------------------------------------

_RE_SHOW_WITH_COLON = re.compile(r"^(\s*show\s+\S+(?:\s+\S+)*):\s*$")
_SHOW_ATL_KEYWORDS = re.compile(r"\b(at|behind|as|with|onlayer|zorder|screen)\b")

_RENPY020_RULE_INFO = {
    "id": "RENPY-020",
    "description": 'show with empty ATL block: "show image:" → "show image" (remove trailing colon)',
    "pattern": _RE_SHOW_WITH_COLON,
    "replacement": "special",
    "severity": "error",
}


def _scan_show_empty_atl(lines: list[str], filepath: str) -> list:
    """Multi-line scan for RENPY-020: show statements with colon but no ATL block."""
    results = []
    for i, line in enumerate(lines):
        m = _RE_SHOW_WITH_COLON.match(line)
        if not m:
            continue
        # Skip if line contains ATL sub-clause keywords (at/behind/as/with etc.)
        body = m.group(1).split(None, 1)
        after_show = body[1] if len(body) > 1 else ""
        if _SHOW_ATL_KEYWORDS.search(after_show):
            continue
        # Look ahead: if next non-blank line is MORE indented, it's an ATL block → colon is needed
        show_indent = len(line) - len(line.lstrip())
        has_atl_block = False
        for j in range(i + 1, min(i + 5, len(lines))):
            next_stripped = lines[j].strip()
            if not next_stripped:
                continue
            next_indent = len(lines[j]) - len(lines[j].lstrip())
            if next_indent > show_indent:
                has_atl_block = True
            break  # only check first non-blank line
        if has_atl_block:
            continue  # colon is correct, ATL block follows
        # No ATL block → remove trailing colon
        fixed = m.group(1)
        results.append(
            ScanResult(
                filepath=filepath,
                line_number=i + 1,
                line_content=line.rstrip(),
                rule_info=_RENPY020_RULE_INFO,
                fixed_line=fixed,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class ScanResult:
    def __init__(self, filepath, line_number, line_content, rule_info, fixed_line=None):
        self.filepath = filepath
        self.line_number = line_number
        self.line_content = line_content
        self.rule = rule_info
        self.fixed_line = fixed_line


def is_in_python_context(lines, line_idx):
    """Check if a line is inside a python block or is an inline $ statement."""
    line = lines[line_idx].strip()
    if line.startswith("$") or line.startswith("python"):
        return True

    # Look backward for python/init python block
    indent = len(lines[line_idx]) - len(lines[line_idx].lstrip())
    for i in range(line_idx - 1, max(line_idx - 50, -1), -1):
        prev = lines[i].strip()
        if re.match(r"^(init\s+)?python(\s+\w+)?\s*:", prev):
            prev_indent = len(lines[i]) - len(lines[i].lstrip())
            if indent > prev_indent:
                return True
            break
        if prev and not prev.startswith("#"):
            prev_indent = len(lines[i]) - len(lines[i].lstrip())
            if prev_indent < indent:
                if not re.match(r"^(if|elif|else|for|while|try|except|with|def|class)", prev):
                    break
    return False


def scan_file(filepath):
    """Scan a single .rpy file and return list of ScanResult."""
    results = []
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            content = f.read()
            lines = content.split("\n")
    except (UnicodeDecodeError, IOError) as e:
        print(f"  [!] Cannot read {filepath}: {e}")
        return results

    # Multi-line rule: RENPY-020 (show empty ATL block)
    results.extend(_scan_show_empty_atl(lines, filepath))

    for line_idx, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith("#") or not stripped:
            continue

        for r in RULES:
            match = r["pattern"].search(line)
            if not match:
                continue

            # PY3 rules require python context ($ line or python: block)
            if r["id"].startswith("PY3"):
                if r["id"] == "PY3-001":
                    pass  # lookbehind already constrains to $ lines
                else:
                    if not is_in_python_context(lines, line_idx):
                        continue

            fixed_line = None
            if r["replacement"] is not None:
                if callable(r["replacement"]):
                    fixed_line = r["pattern"].sub(r["replacement"], line)
                else:
                    fixed_line = r["pattern"].sub(r["replacement"], line)

            results.append(
                ScanResult(
                    filepath=filepath,
                    line_number=line_idx + 1,
                    line_content=line.rstrip(),
                    rule_info=r,
                    fixed_line=fixed_line,
                )
            )

    return results


def scan_directory(game_dir):
    """Scan all .rpy files in a directory recursively."""
    all_results = []
    file_count = 0

    for root, dirs, files in os.walk(game_dir):
        # Skip common non-essential directories
        dirs[:] = [d for d in dirs if d not in ("cache", ".git", "__pycache__")]
        for fname in sorted(files):
            if fname.endswith(".rpy"):
                fpath = os.path.join(root, fname)
                file_count += 1
                results = scan_file(fpath)
                all_results.extend(results)

    return all_results, file_count


def apply_fixes(results, do_backup=True):
    """Apply auto-fixable changes to files."""
    # Group results by file
    by_file = defaultdict(list)
    for r in results:
        if r.fixed_line is not None:
            by_file[r.filepath].append(r)

    fixed_count = 0
    for filepath, file_results in by_file.items():
        if do_backup:
            backup_path = filepath + ".bak"
            if not os.path.exists(backup_path):
                shutil.copy2(filepath, backup_path)

        with open(filepath, "r", encoding="utf-8-sig") as f:
            original = f.read()
        lines = original.split("\n")
        has_trailing_nl = original.endswith("\n")

        for r in sorted(file_results, key=lambda x: x.line_number, reverse=True):
            idx = r.line_number - 1
            if idx < len(lines) and lines[idx].rstrip() == r.line_content:
                lines[idx] = r.fixed_line
                fixed_count += 1

        result = "\n".join(lines)
        if has_trailing_nl and not result.endswith("\n"):
            result += "\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(result)

    return fixed_count


def delete_rpyc_files(game_dir):
    """Delete all Ren'Py cache files (.rpyc/.rpymc/.rpyb) to force recompilation."""
    count = 0
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d not in (".git",)]
        for fname in files:
            if fname.endswith((".rpyc", ".rpymc", ".rpyb")):
                os.remove(os.path.join(root, fname))
                count += 1
    return count


def print_report(results, file_count):
    """Print a formatted scan report."""
    errors = [r for r in results if r.rule["severity"] == "error"]
    warnings = [r for r in results if r.rule["severity"] == "warning"]
    fixable = [r for r in results if r.fixed_line is not None]
    manual = [r for r in results if r.fixed_line is None]

    print("=" * 70)
    print("  Ren'Py 7.x → 8.x Upgrade Scan Report")
    print(f"  Scan time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print(f"  Files scanned:        {file_count}")
    print(f"  Total issues found:   {len(results)}")
    print(f"    Errors:             {len(errors)}")
    print(f"    Warnings:           {len(warnings)}")
    print(f"    Auto-fixable:       {len(fixable)}")
    print(f"    Needs manual fix:   {len(manual)}")
    print("=" * 70)

    if not results:
        print("\n  No issues found! Your project looks ready for Ren'Py 8.x.")
        print("  (Still recommended: test thoroughly after upgrading)\n")
        return

    # Group by file
    by_file = defaultdict(list)
    for r in results:
        by_file[r.filepath].append(r)

    for filepath, file_results in sorted(by_file.items()):
        try:
            rel = os.path.relpath(filepath)
        except ValueError:
            rel = filepath
        print(f"\n--- {rel} ---")
        for r in sorted(file_results, key=lambda x: x.line_number):
            severity_mark = "ERROR" if r.rule["severity"] == "error" else "WARN "
            fix_mark = "[auto-fix]" if r.fixed_line is not None else "[manual]  "
            print(
                f"  L{r.line_number:<5} {severity_mark} {fix_mark} [{r.rule['id']}] {r.rule['description']}"
            )
            print(f"         {r.line_content.strip()}")
            if r.fixed_line is not None:
                print(f"      => {r.fixed_line.strip()}")

    print("\n" + "=" * 70)
    print("  Legend:")
    print("    ERROR     = Will break in Ren'Py 8.x / Python 3")
    print("    WARN      = Might break or is deprecated, review recommended")
    print("    [auto-fix]= Can be fixed automatically with --fix flag")
    print("    [manual]  = Requires manual code review and changes")
    print("=" * 70)


def run_scan(
    game_dir: str, fix: bool = False, backup: bool = True, clean_rpyc: bool = False
) -> tuple[list[ScanResult], int]:
    """Programmatic entry point — scan, optionally fix, return (results, file_count)."""
    results, file_count = scan_directory(game_dir)
    print_report(results, file_count)

    if clean_rpyc:
        count = delete_rpyc_files(game_dir)
        print(f"\n  Deleted {count} .rpyc file(s).\n")

    if fix:
        fixable = [r for r in results if r.fixed_line is not None]
        if fixable:
            fixed = apply_fixes(results, do_backup=backup)
            print(f"\n  Applied {fixed} auto-fix(es).\n")

    return results, file_count


def main():
    parser = argparse.ArgumentParser(
        description="Ren'Py 7.x → 8.x Upgrade Assistant: "
        "Scan and fix Python 2 / old Ren'Py API incompatibilities."
    )
    parser.add_argument("game_dir", help="Path to the Ren'Py project's 'game' directory")
    parser.add_argument(
        "--fix", action="store_true", help="Apply auto-fixes to files (default: scan only)"
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create .bak backup files before modifying (use with --fix)",
    )
    parser.add_argument(
        "--clean-rpyc", action="store_true", help="Delete all .rpyc files to force recompilation"
    )
    args = parser.parse_args()

    game_dir_path = Path(args.game_dir).resolve()
    if not game_dir_path.is_dir():
        print(f"Error: Directory not found: {game_dir_path}")
        sys.exit(1)
    game_dir = str(game_dir_path)

    print(f"\nScanning: {game_dir}\n")

    results, file_count = scan_directory(game_dir)
    print_report(results, file_count)

    if args.clean_rpyc:
        count = delete_rpyc_files(game_dir)
        print(f"\n  Deleted {count} .rpyc file(s).\n")

    if args.fix:
        fixable = [r for r in results if r.fixed_line is not None]
        if fixable:
            fixed = apply_fixes(results, do_backup=args.backup)
            backup_msg = " (backups created)" if args.backup else ""
            print(f"\n  Applied {fixed} auto-fix(es){backup_msg}.")
            print("  Please review the changes and test your project.\n")
        else:
            print("\n  No auto-fixable issues found.\n")
    elif any(r.fixed_line is not None for r in results):
        print("\n  Tip: Run with --fix --backup to auto-fix issues marked [auto-fix]\n")


if __name__ == "__main__":
    main()
