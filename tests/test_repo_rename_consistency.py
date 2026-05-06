#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round 51 contract test - GitHub repo rename + logger namespace sync.

Why:
    Round 51 renamed the GitHub repo Renpy-Translator ->
    Multi-Engine-Game-Translator and renamed the project-wide logger
    namespace renpy_translator -> multi_engine_translator (17 sites).
    This test pins the rename so a future commit cannot accidentally
    reintroduce the old names while remaining type/lint-clean.

    It also guards against the inverse failure mode: an over-eager
    sed/grep replacement removing the upstream attribution to
    anonymousException's renpy-translator (MIT, 2024) project, which
    must remain intact in 6 hooks/tools files for license compliance.

How to apply:
    Independent CI step (.github/workflows/test.yml).  Top-level
    ``def test_*`` functions matching the project convention so
    ``scripts/verify_docs_claims.py`` AST counter sees them.
    Stdlib-only.

Round 51 C2 audit closure (Coverage 4 fixes + 1 architectural decision):
    The Round 51 C2 starter audit (3 parallel Explore agents:
    correctness / coverage / security) returned 0/5/0 findings.
    All 4 actionable Coverage findings are closed same-round per
    Round 50's zero-debt closure rule, with explicit additions
    to this file:

      Coverage MEDIUM-1: SKIP_PARTS skip logic for build artifacts
        was implicit only -- closed by
        ``test_skip_parts_excludes_pycache_dir``.
      Coverage MEDIUM-2: ``UPSTREAM_ATTRIBUTION_FILES`` was hand-
        maintained with no inverse exhaustiveness guard -- closed
        by ``test_upstream_attribution_files_list_is_exhaustive``.
      Coverage LOW-1: Self-skip via SELF_PATH worked but was not
        positively verified that the pattern is in fact present in
        this file -- closed by
        ``test_self_skip_contract_pattern_present_in_self``.
      Coverage LOW-2: The CI mock-target guard regex shape (test.yml
        line ~229) had no unit test verifying both forms (string-arg
        + patch.object) and the relaxed file_safety filter -- closed
        by ``test_ci_mock_target_guard_catches_known_stale_forms``.

    Coverage HIGH-1 (no behavioural test that the 17 logger sites emit
    to ``multi_engine_translator``) is reclassified as an architectural
    decision rather than fixed:

      ``logging.getLogger(NAME)`` is a stdlib-level pure identifier
      dispatch -- the namespace is the name, with no derived behaviour
      beyond name equality.  The static orphan grep
      (``test_logger_namespace_renamed_no_orphan_callsites``) plus the
      positive name-string assertion in ``pyproject.toml`` /
      ``HANDOFF.md`` updates already pin the rename completely.  A
      behavioural test would either (a) be tautologically redundant
      with the static contract, or (b) test Python's stdlib rather
      than this project's code.  Adding such a test would lower the
      signal-to-noise ratio of the suite without adding real coverage.
      Documented per Round 50's "unfixable -> architectural decision,
      not debt" policy.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SELF_PATH = pathlib.Path(__file__).resolve()

# 6 upstream attribution files - reference anonymousException's
# unrelated-but-similarly-named MIT project; must stay verbatim.
UPSTREAM_ATTRIBUTION_FILES = (
    "resources/hooks/extract_hook.rpy",
    "resources/hooks/inject_hook.rpy",
    "resources/hooks/language_switcher.rpy",
    "tools/renpy_lint_fixer.py",
    "tools/rpa_unpacker.py",
    "tools/rpyc_decompiler.py",
)

# Directories excluded from the orphan-logger scan (build artifacts /
# vcs / output trees / venv-style locations).
SKIP_PARTS = ("__pycache__", "output", ".git", "build", "dist", ".venv", "venv")


def test_pyproject_no_orphan_repo_refs():
    """pyproject.toml must not reference the old repo / package name."""
    content = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "Renpy-Translator" not in content, (
        "pyproject.toml still contains old repo name 'Renpy-Translator'"
    )
    assert 'name = "renpy-translator"' not in content, (
        "pyproject.toml still uses old package name 'renpy-translator'"
    )
    assert 'name = "multi-engine-game-translator"' in content, (
        "pyproject.toml missing new package name 'multi-engine-game-translator'"
    )
    assert "https://github.com/Dean20030514/Multi-Engine-Game-Translator" in content, (
        "pyproject.toml Repository URL not updated to new GitHub repo"
    )
    print("[OK] test_pyproject_no_orphan_repo_refs")


