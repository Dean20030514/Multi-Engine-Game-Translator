"""Screen text patching — translate extracted entries and rewrite the
``.rpy`` sources in place.

This is the *mutation* half of the screen translator.  It relies on
:mod:`translators._screen_extract` for the data class and the per-line
regexes, and on :mod:`file_processor.checker` / :mod:`file_processor.patcher`
for placeholder handling and string escaping.

Kept as a hidden ``_screen_*`` module so callers continue to import from
``translators.screen`` (round 26 C-1 split).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

# Round 42 M2 phase-3: 50 MB cap on the screen-translator resume JSON.
# Legitimate screen-translator progress files sit in the KB-low-MB range
# (one entry per translated screen string); anything approaching 50 MB
# is either corrupt or a non-progress file accidentally passed in.
# Matches the cap used by r37-r41 user-facing JSON loaders.
_MAX_PROGRESS_JSON_SIZE = 50 * 1024 * 1024


from translators._screen_extract import (
    ScreenTextEntry,
    _RE_TEXT,
    _RE_TEXTBUTTON,
)

from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)


# ── Dedup ───────────────────────────────────────────────────────────


def _deduplicate_entries(
    entries: list[ScreenTextEntry],
) -> tuple[dict[str, str], dict[str, list[ScreenTextEntry]]]:
    """Group entries by original text.

    Returns ``(translation_table, entries_by_text)`` where
    ``translation_table`` maps each unique text to its (initially empty)
    translation, and ``entries_by_text`` maps each unique text to the
    full list of ``ScreenTextEntry`` occurrences so a single translation
    can be fanned out to every source location.
    """
    translation_table: dict[str, str] = {}
    entries_by_text: dict[str, list[ScreenTextEntry]] = {}
    for e in entries:
        if e.original not in entries_by_text:
            entries_by_text[e.original] = []
            translation_table[e.original] = ""
        entries_by_text[e.original].append(e)
    return translation_table, entries_by_text


# ── Prompt / chunking ───────────────────────────────────────────────

SCREEN_TRANSLATE_SYSTEM_PROMPT = """\
你是一名专业的游戏 UI 本地化翻译专家。你将收到从 Ren'Py 游戏 screen 定义中提取的 UI 文本。

## 任务
将每条英文 UI 文本翻译为简体中文。

## 文本特点
这些文本来自游戏界面中的按钮、标签、提示等短字符串。

## 规则
- **每一条都必须翻译**，不得跳过
- `[variable]` 方括号变量原样保留
- `{{color=#xxx}}`, `{{/color}}`, `{{b}}`, `{{/b}}`, `{{size=N}}` 等标签原样保留，只翻译标签包围的文字
- 占位符令牌（如 __RENPY_PH_0__）原样保留
- UI 翻译应简洁精炼，符合游戏界面用语

{glossary_block}

## 输出格式
返回 JSON 数组，每个元素包含 id（编号）、original（原文）、zh（译文）：

```json
[
  {{"id": 1, "original": "Save Game", "zh": "保存游戏"}}
]
```

