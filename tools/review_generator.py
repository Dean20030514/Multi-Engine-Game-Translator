#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""翻译校对 HTML 报告生成器：side-by-side 对比原文与译文。

用法���
    python review_generator.py translation_db.json -o review.html
    python review_generator.py translation_db.json --issues-only
"""

from __future__ import annotations

import html
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)

# Round 39 M2 phase-2: reject translation_db.json inputs above 50 MB
# before ``json.loads`` reads them.  Legitimate DBs fit in single-digit
# MB even at tens of thousands of entries; 50 MB+ is almost certainly
# malformed or attacker-crafted.  Matches the cap used in
# ``core/translation_db.py`` and the r37 M2 family for consistency.
_MAX_REVIEW_DB_SIZE = 50 * 1024 * 1024


def generate_review_html(
    db_path: Path,
    output_path: Path,
    *,
    show_only_issues: bool = False,
) -> int:
    """生成 side-by-side 翻译校对 HTML 报告。

    Args:
        db_path: translation_db.json 路径
        output_path: 输出 HTML 路径
        show_only_issues: True 则仅显示有 error/warning 的条目

    Returns:
        报告中的条目数（0 表示 DB 超过 50 MB 软上限或无条目）
    """
    # Round 39 M2: size-cap before read.
    try:
        file_size = db_path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > _MAX_REVIEW_DB_SIZE:
        logger.warning(
            "[REVIEW] %s too large (%d bytes > %d-byte cap), "
            "refusing to load", db_path, file_size, _MAX_REVIEW_DB_SIZE,
        )
        return 0
    # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
    with open(db_path, encoding="utf-8") as f:
        ok, fsize2 = check_fstat_size(f, _MAX_REVIEW_DB_SIZE)
        if not ok:
            logger.warning(
                "[REVIEW] %s grew past cap after stat (TOCTOU?): "
                "%d bytes > %d, refusing to load",
                db_path, fsize2, _MAX_REVIEW_DB_SIZE,
            )
            return 0
        data = json.loads(f.read())
    entries = data.get("entries", []) if isinstance(data, dict) else []

    if show_only_issues:
        entries = [
            e for e in entries
            if e.get("error_codes") or e.get("warning_codes") or e.get("status") in ("error", "warning", "writeback_failed", "checker_dropped")
        ]

    # 按文件分组
    by_file: dict[str, list[dict]] = {}
    for e in entries:
        f = e.get("file", "(unknown)")
        by_file.setdefault(f, []).append(e)

    # 统计
    total = len(entries)
    errors = sum(1 for e in entries if e.get("status") == "error" or e.get("error_codes"))
    warnings = sum(1 for e in entries if e.get("status") == "warning" or e.get("warning_codes"))
    ok = sum(1 for e in entries if e.get("status") == "ok")
    failed = sum(1 for e in entries if e.get("status") in ("writeback_failed", "checker_dropped"))

    # 生成 HTML
    parts: list[str] = []
    parts.append(_HTML_HEAD.format(
        total=total, ok=ok, errors=errors, warnings=warnings, failed=failed,
        files=len(by_file),
        mode="仅问题条目" if show_only_issues else "全部条目",
    ))

    for file_path, file_entries in sorted(by_file.items()):
        file_entries.sort(key=lambda e: e.get("line", 0))
        fe = sum(1 for e in file_entries if e.get("status") == "error" or e.get("error_codes"))
        fw = sum(1 for e in file_entries if e.get("status") == "warning" or e.get("warning_codes"))
        parts.append(f'<details{"" if fe or fw else " open"}>')
        badge = ""
        if fe:
            badge += f' <span class="badge err">{fe} error</span>'
        if fw:
            badge += f' <span class="badge warn">{fw} warn</span>'
        parts.append(f'<summary><b>{html.escape(file_path)}</b> ({len(file_entries)} 条){badge}</summary>')
        parts.append('<table><tr><th>行</th><th>状态</th><th>原文</th><th>译文</th><th>代码</th></tr>')

        for e in file_entries:
            line = e.get("line", "?")
            orig = html.escape(e.get("original", "")[:120])
            trans = html.escape(e.get("translation", "")[:120])
            status = e.get("status", "ok")
            codes = ", ".join(e.get("error_codes", []) + e.get("warning_codes", []))

            if status == "error" or e.get("error_codes"):
                cls = "err"
            elif status in ("writeback_failed", "checker_dropped"):
                cls = "fail"
            elif status == "warning" or e.get("warning_codes"):
                cls = "warn"
            else:
                cls = "ok"

            parts.append(
                f'<tr class="{cls}">'
                f'<td>{line}</td><td>{status}</td>'
                f'<td>{orig}</td><td>{trans}</td>'
                f'<td><small>{html.escape(codes)}</small></td></tr>'
            )

        parts.append('</table></details>')

    parts.append('</body></html>')
    output_path.write_text('\n'.join(parts), encoding="utf-8")
    return total


_HTML_HEAD = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Translation Review</title>
<style>
body {{ font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
h1 {{ color: #569cd6; }}
.stats {{ background: #252526; padding: 10px; border-radius: 5px; margin-bottom: 15px; }}
.stats b {{ color: #4ec9b0; }}
table {{ width: 100%; border-collapse: collapse; margin: 5px 0 15px 0; }}
th {{ background: #333; color: #9cdcfe; text-align: left; padding: 4px 8px; }}
td {{ padding: 4px 8px; border-bottom: 1px solid #333; max-width: 400px; word-wrap: break-word; }}
tr.ok {{ }}
tr.warn {{ background: #3e3500; }}
tr.err {{ background: #500000; }}
tr.fail {{ background: #2d1b4e; }}
summary {{ cursor: pointer; padding: 5px; margin: 5px 0; }}
summary:hover {{ background: #333; }}
.badge {{ font-size: 0.8em; padding: 1px 6px; border-radius: 3px; }}
.badge.err {{ background: #d32f2f; color: white; }}
.badge.warn {{ background: #f9a825; color: black; }}
details {{ margin-bottom: 5px; }}
</style></head><body>
<h1>Translation Review Report</h1>
<div class="stats">
<b>模式</b>: {mode} |
<b>总条目</b>: {total} |
<b>文件</b>: {files} |
<span style="color:#4caf50">OK: {ok}</span> |
<span style="color:#f9a825">警告: {warnings}</span> |
<span style="color:#d32f2f">错误: {errors}</span> |
<span style="color:#9c27b0">失败: {failed}</span>
</div>
"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description="生成翻译校对 HTML 报告")
    parser.add_argument("db_path", help="translation_db.json 路径")
    parser.add_argument("-o", "--output", default="review.html", help="输出 HTML 路径")
    parser.add_argument("--issues-only", action="store_true", help="仅显示有问题的条目")
    args = parser.parse_args()

    db = Path(args.db_path)
    if not db.exists():
        print(f"文件不存在: {db}")
        sys.exit(1)

    out = Path(args.output)
    count = generate_review_html(db, out, show_only_issues=args.issues_only)
    print(f"已生成校对报告: {out} ({count} 条)")


if __name__ == "__main__":
    main()