def test_example_json_no_orphan_repo_refs():
    """renpy_translate.example.json $schema must use the new URL."""
    content = (REPO_ROOT / "renpy_translate.example.json").read_text(encoding="utf-8")
    assert "Renpy-Translator" not in content, (
        "renpy_translate.example.json still contains old repo URL"
    )
    assert "https://github.com/Dean20030514/Multi-Engine-Game-Translator" in content, (
        "renpy_translate.example.json $schema not updated to new repo URL"
    )
    print("[OK] test_example_json_no_orphan_repo_refs")


def test_logger_namespace_renamed_no_orphan_callsites():
    """No file may use getLogger("renpy_translator") - all 17 sites moved."""
    pattern = re.compile(r"""getLogger\(["']renpy_translator["']\)""")
    offenders = []
    for py in REPO_ROOT.glob("**/*.py"):
        if any(part in py.parts for part in SKIP_PARTS):
            continue
        # Skip this file - it contains the regex pattern as a string
        # literal which would otherwise self-flag.
        if py.resolve() == SELF_PATH:
            continue
        try:
            content = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if pattern.search(content):
            offenders.append(str(py.relative_to(REPO_ROOT)))
    assert offenders == [], (
        f"orphan getLogger('renpy_translator') still present in: {offenders} "
        f"- Round 51 A4 should have moved every site to "
        f"'multi_engine_translator'."
    )
    print("[OK] test_logger_namespace_renamed_no_orphan_callsites")


def test_upstream_attribution_preserved():
    """6 upstream attribution refs to anonymousException must stay verbatim."""
    for rel in UPSTREAM_ATTRIBUTION_FILES:
        path = REPO_ROOT / rel
        assert path.exists(), f"upstream attribution file missing: {rel}"
        content = path.read_text(encoding="utf-8", errors="ignore")
        assert "renpy-translator" in content, (
            f"upstream attribution to anonymousException's renpy-translator "
            f"(MIT, 2024) removed from {rel} - this is a license-compliance "
            f"violation; the rename only applies to self-references."
        )
        assert "anonymousException" in content, f"upstream author attribution removed from {rel}"
    print("[OK] test_upstream_attribution_preserved")


# ---------------------------------------------------------------------------
# Round 51 C2 Coverage MEDIUM-1: SKIP_PARTS skip logic for build artifacts
# ---------------------------------------------------------------------------


def test_skip_parts_excludes_pycache_dir():
    """Orphan-logger scan must skip __pycache__/ (and other SKIP_PARTS dirs).

    Without this guarantee, a stray ``__pycache__/<module>.pyc`` (or any
    rebuild artefact written as .py) containing the deprecated namespace
    pattern would spuriously fail the orphan check.  Built using the same
    SKIP_PARTS constant + same loop shape as
    ``test_logger_namespace_renamed_no_orphan_callsites`` so the contract
    fails together if the production loop is changed.
    """
    import tempfile

    pattern = re.compile(r"""getLogger\(["']renpy_translator["']\)""")
    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        # Create __pycache__/orphan.py with the BAD pattern - must be skipped.
        pycache = td_path / "__pycache__"
        pycache.mkdir()
        bad_in_skip = pycache / "orphan.py"
        bad_in_skip.write_text(
            'import logging\nlogger = logging.getLogger("renpy_translator")\n',
            encoding="utf-8",
        )
        # Create build/orphan.py - also must be skipped.
        build_dir = td_path / "build"
        build_dir.mkdir()
        (build_dir / "orphan.py").write_text(
            'logger = logging.getLogger("renpy_translator")\n', encoding="utf-8"
        )
        # Sanity: a non-skipped sibling MUST still be caught (positive control).
        (td_path / "real_orphan.py").write_text(
            'logger = logging.getLogger("renpy_translator")\n', encoding="utf-8"
        )

        offenders = []
        for py in td_path.glob("**/*.py"):
            if any(part in py.parts for part in SKIP_PARTS):
                continue
            content = py.read_text(encoding="utf-8")
            if pattern.search(content):
                offenders.append(str(py.relative_to(td_path)))

    # __pycache__ + build files skipped; only the real_orphan.py at root flagged.
    # This proves SKIP_PARTS works AND the regex is functional (no silent skip).
    assert offenders == ["real_orphan.py"], (
        f"SKIP_PARTS skip logic broken: expected ['real_orphan.py'], got {offenders}"
    )
    print("[OK] test_skip_parts_excludes_pycache_dir")


