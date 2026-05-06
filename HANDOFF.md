# HANDOFF — Round 56 末 → Round 57 起点

<!-- VERIFIED-CLAIMS-START -->
tests_total: 485
test_files: 33
ci_steps: 34
assertion_points: 611
<!-- VERIFIED-CLAIMS-END -->

> **上方 fenced 块是声明数字的唯一位置**。其他文档（`CLAUDE.md` / `.cursorrules` / `CHANGELOG.md` / `_archive/EVOLUTION.md` / `README.md` 等）只能引用这些数字，**不能重新声明**。`scripts/verify_docs_claims.py` 在 pre-commit hook 自动检查，drift fails the commit。
>
> 字段定义（由 `verify_docs_claims.py` 静态推导）：
>
> - `tests_total` — `tests/test_*.py` + `tests/smoke_test.py` 中所有 top-level `def test_*` / `async def test_*` 的 AST 计数
> - `test_files` — `tests/test_*.py` + `tests/smoke_test.py` 文件数
> - `ci_steps` — `.github/workflows/test.yml` 中 `jobs.test.steps` 长度
> - `assertion_points` — `tests_total + sum((N assertions))`，第二项从含 `self-test` label 的 CI step 名称解析（当前 `tl_parser` 75 + `screen` 51 = 126）
>
> `--full` 模式额外实跑全部 CI `Run *` step 作 sanity gate。

---

## 状态一句话

纯 Python 零依赖**zh-only**游戏汉化工具。**Round 56 全面深度审计 + 8 项 fix（路径 C 全闭合）**：(H1) `core/api_client.py` 删 5 死 import (atexit/importlib.util/sys/Optional/Any) — r52 C3 retire 后清理不彻底；(H3) `engines/unity_xunity.py` 删 r55 残留 `field` 死 import；(M3) `_translate_one_tl_chunk` 函数内 import 提到模块顶层；(M2) `core/file_safety.py` → `safety/file_safety.py` 顶层独立 package（避免 file_processor 间接依赖 core 的 layering 误解；CI mock target guard 用 fragment match 兼容两种路径，r48 stale mock trap CLASS 仍生效）；(M1) `UNITY_XUNITY_PROFILE` 加 `placeholder_patterns` 保护 regex backrefs (`\d` `\w` `\s` `\b` `\1`-`\9`) — LLM 翻译 regex pattern 时不破坏 backref 语法；(L1) 4 个 production 模块 print() → logger.info()（[translators/screen.py](translators/screen.py) / [tl_parser.py](translators/tl_parser.py) / [_tl_nvl_fix.py](translators/_tl_nvl_fix.py) / [_tl_postprocess.py](translators/_tl_postprocess.py)）；(H2/L2) docs 数字精确化（17 sites → 24 sites + "覆盖所有 production 模块" 软描述）。**连续 16 轮 0 CRITICAL correctness**（r35-r56）。

## 同步状态

- r56 单 commit 待 push（NEVER push 政策保留给用户）
- 本地未 push（按 NEVER push 政策保留 commit 决策给用户）
- pre-commit hook 已激活（`git config core.hooksPath = .git-hooks`）
- 4 件套 + r52 C1 push-status drift check 自动 enforce：py_compile + 800 行 cap + meta-runner + `verify_docs_claims --fast` (含 push-status check)
- Git remote: `https://github.com/Dean20030514/Multi-Engine-Game-Translator.git`

## 架构健康度（核心维度）— r54 末状态保持 r53 不变

| 维度 | 状态 |
|------|------|
| 大文件（> 800 行） | ✅ 全 .py < 800（pre-commit + verify_docs_claims --fast 自动 enforce） |
| 数据完整性 | ✅ TranslationDB 线程安全（RLock）+ 原子写入（os.replace）+ schema v2 partial backfill |
| 反序列化安全 | ✅ 3 处 pickle 全白名单 + r53 红队 audit 8/8 PASS |
| 插件沙箱 | ✅ Subprocess 强制沙箱（r52 BREAKING）+ 启动期 readiness probe + 三通道防护 |
| 目标语言 | ✅ zh 简体中文 only（r52 C4 BREAKING） |
| OOM 防护 | ✅ 26 sites / 12 modules TOCTOU MITIGATED |
| HTTP 响应体 cap | ✅ r53 监控 #2: 精度偏差 1 B |
| Mock target stale trap | ✅ CI grep step 兜底 |
| Repo rename consistency | ✅ Round 51 4 contract tests pin |
| Retry stage 并发 | ✅ r53 W1: ThreadPoolExecutor + 自适应 chunk size |
| LLM ID drift 检测 | ✅ r53 W3 layer 6 |
| LLM JSON 容错 | ✅ r53 W2 layer 7 char-walker |
| 模块分层 | ✅ deferred import 保 layering |
| docs claim drift | ✅ 4 项 prevention 自动化 |
| debt closure | ✅ Round 50 起规则强制；r51 / r52 / r53 / r54 各执行有效 |
| backlog 复杂度 | ✅ r54 重新评估：12 项 → 3 项 actionable；r55 推进 1 项 → 剩 **2 项 actionable** |
| Unity XUnity 引擎 | ✅ r55 新增 + r56 M1 加 backref placeholder protection（`\d`/`\w`/`\s`/`\b`/`\1`-`\9`）+ 18 单元测试 |
| 代码卫生（imports / logger / 路径） | ✅ **r56 audit C 路径**：5 死 import 删 + file_safety 顶层独立 package + 4 production 模块 print → logger |
| 累计审计 | ✅ 连续 16 轮 0 CRITICAL correctness（r35-r56） |

