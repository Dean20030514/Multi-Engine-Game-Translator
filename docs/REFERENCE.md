# 参考手册

本文档汇总：可配置常量速查、Error/Warning 代码索引、引擎与架构路线图。

> 模块图、数据流、引擎指南、测试体系：见 [ARCHITECTURE.md](ARCHITECTURE.md)
> 历史决策：见 [_archive/EVOLUTION.md](../_archive/EVOLUTION.md)

---

## 1. 校验相关常量

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `MODEL_SPEAKING_PATTERNS` | `file_processor/checker.py` | 7 条模式 | W440 模型自述检测关键词 |
| `PLACEHOLDER_ORDER_PATTERNS` | `file_processor/checker.py` | 4 组 (regex, name) | W251 占位符顺序提取 |
| `MIN_CHINESE_RATIO` | `file_processor/validator.py` | 0.05 | W442 中文占比阈值 |
| `LEN_RATIO_LOWER / UPPER` | `pipeline/helpers.py` | 0.15 / 2.5 | W430 长度异常阈值 |

## 2. 翻译流程相关常量

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `SKIP_FILES_FOR_TRANSLATION` | `file_processor/checker.py` | `{define, variables, screens, earlyoptions, options}.rpy` | 跳过翻译的配置文件 |
| `CHECKER_DROP_RATIO_THRESHOLD` | `core/translation_utils.py` | 0.3 | chunk 丢弃率重试阈值 |
| `MIN_DROPPED_FOR_WARNING` | `core/translation_utils.py` | 3 | 最小丢弃数触发警告 |
| `MIN_DIALOGUE_LENGTH` | `core/translation_utils.py` | 4 | 定向翻译最小对话长度 |
| `MAX_MEMORY_ENTRIES` | `core/glossary.py` | 10000 | 翻译记忆最大条目数 |
| `SAVE_INTERVAL` | `core/translation_utils.py` | 10 | 批量写入间隔（每 N 次 mark 写磁盘） |
| `_PH_TOKEN_RE` | `core/translation_utils.py` | `__RENPY_PH_\d+__` | 占位符令牌正则 |
| `_QUOTE_STRIP_PAIRS` | `translators/tl_parser.py` | ASCII "" / 弯引号 "" / 全角 ＂＂ | fill_translation 引号剥离 |
| 截断匹配阈值 | `file_processor/patcher.py:414` | 0.7 | AI 截断文本匹配阈值 |

## 3. 流水线常量

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `RISK_KEYWORDS` | `pipeline/helpers.py` | 14 个关键词 | 试跑文件风险评分 |
| `MAX_FILE_RANK_SCORE` | `pipeline/helpers.py` | 200 | 文件大小评分上限 |
| `RISK_KEYWORD_SCORE` | `pipeline/helpers.py` | 80 | 风险关键词加分 |
| `SAZMOD_BONUS_SCORE` | `pipeline/helpers.py` | 30 | SAZMOD 模组额外加分 |

## 4. 文本分析常量

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `MIN_UNTRANSLATED_TEXT_LENGTH` | `translators/renpy_text_utils.py` | 20 | 漏翻检测最小文本长度 |
| `MIN_ENGLISH_CHARS_FOR_UNTRANSLATED` | `translators/renpy_text_utils.py` | 12 | 漏翻检测最小英文字符数 |
| `_MODEL_PRICING` | `core/api_client.py` | ~20 个模型 | 精确定价表 |

---

## 5. OOM 防护 — 50 MB 文件大小上限

所有用户面 + 内部 JSON/text loader 在 `json.loads()` 或 `read_text()` 前加 `stat().st_size` gate，超限 warning + fallback。合法文件（< 50 MB）行为完全不变。