只返回纯 JSON，不要解释。每条都必须翻译。"""


def _build_screen_user_prompt(chunk_texts: list[str]) -> str:
    """Render the user-side prompt listing all texts in one chunk."""
    lines = []
    for i, text in enumerate(chunk_texts, 1):
        lines.append(f'[{i}] "{text}"')
    return f"请翻译以下 {len(chunk_texts)} 条游戏界面 UI 文本：\n\n" + "\n".join(lines)


def _build_screen_chunks(
    texts: list[str],
    max_per_chunk: int = 40,
) -> list[list[str]]:
    """Slice the unique-text list into translation batches of
    ``max_per_chunk`` items each.
    """
    chunks = []
    for i in range(0, len(texts), max_per_chunk):
        chunks.append(texts[i : i + max_per_chunk])
    return chunks


# ── Translation ─────────────────────────────────────────────────────


def _translate_screen_chunk(
    chunk_texts: list[str],
    client: Any,
    glossary: Any,
    genre: str = "adult",
) -> tuple[dict[str, str], int, list[str]]:
    """Translate one batch of screen texts via the LLM client.

    Returns ``(text_to_translation, dropped_count, warnings)``.  Entries
    that fail placeholder validation are dropped rather than being
    shipped with corrupt escape sequences.
    """
    from file_processor.checker import (
        protect_placeholders,
        restore_placeholders,
        check_response_item,
    )

    result: dict[str, str] = {}
    warnings: list[str] = []
    dropped = 0

    # Placeholder protection: replace ``[var]`` / ``{tag}`` / ``%(name)s``
    # with opaque tokens so the LLM cannot "helpfully" rewrite them.
    protected_texts = []
    mappings = []
    for text in chunk_texts:
        protected, mapping = protect_placeholders(text)
        protected_texts.append(protected)
        mappings.append(mapping)

    glossary_block = ""
    if glossary:
        gt = glossary.to_prompt_text()
        if gt:
            glossary_block = f"## 术语表\n{gt}"

    system_prompt = SCREEN_TRANSLATE_SYSTEM_PROMPT.format(
        glossary_block=glossary_block,
    )
    user_prompt = _build_screen_user_prompt(protected_texts)

    try:
        response = client.translate(system_prompt, user_prompt)
    except Exception as e:
        logger.warning(f"[SCREEN] API 调用失败: {e}")
        return result, len(chunk_texts), warnings

    if not response:
        logger.warning("[SCREEN] API 返回空结果")
        return result, len(chunk_texts), warnings

    # Match each response item back to its source text via id or original.
    for item in response:
        item_id = item.get("id", "")
        original = item.get("original", "")
        zh = item.get("zh", item.get("translation", ""))

        if not zh:
            dropped += 1
            continue

        matched_idx = None
        if isinstance(item_id, int) and 1 <= item_id <= len(chunk_texts):
            matched_idx = item_id - 1
        elif isinstance(item_id, str) and item_id.isdigit():
            idx = int(item_id) - 1
            if 0 <= idx < len(chunk_texts):
                matched_idx = idx

        if matched_idx is None and original:
            for j, pt in enumerate(protected_texts):
                if pt == original or chunk_texts[j] == original:
                    matched_idx = j
                    break

        if matched_idx is None:
            dropped += 1
            continue

        orig_text = chunk_texts[matched_idx]
        mapping = mappings[matched_idx]

        if mapping:
            zh = restore_placeholders(zh, mapping)

        check_item = {"original": orig_text, "zh": zh}
        item_warnings = check_response_item(check_item)
        if item_warnings:
            # Drop entries with placeholder / tag loss.
            has_error = any("E210" in w or "E220" in w or "E230" in w for w in item_warnings)
            if has_error:
                dropped += 1
                warnings.extend(item_warnings)
                continue

        result[orig_text] = zh

    return result, dropped, warnings


# ── Replacement ─────────────────────────────────────────────────────


def _escape_for_screen(text: str) -> str:
    """Escape a translation for safe embedding in a Ren'Py double-quoted
    string.  Delegates to ``file_processor.patcher`` when available.
    """
    try:
        from file_processor.patcher import _escape_for_renpy_string

        return _escape_for_renpy_string(text, '"')
    except ImportError:
        text = text.replace("\\", "\\\\")
        text = text.replace('"', '\\"')
        return text


def _replace_screen_strings_in_file(
    file_path: Path,
    entries: list[ScreenTextEntry],
    translation_table: dict[str, str],
) -> tuple[str, int]:
    """Rewrite the given ``.rpy`` file substituting the translated strings
    for each matched line.

    Returns ``(new_content, replaced_count)``.  Does not write to disk —
    the caller is responsible for persisting ``new_content``.
    """
    try:
        content = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        content = file_path.read_text(encoding="latin-1")

    lines = content.splitlines(keepends=True)
    replaced_count = 0

    entries_by_line: dict[int, list[ScreenTextEntry]] = {}
    for e in entries:
        if e.original in translation_table and translation_table[e.original]:
            entries_by_line.setdefault(e.line_number, []).append(e)

    for line_num, line_entries in entries_by_line.items():
        idx = line_num - 1
        if idx < 0 or idx >= len(lines):
            continue

        line = lines[idx]

        for entry in line_entries:
            zh = translation_table.get(entry.original, "")
            if not zh:
                continue

            escaped_zh = _escape_for_screen(zh)

            if entry.pattern_type == "text":
                new_line, n = _RE_TEXT.subn(
                    lambda m, ez=escaped_zh: m.group(1) + '"' + ez + '"',
                    line,
                    count=1,
                )
                if n > 0:
                    line = new_line
                    replaced_count += 1

            elif entry.pattern_type == "textbutton":
                new_line, n = _RE_TEXTBUTTON.subn(
                    lambda m, ez=escaped_zh: m.group(1) + '"' + ez + '"',
                    line,
                    count=1,
                )
                if n > 0:
                    line = new_line
                    replaced_count += 1

            elif entry.pattern_type in ("tt_action", "notify"):
                # Multiple tt.Action / Notify may appear on one line —
                # build a per-entry pattern anchored on the original text
                # so we only swap the intended occurrence.
                orig_escaped = re.escape(entry.original)
                func_name = r"tt\.Action" if entry.pattern_type == "tt_action" else r"Notify"
                pattern = re.compile(r"(" + func_name + r'\s*\(\s*)"' + orig_escaped + r'"(\s*\))')
                new_line, n = pattern.subn(
                    lambda m, ez=escaped_zh: m.group(1) + '"' + ez + '"' + m.group(2),
                    line,
                    count=1,
                )
                if n > 0:
                    line = new_line
                    replaced_count += 1

        lines[idx] = line

    return "".join(lines), replaced_count


# ── Progress persistence ────────────────────────────────────────────


def _load_progress(progress_path: Path) -> dict:
    """Load the screen-translator resume file, tolerating corruption."""
    if progress_path.is_file():
        try:
            size = progress_path.stat().st_size
        except OSError:
            size = 0
        if size > _MAX_PROGRESS_JSON_SIZE:
            logger.warning(
                f"[SCREEN] 进度文件 {progress_path} 过大 "
                f"({size} > {_MAX_PROGRESS_JSON_SIZE})，视为损坏重置"
            )
            return {"completed_texts": {}, "completed_chunks": [], "stats": {}}
        try:
            # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
            with open(progress_path, encoding="utf-8") as f:
                ok, fsize2 = check_fstat_size(f, _MAX_PROGRESS_JSON_SIZE)
                if not ok:
                    logger.warning(
                        f"[SCREEN] 进度文件 {progress_path} stat 后增长到 "
                        f"{fsize2} 字节（疑似 TOCTOU 攻击），视为损坏重置"
                    )
                    return {"completed_texts": {}, "completed_chunks": [], "stats": {}}
                data = json.loads(f.read())
            if isinstance(data, dict):
                data.setdefault("completed_texts", {})
                data.setdefault("completed_chunks", [])
                data.setdefault("stats", {})
                return data
        except (json.JSONDecodeError, OSError):
            logger.warning("[SCREEN] 进度文件损坏，已重置")
    return {"completed_texts": {}, "completed_chunks": [], "stats": {}}


def _save_progress(progress_path: Path, progress: dict) -> None:
    """Persist progress atomically via a sibling .tmp file."""
    tmp_path = progress_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(progress, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        shutil.move(str(tmp_path), str(progress_path))
    except OSError as e:
        logger.warning(f"[SCREEN] 保存进度失败: {e}")


# ── Backup ──────────────────────────────────────────────────────────


def _create_backup(file_path: Path) -> None:
    """Create a ``.bak`` copy if one does not already exist.

    Subsequent calls on the same path are no-ops — the first backup wins
    so the user's pristine original is preserved across repeated runs.
    """
    bak = file_path.with_suffix(file_path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(str(file_path), str(bak))
        logger.debug(f"[SCREEN] 备份: {bak.name}")
