#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Placeholder protection & response checking."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Optional, Union

from safety.file_safety import check_fstat_size

logger = logging.getLogger(__name__)


# 纯配置/UI 文件——不包含用户可见对话，翻译和漏翻统计均应跳过。
# 文件名匹配（不含路径），按项目需要可追加。
SKIP_FILES_FOR_TRANSLATION = {
    "define.rpy",
    "variables.rpy",
    "screens.rpy",
    "earlyoptions.rpy",
    "options.rpy",
}


# ============================================================
# 可配置的风格/质量检测关键词
# ============================================================

# 模型自我描述或多余解释的典型片段（可根据需要扩充）
MODEL_SPEAKING_PATTERNS = [
    "作为一个ai语言模型",
    "作为一名ai语言模型",
    "作为一个语言模型",
    "as an ai language model",
    "i am an ai language model",
    "i am a large language model",
    "as a language model",
]

# 占位符顺序校验用 pattern：从左到右依次匹配，用于提取有序占位符序列
# 格式 (regex, category_name)；匹配顺序影响提取结果（更具体的模式应靠前，如 {#id} 在通用 {tag} 前）
# 'tag' 模式同时覆盖样式标签（{color=...}/{b}/{i} 等）和控制标签（{w}/{p}/{nw}/{fast}/{cps=N}/{done} 等）
PLACEHOLDER_ORDER_PATTERNS = [
    (r'\[\w+\]', 'var'),
    (r'\{#[^}]+\}', 'menu_id'),
    (r'\{/?[a-zA-Z]+=?[^}]*\}', 'tag'),
    (r'%\([^)]+\)[sd]', 'fmt'),
]

# 预编译为单一正则，按"最早出现"的匹配从左到右收集（用于 _extract_placeholder_sequence）
_PLACEHOLDER_ORDER_REGEX = re.compile(
    '|'.join(f'({p})' for p, _ in PLACEHOLDER_ORDER_PATTERNS)
)


def _extract_placeholder_sequence(text: str,
                                  regex: "re.Pattern | None" = None) -> list[str]:
    """按从左到右顺序提取文本中的占位符序列，用于顺序一致性校验。

    使用 PLACEHOLDER_ORDER_PATTERNS 对应的联合正则，finditer 保证出现顺序。
    例如：'{color=#f00}[name]{/color}' -> ['{color=#f00}', '[name]', '{/color}']

    Args:
        regex: 自定义占位符正则。None 时使用默认 Ren'Py 模式。
    """
    r = regex or _PLACEHOLDER_ORDER_REGEX
    out: list[str] = []
    for m in r.finditer(text):
        # 取第一个非空分组即为当前匹配的占位符
        for g in m.groups():
            if g is not None:
                out.append(g)
                break
    return out


# 占位符保护：发 API 前将 [var]、{{#id}}、%(name)s 等替换为令牌，避免模型误翻；解析后还原
_PLACEHOLDER_PROTECT_PREFIX = "__RENPY_PH_"
_PLACEHOLDER_PROTECT_SUFFIX = "__"


_placeholder_cache: dict[int, tuple[str, list[tuple[str, str]]]] = {}


def clear_placeholder_cache() -> None:
    """Clear the placeholder cache (useful for testing)."""
    _placeholder_cache.clear()


