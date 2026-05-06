"""Screen text translator — 翻译 Ren'Py screen 定义中的裸英文字符串。

Ren'Py 的 Generate Translations 只提取 Say 对话和 _() 包裹的字符串，
screen 内的裸 text/textbutton/tt.Action 不会被 tl 框架覆盖。
本模块直接修改源 .rpy 文件中的英文字符串为中文。

用法:
    python main.py --game-dir /path/to/game --tl-screen --provider xai --api-key KEY
    python main.py --game-dir /path/to/game --tl-mode --tl-screen  # tl-mode 后自动补充

Module layout (round 26 A-H-4 补 — split into three modules so each is
under the 800-line soft cap):

    translators/screen.py            entry + orchestration + self-tests
    translators/_screen_extract.py   scan + identify + skip logic
    translators/_screen_patch.py     chunk + translate + replace + progress

Public API here is unchanged; ``ScreenTextEntry`` / ``extract_screen_strings``
/ ``_deduplicate_entries`` / ``_replace_screen_strings_in_file`` /
``_build_screen_chunks`` / ``_should_skip`` / ``_line_has_underscore_wrap`` /
``_create_backup`` / ``scan_screen_files`` / ``run_screen_translate`` all
remain importable from ``translators.screen``.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from translators._screen_extract import (
    ScreenTextEntry,
    _line_has_underscore_wrap,
    _should_skip,
    extract_screen_strings,
    scan_screen_files,
)
from translators._screen_patch import (
    SCREEN_TRANSLATE_SYSTEM_PROMPT,
    _build_screen_chunks,
    _build_screen_user_prompt,
    _create_backup,
    _deduplicate_entries,
    _escape_for_screen,
    _load_progress,
    _replace_screen_strings_in_file,
    _save_progress,
    _translate_screen_chunk,
)

# Public re-exports for backward compatibility — every symbol that used to
# live directly in this file remains importable from ``translators.screen``.
__all__ = [
    "ScreenTextEntry",
    "SCREEN_TRANSLATE_SYSTEM_PROMPT",
    "extract_screen_strings",
    "scan_screen_files",
    "run_screen_translate",
    "_build_screen_chunks",
    "_build_screen_user_prompt",
    "_create_backup",
    "_deduplicate_entries",
    "_escape_for_screen",
    "_line_has_underscore_wrap",
    "_load_progress",
    "_replace_screen_strings_in_file",
    "_save_progress",
    "_should_skip",
    "_translate_screen_chunk",
]

logger = logging.getLogger(__name__)


# ── Main orchestration ──────────────────────────────────────────────


def run_screen_translate(args: argparse.Namespace) -> None:
    """Screen 文本翻译主入口。"""
    from core.api_client import APIClient, APIConfig
    from core.glossary import Glossary

    start_time = time.time()
    game_dir = Path(args.game_dir)

    # 智能检测 game 子目录
    if (game_dir / "game").exists():
        scan_dir = game_dir / "game"
    else:
        scan_dir = game_dir

    logger.info("\n" + "=" * 60)
    logger.info("Screen 文本翻译")
    logger.info("=" * 60)

    # ── 1. 扫描 ──
    rpy_files = scan_screen_files(scan_dir)
    logger.info(f"[SCREEN] 扫描到 {len(rpy_files)} 个 .rpy 文件")

    # ── 2. 提取 ──
    all_entries: list[ScreenTextEntry] = []
    for rpy in rpy_files:
        entries = extract_screen_strings(rpy)
        all_entries.extend(entries)

    if not all_entries:
        logger.info("[SCREEN] 未发现需要翻译的 screen 文本")
        return

    # ── 3. 去重 ──
    translation_table, entries_by_text = _deduplicate_entries(all_entries)

    n_total = len(all_entries)
    n_unique = len(translation_table)
    n_files = len({e.file_path for e in all_entries})
    logger.info(f"[SCREEN] 提取 {n_total} 条文本（{n_unique} 种不重复），涉及 {n_files} 个文件")

    # dry-run 模式
    if getattr(args, "dry_run", False):
        logger.info(f"\n[SCREEN] Dry-run 模式：发现 {n_unique} 种不重复 screen 文本")
        logger.info(f"[SCREEN] 预估 API 请求：{(n_unique + 39) // 40} 次")
        type_counts: dict[str, int] = {}
        for e in all_entries:
            type_counts[e.pattern_type] = type_counts.get(e.pattern_type, 0) + 1
        for ptype, count in sorted(type_counts.items()):
            logger.info(f"  {ptype}: {count} 条")
        return

    # ── 4. 加载进度 ──
    output_dir = Path(getattr(args, "output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "screen_translate_progress.json"
    progress = _load_progress(progress_path)

    # 恢复已翻译的文本
    completed = progress["completed_texts"]
    for text, zh in completed.items():
        if text in translation_table:
            translation_table[text] = zh

    remaining = [t for t, zh in translation_table.items() if not zh]
    if not remaining:
        logger.info(f"[SCREEN] 所有 {n_unique} 条文本已翻译，直接执行替换")
    else:
        logger.info(f"[SCREEN] 待翻译: {len(remaining)} / {n_unique}")

        if not getattr(args, "api_key", ""):
            logger.error("[SCREEN] 非 dry-run 模式必须提供 --api-key")
            return

        # ── 5. 翻译 ──
        api_config = APIConfig(
            provider=args.provider,
            model=getattr(args, "model", "") or "",
            api_key=args.api_key,
            rpm=getattr(args, "rpm", 60),
            rps=getattr(args, "rps", 5),
            timeout=getattr(args, "timeout", 180.0),
            temperature=getattr(args, "temperature", 0.1),
            max_response_tokens=getattr(args, "max_response_tokens", 32768),
            custom_module=getattr(args, "custom_module", ""),
        )
        client = APIClient(api_config)

        glossary = Glossary()
        dict_files = getattr(args, "dict", []) or []
        if isinstance(dict_files, str):
            dict_files = [dict_files]
        for d in dict_files:
            if Path(d).is_file():
                glossary.load_dict(d)

        chunks = _build_screen_chunks(remaining)
        total_dropped = 0
        all_warnings: list[str] = []

        for ci, chunk in enumerate(chunks):
            if ci in progress.get("completed_chunks", []):
                continue

            logger.info(f"[SCREEN] 翻译 chunk {ci + 1}/{len(chunks)}（{len(chunk)} 条）")

            translations, dropped, warnings = _translate_screen_chunk(
                chunk,
                client,
                glossary,
                genre=getattr(args, "genre", "adult"),
            )
            total_dropped += dropped
            all_warnings.extend(warnings)

            for text, zh in translations.items():
                translation_table[text] = zh
                completed[text] = zh

            progress["completed_chunks"].append(ci)
            progress["completed_texts"] = completed
            progress["stats"] = {
                "total_unique": n_unique,
                "translated": sum(1 for v in translation_table.values() if v),
            }
            _save_progress(progress_path, progress)

        logger.info(
            f"[SCREEN] 翻译完成: "
            f"{sum(1 for v in translation_table.values() if v)}/{n_unique} "
            f"已翻译, {total_dropped} 丢弃"
        )
        if all_warnings:
            logger.info(f"[SCREEN] {len(all_warnings)} 条警告")

        logger.info(f"[SCREEN] {client.usage.summary()}")

    # ── 6. 替换 ──
    translated = {t: zh for t, zh in translation_table.items() if zh}
    if not translated:
        logger.warning("[SCREEN] 无可用翻译，跳过替换")
        return

    files_to_patch: dict[str, list[ScreenTextEntry]] = {}
    for text, entry_list in entries_by_text.items():
        if text in translated:
            for e in entry_list:
                files_to_patch.setdefault(e.file_path, []).append(e)

    total_replaced = 0
    files_modified = 0
    for file_path_str, file_entries in sorted(files_to_patch.items()):
        fpath = Path(file_path_str)

        _create_backup(fpath)

        new_content, replaced = _replace_screen_strings_in_file(
            fpath,
            file_entries,
            translated,
        )
        if replaced > 0:
            fpath.write_text(new_content, encoding="utf-8")
            total_replaced += replaced
            files_modified += 1
            logger.debug(f"[SCREEN] {fpath.name}: {replaced} 处替换")

    # ── 7. 报告 ──
    elapsed = time.time() - start_time
    logger.info(
        f"\n[SCREEN] 完成: {total_replaced} 处替换, "
        f"{files_modified} 个文件修改, 耗时 {elapsed:.1f}s"
    )
    logger.info(
        "[SCREEN] 注意: screen 翻译直接修改了源文件（已创建 .bak 备份）。"
        "游戏更新后需重新执行 --tl-screen。"
    )


# ── Self-tests ──────────────────────────────────────────────────────


def _run_self_tests() -> None:
    """Screen translator self-tests — run via ``python -m translators.screen``."""
    import tempfile

    passed = 0

    # T1: _should_skip
    assert _should_skip("") is True
    assert _should_skip("[var]") is True
    assert _should_skip("[mother]") is True
    assert _should_skip("123") is True
    assert _should_skip("...") is True
    assert _should_skip("已保存") is True
    assert _should_skip("images/bg.png") is True
    assert _should_skip("a") is True
    assert _should_skip("Save Game") is False
    assert _should_skip("NTR: undecided") is False
    assert _should_skip("{color=#f00}Warning{/color}") is False
    assert _should_skip("[name] is here") is False
    assert _should_skip("{size=-10}- You can find work at the tanning salon.{/size}") is False
    assert _should_skip("{size=-10}when you're a gangmember.{/size}") is False
    assert _should_skip("icons/bg.png") is True
    passed += 15
    logger.info(f"[OK] _should_skip: {passed} assertions")

    # T2: _line_has_underscore_wrap
    assert _line_has_underscore_wrap('        textbutton _("Back") action Rollback()') is True
    assert _line_has_underscore_wrap('        text "Hello"') is False
    assert _line_has_underscore_wrap('        textbutton "Start" action Start()') is False
    passed += 3
    logger.info(f"[OK] _line_has_underscore_wrap: {passed} assertions")

    # T3: extract_screen_strings
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".rpy",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write("""
screen contacts():
    vbox:
        text "Mom"
        text "[var]"
        textbutton "Start Game" action Start()
        textbutton _("Back") action Rollback()
        imagebutton auto "icon.png" hovered tt.Action("Go closer") focus_mask True
        imagebutton auto "icon2.png" action Jump("x") hovered Notify("Help needed") focus_mask True
        text "{color=#f00}Warning{/color}"

