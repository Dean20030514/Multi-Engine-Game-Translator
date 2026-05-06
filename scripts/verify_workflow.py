#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round 45 Commit 8: local verify for .github/workflows/test.yml.

Catches the three most common CI workflow regressions before they land
in a commit / push:

  1. YAML syntax errors (parse failure)
  2. Matrix expansion changes (OS or Python version drift)
  3. Missing `shell: bash` on multi-line `run` steps (would run under
     pwsh on windows-latest and likely fail for bash-syntax scripts)

Exit code 0 = OK, 1 = issue found.  Prints a summary table.

Usage:
    python scripts/verify_workflow.py

Dependency: PyYAML (install with `pip install pyyaml --break-system-packages`).

Note: this is the project's ONLY third-party dependency, and it is
intentionally confined to this developer-only tool — it does NOT ship
with any runtime module (core/ / translators/ / engines/ / tools/ /
pipeline/ / file_processor/ / gui*.py are strictly stdlib-only, see
CLAUDE.md 'zero third-party dependencies' principle).  PyYAML is used
only for local CI-workflow drift detection before push; production
code and CI itself parse YAML via GitHub Actions' built-in runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "[verify-workflow] ERROR: PyYAML not installed.  Install with:\n"
        "    pip install pyyaml --break-system-packages",
        file=sys.stderr,
    )
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"

# Expected matrix as of round 44 (expand as needed for future rounds).
EXPECTED_OS = {"ubuntu-latest", "windows-latest"}
EXPECTED_PY_VERSIONS = {"3.9", "3.12", "3.13"}


def main() -> int:
    if not WORKFLOW_PATH.is_file():
        print(f"[verify-workflow] ERROR: {WORKFLOW_PATH} not found", file=sys.stderr)
        return 1

    try:
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"[verify-workflow] ERROR: YAML syntax error: {e}", file=sys.stderr)
        return 1

    issues: list[str] = []

    try:
        matrix = doc["jobs"]["test"]["strategy"]["matrix"]
        actual_os = set(matrix["os"])
        actual_py = set(matrix["python-version"])
    except (KeyError, TypeError) as e:
        issues.append(f"matrix structure unreadable: {e}")
        actual_os = set()
        actual_py = set()

    if actual_os != EXPECTED_OS:
        issues.append(f"matrix.os drift: expected {sorted(EXPECTED_OS)}, got {sorted(actual_os)}")
    if actual_py != EXPECTED_PY_VERSIONS:
        issues.append(
            f"matrix.python-version drift: expected {sorted(EXPECTED_PY_VERSIONS)}, "
            f"got {sorted(actual_py)}"
        )

    missing_shell: list[tuple[int, str]] = []
    try:
        steps = doc["jobs"]["test"]["steps"]
    except (KeyError, TypeError):
        steps = []
    for i, step in enumerate(steps):
        run = step.get("run", "")
        if "\n" in run and step.get("shell") != "bash":
            name = step.get("name", "(unnamed)")
            missing_shell.append((i, name))
    if missing_shell:
        for i, name in missing_shell:
            issues.append(
                f"step[{i}] '{name}' is multi-line but lacks shell: bash "
                f"(may run under pwsh on windows-latest)"
            )

    print("=" * 60)
    print("CI workflow verify --- .github/workflows/test.yml")
    print("=" * 60)
    print("YAML syntax: OK")
    print(f"Matrix OS: {sorted(actual_os)}")
    print(f"Matrix Python: {sorted(actual_py)}")
    print(f"Total steps: {len(steps)}")
    print(f"Run steps: {sum(1 for s in steps if 'run' in s)}")
    print(f"Multi-line run steps without shell:bash: {len(missing_shell)}")
    print("=" * 60)

    if issues:
        print()
        print("ISSUES FOUND:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
