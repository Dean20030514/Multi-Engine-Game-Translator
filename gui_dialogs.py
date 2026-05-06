#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""filedialog + messagebox + config I/O + tool-menu mixin — split from
``gui.py`` in round 41.

Contains the five methods that drive user-facing dialog flows:

- :meth:`AppDialogsMixin._load_config` / :meth:`_save_config` —
  JSON round-trip of the basic / advanced settings, with a
  ``filedialog`` picker when the path entry is empty.
- :meth:`_run_upgrade_scan` / :meth:`_run_upgrade_scan_on_game_dir` —
  Ren'Py 7→8 upgrade-scan tool-menu entry.  The dialog variant pops a
  directory picker; the in-process variant captures ``print`` output
  and pumps it through the shared log queue, reusing the pipeline
  mixin's ``_append_log`` / ``_poll_log`` infrastructure.
- :meth:`_browse_dir` — small helper for the two 浏览 buttons on
  Tab 1 (game dir / output dir).

Cross-mixin calls (``self._append_log`` / ``self._log_queue`` /
``self.btn_start`` etc.) resolve through :class:`gui.App`'s MRO —
``App(AppHandlersMixin, AppPipelineMixin, AppDialogsMixin)`` makes
every pipeline attribute visible to dialog methods at runtime.

The ``from tools.renpy_upgrade_tool import run_scan`` inside
``_run_upgrade_scan_on_game_dir`` is intentionally a lazy import: the
tool carries heavier transitive deps (regex, AST walkers) that the
main GUI does not need on startup.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

from safety.file_safety import check_fstat_size


# Round 44 audit-tail: 50 MB cap on the config.json picked by the GUI
# load dialog.  Missed by r37-r43 M2 phases (the GUI was added in r41
# after those rounds, and the mixin split moved this loader to a new
# file without the size-gate idiom being carried over).  Operator
# freely picks any JSON via filedialog, so size bounding matches the
# r37-r43 user-facing loader contract.
_MAX_GUI_CONFIG_SIZE = 50 * 1024 * 1024


class AppDialogsMixin:
    """filedialog / messagebox / config I/O mixed into :class:`gui.App`."""

    def _run_upgrade_scan(self) -> None:
        """工具菜单入口：弹出目录选择对话框后执行升级扫描。"""
        scan_dir = filedialog.askdirectory(title="选择游戏 game 目录")
        if not scan_dir:
            return
        self._run_upgrade_scan_on_game_dir(scan_dir)

    def _run_upgrade_scan_on_game_dir(self, scan_dir: str) -> None:
        """执行 Ren'Py 7→8 升级扫描（工具菜单和翻译模式共用）。"""
        do_fix = messagebox.askyesno("自动修复", "是否自动修复发现的问题？\n（会创建 .bak 备份）")

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="状态: 升级扫描中...", foreground="blue")
        self._start_time = time.time()

        def worker():
            try:
                import io
                import contextlib
                from tools.renpy_upgrade_tool import run_scan
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    results, file_count = run_scan(
                        scan_dir, fix=do_fix, backup=True,
                    )
                output = buf.getvalue()
                for line in output.splitlines(keepends=True):
                    self._log_queue.put(line)
                self._log_queue.put(("__RC__", 0))
            except Exception as e:
                self._log_queue.put(f"\n[ERROR] {e}\n")
                self._log_queue.put(("__RC__", 1))

        threading.Thread(target=worker, daemon=True).start()

    def _load_config(self) -> None:
        path = self.var_config_path.get().strip()
        if not path:
            path = filedialog.askopenfilename(
                title="选择配置文件", filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
            if not path:
                return
            self.var_config_path.set(path)
        try:
            # Round 44 audit-tail: 50 MB cap before read (see module-level
            # docstring for rationale).
            path_obj = Path(path)
            try:
                fsize = path_obj.stat().st_size
            except OSError:
                fsize = 0
            if fsize > _MAX_GUI_CONFIG_SIZE:
                messagebox.showerror(
                    "加载失败",
                    f"配置文件 {fsize} 字节超过 {_MAX_GUI_CONFIG_SIZE} 字节上限，拒绝加载",
                )
                return
            # Round 49 Step 2: TOCTOU defense via check_fstat_size.
            with open(path_obj, encoding="utf-8") as f:
                ok, fsize2 = check_fstat_size(f, _MAX_GUI_CONFIG_SIZE)
                if not ok:
                    messagebox.showerror(
                        "加载失败",
                        f"配置文件 stat 后增长到 {fsize2} 字节（疑似 TOCTOU 攻击），"
                        f"超过 {_MAX_GUI_CONFIG_SIZE} 字节上限，拒绝加载",
                    )
                    return
                data = json.loads(f.read())
            mapping = {
                "provider": self.var_provider, "model": self.var_model,
                "genre": self.var_genre, "rpm": self.var_rpm, "rps": self.var_rps,
                "workers": self.var_workers, "file_workers": self.var_file_workers,
                "timeout": self.var_timeout,
                "temperature": self.var_temperature, "max_chunk_tokens": self.var_max_chunk,
                "max_response_tokens": self.var_max_response, "target_lang": None,
                "tl_lang": self.var_tl_lang, "min_dialogue_density": self.var_min_density,
                "output_dir": self.var_output_dir,
            }
            for key, var in mapping.items():
                if var and key in data and data[key]:
                    var.set(str(data[key]))
            messagebox.showinfo("加载成功", f"已加载配置: {Path(path).name}")
        except Exception as e:
            messagebox.showerror("加载失败", str(e))

    def _save_config(self) -> None:
        path = self.var_config_path.get().strip()
        if not path:
            path = filedialog.asksaveasfilename(
                title="保存配置", defaultextension=".json",
                filetypes=[("JSON", "*.json")])
            if not path:
                return
            self.var_config_path.set(path)
        data = {
            "provider": self.var_provider.get(),
            "model": self.var_model.get(),
            "genre": self.var_genre.get(),
            "rpm": int(self.var_rpm.get() or 600),
            "rps": int(self.var_rps.get() or 10),
            "workers": int(self.var_workers.get() or 3),
            "file_workers": int(self.var_file_workers.get() or 1),
            "timeout": float(self.var_timeout.get() or 180),
            "temperature": float(self.var_temperature.get() or 0.1),
            "max_chunk_tokens": int(self.var_max_chunk.get() or 4000),
            "max_response_tokens": int(self.var_max_response.get() or 32768),
            "tl_lang": self.var_tl_lang.get(),
            "min_dialogue_density": float(self.var_min_density.get() or 0.20),
            "output_dir": self.var_output_dir.get(),
        }
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("保存成功", f"配置已保存: {Path(path).name}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _browse_dir(self, var) -> None:
        path = filedialog.askdirectory()
        if path:
            var.set(path)
            self._update_preview()