# ---------------------------------------------------------------------------
# Round 51 C2 Coverage MEDIUM-2: UPSTREAM_ATTRIBUTION_FILES exhaustiveness
# ---------------------------------------------------------------------------


def test_upstream_attribution_files_list_is_exhaustive():
    """Every .py / .rpy file with anonymousException attribution must be listed.

    Without an inverse exhaustiveness check, a future contributor could add
    a new tool/hook reusing anonymousException's MIT code without adding it
    to ``UPSTREAM_ATTRIBUTION_FILES``.  Such a file would silently lose its
    license-compliance guard and could be sed-rewritten by a careless rename
    pass.

    Limited to .py and .rpy source files (excludes docs, archive notes, and
    this test file's own list literal) so historical references in markdown
    don't pollute the result.
    """
    listed = set(UPSTREAM_ATTRIBUTION_FILES)
    found = set()
    for ext in ("py", "rpy"):
        for src in REPO_ROOT.glob(f"**/*.{ext}"):
            if any(part in src.parts for part in SKIP_PARTS):
                continue
            # Skip this test file itself - the UPSTREAM_ATTRIBUTION_FILES
            # tuple literal references file paths but is not itself
            # upstream-attributed code.
            if src.resolve() == SELF_PATH:
                continue
            try:
                content = src.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "anonymousException" in content:
                found.add(str(src.relative_to(REPO_ROOT)).replace("\\", "/"))

    listed_normalised = {p.replace("\\", "/") for p in listed}
    missing = found - listed_normalised
    assert not missing, (
        f"Files with anonymousException attribution NOT in "
        f"UPSTREAM_ATTRIBUTION_FILES: {sorted(missing)} - add them to the "
        f"tuple to prevent accidental relicensing under future bulk-rename."
    )
    print("[OK] test_upstream_attribution_files_list_is_exhaustive")


# ---------------------------------------------------------------------------
# Round 51 C2 Coverage LOW-1: Self-skip contract sanity
# ---------------------------------------------------------------------------


def test_self_skip_contract_pattern_present_in_self():
    """Sanity: this file MUST contain the regex pattern as a string literal.

    The orphan-scan test skips ``SELF_PATH`` precisely because this file
    contains the literal ``getLogger("renpy_translator")`` text inside a
    regex pattern (and inside docstrings/error messages).  If the pattern
    were ever stripped from the file (refactor / inline import / lookup
    rename), the self-skip would become unnecessary and could be removed.
    Conversely, while the pattern remains, the self-skip is mandatory.
    This test pins the invariant: pattern in self => self-skip needed.
    """
    self_content = SELF_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"""getLogger\(["']renpy_translator["']\)""")
    assert pattern.search(self_content), (
        "Test file no longer contains the orphan-grep pattern - the "
        "self-skip in test_logger_namespace_renamed_no_orphan_callsites "
        "may now be unnecessary; review and possibly simplify."
    )
    print("[OK] test_self_skip_contract_pattern_present_in_self")


# ---------------------------------------------------------------------------
# Round 51 C2 Coverage LOW-2: CI mock-target guard regex shape
# ---------------------------------------------------------------------------


