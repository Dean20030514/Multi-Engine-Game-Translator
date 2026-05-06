#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sandbox subprocess response-line oversize cap tests — split from
``tests/test_custom_engine.py`` in round 48 Step 5 to bring both
files below the CLAUDE.md 800-line soft limit.  test_custom_engine.py
grew to 1020 lines via 8 accumulated sandbox response cap tests
across r43 (initial cap) / r44 (CHARS not BYTES rename) / r46 (diverse
scripts + exact boundary) / r47 (2-byte Latin + newline-terminated
multibyte) / r48 (newline-cap exact boundary) — caught by user
feedback at r48 end ("multiple files exceed 800; why didn't you alert
me?"), revealing the same multi-round drift that affected
test_engines.py.  See r48 Step 5 lessons in
_archive/CHANGELOG_RECENT_r50.md (Round 48 audit-tail section).

Covers all ``_SubprocessPluginClient._read_response_line`` size cap
tests for the ``_MAX_PLUGIN_RESPONSE_CHARS`` boundary (50 MB chars
cap added r43, renamed from BYTES r44, exercised at boundary edges
with diverse multibyte scripts r46-r48).

NOTE: 8 sandbox response cap tests live here.  Plugin loading +
APIConfig + sandbox basic (roundtrip / request_id / exception /
path traversal / missing module / timeout / stderr cap / close
idempotent) tests stay in ``tests/test_custom_engine.py``.

Tests are byte-identical to their pre-split forms.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_sandbox_rejects_oversize_response_line():
    """Round 43 audit-tail: ``_SubprocessPluginClient._read_response_line``
    enforces a 50 MB cap per response line to prevent an adversarial or
    malfunctioning plugin from OOMing the host with an unbounded single
    line of stdout.  Pairs with the r30 stderr 10 KB cap to bound every
    channel the host reads from.

    Uses a stubbed ``_proc`` with a fake ``stdout.readline`` so the test
    does not need to spin up a real subprocess nor actually allocate 50
    MB — ``_MAX_PLUGIN_RESPONSE_BYTES`` is temporarily patched to a tiny
    value (1 KB) and ``readline(1024)`` returns exactly 1024 bytes
    without a newline to trip the oversize detection.
    """
    from unittest import mock

    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    # Build a bare instance; __init__ would try to Popen a subprocess.
    client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
    client._timeout = 5.0

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            # Simulate a plugin that emits exactly ``size`` bytes with
            # no newline — the cap's worst case.
            if size > 0:
                return self._payload[:size]
            return self._payload

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    # Patch the cap to 1 KB so the test only needs 1 KB of payload.
    # Round 44: canonical name is ``_MAX_PLUGIN_RESPONSE_CHARS``;
    # the old ``_MAX_PLUGIN_RESPONSE_BYTES`` alias still exists but
    # only ``_CHARS`` is read by ``_read_response_line``.
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        client._proc = _FakeProc("X" * 2048)  # more than the cap, no newline
        raised = False
        try:
            client._read_response_line(req_id=42)
        except RuntimeError as e:
            msg = str(e)
            raised = (
                "oversized" in msg.lower() or "exceeded" in msg.lower() or "bytes" in msg.lower()
            )
        assert raised, (
            "plugin response > cap bytes without newline must raise "
            "a RuntimeError; no RuntimeError observed"
        )
    print("[OK] test_sandbox_rejects_oversize_response_line")


def test_sandbox_oversize_response_line_char_semantics_multibyte():
    """Round 44 audit-tail: ``_MAX_PLUGIN_RESPONSE_CHARS`` counts chars,
    not bytes (Popen text=True + readline(N) → N chars).  This test
    feeds a multibyte-dominant payload to prove the cap triggers at the
    same char count regardless of per-char byte width — a CJK response
    and an ASCII response both cap at the same number of characters.

    Documents the r43 audit-tail correction: r43 commit introduced the
    cap as ``_MAX_PLUGIN_RESPONSE_BYTES`` (misleading), r44 renamed to
    ``_MAX_PLUGIN_RESPONSE_CHARS`` and kept the old name as a deprecated
    alias.  The original r43 test exercises the cap with ASCII payload;
    this test covers the multibyte case to close the audit gap.
    """
    from unittest import mock

    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
    client._timeout = 5.0

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            # Text-mode readline counts CHARS, not bytes.  Return exactly
            # ``size`` chars of the payload so the caller sees the cap.
            if size > 0:
                return self._payload[:size]
            return self._payload

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    # Patch the cap to 1024 chars so the test only needs 1024-2048 chars
    # of payload, not 50 MB.  Use CJK chars to prove char-semantics:
    # each "你" is 3 bytes in UTF-8, so 2048 chars = 6144 bytes — but
    # the cap still triggers at 1024 **chars**, not bytes.
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        client._proc = _FakeProc("你" * 2048)  # 2048 chars, 6144 bytes
        raised = False
        msg = ""
        try:
            client._read_response_line(req_id=99)
        except RuntimeError as e:
            msg = str(e)
            raised = "chars" in msg.lower() or "exceeded" in msg.lower()
        assert raised, (
            f"multibyte (CJK) payload > cap chars without newline must "
            f"raise RuntimeError mentioning 'chars' or 'exceeded'; "
            f"got msg={msg!r}"
        )

    # Symmetric: same char count, same trigger regardless of byte width.
    # Patch cap to 1024 chars again; test with ASCII.  Same cap fires at
    # same char count.  (r43's original test covered this already, but
    # re-exercising here documents the byte-agnostic contract.)
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        client._proc = _FakeProc("X" * 2048)  # 2048 chars, 2048 bytes
        raised_ascii = False
        try:
            client._read_response_line(req_id=100)
        except RuntimeError:
            raised_ascii = True
        assert raised_ascii, "ASCII payload > cap chars without newline must also raise"
    print("[OK] test_sandbox_oversize_response_line_char_semantics_multibyte")


def test_sandbox_oversize_response_line_diverse_scripts():
    """Round 46 Step 4 (G3): extend the r44 multibyte cap test from
    Chinese-only ('你' × 2048) coverage to three additional UTF-8
    script families with different byte widths:

      - Japanese hiragana 'あ' (U+3042, 3 bytes UTF-8)
      - Korean hangul     '한' (U+D55C, 3 bytes UTF-8)
      - Emoji             '🎮' (U+1F3AE, 4 bytes UTF-8, beyond BMP)

    All three must trigger the cap at the same char count (1024) as
    ASCII / CJK, regardless of byte width.  This proves the
    char-not-byte contract holds across Asian scripts that rendering
    pipelines occasionally treat as 2-byte (UCS-2 era) and across the
    4-byte BMP-extension range where a few historical readers truncate
    surrogates.  Closes the round 45 audit's optional MEDIUM gap.
    """
    from unittest import mock

    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            # Text-mode readline counts CHARS, not bytes.  Return
            # exactly ``size`` chars of the payload so the caller sees
            # the cap regardless of per-char byte width.
            if size > 0:
                return self._payload[:size]
            return self._payload

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    test_cases = [
        ("あ", "Japanese hiragana 'あ' (3 bytes UTF-8)"),
        ("한", "Korean hangul '한' (3 bytes UTF-8)"),
        ("\U0001f3ae", "Emoji '🎮' U+1F3AE (4 bytes UTF-8)"),
    ]

    for char, label in test_cases:
        # Fresh client per case so the cap-trip state from one case
        # does not leak into the next.
        client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
        client._timeout = 5.0

        # Patch the cap to 1024 chars; payload is 2048 chars (well
        # over the cap).  Byte size ranges from 6 KB (3-byte chars) to
        # 8 KB (4-byte chars), but the cap fires at the char count.
        with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
            client._proc = _FakeProc(char * 2048)
            raised = False
            msg = ""
            try:
                client._read_response_line(req_id=200)
            except RuntimeError as e:
                msg = str(e)
                raised = "chars" in msg.lower() or "exceeded" in msg.lower()
            assert raised, (
                f"{label}: 2048 chars (> 1024 cap) without newline must "
                f"raise RuntimeError mentioning 'chars' or 'exceeded'; "
                f"got msg={msg!r}"
            )
    print("[OK] test_sandbox_oversize_response_line_diverse_scripts")


def test_sandbox_oversize_response_line_exact_cap_boundary():
    """Round 46 Step 5 audit-fix (G3 coverage MEDIUM): cover the exact
    cap boundary case that the r43 / r44 / round 46 tests miss.

    The cap check in ``core/api_plugin.py::_read_response_line`` uses
    ``len(line) >= _MAX_PLUGIN_RESPONSE_CHARS`` (line 347-348), so a
    response line of EXACTLY ``cap`` chars without a newline must
    trigger the RuntimeError — the >= operator means equality is the
    smallest payload that trips the cap.  Earlier tests use 2048 chars
    (well over a 1024 cap), proving "way over caps" but not the
    boundary itself.

    A regression here would mean the operator changed from >= to >,
    silently allowing a perfectly cap-sized truncated line to be
    accepted as a valid response, which would defeat the whole point
    of the cap (the malformed-truncated detection).

    Round 45 audit-tail flagged this as a coverage gap; closed here.
    """
    from unittest import mock

    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            if size > 0:
                return self._payload[:size]
            return self._payload

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    # Boundary case: payload of EXACTLY 1024 chars with no newline.
    # readline(1024) returns 1024 chars; len(line) == cap → >= cap
    # branch fires → must raise.
    client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
    client._timeout = 5.0
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        client._proc = _FakeProc("X" * 1024)  # exactly cap chars, no \n
        raised = False
        msg = ""
        try:
            client._read_response_line(req_id=300)
        except RuntimeError as e:
            msg = str(e)
            raised = "chars" in msg.lower() or "exceeded" in msg.lower()
        assert raised, (
            f"exact-cap (1024 chars, no newline) must trigger RuntimeError "
            f"because the implementation uses >= not >; got msg={msg!r}"
        )

    # Symmetric negative case: payload of cap-1 chars with no newline
    # must NOT trigger the cap check (len(line) < cap).  It will fail
    # later for "no newline → EOF" reasons but NOT the cap raise — the
    # caller's downstream parsing handles that.  This is intentionally
    # a documentation test: prove the >= branch only fires at >= cap.
    client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
    client._timeout = 5.0
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        # cap-1 chars with explicit newline: this is a valid line
        # exactly at the cap-1 length, with newline, so cap check is
        # NOT triggered (the and-clause has not line.endswith('\n')).
        client._proc = _FakeProc("Y" * 1023 + "\n")
        cap_raised = False
        try:
            client._read_response_line(req_id=301)
        except RuntimeError as e:
            # Only treat it as a cap-raise if the message mentions cap.
            cap_raised = "chars" in str(e).lower() or "exceeded" in str(e).lower()
        # Other errors (JSON-parse / req_id mismatch downstream) are
        # acceptable; the only thing we assert is the cap branch did
        # NOT fire here.
        assert not cap_raised, (
            "cap-1 chars with newline must not trigger the >= cap "
            "branch — newline presence + len < cap both required for "
            "the cap path to NOT fire"
        )
    print("[OK] test_sandbox_oversize_response_line_exact_cap_boundary")


def test_sandbox_oversize_response_line_2byte_latin():
    """Round 47 Step 2 (G3 LOW gap): 2-byte UTF-8 chars (Latin-1
    supplement like ñ U+00F1, ü U+00FC) must trigger the cap at the
    same char count as 3-byte CJK / hiragana / hangul and 4-byte
    emoji.  Closes the gap left by r46 Step 5 G3 (which covered 3-byte
    あ/한 + 4-byte 🎮 but not the 2-byte UTF-8 range)."""
    from unittest import mock
    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            return self._payload[:size] if size > 0 else self._payload

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    test_cases = [
        ("ñ", "Spanish ñ U+00F1 (2-byte UTF-8)"),
        ("ü", "German ü U+00FC (2-byte UTF-8)"),
    ]
    for char, label in test_cases:
        client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
        client._timeout = 5.0
        with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
            client._proc = _FakeProc(char * 2048)
            raised = False
            msg = ""
            try:
                client._read_response_line(req_id=400)
            except RuntimeError as e:
                msg = str(e)
                raised = "chars" in msg.lower() or "exceeded" in msg.lower()
            assert raised, (
                f"{label}: 2048 chars (> 1024 cap) without newline must "
                f"raise RuntimeError mentioning 'chars' or 'exceeded'; "
                f"got msg={msg!r}"
            )
    print("[OK] test_sandbox_oversize_response_line_2byte_latin")


def test_sandbox_oversize_response_line_with_newline_terminated_multibyte():
    """Round 47 Step 2 (G3 LOW gap): a multibyte payload < cap chars
    that ends with newline must NOT trigger the cap branch — the
    newline tells readline() to stop early, and the cap check requires
    BOTH ``len(line) >= cap`` AND ``not line.endswith('\\n')``.  Pins
    the well-formed-line acceptance contract for multibyte payloads
    (the cap should only fire on TRUNCATED malformed responses, not
    on well-formed multibyte ones)."""
    from unittest import mock
    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            # Real text-mode readline behaviour: returns up to ``size``
            # chars OR up-to-and-including the next \n, whichever
            # comes first.
            if size <= 0:
                return self._payload
            up_to = self._payload[:size]
            nl = up_to.find("\n")
            return up_to[: nl + 1] if nl >= 0 else up_to

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
    client._timeout = 5.0
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        # 100 CJK chars (300 UTF-8 bytes) + newline — well under 1024
        # char cap; the line is well-formed (newline-terminated).
        client._proc = _FakeProc("你" * 100 + "\n")
        cap_raised = False
        try:
            client._read_response_line(req_id=401)
        except RuntimeError as e:
            cap_raised = "chars" in str(e).lower() or "exceeded" in str(e).lower()
        # Other downstream errors (JSON-parse / req_id mismatch) are
        # acceptable; the only thing this test asserts is that the cap
        # branch did NOT fire on this well-formed multibyte line.
        assert not cap_raised, (
            "100 CJK chars + newline (well under 1024 cap, well-formed) "
            "must NOT trigger the >= cap + no-newline check"
        )
    print("[OK] test_sandbox_oversize_response_line_with_newline_terminated_multibyte")


def test_sandbox_response_line_cap_minus_1_with_newline_passes():
    """Round 48 Step 1 (G3.1 boundary expansion): 1023 chars + \\n
    (cap-1 + newline) must NOT trigger cap.  The cap branch requires
    BOTH ``len(line) >= cap`` AND ``not line.endswith('\\n')``.  At
    cap-1 chars + newline, line len is 1024 (== cap, satisfies >= cap)
    BUT ends with \\n → cap branch does not fire.  Pins the lower edge
    of newline-terminated cap behaviour.
    """
    from unittest import mock
    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            if size <= 0:
                return self._payload
            up_to = self._payload[:size]
            nl = up_to.find("\n")
            return up_to[: nl + 1] if nl >= 0 else up_to

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
    client._timeout = 5.0
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        # 1023 chars + \n; readline(1024) returns 1024 chars ending
        # with \n → len >= cap but endswith \n, cap branch skipped.
        client._proc = _FakeProc("X" * 1023 + "\n")
        cap_raised = False
        try:
            client._read_response_line(req_id=500)
        except RuntimeError as e:
            cap_raised = "chars" in str(e).lower() or "exceeded" in str(e).lower()
        assert not cap_raised, "1023 chars + newline (well-formed at cap-1) must NOT trigger cap"
    print("[OK] test_sandbox_response_line_cap_minus_1_with_newline_passes")


def test_sandbox_response_line_cap_exact_with_newline_passes():
    """Round 48 Step 1 (G3.1 boundary expansion): payload where the
    \\n sits at position cap-1 (so readline returns exactly cap chars
    ending in \\n) must NOT trigger cap.  Exercises the same cap +
    newline guard as the test above but at the upper edge — anything
    shorter still terminates correctly, anything longer would either
    have \\n earlier (reading less than cap) or no \\n (triggers cap).
    """
    from unittest import mock
    from core import api_plugin
    from core.api_plugin import _SubprocessPluginClient

    class _FakeStdout:
        def __init__(self, payload: str):
            self._payload = payload

        def readline(self, size: int = -1) -> str:
            if size <= 0:
                return self._payload
            up_to = self._payload[:size]
            nl = up_to.find("\n")
            return up_to[: nl + 1] if nl >= 0 else up_to

    class _FakeProc:
        def __init__(self, payload: str):
            self.stdout = _FakeStdout(payload)

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    client = _SubprocessPluginClient.__new__(_SubprocessPluginClient)
    client._timeout = 5.0
    with mock.patch.object(api_plugin, "_MAX_PLUGIN_RESPONSE_CHARS", 1024):
        # \n at position 1023 (0-indexed); readline(1024) returns
        # chars[0..1023] = 1023 'Y' chars + 1 '\n' = 1024 chars total
        # ending with \n; "ignored" tail is irrelevant (readline stops
        # at first \n within the size limit).
        client._proc = _FakeProc("Y" * 1023 + "\n" + "ignored")
        cap_raised = False
        try:
            client._read_response_line(req_id=501)
        except RuntimeError as e:
            cap_raised = "chars" in str(e).lower() or "exceeded" in str(e).lower()
        assert not cap_raised, (
            "1024 chars exact with \\n at pos 1023 (cap exact + newline) must NOT trigger cap"
        )
    print("[OK] test_sandbox_response_line_cap_exact_with_newline_passes")


ALL_TESTS = [
    # Round 43 audit-tail: per-response-line size cap (matches r30 stderr cap)
    test_sandbox_rejects_oversize_response_line,
    # Round 44 audit-tail: cap is CHARS not BYTES — multibyte payload
    test_sandbox_oversize_response_line_char_semantics_multibyte,
    # Round 46 Step 4 (G3): diverse scripts (ja hiragana / ko hangul / emoji)
    test_sandbox_oversize_response_line_diverse_scripts,
    # Round 46 Step 5 audit-fix (G3 boundary): exact cap-chars triggers >=
    test_sandbox_oversize_response_line_exact_cap_boundary,
    # Round 47 Step 2 (G3 LOW gap): 2-byte Latin + newline-terminated multibyte
    test_sandbox_oversize_response_line_2byte_latin,
    test_sandbox_oversize_response_line_with_newline_terminated_multibyte,
    # Round 48 Step 1 (G3.1 audit gap): newline-cap exact boundary
    test_sandbox_response_line_cap_minus_1_with_newline_passes,
    test_sandbox_response_line_cap_exact_with_newline_passes,
]


def run_all() -> int:
    """Run every sandbox response cap test in this module."""
    for t in ALL_TESTS:
        t()
    return len(ALL_TESTS)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} SANDBOX RESPONSE CAP TESTS PASSED")
    print("=" * 40)
