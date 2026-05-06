#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Meta-runner — delegates to the six focused test modules.

Historical callers (CI, scripts, IDE integrations) still invoke
``python tests/test_all.py``; that entry point remains the single
"run every unit test" shortcut.  Each tests/test_*.py module also has
its own ``if __name__ == '__main__':`` block for targeted runs.

Prior to round 29 this file held all 113 test function bodies
(2,539 lines total, 3× the project's 800-line soft cap).  Round 29
split those bodies into five focused modules; round 33 Commit 4 prep
added a sixth (``test_runtime_hook``) after the runtime-hook tests
accreted in ``test_translation_state`` from rounds 31–33 pushed the
latter past the same 800-line limit.

* ``test_api_client.py``            — APIClient / retries / HTTP pool
* ``test_file_processor.py``        — splitter / checker / patcher / validator
* ``test_translators.py``           — direct / tl_parser / retranslator / screen
* ``test_glossary_prompts_config.py`` — Glossary / prompts / Config / lang_config
* ``test_translation_state.py``     — ProgressTracker / TranslationDB / dedupe
* ``test_runtime_hook.py``          — runtime-hook emitter + v2 schema + gui overrides
* ``test_tl_retry.py``              — Round 53 W1/W3: retry stage parallelism + LLM ID drift detection
* ``test_pickle_safe_redteam.py``   — Round 53 monitor #1: pickle whitelist red-team
* ``test_unity_xunity_engine.py``   — Round 55: Unity XUnity AutoTranslator engine
* ``test_complex_fixture.py``       — Round 57 T3: complex .rpy fixture round-trip
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import (
    test_api_client,
    test_file_processor,
    test_translators,
    test_glossary_prompts_config,
    test_translation_state,
    test_runtime_hook,
    test_tl_retry,
    test_pickle_safe_redteam,
    test_unity_xunity_engine,
    test_complex_fixture,
    test_main_cli,
)


def main() -> int:
    total = 0
    total += test_api_client.run_all()
    total += test_file_processor.run_all()
    total += test_translators.run_all()
    total += test_glossary_prompts_config.run_all()
    total += test_translation_state.run_all()
    total += test_runtime_hook.run_all()
    total += test_tl_retry.run_all()
    total += test_pickle_safe_redteam.run_all()
    total += test_unity_xunity_engine.run_all()
    total += test_complex_fixture.run_all()
    total += test_main_cli.run_all()
    print()
    print("=" * 40)
    print(f"ALL {total} TESTS PASSED")
    print("=" * 40)
    return total


if __name__ == "__main__":
    main()
