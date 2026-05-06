#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rpyc decompiler — Tier 2: standalone text extraction (no Ren'Py runtime).

Split from ``tools/rpyc_decompiler.py`` in round 40.  This tier runs when
the game's bundled Python is unavailable or Tier 1 (game-python
decompilation) fails: it unpickles the ``.rpyc`` AST under a strict
class whitelist, replaces ``renpy.*`` / ``store.*`` references with
harmless dummy stubs, and walks the tree to extract translatable text
(Say / Menu / TranslateString nodes).

The class-whitelist source of truth is ``tools._rpyc_shared._SHARED_
WHITELIST`` — shared between Tier 1 (injected helper script) and Tier 2
so a malicious .rpyc cannot smuggle ``os.system`` / ``builtins.eval``
through the pickle ``find_class`` hook by exploiting any drift.

Public entry point: :func:`extract_strings_from_rpyc` returning a list
of ``{"type": ..., "text": ..., ...}`` dicts.  The private helpers
(``_DummyClass``, ``_RestrictedUnpickler``, ``_read_rpyc_data``,
``_safe_unpickle``, ``_extract_text_from_node``) are re-exported by
``tools.rpyc_decompiler`` so existing callers / tests that imported
them from the legacy monolith continue to work unchanged.
"""

from __future__ import annotations

import io
import logging
import pickle
import struct
import zlib
from pathlib import Path
from typing import Any, Optional

from tools._rpyc_shared import RPYC2_HEADER, _SHARED_WHITELIST

logger = logging.getLogger(__name__)


class _DummyClass:
    """Stub class for unpickling Ren'Py AST without the renpy module."""

    _state = None
    _class_name = "?"
    _module_name = "?"

    def __init__(self, *args, **kwargs):
        pass

    def append(self, value):
        if self._state is None:
            self._state = []
        self._state.append(value)

    def __getitem__(self, key):
        return self.__dict__.get(key)

    def __setitem__(self, key, value):
        self.__dict__[key] = value

    def __eq__(self, other):
        return False

    def __hash__(self):
        return id(self)

    def __getstate__(self):
        if self._state is not None:
            return self._state
        return self.__dict__

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self._state = state

    def __repr__(self):
        return f"<{self._module_name}.{self._class_name}>"


class _RestrictedUnpickler(pickle.Unpickler):
    """Whitelist unpickler for .rpyc AST data (Tier 2 — standalone path).

    - ``renpy.*`` / ``store.*`` classes are replaced with harmless dummy stubs.
    - A small set of primitive builtins and container types are allowed through.
    - Everything else (``os.system``, ``subprocess.Popen``, ``builtins.eval``,
      etc.) raises ``pickle.UnpicklingError`` — crashing loudly instead of
      silently executing attacker-supplied code.

    Whitelist comes from ``tools._rpyc_shared._SHARED_WHITELIST`` so it
    cannot drift out of sync with the Tier 1 injected helper (see
    ``tools.rpyc_decompiler._DECOMPILE_HELPER_TEMPLATE`` /
    ``_render_decompile_helper``).
    """

    _SAFE_BUILTINS = frozenset(_SHARED_WHITELIST["builtins"])
    _SAFE_COLLECTIONS = frozenset(_SHARED_WHITELIST["collections"])
    _SAFE_CODECS = frozenset(_SHARED_WHITELIST["_codecs"])
    _SAFE_COPYREG = frozenset(_SHARED_WHITELIST["copyreg"])

    def find_class(self, module: str, name: str):
        if module.startswith(("renpy", "store")):
            cls = type(
                name,
                (_DummyClass,),
                {
                    "__module__": module,
                    "_class_name": name,
                    "_module_name": module,
                },
            )
            return cls
        if module in ("builtins", "__builtin__") and name in self._SAFE_BUILTINS:
            return super().find_class(module, name)
        if module == "collections" and name in self._SAFE_COLLECTIONS:
            return super().find_class(module, name)
        if module == "_codecs" and name in self._SAFE_CODECS:
            return super().find_class(module, name)
        if module in ("copyreg", "copy_reg") and name in self._SAFE_COPYREG:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"Refused to load {module}.{name} (not in safe whitelist)")


def _read_rpyc_data(file_obj: io.BufferedIOBase, slot: int) -> Optional[bytes]:
    """Read binary data from a specific slot in a .rpyc file.

    RPYC2 format:
        - Header: b"RENPY RPC2"
        - Followed by slot entries: (slot_id: u32, start: u32, length: u32)
        - Slot 0 marks end of headers

    Legacy format (pre-RPYC2):
        - Entire file is zlib-compressed AST data (slot 1 only)
    """
    file_obj.seek(0)
    header = file_obj.read(1024)

    # Legacy format
    if header[: len(RPYC2_HEADER)] != RPYC2_HEADER:
        if slot != 1:
            return None
        file_obj.seek(0)
        try:
            return zlib.decompress(file_obj.read())
        except zlib.error:
            return None

    # RPYC2 format
    pos = len(RPYC2_HEADER)
    while pos + 12 <= len(header):
        s, start, length = struct.unpack("III", header[pos : pos + 12])
        if s == slot:
            file_obj.seek(start)
            try:
                return zlib.decompress(file_obj.read(length))
            except zlib.error:
                return None
        if s == 0:
            return None
        pos += 12
    return None