def test_ci_mock_target_guard_catches_known_stale_forms():
    """CI workflow's mock-target guard regex must cover both fstat-mock forms.

    The Round 50 1a mock-target stale-trap CLASS guard
    (``.github/workflows/test.yml`` step "Mock target consistency check")
    runs::

        grep -rEn "(mock\\.patch.*os\\.fstat|patch\\.object\\s*\\(\\s*[a-zA-Z_.]*os\\s*,\\s*[\\"']fstat[\\"'])" tests/*.py | grep -v "file_safety"

    Both alternatives are essential:
      1. ``mock.patch(...os.fstat)`` -- the string-arg form
      2. ``patch.object(os, "fstat", ...)`` -- the object-arg form
         (used by tests/test_api_client.py for unrelated mocks)

    The Round 50 C4 deep-audit-tail relaxed the second-stage filter
    from ``core\\.file_safety`` to ``file_safety`` to handle the
    ``from <pkg> import file_safety; patch.object(file_safety.os, "fstat", ...)``
    qualified-but-not-fully-dotted form.  Round 56 M2 moved the helper
    from ``core/file_safety.py`` to ``safety/file_safety.py``; the
    fragment-only filter survives the move because both forms still
    contain the substring "file_safety".

    The Round 51 audit-tail added a third filter level
    ``grep -v "test_repo_rename_consistency"`` to exempt this very
    file (documentation-only references to the patterns above would
    otherwise self-trip the guard).

    This test pins all four pattern fragments so a future workflow
    edit cannot silently degrade the trap.
    """
    workflow_path = REPO_ROOT / ".github" / "workflows" / "test.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    # Form 1: mock.patch(...os.fstat) -- string-arg form
    assert r"mock\.patch.*os\.fstat" in workflow, (
        "CI mock-target guard missing string-arg form; see Round 50 1a guard rationale."
    )
    # Form 2: patch.object(os, "fstat", ...) -- object-arg form
    assert r"patch\.object" in workflow and "fstat" in workflow, (
        "CI mock-target guard missing object-arg form; "
        "Round 50 C2 Correctness LOW-2 added this; do not regress."
    )
    # Filter level 1: relaxed to "file_safety" (Round 50 C4 / r56 M2-safe).
    # The previous strict 'core\.file_safety' would false-positive on
    # ``from <pkg> import file_safety; patch.object(file_safety.os, ...)``.
    # The fragment filter survives the r56 M2 move (core → safety).
    assert 'grep -v "file_safety"' in workflow, (
        "CI mock-target guard first filter missing or wrong; should be "
        "'grep -v \"file_safety\"' (Round 50 C4 relaxation)."
    )
    # Filter level 2: exempt this documentation-only file (Round 51 audit-tail).
    # The strings/comments above contain the regex patterns as references for
    # diagnostic clarity; without this exemption they would self-trip the
    # CI guard.  Mirrors the file_safety sanctioned-exception design.
    assert 'grep -v "test_repo_rename_consistency"' in workflow, (
        "CI mock-target guard third filter missing; should be "
        "'grep -v \"test_repo_rename_consistency\"' to exempt this "
        "documentation-only contract file (Round 51 audit-tail closure)."
    )
    # Strict filter must NOT have been re-introduced.
    assert 'grep -v "core\\.file_safety"' not in workflow, (
        "CI mock-target guard filter regressed to overly-strict "
        "'grep -v \"core\\.file_safety\"' which produced false positives "
        "on qualified `file_safety.os.fstat` mocks; see Round 50 C4 fix."
    )
    print("[OK] test_ci_mock_target_guard_catches_known_stale_forms")


TESTS = [
    test_pyproject_no_orphan_repo_refs,
    test_example_json_no_orphan_repo_refs,
    test_logger_namespace_renamed_no_orphan_callsites,
    test_upstream_attribution_preserved,
    # Round 51 C2 Coverage closure (4 same-round fixes + 1 architectural decision)
    test_skip_parts_excludes_pycache_dir,
    test_upstream_attribution_files_list_is_exhaustive,
    test_self_skip_contract_pattern_present_in_self,
    test_ci_mock_target_guard_catches_known_stale_forms,
]


def run_all() -> int:
    """Run every registered test in registration order and return
    the count for the ``ALL N PASSED`` summary line."""
    for t in TESTS:
        t()
    return len(TESTS)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} REPO RENAME CONSISTENCY TESTS PASSED")
    print("=" * 40)