**阈值选择 rationale**：
- 50 MB 远超任何 legitimate 场景（典型 `translation_db.json` 几百 KB；游戏 RPG Maker `Map001.json` 低 MB；glossary 几十 KB）
- 与 `MAX_API_RESPONSE_BYTES = 32 MB` 同量级
- 每个 loader 独立 `_MAX_*_SIZE` 常量而非共享 helper — 每 module 可独立调阈值；TOCTOU 二次校验则共享 `safety.file_safety.check_fstat_size`（r49 抽取，r56 M2 从 `core/` 移到顶层 `safety/` 包以避免 `file_processor` 间接 import `core` 的 layering 误解）

### 5.1 User-facing loaders（operator-supplied path）

| 常量 | 位置 |
|------|------|
| `_MAX_FONT_CONFIG_SIZE` | `core/font_patch.py` |
| `_MAX_TRANSLATION_DB_SIZE` | `core/translation_db.py` |
| `_MAX_EDITOR_INPUT_SIZE` | `tools/translation_editor.py`（覆盖 `_extract_from_db` + `import_edits`） |
| `_MAX_CONFIG_FILE_SIZE` | `core/config.py` |
| `_MAX_GLOSSARY_JSON_SIZE` | `core/glossary.py`（4 caller 共享 `_json_file_too_large` helper） |
| `_MAX_REVIEW_DB_SIZE` | `tools/review_generator.py` |
| `_MAX_ANALYZE_DB_SIZE` | `tools/analyze_writeback_failures.py` |
| `_MAX_GATE_GLOSSARY_SIZE` | `pipeline/gate.py` |
| `_MAX_RPGM_JSON_SIZE` | `engines/rpgmaker_engine.py`（2 sites） |
| `_MAX_CSV_JSON_SIZE` | `engines/csv_engine.py`（3 readers） |
| `_MAX_GUI_CONFIG_SIZE` | `gui_dialogs.py` |
| `_MAX_UI_WHITELIST_SIZE` | `file_processor/checker.py` |

### 5.2 Internal loaders（pipeline-generated / progress file）

| 常量 | 位置 |
|------|------|
| `_MAX_PROGRESS_JSON_SIZE` | `engines/generic_pipeline.py` / `core/translation_utils.py::ProgressTracker._load` / `translators/_screen_patch.py` |
| `_MAX_REPORT_JSON_SIZE` | `pipeline/stages.py`（2 sites） |

### 5.3 TOCTOU 二次校验（Round 49 完成）

整个 user-facing JSON ingestion surface **26 sites / 12 modules 全 TOCTOU MITIGATED**。共享 helper：

- 位置：`safety/file_safety.py::check_fstat_size(file_obj, max_size) -> tuple[bool, int]`
- 93 行 stdlib-only，fail-open on `(OSError, ValueError)`
- 23 expansion regression 集中到 `tests/test_file_safety.py` (12 C4) + `tests/test_file_safety_c5.py` (11 C5)
- 所有 mock 统一打 `safety.file_safety.os.fstat`（防 r48 mock target stale CRITICAL 重演 — CI grep step 兜底）

**Symlink TOCTOU defense-in-depth**（r53 监控 #4 mitigation）：
- 当前 r49 fstat helper 把 race window 收紧到 microsecond 级 fd-based fstat
- POSIX `open(link)` 在 t0 解析 → relink → fstat 在 t2 sees inode_B 的 path-swap symlink TOCTOU 在理论上仍可触发
- **r53 mitigation**：`main.py::_maybe_warn_on_symlink` 在 `--game-dir` / `--config` 是 symlink 时输出 warning（非阻断），`--allow-symlink` 抑制（NAS / 挂载场景）。其他 path 入口（`--output-dir` / `--font-file` / `--font-config` / `--ui-button-whitelist`）暂未加，因风险 surface 小（用户提供小文件 vs 整个游戏目录）
- 当前威胁评估：本地单机工具无 multi-tenant 场景，attacker 已有本地 RW 权限即可 — 比 symlink TOCTOU 严重得多。当前 codebase **无 realistic exploit vector**；warning 仅作审计提示

