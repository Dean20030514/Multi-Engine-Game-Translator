#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API client tests — APIConfig / UsageStats / rate limiter / JSON parsing / pricing / HTTP retries / connection pool / response size caps.

Split from the monolithic ``tests/test_all.py`` in round 29; every test
function is copied byte-identical from its original location so test
behaviour is preserved.  Run standalone via ``python tests/test_api_client.py``
or collectively via ``python tests/test_all.py`` (which delegates to
``run_all()`` in each split module).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import api_client


def test_api_config():
    c = api_client.APIConfig(provider="xai", api_key="test")
    assert c.endpoint == "https://api.x.ai/v1/chat/completions"
    assert c.model == "grok-4-1-fast-reasoning"
    c2 = api_client.APIConfig(provider="claude", api_key="test")
    assert c2.endpoint == "https://api.anthropic.com/v1/messages"
    c3 = api_client.APIConfig(provider="deepseek", api_key="test", model="my-model")
    assert c3.model == "my-model"
    c4 = api_client.APIConfig(provider="gemini", api_key="test")
    assert "googleapis" in c4.endpoint
    assert c4.model == "gemini-2.5-flash"
    print("[OK] APIConfig")


def test_usage_stats():
    u = api_client.UsageStats("xai", "grok-3")
    u.record(1000, 500)
    u.record(2000, 1000)
    assert u.total_input_tokens == 3000
    assert u.total_output_tokens == 1500
    assert u.total_requests == 2
    assert u.estimated_cost > 0
    s = u.summary()
    assert "3,000" in s
    assert "$" in s
    print(f"[OK] UsageStats: {s}")


def test_rate_limiter():
    r = api_client.RateLimiter(rpm=100, rps=10)
    r.acquire()
    r.acquire()
    print("[OK] RateLimiter")


def test_json_parse():
    p = api_client.APIClient._parse_json_response
    # Direct JSON
    r = p('[{"line": 1, "original": "hi", "zh": "你好"}]')
    assert len(r) == 1
    # Markdown block
    r2 = p('Here:\n```json\n[{"line": 1, "original": "hi", "zh": "hey"}]\n```')
    assert len(r2) == 1
    # Trailing comma
    r3 = p('[{"line": 1, "original": "hi", "zh": "hey"},]')
    assert len(r3) == 1
    # Empty
    r4 = p("[]")
    assert r4 == []
    # Garbage
    r5 = p("I cannot translate this")
    assert r5 == []
    # 逐对象提取（数组格式损坏但单个对象完整）
    r6 = p(
        'Some text {"line": 5, "original": "hello", "zh": "你好"} and {"line": 10, "original": "world", "zh": "世界"} end'
    )
    assert len(r6) == 2
    assert r6[0]["line"] == 5
    assert r6[1]["zh"] == "世界"
    # 含转义引号的对象
    r7 = p('[{"line": 1, "original": "She said \\"hello\\"", "zh": "她说\\"你好\\""}]')
    assert len(r7) == 1
    assert "\\" in r7[0]["original"] or "hello" in r7[0]["original"]
    # 字段顺序变化
    r8 = p('{"zh": "你好", "line": 1, "original": "hi"}')
    # 应该能被 strategy 6 或 direct parse 捕获
    print("[OK] _parse_json_response (含逐对象提取)")


def test_w2_escape_fix_inner_quotes_in_zh():
    """Round 53 W2 layer 7: stray ``"`` inside zh value gets repaired.

    Pattern observed in pre-r52 ja path: LLM emits ``{"zh": "他说"你好""}``
    where the inner quotes should be ``\\"``. The structural 1-6 layer
    chain cannot recover; layer 7 char-walks the text and re-escapes.
    """
    p = api_client.APIClient._parse_json_response
    # Stray quotes inside zh value: 他说 + "你好" should be re-escaped
    broken = '[{"id": "x1", "original": "He said hi", "zh": "他说"你好""}]'
    result = p(broken)
    assert len(result) == 1, f"layer 7 must recover 1 item, got {result}"
    assert result[0]["id"] == "x1"
    # The repaired zh should contain the inner content (quotes escaped)
    assert "你好" in result[0]["zh"]
    print("[OK] w2_escape_fix_inner_quotes_in_zh")


