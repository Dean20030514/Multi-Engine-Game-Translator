# 架构与数据流

本文档汇总：模块图、三种翻译模式数据流、四阶段一键流水线、引擎抽象层、新引擎扩展指南、质量保障链、测试体系。

> 阈值常量、错误码、路线图：见 [REFERENCE.md](REFERENCE.md)
> 历史决策：见 [_archive/EVOLUTION.md](../_archive/EVOLUTION.md)
> 当前数字：见 [HANDOFF.md](../HANDOFF.md) 顶部 `VERIFIED-CLAIMS` 块

---

## 0. Quick Tour for Human Maintainers（r59 O1 — 人类视角入口）

> 这一段是给**新加入的人类维护者**写的，不是给 AI 写的。如果你刚 clone 完仓库不知道从哪里下手，先读这一段；其他章节是 reference，需要时查。

### 这是个什么项目

游戏汉化工具：把 Ren'Py / RPG Maker MV-MZ / CSV-JSONL / Unity XUnity 文件丢给 LLM 翻译，自动回填到原文件位置。**目标语言固定 zh 简体中文**（r52 BREAKING）。**零运行时依赖**（项目 hard contract），纯 Python ≥ 3.10。

### 5 分钟跑通

```bash
# 1. 克隆 + 跑单元测试看是否绿
git clone https://github.com/Dean20030514/Multi-Engine-Game-Translator
cd Multi-Engine-Game-Translator
python tests/test_all.py    # 应输出 ALL XXX TESTS PASSED

# 2. dry-run（不调 API）— 用项目自带的小 fixture
python main.py --game-dir tests/tl_priority_mini/game --provider xai --dry-run

# 3. 看 docs/ONBOARDING.md（r59 O3 引入）— 5 分钟快速向导
```

### 心理模型

- **`engines/`** 是抽象层——它知道"游戏目录里有什么文件"。Ren'Py 引擎是**特殊的**（详见 [`docs/REFERENCE.md §13.2.1`](REFERENCE.md)）：它不走 `generic_pipeline` 6 阶段流水线，而是路由到 `translators/` 三条专用管线（tl-mode / direct / retranslate）。其他引擎（RPGM / CSV / Unity XUnity）才走 generic_pipeline。
- **`translators/`** 是 Ren'Py 专用翻译实现——`DialogueEntry` 数据类型 + 跨文件去重 + 5 层 fallback + r53 W1 retry 并发 + r53 W3 LLM ID drift detection layer-6。
- **`core/`** 是 LLM API 抽象 + 共享基础设施（API 客户端、连接池、prompts、术语表、translation_db、pickle 白名单 unpickler）。
- **`safety/`** 是 cross-cutting helper（目前只有 r56 M2 移过来的 `file_safety.py` TOCTOU 防御）。
- **`file_processor/`** 是 .rpy 文本处理（splitter / patcher / checker / validator）。
- **`pipeline/`** 是一键四阶段流水线（pilot → gate → full → catchup）。

### 必读上下文

按重要度排序：

1. [`HANDOFF.md`](../HANDOFF.md)（≈250 行）— 当前轮次 + 已完成 + 下一步推荐 + Round N+1 关键约束（含所有 hard contracts）
2. [`CLAUDE.md`](../CLAUDE.md)（≈150 行）— 10 大开发原则 + 模块图 + 维护规则 + 已知限制
3. 本文档 — 模块图 / 数据流 / 引擎扩展指南
4. [`docs/REFERENCE.md`](REFERENCE.md) — 阈值常量 + 错误码 + 配置层级优先级 + 引擎路线图

> r66 retire ADR framework：架构决策已在 CLAUDE.md hard contracts + EVOLUTION 阶段叙事完整记录

### 本项目的几个特殊约束