**TOCTOU fstat 自身 race window**（r53 监控 #3 architectural decision）：
- 当前实现：`open()` → `os.fstat(fd)` 在 microsecond 级 OS-atomic 边界
- 进一步 narrow 依赖 OS-level FD-ops 实现细节（fstat 内部 syscall 时序），无 actionable improvement path
- r53 末决定：维持当前实现，retire 监控；如未来 OS-level 改进或工具链升级提供新原语再 reconsider

**Pickle 白名单红队 verified safe**（r53 监控 #1 architectural decision）：
- `tests/test_pickle_safe_redteam.py` 8 测试覆盖直接调用 gadget (os.system / subprocess.Popen / eval / exec) + chain attack 尝试 (`_codecs.encode` 仅产 inert bytes / `_reconstructor` 在 base resolve 阶段被拒) + 边界控制 (legitimate roundtrip / arbitrary class default-deny)
- 任何向 `_SAFE_BUILTINS` / `_SAFE_COLLECTIONS` / `_SAFE_CODECS` / `_SAFE_COPYREG` 添加新 entry 必须先跑红队 audit（CLAUDE.md hard contract）

---

## 6. 其他内存 / 资源上限

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `MAX_API_RESPONSE_BYTES` | `core/api_client.py` (re-export from `core/http_pool.py`) | 32 MB | HTTPS 响应体上限（r53 监控 #2：精度偏差从 65535 B 降至 1 B，`read_bounded` chunk size 自适应 `min(_READ_CHUNK_SIZE, limit - total + 1)`） |
| `_MAX_PLUGIN_RESPONSE_CHARS` | `core/api_plugin.py` | 50M chars | plugin subprocess stdout per-line cap（**chars 不是 bytes** — Popen text mode；CJK 响应最坏字节 ~150 MB） |
| `_MAX_PLUGIN_RESPONSE_BYTES` | `core/api_plugin.py` | alias | r43 原 name，r44 保留作 backward-compat alias |
| plugin stderr | `core/api_plugin.py` | `read(10_000)` | 取尾 600 字符显示 |
| `MAX_LOG_LINES` / `TRIM_TO` | `gui_pipeline.py` | 5000 / 3000 | GUI 日志 Text widget 行数上限 / 裁剪目标 |

---

## 7. API 调用默认参数（`core/api_client.py::APIConfig`）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `rpm` | 0 | 每分钟请求数；0 = 不限（由 `--rpm` 覆盖） |
| `rps` | 0 | 每秒请求数；0 = 不限 |
| `timeout` | 180.0 秒 | 推理模型自动提升到 ≥ 300.0 秒 |
| `temperature` | 0.1 | 低温保证一致性 |
| `max_retries` | 5 | 429/5xx 自动重试上限 |
| `max_response_tokens` | 32768 | response 的 max_tokens 参数 |
| `use_connection_pool` | True | HTTPS 连接池（节省 ~90s / 600 次调用） |

> **Round 52 BREAKING removal**：`sandbox_plugin: bool = False` field 已删除。所有 `provider="custom"` 自动走 JSONL subprocess sandbox（`_SubprocessPluginClient`）；importlib in-process loader 已 retire。

---

## 8. 速率限制 + 退避重试

| 常量 / 行为 | 位置 | 说明 |
|------|------|------|
| RPM / RPS 双重限制 | `core/api_client.py::RateLimiter` | 线程安全；`_second_counts` 批量清理 |
| 429 / 5xx 自动重试 | `core/api_client.py::translate` | 指数退避 + jitter；优先 `Retry-After` 头；退避上限 60 秒 |

---

## 9. 模型定价表

`core/api_client.py::_MODEL_PRICING`：精确匹配优先、按 model name 前缀 fallback、最终 `(input, output, False)` unknown 降级。

| 提供商 | `--provider` | 默认模型 | 输入/输出 ($/M tokens) |
|--------|-------------|---------|------------------------|
| xAI | `xai` / `grok` | grok-4-1-fast-reasoning | $0.20 / $0.50 |
| OpenAI | `openai` | gpt-4o-mini | $0.15 / $0.60 |
| DeepSeek | `deepseek` | deepseek-chat | $0.14 / $0.28 |
| Claude | `claude` | claude-sonnet-4 | $3.00 / $15.00 |
| Gemini | `gemini` | gemini-2.5-flash | $0.15 / $0.60 |

