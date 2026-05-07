# 6 维度深度债务审计报告

> **当前版本**：r63 audit（重写于 r63）
>
> **历史**：
> - r57 cycle（创建于 r57，含 23 findings）：r57/r58/r59 三轮分别闭合 8+8+8 = 23 项；详见 [`_archive/EVOLUTION.md`](_archive/EVOLUTION.md) 阶段十六-十八
> - r60 cycle（重写于 r60，含 23 findings）：r61 闭合 11 项 + r62 闭合 12 项 = 23 项全闭合；详见 [`_archive/EVOLUTION.md`](_archive/EVOLUTION.md) 阶段二十-二一
> - **r63 cycle（本次）**：第三次 6 维度深度审计，**不重复任何已 fix / 已 retire 的 r57/r60 cycle findings**（合计已闭合 46 项）；扫描 r62 末 baseline 后的更深层、跨维度潜在债务
>
> **范围**：r62 末状态 — 191/191 PASS / VERIFIED-CLAIMS OK（tests_total 498 / test_files 36 / ci_steps 36 / assertion_points 624）/ 22 轮 0 CRITICAL streak / 15 hard contracts / actionable backlog 仅剩 Godot + Kirikiri/TyranoBuilder
>
> **状态**：📋 待用户决策 fix path（X / Y / Z / W）；尚未实施。

---

## 1️⃣ 技术债（Technical Debt）

### T1 🔴 HIGH — 3 个测试文件危险接近 800 行 cap（pre-commit blocker 风险）

实测：

| 文件 | 行数 | 距 cap |
|------|------|-------|
| `tests/test_file_safety.py` | **798** | **2 行** |
| `tests/test_api_client.py` | **792** | **8 行** |
| `tests/test_verify_docs_claims.py` | **790** | **10 行** |

任何加新测试到这 3 文件之一就 block commit（pre-commit hook 4 件套之一是 file-size cap 自动 enforce）。`test_file_safety.py` r58 P1 拆过一次 (807→798)，再加 1 行就越界。

这是**可预测的 imminent failure**：r62 B1 加 `test_interrupt_recovery.py` 单独文件就避开了，但下次有 audit finding 需要 fix `core/api_client.py`、`safety/file_safety.py` 或 `verify_docs_claims.py` 时，自然会想加测试到对应 test_*.py 文件，触发 cap block，被迫先拆分（流程 friction）。

**fix**：(a) 主动拆 3 文件，每个降到 ≤ 600 行，留 ≥ 200 行余量；(b) 不动 — 等下次有人触发 cap 再处理；(c) 改 cap 为 1000 行（违反 hard contract，需 plan-first）。

建议 **(a)**：3 文件拆分约 ~300 行新文件，比 r58 P1 拆 test_translators 832→654 简单（已有可参考模式）。

### T2 🟡 MEDIUM — 4 production 文件接近 800 cap（剩余 <60 行余量）

实测：

| 文件 | 行数 | 距 cap |
|------|------|-------|
| `file_processor/patcher.py` | 770 | 30 |
| `tools/translation_editor.py` | 758 | 42 |
| `tools/rpyc_decompiler.py` | 742 | 58 |
| `engines/rpgmaker_engine.py` | 742 | 58 |
| `core/api_client.py` | 732 | 68 |
| `file_processor/checker.py` | 724 | 76 |

T1 是 imminent，T2 是 1-2 轮内将触发。`core/api_client.py` 在 mypy enforce 6 文件 scope 内（[ADR 0007](docs/adr/0007-mypy-enforce-scope.md)）— 拆分需保持 scope 内文件全部 mypy clean。

**fix**：(a) 优先拆 `file_processor/patcher.py` (770)；(b) `tools/translation_editor.py` 和 `tools/rpyc_decompiler.py` 是辅助 tool，按 r57 T4 architectural decision "tools/ 散乱无共享 base"——可暂不拆等触发；(c) `core/api_client.py` 含 mypy scope，触发前主动拆出 helper 模块（如 `core/api_retry.py` for 退避重试逻辑）。

建议 **(a)+(c)**：避免 hot path 文件触发 cap block。

