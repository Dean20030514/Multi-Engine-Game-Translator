#!/usr/bin/env python3
"""对已有翻译结果重新跑闸门验证（不调 API）。

使用 one_click_pipeline.evaluate_gate 读取已生成的 pilot 输入/输出，
在当前代码版本（包括最新阈值）下重新计算 GATE-PILOT 统计。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.gate import evaluate_gate

# 默认路径（可通过环境变量覆盖）
_DEFAULT_PROJECT = r"C:\Users\16097\Desktop\Renpy翻译\Renpy汉化（我的）\output\projects\TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed"


def main() -> None:
    project = Path(os.environ.get("REVALIDATE_PROJECT", _DEFAULT_PROJECT))
    # 原文根目录：pilot 阶段采样出来的原始脚本
    original_root = project / "_pipeline" / "pilot_input"
    # 译文根目录：pilot 阶段对应的翻译结果（带 game 子目录）
    translated_root = project / "_pipeline" / "pilot_output" / "game"

    if not original_root.exists():
        raise SystemExit(f"original_root 不存在: {original_root}")
    if not translated_root.exists():
        raise SystemExit(f"translated_root 不存在: {translated_root}")

    gate = evaluate_gate(original_root, translated_root)

    print("\n=== 重新验证结果（GATE-PILOT） ===")
    for k in sorted(gate.keys()):
        print(f"  {k}: {gate[k]}")


if __name__ == "__main__":
    main()