def protect_placeholders(text: str,
                         patterns: "list[str] | None" = None,
                         ) -> tuple[str, list[tuple[str, str]]]:
    """将文本中的占位符替换为唯一令牌，供发往 API 时使用。

    使用与 PLACEHOLDER_ORDER_PATTERNS 相同的模式提取占位符，按首次出现顺序去重后，
    对同一占位符的每一次出现均替换（全局替换）。例如 "[name] says hi to [name]" 中
    两个 [name] 都会变为 __RENPY_PH_0__。

    Args:
        patterns: 自定义占位符正则列表（从 EngineProfile.placeholder_patterns 传入）。
            None 时使用默认 Ren'Py 模式，保持向后兼容。
    Returns:
        (替换后的文本, mapping: [(token, original), ...])
    """
    # Cache lookup — only for default patterns (patterns is None)
    if patterns is None:
        cache_key = hash(text)
        cached = _placeholder_cache.get(cache_key)
        if cached is not None:
            return cached

    _use_cache = patterns is None

    if not text.strip():
        rv = text, []
        if _use_cache:
            _placeholder_cache[cache_key] = rv
        return rv
    # 选择占位符正则：自定义模式 or 默认 Ren'Py 模式
    if patterns is not None:
        regex = re.compile("|".join(f"({p})" for p in patterns)) if patterns else None
        if regex is None:
            return text, []
    else:
        regex = _PLACEHOLDER_ORDER_REGEX
    matches: list[tuple[int, int, str]] = []
    for m in regex.finditer(text):
        for g in m.groups():
            if g is not None:
                matches.append((m.start(), m.end(), g))
                break
    if not matches:
        rv = text, []
        if _use_cache:
            _placeholder_cache[cache_key] = rv
        return rv
    # 按首次出现顺序去重
    ordered: list[str] = []
    seen: set[str] = set()
    for _s, _e, matched in matches:
        if matched not in seen:
            seen.add(matched)
            ordered.append(matched)
    mapping = [
        (f"{_PLACEHOLDER_PROTECT_PREFIX}{i}{_PLACEHOLDER_PROTECT_SUFFIX}", orig)
        for i, orig in enumerate(ordered)
    ]
    orig_to_token = {orig: token for token, orig in mapping}
    # 从后往前替换，避免偏移变化
    replacements = [
        (s, e, orig_to_token[m]) for s, e, m in matches
    ]
    replacements.sort(key=lambda x: x[0], reverse=True)
    result = text
    for start, end, token in replacements:
        result = result[:start] + token + result[end:]
    rv = result, mapping
    if _use_cache:
        _placeholder_cache[cache_key] = rv
    return rv


def restore_placeholders(text: str, mapping: list[tuple[str, str]]) -> str:
    """将保护阶段生成的令牌还原为原始占位符。

    Args:
        text: 可能包含 __RENPY_PH_0__ 等令牌的字符串
        mapping: protect_placeholders 返回的 [(token, original), ...]
    """
    if not mapping or not text:
        return text
    for token, original in mapping:
        text = text.replace(token, original)
    return text


# ---------------------------------------------------------------------------
# 锁定术语预替换 — 翻译前将 locked_terms 替换为令牌，翻译后还原为中文译名
# 作为 prompt 注入的补充保险：即使 LLM 忽略术语表指令，译名也会被正确插入。
# ---------------------------------------------------------------------------

_LOCKED_TERM_PREFIX = "__LOCKED_TERM_"
_LOCKED_TERM_SUFFIX = "__"


def protect_locked_terms(
    text: str,
    locked_terms: "dict[str, str]",
) -> tuple[str, list[tuple[str, str]]]:
    """将 locked_terms 中的源语言术语替换为唯一令牌。

    使用词边界 ``\\b`` 匹配，避免部分命中（如 "Game" 不匹配 "GameOver"）。

    Args:
        text: 已经过 protect_placeholders() 处理的文本。
        locked_terms: ``{英文术语: 中文译名}`` 字典。仅处理两者均非空的条目。

    Returns:
        (替换后的文本, mapping: [(token, 中文译名), ...])
        注意：与 protect_placeholders 不同，这里 mapping 的第二个元素是**中文译名**
        而不是原始文本，因为 restore 时需要插入译名而非还原原文。
    """
    if not locked_terms or not text:
        return text, []

    mapping: list[tuple[str, str]] = []
    idx = 0

    # 按术语长度降序排列，优先匹配较长术语（避免 "New York" 被 "New" 先匹配）
    for en_term, zh_term in sorted(locked_terms.items(), key=lambda kv: -len(kv[0])):
        if not en_term or not zh_term:
            continue
        escaped = re.escape(en_term)
        # 智能词边界：仅在术语首/尾是"词字符"(\w) 时添加 \b，
        # 避免 "C++" 等含特殊字符的术语匹配失败。
        prefix = r"\b" if en_term[0].isalnum() or en_term[0] == "_" else ""
        suffix = r"\b" if en_term[-1].isalnum() or en_term[-1] == "_" else ""
        pattern = re.compile(prefix + escaped + suffix)
        if pattern.search(text):
            token = f"{_LOCKED_TERM_PREFIX}{idx}{_LOCKED_TERM_SUFFIX}"
            text = pattern.sub(token, text)
            mapping.append((token, zh_term))
            idx += 1

    return text, mapping


