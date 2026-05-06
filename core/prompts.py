#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt 模板 — 整文件翻译的核心指令

支持从外部模板文件按项目/题材覆写：
- 基础规则仍使用内置 SYSTEM_PROMPT_TEMPLATE
- 风格与文化适配可通过 prompt_presets/<project_name>/<genre>/style.txt 与
  prompt_presets/<project_name>/<genre>/culture.txt 覆写
"""

from pathlib import Path
from typing import Optional


SYSTEM_PROMPT_TEMPLATE = """\
你是一名专业的 Ren'Py 游戏本地化翻译专家，精通 Ren'Py 引擎脚本结构。
你的任务是阅读完整的 .rpy 文件，识别需要翻译的文本，将它们翻译为简体中文。

## 核心原则
你会收到一个带行号的完整 .rpy 文件。你需要：
1. 仔细阅读整个文件，理解代码结构和上下文
2. 识别所有「需要翻译」的文本字符串
3. 将它们翻译为简体中文
4. 以 JSON 数组格式返回结果

## ✅ 需要翻译的内容
1. **对话文本**：角色台词 `character "Hello"` 中的 "Hello"
2. **旁白文本**：无角色名的独立字符串 `"You enter the room."`
3. **菜单选项**：`menu:` 块中用户可选的文本
   - 注意：`"Go home {{#home_choice}}"` → 只翻译 `Go home`，`{{#home_choice}}` 是翻译标识符，必须原样保留
4. **界面显示文本**：`text "Save Game"` 或 `textbutton "Start"` 中用户可见的文本
5. **通知文本**：`renpy.notify("message")` 中用户可见文本
6. **config.name**：游戏标题可以翻译
7. **translate 块中的 old/new**：
   - `old "English text"` → 不要输出（这是原文标记）
   - `new ""` → 输出空字符串对应的翻译，即把 it 当作替换内容

## ⛔ 绝对不能翻译的内容（翻译 = 游戏崩溃）
1. **变量引用**：`[mother]`, `[bs]`, `[name]` → 方括号内变量名必须保持原样
2. **Screen / Label 名称**：`screen say(...)` 中的 `say`、`label bedroom:` 中的 `bedroom`
3. **Ren'Py 关键字**：screen, label, jump, call, show, hide, scene, define, default, init, python, style, transform, menu, translate 等
4. **组件名和 ID**：`id "window"`, `style "namebox"`, `style_prefix "say"` 中引号内的标识符
5. **Action 参数**：`action ShowMenu("save")`, `SetVariable("x", ...)`, `Jump("label")`, `Call("label")` 中引号内的标识符
6. **Python 代码**：if/elif/else 条件、变量赋值、函数调用
7. **文件路径**：`"images/xxx.png"`, `"audio/xxx.mp3"` 等资源路径
8. **build 配置**：`build.classify` / `build.archive` 中的文件模式和归档名
9. **Ren'Py 文本标签本身**：
   - 颜色/样式：`{{color=#f00}}`, `{{/color}}`, `{{b}}`, `{{/b}}`, `{{i}}`, `{{/i}}`, `{{u}}`, `{{s}}`
   - 大小：`{{size=+10}}`, `{{/size}}`
   - 字体：`{{font=xxx.ttf}}`, `{{/font}}`
   - 控制标签：`{{w}}`, `{{w=1.0}}`, `{{p}}`, `{{p=1.0}}`, `{{nw}}`, `{{fast}}`, `{{done}}`
   - 速度：`{{cps=20}}`, `{{/cps}}`
   - 超链接：`{{a=URL}}`, `{{/a}}`
   - 只翻译标签包围的**文本**，标签本身原样保留
10. **URL 和链接**
11. **glob 模式**：`"*.rpy"`, `"**.bak"` 等
12. **style/transform 属性值**：xalign, yalign 等数值
13. **翻译函数标记**：`_("text")` 中的 `_()` 包裹保持，只翻译引号内文本
14. **条件字符串插值**：`%(name)s` 格式化占位符保持原样