reasoning models（`grok-*-reasoning` / `deepseek-reasoner` / `o3-mini` 等）的 thinking tokens 按 3-5× 计费。

---

## 10. Chunk / Pipeline 默认参数

| 字段 / 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `--workers` (chunk 级并发) | `main.py` argparse | 3 | 同一文件内 chunk 并发翻译数 |
| `--file-workers` (文件级并发) | `main.py` argparse | 1 | 同时翻译的文件数 |
| `max_chunk_tokens` | `main.py` argparse | 4000 | chunk 切分上限；超过则 `_force_split` |
| `min_dialogue_density` | `main.py` argparse | 0.20 | 低于此密度文件降级为 targeted 模式 |
| `--pilot-count` | `main.py` argparse | 20 | 试跑文件数 |
| `--gate-max-untranslated-ratio` | `main.py` argparse | 0.08 | 闸门最大漏翻比 |

---

## 11. 语言配置

> **Round 52 C4 BREAKING removal**：`core/lang_config.py` 整个文件已删除。r35-r48 多目标语言 contract（zh / zh-tw / ja / ko）+ `LANGUAGE_CONFIGS` dict + `LanguageConfig` dataclass + `resolve_translation_field()` + 5 层 contract（prompt / alias-read / checker / zh-tw 隔离 / generic fallback）+ `--target-lang` flag + `args.target_lang` outer loop + `args.target_langs` parsing + `args.lang_config` 全部 retire。
>
> **目标语言固定 zh 简体中文**。LLM response 字段名硬编码 `"zh"`。MIN_CHINESE_RATIO（0.05）成为唯一的 W442 阈值。
>
> 已有 v2 schema translation_db.json：跑 `python scripts/migrate_db_v2_to_v1.py output/translation_db.json` 迁移到 v1 flat。

---

## 12. Error / Warning Code 索引

**处理原则**：E 级错误 → 丢弃翻译保留原文；W 级警告 → 保留翻译但记录日志。

| Code | 级别 | 含义 | 处理 |
|------|------|------|------|
| E210_VAR_MISSING | error | 译文缺少原文中的 `[var]` 变量 | 丢弃翻译 |
| W211_VAR_EXTRA | warning | 译文含原文没有的 `[var]` 变量 | 保留但告警 |
| E220_TEXT_TAG_MISMATCH | error | `{tag}` 配对不一致 | 丢弃翻译 |
| E230_MENU_ID_MISMATCH | error | `{#id}` 菜单标识符不一致 | 丢弃翻译 |
| E240_FMT_PLACEHOLDER_MISMATCH | error | `%(name)s` 格式化占位符不一致 | 丢弃翻译 |
| W251_PLACEHOLDER_ORDER | warning | 占位符顺序与原文不一致（集合相同） | 仅告警，仍 apply |
| W410_GLOSSARY_MISS | warning | 术语表未命中 | 告警 |
| E411_GLOSSARY_LOCK_MISS | error | 锁定术语未使用规定译名 | 标记错误 |
| E420_NO_TRANSLATE_CHANGED | error | 禁翻片段被修改 | 标记错误 |
| W430_LEN_RATIO_SUSPECT | warning | 译文长度比例异常 | 告警 |
| W440_MODEL_SPEAKING | warning | 模型自我描述/多余解释 | 告警 |
| W441_PUNCT_MIX | warning | 中英标点连续混用 | 告警 |
| W442_SUSPECT_ENGLISH_OUTPUT | warning | 中文占比极低，疑似未翻译 | 告警 |
| E250_CONTROL_TAG_DAMAGED | error | Ren'Py 控制标签在译文中缺失 | 标记错误 |
| W460_POSSIBLE_OVERTRANSLATION | warning | Ren'Py 关键字可能被过度翻译 | 告警 |
| W470_CONSECUTIVE_PUNCTUATION | warning | 连续中文标点（。。、！！） | 告警 |