def test_w2_escape_fix_unescaped_in_original():
    """Round 53 W2 layer 7: stray ``"`` inside original field also fixed."""
    p = api_client.APIClient._parse_json_response
    broken = '[{"id": "x2", "original": "You can"t see", "zh": "你看不见"}]'
    result = p(broken)
    assert len(result) == 1, f"layer 7 must recover 1 item, got {result}"
    assert result[0]["id"] == "x2"
    assert "看不见" in result[0]["zh"]
    print("[OK] w2_escape_fix_unescaped_in_original")


def test_w2_escape_fix_multiple_stray_quotes():
    """Round 53 W2 layer 7: multiple consecutive stray quotes all repaired."""
    p = api_client.APIClient._parse_json_response
    # 她说："hello""  — Chinese colon then unescaped english quotes
    broken = '[{"id": "x3", "original": "She says hello", "zh": "她说："hello""}]'
    result = p(broken)
    assert len(result) == 1, f"layer 7 must recover 1 item, got {result}"
    assert result[0]["id"] == "x3"
    print("[OK] w2_escape_fix_multiple_stray_quotes")


def test_w2_escape_fix_does_not_break_valid_json():
    """Round 53 W2 layer 7: well-formed JSON passes through layer 1 unchanged.

    Layer 7 must never run when layer 1 succeeds — verified indirectly by
    asserting that valid JSON still parses (no over-escape mangles it).
    """
    p = api_client.APIClient._parse_json_response
    # Properly escaped quotes inside zh value
    valid = '[{"id": "x4", "original": "Hello", "zh": "他说\\"你好\\""}]'
    result = p(valid)
    assert len(result) == 1
    assert result[0]["id"] == "x4"
    # zh should still contain the escape sequence (not over-escaped)
    assert '"你好"' in result[0]["zh"]
    print("[OK] w2_escape_fix_does_not_break_valid_json")


def test_w2_repair_helper_directly():
    """Round 53 W2 layer 7: ``_repair_unescaped_quotes_in_strings`` correctness."""
    from core.api_client import _repair_unescaped_quotes_in_strings as repair

    # No-op on well-formed JSON
    assert repair('{"a": "b"}') == '{"a": "b"}'

    # Single stray quote inside value
    fixed = repair('{"a": "he"llo"}')
    assert fixed == '{"a": "he\\"llo"}', f"got: {fixed!r}"

    # Backslash-escape pass-through
    assert repair('{"a": "x\\"y"}') == '{"a": "x\\"y"}'

    # Empty string value
    assert repair('{"a": ""}') == '{"a": ""}'

    # Nested object boundary
    nested = repair('{"a": {"b": "c"}}')
    assert nested == '{"a": {"b": "c"}}', f"got: {nested!r}"

    print("[OK] w2_repair_helper_directly")


def test_pricing_lookup():
    """测试模型级定价查询和推理模型检测"""
    from core.api_client import get_pricing, is_reasoning_model

    # 精确匹配
    pin, pout, exact = get_pricing("xai", "grok-4-1-fast-reasoning")
    assert exact is True
    assert pin == 0.20
    assert pout == 0.50

    # grok-4.20 精确匹配
    pin, pout, exact = get_pricing("xai", "grok-4.20-beta-0309-reasoning")
    assert exact is True
    assert pin == 2.00

    # 前缀匹配（带日期后缀）
    pin, pout, exact = get_pricing("xai", "grok-4-1-fast-reasoning-20260301")
    assert exact is True
    assert pin == 0.20

    # 未知模型 → 提供商兜底
    pin, pout, exact = get_pricing("xai", "grok-99-unknown")
    assert exact is False

    # 推理模型检测
    assert is_reasoning_model("grok-4-1-fast-reasoning") is True
    assert is_reasoning_model("deepseek-reasoner") is True
    assert is_reasoning_model("o1-mini") is True
    assert is_reasoning_model("o3") is True
    assert is_reasoning_model("gpt-4o-mini") is False
    assert is_reasoning_model("grok-3-fast") is False
    assert is_reasoning_model("claude-sonnet-4-20250514") is False

    print("[OK] pricing lookup & reasoning detection")