def restore_locked_terms(text: str, mapping: list[tuple[str, str]]) -> str:
    """将锁定术语令牌替换为中文译名。

    Args:
        text: 可能包含 __LOCKED_TERM_N__ 令牌的字符串。
        mapping: protect_locked_terms 返回的 [(token, 中文译名), ...]。
    """
    if not mapping or not text:
        return text
    for token, zh_term in mapping:
        text = text.replace(token, zh_term)
    return text


def _count_translatable_lines_in_chunk(content: str) -> int:
    """启发式统计 chunk 中「可能需翻译」的行数。

    排除规则：
      - 注释行、空行
      - 不含双引号的行
      - 已包含中文字符的行（视为已翻译，不计入 expected）
    """
    count = 0
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if '"' not in s:
            continue
        if any("\u4e00" <= c <= "\u9fff" for c in s):
            continue
        count += 1
    return count


def check_response_chunk(chunk_content: str, translations: list[dict]) -> list[str]:
    """Chunk 级 ResponseChecker：API 返回条数与 chunk 内可翻译行数是否一致。

    Returns:
        警告信息列表；若条数不一致则包含一条 [CHECK] 级警告及差值说明。
    """
    warnings: list[str] = []
    expected = _count_translatable_lines_in_chunk(chunk_content)
    actual = len(translations)
    if expected != actual:
        delta = actual - expected
        warnings.append(
            f"chunk 条数不一致: 预期约 {expected} 条（按含引号行估算）, 实际返回 {actual} 条, 差值 {delta:+d}"
        )
    return warnings


def check_response_item(item: dict, line_offset: int = 0,
                        placeholder_re: "re.Pattern | None" = None) -> list[str]:
    """轻量 ResponseChecker：对单条 API 返回的翻译做本地校验，不调 API。

    检查：原文非空时译文非空、占位符集合一致、必要字段存在。
    任一不通过则返回非空列表，调用方应丢弃该条（不写入译文，保留原文计漏翻）。

    Round 52 C4 BREAKING: lang_config kwarg retired (zh-only). Translation
    field hard-coded to ``item["zh"]``.

    Args:
        placeholder_re: 自定义占位符正则。None 时使用默认 Ren'Py 模式。
    Returns:
        警告信息列表，空表示通过。
    """
    warnings: list[str] = []
    line = item.get("line", 0) or 0
    if line_offset:
        line = line + line_offset
    original = (item.get("original") or "").strip()
    zh = (item.get("zh") or "").strip()

    if not original:
        warnings.append(f"行 {line}: original 为空")
        return warnings
    # 原文非空但译文为空 -> 丢弃该条，计漏翻
    if not zh:
        warnings.append(f"行 {line}: 译文为空")
        return warnings
    orig_placeholders = set(_extract_placeholder_sequence(original, regex=placeholder_re))
    zh_placeholders = set(_extract_placeholder_sequence(zh, regex=placeholder_re))
    if orig_placeholders != zh_placeholders:
        missing = orig_placeholders - zh_placeholders
        extra = zh_placeholders - orig_placeholders
        parts = []
        if missing:
            parts.append(f"译文缺少占位符 {missing}")
        if extra:
            parts.append(f"译文多出占位符 {extra}")
        warnings.append(f"行 {line}: 占位符与原文不一致 — {'; '.join(parts)}")
    return warnings


# ============================================================
# Bulk response post-processing (round 27 A-H-2 — pushed down from
# ``core/translation_utils.py`` to eliminate the core → file_processor
# reverse dependency).  These wrappers operate on lists of response
# dicts ``{"line", "original", "zh", ...}`` and belong next to the
# single-item primitives they delegate to.
# ============================================================

def _filter_checked_translations(
    translations: list[dict],
    line_offset: int = 0,
) -> tuple[list[dict], int, list[dict], list[str]]:
    """Run ``check_response_item`` on each translation dict and split the
    input into kept / dropped / warnings.

    Round 31 Tier A-2: before invoking the checker, apply
    ``fix_chinese_placeholder_drift`` in-place across every entry so a
    translation that would otherwise be dropped solely due to an AI-
    introduced ``[姓名]`` → ``[name]`` drift can be salvaged.  The fix
    is idempotent and side-effect-free when no drift exists.

    Round 52 C4 BREAKING: lang_config kwarg retired (zh-only).

    Returns ``(kept, dropped_count, dropped_items, warnings)``.  Empty
    results are returned when ``translations`` is empty — callers never
    need to guard against ``None``.
    """
    kept: list[dict] = []
    dropped_items: list[dict] = []
    dropped_count = 0
    warnings: list[str] = []
    for t in translations:
        # Normalise Chinese placeholder drift BEFORE the placeholder-set
        # comparison inside ``check_response_item`` runs, so fixable
        # drift doesn't cost us an otherwise-valid translation.
        for key in ("original", "zh"):
            val = t.get(key)
            if val:
                fixed = fix_chinese_placeholder_drift(val)
                if fixed != val:
                    t[key] = fixed
        item_warnings = check_response_item(t, line_offset=line_offset)
        if item_warnings:
            dropped_count += 1
            dropped_items.append(t)
            for w in item_warnings:
                warnings.append(f"[CHECK-DROPPED] {w}")
        else:
            kept.append(t)
    return kept, dropped_count, dropped_items, warnings