- **NEVER push 政策**：CLAUDE.md global rule 禁止 AI 助手 push；任何 commit 都由人类 maintainer 决定何时 push
- **byte-identical CLAUDE.md ↔ .cursorrules**：修 CLAUDE.md 必须 `cp CLAUDE.md .cursorrules`；CI guard 检查
- **VERIFIED-CLAIMS 单一声称源**：测试数 / 文件数 / CI 步骤 / 断言点只在 [`HANDOFF.md`](../HANDOFF.md) 顶部 fenced block 声明；其他文档只能引用，pre-commit hook + CI 双层 enforce 不可漂移
- **800 行 cap**：任何 .py 文件超 800 行 pre-commit hook 会 block；rule 强制拆分而非允许单文件膨胀
- **零欠账闭合**（r50 起）：所有 audit findings 必须**同轮 fix**，无法 fix 的必须显式归 architectural decision（写入 CLAUDE.md "已知限制"段）而不是 silent defer
- **mypy enforce**（r57 T2 / r58 P1）：6 文件 hot-path scope + `engines/+safety/` 必须 0 errors；新文件加入前必须先 mypy clean
- **ruff lint+format CI 门禁**（r58 P1）：`ruff check .` + `ruff format --check .` 必须 green；新 PR 不过这两关进不来

### 改动前的检查清单

参考 [`CLAUDE.md`](../CLAUDE.md) "修改代码前的检查清单"段。最重要 3 条：

1. **方案先行**：multi-file refactor 必须先 plan-first（CLAUDE.md 第 7 条）
2. **零依赖**：禁引入第三方 runtime 依赖（CLAUDE.md 第 9 条）
3. **测试先行**：跑 `python tests/test_all.py` 确认零回归再交差

### 如果你想加新引擎

