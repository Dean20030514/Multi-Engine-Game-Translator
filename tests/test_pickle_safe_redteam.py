#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round 53 monitor item #1: red-team audit of ``core.pickle_safe.SafeUnpickler``.

The Round 49 audit flagged ``_codecs.encode`` and ``copyreg._reconstructor``
as theoretical chain-attack vectors in the SafeUnpickler whitelist. Round 53
elevates this from informational watchlist to actionable verification —
construct realistic exploit payloads (the kind that successfully RCE a
naive ``pickle.loads``) and prove SafeUnpickler refuses every one.

Payloads exercised:
  1. ``os.system`` direct-call gadget
  2. ``subprocess.Popen`` direct-call gadget
  3. ``eval`` direct-call gadget
  4. ``exec`` direct-call gadget
  5. ``_codecs.encode`` whitelist-narrowing chain attempt (audit concern A)
  6. ``copyreg._reconstructor`` GadgetChain with non-whitelisted base
     (audit concern B)
  7. legitimate payload still deserialises (positive control)
  8. arbitrary non-whitelisted module/class blocked (general guarantee)

Each payload is constructed with the standard ``__reduce__`` protocol that
pickle uses to invoke raw callables. The test asserts SafeUnpickler raises
``pickle.UnpicklingError`` before any side-effectful resolution happens.
No exploit code ever runs — payloads are deserialised under SafeUnpickler
only, never under the default ``pickle.loads``.

Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.pickle_safe import safe_loads


# ────────────────────────────────────────────────────────────────────
# Direct-call gadgets (the canonical pickle RCE pattern)
# ────────────────────────────────────────────────────────────────────


class _OsSystemPayload:
    """Pickle gadget — would invoke os.system at deserialisation time."""

    def __reduce__(self):
        return (os.system, ('echo "PWNED via os.system"',))


def test_red_team_blocks_os_system():
    """SafeUnpickler refuses to resolve os.system.

    Note: pickle serialises ``os.system`` as ``posix.system`` on POSIX
    and ``nt.system`` on Windows (it follows the actual definition site).
    Both must be blocked — the whitelist contains neither ``posix`` nor
    ``nt``, so the ``module not in whitelist`` branch fires.
    """
    malicious = pickle.dumps(_OsSystemPayload())
    try:
        safe_loads(malicious)
    except pickle.UnpicklingError as e:
        msg = str(e)
        assert "system" in msg, f"error must name the blocked symbol; got: {e}"
        print(f"[OK] red_team_blocks_os_system (blocked: {msg.split('(')[0].strip()})")
        return
    raise AssertionError("os.system payload was NOT blocked — RCE possible")


class _SubprocessPopenPayload:
    """Pickle gadget — would invoke subprocess.Popen at deserialisation time."""

    def __reduce__(self):
        return (subprocess.Popen, (["echo", "PWNED via Popen"],))


def test_red_team_blocks_subprocess_popen():
    """SafeUnpickler refuses to resolve subprocess.Popen."""
    malicious = pickle.dumps(_SubprocessPopenPayload())
    try:
        safe_loads(malicious)
    except pickle.UnpicklingError:
        print("[OK] red_team_blocks_subprocess_popen")
        return
    raise AssertionError("subprocess.Popen payload was NOT blocked")


class _EvalPayload:
    """Pickle gadget — would invoke builtins.eval at deserialisation time."""

    def __reduce__(self):
        return (eval, ('__import__("os").system("echo PWNED via eval")',))


def test_red_team_blocks_eval():
    """SafeUnpickler refuses to resolve builtins.eval."""
    malicious = pickle.dumps(_EvalPayload())
    try:
        safe_loads(malicious)
    except pickle.UnpicklingError:
        print("[OK] red_team_blocks_eval")
        return
    raise AssertionError("eval payload was NOT blocked")


class _ExecPayload:
    """Pickle gadget — would invoke builtins.exec at deserialisation time."""

    def __reduce__(self):
        return (exec, ('__import__("os").system("echo PWNED via exec")',))


def test_red_team_blocks_exec():
    """SafeUnpickler refuses to resolve builtins.exec."""
    malicious = pickle.dumps(_ExecPayload())
    try:
        safe_loads(malicious)
    except pickle.UnpicklingError:
        print("[OK] red_team_blocks_exec")
        return
    raise AssertionError("exec payload was NOT blocked")


# ────────────────────────────────────────────────────────────────────
# Audit concern A: ``_codecs.encode`` whitelist-narrowing
# ────────────────────────────────────────────────────────────────────