def _restore_placeholders_in_translations(
    translations: list[dict],
    ph_mapping: list[tuple[str, str]],
    extra_keys: tuple[str, ...] = (),
) -> None:
    """In-place: restore ``[var]`` / ``{tag}`` placeholders across every
    translation dict's ``original`` / ``zh`` fields (plus any ``extra_keys``
    the caller names — e.g. ``id`` for tl-mode).
    """
    keys = ("original", "zh") + extra_keys
    for t in translations:
        for key in keys:
            val = t.get(key)
            if val:
                t[key] = restore_placeholders(val, ph_mapping)


def _restore_locked_terms_in_translations(
    translations: list[dict],
    lt_mapping: list[tuple[str, str]],
    extra_keys: tuple[str, ...] = (),
) -> None:
    """In-place: restore locked-term tokens (``__LOCKED_0__`` etc.) back
    to their translated forms across every translation dict's fields.

    Both ``original`` and ``zh`` are processed so downstream validators
    see the post-restore text and don't flag the token itself as a
    placeholder mismatch.
    """
    keys = ("original", "zh") + extra_keys
    for t in translations:
        for key in keys:
            val = t.get(key)
            if val:
                t[key] = restore_locked_terms(val, lt_mapping)


# ============================================================
# Round 31 Tier A-1: Common UI button whitelist
# Ported from `renpy_hook_template_py3.rpy::_youling_is_sensitive_ui_text`.
# When a translation looks like a standard UI button (OK / Cancel / Save / etc.),
# translators often force Chinese ("保存") where the game's screen layout was
# designed around the English string; this warning gives the user a chance to
# notice.  Strict-Stdlib: just a frozenset + one normalisation function.
# ============================================================

COMMON_UI_BUTTONS: frozenset[str] = frozenset({
    "yes", "no", "ok", "cancel", "quit", "return", "exit",
    "back", "next", "skip", "continue", "retry",
    "start", "load", "save", "delete", "new game",
    "main menu", "menu", "preferences", "prefs", "options",
    "settings", "about", "help", "credits",
    "auto", "history", "rollback",
    "confirm", "close", "done", "apply", "reset",
    "on", "off", "enable", "disable",
})


def _normalise_ui_button(text: str) -> str:
    """Lower-case + collapse-whitespace rule shared by ``is_common_ui_button``
    and the ``add_ui_button_whitelist`` loader so lookups and inserts stay
    aligned.  Returns an empty string for non-strings or all-whitespace input.

    ASCII-dominant by design — case fold + whitespace collapse only.  Does
    NOT apply Unicode NFC/NFD/NFKC/NFKD normalisation: precomposed ``é``
    (U+00E9) and decomposed ``é`` (U+0065 + U+0301) remain distinct tokens.
    Rationale: the whitelist is overwhelmingly ASCII Ren'Py button labels
    (Save / Load / Quit / ...) plus operator-supplied CJK extensions like
    ``存档`` / ``读档`` where NFC/NFD has no meaningful effect on the hot
    path.  Cross-script fuzzy matching is the job of
    ``core.lang_config.resolve_translation_field`` via
    ``lang_config.field_aliases`` (round 39+), not this normaliser.
    Operators needing NFC/NFD interop must pre-normalise their input
    before calling ``add_ui_button_whitelist``.  This design choice is
    documented as the round 48 audit LOW Coverage closure (round 49 Step 1).
    """
    if not isinstance(text, str):
        return ""
    return " ".join(text.strip().lower().split())


