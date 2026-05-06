#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime-hook emitter (round 31 Tier C).

Opt-in pipeline tail-step that writes ``translations.json`` plus a copy of
``resources/hooks/inject_hook.rpy`` into the translated output directory.
Pairs with the ``--sandbox`` style ``RENPY_TL_INJECT=1`` launch gate in the
hook file so end-users can choose between:

  * **Default (static-file mode)** — translated ``.rpy`` files are
    written to ``output_dir/game/``; the game runs translated without any
    runtime hook.
  * **Opt-in (runtime-hook mode)** — users who prefer to keep the game's
    original ``.rpy`` files unmodified can ship just the ``translations.json``
    + ``zz_tl_inject_hook.rpy`` produced here alongside the unmodified
    game, and launch with ``RENPY_TL_INJECT=1``.

Activated only when the caller passes ``getattr(args, "emit_runtime_hook",
False)``; silently no-ops otherwise.  Zero third-party dependencies.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
from pathlib import Path
from typing import Iterable, Mapping

logger = logging.getLogger("multi_engine_translator")


# Round 33 Subtask 2: safety regex for ``gui_overrides`` keys.  The key must
# look like ``gui.xyz`` (or ``gui.sub.xyz``) so the emitted Ren'Py code is a
# pure attribute assignment — never a Python expression or statement that
# could execute arbitrary code when an untrusted ``font_config.json`` is
# passed in.  Values are also typechecked separately (int/float only).
_SAFE_GUI_KEY = re.compile(r"^gui\.[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*$")


# Round 35 Commit 4: safety regex for ``config_overrides`` keys.  Ren'Py's
# ``config`` namespace is a FLAT module-like object (no ``config.sub.X`` —
# unlike ``gui``'s potentially-nested structure) so the pattern is tighter:
# only single-dot identifiers allowed.  Values still restricted to int/float
# today; a future round can extend to bool for e.g. ``config.autosave``.
_SAFE_CONFIG_KEY = re.compile(r"^config\.[A-Za-z_][A-Za-z_0-9]*$")


# Round 34 Commit 4: generalised dispatch table for ``font_config`` override
# categories.  Round 35 Commit 4 registers the second category,
# ``config_overrides``, now that the infrastructure is proven in prod.
#
# Each entry maps a top-level ``font_config`` sub-dict name to the regex
# its keys must match to be emitted into ``zz_tl_inject_gui.rpy``.  All
# safe categories share a single aux ``.rpy`` file written at ``init 999``
# under the ``RENPY_TL_INJECT=1`` env-var guard.
#
# ``style_overrides`` remains deliberately excluded because modifying the
# style registry at ``init 999`` time contradicts the project-wide design
# choice documented in ``resources/hooks/inject_hook.rpy:34-37`` ("Font-
# replacement uses only ``config.font_replacement_map``, not style-object
# monkey-patching").  ``config.X`` by contrast is a plain module attribute
# assignment supported at any init priority, so it's the natural second
# category to register.
#
# Values are restricted to ``int`` / ``float`` at runtime (see
# ``_sanitise_overrides``); ``bool`` / ``str`` / ``list`` / ``dict`` /
# ``None`` are rejected with a warning.  Future rounds adding categories
# should (a) add a regex entry below, (b) extend ``test_override_
# categories_table_is_extensible`` with the new key, (c) document the
# Ren'Py init-timing impact in the CHANGELOG.
_OVERRIDE_CATEGORIES: "dict[str, re.Pattern[str]]" = {
    "gui_overrides": _SAFE_GUI_KEY,
    "config_overrides": _SAFE_CONFIG_KEY,
}


# Round 38 C3: per-category bool policy.  ``gui.*`` attributes
# (font sizes, layout measurements, color constants) never legitimately
# take a boolean today, so a ``gui.text_size = True`` assignment is
# almost certainly a typo and stays rejected.  ``config.*`` attributes
# by contrast include first-class Ren'Py bool switches —
# ``config.autosave = True``, ``config.developer = False``,
# ``config.rollback_enabled = True`` etc. — so those must pass through
# the sanitiser with their bool values intact.  Other future categories
# should pick a policy explicitly when registered.
_OVERRIDE_ALLOW_BOOL: "dict[str, bool]" = {
    "gui_overrides": False,
    "config_overrides": True,
}