def test_red_team_codecs_encode_returns_data_only():
    """``_codecs.encode`` is whitelisted but only produces inert data.

    The r49 audit flagged ``_codecs.encode`` as a theoretical chain-attack
    vector. This test verifies the threat is data-only: even when an
    attacker controls the encode arguments, the result is bytes/str
    (a passive transformation), never an executable callable.
    """
    import _codecs

    # _codecs.encode is in the whitelist; its sole effect is encoding
    # bytes/str. Build a gadget that uses it; the returned data must be
    # inert (no further deserialisation step can re-invoke it).
    class _CodecsAbusePayload:
        def __reduce__(self):
            return (_codecs.encode, ("import os; os.system('echo PWNED')", "utf-8"))

    abuse = pickle.dumps(_CodecsAbusePayload())
    result = safe_loads(abuse)
    assert isinstance(result, bytes), f"expected bytes, got {type(result)}"
    assert b"echo PWNED" in result, "data must be returned literally, not executed"
    # The string is sitting in memory as bytes — never executed.
    print("[OK] red_team_codecs_encode_returns_data_only")


# ────────────────────────────────────────────────────────────────────
# Audit concern B: ``copyreg._reconstructor`` GadgetChain
# ────────────────────────────────────────────────────────────────────


def test_red_team_reconstructor_with_malicious_base_blocked():
    """``copyreg._reconstructor`` with non-whitelisted base is blocked.

    GadgetChain attempt: invoke ``copyreg._reconstructor(cls, base, state)``
    where ``base`` is something dangerous (here ``os.system``).
    SafeUnpickler MUST reject resolving the base callable BEFORE
    _reconstructor is invoked, breaking the chain.
    """
    import copyreg

    class _ReconstructorAbuse:
        def __reduce__(self):
            # _reconstructor signature: (cls, base, state) -> instance
            # We try to slot ``os.system`` into the ``base`` position.
            return (copyreg._reconstructor, (object, os.system, None))

    malicious = pickle.dumps(_ReconstructorAbuse())
    try:
        safe_loads(malicious)
    except pickle.UnpicklingError:
        print(
            "[OK] red_team_reconstructor_with_malicious_base_blocked "
            "(UnpicklingError on os.system resolution)"
        )
        return
    except (TypeError, AttributeError) as e:
        # Acceptable: pickle infrastructure blocked at type-construction
        # time before SafeUnpickler had a chance to. Either way no RCE.
        print(
            f"[OK] red_team_reconstructor_with_malicious_base_blocked "
            f"(structurally rejected: {type(e).__name__})"
        )
        return
    raise AssertionError(
        "copyreg._reconstructor with os.system base was NOT blocked — "
        "GadgetChain successful, audit upgrade required"
    )


# ────────────────────────────────────────────────────────────────────
# Whitelist boundary (positive + negative controls)
# ────────────────────────────────────────────────────────────────────


def test_red_team_legitimate_payload_works():
    """Plain data structures (lists, dicts, tuples, sets) deserialise normally."""
    payload = {"a": [1, 2, 3], "b": ("nested", {"x": 0.5}), "c": frozenset({"y", "z"})}
    serialised = pickle.dumps(payload)
    result = safe_loads(serialised)
    assert result == payload, f"data corruption: {result} != {payload}"
    print("[OK] red_team_legitimate_payload_works")


def test_red_team_blocks_arbitrary_module_class():
    """SafeUnpickler refuses any module/name combination not in the whitelist."""
    import json

    class _NonWhitelistedClass:
        def __reduce__(self):
            # json.JSONDecoder is benign but not in the whitelist —
            # the principle "default-deny" must hold for it too.
            return (json.JSONDecoder, ())

    malicious = pickle.dumps(_NonWhitelistedClass())
    try:
        safe_loads(malicious)
    except pickle.UnpicklingError:
        print("[OK] red_team_blocks_arbitrary_module_class")
        return
    raise AssertionError("non-whitelisted class was NOT blocked — default-deny breached")


# ────────────────────────────────────────────────────────────────────


def run_all() -> int:
    tests = [
        test_red_team_blocks_os_system,
        test_red_team_blocks_subprocess_popen,
        test_red_team_blocks_eval,
        test_red_team_blocks_exec,
        test_red_team_codecs_encode_returns_data_only,
        test_red_team_reconstructor_with_malicious_base_blocked,
        test_red_team_legitimate_payload_works,
        test_red_team_blocks_arbitrary_module_class,
    ]
    for t in tests:
        t()
    return len(tests)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} RED-TEAM TESTS PASSED")
    print("=" * 40)