def is_common_ui_button(text: str) -> bool:
    """Return True if ``text`` looks like a standard Ren'Py UI button whose
    English string is often wired to screen layout / hotkeys.

    Normalises case + whitespace before the lookup, then checks both the
    immutable ``COMMON_UI_BUTTONS`` baseline and the runtime-configurable
    ``_ui_button_extensions`` set populated by ``load_ui_button_whitelist``.
    Not intended to be an exhaustive classifier — just a fast "smells like
    a button" hint.
    """
    normalised = _normalise_ui_button(text)
    if not normalised:
        return False
    return normalised in COMMON_UI_BUTTONS or normalised in _ui_button_extensions


# ============================================================
# Round 32 Commit 2: runtime-configurable UI-button whitelist extensions.
# ``COMMON_UI_BUTTONS`` above is the immutable baseline copied byte-for-byte
# from the competitor hook's curated list.  Operators can layer project-
# specific tokens (e.g. Chinese ``存档`` / ``读档``) on top via the
# ``--ui-button-whitelist`` CLI flag or the ``ui_button_whitelist`` config
# key, and those extensions are mirrored to hook-side via the sidecar
# ``ui_button_whitelist.json`` emitted by ``core/runtime_hook_emitter.py``.
#
# Thread-safety contract: ``_ui_button_extensions`` is a frozenset that is
# *rebound* (not mutated) on every load/add/clear.  Attribute rebind is
# atomic under the GIL, so readers of ``is_common_ui_button`` in worker
# threads always observe a consistent snapshot.  All loaders MUST complete
# before the first ``engine.run(args)`` spawns a ThreadPoolExecutor.
# ============================================================

_ui_button_extensions: frozenset[str] = frozenset()


def add_ui_button_whitelist(tokens: Iterable[str]) -> int:
    """Rebind ``_ui_button_extensions`` with ``tokens`` merged in.

    Returns the number of previously-unseen entries that were inserted.
    Tokens are normalised via ``_normalise_ui_button``; empties and
    non-strings are silently dropped.  Idempotent: replaying the same
    token list is a no-op.
    """
    global _ui_button_extensions
    cleaned = {_normalise_ui_button(t) for t in tokens}
    cleaned.discard("")
    before = len(_ui_button_extensions)
    _ui_button_extensions = frozenset(_ui_button_extensions | cleaned)
    return len(_ui_button_extensions) - before


def load_ui_button_whitelist(paths: Iterable[Union[str, Path]]) -> int:
    """Load one or more ``.txt`` / ``.json`` whitelist files into the
    extension set.  Returns the total number of new entries added across
    all files.

    ``.txt`` format (also the fallback for unknown extensions):
        * UTF-8 (BOM tolerated via ``utf-8-sig`` decode)
        * one token per line
        * lines starting with ``#`` and blank lines are skipped

    ``.json`` format:
        * UTF-8, top-level JSON array of strings, e.g. ``["存档", "读档"]``
        * other shapes log a warning and the file is skipped

    Best-effort loader: missing files, read errors, and malformed JSON log
    a warning and move on.  The translation run is never aborted by a
    whitelist problem.
    """
    import json as _json

    # Round 44 audit-tail: 50 MB cap on operator-supplied UI whitelist
    # files.  Missed by r32 when the --ui-button-whitelist flag was
    # added.  Matches the cap used across r37-r43 user-facing loaders.
    _MAX_UI_WHITELIST_SIZE = 50 * 1024 * 1024

    total_added = 0
    for raw_path in paths:
        if not raw_path:
            continue
        p = Path(str(raw_path))
        if not p.is_file():
            logger.warning("[UI-WHITELIST] 文件不存在或不可读，跳过: %s", p)
            continue
        try:
            fsize = p.stat().st_size
        except OSError:
            fsize = 0
        if fsize > _MAX_UI_WHITELIST_SIZE:
            logger.warning(
                "[UI-WHITELIST] 跳过 %s: 文件 %d 字节超过 %d 字节上限",
                p, fsize, _MAX_UI_WHITELIST_SIZE,
            )
            continue
        try:
            # Round 49 Step 2: TOCTOU defense via check_fstat_size on the open fd.
            with open(p, encoding="utf-8-sig") as f:
                ok, fsize2 = check_fstat_size(f, _MAX_UI_WHITELIST_SIZE)
                if not ok:
                    logger.warning(
                        "[UI-WHITELIST] 跳过 %s: 文件 stat 后增长到 %d 字节"
                        "（疑似 TOCTOU 攻击），超过 %d 字节上限",
                        p, fsize2, _MAX_UI_WHITELIST_SIZE,
                    )
                    continue
                text = f.read()
        except OSError as e:
            logger.warning("[UI-WHITELIST] 读取失败，跳过 %s: %s", p, e)
            continue

        suffix = p.suffix.lower()
        tokens: list[str] = []
        if suffix == ".json":
            try:
                data = _json.loads(text)
            except ValueError as e:
                logger.warning("[UI-WHITELIST] JSON 解析失败，跳过 %s: %s", p, e)
                continue
            if not isinstance(data, list):
                logger.warning(
                    "[UI-WHITELIST] JSON 结构应为 list[str]，跳过 %s", p,
                )
                continue
            tokens = [t for t in data if isinstance(t, str)]
        else:
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                tokens.append(stripped)

        added = add_ui_button_whitelist(tokens)
        total_added += added
        logger.info(
            "[UI-WHITELIST] %s: 新增 %d 条 UI 按钮（文件原始 %d 条）",
            p, added, len(tokens),
        )
    return total_added