## 判断技巧
- `style`, `style_prefix`, `id`, `action`, `SetVariable`, `SetField`, `Show`, `ShowMenu`, `Jump`, `Call` 后的字符串 → **不翻译**
- `text`, `textbutton` 的显示文本（第一个字符串参数）→ **翻译**
- `label`, `textbutton`, `imagebutton` 的 `action` 参数 → **不翻译**
- 对话行（行首是角色变量或无前缀的引号字符串）→ **翻译**
- `old "..."` 行 → **不要输出**（这是翻译框架的原文标记）
- `new "..."` 行 → **翻译**（引号内填写译文）
- `{{#identifier}}` 形式的菜单选项尾缀 → **不翻译**，原样保留在译文末尾
- `{{w}}`, `{{w=0.5}}`, `{{p}}`, `{{nw}}`, `{{fast}}`, `{{cps=20}}` 等控制标签 → **原样保留在译文中相同位置**
- `{{a=URL}}链接文字{{/a}}` → 只翻译链接文字，URL 和标签保留
- `_("text")` 包裹的文本 → **翻译引号内文本**，`_()` 保留
- `add "image.png"`, `use some_screen` → **不翻译**（资源/screen 引用）
- 看起来像代码、路径、配置值 → **不翻译**
- 拿不准时：先判断是否为**用户可见文本**（对话/旁白/菜单/UI）。
    - 如果是用户可见文本：**优先翻译**。
    - 仅当明确是代码标识符/路径/动作参数时才不翻译。
- 对于纯英文对话或旁白，不要原样保留英文。

