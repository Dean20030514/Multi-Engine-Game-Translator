#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom translation plugin loader — sandbox-only subprocess mode.

Split from ``core/api_client.py`` in round 40 as one of four pre-existing
> 800-line source files flagged by HANDOFF r39→40.  Round 52 BREAKING
retired the legacy ``importlib`` in-process loader (``_load_custom_engine``)
— every custom plugin now runs in a sandboxed subprocess via
:class:`_SubprocessPluginClient`.  Public API is re-exported from
:mod:`core.api_client`.

Plugin runs in a separate interpreter invoked with
``python -u <plugin>.py --plugin-serve``.  Host and plugin exchange
JSONL messages over stdin / stdout.  Reuses a single child across
every chunk translation so the startup cost (~100-150ms) is
amortised.  10 KB stderr read cap (round 30) prevents a pathological
plugin from OOMing the host with an exception-message flood.

Migration from importlib mode (pre-round-52):
  * Plugin file must expose ``translate_batch(system_prompt, user_prompt)``
    or the per-item ``translate(text, source_lang, target_lang)``.
  * Plugin file must include an ``if __name__ == "__main__":`` block
    that handles the ``--plugin-serve`` argv and runs a JSONL serve
    loop reading requests from stdin and writing responses to stdout.
  * See ``custom_engines/example_echo.py`` for the canonical template.
  * Plugins lacking the serve block trigger an immediate startup
    failure with migration guidance via the readiness probe in
    :meth:`_SubprocessPluginClient.__init__`.
