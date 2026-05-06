#!/usr/bin/env python3
"""Tests for custom translation engine plugin system.

Round 52 BREAKING: importlib in-process loader retired; every plugin
runs in a subprocess sandbox.  Pre-r52 importlib-only tests removed:

  - test_load_example_echo / _with_py_extension / _nonexistent_raises
    / _no_interface_raises — covered by sandbox readiness probe +
    test_sandbox_rejects_missing_module
  - test_load_path_traversal_rejected — covered by
    test_sandbox_rejects_path_traversal
  - test_load_empty_name_raises — replaced by
    test_subprocess_rejects_empty_name (sandbox-side equivalent)
  - test_client_custom_single_fallback — host-side single-item
    fallback only applied to in-process modules; subprocess protocol
    is batch-only by contract
  - test_config_sandbox_plugin_default — APIConfig.sandbox_plugin
    field deleted (unconditional sandbox)

New tests for r52 BREAKING:
  - test_subprocess_rejects_empty_name — sandbox client analogue
  - test_subprocess_rejects_plugin_without_serve_block — readiness
    probe surfaces missing __main__ block as immediate __init__
    failure with migration guidance
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.api_client import (
    APIConfig,
    APIClient,
    _SubprocessPluginClient,
)


# ============================================================
# APIConfig tests
# ============================================================


def test_config_custom_provider():
    """APIConfig accepts 'custom' provider."""
    c = APIConfig(provider="custom", api_key="", custom_module="example_echo")
    assert c.provider == "custom"
    assert c.model == "custom"
    assert c.custom_module == "example_echo"
    print("[OK] test_config_custom_provider")


def test_config_custom_module_default():
    """custom_module defaults to empty string."""
    c = APIConfig(provider="xai", api_key="test")
    assert c.custom_module == ""
    print("[OK] test_config_custom_module_default")


# ============================================================
# APIClient custom engine call tests (sandbox-only as of round 52)
# ============================================================


def test_client_custom_batch():
    """APIClient with custom provider calls translate_batch via sandbox."""
    config = APIConfig(provider="custom", api_key="", custom_module="example_echo")
    client = APIClient(config)
    try:
        items = [{"line": 1, "original": "Hello"}]
        user_prompt = json.dumps(items, ensure_ascii=False)
        result = client.translate("system prompt", user_prompt)

        assert len(result) == 1
        assert result[0]["zh"] == "[ECHO] Hello"
    finally:
        client._custom_module.close()
    print("[OK] test_client_custom_batch")


def test_client_custom_batch_returns_list():
    """translate_batch returning list[dict] (not string) is serialized correctly.

    Round 52: temp module rewritten with full __main__ + _plugin_serve()
    block — pre-r52 importlib mode allowed module bodies without a
    serve loop, but subprocess sandbox requires the JSONL protocol.
    """
    engines_dir = Path(__file__).resolve().parent.parent / "custom_engines"
    list_module = engines_dir / "_test_list_return.py"
    body = (
        "import json, sys\n"
        "\n"
        "def translate_batch(system_prompt, user_prompt):\n"
        "    items = json.loads(user_prompt)\n"
        "    return [{'line': it.get('line', 0), 'original': it['original'],\n"
        "             'zh': 'OK'} for it in items]\n"
        "\n"
        "def _plugin_serve():\n"
        "    for line in sys.stdin:\n"
        "        line = line.strip()\n"
        "        if not line: continue\n"
        "        req = json.loads(line)\n"
        "        if req.get('request_id') == -1: break\n"
        "        try:\n"
        "            result = translate_batch(req.get('system_prompt', ''),\n"
        "                                     req.get('user_prompt', ''))\n"
        "            if isinstance(result, list):\n"
        "                result = json.dumps(result, ensure_ascii=False)\n"
        "            resp = {'request_id': req['request_id'],\n"
        "                    'response': result, 'error': None}\n"
        "        except Exception as e:\n"
        "            resp = {'request_id': req['request_id'],\n"
        "                    'response': None, 'error': str(e)}\n"
        "        print(json.dumps(resp, ensure_ascii=False), flush=True)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    if len(sys.argv) > 1 and sys.argv[1] == '--plugin-serve':\n"
        "        _plugin_serve()\n"
    )
    list_module.write_text(body, encoding="utf-8")
    try:
        config = APIConfig(provider="custom", api_key="", custom_module="_test_list_return")
        client = APIClient(config)
        try:
            items = [{"line": 1, "original": "Test"}]
            user_prompt = json.dumps(items, ensure_ascii=False)
            result = client.translate("sys", user_prompt)

            assert len(result) == 1
            assert result[0]["zh"] == "OK"
        finally:
            client._custom_module.close()
    finally:
        list_module.unlink(missing_ok=True)
    print("[OK] test_client_custom_batch_returns_list")


# ============================================================
# Subprocess sandbox tests (round 28 S-H-4; round 52 made unconditional)
# ============================================================

_CUSTOM_ENGINES_DIR = Path(__file__).resolve().parent.parent / "custom_engines"


def _write_plugin(name: str, body: str) -> Path:
    """Write a throwaway plugin under custom_engines/ and return its path.

    The body must include an ``if __name__ == "__main__":`` block that
    calls a ``_plugin_serve`` helper implementing the JSONL protocol —
    round 52 enforces this via the readiness probe in
    :meth:`_SubprocessPluginClient.__init__`.
    """
    p = _CUSTOM_ENGINES_DIR / f"{name}.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_sandbox_roundtrip_batch():
    """Full happy path: launch example_echo in sandbox, send a batch
    request, verify the response reaches the host unchanged."""
    config = APIConfig(
        provider="custom",
        api_key="",
        custom_module="example_echo",
    )
    client = APIClient(config)
    try:
        items = [{"line": 1, "original": "Hello"}]
        user_prompt = json.dumps(items, ensure_ascii=False)
        result = client.translate("system prompt", user_prompt)
        assert len(result) == 1
        assert result[0]["zh"] == "[ECHO] Hello", result
    finally:
        client._custom_module.close()
    print("[OK] test_sandbox_roundtrip_batch")


def test_sandbox_request_id_tracking():
    """Multiple chunks share one subprocess; every response's request_id
    must match the dispatched request (no off-by-one / no lost messages)."""
    config = APIConfig(
        provider="custom",
        api_key="",
        custom_module="example_echo",
    )
    client = APIClient(config)
    try:
        for i in range(3):
            items = [{"line": i + 1, "original": f"Text_{i}"}]
            result = client.translate("sys", json.dumps(items, ensure_ascii=False))
            assert len(result) == 1
            assert result[0]["zh"] == f"[ECHO] Text_{i}"
        # Request counter should reflect 3 dispatches.
        assert client._custom_module._request_id == 3
    finally:
        client._custom_module.close()
    print("[OK] test_sandbox_request_id_tracking")


def test_sandbox_plugin_exception_wrapped():
    """A plugin raising inside translate_batch must surface as a
    RuntimeError in the host (wrapping the ``error`` JSON field)."""
    body = (
        "import json, sys\n"
        "\n"
        "def translate_batch(system_prompt, user_prompt):\n"
        "    raise ValueError('plugin crashed on purpose')\n"
        "\n"
        "def _plugin_serve():\n"
        "    for line in sys.stdin:\n"
        "        line = line.strip()\n"
        "        if not line: continue\n"
        "        req = json.loads(line)\n"
        "        if req.get('request_id') == -1: break\n"
        "        try:\n"
        "            result = translate_batch(req.get('system_prompt',''),\n"
        "                                     req.get('user_prompt',''))\n"
        "            resp = {'request_id': req['request_id'],\n"
        "                    'response': result, 'error': None}\n"
        "        except Exception as e:\n"
        "            resp = {'request_id': req['request_id'],\n"
        "                    'response': None, 'error': str(e)}\n"
        "        print(json.dumps(resp), flush=True)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    if len(sys.argv) > 1 and sys.argv[1] == '--plugin-serve':\n"
        "        _plugin_serve()\n"
    )
    path = _write_plugin("_test_sandbox_raises", body)
    try:
        config = APIConfig(
            provider="custom",
            api_key="",
            custom_module="_test_sandbox_raises",
        )
        client = APIClient(config)
        try:
            raised = False
            try:
                client.translate("sys", json.dumps([{"line": 1, "original": "x"}]))
            except RuntimeError as e:
                raised = "plugin crashed on purpose" in str(e)
            assert raised, "host should have raised RuntimeError wrapping plugin error"
        finally:
            client._custom_module.close()
    finally:
        path.unlink(missing_ok=True)
    print("[OK] test_sandbox_plugin_exception_wrapped")


def test_sandbox_rejects_path_traversal():
    """Path separators in module name are rejected (security)."""
    for name in ["../evil", "foo/bar", "..\\evil"]:
        raised = False
        try:
            _SubprocessPluginClient(name)
        except RuntimeError as e:
            raised = "路径分隔符" in str(e)
        assert raised, f"should have rejected {name!r}"
    print("[OK] test_sandbox_rejects_path_traversal")


def test_sandbox_rejects_missing_module():
    """Missing plugin file raises RuntimeError before spawning any process."""
    raised = False
    try:
        _SubprocessPluginClient("nonexistent_sandbox_plugin_xyz")
    except RuntimeError as e:
        raised = "未找到" in str(e)
    assert raised
    print("[OK] test_sandbox_rejects_missing_module")


def test_subprocess_rejects_empty_name():
    """Round 52: sandbox client analogue of removed test_load_empty_name_raises.

    Empty module name raises RuntimeError before any subprocess launch."""
    raised = False
    try:
        _SubprocessPluginClient("")
    except RuntimeError as e:
        raised = "需要指定模块名" in str(e)
    assert raised, "empty module name must be rejected"
    print("[OK] test_subprocess_rejects_empty_name")


def test_subprocess_rejects_plugin_without_serve_block():
    """Round 52 readiness probe: a plugin file lacking the
    ``--plugin-serve`` __main__ block must fail at __init__ with
    migration guidance, not at first translate() call."""
    body = (
        "# Missing __main__ block — running this file with --plugin-serve\n"
        "# will print nothing and exit 0 immediately.\n"
        "def translate_batch(system_prompt, user_prompt):\n"
        "    return '[]'\n"
    )
    path = _write_plugin("_test_no_serve_block", body)
    try:
        raised = False
        err_msg = ""
        try:
            _SubprocessPluginClient("_test_no_serve_block")
        except RuntimeError as e:
            raised = True
            err_msg = str(e)
        assert raised, "plugin without serve block must fail at __init__"
        # Error must guide migration, not be a generic startup failure.
        assert "--plugin-serve" in err_msg, (
            f"error should mention --plugin-serve protocol; got: {err_msg!r}"
        )
        assert "round 52" in err_msg.lower() or "_plugin_serve" in err_msg, (
            f"error should reference migration guidance; got: {err_msg!r}"
        )
    finally:
        path.unlink(missing_ok=True)
    print("[OK] test_subprocess_rejects_plugin_without_serve_block")


def test_sandbox_timeout_kills_hung_plugin():
    """A plugin that never responds must be killed by the host timeout."""
    body = (
        "import sys, time\n"
        "\n"
        "def translate_batch(system_prompt, user_prompt):\n"
        "    time.sleep(30)\n"
        "    return '[]'\n"
        "\n"
        "def _plugin_serve():\n"
        "    for line in sys.stdin:\n"
        "        if not line.strip(): continue\n"
        "        time.sleep(30)  # never responds\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    if len(sys.argv) > 1 and sys.argv[1] == '--plugin-serve':\n"
        "        _plugin_serve()\n"
    )
    path = _write_plugin("_test_sandbox_hang", body)
    try:
        # Use a very small timeout so the test finishes quickly.
        config = APIConfig(
            provider="custom",
            api_key="",
            custom_module="_test_sandbox_hang",
            timeout=1.0,
        )
        client = APIClient(config)
        try:
            raised = False
            try:
                client.translate("sys", json.dumps([{"line": 1, "original": "x"}]))
            except RuntimeError as e:
                raised = "超时" in str(e)
            assert raised, "host should have raised on subprocess timeout"
            # After timeout the subprocess must be reaped / no longer alive.
            assert client._custom_module._proc.poll() is not None, (
                "subprocess should have been killed after timeout"
            )
        finally:
            client._custom_module.close()
    finally:
        path.unlink(missing_ok=True)
    print("[OK] test_sandbox_timeout_kills_hung_plugin")


def test_sandbox_stderr_read_bounded():
    """When a plugin exits prematurely, the host's diagnostic reads at most
    10 KB of stderr and includes only a ~600-char tail in the RuntimeError
    (round 30 robustness fix guarding against OOM on pathological plugin
    output).

    Round 52: the readiness probe at __init__ catches the early exit, so
    the bounded stderr read happens during construction rather than on
    first translate() call.  The 2_000-char ceiling on the error message
    is the invariant we pin — changing 3_000 here to 3_000_000 must not
    break the assertion because of the 10 KB cap.
    """
    body = (
        "import sys\n"
        "\n"
        "def translate_batch(system_prompt, user_prompt):\n"
        "    return '[]'\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    if len(sys.argv) > 1 and sys.argv[1] == '--plugin-serve':\n"
        "        sys.stderr.write('X' * 3_000)\n"
        "        sys.stderr.flush()\n"
        "        sys.exit(7)\n"
    )
    path = _write_plugin("_test_sandbox_big_stderr", body)
    try:
        raised = False
        err = ""
        try:
            _SubprocessPluginClient("_test_sandbox_big_stderr")
        except RuntimeError as e:
            raised = True
            err = str(e)
        assert raised, "host should have detected the prematurely-exited child"
        assert "exit=7" in err, f"expected exit code surfaced, got: {err!r}"
        # Total error message including Chinese prefix must be bounded;
        # the stderr payload was 3 KB but the error embeds only the last
        # 600 chars of a 10 KB-bounded read — so the message stays short
        # regardless of how much the plugin wrote.
        assert len(err) < 2_000, f"stderr tail leaked too much into error ({len(err)} chars)"
    finally:
        path.unlink(missing_ok=True)
    print("[OK] test_sandbox_stderr_read_bounded")


def test_sandbox_close_idempotent():
    """Calling close() twice on a subprocess client is a no-op the second time."""
    config = APIConfig(
        provider="custom",
        api_key="",
        custom_module="example_echo",
    )
    client = APIClient(config)
    sandbox = client._custom_module
    sandbox.close()
    # Second close should not raise.
    sandbox.close()
    # Calls after close raise.
    raised = False
    try:
        sandbox.translate_batch("s", "[]")
    except RuntimeError:
        raised = True
    assert raised, "calls after close() must raise"
    print("[OK] test_sandbox_close_idempotent")


# ============================================================
# Runner
# ============================================================

ALL_TESTS = [
    test_config_custom_provider,
    test_config_custom_module_default,
    test_client_custom_batch,
    test_client_custom_batch_returns_list,
    # Round 28 S-H-4 sandbox; round 52 BREAKING made unconditional
    test_sandbox_roundtrip_batch,
    test_sandbox_request_id_tracking,
    test_sandbox_plugin_exception_wrapped,
    test_sandbox_rejects_path_traversal,
    test_sandbox_rejects_missing_module,
    test_subprocess_rejects_empty_name,
    test_subprocess_rejects_plugin_without_serve_block,
    test_sandbox_timeout_kills_hung_plugin,
    test_sandbox_stderr_read_bounded,
    test_sandbox_close_idempotent,
    # Round 48 Step 5: 8 sandbox response-line oversize cap tests
    # moved to tests/test_sandbox_response_cap.py to bring this file
    # back under the CLAUDE.md 800-line soft limit.
]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for t in ALL_TESTS:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    total = passed + failed
    if failed:
        print(f"\n{passed}/{total} PASSED, {failed} FAILED")
        sys.exit(1)
    else:
        print(f"\nALL {total} CUSTOM ENGINE TESTS PASSED")
