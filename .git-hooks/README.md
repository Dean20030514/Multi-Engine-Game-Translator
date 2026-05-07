# Git Hooks

This directory contains the project's `pre-commit` hook. It runs four fast sanity checks before letting a commit proceed.

## What it checks

1. **`py_compile` smoke** — every staged `.py` file is byte-compiled to catch syntax errors.

2. **File-size guard** — any `.py` outside `.git` / `_archive` / `__pycache__` / `output` exceeding **800 lines** blocks the commit. Any such file should be split into smaller modules.

3. **Meta-runner tests** — `python tests/test_all.py` (~7s) runs **every** `tests/test_*.py` file via subprocess (r64 S1 rewrite, ~35 enabled files; `test_all.py` and `test_single.py` excluded — see `_NON_TEST_FILES`). Per-file count parsed from each module's tail banner (r67 H1 fixed regex to accept hyphens, digits, and Chinese banner formats). `returncode == 0` is the authoritative pass signal; the count is informational. Total reported tests ≈ `tests_total` in `HANDOFF.md` `VERIFIED-CLAIMS` block.

4. **`scripts/verify_docs_claims.py --fast`** — re-derives `test_files` and `ci_steps` from the source tree and compares them against the fenced `VERIFIED-CLAIMS` block in `HANDOFF.md`. Any drift fails the commit.

The expensive `tests_total` / `assertion_points` re-derivation lives behind `--full` and runs in CI only — a full sweep takes ~30-60s and isn't appropriate for every local commit.

The full independent-suite sweep (`python tests/test_engines.py` / `test_ui_whitelist.py` / etc.) is also CI-only. Local commit wall-time stays around 7-12 seconds.

## Documentation drift contract

**Never claim numbers** (test count / file count / CI step / line count / assertion count) in `HANDOFF.md` / `CHANGELOG.md` / `CLAUDE.md` / `.cursorrules` / `_archive/EVOLUTION.md` / `README.md` without first running `grep` / `wc` / `find` / `python scripts/verify_docs_claims.py` to ground-truth.

`HANDOFF.md`'s fenced `<!-- VERIFIED-CLAIMS-START -->...<!-- END -->` block is the **single declaration site**. Every other doc may reference those numbers in prose but MUST NOT re-declare them. When end-of-round docs sync runs, only the fenced block changes; the surrounding prose stays generic ("see `VERIFIED-CLAIMS`").

## Install

```bash
scripts/install_hooks.sh
# or equivalently:
git config core.hooksPath .git-hooks
```

## Bypass

For emergencies (e.g., a hotfix where tests need to land in a separate commit), pass `--no-verify` to `git commit`. Document the reason in the commit body.

## Uninstall

```bash
git config --unset core.hooksPath
```
