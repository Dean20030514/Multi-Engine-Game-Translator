#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared constants for the rpyc decompiler's Tier 1 and Tier 2 chains.

Split from ``tools/rpyc_decompiler.py`` in round 40 as the leaf module
both tiers depend on.  Keeping whitelist + format constants here
instead of in one of the tier modules avoids a circular import when
the main module re-exports symbols from Tier 2 at the end.

Round 26 C-3 (originally in the monolithic ``rpyc_decompiler.py``):
the Tier 1 injected helper script and the Tier 2 ``_RestrictedUnpickler``
both use this allowlist to reject classes outside the safe set
— otherwise a malicious .rpyc could smuggle ``os.system`` /
``builtins.eval`` through the pickle ``find_class`` hook.
Co-locating them in this leaf module prevents silent drift.

``_WHITELIST_TIER1_PY2_EXTRAS`` captures the only legitimate
divergence: Ren'Py 7.x ships Python 2.7, which has ``long`` and
``unicode`` as distinct builtins; Tier 2 runs under Python 3 only
and does not need them.
"""

from __future__ import annotations

from typing import Dict, List


RPYC2_HEADER = b"RENPY RPC2"

# Slot 1 = AST data, Slot 2 = source checksum (we only need slot 1)
_AST_SLOT = 1


_SHARED_WHITELIST: Dict[str, List[str]] = {
    "builtins": [
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
    ],
    "collections": ["OrderedDict", "defaultdict"],
    "_codecs": ["encode", "decode"],
    "copyreg": ["_reconstructor", "__newobj__"],
}

_WHITELIST_TIER1_PY2_EXTRAS: Dict[str, List[str]] = {
    "builtins": ["long", "unicode"],
}