label start:
    text "Not in screen"
    "Hello"
""")
        f.flush()
        tmp_path = Path(f.name)

    try:
        entries = extract_screen_strings(tmp_path)
        originals = [e.original for e in entries]
        assert "Mom" in originals, f"Missing 'Mom', got {originals}"
        assert "Start Game" in originals, f"Missing 'Start Game', got {originals}"
        assert "Go closer" in originals, f"Missing 'Go closer', got {originals}"
        assert "Help needed" in originals, f"Missing 'Help needed', got {originals}"
        assert "{color=#f00}Warning{/color}" in originals
        assert "[var]" not in originals, "[var] should be skipped"
        assert "Back" not in originals, "_('Back') should be skipped"
        assert "Not in screen" not in originals, "text outside screen should be skipped"

        type_map = {e.original: e.pattern_type for e in entries}
        assert type_map["Mom"] == "text"
        assert type_map["Start Game"] == "textbutton"
        assert type_map["Go closer"] == "tt_action"
        assert type_map["Help needed"] == "notify"
        passed += 12
        logger.info(f"[OK] extract_screen_strings: {passed} assertions")
    finally:
        os.unlink(tmp_path)

    # T4: _deduplicate_entries
    e1 = ScreenTextEntry("a.rpy", 1, "text", "Hello")
    e2 = ScreenTextEntry("b.rpy", 5, "text", "Hello")
    e3 = ScreenTextEntry("a.rpy", 3, "text", "World")
    table, by_text = _deduplicate_entries([e1, e2, e3])
    assert len(table) == 2
    assert len(by_text["Hello"]) == 2
    assert len(by_text["World"]) == 1
    passed += 3
    logger.info(f"[OK] _deduplicate_entries: {passed} assertions")

    # T5: _replace_screen_strings_in_file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".rpy",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write('    text "Save Game"\n')
        f.write('    textbutton "Start" action Start() style "btn"\n')
        f.write('    imagebutton hovered tt.Action("Go closer") focus_mask True\n')
        f.write('    text "{color=#f00}Warning{/color}"\n')
        f.flush()
        tmp_path = Path(f.name)

    try:
        test_entries = [
            ScreenTextEntry(str(tmp_path), 1, "text", "Save Game"),
            ScreenTextEntry(str(tmp_path), 2, "textbutton", "Start"),
            ScreenTextEntry(str(tmp_path), 3, "tt_action", "Go closer"),
            ScreenTextEntry(str(tmp_path), 4, "text", "{color=#f00}Warning{/color}"),
        ]
        test_table = {
            "Save Game": "保存游戏",
            "Start": "开始",
            "Go closer": "靠近",
            "{color=#f00}Warning{/color}": "{color=#f00}警告{/color}",
        }
        new_content, count = _replace_screen_strings_in_file(
            tmp_path,
            test_entries,
            test_table,
        )
        assert count == 4, f"Expected 4 replacements, got {count}"
        assert '"保存游戏"' in new_content
        assert '"开始"' in new_content
        assert 'style "btn"' in new_content
        assert '"靠近"' in new_content
        assert "{color=#f00}警告{/color}" in new_content
        passed += 5
        logger.info(f"[OK] _replace_screen_strings_in_file: {passed} assertions")
    finally:
        os.unlink(tmp_path)

    # T6: backup
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".rpy",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write("test content\n")
        f.flush()
        tmp_path = Path(f.name)
    try:
        bak_path = tmp_path.with_suffix(tmp_path.suffix + ".bak")
        assert not bak_path.exists()
        _create_backup(tmp_path)
        assert bak_path.exists()
        bak_path.write_text("old backup", encoding="utf-8")
        _create_backup(tmp_path)
        assert bak_path.read_text(encoding="utf-8") == "old backup"
        passed += 3
        logger.info(f"[OK] _create_backup: {passed} assertions")
    finally:
        os.unlink(tmp_path)
        if bak_path.exists():
            os.unlink(bak_path)

    # T7: _build_screen_chunks
    texts = [f"text_{i}" for i in range(100)]
    chunks = _build_screen_chunks(texts, max_per_chunk=40)
    assert len(chunks) == 3
    assert len(chunks[0]) == 40
    assert len(chunks[2]) == 20
    passed += 3
    logger.info(f"[OK] _build_screen_chunks: {passed} assertions")

    # T8: Notify replacement
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".rpy",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write('    imagebutton action Jump("x") hovered Notify("Help needed") focus_mask True\n')
        f.flush()
        tmp_path = Path(f.name)
    try:
        test_entries_notify = [
            ScreenTextEntry(str(tmp_path), 1, "notify", "Help needed"),
        ]
        test_table_notify = {"Help needed": "需要帮助"}
        new_content, count = _replace_screen_strings_in_file(
            tmp_path,
            test_entries_notify,
            test_table_notify,
        )
        assert count == 1
        assert '"需要帮助"' in new_content
        assert "Notify" in new_content
        assert 'Jump("x")' in new_content
        passed += 4
        logger.info(f"[OK] Notify replacement: {passed} assertions")
    finally:
        os.unlink(tmp_path)

    # T9: multiple tt.Action on same line
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".rpy",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(
            '    imagebutton hovered tt.Action("Open") xpos 100 '
            'hovered tt.Action("Close") focus_mask True\n'
        )
        f.flush()
        tmp_path = Path(f.name)
    try:
        test_entries_multi = [
            ScreenTextEntry(str(tmp_path), 1, "tt_action", "Open"),
            ScreenTextEntry(str(tmp_path), 1, "tt_action", "Close"),
        ]
        test_table_multi = {"Open": "打开", "Close": "关闭"}
        new_content, count = _replace_screen_strings_in_file(
            tmp_path,
            test_entries_multi,
            test_table_multi,
        )
        assert '"打开"' in new_content
        assert '"关闭"' in new_content
        assert count == 2
        passed += 3
        logger.info(f"[OK] multi tt.Action replacement: {passed} assertions")
    finally:
        os.unlink(tmp_path)

    logger.info(f"\n{'=' * 40}")
    logger.info(f"ALL {passed} SCREEN TRANSLATOR TESTS PASSED")
    logger.info(f"{'=' * 40}")


if __name__ == "__main__":
    _run_self_tests()