---

## 13. 引擎路线图

### 13.1 已完成

| 引擎 | 优先级 | 占比 | 依赖 | 完成 |
|------|--------|------|------|------|
| Ren'Py | P0 | ~35% | 纯标准库 | r1 |
| RPG Maker MV/MZ | P0 | ~25% | 纯标准库 | r28 |
| CSV/JSONL/JSON 通用 | P0 | 覆盖全部 | 纯标准库 | r28 |
| Unity (XUnity AutoTranslator) | P2 | ~10% | 纯标准库（不解析 AssetBundle） | **r55** |

### 13.2 待实现（r55 末剩余 actionable，按 ROI 排序）

| 优先级 | 引擎 | 占比 | 难度 | 依赖 |
|--------|------|------|------|------|
| 🟡 P1 | Godot | ~3% | 低 | 纯标准库 |
| 🟢 P2 | Kirikiri 2/Z | ~5% | 中 | 参考 VNTextPatch |
| 🟢 P2 | TyranoBuilder | ~3% | 低 | .ks 脚本 |

### 13.3 各引擎实现要点

- **Unity / XUnity（P2，r55 完成）**：不解析 AssetBundle；只处理 XUnity AutoTranslator 导出的 `original=translation` 文本文件 + `//` 注释 + `r:"<pattern>"="<replacement>"` 正则规则（pattern 不动，仅 replacement 提交 LLM）。`engines/unity_xunity.py` + UTF-8 BOM round-trip + CRLF/LF 行尾保留 + 50 MB OOM cap + TOCTOU 防御。CLI `--engine unity` / `--engine unity_xunity`。
- **Godot（P1）**：`.tscn`/`.gd`/`.tres` 均为文本格式，纯标准库。`.gd` 中 `tr("...")` 需正则提取，Godot CSV 翻译表可直接用 CSVEngine。
- **Kirikiri 2/Z（P2）**：`.ks` 是文本格式可直接正则提取，`.scn` 二进制通过 VNTextPatch 导出 CSV。
- **TyranoBuilder（P2）**：`.ks` 脚本格式类似 Kirikiri，实现方案相近。

### 13.3.1 r54 retire 引擎（移到 architectural decision）

> 详见本文 §13.4 + [HANDOFF.md "Round 54 retire"](../HANDOFF.md) 段。retire 理由按 ROI 评估 + r52 起"减法 + 聚焦"原则。

- **RPG Maker VX/Ace** retired — 需要 `rubymarshal` 第三方依赖，违反零依赖核心契约（CLAUDE.md 第 9 原则）
- **Wolf RPG Editor** retired — 走 WolfTrans 导出 CSV → 已通过 CSVEngine 间接支持，重复造轮子
- **Unreal Engine** retired — uasset 工具链极其复杂，主流 Unreal 游戏走 .uasset 内部 LocText 系统，需要专用工具，不是这个项目的定位
- **HTML5 / 浏览器** retired — HTML5 游戏极少做汉化（往往是 web app i18n 已有现成方案）；用户场景虚

### 13.4 架构 TODO（非引擎）

