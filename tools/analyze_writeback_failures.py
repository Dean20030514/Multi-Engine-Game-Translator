#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回写失败根因分析工具

输入：translation_db.json（含 status="writeback_failed" 的条目）
输出：按失败类型分类的统计报告 + 典型样本

用法：
    python analyze_writeback_failures.py output/translation_db.json
    python analyze_writeback_failures.py output/projects/MyGame/translation_db.json
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)

# Round 39 M2 phase-2: reject translation_db.json inputs above 50 MB
# before ``json.loads``.  Matches the cap used in
# ``core/translation_db.py`` and ``tools/review_generator.py``.
_MAX_ANALYSIS_DB_SIZE = 50 * 1024 * 1024


FAILURE_TYPES = {
    "WF-01": "行号偏移过大",
    "WF-02": "原文被截断",
    "WF-03": "原文被修改",
    "WF-04": "引号嵌套冲突",
    "WF-05": "跨行文本",
    "WF-06": "重复原文冲突",
    "WF-07": "编码不一致",
    "WF-08": "其他",
}


def analyze(db_path: Path) -> dict:
    """分析 translation_db.json 中的回写失败条目。

    Round 39 M2: 拒绝 > 50 MB 的输入文件（warning + 返回空结果）。
    """
    # Round 39 M2: size-cap before read.
    try:
        file_size = db_path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > _MAX_ANALYSIS_DB_SIZE:
        logger.warning(
            "[ANALYSIS] %s too large (%d bytes > %d-byte cap), "
            "refusing to load", db_path, file_size, _MAX_ANALYSIS_DB_SIZE,
        )
        return {"total": 0, "by_type": {}, "samples": {}}
    # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
    with open(db_path, encoding="utf-8") as f:
        ok, fsize2 = check_fstat_size(f, _MAX_ANALYSIS_DB_SIZE)
        if not ok:
            logger.warning(
                "[ANALYSIS] %s grew past cap after stat (TOCTOU?): "
                "%d bytes > %d, refusing to load",
                db_path, fsize2, _MAX_ANALYSIS_DB_SIZE,
            )
            return {"total": 0, "by_type": {}, "samples": {}}
        data = json.loads(f.read())
    entries = data.get("entries", []) if isinstance(data, dict) else []

    # 筛选回写失败条目
    failures = [e for e in entries if e.get("status") == "writeback_failed"]

    if not failures:
        return {"total": 0, "by_type": {}, "samples": {}}

    # 按类型统计
    type_counter: Counter = Counter()
    samples: dict[str, list[dict]] = {}

    for entry in failures:
        diag = entry.get("diagnostic", {})
        ft = diag.get("failure_type", "WF-08")
        type_counter[ft] += 1
        if ft not in samples:
            samples[ft] = []
        if len(samples[ft]) < 3:  # 每种类型保留前 3 个样本
            samples[ft].append({
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "original": entry.get("original", "")[:80],
                "detail": diag.get("detail", ""),
            })

    # 按占比排序
    total = len(failures)
    by_type = {}
    for ft, count in type_counter.most_common():
        by_type[ft] = {
            "count": count,
            "ratio": round(count / total, 4),
            "description": FAILURE_TYPES.get(ft, "未知"),
        }

    return {"total": total, "by_type": by_type, "samples": samples}


def print_report(result: dict) -> None:
    """打印分析报告。"""
    total = result["total"]
    if total == 0:
        print("未发现回写失败条目（status='writeback_failed'）。")
        print("提示：需要先用最新代码跑一次 direct-mode 翻译来采集诊断数据。")
        return

    print("=" * 60)
    print(f"回写失败根因分析报告")
    print("=" * 60)
    print(f"\n总失败数: {total}")
    print(f"\n按类型分布:")

    for ft, info in result["by_type"].items():
        desc = info["description"]
        count = info["count"]
        ratio = info["ratio"]
        print(f"  {ft} {desc:12s}: {count:5d} ({ratio:.1%})")

    print(f"\n{'=' * 60}")
    print("各类型典型样本（前 3 条）")
    print("=" * 60)

    for ft, samples in result["samples"].items():
        desc = FAILURE_TYPES.get(ft, "未知")
        print(f"\n--- {ft} {desc} ---")
        for s in samples:
            print(f"  文件: {s['file']}")
            print(f"    行号: {s['line']}")
            print(f"    原文: \"{s['original']}\"")
            if s["detail"]:
                print(f"    详情: {s['detail']}")


def main():
    if len(sys.argv) < 2:
        print("用法: python analyze_writeback_failures.py <translation_db.json>")
        sys.exit(1)

    db_path = Path(sys.argv[1])
    if not db_path.exists():
        print(f"文件不存在: {db_path}")
        sys.exit(1)

    result = analyze(db_path)
    print_report(result)

    # 同时输出 JSON 格式（供程序化分析）
    json_out = db_path.parent / "writeback_analysis.json"
    json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON 报告已保存: {json_out}")


if __name__ == "__main__":
    main()
