"""Screen text extraction — scan Ren'Py ``.rpy`` files and pick out bare
English strings inside ``screen`` definitions.

This module is the *identification* half of the screen translator.  It
decides **what** to translate but performs no I/O beyond reading source
files.  The mutation half (translate + replace) lives in
``translators/_screen_patch.py``.

Kept as a hidden ``_screen_*`` module so callers continue to import from
``translators.screen`` (round 26 C-1 split).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# ── Data structures ─────────────────────────────────────────────────


@dataclass
class ScreenTextEntry:
    """One translatable string found inside a ``screen`` definition."""

    file_path: str  # Absolute path to the source .rpy
    line_number: int  # 1-based line number
    pattern_type: str  # "text" | "textbutton" | "tt_action" | "notify"
    original: str  # Literal content (unescaped)


# ── Regexes ─────────────────────────────────────────────────────────
# Module-level so Python compiles them once at import time.

_RE_TEXT = re.compile(r'^(\s+text\s+)"((?:[^"\\]|\\.)*)"')
_RE_TEXTBUTTON = re.compile(r'^(\s+textbutton\s+)"((?:[^"\\]|\\.)*)"')
_RE_TT_ACTION = re.compile(r'(tt\.Action\s*\(\s*)"((?:[^"\\]|\\.)*)"(\s*\))')
# ``Notify("...")`` toasts use the same shape as tt.Action.
_RE_NOTIFY = re.compile(r'(Notify\s*\(\s*)"((?:[^"\\]|\\.)*)"(\s*\))')

# Skip-list detection.
_RE_PURE_VAR = re.compile(r"^\[[\w.!]+\]$")
_FILE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".mp3",
    ".ogg",
    ".wav",
    ".ttf",
    ".otf",
    ".rpyc",
    ".rpy",
)


# ── Scan ────────────────────────────────────────────────────────────


def scan_screen_files(game_dir: Path) -> list[Path]:
    """Return every ``.rpy`` under ``game_dir`` excluding tl/renpy/lib."""
    result = []
    for rpy in sorted(game_dir.rglob("*.rpy")):
        rel = rpy.relative_to(game_dir)
        if any(p in ("tl", "renpy", "lib") for p in rel.parts):
            continue
        result.append(rpy)
    return result


# ── Skip logic ──────────────────────────────────────────────────────


def _should_skip(text: str) -> bool:
    """Return True for strings that should not be sent to the translator.

    Skips empties, single characters, pre-translated Chinese, pure
    ``[var]`` references, pure punctuation/number strings, and file paths.
    """
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) <= 1:
        return True
    if any("\u4e00" <= c <= "\u9fff" for c in stripped):
        return True
    if _RE_PURE_VAR.fullmatch(stripped):
        return True
    if not any(c.isalpha() for c in stripped):
        return True
    lower = stripped.lower()
    if any(lower.endswith(ext) for ext in _FILE_EXTENSIONS):
        return True
    # Strip Ren'Py tags before the path heuristic so ``{/size}`` etc.
    # don't falsely trigger the ``/`` + ``.`` match.
    tag_stripped = re.sub(r"\{/?[^}]*\}", "", stripped)
    if "/" in tag_stripped and "." in tag_stripped:
        return True
    return False


def _line_has_underscore_wrap(line: str) -> bool:
    """True if any ``_("..."`` wrapper appears before the first quote on
    the line — those strings are already handled by Ren'Py's tl framework.
    """
    before_quote = line.split('"')[0]
    return "_(" in before_quote


# ── Extract ─────────────────────────────────────────────────────────


def extract_screen_strings(file_path: Path) -> list[ScreenTextEntry]:
    """Extract all bare-English entries from a single ``.rpy`` file.

    Walks the file line-by-line tracking whether we are inside a
    ``screen`` definition (so labels/default-blocks are not scanned), and
    matches each of the four line patterns (text / textbutton /
    tt.Action / Notify).
    """
    try:
        content = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        try:
            content = file_path.read_text(encoding="latin-1")
        except OSError:
            return []

    lines = content.splitlines()
    entries: list[ScreenTextEntry] = []

    in_screen = False
    screen_indent = 0

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Detect screen definition start.
        if stripped.startswith("screen ") and stripped.rstrip().endswith(":"):
            in_screen = True
            screen_indent = indent
            continue

        # Detect screen definition end (non-blank, non-comment at or below
        # the opening indent).
        if in_screen and stripped and not stripped.startswith("#"):
            if indent <= screen_indent:
                in_screen = False

        if not in_screen:
            continue
        if stripped.startswith("#"):
            continue
        if _line_has_underscore_wrap(line):
            continue

        line_num = i + 1
        file_str = str(file_path)

        m = _RE_TEXT.match(line)
        if m:
            text = m.group(2)
            if not _should_skip(text):
                entries.append(ScreenTextEntry(file_str, line_num, "text", text))
            continue

        m = _RE_TEXTBUTTON.match(line)
        if m:
            text = m.group(2)
            if not _should_skip(text):
                entries.append(ScreenTextEntry(file_str, line_num, "textbutton", text))
            continue

        for m in _RE_TT_ACTION.finditer(line):
            text = m.group(2)
            if not _should_skip(text):
                entries.append(ScreenTextEntry(file_str, line_num, "tt_action", text))

        for m in _RE_NOTIFY.finditer(line):
            text = m.group(2)
            if not _should_skip(text):
                entries.append(ScreenTextEntry(file_str, line_num, "notify", text))

    return entries
