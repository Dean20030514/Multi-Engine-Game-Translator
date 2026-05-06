#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键流水线：试跑批次 + 自动闸门 + 全量批处理 + 漏翻增量轮"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import logging

logger = logging.getLogger(__name__)


from pipeline.helpers import StageError, _print, resolve_scan_root
from pipeline.stages import (
    _run_pilot_phase,
    _run_full_translation_phase,
    _run_retranslate_phase,
    _run_tl_mode_phase,
    _run_final_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键翻译流水线")
    parser.add_argument("--game-dir", required=True, help="游戏根目录")
    parser.add_argument(
        "--provider",
        default="xai",
        choices=["xai", "grok", "openai", "deepseek", "claude", "gemini"],
    )
    parser.add_argument("--api-key", default="", help="API 密钥；留空则读取 XAI_API_KEY")
    parser.add_argument("--model", default="grok-4-1-fast-reasoning")
    parser.add_argument(
        "--genre", default="adult", choices=["adult", "visual_novel", "rpg", "general"]
    )
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument(
        "--file-workers", type=int, default=1, help="文件级并行线程数 (>1 多文件同时翻译)"
    )
    parser.add_argument("--rpm", type=int, default=600)
    parser.add_argument("--rps", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-chunk-tokens", type=int, default=4000)
    parser.add_argument("--max-response-tokens", type=int, default=32768)
    parser.add_argument("--pilot-count", type=int, default=20, help="试跑文件数")
    parser.add_argument(
        "--gate-max-untranslated-ratio", type=float, default=0.08, help="闸门允许的最大漏翻占比"
    )
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--clean-output", action="store_true", help="开始前清理输出目录")
    parser.add_argument(
        "--dict", nargs="*", default=[], metavar="PATH", help="词典文件（透传 main.py）"
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[], metavar="PATTERN", help="排除文件模式（透传 main.py）"
    )
    parser.add_argument(
        "--copy-assets", action="store_true", help="复制非 .rpy 资源（透传 main.py）"
    )
    parser.add_argument(
        "--package-name", default="CN_patch_game", help="输出 zip 包名（不含扩展名）"
    )
    parser.add_argument(
        "--patch-font",
        action="store_true",
        default=False,
        help="打包前启用自动字体补丁：复制字体到 game/ 并改写 gui.*_font",
    )
    parser.add_argument(
        "--font-file",
        default="",
        metavar="PATH",
        help="指定字体文件路径，覆盖默认的 resources/fonts/ 查找",
    )
    parser.add_argument(
        "--min-dialogue-density",
        type=float,
        default=0.20,
        metavar="RATIO",
        help="对话密度阈值 (默认: 0.20)；低于此值的文件走定向翻译模式",
    )
    parser.add_argument(
        "--tl-mode",
        action="store_true",
        default=False,
        help="使用 tl-mode 替代 direct-mode：跳过试跑/补翻，直接扫描 tl/<lang>/ 空槽位翻译",
    )
    parser.add_argument(
        "--tl-lang",
        default="chinese",
        metavar="LANG",
        help="tl 语言子目录名 (默认: chinese)；仅 --tl-mode 时有效",
    )
    parser.add_argument(
        "--tl-screen",
        action="store_true",
        default=False,
        help="翻译 screen 中的裸英文字符串（text/textbutton/Tooltip/Notify）",
    )
    parser.add_argument(
        "--no-lint-repair",
        action="store_true",
        default=False,
        help="跳过翻译后的 Ren'Py lint 修复阶段",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # Round 52 C4 BREAKING: --target-lang retired; force zh.
    args.target_lang = "zh"
    t0 = time.time()

    # API Key 解析优先级（高 → 低）：
    #   1. --api-key CLI（显式传入）
    #   2. _RENPY_TRANSLATOR_CHILD_API_KEY（GUI/launcher 注入的子进程专用变量，
    #      读完立即 pop 防止继承到下游 subprocess）
    #   3. XAI_API_KEY 通用环境变量（向后兼容 CLI 用户习惯）
    api_key = (
        args.api_key
        or os.environ.pop("_RENPY_TRANSLATOR_CHILD_API_KEY", "")
        or os.environ.get("XAI_API_KEY", "")
    )
    if not api_key:
        raise StageError("未提供 API key，请传 --api-key 或设置 XAI_API_KEY")
    project_root = Path(args.game_dir).resolve()
    if not project_root.exists():
        raise StageError(f"游戏目录不存在: {project_root}")

    scan_root = resolve_scan_root(project_root)

    # 项目级输出根目录: <output-dir>/projects/<project_name>/
    out_root = Path(args.output_dir).resolve()
    project_name = project_root.name
    project_out_root = out_root / "projects" / project_name

    # 分阶段目录（目前实际输出落在 stage2_translated，其余阶段为预留占位）
    stage0_raw = project_out_root / "stage0_raw"
    stage1_normalized = project_out_root / "stage1_normalized"
    stage2_translated = project_out_root / "stage2_translated"
    stage3_polished = project_out_root / "stage3_polished"

    # 流水线内部使用的临时目录仍放在项目子目录下
    pipeline_root = project_out_root / "_pipeline"
    pilot_input = pipeline_root / "pilot_input"
    pilot_output = pipeline_root / "pilot_output"
    incremental_input = pipeline_root / "incremental_input"
    incremental_output = pipeline_root / "incremental_output"

    # 项目级系统 UI 术语：projects/<project_name>/system_ui_terms.json
    # main.py 在每个 output_dir 下加载同名文件，这里负责在各阶段输出目录之间同步。
    system_terms_src = project_out_root / "system_ui_terms.json"

    def _propagate_system_terms(dst_output_root: Path) -> None:
        """将项目级 system_ui_terms.json 复制到指定输出根目录，供 main.py 使用。"""
        if not system_terms_src.exists():
            return
        try:
            dst_output_root.mkdir(parents=True, exist_ok=True)
            dst_path = dst_output_root / "system_ui_terms.json"
            shutil.copy2(system_terms_src, dst_path)
        except OSError as e:
            # 术语文件复制失败不影响流水线主流程
            logger.debug(f"复制系统术语表失败: {e}")

    if args.clean_output and project_out_root.exists():
        _print(f"[CLEAN] 删除项目输出目录: {project_out_root}")
        shutil.rmtree(project_out_root)

    # 创建基础目录结构
    for d in (
        stage0_raw,
        stage1_normalized,
        stage2_translated,
        stage3_polished,
        pipeline_root,
        pilot_output,
    ):
        d.mkdir(parents=True, exist_ok=True)

    use_tl_mode = getattr(args, "tl_mode", False)
    tl_lang = getattr(args, "tl_lang", "chinese")

    report: dict = {
        "config": {
            "game_dir": str(project_root),
            "scan_root": str(scan_root),
            "provider": args.provider,
            "model": args.model,
            "pilot_count": args.pilot_count,
            "gate_max_untranslated_ratio": args.gate_max_untranslated_ratio,
            "dict": args.dict,
            "exclude": args.exclude,
            "copy_assets": args.copy_assets,
            "target_lang": "zh",  # Round 52 C4: hardcoded zh
            "tl_mode": use_tl_mode,
            "tl_lang": tl_lang if use_tl_mode else None,
        },
        "stages": {},
    }

    if use_tl_mode:
        _run_tl_mode_phase(
            project_root,
            stage2_translated,
            pipeline_root,
            tl_lang,
            args,
            api_key,
            report,
            _propagate_system_terms,
        )
    else:
        # ── direct-mode 流水线（四阶段） ──
        _print("\n=== Stage 1/4: 试跑批次 ===")
        _run_pilot_phase(
            scan_root,
            pilot_input,
            pilot_output,
            stage2_translated,
            pipeline_root,
            args,
            api_key,
            report,
            _propagate_system_terms,
        )

        _print("\n=== Stage 2/4: 全量批处理 ===")
        _run_full_translation_phase(
            project_root,
            scan_root,
            stage2_translated,
            pipeline_root,
            args,
            api_key,
            report,
            _propagate_system_terms,
        )

        _print("\n=== Stage 3/4: 漏翻补翻轮 ===")
        full_translated_root = resolve_scan_root(stage2_translated)
        report["stages"]["retranslate"] = _run_retranslate_phase(
            full_translated_root,
            stage2_translated,
            pipeline_root,
            args,
            api_key,
        )

        _print("\n=== Stage 4/4: 最终自动闸门 ===")

    # ── 共享的最终闸门与报告（direct-mode 和 tl-mode 共用） ──
    ok = _run_final_report(
        scan_root,
        stage2_translated,
        project_out_root,
        pipeline_root,
        pilot_output,
        args,
        report,
        t0,
    )
    if ok:
        _print("[DONE ] 一键流水线执行成功")
        return

    raise StageError("最终闸门未通过，请检查 pipeline_report.json 与 _pipeline 日志")


if __name__ == "__main__":
    try:
        main()
    except StageError as e:
        _print(f"[FAIL ] {e}")
        sys.exit(2)