def clear_ui_button_whitelist() -> None:
    """Rebind the extension set back to empty.  Primarily for test isolation
    (the project has no pytest fixtures; every new test calls this at the top).
    """
    global _ui_button_extensions
    _ui_button_extensions = frozenset()


def get_ui_button_whitelist_extensions() -> frozenset[str]:
    """Return a snapshot of the current extensions.  Already a frozenset so
    the caller cannot mutate module state inadvertently; callers that need
    the union with the baseline should call ``is_common_ui_button`` directly.
    """
    return _ui_button_extensions


# ============================================================
# Round 31 Tier A-2: Chinese placeholder drift auto-fix
# Ported from `renpy_hook_template_py3.rpy::_fix_renpy_placeholders`.
# AI models frequently "helpfully translate" the variable NAME inside Ren'Py
# placeholders (``[name]`` → ``[名字]``) even though the user_prompt tells
# them to leave those alone.  When the token isn't protected (e.g. screen-
# translator short fragments), the output ships with broken Ren'Py syntax.
# This auto-fix catches the most common drift variants as a belt-and-braces
# layer on top of ``protect_placeholders`` / ``restore_placeholders``.
# ============================================================

_CHINESE_PLACEHOLDER_DRIFT_MAP: tuple[tuple[str, str], ...] = (
    # Square brackets — the canonical Ren'Py variable form.
    ("[姓名]", "[name]"),
    ("[名字]", "[name]"),
    ("[名称]", "[name]"),
    # Chinese full-width parens the AI likes to produce.
    ("（姓名）", "[name]"),
    ("（名字）", "[name]"),
    ("(姓名)", "[name]"),
    ("(名字)", "[name]"),
    # Double curly braces (Ren'Py 8 screen-text variable form).
    ("{{姓名}}", "{{name}}"),
    ("{{名字}}", "{{name}}"),
    ("{{名称}}", "{{name}}"),
)


def fix_chinese_placeholder_drift(text: str) -> str:
    """Normalise AI-introduced Chinese placeholder variants back to Ren'Py.

    Handles the three forms the upstream competitor hook observed in the wild:
    ``[姓名]`` / ``[名字]`` / ``[名称]`` → ``[name]``, plus the full-width
    paren variants ``（姓名）`` and the ``{{姓名}}`` double-curly form.  Each
    replacement is independent — if ``text`` doesn't contain a drift variant
    it is returned unchanged.

    Safe to call on strings that don't contain Chinese — pure string replace,
    no regex, no Unicode normalisation surprises.
    """
    if not text:
        return text
    for bad, good in _CHINESE_PLACEHOLDER_DRIFT_MAP:
        if bad in text:
            text = text.replace(bad, good)
    return text


def _fix_chinese_placeholder_drift_in_translations(
    translations: list[dict],
    extra_keys: tuple[str, ...] = (),
) -> int:
    """In-place normalise ``fix_chinese_placeholder_drift`` across a list of
    translation dicts.  Returns the number of entries that were modified
    (useful for logging / tests).

    Default keys processed are ``original`` and ``zh``; callers that also
    need ``id`` (tl-mode) can pass it via ``extra_keys``.
    """
    keys = ("original", "zh") + extra_keys
    modified = 0
    for t in translations:
        changed = False
        for key in keys:
            val = t.get(key)
            if val:
                fixed = fix_chinese_placeholder_drift(val)
                if fixed != val:
                    t[key] = fixed
                    changed = True
        if changed:
            modified += 1
    return modified