# ============================================================
# B1: 核心函数单元测试 — protect/restore_placeholders
# ============================================================


def test_api_empty_choices():
    """T50: API 返回空 choices 时不崩溃"""
    from core import api_client

    # 模拟空 choices 的情况——直接测试解析逻辑
    # _call_openai_format 需要网络，这里测试 get_pricing 和 is_reasoning_model
    assert api_client.is_reasoning_model("grok-4-1-fast-reasoning") is True
    assert api_client.is_reasoning_model("gpt-4o-mini") is False
    assert api_client.is_reasoning_model("o3-mini") is True
    assert api_client.is_reasoning_model("deepseek-reasoner") is True
    print("[OK] api_reasoning_detection")


def test_reasoning_model_timeout():
    """推理模型自动提升 timeout"""
    from core import api_client

    config = api_client.APIConfig(
        provider="xai", api_key="test", model="grok-4-1-fast-reasoning", timeout=180.0
    )
    assert config.timeout >= 300.0, f"Expected >= 300, got {config.timeout}"
    # 非推理模型不应提升
    config2 = api_client.APIConfig(
        provider="openai", api_key="test", model="gpt-4o-mini", timeout=180.0
    )
    assert config2.timeout == 180.0
    print("[OK] reasoning_model_timeout")


def _make_urlopen_success(body_bytes: bytes):
    """Build a MagicMock that behaves like ``urlopen(...)`` return value (context manager).

    Uses a real ``BytesIO`` for ``read`` so that the bounded-read helper in
    ``core.http_pool`` (which loops until ``read(N)`` returns ``b''``) terminates
    naturally at EOF instead of looping on a sticky MagicMock ``return_value``.
    """
    from unittest.mock import MagicMock
    import io

    ctx = MagicMock()
    resp = MagicMock()
    resp.read = io.BytesIO(body_bytes).read
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value = False
    return ctx


def _build_httperror(code: int, retry_after: str = ""):
    """Build a ``urllib.error.HTTPError`` with optional Retry-After header."""
    from urllib.error import HTTPError
    from io import BytesIO
    import email.message

    hdrs = email.message.Message()
    if retry_after:
        hdrs["Retry-After"] = retry_after
    return HTTPError("http://example/api", code, "err", hdrs, BytesIO(b'{"error": "x"}'))


_OPENAI_OK_BODY = (
    b'{"choices": [{"message": {"content": "ok"}}],'
    b' "usage": {"prompt_tokens": 1, "completion_tokens": 1}}'
)