## 推荐的 Round 56+ 工作项

> Round 55 推进 1 项（Unity XUnity）后 **actionable backlog 仅剩 2 项**（按 ROI 排序）。延续 r52 起"减法 + 聚焦"方向。

### 🟡 中 ROI 可选（按需启动）

1. **Godot 引擎接入**（P1，3% 用户面）
   - `.tscn` / `.gd` / `.tres` 是文本格式，纯标准库可行
   - `tr("...")` 正则提取 + Godot CSV 翻译表直接走 CSVEngine
   - 估算：~300 行实现 + 测试

2. **Kirikiri 2/Z + TyranoBuilder**（P2，5% + 3% 用户面）
   - 都是 `.ks` 文本格式，可正则提取
   - `.scn` 二进制需 VNTextPatch 外部工具（间接支持）
   - 估算：~250 行实现 + 测试

### ✅ Round 55 完成（1 项；从 actionable backlog 移到 已完成）

- ~~**Unity XUnity AutoTranslator 接入**~~ — **r55 完成**：[`engines/unity_xunity.py`](engines/unity_xunity.py) 实现 detect/extract/write_back，支持 `original=translation` 普通行 + `//` 注释保留 + `r:"<pattern>"="<replacement>"` 正则规则（pattern 不动，仅 replacement 提交 LLM）+ UTF-8 BOM round-trip + CRLF/LF 行尾保留 + 50 MB OOM cap + TOCTOU 防御。CLI `--engine unity` 与 `--engine unity_xunity` 都接受。16 单元测试 PASS（含 round-trip byte-identical assertion）。

### ✅ Round 56 完成（8 项 audit fix；路径 C 全闭合）

> r55 末用户要求"全面且深度的检查一遍"。8 维度 audit 收集 11 findings（3 HIGH / 3 MEDIUM / 5 LOW），用户决策路径 C 全部 fix（H+M+L1+L2）。**纯优化轮，无新功能**。