def _iter_translation_pairs(
    entries: Iterable[Mapping[str, object]],
) -> Iterable[tuple[str, str]]:
    """Yield (original, translation) pairs for successful entries only.

    Round 52 C4 BREAKING: ``entry_language_filter`` retired (zh-only).
    """
    for entry in entries:
        status = str(entry.get("status", "") or "").lower()
        if status and status != "ok":
            continue
        original = entry.get("original")
        translation = entry.get("translation")
        if not isinstance(original, str) or not isinstance(translation, str):
            continue
        if not original or not translation:
            continue
        yield original, translation


def build_translations_map(
    entries: Iterable[Mapping[str, object]],
) -> dict:
    """Collapse a ``TranslationDB.entries`` iterable into the runtime hook
    translations JSON payload.

    Round 52 C4 BREAKING: v2 nested multi-language schema retired.  Output
    is always v1 flat ``{original: translation}``.  ``target_lang``,
    ``schema_version``, ``entry_language_filter`` kwargs all retired.

    Deduplication: first successful translation wins (stable across re-runs
    because ``translation_db.json`` preserves insertion order).  Conflicting
    translations keep the first one and log debug-level notice.
    """
    mapping: dict[str, str] = {}
    conflicts = 0
    for original, translation in _iter_translation_pairs(entries):
        existing = mapping.get(original)
        if existing is None:
            mapping[original] = translation
        elif existing != translation:
            conflicts += 1
            logger.debug(
                "[TL-INJECT] translation conflict for %r — kept first (%r), skipped (%r)",
                original,
                existing,
                translation,
            )
    if conflicts:
        logger.info(
            "[TL-INJECT] %d original(s) had conflicting translations; kept first occurrence each",
            conflicts,
        )
    return mapping


def _write_json_atomic(path: Path, data: object) -> None:
    """Write ``data`` as pretty UTF-8 JSON atomically via temp + os.replace.

    Shared helper so every artefact emitted by the runtime hook (translations,
    ui whitelist sidecar, and future v2 schema envelopes) uses identical
    crash-safety: an interrupted run never leaves a half-written file.
    Keys are sorted for stable diffs; ``ensure_ascii=False`` keeps CJK
    content readable when users inspect the files.
    """
    import os as _os

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    _os.replace(str(tmp_path), str(path))


def _sanitise_overrides(
    overrides: Mapping[str, object],
    key_regex: "re.Pattern[str]",
    category_name: str = "gui",
    *,
    allow_bool: bool = False,
) -> dict[str, object]:
    """Filter ``overrides`` to safe ``<ns>.xxx = int|float[|bool]`` pairs.

    Round 33 Subtask 2 + Round 34 Commit 4 (generalised): the generated
    ``zz_tl_inject_gui.rpy`` embeds each key/value as raw Python source,
    so we must reject anything that could escape the attribute-assignment
    shape — including keys with suffixes, operators, or whitespace, and
    any value that isn't a plain numeric (or, for some categories,
    bool) type.

    ``category_name`` is just the warning-message label ("gui", "config",
    etc.) so the emitted log tells the operator which sub-dict got
    rejected without leaking the full regex.  Each drop logs at
    ``warning`` level.

    Round 38 C3: ``allow_bool`` is the per-category bool-policy gate.
    Defaults to ``False`` (backwards-compatible — ``gui.X = True`` is
    still rejected because no supported gui attribute legitimately
    expects a boolean).  Set to ``True`` for categories whose Ren'Py
    attributes include first-class booleans — e.g. ``config.autosave``,
    ``config.developer``, ``config.rollback_enabled``.  Callers use
    :data:`_OVERRIDE_ALLOW_BOOL` to resolve the right value per category.
    """
    clean: dict[str, object] = {}
    for raw_key, raw_val in overrides.items():
        if not isinstance(raw_key, str) or not key_regex.match(raw_key):
            logger.warning(
                "[TL-INJECT] skipping unsafe %s key in font_config: %r",
                category_name,
                raw_key,
            )
            continue
        # Round 38 C3: bool is a subtype of int in Python.  Check it
        # explicitly BEFORE the generic int/float check so a ``True`` /
        # ``False`` value only slips through when ``allow_bool=True``.
        if isinstance(raw_val, bool):
            if not allow_bool:
                logger.warning(
                    "[TL-INJECT] skipping bool %s value for %s: %r "
                    "(bool not allowed in this category)",
                    category_name,
                    raw_key,
                    raw_val,
                )
                continue
            # allow_bool=True: fall through to accept the bool.
        elif not isinstance(raw_val, (int, float)):
            logger.warning(
                "[TL-INJECT] skipping non-numeric %s value for %s: %r",
                category_name,
                raw_key,
                raw_val,
            )
            continue
        # Round 36 H2: reject inf / -inf / nan.  Python's ``json.loads``
        # accepts JSON ``Infinity`` / ``NaN`` as ``float('inf')`` /
        # ``float('nan')`` which pass the ``isinstance`` check above but
        # ``repr(inf) == 'inf'`` is not a valid identifier in Ren'Py's
        # ``init python:`` block — game startup crashes with NameError.
        if isinstance(raw_val, float) and not math.isfinite(raw_val):
            logger.warning(
                "[TL-INJECT] skipping non-finite %s value for %s: %r",
                category_name,
                raw_key,
                raw_val,
            )
            continue
        clean[raw_key] = raw_val
    return clean