### T3 🟢 LOW — 类型 hint 度量误导（r60 T2 数字不准）

r60 audit T2 声称 hint coverage "44% → 43.2%"，但**该数字包含 tests/**（460/1082）；扣除 tests/ 后 production-only coverage = **393/451 = 87.1%**。

production 代码实际类型注解良好，"反向 trend" 的描述误导。r61 T2 fix 加的 "新代码 100% type hint" CONTRIBUTING 规则（针对新代码不强求 backfill）是正确方向。

**fix**：(a) 文档修正——`AUDIT_R57.md` 说明 production 87.1% 而非 43.2%；(b) 修 r60 audit T2 度量方法说明（避免未来读者再被误导）；(c) 不动（历史记录保留原数字 + r61 T2 fix 已对此 acknowledged）。

建议 **(a)**：本 audit 已含此说明，已自动满足。

### T4 🟢 LOW — `__pycache__` / `.pyc` 残留 267 个文件

实测：267 个 `.pyc` 文件本地。`.gitignore` 已含 `__pycache__/` 和 `*.pyc`，git 不追踪。但本地累积影响：
- `find` 查询慢
- 删除 production .py 后 .pyc 还在，导致 stale module 残留
- IDE / mypy 偶尔从 .pyc 读 stale signature

**fix**：(a) `scripts/clean_pycache.sh` / `.bat` 清理工具脚本；(b) 不做 — 用户随手 `find . -name __pycache__ -exec rm -rf {} +` 即可。

建议 **(b)**：retire to architectural decision；标记到 CLAUDE.md "已知限制"段，提示用户偶尔清理。

---

## 2️⃣ 质量与安全债（Quality & Security Debt）

### S1 🔴 HIGH — pre-commit hook 仅运行 40% tests（local feedback gap）

实测：
- `tests/test_*.py` 文件总数：**35**
- 总 `def test_*` 数：**485**
- meta-runner (`tests/test_all.py`) 实跑：**191** ≈ 39%
- meta-runner imports：仅 11 文件（`test_api_client` / `test_file_processor` / `test_translators` / `test_glossary_prompts_config` / `test_translation_state` / `test_runtime_hook` / `test_tl_retry` / `test_pickle_safe_redteam` / `test_unity_xunity_engine` / `test_complex_fixture` / `test_main_cli`）

**剩 24 个测试文件 pre-commit 不会跑**，包括：
- `test_interrupt_recovery.py`（**r62 B1 刚加！**）
- `test_tl_pipeline.py`（**含 r61 T1 fix 验证测试！**）
- `test_verify_docs_claims.py` / `test_verify_docs_claims_push_status.py`
- `test_engines.py` / `test_engines_rpgmaker.py` / `test_csv_engine.py`
- `test_file_safety.py` / `test_file_safety_c5.py`（**TOCTOU helper 测试！**）
- `test_repo_rename_consistency.py`（**r51 hard contract logger namespace 测试！**）
- `test_translation_editor.py` / `test_ui_whitelist.py` / `test_runtime_hook_filter.py` 等

CI 用 individual `python tests/test_X.py` step 兜底（`.github/workflows/test.yml` 共 ~25 行 `Run *` step）。但 **local pre-commit 不跑 = local commit 不会 catch 这些测试的 regression**。新加的 r61 T1 / r62 B1 测试如果发生回归，pre-commit 不会 block；只有 push 后 CI 才发现。

时间成本实测：
- meta-runner: 0.68s
- 5 个非 meta-runner 测试串行: 1.0s（合理估计全部 24 个 ~3s）
- 估计扩到全部 485 测试：**~3.5s** 总耗时（仍快）

**fix**：(a) 扩 meta-runner 把所有 35 文件全 import；(b) 加新 fast-meta-runner 跑全部 35 文件（保留原 meta-runner 用于 CI 历史兼容）；(c) 维持现状（CI 兜底，local feedback gap 是 acceptable trade-off）。

建议 **(a)**：3.5s vs 0.68s 成本可接受；local feedback 完整 = 真正"零回归"承诺。

### S2 🟡 MEDIUM — 文件命名 drift：`AUDIT_R57.md` 实际是 r63 cycle 容器

文件名 "R57" 但当前是 r63 cycle audit（r57 cycle 23 findings 已 r57-r59 闭合 / r60 cycle 23 findings 已 r61-r62 闭合）。

新贡献者读 docs/CLAUDE.md 看到 `AUDIT_R57.md` 引用，会以为是 r57 时期的 audit；实际打开是 r63 内容。文件名与内容 cycle 完全不一致。

r62 末 plan 说 "AUDIT_R57.md 应在 r63+ 移到 `_archive/AUDIT_R60.md`" — 但**没真正执行**。当前文件继续被 r63 audit 重写。

**fix**：(a) 改名为 **永久入口** `AUDIT.md`（每轮 audit 重写为容器，旧 cycle 闭合时归档到 `_archive/AUDIT_R{cycle_end}.md`）；(b) 当前 r63 cycle 完成 fix 后，把本文件归档为 `_archive/AUDIT_R63.md`，下次 audit 创建新 `AUDIT_R66.md`（一对一 cycle 命名，但下次又会出现命名/cycle drift）；(c) 不动（status quo）。

建议 **(a)**：永久入口 `AUDIT.md` 模式更稳定；retired cycles 自然归档命名按完成 round 编号；本 r63 cycle 完成后归档 `_archive/AUDIT_R63.md` + 重命名当前文件 `AUDIT.md`。

### S3 🟡 MEDIUM — `START.bat` 错误声称 Python 3.9+（与 r57 T1 BREAKING 矛盾）

`START.bat:7`：

```bat
echo [ERROR] Python 3.9+ is required.
```

但 r57 T1 已 BREAKING bump 到 ≥ 3.10（[ADR 0006](docs/adr/0006-python-310-floor.md) / [hard contract #12](CLAUDE.md)）。Python 3.9 用户运行 START.bat 会过 `where python` 检查，但实际 Python 代码（PEP 604 `int | None`）在 3.9 下崩溃 — **错误信息误导用户**。

**fix**：(a) 改 `Python 3.9+` → `Python 3.10+`；同时 START.bat 加版本号检测（`python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"`）拦截过早失败。

中等成本（~10 行 batch），高 ROI（用户体验直接改善）。

### S4 🟢 LOW — 无 `--version` flag（用户无法查询当前安装版本）

`main.py::main()` argparse 没有 `parser.add_argument("--version", action="version", ...)`。r62 B2 已 bump 到 v2.0.0，但用户运行 `python main.py --version` 报 argparse error（`--game-dir` 未提供）。

PyInstaller 打包后 .exe 也没 --version 输出（`build.py` 不读 `pyproject.toml::version`）。

**fix**：(a) main.py 加 `parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")`；从 `pyproject.toml` 读取或硬编码 `__version__`；(b) build.py 加 PyInstaller `--version-file` 选项让 .exe 有 Windows 版本 metadata；(c) 不做。

建议 **(a)+(b) 一并做**（小成本，~15 行 + version-file 模板）。

---

## 3️⃣ 架构与设计债（Architecture & Design Debt）

### A1 🟡 MEDIUM — `gui.py` 仍 594 行，r60 audit T3/A3 watchlist 未推进

r60 audit T3/A3 已识别 `gui.py` 594 行接近 cap（206 行余量）；r61 fix 选择 (c) "懒处理 + 新 PR 加 GUI 功能必须先拆"约束，但**没主动拆**。从 r56 (594 行) 到 r62 (594 行) 没增长，但项目持续演进，未来加 GUI 功能（Godot 引擎按钮 / Kirikiri 按钮 / 多账号 UI）会立即触发 cap。

预防性拆分比 reactive 拆分简单：当前 `gui.py` 已有 `gui_dialogs.py` (185) + `gui_handlers.py` (73) + `gui_pipeline.py` (244) 三个 mixin，主文件继续按功能拆出 `gui_main_window.py` (~200) + `gui_scan_panel.py` (~150) + `gui_run_panel.py` (~200) 等。

**fix**：(a) 主动拆 `gui.py` 594 → 4 文件 ~150 行/个；(b) 不动等触发（已是 r60 audit 决策，r63 不重提决策）；(c) 升级 800 cap 为 1000 行（BREAKING hard contract，需 plan-first）。

建议 **(b)**：r60 audit 已决策，r63 不重复推翻；watchlist 持续。

### A2 🟡 MEDIUM — pipeline/stages.py 函数内 import 10 处（最高），lazy import vs 循环规避不明

实测函数内 import top：

| 文件 | 函数内 import 数 |
|------|-----------------|
| `pipeline/stages.py` | **10** |
| `engines/generic_pipeline.py` | 6 |
| `core/runtime_hook_emitter.py` | 6 |
| `engines/renpy_engine.py` | 5 |
| `engines/engine_detector.py` | 5 |

每个函数内 import 都可能是：
1. **正当 lazy import**（启动时间优化 / 减少 import 链）
2. **历史循环依赖防御**（实际可能已无循环）— 提到顶层省去运行时开销
3. **延迟可选依赖**（如某模块仅在 plugin 启用时 import）

r56 audit M3 已处理过 1 处（`_translate_one_tl_chunk` 函数内 import → 顶层）。但 `pipeline/stages.py` 10 处未审。

**fix**：(a) 每处加 docstring 说明 lazy 原因；(b) 静态分析（mypy / 实际跑）确认无循环后 hoist 到顶层；(c) 不动。

建议 **(a)** 优先（低成本，文档清晰；hoist 是 r64+ 工作）。

### A3 🟢 LOW — `tools/__init__.py` / `pipeline/__init__.py` / `core/__init__.py` 空文件

实测：

| 文件 | 行数 |
|------|------|
| `file_processor/__init__.py` | 96 |
| `engines/__init__.py` | 41 |
| `safety/__init__.py` | 21 |
| `translators/__init__.py` | 0 |
| `tools/__init__.py` | 0 |
| `pipeline/__init__.py` | 0 |
| `core/__init__.py` | 0 |

不一致：4 个 package 是 namespace-only（空 __init__），3 个有实质 re-export。模块大小 8 个 package（含顶层 .py 文件）总计 41337 行 — 中等规模项目。

空 __init__ 是 valid Python，但项目可考虑：(1) 加 `__all__` explicit re-export；(2) 加 module docstring；(3) namespace-only 维持现状。

**fix**：(a) 空 __init__ 加最小 docstring（5-10 行/个，描述 package 用途）；(b) 不动（Python 惯例允许空 __init__）。

建议 **(b)**：retire to architectural decision；新贡献者从 docs/ARCHITECTURE.md 模块图理解，不依赖 __init__ docstring。

---

## 4️⃣ 流程与文档债（Process & Documentation Debt）

### P1 🟡 MEDIUM — `ROADMAP.md` 严重 stale（说"截止 r57 末"但已 r62 末）

`ROADMAP.md:7`：

> 本文件 r58 P2 引入。**截止 r57 末**项目已闭合 4 大债务维度...

实际 r62 末，r60 audit 23 findings 全闭合 + version 1.0→2.0 + 11 ADRs 等大量演进。当前能力段 (line 10) 仍仅说 "Unity XUnity AutoTranslator 文件支持（r55）"，没提 r56-r62 任何闭合。

新贡献者按 ROADMAP 对项目当前状态判断错误。

**fix**：(a) ROADMAP.md "截止" 段改为 "截止 r62 末"，更新当前能力段（11 ADRs / v2.0.0 / 22 轮 0-CRITICAL 等）；(b) 加 ROADMAP last-updated 字段并约束每 5 轮 docs sync 必更新；(c) ROADMAP.md retire（HANDOFF.md + EVOLUTION.md 已覆盖）。

建议 **(a)+(b)**：本 r63 docs sync 顺手做。

### P2 🟡 MEDIUM — `docs/ONBOARDING.md` 说 "5 份 ADR" 但实际 11 份

`docs/ONBOARDING.md:45`：

> | 找架构决策 / "为什么这样设计？" | [`docs/adr/`](adr/) — **5 份 ADR**（zero-deps / zh-only / subprocess-plugin / RenPy-dedicated / safety-toplevel）|

r61 A1 已补 ADR 0006-0011 共 6 份，索引现 11 份。ONBOARDING 没同步。

**fix**：(a) 改 "5 份" → "11 份"，列表加 6 个新 ADR slug；(b) 改为 "见 [`docs/adr/README.md`](adr/README.md) 索引" 避免数字 drift（最低维护成本）。

建议 **(b)**：避免未来再 drift（r66 加新 ADR 时 ONBOARDING 又要改）。

### P3 🟢 LOW — `docs/ARCHITECTURE.md` / `docs/REFERENCE.md` 未提 r60+ ADR

实测 grep "ADR 0006|0007|0008|0009|0010|0011"：

```
（空）
```

`docs/REFERENCE.md` 仅在 §7b plugin 协议段提到 r60/r61，没有交叉引用 6 份新 ADR。`docs/ARCHITECTURE.md` 完全没提 r60+ 的 ADR 编号。

新贡献者读 ARCHITECTURE 找架构决策，看到旧 ADR 引用（0001-0005）会以为只有这些；要找 r57+ 的契约（如 mypy enforce / ruff CI）必须自己 grep 全 docs/。

**fix**：(a) docs/ARCHITECTURE.md 加一段 "## ADR 索引" cross-link 11 份；(b) 在已有 hard contract 描述处补 ADR 引用（如 mypy enforce → `[ADR 0007](adr/0007-mypy-enforce-scope.md)`）；(c) 不做（ADR README 已是单一源）。

建议 **(a)+(b)**：低成本 high ROI 文档可发现性提升。

### P4 🟢 LOW — Windows install_hooks.bat 缺失（仅 .sh 版本）

`scripts/install_hooks.sh` 是 bash，Windows 用户必须用 Git Bash / MSYS2 / WSL 才能跑。但项目主开发环境就是 Windows（CLAUDE.md 明确说明）+ Windows 用户大概率用 cmd / PowerShell。

新 Windows contributor 跑不了 install_hooks.sh，pre-commit 不激活，导致 800 cap / docs claim drift / push-status 等防御都不工作。

**fix**：(a) `scripts/install_hooks.bat` 新建（~15 行 batch 等价于 .sh）；(b) `scripts/install_hooks.ps1` PowerShell 版（更现代）；(c) 文档化 .sh 跑法（用户自己 Git Bash 跑）。

建议 **(a)**：低成本 high ROI；项目主开发环境就是 Windows，应有 .bat 版本。

---

## 5️⃣ 产品与业务债（Product & Business Debt）

### B1 🟡 MEDIUM — `pyproject.toml::description` 与 README 中文描述对齐，但英文使用场景缺

实测 `pyproject.toml::description`：

> "纯 Python 的多引擎游戏自动汉化工具（Ren'Py / RPG Maker MV-MZ / Unity XUnity / CSV-JSONL），通过 LLM API 翻译为简体中文"

中文 description 字段在 PyPI / `pip search` / `pip show` 等英文工具显示时**显示中文 + 英文工具用户看不懂**。GitHub repo description 是单独字段（用户在 GitHub 设置）。

**fix**：(a) description 改双语 (English first + 中文 fallback) 或 English-only（PyPI 惯例）；(b) 不做（项目主要面向中文用户，PyPI 不是主分发渠道）。

建议 **(a)**：改 English-only `"Pure-Python multi-engine game translator (Ren'Py / RPG Maker MV-MZ / Unity XUnity / CSV-JSONL) using LLM APIs for Simplified Chinese localization."` ~150 字符。

### B2 🟡 MEDIUM — build.py 没有 PyInstaller version-info（生成的 .exe 无版本号）

`build.py` 没用 PyInstaller 的 `--version-file` 选项。生成的 .exe 在 Windows 资源管理器 → 右键 → 属性 → 详细信息 看不到版本号、产品名、公司等 metadata。

r62 B2 升 v2.0.0 但 .exe 用户看不到。release.yml (r59 B1) 上传 binary 到 GitHub Release 也没 version embed。

**fix**：(a) 创建 `build/version_info.txt` PyInstaller version template（~25 行）+ `build.py` 引用 + 自动从 pyproject.toml 读 version。

中等成本但实现一次永久受益。

### B3 🟢 LOW — `core/api_client.py` 硬编码 5 LLM provider URL + model

实测：

| Provider | URL | Default Model |
|----------|-----|---------------|
| xai/grok | `https://api.x.ai/v1/chat/completions` | grok-4-1-fast-reasoning |
| openai | `https://api.openai.com/v1/chat/completions` | gpt-4o-mini |
| deepseek | `https://api.deepseek.com/v1/chat/completions` | deepseek-chat |
| claude | `https://api.anthropic.com/v1/messages` | claude-sonnet-4-20250514 |
| gemini | `https://generativelanguage.googleapis.com/v1beta/chat/completions` | (default) |

URL / 模型变动频繁（OpenAI 改 endpoint、Claude 出新版）— 需要每次手动改源码 + 发版。用户用 `--api-base` / `--model` flag 覆盖能临时绕，但 default fallback 长期 stale 风险。

**fix**：(a) 抽到 `core/llm_providers.json` 用户可覆盖；(b) 文档化"用户应该 `--api-base` / `--model` 覆盖默认值"，default 仅 starting point；(c) 不做（每次升级模型时人工同步是合理工作）。

建议 **(b)**：retire to architectural decision；添加 CLAUDE.md "已知限制" 段提示用户。

### B4 🟢 LOW — RPG Maker engine 链接 stale（论坛 thread）

`engines/rpgmaker_engine.py:741`:

> "  3. 参考: https://forums.rpgmakerweb.com/index.php?threads/how-to-change-font.48735/"

外链到 RPG Maker 论坛 thread。论坛 URL 长期 stale 风险（线程合并 / 用户删帖 / 论坛改版）。

**fix**：(a) 把链接 archived 到 web archive (`https://web.archive.org/web/...`)；(b) 内嵌核心信息到 docstring（避免依赖外部资源）；(c) 不做（教程链接 stale 是 OSS 通病）。

建议 **(c)**：retire；外链 stale 风险无系统解决方案。

---

## 6️⃣ 组织与知识债（Org & Knowledge Debt）

### O1 🟡 MEDIUM — 缺 `.editorconfig`（多 IDE 一致性）

实测：项目根没有 `.editorconfig`。`.gitattributes` 控制 git 层（line endings），但 IDE 层（VS Code / IntelliJ / Sublime / Vim）需要 `.editorconfig` 才能统一 indent / charset / EOL / trim trailing whitespace 等设置。

不同 IDE 默认行为不同：VS Code 默认 4 空格 + LF；IntelliJ 默认 4 空格 + 系统 EOL（Windows 上 CRLF）；Sublime 默认 tab。无 .editorconfig 导致 contributor 提交可能引入 CRLF / 4-tab indent 混乱（虽然 ruff format 会修正，但 commit 第一时间引入是 PR friction）。

**fix**：(a) 添加 `.editorconfig`（~15 行，Python 4-space LF UTF-8 trim trailing）；(b) 不做（依赖 ruff format 兜底）。

建议 **(a)**：低成本，高 ROI（IDE-agnostic）；EditorConfig 是 industry-standard。

### O2 🟡 MEDIUM — 没有 `.github/FUNDING.yml`（GitHub Sponsor 入口）

GitHub repo "Sponsor this project" 按钮需要 `.github/FUNDING.yml`（即使 maintainer 不接受 sponsorship 也可以是空 / 显式 disabled）。

r59 O4 (community 建设 retire) 已说 "sponsor 入口 ROI 低"——但**没显式 disable**。GitHub UI 在没有 FUNDING.yml 时 sponsor 按钮根据 user/org 默认设置；显式 file 可以明确 "no sponsorship right now" 信号。

**fix**：(a) `.github/FUNDING.yml` 显式空 / 单行注释 "Sponsorship not currently active per [r59 O4 retire]"；(b) 不做（依赖 GitHub 默认行为）。

建议 **(b)**：retire；与 r59 O4 community 建设 retire 一致逻辑；如未来打开 sponsor 再加。

### O3 🟢 LOW — 没有 `tests/test_audit_consistency.py` 验证 ADR 索引同步

r61 A1 加 6 份 ADR 后，`docs/adr/README.md` 索引手动维护。如未来加 ADR 0012 但忘记更新 README 索引，没自动 catch 机制。

类似已有 r51 `tests/test_repo_rename_consistency.py` 钉 logger namespace 数；可加 `tests/test_adr_index_consistency.py` 钉 ADR 文件数 = 索引行数。

**fix**：(a) 新建 `tests/test_adr_index_consistency.py`（~30 行）pin `len(glob.glob('docs/adr/0*-*.md')) == count_index_rows(README.md)`；(b) 不做（依赖人工 review）。

建议 **(b)**：retire；ADR 增加频率低（项目 r1-r62 累计 11 份），人工 review 成本可接受。

### O4 🟢 LOW — 没有 `tests/test_changelog_completeness.py` 验证每轮 commit 必有 CHANGELOG entry

CHANGELOG.md 手写 (r60 audit P3 retire)，但缺 contract test。如未来某轮 commit 提交但忘了更新 CHANGELOG，没自动 catch。

**fix**：(a) `tests/test_changelog_completeness.py` 检查最后 5 commits（git log）每个有对应 CHANGELOG round entry；(b) 不做。

建议 **(b)**：retire；与 P3 retire 一致逻辑（手写 CHANGELOG 是 deliberate curation，不强制 mechanical）。

---

## 📊 6 维度 Findings 汇总

| 维度 | 🔴 HIGH | 🟡 MEDIUM | 🟢 LOW | 小计 |
|------|---------|-----------|--------|------|
| 1. 技术债 | T1 | T2 | T3, T4 | 4 |
| 2. 质量与安全债 | S1 | S2, S3 | S4 | 4 |
| 3. 架构与设计债 | — | A1, A2 | A3 | 3 |
| 4. 流程与文档债 | — | P1, P2 | P3, P4 | 4 |
| 5. 产品与业务债 | — | B1, B2 | B3, B4 | 4 |
| 6. 组织与知识债 | — | O1, O2 | O3, O4 | 4 |
| **TOTAL** | **2** | **9** | **12** | **23** |

**所有 findings 不破坏 22 轮 0 CRITICAL streak**（无 correctness bug；T1/S1 是流程/工具 gap，不是运行时错误）。

---

## 与 r57/r60 audit 的对照

| 维度 | r57 cycle (闭合) | r60 cycle (闭合) | r63 cycle (本次新发现) | 重复? |
|------|----------------|----------------|--------------------|------|
| 技术债 | tempfile / hint / gui_cap / benchmark | tempfile leak / hint trend / gui near cap / benchmark | **3 testfile cap** / 4 prod near cap / hint metric drift / pyc residue | **0 重复** — r60 T3 (gui.py) 已 r61 watchlist；本轮新发现是 testfile imminent + 4 个新 production 文件接近 cap |
| 质量与安全债 | escape fuzz / path traversal / .gitignore / log injection | macos CI / plugin schema / API key / prompt injection | **pre-commit 40% 测试覆盖** / file 命名 drift / START.bat 3.9 stale / `--version` 缺 | **0 重复** |
| 架构与设计债 | tools/ retire / config helper / RenPy-dedicated | ADR gap / GUI subprocess / gui_cap | gui.py watchlist / pipeline/stages 函数内 import 10 处 / 空 `__init__.py` | **1 部分重复**（gui.py r60 audit T3 + r63 A1，标 watchlist persisted） |
| 流程与文档债 | TBD | HANDOFF 增长 / contributors / changelog auto / fixture | **ROADMAP stale (r57 末)** / ONBOARDING ADR 数 stale / ARCHITECTURE 缺 ADR refs / Windows install_hooks.bat 缺 | **0 重复** |
| 产品与业务债 | TBD | interrupt / version / GUI progress / multi-account | description i18n / .exe version-info / LLM URLs hardcoded / RPG Maker forum link | **0 重复** |
| 组织与知识债 | TBD | CoC / governance / TODO tracking / bus factor | `.editorconfig` 缺 / FUNDING.yml 缺 / ADR consistency test 缺 / CHANGELOG completeness test 缺 | **0 重复** |

**r63 audit 净新增 22 unique findings + 1 watchlist-persisted（gui.py 重复 acknowledge）**。

---

## 🎯 推荐 Fix Path

### 路径 X — 全部 fix（23 项，~700 行改动）

预估 4-5 commits 跨 r64-r65 两轮（与 r60→r61-r62 模式一致）。

### 路径 Y — H + M（建议，~280 行改动）

11 项 fix（2 H + 9 M）。L 留 architectural decision 文档化。预估 2-3 commits 跨 r64。

| 维度 | H + M findings |
|------|---------------|
| 技术债 | T1 + T2 |
| 质量与安全债 | S1 + S2 + S3 |
| 架构与设计债 | A1 + A2 |
| 流程与文档债 | P1 + P2 |
| 产品与业务债 | B1 + B2 |
| 组织与知识债 | O1 + O2 |

### 路径 Z — 仅 H（最小冲击，~150 行改动）

2 项 fix：
- T1 — 拆 3 个 testfile 接近 cap（避免 imminent block）
- S1 — 扩 meta-runner 把所有 35 文件全 import（修 pre-commit 40% 覆盖）

预估 1 commit。最防御性 fix。

### 路径 W — 拒绝 fix，全部 retire to architectural decision

承认这些是项目特性（小团队 / 当前 maturity / 最小改动原则），文档化为 explicit decisions。预估 1 commit（仅 docs）。

---

## Audit 提出方建议

**路径 Y（H + M 全 fix）**。理由：

1. **T1 HIGH** 是 imminent failure — 3 个 testfile 距 cap < 10 行，下一次任何加测试需求触发 commit block，被迫 reactive 拆分；预防性 fix 简单。
2. **S1 HIGH** 是 silent 已存在 6+ 轮的 local feedback gap — 24/35 测试不在 pre-commit 跑，**包括 r61 T1 fix 验证测试和 r62 B1 interrupt 测试本身**。本审计的 "22 轮 0 CRITICAL streak" 部分依赖 pre-commit catch，但实际 pre-commit 只 catch 39% 测试。
3. **T2 + A2** 是 1-2 轮内会 reactively 触发的 cap / lazy import 债，pre-emptive 处理顺手。
4. **S2 + S3 + S4** 是 user-facing UX 缺陷（命名混淆 / 错误信息 / 无 --version）— 用户感知层。
5. **P1 + P2 + P3** 是 docs drift（ROADMAP / ONBOARDING / ARCHITECTURE 不同步），新贡献者直接受影响。
6. **B1 + B2** 是 v2.0.0 升级后未配套的 metadata 同步（PyPI description / .exe version-info）。
7. **O1 + O2** 是 GitHub community standards 完整度（`.editorconfig` / `FUNDING.yml`）— 低成本 high visibility。
8. **L 级 12 项**多数 retire-able（cosmetic / 未触发条件 / 维护成本高于 ROI），显式 retire 比硬干强。

预估 11 项 fix 跨 2-3 commits 完成（按 r60→r61-r62 同模式拆分维度）。

---

## 备注

- 本文件由 r63 audit 重写（r57/r60 旧版本均已 r57-r59 / r61-r62 全闭合，git log + EVOLUTION 阶段十六-十八 / 二十-二一 留底）
- 一旦本轮 fix path 选定并实施完成，本文件应：
  - (a) 移到 `_archive/AUDIT_R{closure_round}.md` 历史归档（与 r57/r60 旧版本相同处理）
  - (b) **建议**：本 r63 cycle 完成 fix 后改名为永久入口 `AUDIT.md`，闭合的 cycle 自动归档（响应本审计 S2 finding）
- 当前**未 commit**——选择 fix 范围后再决定是否一起 commit
- r60 滚动归档（hard contract #15）下次触发 r65；r63 不触发归档