| 优先级 | 项目 | 状态 |
|--------|------|------|
| ~~🟠 P1~~ | ~~非中文目标语言端到端验证（ja / ko / zh-tw）~~ | **r52 C4 BREAKING retired** — 5 层 code-level contract + `lang_config.py` + `--target-lang` 全部删除；目标语言固定 zh |
| ~~🟡 P2~~ | ~~A-H-3 Medium（让 Ren'Py 走 generic_pipeline 6 阶段）~~ | **r54 retired to architectural decision** — r52 C4 后 Ren'Py 是 zh-only 单一目标，"统一抽象"用户场景消失；generic_pipeline 反而是从 tl-mode 派生的，反向接入是绕路；r53 W1 retry 并发 / 99.991% 翻译成功率 / 14 轮 0 CRITICAL 全在专有管线下达成，无需通用化 |
| ~~🟡 P2~~ | ~~A-H-3 Deep（完全退役 DialogueEntry）~~ | **r54 retired to architectural decision** — `tl_file/tl_line/block_start_line` 搬到 `metadata` 字典只是换位置，没真正统一；attribute access → dict lookup 是降级；75+ 引用 / 11 文件全改、删除无回滚 |
| ~~🟡 P2~~ | ~~S-H-4 Breaking（强制所有 plugins 走 subprocess，retire importlib）~~ | **r52 C3 完成** — importlib loader 删除 + 启动期 readiness probe + plugin 必须实现 `_plugin_serve()`；migration guide 见 `custom_engines/example_echo.py` |
| ~~🟢 W1~~ | ~~retry 阶段并发化 + per-chunk progress logging~~ | **r53 W1 完成** — `translators/_tl_retry.py` ThreadPoolExecutor + 自适应 chunk size + 17 单元测试 |
| ~~🟢 W2~~ | ~~LLM JSON mis-escape 鲁棒化~~ | **r53 W2 完成** — `_extract_json_array` layer-7 char-walker `_repair_unescaped_quotes_in_strings` + 5 单元测试 |
| ~~🟢 W3~~ | ~~LLM ID drift detection~~ | **r53 W3 完成** — `detect_id_drift()` 主 stage + retry stage 各注入 layer-6（symmetric-difference > 10% 触发 W3-DRIFT warn） |
| ~~🟢 W4~~ | ~~direct-mode source-language awareness~~ | **r53 W4 完成** — 文档化路径（启动 INFO log + 常量 docstring + README + CLAUDE.md），不加 `--source-lang` CLI flag |
| ~~🟢 P3~~ | ~~RPG Maker Plugin Commands（code 356）~~ | **r54 retired to architectural decision** — 真实覆盖 ~25% × ~10% = ~2.5% 用户场景；每个 plugin 都需逐个适配；按需启动模式更合理（用户实际报告具体游戏样本时再开新轮，不应作为 standing backlog） |
| ~~🟢 P3~~ | ~~加密 RPA / RGSS 归档~~ | **r54 retired to architectural decision** — 涉及反编译加密算法（破解游戏 DRM），法律灰色地带；用户群体小；非加密 RPA / RGSS 已支持 |

### 13.5 监控项（r53 末重新评估完整闭合）

| 项 | r52 状态 | r53 重新评估 |
|----|---------|-------------|
| Pickle 白名单 `_codecs.encode` / `copyreg._reconstructor` 理论链式攻击 | informational watchlist | **architectural decision (verified safe)** — `tests/test_pickle_safe_redteam.py` 8 红队 payload 全 blocked；`_codecs.encode` 仅产 inert bytes/str；`_reconstructor` 在 base resolve 阶段被拒 |
| HTTP 响应体 64 KB 精度偏差 | informational watchlist | **mitigated** — `read_bounded` chunk size 改 `min(_READ_CHUNK_SIZE, limit - total + 1)`，最大偏差 65535 B → 1 B |
| TOCTOU fstat 自身 race 窗口 | microsecond 级 | **architectural decision** — 已是 OS-atomic 边界，进一步 narrow 依赖 OS 实现细节，无 actionable improvement |
| Symlink path-swap TOCTOU | 本地工具无 exploit vector | **mitigated (informational warning)** — `main.py::_maybe_warn_on_symlink` 在 `--game-dir` / `--config` 是 symlink 时 warn，`--allow-symlink` 抑制 |
| Logger namespace 行为契约 | r51 architectural decision | **architectural decision (maintained)** — r51 4 contract tests pin 覆盖所有 production 模块（r51 时 17 sites，r56 末实测 24 sites — contract 是"覆盖"而非定值）；如未来引入 logging filter / sink / metric pipeline，需 reconsider |
| GUI 自动化 | architectural decision | **architectural decision (maintained)** — 跨平台 headless 需违反零依赖契约 + ROI 低；如未来引入纯 stdlib GUI mock 框架可重新评估 |
