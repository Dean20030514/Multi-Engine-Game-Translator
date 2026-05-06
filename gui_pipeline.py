#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subprocess launch + log pump + progress + completion mixin — split
from ``gui.py`` in round 41.

Contains the nine methods that together drive the subprocess lifecycle:

- :meth:`AppPipelineMixin._start` / :meth:`_run_command` — validate args,
  spawn the worker thread that ``Popen``'s ``main.py`` / ``one_click_pipeline.py``.
- :meth:`_run_dry_run` — variant that launches ``--dry-run`` and collects
  summary lines for a messagebox at the end.
- :meth:`_append_log` / :meth:`_parse_progress` — log text trimming +
  progress-bar regex parsing.
- :meth:`_on_finished` — subprocess completion callback invoked via the
  queue by :meth:`_poll_log`.  Resets buttons, updates status, writes
  trailing log line.
- :meth:`_stop` — Ctrl-C / terminate / kill escalation.
- :meth:`_clear_log` — text-widget clear.
- :meth:`_poll_log` — Tkinter ``after`` timer that drains the subprocess
  log queue at 50-200 ms intervals, dispatches ``__RC__`` / ``__DRYRUN__``
  sentinels to :meth:`_on_finished`.

Requires the host class (``gui.App``) to expose on ``self`` at call
time: ``btn_start`` / ``btn_stop`` / ``lbl_status`` / ``lbl_progress``
/ ``progress_bar`` / ``log_text`` / ``root`` / ``process`` /
``_log_queue`` / ``_start_time`` / ``var_game_dir`` / ``var_api_key``
/ ``_project_root`` (canonicalised ``PROJECT_ROOT`` stashed during
``App.__init__`` so this mixin does not re-derive it from
``__file__``, which would resolve to *this* file's directory), plus
``_build_command`` / ``_mask_api_key`` methods.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox


# 进度日志匹配模式，例如 [3/50] (6%) 或 [3/50]
_RE_PROGRESS = re.compile(r"\[(\d+)/(\d+)\](?:\s*\((\d+)%\))?")

# 日志裁剪阈值
MAX_LOG_LINES = 5000
TRIM_TO = 3000


class AppPipelineMixin:
    """subprocess + log + progress mixed into :class:`gui.App`."""

    def _start(self) -> None:
        game_dir = self.var_game_dir.get().strip()
        if not game_dir:
            messagebox.showwarning("缺少参数", "请填写游戏目录路径")
            return
        api_key = self.var_api_key.get().strip()
        if not api_key:
            messagebox.showwarning("缺少参数", "请填写 API 密钥")
            return

        cmd = self._build_command()
        self._run_command(cmd)

    def _run_command(self, cmd: list[str]) -> None:
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="状态: 运行中...", foreground="blue")
        self._start_time = time.time()
        self._append_log(f">>> {self._mask_api_key(cmd)}\n\n")

        # API key 通过私有环境变量传递；main.py / one_click_pipeline.py 读取后立即 pop
        child_env = os.environ.copy()
        api_key = self.var_api_key.get().strip()
        if api_key:
            child_env["_RENPY_TRANSLATOR_CHILD_API_KEY"] = api_key

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=str(self._project_root),
                    env=child_env,
                )
                self.process = proc
                for line in proc.stdout:
                    self._log_queue.put(line)
                proc.wait()
                self._log_queue.put(("__RC__", proc.returncode))
            except Exception as e:
                self._log_queue.put(f"\n[ERROR] {e}\n")
                self._log_queue.put(("__RC__", -1))

        threading.Thread(target=worker, daemon=True).start()

    def _parse_progress(self, text: str) -> None:
        """从日志行中解析进度信息并更新进度条。"""
        m = _RE_PROGRESS.search(text)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            if m.group(3):
                pct = int(m.group(3))
            else:
                pct = int(current / total * 100) if total > 0 else 0
            self.progress_bar["value"] = pct
            self.lbl_progress.config(text=f"{current}/{total} ({pct}%)")

    def _append_log(self, text: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, text)
        # 日志裁剪：超过阈值时删除早期行
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            trim_end = line_count - TRIM_TO
            self.log_text.delete("1.0", f"{trim_end}.0")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def _on_finished(self, returncode: int) -> None:
        elapsed = time.time() - self._start_time
        self.process = None
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        if returncode == 0:
            self.lbl_status.config(text=f"状态: 完成 ({elapsed:.1f}s)", foreground="green")
            self._append_log(f"\n[完成] 耗时 {elapsed:.1f} 秒\n")
            self.progress_bar["value"] = 100
            self.lbl_progress.config(text="完成")
        else:
            self.lbl_status.config(text=f"状态: 错误 (code={returncode})", foreground="red")
            self._append_log(f"\n[错误] 退出码 {returncode}，耗时 {elapsed:.1f} 秒\n")

    def _stop(self) -> None:
        if self.process:
            try:
                # Windows: 发送 CTRL_C_EVENT 让子进程的 KeyboardInterrupt 触发进度保存
                import signal

                if hasattr(signal, "CTRL_C_EVENT"):
                    self.process.send_signal(signal.CTRL_C_EVENT)
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            except OSError:
                pass
            self.lbl_status.config(text="状态: 已停止", foreground="orange")
            self._append_log("\n[已停止] 进程被终止（已尝试保存进度）\n")
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.lbl_progress.config(text="已停止")

    def _clear_log(self) -> None:
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")

    def _run_dry_run(self) -> None:
        game_dir = self.var_game_dir.get().strip()
        if not game_dir:
            messagebox.showwarning("缺少参数", "请先在「基本设置」中填写游戏目录")
            return
        cmd = self._build_command(dry_run=True)
        self._dry_run_cmd = cmd
        self._dry_run_output = []

        # 使用特殊日志收集
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="状态: 扫描中...", foreground="blue")
        self._start_time = time.time()
        self._append_log(f">>> {self._mask_api_key(cmd)}\n\n")

        # dry-run 无需 API key，但为一致性同样通过 env 传递（若用户已输入）
        child_env = os.environ.copy()
        api_key = self.var_api_key.get().strip()
        if api_key:
            child_env["_RENPY_TRANSLATOR_CHILD_API_KEY"] = api_key

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=str(self._project_root),
                    env=child_env,
                )
                self.process = proc
                lines = []
                for line in proc.stdout:
                    self._log_queue.put(line)
                    lines.append(line)
                proc.wait()
                self._log_queue.put(("__DRYRUN__", lines, proc.returncode))
            except Exception as e:
                self._log_queue.put(f"\n[ERROR] {e}\n")
                self._log_queue.put(("__RC__", -1))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_log(self) -> None:
        got_data = False
        for _ in range(50):
            try:
                item = self._log_queue.get_nowait()
                got_data = True
                if isinstance(item, tuple):
                    if item[0] == "__RC__":
                        self._on_finished(item[1])
                        continue
                    elif item[0] == "__DRYRUN__":
                        lines, rc = item[1], item[2]
                        self._on_finished(rc)
                        if rc == 0:
                            summary = []
                            for line in lines:
                                if any(
                                    k in line
                                    for k in ("剩余文件", "估计费用", "API 调用", "估计输入")
                                ):
                                    summary.append(line.strip())
                            if summary:
                                messagebox.showinfo("Dry-run 摘要", "\n".join(summary))
                        continue
                if isinstance(item, str):
                    self._parse_progress(item)
                self._append_log(item)
            except queue.Empty:
                break
        interval = 50 if got_data else 200
        self._poll_id = self.root.after(interval, self._poll_log)
