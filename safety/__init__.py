#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Top-level safety helpers.

Round 56 audit M2: extracted from ``core/`` to its own top-level
package because the helpers it provides (TOCTOU defenses, etc.) are
consumed by ``core``, ``file_processor``, ``engines``, ``pipeline``,
``translators``, ``tools``, and ``gui_dialogs`` alike. Keeping the
helper inside ``core/`` blurred the layering rule "``file_processor``
must not import ``core`` at module load time" — see CLAUDE.md
maintenance rules and ``HANDOFF.md`` Round 56 fix log.

The helper itself is unchanged, only the import path migrates from
``core.file_safety`` → ``safety.file_safety``. Callers updated in
the same commit; the r48 mock-target consistency CI guard now pins
``safety.file_safety.os.fstat``.
"""

from safety.file_safety import check_fstat_size

__all__ = ["check_fstat_size"]