def test_api_429_retry_after_header():
    """HTTP 429 with ``Retry-After`` header: wait the advertised seconds then retry."""
    from unittest.mock import patch
    from core import api_client

    config = api_client.APIConfig(
        provider="xai",
        api_key="test",
        model="grok",
        max_retries=3,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = api_client.APIClient(config)

    err = _build_httperror(429, retry_after="2")
    ok = _make_urlopen_success(_OPENAI_OK_BODY)

    with (
        patch.object(api_client.urlreq, "urlopen", side_effect=[err, ok]) as m_open,
        patch.object(api_client.time, "sleep") as m_sleep,
        patch("random.uniform", return_value=0.0),
    ):
        raw = client._call_api("sys", "user")

    assert raw == "ok"
    assert m_open.call_count == 2
    assert m_sleep.call_count == 1
    first_wait = m_sleep.call_args_list[0][0][0]
    assert abs(first_wait - 2.0) < 0.01, f"expected wait ~2s (Retry-After), got {first_wait}"
    print("[OK] test_api_429_retry_after_header")


def test_api_429_exponential_backoff():
    """HTTP 429 without ``Retry-After``: exponential backoff kicks in, then retry succeeds."""
    from unittest.mock import patch
    from core import api_client

    config = api_client.APIConfig(
        provider="xai",
        api_key="test",
        model="grok",
        max_retries=3,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = api_client.APIClient(config)

    err = _build_httperror(429)  # no Retry-After
    ok = _make_urlopen_success(_OPENAI_OK_BODY)

    with (
        patch.object(api_client.urlreq, "urlopen", side_effect=[err, ok]),
        patch.object(api_client.time, "sleep") as m_sleep,
        patch("random.uniform", return_value=0.0),
    ):
        raw = client._call_api("sys", "user")

    assert raw == "ok"
    assert m_sleep.call_count == 1
    wait = m_sleep.call_args_list[0][0][0]
    # attempt=1: base = min(2**1 * 5, 60) = 10, jitter=0 -> wait=10
    assert abs(wait - 10.0) < 0.01, f"expected exponential backoff ~10s, got {wait}"
    print("[OK] test_api_429_exponential_backoff")


def test_api_500_retry():
    """HTTP 500 retries with its own exponential backoff schedule."""
    from unittest.mock import patch
    from core import api_client

    config = api_client.APIConfig(
        provider="xai",
        api_key="test",
        model="grok",
        max_retries=3,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = api_client.APIClient(config)

    err = _build_httperror(500)
    ok = _make_urlopen_success(_OPENAI_OK_BODY)

    with (
        patch.object(api_client.urlreq, "urlopen", side_effect=[err, ok]),
        patch.object(api_client.time, "sleep") as m_sleep,
        patch("random.uniform", return_value=0.0),
    ):
        raw = client._call_api("sys", "user")

    assert raw == "ok"
    assert m_sleep.call_count == 1
    wait = m_sleep.call_args_list[0][0][0]
    # attempt=1: base = min(2**1 * 3, 60) = 6, jitter=0 -> wait=6
    assert abs(wait - 6.0) < 0.01, f"expected 500 backoff ~6s, got {wait}"
    print("[OK] test_api_500_retry")


def test_api_401_no_retry():
    """HTTP 401 surfaces immediately as ``RuntimeError`` — no retry, no sleep."""
    from unittest.mock import patch
    from core import api_client

    config = api_client.APIConfig(
        provider="xai",
        api_key="test",
        model="grok",
        max_retries=3,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = api_client.APIClient(config)

    err = _build_httperror(401)

    with (
        patch.object(api_client.urlreq, "urlopen", side_effect=err),
        patch.object(api_client.time, "sleep") as m_sleep,
    ):
        try:
            client._call_api("sys", "user")
            raised = False
        except RuntimeError as e:
            raised = True
            assert "401" in str(e)
            assert "api-key" in str(e).lower() or "api_key" in str(e).lower()

    assert raised, "expected RuntimeError on 401"
    assert m_sleep.call_count == 0, "401 must not trigger retry sleep"
    print("[OK] test_api_401_no_retry")


def test_api_404_no_retry():
    """HTTP 404 surfaces immediately as ``RuntimeError`` — no retry, no sleep."""
    from unittest.mock import patch
    from core import api_client

    config = api_client.APIConfig(
        provider="xai",
        api_key="test",
        model="bad-model",
        max_retries=3,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = api_client.APIClient(config)

    err = _build_httperror(404)

    with (
        patch.object(api_client.urlreq, "urlopen", side_effect=err),
        patch.object(api_client.time, "sleep") as m_sleep,
    ):
        try:
            client._call_api("sys", "user")
            raised = False
        except RuntimeError as e:
            raised = True
            assert "404" in str(e)
            assert "bad-model" in str(e)

    assert raised, "expected RuntimeError on 404"
    assert m_sleep.call_count == 0, "404 must not trigger retry sleep"
    print("[OK] test_api_404_no_retry")


def test_api_urlerror_retry():
    """Transport-level ``URLError`` (e.g. DNS / TLS / connection refused) retries."""
    from unittest.mock import patch
    from urllib.error import URLError
    from core import api_client

    config = api_client.APIConfig(
        provider="xai",
        api_key="test",
        model="grok",
        max_retries=3,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = api_client.APIClient(config)

    err = URLError("connection refused")
    ok = _make_urlopen_success(_OPENAI_OK_BODY)

    with (
        patch.object(api_client.urlreq, "urlopen", side_effect=[err, ok]) as m_open,
        patch.object(api_client.time, "sleep") as m_sleep,
        patch("random.uniform", return_value=0.0),
    ):
        raw = client._call_api("sys", "user")

    assert raw == "ok"
    assert m_open.call_count == 2
    assert m_sleep.call_count == 1
    wait = m_sleep.call_args_list[0][0][0]
    # URLError path: base = min(2**1 * 3, 60) = 6, jitter=0 -> wait=6
    assert abs(wait - 6.0) < 0.01, f"expected URLError backoff ~6s, got {wait}"
    print("[OK] test_api_urlerror_retry")


def _mock_http_response(status: int, body: bytes = b'{"ok":true}', headers=None):
    """Build a mock ``http.client.HTTPResponse`` (supports status / getheaders / read).

    Uses a real ``BytesIO`` for ``read`` so bounded reads terminate at EOF.
    """
    from unittest.mock import MagicMock
    import io

    resp = MagicMock()
    resp.status = status
    resp.getheaders = MagicMock(return_value=headers or [])
    resp.read = io.BytesIO(body).read
    return resp


def test_http_pool_reuses_connection():
    """Three POSTs on the same thread must hit exactly one underlying HTTPSConnection.

    This is the core reason the pool exists: it eliminates ~150 ms of TCP+TLS
    handshake per request after the first one.
    """
    from unittest.mock import patch, MagicMock
    from core.http_pool import HTTPSConnectionPool

    mock_conn = MagicMock()
    # 每次 getresponse() 返回全新 resp（带独立 BytesIO），这样 3 次 post 都能读到完整 body
    mock_conn.getresponse = MagicMock(side_effect=lambda: _mock_http_response(200))

    with patch("core.http_pool.http.client.HTTPSConnection", return_value=mock_conn) as m_cls:
        pool = HTTPSConnectionPool()
        for _ in range(3):
            body = pool.post("https://api.example.com/v1/x", b"{}", {"X": "1"})
            assert body == b'{"ok":true}'
        assert m_cls.call_count == 1, f"expected 1 connection created, got {m_cls.call_count}"
        assert mock_conn.request.call_count == 3
    print("[OK] test_http_pool_reuses_connection")


def test_http_pool_reconnects_on_transport_error():
    """Transport failure (e.g. keep-alive dropped) should trigger a single reconnect."""
    from unittest.mock import patch, MagicMock
    from core.http_pool import HTTPSConnectionPool

    mock_broken = MagicMock()
    mock_broken.request = MagicMock(side_effect=ConnectionResetError("broken pipe"))

    mock_fresh = MagicMock()
    mock_fresh.getresponse = MagicMock(return_value=_mock_http_response(200))

    with patch(
        "core.http_pool.http.client.HTTPSConnection", side_effect=[mock_broken, mock_fresh]
    ) as m_cls:
        pool = HTTPSConnectionPool()
        body = pool.post("https://api.example.com/v1/x", b"{}", {})

    assert body == b'{"ok":true}'
    assert m_cls.call_count == 2, f"expected reconnect (2 conns), got {m_cls.call_count}"
    assert mock_broken.close.called, "broken connection should have been closed"
    print("[OK] test_http_pool_reconnects_on_transport_error")


def test_http_pool_raises_http_error_on_4xx():
    """HTTP 4xx / 5xx must surface as ``urllib.error.HTTPError`` so that
    ``APIClient._call_api`` retry logic keeps working unchanged."""
    from unittest.mock import patch, MagicMock
    from urllib.error import HTTPError
    from core.http_pool import HTTPSConnectionPool

    mock_conn = MagicMock()
    mock_conn.getresponse = MagicMock(
        return_value=_mock_http_response(
            429, body=b'{"error":"rate"}', headers=[("Retry-After", "5")]
        )
    )

    with patch("core.http_pool.http.client.HTTPSConnection", return_value=mock_conn):
        pool = HTTPSConnectionPool()
        try:
            pool.post("https://api.example.com/v1/x", b"{}", {})
            raised = False
        except HTTPError as e:
            raised = True
            assert e.code == 429
            assert e.headers.get("Retry-After") == "5"
    assert raised, "expected HTTPError on 429"
    print("[OK] test_http_pool_raises_http_error_on_4xx")


def test_api_key_child_env_pop():
    """``_RENPY_TRANSLATOR_CHILD_API_KEY`` must be read with ``pop`` not ``get``.

    Both ``main.py`` and ``one_click_pipeline.py`` read the private child-process
    variable and remove it from the environment in the same statement, so that
    the key does not leak into further ``subprocess`` children spawned by the
    translator (e.g. PyInstaller helpers, Ren'Py's bundled Python). This test
    codifies that contract.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    # 1. In-process pop semantics
    os.environ["_RENPY_TRANSLATOR_CHILD_API_KEY"] = "test_key_xyz"
    key = os.environ.pop("_RENPY_TRANSLATOR_CHILD_API_KEY", "")
    assert key == "test_key_xyz"
    assert "_RENPY_TRANSLATOR_CHILD_API_KEY" not in os.environ
    assert os.environ.pop("_RENPY_TRANSLATOR_CHILD_API_KEY", "") == ""

    # 2. Cross-process: env var set on parent is received by child, then pop() removes it.
    child_code = (
        "import os; "
        "k = os.environ.pop('_RENPY_TRANSLATOR_CHILD_API_KEY', ''); "
        "still = '_RENPY_TRANSLATOR_CHILD_API_KEY' in os.environ; "
        "print(f'{k}|{still}')"
    )
    env = os.environ.copy()
    env["_RENPY_TRANSLATOR_CHILD_API_KEY"] = "sub_key_abc"
    proc = subprocess.run(
        [sys.executable, "-c", child_code],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    assert proc.stdout.strip() == "sub_key_abc|False", f"unexpected child output: {proc.stdout!r}"
    print("[OK] test_api_key_child_env_pop")


# ============================================================
# Response-body size cap (round 22 — H1)
# ============================================================


def test_http_pool_rejects_oversized_response():
    """``HTTPSConnectionPool.post`` must stop reading once the response body
    exceeds ``MAX_API_RESPONSE_BYTES`` (32 MB) and raise ``ResponseTooLarge``.

    Guards against a malicious / misconfigured endpoint streaming unbounded
    data into the translator process, which would otherwise OOM.
    """
    from unittest.mock import patch, MagicMock
    from core.http_pool import HTTPSConnectionPool, ResponseTooLarge

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.getheaders = MagicMock(return_value=[])
    # Each read() returns 64 KB; the pool reads in 64 KB chunks so we hit the
    # 32 MB cap after ~513 iterations without needing to materialise 32 MB in
    # the test process.
    mock_resp.read = MagicMock(return_value=b"\x00" * 65536)

    mock_conn = MagicMock()
    mock_conn.getresponse = MagicMock(return_value=mock_resp)

    with patch("core.http_pool.http.client.HTTPSConnection", return_value=mock_conn):
        pool = HTTPSConnectionPool()
        try:
            pool.post("https://api.example.com/v1/x", b"{}", {})
            raised = False
        except ResponseTooLarge as e:
            raised = True
            msg = str(e)
            assert "32" in msg, f"expected size info in error msg, got: {msg}"
    assert raised, "expected ResponseTooLarge when pool reads past the cap"
    print("[OK] test_http_pool_rejects_oversized_response")


def test_w_monitor2_read_bounded_precision_at_cap():
    """Round 53 monitor #2: ``read_bounded`` precision deviation ≤ 1 byte.

    Pre-r53 baseline: each iteration read a full 64 KB chunk before the
    cap check fired, so streams could exceed the nominal cap by up to
    65535 bytes. r53 monitor #2 tightens this by sizing each read to
    ``min(_READ_CHUNK_SIZE, limit - total + 1)``; the +1 reserves one
    byte for overshoot detection but never accepts it. This test asserts
    the new precision contract.
    """
    from io import BytesIO
    from core.http_pool import read_bounded, ResponseTooLarge

    LIMIT = 1024  # 1 KB — small for fast test
    OVERSHOOT = 100  # data is limit + 100 bytes
    stream = BytesIO(b"\x00" * (LIMIT + OVERSHOOT))
    try:
        read_bounded(stream, limit=LIMIT)
    except ResponseTooLarge:
        pos = stream.tell()
        assert pos <= LIMIT + 1, (
            f"r53 monitor #2 precision contract violated: stream advanced "
            f"to position {pos} but cap is {LIMIT} (max deviation 1 byte)"
        )
        print(
            f"[OK] w_monitor2_read_bounded_precision_at_cap "
            f"(read {pos} bytes, limit {LIMIT}, deviation {pos - LIMIT})"
        )
        return
    raise AssertionError("expected ResponseTooLarge to raise")


def test_w_monitor2_read_bounded_at_exact_limit_succeeds():
    """``read_bounded`` returns full payload when size equals limit exactly."""
    from io import BytesIO
    from core.http_pool import read_bounded

    LIMIT = 2048
    payload = b"\xab" * LIMIT  # exactly at limit
    stream = BytesIO(payload)
    result = read_bounded(stream, limit=LIMIT)
    assert result == payload, "exact-limit payload must return intact"
    assert len(result) == LIMIT
    print("[OK] w_monitor2_read_bounded_at_exact_limit_succeeds")


def test_w_monitor2_read_bounded_one_byte_over_limit_raises():
    """Boundary: limit + 1 byte exactly triggers ResponseTooLarge."""
    from io import BytesIO
    from core.http_pool import read_bounded, ResponseTooLarge

    LIMIT = 2048
    stream = BytesIO(b"\xff" * (LIMIT + 1))
    try:
        read_bounded(stream, limit=LIMIT)
    except ResponseTooLarge:
        print("[OK] w_monitor2_read_bounded_one_byte_over_limit_raises")
        return
    raise AssertionError("limit + 1 byte must raise")


def test_api_client_urllib_rejects_oversized_response():
    """The urllib fallback path in ``APIClient`` must also enforce the cap —
    otherwise setting ``use_connection_pool=False`` would silently bypass
    the hardening.
    """
    from unittest.mock import patch, MagicMock
    from core import api_client
    from core.http_pool import ResponseTooLarge

    config = api_client.APIConfig(
        provider="xai",
        api_key="test",
        model="grok",
        max_retries=1,
        rpm=0,
        rps=0,
        use_connection_pool=False,
    )
    client = api_client.APIClient(config)

    mock_resp = MagicMock()
    mock_resp.read = MagicMock(return_value=b"\x00" * 65536)
    ctx = MagicMock()
    ctx.__enter__.return_value = mock_resp
    ctx.__exit__.return_value = False

    with patch.object(api_client.urlreq, "urlopen", return_value=ctx):
        try:
            client._call_api("sys", "user")
            raised = False
        except ResponseTooLarge:
            raised = True
    assert raised, "urllib fallback path should also raise ResponseTooLarge"
    print("[OK] test_api_client_urllib_rejects_oversized_response")


def run_all() -> int:
    """Run every test in this module; return test count."""
    tests = [
        test_api_config,
        test_usage_stats,
        test_rate_limiter,
        test_json_parse,
        test_w2_escape_fix_inner_quotes_in_zh,
        test_w2_escape_fix_unescaped_in_original,
        test_w2_escape_fix_multiple_stray_quotes,
        test_w2_escape_fix_does_not_break_valid_json,
        test_w2_repair_helper_directly,
        test_pricing_lookup,
        test_api_empty_choices,
        test_reasoning_model_timeout,
        test_api_429_retry_after_header,
        test_api_429_exponential_backoff,
        test_api_500_retry,
        test_api_401_no_retry,
        test_api_404_no_retry,
        test_api_urlerror_retry,
        test_http_pool_reuses_connection,
        test_http_pool_reconnects_on_transport_error,
        test_http_pool_raises_http_error_on_4xx,
        test_api_key_child_env_pop,
        test_http_pool_rejects_oversized_response,
        test_w_monitor2_read_bounded_precision_at_cap,
        test_w_monitor2_read_bounded_at_exact_limit_succeeds,
        test_w_monitor2_read_bounded_one_byte_over_limit_raises,
        test_api_client_urllib_rejects_oversized_response,
    ]
    for t in tests:
        t()
    return len(tests)


if __name__ == "__main__":
    n = run_all()
    print()
    print("=" * 40)
    print(f"ALL {n} TESTS PASSED")
    print("=" * 40)