## 翻译规范
{style_block}
{culture_block}
- 自然口语化，避免生硬直译
- 保持原文语气和情感
- 保持换行符 `\\n` 数量、位置一致
- `[variable]` 占位符原样保留，不改名不删除
- `{{tag}}内容{{/tag}}` 保留标签，翻译内容
- `%(name)s` 等格式化占位符原样保留
 - 占位符（如 [变量]、{{标签}}、%(name)s、{{#id}}）在译文中数量与出现顺序应尽量与原文一致；若因语序调整需调序，请保持所有占位符完整且位置正确
- 控制标签 `{{w}}` `{{p}}` `{{nw}}` `{{fast}}` 原样保留在对应位置
- 翻译长度合理：中文译文通常比英文短 30-60%，异常长/短请复查
- 避免多余的标点：英文句号 `.` 翻译为 `。`，不要出现 `。.` 这样的双标点
- 若术语表中将某些英文标记为“锁定术语”，则当这些英文出现在原文中时，译文中必须严格使用给定的中文译名，不得使用其他译名
- 若术语表中将某些片段标记为“禁翻片段”，当这些片段出现在原文中时，译文应保持相同的英文片段，不要翻译或改写

{glossary_block}

## 输出格式
返回一个 JSON 数组，每个元素包含：
- `line`: 行号（与文件行号一致，从 1 开始）
- `original`: 原始英文文本（必须与文件中引号内的内容完全一致）
- `zh`: 中文译文

示例：
```json
[
  {{"line": 15, "original": "Hello, how are you?", "zh": "你好，你怎么样？"}},
  {{"line": 28, "original": "Go to the store", "zh": "去商店"}},
  {{"line": 42, "original": "Save Game", "zh": "保存游戏"}},
  {{"line": 55, "original": "Are you sure you want to quit?{{#quit_confirm}}", "zh": "你确定要退出吗？{{#quit_confirm}}"}}
]
```

⚠️ 只返回纯 JSON 数组。不需要 markdown 代码块标记，不要解释，不要思考过程。
⚠️ original 字段必须是引号内的精确原文，不含外层引号。
⚠️ 如果文件中没有需要翻译的内容，返回空数组 `[]`。"""

STYLE_ADULT = (
    "## 翻译风格\n- 成人游戏风格：直白露骨，用词大胆\n- 保持原文的挑逗/色情意味\n- 对话自然口语化"
)
STYLE_VISUAL_NOVEL = "## 翻译风格\n- 视觉小说风格：文学化，注重叙事感和情感表达"
STYLE_RPG = "## 翻译风格\n- RPG 风格：简洁有力，注重游戏性用语"
STYLE_GENERAL = "## 翻译风格\n- 通用游戏风格：自然流畅"

_STYLES = {
    "adult": STYLE_ADULT,
    "visual_novel": STYLE_VISUAL_NOVEL,
    "rpg": STYLE_RPG,
    "general": STYLE_GENERAL,
}


def _load_text_if_exists(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8-sig").strip()
    return ""


# ============================================================
# 引擎专属 prompt 附加说明
# ============================================================

_ENGINE_PROMPT_ADDONS: dict[str, str] = {
    "rpgmaker": """
## RPG Maker Special Variables
The text may contain RPG Maker control codes that MUST be preserved exactly:
- \\V[n] — game variable (displays a number or text)
- \\N[n] — character name reference
- \\P[n] — party member name
- \\C[n] — color change (\\C[0] resets to default)
- \\G — currency unit
- \\{ and \\} — increase/decrease font size
- \\! — wait for player input
- \\. and \\| — pause (short/long)
- \\> and \\< — instant display on/off
Do NOT translate, modify, or remove any of these codes.
""",
    "generic": """
## Translation Format
Return a JSON array where each object has "id" matching the input and a translation field.
Preserve any placeholder tokens (e.g., __RENPY_PH_0__) exactly as they appear.
""",
}


# ============================================================
# CoT 思维链翻译 addon
# ============================================================

_COT_ADDON_ZH = """
## 翻译流程（Chain-of-Thought）

对每条文本，请在内部按以下三步思考后再输出最终译文：
1. **直译**：逐字忠实翻译原文，保留所有占位符和标点
2. **校正**：检查术语一致性（参考术语表）、占位符完整性、语法自然度
3. **意译**：基于校正结果，输出自然流畅、符合目标语言习惯的最终译文

在 JSON 输出中，只返回第 3 步的最终译文。不要输出中间推理步骤。
"""


def build_system_prompt(
    genre: str = "adult",
    glossary_text: str = "",
    project_name: Optional[str] = None,
    engine_profile: object = None,
    cot: bool = False,
) -> str:
    """构建系统提示词（zh-only since round 52 C4）。

    优先加载外部模板中的风格/文化块：
    - prompt_presets/<project_name>/<genre>/style.txt
    - prompt_presets/<project_name>/<genre>/culture.txt
    - 若未提供 project_name，则回退到 prompt_presets/<genre>/...
    - 若找不到外部模板，则使用内置 STYLE_* 与空的文化块。

    engine_profile: 引擎配置（EngineProfile 实例，可选）。
      - None → Ren'Py 默认路径（现有行为不变）
      - 非 None → 追加引擎专属 prompt addon

    cot: 启用 CoT 思维链翻译（直译→校正→意译）。
    """
    # 1. 解析外部模板目录搜索顺序
    base_dir = Path(__file__).parent / "prompt_presets"
    search_dirs = []
    if project_name:
        search_dirs.append(base_dir / project_name / genre)
    search_dirs.append(base_dir / genre)

    external_style = ""
    external_culture = ""
    for d in search_dirs:
        if not d.exists():
            continue
        if not external_style:
            external_style = _load_text_if_exists(d / "style.txt")
        if not external_culture:
            external_culture = _load_text_if_exists(d / "culture.txt")
        if external_style and external_culture:
            break

    # 2. 决定最终使用的风格与文化块
    style = external_style or _STYLES.get(genre, STYLE_GENERAL)
    culture_block = external_culture or ""

    # 3. 术语表块
    if glossary_text:
        glossary_block = f"## 术语表（请保持翻译一致）\n{glossary_text}"
    else:
        glossary_block = ""
    base = SYSTEM_PROMPT_TEMPLATE.format(
        style_block=style,
        culture_block=culture_block,
        glossary_block=glossary_block,
    )

    # 追加引擎专属说明（仅非 Ren'Py 引擎）
    if engine_profile is not None:
        addon_key = getattr(engine_profile, "prompt_addon_key", "")
        addon = _ENGINE_PROMPT_ADDONS.get(addon_key, "")
        if addon:
            base = base.rstrip() + "\n\n" + addon.strip() + "\n"

    # 追加 CoT 思维链说明
    if cot:
        base = base.rstrip() + "\n" + _COT_ADDON_ZH.strip() + "\n"

    return base


def build_user_prompt(filename: str, content: str, chunk_info: dict = None) -> str:
    """构建用户提示词（带行号的文件内容）

    Args:
        filename: 文件名（相对路径）
        content: 文件内容
        chunk_info: 分块信息 {"part": 1, "total": 3, "line_offset": 0,
                     可选 "prev_context": str, "prev_context_offset": int}
    """
    lines = content.split("\n")
    offset = chunk_info.get("line_offset", 0) if chunk_info else 0

    header = f"文件：{filename}\n"
    if chunk_info:
        header += f"（第 {chunk_info['part']}/{chunk_info['total']} 部分，"
        header += f"行 {1 + offset}-{len(lines) + offset}）\n"

    # 上文上下文（仅供 AI 了解前文语境，不需要翻译）
    context_block = ""
    if chunk_info and chunk_info.get("prev_context"):
        ctx_lines = chunk_info["prev_context"].split("\n")
        ctx_offset = chunk_info.get("prev_context_offset", 0)
        numbered_ctx = []
        for i, line in enumerate(ctx_lines):
            lineno = i + 1 + ctx_offset
            numbered_ctx.append(f"{lineno:5d}| {line}")
        context_block = (
            "--- 以下是前一部分末尾的上下文（仅供参考，不要翻译） ---\n"
            + "\n".join(numbered_ctx)
            + "\n--- 上下文结束，以下是需要翻译的内容 ---\n\n"
        )

    # 添加行号
    numbered_lines = []
    for i, line in enumerate(lines):
        lineno = i + 1 + offset
        numbered_lines.append(f"{lineno:5d}| {line}")
    numbered = "\n".join(numbered_lines)

    return f"请翻译以下 Ren'Py 文件中需要翻译的文本：\n\n{header}\n{context_block}{numbered}"


# ============================================================
# 补翻模式专用 prompt
# ============================================================

RETRANSLATE_SYSTEM_PROMPT = """\
你是一名 Ren'Py 游戏翻译专家。你将收到一段已部分翻译的游戏脚本，其中用 `>>>` 标记了被遗漏的英文对话行。

## 任务
翻译所有用 `>>>` 标记的行。未标记的行是上下文，帮助你理解语境，不需要翻译。

## 规则
- 每一个 `>>>` 标记行都**必须**翻译，不得跳过
- `[variable]` 方括号变量名原样保留
- `{{{{tag}}}}` 文本标签原样保留
- `%(name)s` 格式化占位符原样保留
- `{{{{#identifier}}}}` 菜单标识符原样保留
- 保持换行符 `\\n` 一致
- 翻译风格自然口语化，保持原文语气

{glossary_block}

## 输出格式
返回一个 JSON 数组：
```json
[
  {{"line": 236, "original": "So, what's for dinner?", "zh": "今晚吃什么？"}},
  {{"line": 238, "original": "She smiled warmly.", "zh": "她温暖地笑了。"}}
]
```

⚠️ 只返回纯 JSON 数组。不需要 markdown 代码块标记。
⚠️ original 字段必须是引号内的精确原文。
⚠️ 每个 `>>>` 标记行都必须翻译，遗漏比误翻更严重。"""


def build_retranslate_system_prompt(glossary_text: str = "") -> str:
    """Build the retranslate-mode system prompt (zh-only since round 52 C4)."""
    if glossary_text:
        glossary_block = f"## 术语表\n{glossary_text}"
    else:
        glossary_block = ""
    return RETRANSLATE_SYSTEM_PROMPT.format(glossary_block=glossary_block)


def build_retranslate_user_prompt(
    filename: str,
    chunk_lines: list[tuple[int, str, bool]],
) -> str:
    """构建补翻模式的用户提示词。

    Args:
        filename: 文件相对路径
        chunk_lines: [(1-based_line_number, line_content, is_target), ...]
    """
    formatted = []
    for lineno, line, is_target in chunk_lines:
        prefix = ">>> " if is_target else "    "
        formatted.append(f"{prefix}{lineno:5d}| {line}")
    body = "\n".join(formatted)

    target_count = sum(1 for _, _, t in chunk_lines if t)
    return (
        f"[补翻模式] 文件：{filename}\n"
        f"以下有 {target_count} 行被遗漏的英文对话（标记为 >>>），每一行都必须翻译。\n\n"
        f"{body}"
    )


# ============================================================
# tl-mode 专用 prompt
# ============================================================

TLMODE_SYSTEM_PROMPT = """\
你是一名专业的 Ren'Py 视觉小说翻译专家。你将收到从 Ren'Py 翻译框架提取的待翻译文本条目。

## 任务
将每条英文文本翻译为简体中文。

## 条目格式
每条待翻译文本前有一个标识符行：
- `[ID: xxx]` 表示对话条目，`[Char: yyy]` 是说话角色（可能为空 = 旁白）
- `[STRING]` 表示界面/系统字符串

## 规则
- **每一条都必须翻译**，不得跳过
- `[variable]` 方括号变量名原样保留
- `{{{{tag}}}}内容{{{{/tag}}}}` 保留标签，只翻译内容
- `%(name)s` 格式化占位符原样保留
- `{{{{#identifier}}}}` 菜单标识符原样保留
- 保持换行符 `\\n` 一致：译文中 `\\n` 的数量和位置应尽量与原文对应
- `[MULTILINE]` 标记的条目含有 `\\n` 换行符，翻译时**必须保留所有 `\\n`**，不要删除或合并
- 翻译风格自然口语化，保持原文语气和情感
- 避免生硬直译和机翻腔
- 避免多余标点：不要出现 `。.` `？?` 等中英标点混用

{style_block}
{glossary_block}

## 输出格式
返回一个 JSON 数组，每个元素包含：
- `id`: 对话条目用 identifier（如 `"start_636ae3f5"`），字符串条目用原文本身（如 `"History"`）
- `original`: 精确原文
- `zh`: 中文译文

```json
[
  {{"id": "start_636ae3f5", "original": "Hello, how are you?", "zh": "你好，你怎么样？"}},
  {{"id": "History", "original": "History", "zh": "历史"}}
]
```

只返回纯 JSON 数组。不需要 markdown 代码块标记，不要解释，不要思考过程。
每条都必须翻译，遗漏比误翻更严重。"""


def build_tl_system_prompt(
    glossary_text: str = "",
    genre: str = "adult",
    cot: bool = False,
) -> str:
    """Build the tl-mode system prompt (zh-only since round 52 C4)."""
    style_block = _STYLES.get(genre, STYLE_GENERAL)
    if glossary_text:
        glossary_block = f"## 术语表（请保持翻译一致）\n{glossary_text}"
    else:
        glossary_block = ""
    base = TLMODE_SYSTEM_PROMPT.format(
        style_block=style_block,
        glossary_block=glossary_block,
    )
    if cot:
        base = base.rstrip() + "\n" + _COT_ADDON_ZH.strip() + "\n"
    return base


def build_tl_user_prompt(chunk_text: str, entry_count: int) -> str:
    """构建 tl-mode 用户提示词。"""
    return f"请翻译以下 {entry_count} 条 Ren'Py 游戏文本：\n\n{chunk_text}"
