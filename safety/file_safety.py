#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TOCTOU-safe file size helpers for OOM-cap defense.

Re-checks file size after open() via os.fstat on the actual file
descriptor, defeating the TOCTOU (time-of-check / time-of-use) race
window between an earlier path-based stat() (e.g. ``Path.stat()``)
and the subsequent ``open()`` call.

Standard usage pattern:

    1. Path.stat() check (fast, may race with attacker growing file)
    2. open(filepath, ...) as f
    3. check_fstat_size(f, max_size)      ← this module
    4. proceed (read / stream) or reject

Round 47 Step 2 (D3) introduced the os.fstat-after-open pattern
inline in ``engines/csv_engine.py::_extract_csv`` to mitigate the
TOCTOU bypass vector flagged by the r46 security audit.

Round 48 Step 2 (D method scope expansion) extracts the pattern as
a reusable helper so it applies uniformly to other user-facing file
readers — initially the JSONL/JSON readers in the same csv_engine
module that share the same TOCTOU surface; future rounds may extend
to the 22+ user-facing JSON loaders identified in the r37-r47 OOM
hardening sweep.

Strict-stdlib: depends only on ``os``.  No third-party imports.  No
side effects (no logging, no I/O beyond fstat).  Caller decides how
to react to a False return — typically ``logger.warning(...)`` then
``return []`` or equivalent fallback.
"""

from __future__ import annotations

import os
from typing import IO


def check_fstat_size(file_obj: IO, max_size: int) -> tuple[bool, int]:
    """Check the size of an open file via os.fstat on its descriptor.

    Defeats the TOCTOU race where an attacker grows a file between an
    earlier path-based stat() and this open() — by checking the fd's
    actual size, the attack window collapses to the inside of open()
    itself (microseconds, OS-atomic on most filesystems).

    Parameters
    ----------
    file_obj : IO
        An open file object with a working ``.fileno()`` method.
    max_size : int
        Maximum allowed size in bytes (typically the same cap as the
        path-based pre-check; e.g. 50 * 1024 * 1024 = 50 MB).

    Returns
    -------
    (within_limit, observed_size) : tuple[bool, int]
        - ``within_limit`` is True if ``size <= max_size``, else False
        - ``observed_size`` is the byte count from os.fstat, or 0 on
          OSError (rare on a valid open fd)
        - On OSError or ValueError, returns ``(True, 0)`` — fail-open
          matching the design choice across r37-r47 path-based stat()
          callers.  Rationale:
          * OSError on a successfully opened fd is extremely rare
            (filesystem errors, permission drop post-open).
          * ValueError can be raised by ``fileno()`` if ``file_obj``
            is a non-real-file object (e.g. ``io.StringIO``,
            ``io.BytesIO``).  Real-file callers (the only intended
            callers per r48 Step 2 design) won't hit this path, but
            catching ValueError makes the helper safe to call from
            arbitrary file-like wrappers without surprises.
          If either fires, blocking the operation risks more harm
          than letting it proceed (the surrounding code paths have
          other guards — explicit cap pre-check before open, generic
          Exception handler downstream).

    Caller contract (Round 50 1e — closes r49 audit Security LOW 1):
        Callers MUST treat ``(ok=True, size=0)`` as "we don't know
        yet, but proceeding anyway" — observed_size is NOT reliable
        when ok=True after a fail-open path.  Real-file callers (the
        only intended consumers) will never see this; non-real-file
        wrappers (StringIO/BytesIO) will, and the helper proceeds
        rather than block.  Do not log ``observed_size`` as a
        ground-truth file-size metric to operators; use it only as
        an audit hint when paired with the ok=False branch.

    Examples
    --------
    Both branches shown explicitly (Round 50 C2 Security LOW-2):

    >>> from pathlib import Path
    >>> _MAX_SIZE = 50 * 1024 * 1024  # 50 MB
    >>> with open(filepath, encoding="utf-8") as f:
    ...     ok, size = check_fstat_size(f, _MAX_SIZE)
    ...     if not ok:
    ...         # ok=False branch: ``size`` IS reliable (real fstat result)
    ...         logger.warning(f"file grew past cap: {size} bytes > {_MAX_SIZE}")
    ...         return []
    ...     # ok=True branch: ``size`` may be 0 if fail-open fired (OSError /
    ...     # ValueError on fileno).  DO NOT log size as ground-truth here —
    ...     # use it only for audit context paired with ok=False above.
    ...     content = f.read()
    """
    try:
        size = os.fstat(file_obj.fileno()).st_size
    except (OSError, ValueError):
        return True, 0  # fail-open
    return size <= max_size, size