- **H1 — `core/api_client.py` 5 死 import**（`atexit` / `importlib.util` / `sys` / `Optional` / `Any`）— r52 C3 BREAKING retire importlib loader 后清理不彻底，`typing.Optional/Any` 未实际使用
- **H2 — logger sites 17 → 24 docs drift**（HANDOFF / CLAUDE.md / docs/REFERENCE / EVOLUTION）— r51 加固时数字 17，r52-r55 新模块自然增长但 docs 未同步；r56 把"17 sites"硬编码改为"覆盖所有 production 模块"软描述（避免再 drift）
- **H3 — `engines/unity_xunity.py` r55 残留 `field` import** — 我自己 r55 引入的死代码，`_ParsedLine` 全是简单默认值不需 `field(default_factory=...)`
- **M1 — Unity XUnity regex backref protection**（用户 Q (a) 选择）— `UNITY_XUNITY_PROFILE.placeholder_patterns` 加 `\d`/`\D`/`\w`/`\W`/`\s`/`\S`/`\b`/`\B`/`\[1-9]` 共 9 个 patterns；LLM 翻译 regex pattern 时 `protect_placeholders` 把 backref 替换为 `__RENPY_PH_*__` 占位符，restore 时还原；2 单元测试覆盖（profile 编译 + protect/restore round-trip）
- **M2 — `core/file_safety.py` → `safety/file_safety.py`**（用户 Q (b) 选择）— 顶层独立 package，`safety/__init__.py` re-export `check_fstat_size`；18 production .py 顶层 import 路径迁移；3 测试 mock target 迁移；CI workflow `Mock target consistency check` step 文档更新（fragment match `grep -v "file_safety"` 兼容两种路径，r48 stale mock trap CLASS 仍生效）；CLAUDE.md 模块图调整 + r51 contract test 文档同步
- **M3 — `_translate_one_tl_chunk` 函数内 import → 顶层** — r53 W3 加 ID drift detection 时函数内 `from translators._tl_retry import detect_id_drift, _expected_id_set` 是循环 import 防御（实测 _tl_retry 不依赖 tl_mode，无循环）；提到模块顶层符合项目 idiomatic style
- **L1 — production print() → logger.info()**（用户指示：仅 build.py 保留 print）— 4 个 translators 模块迁移：`screen.py` (12 处) / `tl_parser.py` (15 处) / `_tl_nvl_fix.py` (1 处) / `_tl_postprocess.py` (1 处)，共 29 处；3 个文件新增 `import logging` + `logger = logging.getLogger("multi_engine_translator")` 绑定。pipeline/* 已用 `_print()` wrapper（已 logger.info）不需改
- **L2 — hard contract 计数术语统一** — 把"17 sites"硬编码描述改为"覆盖所有 production 模块"软描述，详见 H2

**数字增量（VERIFIED-CLAIMS）**：tests_total 483 → 485 (+2: r56 M1 backref protection 测试); test_files 33 unchanged; ci_steps 34 unchanged; assertion_points 609 → 611 (+2)。

### ⚫ 监控项（informational watchlist，r53 已全部闭合）

> r53 末重新评估：6 项中 5 项 retire 到 architectural decision，1 项 mitigation。详见 [docs/REFERENCE.md §13.5](docs/REFERENCE.md)。本段不重列。

### ✅ Round 54 retire（8 项；从 actionable backlog 移到 architectural decision）

> **r54 决策原则**：r52 C4 起项目进入"减法 + 聚焦"时代（删 lang_config / 退多语言 / -4123 行），r53 延续此方向（6 监控项重新评估）；r54 用同样标准重新评估剩余 backlog，识别**负 ROI 项**显式 retire。延续 CLAUDE.md 第 8 原则"最小改动"+ 第 10 原则"零欠账闭合"。

| 项 | 来源 | r54 retire 理由 |
|----|------|---------------|
| **A-H-3 Medium**（Ren'Py 走 generic_pipeline 6 阶段） | r28 提案 | r52 C4 后 Ren'Py 是 zh-only 单一目标，"统一抽象"用户场景消失；`generic_pipeline` 反而是从 tl-mode 派生的，反向接入是绕路；r53 W1 retry 并发 / 99.991% 翻译成功率 / 14 轮 0 CRITICAL 全在专有管线下达成，无需通用化 |
| **A-H-3 Deep**（完全退役 DialogueEntry） | r28 提案 | `tl_file` / `tl_line` / `block_start_line` 搬到 `metadata` 字典只是换位置，没真正统一；attribute access → dict lookup 是降级；75+ 引用 / 11 文件全改、删除无回滚；与 r52 起"减法时代"方向相反 |
| **RPG Maker Plugin Commands (code 356)** | r28 提案 | 真实覆盖 ~25% × ~10% = ~2.5% 用户场景；每个 plugin 都需逐个适配；按需启动模式更合理（用户实际报告具体游戏样本时再开新轮，不应作为 standing backlog） |
| **加密 RPA / RGSS 归档支持** | r28 提案 | 涉及反编译加密算法 — **法律灰色地带**（破解游戏 DRM）；用户群体小；非加密 RPA / 非加密 RGSS 已支持 |
| **RPG Maker VX/Ace 支持**（P1） | 引擎路线图 | 需要 `rubymarshal` 第三方依赖 — **违反零依赖核心契约**（CLAUDE.md 第 9 原则）；与项目设计哲学冲突；走 WolfTrans 类工具导出 CSV → CSVEngine 已间接支持类似 use case |
| **Wolf RPG Editor**（P1） | 引擎路线图 | 二进制自定义解析复杂；**走 WolfTrans 导出 CSV → 已通过 CSVEngine 间接支持**，重复造轮子；用户场景与 RPG Maker VX/Ace 高度重叠 |
| **Unreal Engine**（P3） | 引擎路线图 | uasset 工具链极其复杂；主流 Unreal 游戏走 .uasset 内部 LocText 系统，需要专用工具，不是这个项目的定位；ROI 极低 |
| **HTML5 / 浏览器**（P3） | 引擎路线图 | HTML5 游戏极少做汉化（往往是 web app i18n 已有现成方案）；用户场景虚 |

### ✅ 已 retired / 完成（r53 闭合）

详见 [_archive/EVOLUTION.md](_archive/EVOLUTION.md) 阶段十二。Quick recap：W1 retry 并发化 / W2 escape-fix layer 7 / W3 ID drift detection layer 6 / W4 direct-mode English-only 文档化 / 6 监控项重新评估全闭合。

---

## 关键文件路径速查

| 类别 | 路径 |
|------|------|
| AI 全局上下文 | `CLAUDE.md` / `.cursorrules`（byte-identical） |
| 本次交接 | `HANDOFF.md`（本文件） |
| 用户面文档 | `README.md`（中英双语） |
| 变更日志 | `CHANGELOG.md`（极简入口）+ `_archive/EVOLUTION.md`（r1-r54） |
| 全量历史 | `_archive/CHANGELOG_FULL.md` + `_archive/CHANGELOG_RECENT_r52.md`（r48-r52 详细） |
| 入口 | `main.py` / `gui.py`（mixin） / `one_click_pipeline.py` |
| 引擎抽象 | `engines/{engine_base, engine_detector, generic_pipeline, renpy_engine, rpgmaker_engine, csv_engine, unity_xunity}.py` |
| 核心 | `core/{api_client, api_plugin, config, glossary, prompts, translation_db, translation_utils, http_pool, pickle_safe, font_patch, runtime_hook_emitter, file_safety}.py` |
| 流水线 | `pipeline/{helpers, gate, stages}.py` |
| 翻译子模块 | `translators/{direct, tl_mode, retranslator, screen, tl_parser, renpy_text_utils}.py` + 7 私有子模块（含 r53 `_tl_retry.py`） |
| 测试 | `tests/test_all.py` meta-runner + 33 独立 suites（含 r53 `test_tl_retry.py` + `test_pickle_safe_redteam.py` + r55 `test_unity_xunity_engine.py`） |
| docs | `docs/ARCHITECTURE.md`（架构 + 数据流 + 校验链 + 引擎指南 + 测试体系）+ `docs/REFERENCE.md`（常量 + 错误码 + 路线图 + r54 retire） |
| CI | `.github/workflows/test.yml`（双 OS matrix × 3 Python = 6 jobs；step 数见 VERIFIED-CLAIMS）+ `scripts/verify_workflow.py` |
| 开发者工具 | `.gitattributes` + `.gitignore` + `build.py --clean-only` + `.git-hooks/pre-commit` + `scripts/{install_hooks.sh, verify_workflow.py, verify_docs_claims.py, migrate_db_v2_to_v1.py}` |

---

## 下次新对话接手指南

**必读顺序**（上下文从零开始）：

1. **本文件** — 当前状态 + 推荐工作项 + 文件路径
2. **`CLAUDE.md`** — 项目身份 + 10 大开发原则 + 模块图（zh-only since r52 C4）
3. **`docs/ARCHITECTURE.md`** + **`docs/REFERENCE.md`** — 架构与常量
4. **（按需）** `_archive/EVOLUTION.md` — 历史决策（含 r54 段）
5. **（按需）** `_archive/CHANGELOG_RECENT_r52.md` — 最近 5 轮（r48-r52）详细

**Round 57 关键约束**：
- audit findings 必须**同轮 fix，no tier exemption**（r50 起 written + enforced；r51 / r52 / r53 / r54 / r55 / r56 各执行有效）
- 数字声称只在本文件 `VERIFIED-CLAIMS` 块声明
- 修改 `CLAUDE.md` 必须同步 `.cursorrules`
- 修改 logger namespace / repo URL self-references 必须保持 `tests/test_repo_rename_consistency.py` 4 contract tests 全 PASS（r51 加固）
- 6 处 anonymousException 上游归属永远不能被任何 sed/refactor 误删
- **目标语言固定 zh**（r52 C4 BREAKING）— 任何 multi-target / lang_config / target-lang 重新引入必须先 plan-first 撤销 r52 C4
- **插件强制 subprocess sandbox**(r52 C3 BREAKING）— 任何 importlib in-process loader 重新引入必须先 plan-first 撤销 r52 C3
- **`tl_mode.py` retry 路径必须保持并发**（r53 W1）— 任何 sequential retry 重新引入必须先 plan-first
- **LLM ID drift detection 必须保留 layer-6**（r53 W3）— 任何主 stage / retry stage 移除 `detect_id_drift()` 必须先 plan-first
- **Pickle 白名单不得放宽**（r53 监控 #1 verified）— 任何向 `_SAFE_BUILTINS` / `_SAFE_COLLECTIONS` / `_SAFE_CODECS` / `_SAFE_COPYREG` 添加新 entry 必须先跑红队 audit
- **r54 retired 8 项不应被无证据重新打开**（r54 backlog 评估纪律）— A-H-3 Medium / Deep / RPG Maker Plugin Commands / 加密归档 / RPG Maker VX-Ace / Wolf RPG Editor / Unreal Engine / HTML5 任一项重新打开必须先有具体用户场景证据 + plan-first 论证 ROI 翻转
- **Unity XUnity 引擎解析契约**（r55 hard contract #13）— XUAT 行解析必须用 `str.partition('=')` (split first only)，注释行 `//` 必须 round-trip preserve，正则规则 `r:"..."="..."` 翻译时 pattern 必须保留不动只翻译 replacement；任何修改解析或回写语义必须先 plan-first
- pre-commit hook 已激活，会自动 enforce file-size cap + drift check + r52 C1 push-status drift check