def _safe_unpickle(data: bytes) -> Any:
    """Unpickle RPYC AST data using restricted unpickler."""
    return _RestrictedUnpickler(io.BytesIO(data), encoding="bytes").load()


def _extract_text_from_node(node: Any) -> list[dict]:
    """Recursively extract translatable text from an AST node (DummyClass tree).

    Returns list of dicts with keys: type, text, who (optional), identifier (optional).
    """
    results: list[dict] = []

    if node is None:
        return results

    class_name = getattr(node, "_class_name", "") or type(node).__name__

    # Say statement: has 'what' (text) and optionally 'who' (speaker)
    if class_name == "Say":
        what = getattr(node, "what", None)
        who = getattr(node, "who", None)
        if what and isinstance(what, (str, bytes)):
            text = what.decode("utf-8", errors="replace") if isinstance(what, bytes) else what
            entry = {"type": "say", "text": text}
            if who:
                entry["who"] = (
                    who.decode("utf-8", errors="replace") if isinstance(who, bytes) else str(who)
                )
            results.append(entry)

    # TranslateString: has 'old' and 'new' and 'language'
    elif class_name == "TranslateString":
        old = getattr(node, "old", None)
        new = getattr(node, "new", None)
        lang = getattr(node, "language", None)
        if old and isinstance(old, (str, bytes)):
            text = old.decode("utf-8", errors="replace") if isinstance(old, bytes) else old
            entry = {"type": "translate_string", "old": text}
            if new and isinstance(new, (str, bytes)):
                entry["new"] = (
                    new.decode("utf-8", errors="replace") if isinstance(new, bytes) else new
                )
            if lang:
                entry["language"] = (
                    lang.decode("utf-8", errors="replace") if isinstance(lang, bytes) else str(lang)
                )
            results.append(entry)

    # Menu: has 'items' list of (caption, condition, block) tuples
    elif class_name == "Menu":
        items = getattr(node, "items", None)
        if items and isinstance(items, (list, tuple)):
            for item in items:
                if isinstance(item, (list, tuple)) and len(item) >= 1:
                    caption = item[0]
                    if caption and isinstance(caption, (str, bytes)):
                        text = (
                            caption.decode("utf-8", errors="replace")
                            if isinstance(caption, bytes)
                            else caption
                        )
                        results.append({"type": "menu", "text": text})

    # Recurse into child nodes
    # Check common container attributes
    for attr_name in ("block", "children", "entries", "items", "next"):
        child = getattr(node, attr_name, None)
        if child is None:
            continue
        if isinstance(child, (list, tuple)):
            for item in child:
                if hasattr(item, "__dict__") or hasattr(item, "_class_name"):
                    results.extend(_extract_text_from_node(item))
        elif hasattr(child, "__dict__") or hasattr(child, "_class_name"):
            results.extend(_extract_text_from_node(child))

    # Also check _state for DummyClass nodes
    state = getattr(node, "_state", None)
    if isinstance(state, (list, tuple)):
        for item in state:
            if hasattr(item, "__dict__") and hasattr(item, "_class_name"):
                results.extend(_extract_text_from_node(item))

    return results


def extract_strings_from_rpyc(rpyc_path: Path) -> list[dict]:
    """Extract translatable strings from a single .rpyc file (Tier 2).

    Returns list of dicts, each containing at least 'type' and 'text'.
    """
    with open(rpyc_path, "rb") as f:
        for slot in [1, 2]:
            data = _read_rpyc_data(f, slot)
            if data is not None:
                try:
                    raw = _safe_unpickle(data)
                except Exception as exc:
                    logger.warning("[RPYC] Unpickle 失败 %s: %s", rpyc_path.name, exc)
                    return []

                # The unpickled data is typically (checksum, stmts_list)
                stmts = None
                if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                    stmts = raw[1]
                elif isinstance(raw, list):
                    stmts = raw
                else:
                    stmts = raw

                results: list[dict] = []
                if isinstance(stmts, (list, tuple)):
                    for stmt in stmts:
                        results.extend(_extract_text_from_node(stmt))
                else:
                    results.extend(_extract_text_from_node(stmts))

                if results:
                    return results
            f.seek(0)

    return []