def _sanitise_gui_overrides(
    overrides: Mapping[str, object],
) -> dict[str, object]:
    """Round 33 back-compat thin wrapper — delegates to the generalised
    :func:`_sanitise_overrides` with the ``gui_overrides`` category's
    regex.  Kept as a public-ish symbol because round-33 callers and
    tests import this name directly; round-34 code should prefer the
    generic form.
    """
    return _sanitise_overrides(
        overrides,
        _OVERRIDE_CATEGORIES["gui_overrides"],
        category_name="gui",
    )


def _emit_overrides_rpy(
    output_game_dir: Path,
    font_config: Mapping[str, object] | None,
    *,
    filename: str = "zz_tl_inject_gui.rpy",
) -> Path | None:
    """Emit a Ren'Py script that applies overrides at ``init 999``.

    Round 34 Commit 4 generalised version: loops over every registered
    category in :data:`_OVERRIDE_CATEGORIES` and accumulates the safe
    key/value pairs into one combined file.  Today only ``gui_overrides``
    is registered (see the dispatch table's docstring for why
    ``style_overrides`` is deliberately excluded).

    Generated file shape (example with gui category only)::

        init 999 python:
            import os
            if os.environ.get("RENPY_TL_INJECT") == "1":
                gui.text_size = 22
                gui.name_text_size = 24

    ``init 999`` runs *after* the game's own ``define`` statements (which
    sit at implicit priority 0), so the override takes effect even when
    the game ships default values.  The env-var guard mirrors the main
    hook so shipping this file alongside an untouched game is safe —
    removing ``RENPY_TL_INJECT=1`` fully disables the override.

    Returns the emitted path when a file was written, or ``None`` when
    every registered category produced an empty sanitised map (default
    round-32 no-output behaviour preserved).
    """
    if not font_config:
        return None

    combined: dict[str, object] = {}
    for cat_name, key_regex in _OVERRIDE_CATEGORIES.items():
        bucket = font_config.get(cat_name) if isinstance(font_config, Mapping) else None
        if not isinstance(bucket, Mapping):
            continue
        # Strip the "_overrides" suffix for a cleaner warning namespace
        # label, e.g. "gui_overrides" → "gui".
        label = cat_name[: -len("_overrides")] if cat_name.endswith("_overrides") else cat_name
        # Round 38 C3: resolve per-category bool policy via the
        # _OVERRIDE_ALLOW_BOOL map.  Missing categories default to
        # False (safest fallback — matches r33-r37 behaviour).
        allow_bool = _OVERRIDE_ALLOW_BOOL.get(cat_name, False)
        cleaned = _sanitise_overrides(
            bucket,
            key_regex,
            category_name=label,
            allow_bool=allow_bool,
        )
        combined.update(cleaned)

    if not combined:
        return None

    output_game_dir = Path(output_game_dir)
    output_game_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Auto-generated by core/runtime_hook_emitter.py (round 33 Subtask 2;",
        "# round 34 Commit 4 generalised the dispatch over multiple override",
        "# categories, only gui_overrides registered today).",
        "# Applied at init 999 so it runs AFTER gui.rpy's `define gui.xxx = N`",
        "# defaults, and guarded by RENPY_TL_INJECT=1 env var so shipping this",
        "# file alongside an unmodified game stays safe — without the env var",
        "# it is a no-op.",
        "",
        "init 999 python:",
        "    import os",
        '    if os.environ.get("RENPY_TL_INJECT") == "1":',
    ]
    for k in sorted(combined):
        # ``repr`` on an int / float yields a Python-safe literal so the
        # emitted line is always a valid Ren'Py Python expression.
        lines.append(f"        {k} = {combined[k]!r}")
    lines.append("")

    rpy_path = output_game_dir / filename
    content = "\n".join(lines)
    # Atomic write mirroring ``_write_json_atomic``'s crash-safety shape.
    import os as _os

    tmp_path = rpy_path.with_suffix(rpy_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    _os.replace(str(tmp_path), str(rpy_path))

    logger.info(
        "[TL-INJECT] emitted overrides: %d key(s) → %s",
        len(combined),
        rpy_path.name,
    )
    return rpy_path


def _emit_gui_overrides_rpy(
    output_game_dir: Path,
    overrides: Mapping[str, object] | None,
    *,
    filename: str = "zz_tl_inject_gui.rpy",
) -> Path | None:
    """Round 33 back-compat thin wrapper — wraps ``overrides`` into a
    ``{"gui_overrides": ...}`` font_config shape and delegates to the
    generalised :func:`_emit_overrides_rpy`.  Kept so existing callers
    that passed the raw gui-overrides map directly keep working.
    """
    if overrides is None:
        return None
    return _emit_overrides_rpy(
        output_game_dir,
        {"gui_overrides": overrides},
        filename=filename,
    )


def emit_runtime_hook(
    output_game_dir: Path,
    translation_db_entries: Iterable[Mapping[str, object]],
    *,
    hook_template_path: Path | None = None,
    hook_filename: str = "zz_tl_inject_hook.rpy",
    ui_button_extensions: Iterable[str] | None = None,
    font_path: Path | None = None,
    font_config: Mapping[str, object] | None = None,
) -> tuple[Path, Path, int]:
    """Write ``translations.json`` + copy the inject hook into
    ``output_game_dir``.

    Args:
        output_game_dir: Directory to write into (typically
            ``<output>/game`` so users can drop it over their game).
            Created if missing.
        translation_db_entries: Iterable of ``TranslationDB.entries``-shaped
            dicts.  Only ``status == "ok"`` entries contribute to the map.
        hook_template_path: Override for the source ``inject_hook.rpy``.
            Defaults to ``<project_root>/resources/hooks/inject_hook.rpy``.
        hook_filename: Name to save the hook under in ``output_game_dir``.
            Default uses the ``zz_`` prefix so Ren'Py loads it last among
            ``init python early:`` blocks — safest order for a monkey-patch
            shim that depends on other game init running first.
        ui_button_extensions: Optional iterable of UI-button whitelist
            extensions (round 32 Subtask A).  When non-empty, written to a
            sidecar ``ui_button_whitelist.json`` next to ``translations.json``
            so ``inject_hook.rpy`` can mirror the Python-side extensions at
            runtime.  Empty / None → sidecar file is NOT created, keeping
            default output byte-compatible with round 31.
        font_path: Optional path to a ``.ttf`` / ``.otf`` font file (round 32
            Subtask B).  When set and the file exists, the font is copied to
            ``<output_game_dir>/fonts/tl_inject.ttf`` so the hook's font
            replacement block (keyed on the ``_TL_FONT_REL`` constant) fires
            automatically.  None / missing file → fonts directory NOT
            created.  ``shutil.SameFileError`` (caller passes an already-
            correct destination) is tolerated and silently skipped.
        font_config: Optional already-loaded ``font_config.json`` dict (round
            33 Subtask 2).  When its ``gui_overrides`` sub-dict has at least
            one safe ``gui.xxx = int|float`` pair, an auxiliary
            ``zz_tl_inject_gui.rpy`` is emitted next to the main hook.  That
            aux file runs at ``init 999`` under an ``RENPY_TL_INJECT=1``
            env-var guard, so it safely overrides the game's ``gui.rpy``
            ``define`` defaults without affecting plays that don't set the
            env var.  Unsafe keys (regex mismatch) or non-numeric values
            are filtered out with a warning.
    Round 52 C4 BREAKING: v2 schema and language filter kwargs retired.
    Output is always v1 flat ``{original: translation}``.

    Returns:
        (translations_json_path, hook_rpy_path, entry_count)

    Raises:
        FileNotFoundError: if ``hook_template_path`` does not exist.
        OSError: on filesystem write failure (caller should log + continue;
            a runtime-hook failure must not abort the main pipeline).
    """
    output_game_dir = Path(output_game_dir)
    output_game_dir.mkdir(parents=True, exist_ok=True)

    if hook_template_path is None:
        project_root = Path(__file__).resolve().parent.parent
        hook_template_path = project_root / "resources" / "hooks" / "inject_hook.rpy"
    hook_template_path = Path(hook_template_path)
    if not hook_template_path.is_file():
        raise FileNotFoundError(
            f"inject hook template missing: {hook_template_path}\n"
            "Ensure resources/hooks/inject_hook.rpy is present."
        )

    # Build map + write translations.json atomically (temp + os.replace)
    # so an interrupted run never leaves a half-written JSON.
    payload = build_translations_map(translation_db_entries)
    json_path = output_game_dir / "translations.json"
    _write_json_atomic(json_path, payload)
    entry_count = len(payload) if isinstance(payload, dict) else 0

    # Round 32 Subtask A: optional UI-button whitelist sidecar.  Written
    # only when the caller supplied non-empty extensions — default output
    # stays byte-compatible with round 31 (translations.json + hook only).
    if ui_button_extensions is not None:
        ext_sorted = sorted({str(t) for t in ui_button_extensions if isinstance(t, str) and t})
        if ext_sorted:
            ui_json_path = output_game_dir / "ui_button_whitelist.json"
            _write_json_atomic(ui_json_path, {"extensions": ext_sorted})
            logger.info(
                "[TL-INJECT] emitted UI button sidecar: %d extensions → %s",
                len(ext_sorted),
                ui_json_path.name,
            )

    # Round 32 Subtask B: optional font bundle.  Target filename is fixed
    # to ``tl_inject.ttf`` to match ``inject_hook.rpy``'s hardcoded
    # ``_TL_FONT_REL`` constant.  Kept as a side-effect (not in the return
    # tuple) so callers that only inspect (json_path, hook_path, count) stay
    # byte-compatible with round 31.
    if font_path is not None:
        font_src = Path(font_path)
        if font_src.is_file():
            fonts_dir = output_game_dir / "fonts"
            fonts_dir.mkdir(parents=True, exist_ok=True)
            dst_font = fonts_dir / "tl_inject.ttf"
            # Path pre-check to handle the src == dst case cross-platform:
            # POSIX would raise ``shutil.SameFileError``; Windows raises
            # ``PermissionError [WinError 32]`` instead.  Resolving both
            # paths first lets us skip the copy entirely and stay portable.
            try:
                same = font_src.resolve() == dst_font.resolve()
            except OSError:
                same = False
            if same:
                logger.debug(
                    "[TL-INJECT] skip font copy — src == dst (%s)",
                    dst_font,
                )
            else:
                try:
                    shutil.copy2(str(font_src), str(dst_font))
                    logger.info(
                        "[TL-INJECT] bundled font: %s → %s",
                        font_src.name,
                        dst_font.relative_to(output_game_dir),
                    )
                except shutil.SameFileError:
                    # Belt-and-braces: even if resolve() disagreed, the
                    # POSIX SameFileError path still degrades gracefully.
                    pass

    # Round 33 Subtask 2 + Round 34 Commit 4: optional overrides auxiliary
    # script.  Generalised dispatch — iterates every registered category
    # in ``_OVERRIDE_CATEGORIES`` and accumulates safe key/value pairs
    # into one combined ``zz_tl_inject_gui.rpy``.  Default output stays
    # byte-compatible with round 32 when font_config is omitted or every
    # registered category comes up empty / unsafe.
    if font_config is not None:
        _emit_overrides_rpy(output_game_dir, font_config)

    # Copy the hook .rpy — shutil.copy2 preserves mtime/permissions so
    # Ren'Py's .rpyc cache invalidation still works when the template
    # is updated upstream.
    hook_out = output_game_dir / hook_filename
    shutil.copy2(str(hook_template_path), str(hook_out))

    logger.info(
        "[TL-INJECT] emitted runtime hook (v1 flat): %d translations → %s (+ %s)",
        entry_count,
        json_path.name,
        hook_out.name,
    )
    return json_path, hook_out, entry_count


def emit_if_requested(
    args,
    output_dir: Path,
    translation_db,
) -> None:
    """Pipeline tail-step: check ``args.emit_runtime_hook`` and emit.

    Designed to be called from every Ren'Py-facing pipeline
    (``translators.direct.run_pipeline``,
    ``translators.tl_mode.run_tl_pipeline``,
    ``translators.retranslator.run_retranslate_pipeline``,
    ``engines.generic_pipeline.run_generic_pipeline``) at the very end,
    after ``translation_db.save()`` has persisted the session state.

    Args:
        args: argparse ``Namespace`` — the flag is read as
            ``getattr(args, "emit_runtime_hook", False)``.
        output_dir: Pipeline output root; the hook + JSON are written
            under ``output_dir / "game"`` (created if missing).
        translation_db: A ``TranslationDB`` instance.  Only the
            ``.entries`` attribute is read — keeps coupling minimal.

    Never raises into the caller: an emit failure is logged as a
    warning and swallowed, so a broken hook template or a read-only
    output directory cannot abort a successful translation run.
    """
    if not getattr(args, "emit_runtime_hook", False):
        return
    try:
        entries = getattr(translation_db, "entries", None)
        if not entries:
            logger.info("[TL-INJECT] skip emit — translation_db empty")
            return
        output_game_dir = Path(output_dir) / "game"
        # Round 32 Subtask A: mirror the Python-side UI-button whitelist
        # extensions into a sidecar JSON so the inject_hook can read them
        # at runtime.  Returns frozenset (already empty / populated by
        # main.py before engine.run); we pass through unconditionally —
        # emit_runtime_hook treats empty input as "don't emit sidecar".
        ui_ext: Iterable[str] | None = None
        try:
            from file_processor import get_ui_button_whitelist_extensions

            ui_ext = get_ui_button_whitelist_extensions()
        except ImportError:
            ui_ext = None
        # Round 32 Subtask B: resolve the font via the same helper static
        # mode uses (``--font-file`` preferred, ``resources/fonts/`` fallback)
        # and bundle into ``<output>/game/fonts/tl_inject.ttf``.  None result
        # (no flag, no built-in font) → emit_runtime_hook silently skips the
        # fonts directory.
        font_source: Path | None = None
        try:
            from core.font_patch import resolve_font, default_resources_fonts_dir

            explicit = getattr(args, "font_file", "") or None
            font_source = resolve_font(default_resources_fonts_dir(), explicit)
        except (ImportError, OSError):
            font_source = None
        # Round 33 Subtask 2: load ``font_config.json`` (if supplied) and
        # pass the gui_overrides through to the aux zz_tl_inject_gui.rpy
        # emitter.  Shares ``core.font_patch.load_font_config`` with the
        # static-mode ``apply_font_patch`` so operators get the same
        # file-format guarantees on both paths.
        font_config_dict: Mapping[str, object] | None = None
        font_config_path = getattr(args, "font_config", "") or ""
        if font_config_path:
            try:
                from core.font_patch import load_font_config

                font_config_dict = load_font_config(Path(font_config_path)) or None
            except (ImportError, OSError):
                font_config_dict = None
        # Round 52 C4 BREAKING: v2 schema retired; --runtime-hook-schema
        # CLI flag retired; output is always v1 flat {original: translation}.
        emit_runtime_hook(
            output_game_dir,
            entries,
            ui_button_extensions=ui_ext,
            font_path=font_source,
            font_config=font_config_dict,
        )
    except (OSError, ValueError, FileNotFoundError) as e:
        logger.warning("[TL-INJECT] emit failed, continuing: %s", e)
