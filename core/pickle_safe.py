#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whitelist-based safe pickle unpickler.

Raw ``pickle.loads`` on untrusted input is equivalent to remote code execution:
pickle opcodes can call ``os.system``, ``subprocess.Popen``, ``eval``, or any
other importable callable via ``__reduce__``. This module provides a drop-in
replacement that only resolves classes from a small, pre-approved whitelist
(pure data containers and primitive types) — anything else raises
``pickle.UnpicklingError``.

Intended consumers:
    - ``tools/rpa_unpacker.py``      (RPA archive index reading)
    - ``tools/rpyc_decompiler.py``   (Ren'Py compiled script AST loading)

The Ren'Py-specific behaviour (mapping ``renpy.*`` / ``store.*`` classes to
harmless stubs instead of raising) is kept inside ``rpyc_decompiler.py``
because it requires the stub class hierarchy defined there; this module
stays minimal and reusable.

Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

import io
import pickle
from typing import Any, FrozenSet

# Primitive builtins that appear in almost any legitimate pickle payload.
_SAFE_BUILTINS: FrozenSet[str] = frozenset(
    {
        "list",
        "tuple",
        "dict",
        "str",
        "bytes",
        "bytearray",
        "int",
        "float",
        "bool",
        "NoneType",
        "set",
        "frozenset",
        "complex",
    }
)

# Ordered / default dict variants that commonly appear in Python object graphs.
_SAFE_COLLECTIONS: FrozenSet[str] = frozenset(
    {
        "OrderedDict",
        "defaultdict",
    }
)

# Pickle internal helpers: pickle uses ``_codecs.encode`` (via the REDUCE
# opcode) to reconstruct bytes / unicode objects and ``copyreg._reconstructor``
# to rebuild simple class instances. These are pure data-rebuilding utilities
# and do not broaden the attack surface meaningfully, but they are required
# for legitimate payloads to load.
_SAFE_CODECS: FrozenSet[str] = frozenset({"encode", "decode"})
_SAFE_COPYREG: FrozenSet[str] = frozenset({"_reconstructor", "__newobj__"})


class SafeUnpickler(pickle.Unpickler):
    """Pickle unpickler limited to a small whitelist of safe types.

    Any ``find_class`` call for a module/name combination outside the
    whitelist raises ``pickle.UnpicklingError`` before instantiation, so
    side-effectful class resolution cannot happen.
    """

    def find_class(self, module: str, name: str) -> Any:
        # ``__builtin__`` is the Python 2 module name for builtins; pickle
        # payloads generated on Py2 sometimes reference it even when loaded
        # on Py3, so accept both aliases.
        if module in ("builtins", "__builtin__") and name in _SAFE_BUILTINS:
            return super().find_class(module, name)
        if module == "collections" and name in _SAFE_COLLECTIONS:
            return super().find_class(module, name)
        if module == "_codecs" and name in _SAFE_CODECS:
            return super().find_class(module, name)
        if module in ("copyreg", "copy_reg") and name in _SAFE_COPYREG:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"Refused to load {module}.{name} (not in safe whitelist)")


def safe_loads(data: bytes, *, encoding: str = "ASCII", errors: str = "strict") -> Any:
    """Whitelist-restricted drop-in for ``pickle.loads``.

    Args:
        data: Raw pickle byte stream from an untrusted source.
        encoding: Pickle text encoding (matches ``pickle.loads`` signature).
        errors: Pickle error handling mode (matches ``pickle.loads`` signature).

    Returns:
        The deserialised object graph (only built from whitelisted types).

    Raises:
        pickle.UnpicklingError: If the payload references any non-whitelisted
            class, or if the payload is malformed.
    """
    return SafeUnpickler(io.BytesIO(data), encoding=encoding, errors=errors).load()