参考 r55 Unity XUnity 接入路径（详见 [本文档 §6](#6-引擎抽象层)）：
1. `engines/your_engine.py` 实现 `EngineBase.{detect, extract_texts, write_back}`
2. `engines/engine_base.py` 加 `YOUR_PROFILE` 常量
3. `engines/engine_detector.py` 加 `EngineType.YOUR` + `_MANUAL_MAP` + `create_engine` 分支
4. `engines/__init__.py` export profile
5. `main.py` argparse choices 加 `your_engine`
6. `tests/test_your_engine.py` 至少 round-trip byte-identical 测试 + ≥ 1 集成测试
7. CHANGELOG / EVOLUTION / HANDOFF / docs/REFERENCE 同步

### 如果你不知道某段代码为什么这样写

1. 看 [`_archive/EVOLUTION.md`](../_archive/EVOLUTION.md) — 按轮次叙事（r1 → 当前）；详细历史在 r56-r60 / r61-r65 滚动归档文件
2. 看 git blame / git log — 每个 commit message 都尽量解释了 "why"
3. 看 [`CLAUDE.md`](../CLAUDE.md) "维护规则"段 — 15 条 hard contracts 含具体契约规则

> r66 retire ADR framework：架构决策已在 CLAUDE.md hard contracts + EVOLUTION 阶段叙事 + git history 完整记录。原 `docs/adr/` 目录 + 11 ADR 文件已删除。

---

## 1. 模块调用关系

```
gui.py (图形界面) ─── start_launcher.py (CLI 菜单) ─── tools/renpy_upgrade_tool.py
       │                      │
       └──────────────────────┘
                │ subprocess
                ▼
main.py (CLI 入口) → engines.resolve_engine(args.engine).run(args)
  │
  ├── engines/                        多引擎抽象层
  │    ├── engine_detector.py         检测 + CLI 路由
  │    ├── engine_base.py             EngineProfile / TranslatableUnit / EngineBase
  │    ├── generic_pipeline.py        6 阶段通用流水线
  │    ├── renpy_engine.py            薄包装，内部路由 translators/
  │    ├── rpgmaker_engine.py         RPG Maker MV/MZ
  │    └── csv_engine.py              CSV/JSONL/JSON
  │
  ├── translators/                    Ren'Py 三条管线
  │    ├── direct.py     + _direct_chunk / _direct_file / _direct_cli
  │    ├── tl_mode.py    + _tl_patches / _tl_dedup
  │    ├── retranslator.py
  │    ├── screen.py     + _screen_extract / _screen_patch
  │    ├── tl_parser.py  + _tl_postprocess / _tl_nvl_fix / _tl_parser_selftest
  │    └── renpy_text_utils.py
  │
  └── core/                           共享基础设施
       ├── api_client.py + api_plugin.py
       ├── prompts.py / glossary.py
       ├── translation_db.py / translation_utils.py
       ├── config.py / font_patch.py
       ├── http_pool.py        HTTPS 线程本地连接池 (~90s 节省)
       ├── pickle_safe.py      白名单 SafeUnpickler
       ├── file_safety.py      TOCTOU 防御 (fstat 二次校验)
       └── runtime_hook_emitter.py

file_processor/  splitter / patcher / checker / validator
pipeline/        helpers (评分) / gate (闸门) / stages (四阶段)
tools/           rpa_unpacker/packer / rpyc_decompiler / renpy_lint_fixer
                 renpy_upgrade_tool / translation_editor / merge_translations_v2
                 review_generator / analyze_writeback_failures
custom_engines/  用户自定义翻译引擎插件 (example_echo.py 示例)
scripts/         verify_docs_claims.py / verify_workflow.py / install_hooks.sh
```

**统一入口契约**：`main.py` 不再分派 translators/，所有 `--engine` 值（含 `auto` / `renpy`）都走 `engines.resolve_engine(...).run(args)`。Ren'Py 的 tl-mode / tl-screen / retranslate / direct 四个分支由 `engines/renpy_engine.py::RenPyEngine.run()` 内部路由。

---

## 2. 三种翻译模式数据流

### 2.1 Direct-mode（默认）

```
run_pipeline(args) [translators/direct.py]
  ├─ 初始化：APIClient / Glossary / ProgressTracker / TranslationDB
  ├─ 扫描 .rpy → 排除引擎(renpy/lib/) → 排除 --exclude → tl-priority 过滤
  ├─ 按文件大小升序排列（小文件优先积累翻译记忆）
  └─ 逐文件翻译：
      translate_file()
        ├─ 文件名 ∈ SKIP_FILES_FOR_TRANSLATION → [SKIP-CFG] 直接复制
        ├─ calculate_dialogue_density() < 阈值 → _translate_file_targeted()
        └─ 密度 ≥ 阈值 → split_file() → 逐 chunk 翻译：
            _translate_chunk_with_retry()
              ├─ _should_retry() → (should, needs_split)
              ├─ needs_split=True → _split_chunk()（label > 空行 > 二等分）→ 合并
              └─ _translate_chunk()
                    ├─ prev_context: 前一 chunk 末尾 5 行
                    ├─ protect_placeholders() → __RENPY_PH_N__ 令牌
                    ├─ client.translate()
                    ├─ restore_placeholders()
                    ├─ check_response_item() + check_response_chunk()
                    └─ 不通过 → 丢弃保留原文，status="checker_dropped"
                    → ChunkResult dataclass 封装返回值
      apply_translations()  行级回写，四遍匹配，第四遍跳过 modified_lines
      validate_translation()  50+ 项校验
      glossary.update_from_translations()  翻译记忆学习
```

**密度自适应路由**：阈值 `--min-dialogue-density` 默认 0.20。低密度（多代码少对话）→ 提取对话行 + ±3 行上下文定向翻译；高密度 → 整文件按块拆分全量翻译。

### 2.2 tl-mode（`--tl-mode --tl-lang chinese`）

```
run_tl_pipeline(args) [translators/tl_mode.py]
  ├─ scan_tl_directory() 扫描 tl/<lang>/*.rpy（排除 common.rpy）
  ├─ get_untranslated_entries() 筛选空槽位
  │   ├─ DialogueEntry: translation == ""
  │   └─ StringEntry: new == ""
  ├─ build_tl_chunks()  每 chunk ≤ 30 条；含 \n 自动加 [MULTILINE]
  ├─ ThreadPoolExecutor 并发翻译
  │   └─ per-chunk: protect → API → restore(id/original/zh) → check_response_item
  ├─ 匹配阶段：
  │   ├─ DialogueEntry: identifier hash 精确匹配
  │   └─ StringEntry: 四层 fallback（精确 → strip → 去占位符令牌 → 转义规范化）
  └─ fill_translation() 行级精确回填
      └─ str.replace 只替换第一个 "" → "译文"（保留缩进/character 前缀）
      └─ 引号剥离保护：ASCII "" / 弯引号 "" / 全角 ＂＂
  └─ postprocess_tl_directory()：移除 nvl clear + 补 pass
  └─ fix_nvl_ids_directory()：8.6+ say-only → 7.x nvl+say 哈希
```

**关键设计**：
- tl_parser.py 状态机（IDLE/DIALOGUE/STRINGS/SKIP），UTF-8 BOM 处理
- 回填精度远高于 direct-mode（行号定位 vs 文本匹配），消除回写失败类漏翻
- .bak 备份首次回填前创建，不覆盖已有
- 独立进度文件 `tl_progress.json`
- 并发安全：RateLimiter / UsageStats / ProgressTracker 均自带 threading.Lock

### 2.3 Retranslate（`--retranslate`）

```
retranslate_file() [translators/retranslator.py]
  ├─ find_untranslated_lines()  检测残留英文行
  │   └─ 排除 auto/hover/idle 定义、image 路径、screen 布局属性
  ├─ build_retranslate_chunks()  每 chunk ≤ 20 漏翻行 + ±3 上下文，合并重叠
  ├─ 专用 retranslate prompt（>>> 标记行必须翻译，上下文仅参考）
  │   └─ build_retranslate_system_prompt() 中文模板（round 52 C4 BREAKING：
  │       multi-target language path 已 retired，hardcoded zh-only）
  ├─ 原地补翻，.bak 自动备份（不覆盖已有）
  └─ 独立进度文件 retranslate_progress.json
```

---

## 3. 四阶段一键流水线（one_click_pipeline.py）

```
main() 纯编排入口
  ├─ (--tl-mode) → _run_tl_mode_phase()  跳过试跑直接 tl 全量翻译
  └─ (direct-mode)
      ├─ Stage 1/4 → _run_pilot_phase()
      │   pick_pilot_files(): score = min(size/1KB, 200)
      │                             + 80 if risk_keyword
      │                             + 30 if sazmod
      │   → run_main() 翻译 → evaluate_gate() → AI 术语提取
      │   → errors > 0 中止；ratio 超阈值警告继续
      ├─ Stage 2/4 → _run_full_translation_phase()  全量翻译 + 闸门
      ├─ Stage 3/4 → _run_retranslate_phase()       原地补翻
      └─ Stage 4/4 → _run_final_report()
          evaluate_gate() + attribute_untranslated() + zip 打包
```

**目录结构**：

```
output/projects/<project_name>/
  ├─ stage2_translated/    全量翻译结果
  ├─ _pipeline/
  │   ├─ pilot_input/      试跑输入
  │   ├─ pilot_output/     试跑输出
  │   └─ *.log
  └─ pipeline_report.json
```

---

## 4. 核心算法

### 4.1 Token 估算
```python
token_count = ascii_chars // 4 + non_ascii_chars // 2 + 1
```

### 4.2 占位符保护
```
"[name] says: {color=#f00}Hello{/color}"
→ "__RENPY_PH_0__ says: __RENPY_PH_1__Hello__RENPY_PH_2__"
映射: [(0, "[name]"), (1, "{color=#f00}"), (2, "{/color}")]
```

### 4.3 文件拆分策略（`split_file`）
1. 识别顶层 Ren'Py 块边界（label / screen / define / init / translate / menu 等）
2. 按块累积 token，超过 `max_chunk_tokens`（默认 4000）时断开
3. 单块超限 → 按行数拆分，优先空行处断开
4. 每个 chunk 携带行偏移量（`base_line_offset`），确保多块重组

### 4.4 风险评分（试跑文件选择）
```python
score = min(file_size / 1024, MAX_FILE_RANK_SCORE)
      + RISK_KEYWORD_SCORE * (any keyword in filename)
      + SAZMOD_BONUS_SCORE * ("sazmod" in filename)
```

### 4.5 tl-mode StringEntry 四层 fallback 匹配
1. 精确匹配 `entry.old == api_returned_id`
2. strip 空白后匹配
3. 去占位符令牌后匹配
4. 转义规范化（`\"` → `"`, `\n` → 换行）后匹配

---

## 5. 引擎抽象层

### 5.1 EngineProfile 数据类

引擎差异的参数化描述，让 `protect_placeholders()` 和 `validate_translation()` 根据引擎调整行为。

| 字段 | 类型 | 用途 |
|------|------|------|
| `name` | `str` | 引擎标识符（`"renpy"` / `"rpgmaker_mv"` / `"csv"`） |
| `display_name` | `str` | 用户可见名称 |
| `placeholder_patterns` | `list[str]` | 占位符正则列表，用于 `protect_placeholders` 参数化 |
| `skip_line_patterns` | `list[str]` | 不翻译的行模式正则 |
| `encoding` | `str` | 文件默认编码 |
| `max_line_length` | `int \| None` | 译文行宽限制 |
| `prompt_addon_key` | `str` | 引擎专属 prompt 片段查找 key |
| `supports_context` | `bool` | 提取时是否提供上下文行 |
| `context_lines` | `int` | 上下文行数（默认 3） |

辅助方法：`compile_placeholder_re()` / `compile_skip_re()` 编译为单个正则。

内置 Profile：`RENPY_PROFILE` / `RPGMAKER_MV_PROFILE` / `CSV_PROFILE`，注册在 `ENGINE_PROFILES` 字典。

### 5.2 TranslatableUnit 数据类

所有非 Ren'Py 引擎共用的文本单元（Ren'Py 有自己的 DialogueEntry / StringEntry）。

| 字段 | 类型 | 用途 |
|------|------|------|
| `id` | `str` | 全局唯一标识 |
| `original` | `str` | 原文 |
| `context` / `speaker` | `str` | 上下文行 / 说话人 |
| `file_path` | `str` | 来源文件相对路径 |
| `metadata` | `dict` | 引擎专属元数据（write_back 的定位关键），通用流水线只透传不碰 |
| `translation` | `str` | 翻译结果 |
| `status` | `str` | `pending` / `translated` / `checker_dropped` / `ai_not_returned` / `skipped` |

### 5.3 EngineBase 抽象基类

**必须实现**：`_default_profile()` / `detect(game_dir)` / `extract_texts(game_dir)` / `write_back(game_dir, units, output_dir)`

**可选覆写**：`post_process()`（默认无）、`run(args)`（默认走 generic_pipeline）、`dry_run()`（默认统计 extract）

### 5.4 新引擎添加流程（7 步）

1. 新建 `engines/xxx_engine.py`：继承 EngineBase，实现 4 个抽象方法
2. 新建 EngineProfile：在 `engine_base.py` 添加 `XXX_PROFILE`，注册到 `ENGINE_PROFILES`
3. 更新 `engine_detector.py`：`detect_engine_type()` + `create_engine()` + `resolve_engine()` manual_map
4. 更新 `core/prompts.py`：在 `_ENGINE_PROMPT_ADDONS` 添加引擎 prompt
5. 可选：更新 `core/glossary.py` 添加角色/术语扫描
6. 新增测试：`tests/test_engines.py` 添加检测、提取、回写测试
7. 更新文档：README "支持引擎"列表 + CLI `--engine` choices

### 5.5 零依赖约束处理

| 场景 | 处理 |
|------|------|
| RPG Maker VX/Ace 需 `rubymarshal` | 可选功能，缺依赖时 pip install 提示 |
| Unity AssetBundle 需 `UnityPy` | 不直接支持，通过 XUnity 导出文本间接支持 |
| Kirikiri .scn 需二进制解析 | 优先 .ks 文本格式，.scn 通过 VNTextPatch CSV |
| 老日系编码（Shift_JIS/EUC-JP） | EngineProfile.encoding 指定 |

### 5.6 自定义翻译引擎插件

放在 `custom_engines/<module>.py`，实现 `translate_batch(system_prompt, user_prompt) -> str | list[dict]`（subprocess 协议只走 batch；round 28 引入的单句 `translate()` host-side fallback 仅在已 retire 的 importlib 模式下生效）。

**运行模式**（round 28 S-H-4 引入 opt-in sandbox；**round 52 BREAKING：unconditional sandbox**，importlib in-process loader retired）：

| 模式 | CLI | 隔离级别 | 启动 | 备注 |
|------|------|---------|------|------|
| Subprocess sandbox | `--provider custom --custom-module NAME` | subprocess + JSONL，独立进程，无法访问 host env vars / fd / heap | ~100-150ms 启动 + ~5-15ms/call | 唯一模式（r52 起） |

**Plugin 必备结构**：plugin 文件必须包含 `if __name__ == "__main__":` block，在收到 `--plugin-serve` argv 时调用 `_plugin_serve()` 跑 JSONL serve loop（参考 `custom_engines/example_echo.py`）。缺失该 block 的 plugin 在 `_SubprocessPluginClient.__init__` 的 readiness probe 里立即失败并显示迁移指引。

**Sandbox 协议**：
- Request：`{"request_id": <int>, "system_prompt": <str>, "user_prompt": <str>}`
- Response：`{"request_id": <int>, "response": <str|null>, "error": <str|null>}`
- Shutdown：`{"request_id": -1}` + 关闭 stdin
- 超时：宿主用 `APIConfig.timeout`（默认 180s）；超时 `proc.kill()` + `wait(2)`
- stderr 截断：插件异常退出时宿主读取 stderr tail（< 10KB），消息 ≤ 600 字符
- stdout per-line cap：`_MAX_PLUGIN_RESPONSE_CHARS = 50 * 1024 * 1024`（**chars 不是 bytes** — Popen `text=True` 模式下 `readline(N)` 的 N 计算解码后字符数；CJK 响应最坏字节 ~150 MB）

完整示例参见 `custom_engines/example_echo.py`。

---

## 6. 翻译质量保障链

### 6.1 发送前保护

```
protect_placeholders()
  [name] → __RENPY_PH_0__
  {color=#f00} → __RENPY_PH_1__
  %(var)s → __RENPY_PH_2__
  → 按出现顺序全局去重，生成映射 list[(index, original)]
```

### 6.2 返回后校验（ResponseChecker）

```
check_response_item(item, placeholder_re=None):
  ├─ 占位符集合一致性（原文 vs 译文）
  ├─ 原文非空 + 译文非空（硬编码读 item["zh"]）
  └─ 不通过 → status="checker_dropped"，保留原文

check_response_chunk():
  └─ 条数一致性（启发式 _count_translatable_lines_in_chunk）
```

**Round 52 C4 BREAKING**：r35-r48 多语言 5 层 contract（prompt per-lang / alias-read / checker per-lang / zh-tw 隔离 / generic fallback）已**完全删除**，目标语言固定 zh，response 字段名硬编码 `"zh"`。`core/lang_config.py` 文件已删除，`resolve_translation_field()` 已删除。

### 6.3 回写后校验（`validate_translation`，50+ 项）

详见 [REFERENCE.md](REFERENCE.md) "Error / Warning Code 索引"。

### 6.4 数据采集与归因

- **per-chunk 指标**：`report.json` → chunk_stats（expected / returned / dropped）
- **漏翻归因**：`attribute_untranslated()` → 四分类（AI 未返回 ~71% / 回写失败 ~28% / Checker 丢弃 ~1% / 未知）
- **translation_db** 记录每条翻译完整元数据，支持增量归因查询

---

## 7. API 集成 + 安全

### 7.1 提供商

xAI / OpenAI / DeepSeek / Claude / Gemini 五大 + 自定义引擎插件。精确定价表在 `core/api_client.py::_MODEL_PRICING`。

### 7.2 JSON 解析容错链（6 级降级）

1. 直接 `json.loads()`
2. 从 Markdown 代码块提取 ` ```json...``` `
3. 搜索第一个 `[` 到最后一个 `]`
4. 修复尾部逗号
5. 正则逐项提取 JSON 对象
6. 字段顺序容错

### 7.3 速率控制

- `RateLimiter`：线程安全 RPM + RPS 双重限制
- 指数退避重试：429/5xx 自动重试，jitter 抖动，优先 `Retry-After` 头，退避上限 60s
- `UsageStats`：线程安全 token 用量 + 费用实时统计
- 推理模型检测：reasoning model thinking tokens 按 3-5× 计费

### 7.4 资源边界与 OOM 防护

**所有用户面 + 内部 JSON loader 加 50 MB size cap**（详见 [REFERENCE.md](REFERENCE.md) "OOM 防护" section）。

**插件强制 subprocess 沙箱**（round 52 BREAKING）：
- 所有 custom plugin 在独立 subprocess 中运行，无法访问 host env vars / file descriptors / heap
- `_SubprocessPluginClient.__init__` 启动期 readiness probe（5 × 20ms 轮询）检测无 `--plugin-serve` 块的 plugin → 立即 raise 迁移指引
- Legacy importlib in-process loader（pre-r52）已 retire；零迁移路径，旧 plugin 必须加 `if __name__ == "__main__": _plugin_serve()` block

**插件子进程三通道防护**：
- **stdout**：`_MAX_PLUGIN_RESPONSE_CHARS = 50M chars` 单行上限
- **stderr**：`stderr.read(10_000)` 10 KB（取尾 600 字符 crash-diag）
- **stdin**：由 `_SHUTDOWN_REQUEST_ID = -1` 控制 lifecycle

**HTTP 响应体**：`MAX_API_RESPONSE_BYTES = 32 MB`，`read_bounded` 共享工具统一 pool + urllib 双路径。

### 7.5 TOCTOU 防御（Round 49 完成）

整个 user-facing JSON ingestion surface **26 sites / 12 modules 全 TOCTOU MITIGATED**（attack window 缩到 microsecond 级 fstat-on-fd）。共享 helper `safety/file_safety.py::check_fstat_size`，pattern：

```python
fsize = path.stat().st_size           # path-based fast path
if fsize > _MAX_X_SIZE: warn + skip   # 拒绝巨型文件 before open
with open(path, encoding=...) as f:
    ok, fsize2 = check_fstat_size(f, _MAX_X_SIZE)  # TOCTOU defense
    if not ok: warn TOCTOU + skip/return/continue/raise
    data = json.loads(f.read())
```

---

## 8. 测试体系

### 8.1 文件结构

测试文件总数 + 用例总数：见 `HANDOFF.md` 顶部 `VERIFIED-CLAIMS` 块（`test_files` / `tests_total`）。

```
tests/
├─ test_all.py              meta-runner，聚合 6 focused suites
├─ smoke_test.py            校验规则冒烟
├─ test_api_client.py       core.api_client (APIConfig/UsageStats/RateLimiter/JSON 解析/定价/HTTP)
├─ test_file_processor.py   splitter / checker / patcher / validator
├─ test_translators.py      direct chunk / tl_parser / retranslator / screen
├─ test_glossary_prompts_config.py   glossary / locked_terms / prompts / config
├─ test_translation_state.py         ProgressTracker / TranslationDB / dedup
├─ test_engines.py + test_engines_rpgmaker.py + test_csv_engine.py
├─ test_runtime_hook.py + test_runtime_hook_filter.py + test_runtime_hook_v2_schema.py
├─ test_translation_editor.py + test_translation_editor_v2.py
├─ test_merge_translations_v2.py
├─ test_custom_engine.py + test_sandbox_response_cap.py
├─ test_file_safety.py + test_file_safety_c5.py
├─ test_translation_db_language.py + test_multilang_run.py
├─ test_progress_tracker_language.py + test_override_categories.py
├─ test_ui_whitelist.py
├─ test_rpa_unpacker.py + test_rpyc_decompiler.py + test_lint_fixer.py
├─ test_tl_dedup.py + test_batch1.py
├─ test_direct_pipeline.py + test_tl_pipeline.py    集成测试
├─ test_verify_docs_claims.py                       drift checker 自测
└─ test_single.py                                   端到端（需 API）
```

### 8.2 内建 self-test

- `python -c "from translators._tl_parser_selftest import run_self_tests; run_self_tests()"` — 75 断言
- `python -c "from translators.screen import _run_self_tests; _run_self_tests()"` — 51 断言

### 8.3 数据 fixture

| 文件 | 用途 |
|------|------|
| `tests/sample_triggers.rpy` + `_trans.rpy` | 触发各 W/E 代码的原文/译文样本 |
| `tests/glossary_test.json` | 含 locked_terms / no_translate 的术语表 |
| `tests/sample_strings.rpy` | translate strings 块样本 |
| `tests/fixtures/strings_only/` | strings 统计隔离子目录 |
| `tests/tl_priority_mini/` | tl 优先模式最小目录结构 |
| `tests/artifacts/` | 实际项目 untranslated JSON（projz / tyrant） |

### 8.4 执行方式

> **⚠️ meta-runner 是 smoke subset，不等于全量 `tests_total`**
>
> `tests/test_all.py` 仅聚合 6 个 focused suites（见 `tests/test_all.py` 顶部 docstring 列表）— 覆盖 core/translators/file_processor/glossary/state/runtime_hook 主路径，是 ~5s 的快通道。
>
> 全量 `tests_total`（见 `HANDOFF.md` `VERIFIED-CLAIMS` 块，~3× meta-runner）含 engine / RPA / rpyc / editor / pipeline / file_safety / 端到端集成等独立 suite，**只在 CI 或本地分别运行各独立 suite 时跑齐**。pre-commit hook 用 meta-runner（速度优先），不代表零回归 — 真实零回归看 CI 6 jobs 全绿。

**本地快速验证**：
```bash
python tests/test_all.py                    # meta-runner（6 focused suites，~5s smoke）
python scripts/verify_docs_claims.py --fast # docs claim 同步性检查（~1s）
```

**完整本地 sweep**（pre-commit 不跑，CI 跑）：
```bash
# 各独立 suite 单独运行（pwsh 一行：Get-ChildItem tests/test_*.py | % { python $_.FullName }）
python tests/test_engines.py
python tests/test_engines_rpgmaker.py
python tests/test_csv_engine.py
# ... 其余独立 suite（数量见 VERIFIED-CLAIMS.test_files）
python scripts/verify_docs_claims.py --full # 实跑 CI 全部 Run-* steps
```

**CI**：
- 6 jobs（matrix `[ubuntu-latest, windows-latest]` × `[3.10, 3.12, 3.13]`，r57 T1 起 — `pyproject.toml requires-python = ">=3.10"`）
- 步骤数见 `VERIFIED-CLAIMS.ci_steps`
- 关键步骤：py_compile + meta + 22 独立 suite + 2 self-test + verify_docs_claims unit + push-status (r52 C1) + `--full` + mock target consistency check + build.py smoke (r52 C2) + 零依赖检查 + mypy informational + integration dry-run

### 8.5 pre-commit hook（4 件套）

`.git-hooks/pre-commit`（通过 `scripts/install_hooks.sh` 启用）：

1. py_compile 所有 staged .py 文件
2. file-size guard：>800 行 .py 直接 block
3. meta-runner（`tests/test_all.py`，~5s）
4. `verify_docs_claims --fast`（~1s）

总耗时 7-12 秒。Bypass：`git commit --no-verify`（仅紧急情况，需在 commit body 说明原因）。