"""

from __future__ import annotations

import atexit
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


_CUSTOM_ENGINES_DIR = "custom_engines"

# Round 52: readiness probe after subprocess launch.  A plugin that
# lacks the ``--plugin-serve`` block exits immediately (exit 1 with
# the "This is a translation plugin..." stderr printed by the
# example_echo template).  Polling for early exit catches that case
# at __init__ time, surfacing migration guidance before the first
# translate() call rather than deferring the diagnostic.
#
# 5 polls * 20ms = ~100ms ceiling; well-formed plugins never trip
# this because the JSONL serve loop blocks on stdin reading and
# stays alive indefinitely.
_STARTUP_PROBE_POLL_COUNT = 5
_STARTUP_PROBE_POLL_INTERVAL = 0.02

# Round 43 audit-tail: per-line cap on the subprocess stdout response.
# ``_SubprocessPluginClient`` reads plugin stdout one line at a time
# via ``readline()``; without a bound, a misbehaving or adversarial
# plugin can emit an unbounded single-line payload and OOM the host
# before the JSON decoder even runs.  r30 already added a 10 KB stderr
# cap for crash diagnostics; this matches it on the main response
# channel.
#
# Round 44 audit-tail: the unit here is **characters, not bytes**.
# :meth:`subprocess.Popen` is started with ``text=True, encoding="utf-8"``
# (r28 S-H-4), so ``self._proc.stdout`` is a text stream and
# ``readline(N)`` counts ``N`` CHARS (decoded codepoints), not bytes.
# On a pure-ASCII payload the cap is effectively 50 MB of bytes, but on
# a response dominated by CJK text each char is 3 UTF-8 bytes, so the
# worst-case byte footprint is ~150 MB before we reject.  This is
# acceptable defensive coverage for the OOM DoS threat the cap was
# added to address (host has GB-range RAM; 150 MB is manageable), but
# the variable name previously claimed BYTES and was therefore
# misleading.  Legitimate batch responses are typically < 1 MB of JSON.
_MAX_PLUGIN_RESPONSE_CHARS = 50 * 1024 * 1024


class _SubprocessPluginClient:
    """Long-running subprocess wrapper for custom translation plugins.

    Round 28 introduced the subprocess sandbox as opt-in (``--sandbox-plugin``).
    Round 52 BREAKING made it the only mode — custom plugins are now
    always invoked through an out-of-process JSONL protocol.  That denies
    the plugin direct access to the host's environment variables, file
    descriptors, and heap, while keeping latency acceptable by reusing a
    single child interpreter across every chunk translation.

    Protocol (newline-delimited JSON, one object per line):

    * Request (host → plugin):
      ``{"request_id": <int>, "system_prompt": <str>, "user_prompt": <str>}``
    * Response (plugin → host):
      ``{"request_id": <int>, "response": <str|null>, "error": <str|null>}``
    * Shutdown (host → plugin): ``{"request_id": -1}`` followed by stdin close.

    The plugin module's ``__main__`` block is responsible for reading
    stdin, dispatching to ``translate_batch`` / ``translate``, and writing
    the JSON line to stdout (flushed).  ``custom_engines/example_echo.py``
    demonstrates the canonical shape; plugins lacking the serve block
    fail at __init__ time via the startup readiness probe.
    """

    _SHUTDOWN_REQUEST_ID = -1

    def __init__(
        self,
        module_name: str,
        *,
        timeout: float = 180.0,
    ) -> None:
        if not module_name:
            raise RuntimeError(
                "自定义引擎需要指定模块名: --custom-module <模块名>\n"
                f"模块文件应放在项目目录的 {_CUSTOM_ENGINES_DIR}/ 子目录下"
            )

        if module_name.endswith(".py"):
            module_name = module_name[:-3]
        if "/" in module_name or "\\" in module_name or ".." in module_name:
            raise RuntimeError(f"自定义引擎模块名不能包含路径分隔符: '{module_name}'")

        project_root = Path(__file__).resolve().parent.parent
        engines_dir = project_root / _CUSTOM_ENGINES_DIR
        module_path = engines_dir / f"{module_name}.py"
        if not module_path.is_file():
            raise RuntimeError(
                f"自定义引擎模块未找到: {module_path}\n"
                f"请在 {engines_dir}/ 目录下创建 {module_name}.py 文件"
            )

        self._module_path = module_path
        self._timeout = timeout
        self._request_id = 0
        self._lock = threading.Lock()
        self._closed = False
        # ``_proc`` is assigned before ``atexit.register`` so that if the
        # Popen call itself raises (e.g. the interpreter binary vanished),
        # the finalizer has nothing to tear down.  If any post-launch step
        # raises, the try/except below guarantees we kill the child before
        # propagating so a half-initialised instance never leaks a process.
        self._proc = None

        try:
            # Launch the subprocess.  ``-u`` ensures unbuffered stdout so
            # every response line reaches us without waiting for a full
            # buffer.
            self._proc = subprocess.Popen(
                [sys.executable, "-u", str(module_path), "--plugin-serve"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(project_root),
                text=True,
                encoding="utf-8",
                # Line-buffered on the host side so our writes flush per line.
                bufsize=1,
            )
            logger.info(
                "[API] 沙箱模式启动自定义引擎子进程: %s (pid=%s)",
                module_path,
                self._proc.pid,
            )
            # Round 52: readiness probe.  A plugin missing the
            # ``--plugin-serve`` block exits immediately (typically
            # exit 1 with the example_echo template's "This is a
            # translation plugin..." stderr).  Polling for early
            # exit at __init__ surfaces the migration error before
            # any translate() call is dispatched.
            for _ in range(_STARTUP_PROBE_POLL_COUNT):
                if self._proc.poll() is not None:
                    stderr_tail = ""
                    try:
                        stderr_tail = (self._proc.stderr.read(10_000) or "")[-600:]  # type: ignore[union-attr]
                    except (OSError, ValueError):
                        pass
                    raise RuntimeError(
                        f"自定义引擎子进程在启动后立即退出 "
                        f"(exit={self._proc.returncode}): {stderr_tail}\n"
                        f"\n"
                        f"自 round 52 起所有 custom plugin 强制走 subprocess 沙箱，\n"
                        f"plugin 必须在 if __name__ == '__main__': block 中处理\n"
                        f"--plugin-serve 参数并运行 JSONL 协议 serve loop。\n"
                        f"参考 custom_engines/example_echo.py 的 _plugin_serve()。"
                    )
                time.sleep(_STARTUP_PROBE_POLL_INTERVAL)
            # Best-effort cleanup when the process interpreter exits without
            # an explicit close() call (e.g. KeyboardInterrupt paths).
            atexit.register(self._shutdown_quietly)
        except BaseException:
            # Round 30 robustness: if we managed to start the child but
            # something else (e.g. ``atexit.register``) raised before we
            # finished initialising, kill the orphaned process so it
            # doesn't linger.
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            raise

    # -----------------------------------------------------------------
    # Public duck-typed interface mirroring a loaded plugin module.
    # ``APIClient._call_custom`` checks ``hasattr(mod, "translate_batch")``
    # and calls it with the raw prompts — presenting the same method
    # here means the sandbox path reuses the legacy batch-dispatch code.
    # -----------------------------------------------------------------

    def translate_batch(self, system_prompt: str, user_prompt: str) -> str:
        return self._call(system_prompt, user_prompt)

    def _call(self, system_prompt: str, user_prompt: str) -> str:
        if self._closed:
            raise RuntimeError("自定义引擎子进程已关闭，无法继续调用")
        if self._proc.poll() is not None:  # type: ignore[union-attr]
            stderr = ""
            try:
                # Round 30 bound: cap stderr read at 10 KB so a pathological
                # plugin spewing megabytes of text on exit cannot OOM the
                # host.  Only the tail is shown in the error anyway.
                stderr = (self._proc.stderr.read(10_000) or "")[-600:]  # type: ignore[union-attr]
            except (OSError, ValueError):
                pass
            raise RuntimeError(
                f"自定义引擎子进程意外退出 (exit={self._proc.returncode}): {stderr}"  # type: ignore[union-attr]
            )

        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            request = {
                "request_id": req_id,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
            try:
                line = json.dumps(request, ensure_ascii=False) + "\n"
                self._proc.stdin.write(line)  # type: ignore[union-attr]
                self._proc.stdin.flush()  # type: ignore[union-attr]
            except (BrokenPipeError, OSError) as e:
                raise RuntimeError(f"自定义引擎子进程写入失败: {e}") from e

            # Single-line read; the protocol guarantees one response per
            # request delimited by ``\n``.  The host-side timeout is the
            # APIConfig timeout; if the plugin hangs we kill the process.
            response_line = self._read_response_line(req_id)
            try:
                response = json.loads(response_line)
            except (json.JSONDecodeError, ValueError) as e:
                raise RuntimeError(f"自定义引擎子进程返回非法 JSON: {response_line[:200]!r}") from e

            if response.get("request_id") != req_id:
                raise RuntimeError(
                    f"自定义引擎子进程响应乱序: expected request_id={req_id}, "
                    f"got {response.get('request_id')!r}"
                )
            error = response.get("error")
            if error:
                raise RuntimeError(f"自定义引擎子进程报错: {error}")
            payload = response.get("response")
            if payload is None:
                return ""
            if isinstance(payload, str):
                return payload
            # If the plugin returns list[dict] through the JSON field we
            # re-serialise it so the caller's ``json.loads`` round-trip
            # still works.
            return json.dumps(payload, ensure_ascii=False)

    def _read_response_line(self, req_id: int) -> str:
        """Read a single line from the subprocess stdout with timeout."""
        # ``TimeoutExpired`` would only work with ``communicate``; here we
        # emulate a deadline by reading in a helper thread and joining
        # with timeout.  This keeps the implementation pure-stdlib.
        result: list[str] = []
        error: list[BaseException] = []

        def _reader() -> None:
            try:
                # Round 43 / Round 44 audit-tail: bound the read so a
                # misbehaving plugin cannot OOM the host with an
                # unbounded single response line.  ``readline(N)`` on
                # the text-mode subprocess.stdout returns up to N CHARS
                # (decoded codepoints) OR up-to-and-including the next
                # newline, whichever comes first — so if the plugin
                # hits the char cap without emitting a newline we
                # detect the malformed response and raise instead of
                # accepting a truncated line.  See the
                # ``_MAX_PLUGIN_RESPONSE_CHARS`` docstring for the
                # byte-vs-char distinction.
                line = self._proc.stdout.readline(_MAX_PLUGIN_RESPONSE_CHARS)  # type: ignore[union-attr]
                if line == "":
                    error.append(EOFError("plugin stdout closed before response"))
                    return
                if len(line) >= _MAX_PLUGIN_RESPONSE_CHARS and not line.endswith("\n"):
                    error.append(
                        RuntimeError(
                            f"plugin response line exceeded "
                            f"{_MAX_PLUGIN_RESPONSE_CHARS} chars without "
                            f"newline — treating as malformed oversized "
                            f"response (request_id={req_id})"
                        )
                    )
                    return
                result.append(line.rstrip("\n"))
            except BaseException as e:  # noqa: BLE001 - re-raise on main thread
                error.append(e)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(self._timeout)
        if t.is_alive():
            # Plugin stuck — kill the subprocess so we don't leak it.
            # Wait briefly so poll() reflects the terminated state for any
            # diagnostic code the caller runs after catching this error.
            try:
                self._proc.kill()  # type: ignore[union-attr]
            except OSError:
                pass
            try:
                self._proc.wait(timeout=2)  # type: ignore[union-attr]
            except subprocess.TimeoutExpired:
                pass
            raise RuntimeError(f"自定义引擎子进程响应超时 (>{self._timeout}s, request_id={req_id})")
        if error:
            raise RuntimeError(f"读取自定义引擎子进程响应失败: {error[0]}") from error[0]
        return result[0] if result else ""

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def close(self) -> None:
        """Send the shutdown sentinel and terminate the subprocess.

        Safe to call multiple times.  Catches every subprocess-related
        error so repeated shutdowns never raise.
        """
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.poll() is None and self._proc.stdin and not self._proc.stdin.closed:  # type: ignore[union-attr]
                self._proc.stdin.write(  # type: ignore[union-attr]
                    json.dumps({"request_id": self._SHUTDOWN_REQUEST_ID}) + "\n"
                )
                self._proc.stdin.flush()  # type: ignore[union-attr]
                self._proc.stdin.close()  # type: ignore[union-attr]
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            self._proc.wait(timeout=5)  # type: ignore[union-attr]
        except subprocess.TimeoutExpired:
            try:
                self._proc.kill()  # type: ignore[union-attr]
            except OSError:
                pass
            try:
                self._proc.wait(timeout=2)  # type: ignore[union-attr]
            except subprocess.TimeoutExpired:
                pass

    def _shutdown_quietly(self) -> None:
        """``atexit`` hook — swallow all errors so interpreter exit is clean."""
        try:
            self.close()
        except BaseException:  # noqa: BLE001
            pass

    def __del__(self) -> None:  # pragma: no cover - finaliser
        try:
            self.close()
        except BaseException:  # noqa: BLE001
            pass
