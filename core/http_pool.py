#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thread-local HTTPS connection pool using only the Python standard library.

Why this exists
---------------
``urllib.request.urlopen`` does **not** reuse connections. Every call performs
a fresh TCP handshake + TLS handshake. For a typical game translation run
(~600 API calls), that is ~90 s of wasted cold-start time.

Design
------
- One ``http.client.HTTPSConnection`` is cached per thread in ``threading.local()``.
- A single SSL context is shared across threads (``ssl.create_default_context``
  is thread-safe per CPython docs).
- On transport-level failure (keep-alive timeout, peer reset, broken pipe),
  the connection is dropped and the request retries **once** on a fresh
  connection before giving up.
- HTTP-level errors (4xx / 5xx) are raised as ``urllib.error.HTTPError`` so
  that callers who already handle that exception (notably ``APIClient._call_api``)
  keep working unchanged.

Only HTTPS is supported. Callers using plain HTTP endpoints should fall back
to ``urllib.request.urlopen``.

Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

import email.message
import http.client
import logging
import ssl
import threading
from io import BytesIO
from typing import Optional
from urllib.error import HTTPError
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Shared SSL context — building a fresh one per connection wastes ~20 ms each time
# and is unnecessary since the context is immutable after construction.
_SHARED_SSL_CTX = ssl.create_default_context()

# Hard ceiling for any single API response body. Normal LLM responses are
# bounded by ``max_response_tokens`` (default 32768 ≈ ~100 KB of UTF-8), so
# 32 MB leaves ~300× headroom for pathological cases while still guarding
# against a malicious / misbehaving endpoint that streams unbounded data.
MAX_API_RESPONSE_BYTES: int = 32 * 1024 * 1024

# Read buffer size for bounded reads. 64 KB balances syscall overhead with
# the promptness of hitting the size limit on a hostile stream.
_READ_CHUNK_SIZE: int = 64 * 1024


class ResponseTooLarge(RuntimeError):
    """Raised when an HTTP response body exceeds ``MAX_API_RESPONSE_BYTES``."""


def read_bounded(readable, *, limit: int = MAX_API_RESPONSE_BYTES) -> bytes:
    """Read from a file-like ``readable`` object, enforcing a byte-count cap.

    Works for both ``http.client.HTTPResponse`` and the context-manager object
    returned by ``urllib.request.urlopen``. Reads in chunks (≤ 64 KB) so the
    limit is hit promptly on hostile streams without stalling normal use.

    Raises ``ResponseTooLarge`` once cumulative bytes would exceed ``limit``.

    Round 53 monitor item #2 (precision tightening): each iteration's read
    size is capped at ``min(_READ_CHUNK_SIZE, limit - total + 1)``. The
    ``+1`` reserves one byte to detect overshoot at the boundary without
    accepting it. Maximum precision deviation is therefore 1 byte (the
    detector byte itself triggers the raise) instead of the previous
    ~64 KB (one full chunk past the cap before the check fired). The
    fix preserves the fast path for normal-sized responses (< 64 KB
    remaining → ``budget`` is the limiting factor only at the cap edge).
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        budget = limit - total + 1  # +1 = overshoot detector byte
        chunk = readable.read(min(_READ_CHUNK_SIZE, budget))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ResponseTooLarge(
                f"API 响应体超过 {limit // 1024 // 1024} MB 上限，已中断读取 "
                f"(endpoint 可能被劫持或返回异常数据)"
            )
        chunks.append(chunk)
    return b"".join(chunks)


class HTTPSConnectionPool:
    """Per-thread persistent HTTPS connection pool.

    Thread-safe: each thread sees its own connection object via
    ``threading.local()``; there is no cross-thread shared mutable state.

    Typical usage::

        pool = HTTPSConnectionPool(timeout=180.0)
        body = pool.post("https://api.example.com/v1/chat", data, headers)
    """

    def __init__(self, timeout: float = 180.0):
        self._local = threading.local()
        self._timeout = timeout

    def post(self, url: str, data: bytes, headers: dict) -> bytes:
        """Send a POST and return the raw response body bytes.

        Args:
            url: Full HTTPS URL.
            data: Request body (already JSON-encoded).
            headers: Dict of header name → value.

        Returns:
            Response body as bytes.

        Raises:
            urllib.error.HTTPError: On HTTP 4xx / 5xx (matches ``urlopen`` semantics).
            http.client.HTTPException / OSError: On unrecoverable transport failure
                (after one automatic reconnect retry).
        """
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(
                f"HTTPSConnectionPool only supports https:// URLs, got: {parsed.scheme}"
            )
        host = parsed.hostname
        if not host:
            raise ValueError(f"URL missing host: {url}")
        port = parsed.port or 443
        path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")

        # Attempt on current connection; on transport error rebuild once and retry.
        last_transport_err: Optional[BaseException] = None
        for attempt in (1, 2):
            conn = self._get_or_create(host, port)
            try:
                conn.request("POST", path, body=data, headers=headers)
                resp = conn.getresponse()
                body = read_bounded(resp)
            except ResponseTooLarge:
                # Size-limit breach is not a transport problem — drop the
                # (now-misaligned) connection and surface the error.
                self._drop_connection()
                raise
            except (http.client.HTTPException, ConnectionError, OSError) as e:
                last_transport_err = e
                self._drop_connection()
                if attempt == 2:
                    raise
                continue

            if 400 <= resp.status < 600:
                hdrs = email.message.Message()
                for k, v in resp.getheaders():
                    hdrs[k] = v
                raise HTTPError(
                    url,
                    resp.status,
                    body.decode("utf-8", errors="replace"),
                    hdrs,
                    BytesIO(body),
                )
            return body

        # Defensive: loop exits only via return or raise above, but satisfy type checkers.
        if last_transport_err:
            raise last_transport_err
        raise RuntimeError("HTTPSConnectionPool.post: unreachable state")

    def _get_or_create(self, host: str, port: int) -> http.client.HTTPSConnection:
        """Return the thread-local connection, creating a fresh one if needed."""
        key = (host, port)
        existing = getattr(self._local, "conn", None)
        if existing is not None and getattr(self._local, "key", None) == key:
            return existing
        # Different host/port (or no connection yet) — close any stale one first.
        # Round 30: narrow the cleanup exception from bare ``Exception`` to the
        # concrete ones ``http.client.HTTPConnection.close`` is documented to
        # raise, so programming bugs (AttributeError, TypeError) propagate
        # instead of being silently swallowed by connection-pool recycling.
        if existing is not None:
            try:
                existing.close()
            except (OSError, http.client.HTTPException):
                pass
        conn = http.client.HTTPSConnection(
            host, port, timeout=self._timeout, context=_SHARED_SSL_CTX
        )
        self._local.conn = conn
        self._local.key = key
        return conn

    def _drop_connection(self) -> None:
        """Close and forget the thread-local connection (called on transport error)."""
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            try:
                existing.close()
            except (OSError, http.client.HTTPException):
                pass
        self._local.conn = None
        self._local.key = None

    def close(self) -> None:
        """Close the current thread's connection. Other threads' connections are
        left to ordinary garbage collection when their threads exit."""
        self._drop_connection()
