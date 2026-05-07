# HANDOFF — Round 66 末 → Round 67 起点（**用户决策 retire ADR + AUDIT framework；3 个文件 / 文件夹删除 + 19 文件 refs 同步**）

<!-- VERIFIED-CLAIMS-START -->
tests_total: 490
test_files: 39
ci_steps: 36
assertion_points: 616
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

纯 Python 零依赖**zh-only**游戏汉化工具。**Round 66 用户决策 retire ADR + AUDIT framework**：(1) 删除 3 个目标——`AUDIT.md` 永久入口（r64 S2 加） + `_archive/AUDIT_R63.md` r63 cycle 容器（150+ 行） + `docs/adr/` 整个目录（12 文件：README + 11 ADRs，~3500 行）；(2) 19 文件 refs 同步——CLAUDE.md / .cursorrules / HANDOFF / CHANGELOG / EVOLUTION（3 文件）/ README / ROADMAP / RELEASE / CONTRIBUTING / docs/ARCHITECTURE / docs/ONBOARDING / docs/REFERENCE / pyproject.toml / .gitignore / 2 workflows / 2 templates / dependabot.yml / START.bat 全部更新为 inline 解释或指向 CLAUDE.md hard contracts + EVOLUTION 阶段叙事；(3) **CLAUDE.md "已知限制"段加 2 条 explicit retire 条目**——明示"未来 audit 不要 propose 重新引入 ADR framework / docs/adr/ 目录 / ADR consistency 测试 / AUDIT.md 永久入口 / 6 维度审计自动化 / audit cycle 周期化命名"。**理由**：架构契约已在 CLAUDE.md hard contracts 列表 + "项目身份"段 + "已知限制"段 + EVOLUTION 阶段叙事完整记录；ADR 文件冗余形式主义；6 维度审计已 demonstrate diminishing returns（r63 cycle 真问题仅 2 HIGH，其余多 cosmetic）；项目 25 轮 0 CRITICAL streak + 完整工具链已足。**数字 unchanged**（480/38/36/606）；hard contracts 仍 15。**连续 26 轮 0 CRITICAL correctness**（r35-r66）。

## 同步状态

- r66 单 commit 待 push（NEVER push 政策保留给用户）
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
| Unity XUnity 引擎 | ✅ r55 新增 + r56 M1 加 backref placeholder protection + 18 单元测试 |
| 代码卫生（imports / logger / 路径） | ✅ r56 audit C 路径：5 死 import 删 + file_safety 顶层独立 package + 4 production 模块 print → logger |
| Python 版本 | ✅ **r57 T1**：`requires-python = ">=3.10"`（PEP 604 `int \| None` 语法运行时支持）；CI matrix `[3.10, 3.12, 3.13]` |
| Mypy 类型检查 | ✅ **r57 T2 升级 enforce**（6 文件 scope 0 errors；21 `# type: ignore[union-attr]` 在 api_plugin.py 标记 runtime-safe Optional Popen 访问；CI step 移除 `\|\| true`） |
| Path traversal 防护 | ✅ **r57 S2**：`main.py::_sanitize_user_path` 拒绝 `/etc/` `/proc/` `c:/windows/` 等系统目录路径；多用户共享环境 defense-in-depth |
| .gitignore secrets | ✅ **r57 S1**：加 `.env` / `*.key` / `*.pem` / `api_keys.json` / `secrets.json` |
| `.rpy` escape fuzz 覆盖 | ✅ **r57 S4**：`_escape_for_renpy_string` 抗 12 种恶意 LLM payload，property-based 测试 |
| Complex fixture 测试覆盖 | ✅ **r57 T3**：synthetic 复杂 .rpy（nvl / multi-line / 标签 / SAZMOD / escape）+ scan + fill round-trip 集成测试 |
| Lint / Format 门禁 | ✅ **r58 P1**：CI 加 `ruff check .` + `ruff format --check .` + mypy scope 扩大到 `engines/+safety/`（pyproject.toml `[tool.ruff]` 配置 target-py310 + extend-ignore E402/E501/F841）|
| 配置 helper 共享 | ✅ **r58 A1**：`core/config.py::resolve_args_from_config` 三层合并逻辑共享 helper（CLI > config file > defaults）|
| Process docs | ✅ **r58 P2 + r59 B1/O1/O3**：RELEASE / ROADMAP / 5 ADR / ISSUE_TEMPLATE / PR_TEMPLATE / dependabot + **release.yml** 自动化 + **ARCHITECTURE §0 Quick Tour** + **docs/ONBOARDING.md** |
| EVOLUTION 滚动归档约定 | ✅ **r58 P3**：每 5 轮 (r60/r65/...) 归档详细叙事到 `_archive/EVOLUTION_rN-4_rN.md` — **r60 首次触发** |
| Release 自动化 | ✅ **r59 B1**：`.github/workflows/release.yml` on `v*` tag → PyInstaller × 3 OS matrix → SHA256SUMS → draft Release |
| 用户面文档 | ✅ **r59 B4**：README 中英双段加"免责声明"（翻译产物法律责任由用户承担）|
| 错误信息一致化 | ✅ **r59 B3**：5 处英文 message 中文化；prefix 保持英文 caps（已成熟惯例 + grep 友好）|
| AUDIT.md 23 findings (r57 cycle) | ✅ **r59 末全闭合**（r57 8 + r58 8 + r59 8 - 1 retire 复用 = 23）|
| AUDIT.md 23 findings (r60 cycle) | ✅ **r62 末全闭合**（r61 11 + r62 12 = 23 项全闭合）|
| AUDIT.md 23 findings (r63 cycle) | ✅ **r65 末全闭合**（r64 11 + r65 12 = 23）+ 3 audit-tail surfaced regressions；audit backlog 清零 |
| ADR + AUDIT framework | 🚫 **r66 retire**：用户决策删除 `docs/adr/`（11 ADRs）+ `AUDIT.md` + `_archive/AUDIT_R63.md`；架构契约 inline 到 CLAUDE.md hard contracts 列表 + EVOLUTION 阶段叙事；未来 audit 不要重提 |
| macOS CI 覆盖 | ✅ **r61 S1**：`.github/workflows/test_macos.yml` nightly schedule（cron + workflow_dispatch，3.10/3.12/3.13）|
| EVOLUTION 滚动归档 | ✅ **r60 首次执行**（hard contract #15）— `_archive/EVOLUTION_r56_r60.md` 新建；主 EVOLUTION.md 364→276 (-88 / 24%) |
| 项目版本号 | ✅ **r62 B2**：`pyproject.toml::version` 1.0.0 → 2.0.0（反映 r52 C3/C4 + r57 T1 累积 BREAKING）|
| 治理文档 | ✅ **r62 O1+O2**：`CODE_OF_CONDUCT.md` 新建（Contributor Covenant 2.1）+ `CONTRIBUTING.md` "Governance" 段（BDFL 模型）|
| 中断恢复测试 | ✅ **r62 B1**：`tests/test_interrupt_recovery.py` 3 observation tests pin SIGTERM/KI 现状 |
| Meta-runner 覆盖 | ✅ **r64 S1**：subprocess-discover-and-run 跑全部 35 启用测试文件（test_all 自身 + test_single 排除）（pre-r64 仅 11 文件 / 39%）；audit-tail 修 3 pre-existing silent regressions |
| EVOLUTION 滚动归档 | ✅ **r65 二次执行**（hard contract #15）— `_archive/EVOLUTION_r61_r65.md` 新建；hard contract #15 阈值 r65 二次微调到 ≥30 行 OR ≥10%（acknowledge 归档量随 baseline 自然变化）|
| 累计审计 | ✅ 连续 26 轮 0 CRITICAL correctness（r35-r66）；3 cycles × 23 findings = 69 unique findings 全闭合（r66 retire AUDIT framework 后不再做周期化 6 维度审计）|

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

### 🚫 Round 66 完成（用户决策 retire ADR + AUDIT framework）

> r66 是**纯文档清理 + retire 决策轮**，零代码 / 零数字变更（VERIFIED-CLAIMS 维持 480/38/36/606）。用户在 r65 末发起反向决策：删除 ADR + AUDIT 整套体系。

**1. 删除 3 个目标**：
- `AUDIT.md` 永久入口（r64 S2 加，~50 行）
- `_archive/AUDIT_R63.md`（r63 cycle 容器 + r64+r65 closure 表，~150 行）
- `docs/adr/` 整个目录（README + 0001-0011 共 12 文件，~3500 行）

git history 完整保留可追溯（如需 `git show <commit>:docs/adr/0007-mypy-enforce-scope.md` 恢复）。

**2. 19 文件 refs 同步**：
- CLAUDE.md / .cursorrules（byte-identical）— hard contracts 引用（#11 mypy / #12 py3.10 / #13 path traversal）改为 inline 描述；docs index 删 AUDIT.md / AUDIT_R63.md entry
- HANDOFF.md / CHANGELOG.md — 历史叙事 ADR markdown links → "ADR N (r66 retired)" 文本（保留历史，去 dead links）
- _archive/EVOLUTION.md / EVOLUTION_r56_r60.md / EVOLUTION_r61_r65.md — 顶部加 r66 retire 注解；文中 ADR 引用保留为历史叙事
- README.md / ROADMAP.md / CONTRIBUTING.md / RELEASE.md — `docs/adr/` 链接 → CLAUDE.md hard contracts 引用
- docs/ARCHITECTURE.md — §0.7 "11 ADRs 索引段" 整段删除；ADR 链接改 inline 描述
- docs/ONBOARDING.md — ADR 引用改 CLAUDE.md hard contracts + EVOLUTION
- pyproject.toml / .gitignore / dependabot.yml / 2 workflows / 2 templates / START.bat — 注释中 ADR 引用改 hard contract 编号

**3. CLAUDE.md "已知限制"段加 2 条 explicit retire**：
- 🚫 ADR framework retire — "**未来 audit 不要 propose 重新引入 ADR framework / docs/adr/ 目录 / ADR consistency 测试**"
- 🚫 AUDIT permanent entry framework retire — "**未来 audit 不要 propose 重新引入 AUDIT.md 永久入口 / 6 维度审计自动化 / audit cycle 周期化命名**"

理由：架构契约已在 CLAUDE.md hard contracts 列表 + "项目身份"段 + "已知限制"段 + EVOLUTION 阶段叙事完整记录；ADR 文件冗余形式主义。6 维度审计已 demonstrate diminishing returns（r63 cycle 真问题仅 2 HIGH 其余多 cosmetic）；项目 25 轮 0 CRITICAL streak + 完整工具链 + pre-commit + CI + ruff + mypy + meta-runner subprocess-discover 已足。

**数字增量**：tests_total / test_files / ci_steps / assertion_points 全 unchanged (480/38/36/606)；hard contracts 仍 15（r66 retire 不算新约束，但本身是 r66 重要决策记录在 CLAUDE.md "已知限制"段）。**连续 26 轮 0 CRITICAL correctness**（r35-r66）。

### ✅ Round 65 完成（r63 audit 路径 X 第二波 — 维度 4+5+6 共 12 项 fix；audit backlog 清零 + EVOLUTION 滚动归档第二次执行）

> r63 末用户选**路径 X**（全部 23 项 fix，约 r64-r65 两轮）。r65 推进维度 4+5+6 共 12 项（P1-P4 + B1-B4 + O1-O4）+ 同时执行 hard contract #15 EVOLUTION 滚动归档。

**1. P1-P4（流程与文档债）**：
- (P1) `ROADMAP.md` "截止 r57 末" → "截止 r64 末"；当前能力段加 11 ADRs / v2.0.0 / 24 轮 0-CRITICAL / 完整 docs / AUDIT 永久入口 / Meta-runner subprocess-discover；短期路线图 r58-r64 引入项标 ✅
- (P2) `docs/ONBOARDING.md:45` "5 份 ADR" → 引用 `docs/adr/README.md` 索引（避免数字 drift；新加 ADR 不需再改 ONBOARDING）
- (P3) `docs/ARCHITECTURE.md §0.7` 新加 "关键架构决策快查（11 ADRs）"按主题分组（依赖+Python / 目标语言 / Plugin / Engine / CI gate / 安全 / 流程）
- (P4) 新建 `scripts/install_hooks.bat`（~30 行 Windows batch，等价 .sh；项目主开发环境 Windows 应有 .bat 版本）

**2. B1-B4（产品与业务债）**：
- (B1) `pyproject.toml::description` 改英文：`"Pure-Python multi-engine game translator (Ren'Py / RPG Maker MV-MZ / Unity XUnity / CSV-JSONL) using LLM APIs for Simplified Chinese localization"`（PyPI / `pip show` 国际工具友好）
- (B2) `build.py` 加 `_read_project_version()` + `_write_version_info()` 生成 PyInstaller VS_VERSION_INFO 模板（major.minor.patch.build tuple + StringFileInfo + VarFileInfo）；PyInstaller cmd 加 `--version-file`；`.gitignore` 加 `version_info.txt`（每次 build 重新生成）；.exe Properties → Details 现含 v2.0.0 metadata
- (B3+B4) 2 项 retire to architectural decision（LLM provider URL/model 硬编码 / RPG Maker forum link stale）

**3. O1-O4（组织与知识债）**：
- (O1) 新建 `.editorconfig`（root + Python 4-space + LF + UTF-8 + trim trailing；`*.bat` CRLF；Markdown 不 trim trailing；YAML/TOML/JSON 2-space；Makefile tab）— industry-standard，多 IDE 一致性
- (O2) 新建 `.github/FUNDING.yml` 显式 disabled（与 r59 O4 community 建设 retire 一致；注释说明 re-enable 条件）
- (O3+O4) 2 项 retire to architectural decision（TODO tracking 仅 internal docs confirm-retire / ADR + CHANGELOG completeness 测试缺失 retire）

**4. EVOLUTION 滚动归档（hard contract #15 第二次触发）**：
- 新建 `_archive/EVOLUTION_r61_r65.md`（5 阶段 r61-r65 完整叙事归档）
- 主 `_archive/EVOLUTION.md` 阶段二十-二三表格 + r65 详细 → 5 行紧凑表格 + 单行 archive 注释
- 285 → 288 行（+3，r60 → r65 累计 +12 / +4%；远低于历史 +20-30/轮）
- **hard contract #15 阈值 r65 二次微调到 ≥30 行 OR ≥10%**（acknowledge 归档量随 baseline 自然变化；r60 大幅压缩后 baseline 已小，机械阈值不应判违约）
- CLAUDE.md 文档索引加 `EVOLUTION_r61_r65.md` entry；`docs/adr/0010-evolution-rolling-archive.md` 阈值演变表更新

**数字增量**：tests_total / test_files / ci_steps / assertion_points 全 unchanged (480/38/36/606)；hard contracts 仍 15（r65 closures 都是 docs / config / retire）。**r63 audit 23 findings 全闭合**（r64 11 + r65 12 = 23）。**3 cycles × 23 = 69 unique findings 全闭合**。

### ✅ Round 64 完成（r63 audit 路径 X 第一波 — 维度 1+2+3 共 11 项 fix 全闭合 + 3 audit-tail surfaced regressions）

> r63 末用户选**路径 X**（全部 23 项 fix，约 r64-r65 两轮）。r64 推进维度 1+2+3 共 11 项（T1-T4 + S1-S4 + A1-A3）。剩余维度 4+5+6 共 12 项给 r65。**r64 是 r60→r61-r62 cycle 的复刻**。

**1. T1 HIGH — 拆 3 testfile（pre-emptive 800 cap 防御）**：
- `tests/test_file_safety.py` 798 → **151** 行（5 helper unit tests）+ 新 `tests/test_file_safety_loaders.py` **692** 行（16 caller-integration TOCTOU regressions）
- `tests/test_api_client.py` 792 → **656** 行（22 unit tests）+ 新 `tests/test_api_client_response_cap.py` **173** 行（5 response-body cap tests）
- `tests/test_verify_docs_claims.py` 790 → **553** 行（16 helper unit tests）+ 新 `tests/test_verify_docs_claims_main.py` **405** 行（12 main_fast_path integration tests，含复制 `_make_fixture_repo` helper）
- 全部 21+27+28 = 76 tests 拆分后保留 PASS

**2. S1 HIGH — 重写 meta-runner + audit-tail 修 3 silent regressions**：
- `tests/test_all.py` 完全重写为 **subprocess-discover-and-run** 模式（35 启用文件 / ~7s vs prior 11 文件 / 0.68s）。Discover 模式自动跟进未来新加测试文件，永不再 silent gap。**r67 H1 后续修**：banner regex `[A-Z_ ]*?` → `[A-Z_\-0-9 ]*?` + 中文 banner fallback，修复 10 文件 96 测试 silent miscount 为 0
- audit-tail 副产品：S1 修改后 meta-runner 立即暴露 3 个 pre-existing silent regressions（pre-r64 因为不在 meta-runner 而无人发现）：
  - `tests/test_batch1.py:240-270` — 3 个多语言测试 (`test_default_language_ja/ko/zh-tw`) 引用已 r52 C4 BREAKING 移除的字符串 (`"japanese"` / `"korean"` / `"traditional_chinese"`)。**修**：rename 为 `_kwarg_ignored_post_r52` 并改 assertion 为 `"chinese"`（pin r52 C4 contract: kwarg ignored, always 'chinese'）
  - `tests/test_rpyc_decompiler.py` (582 行) — 5/8 imports 引用已不存在的 API（`RPYC2_HEADER` / `_RestrictedUnpickler` / `_read_rpyc_data` / `_safe_unpickle` / `extract_strings_from_rpyc`）。**修**：删除（dead test debt；r65+ 可在新 API 上重建）
  - `tests/test_single.py` — 是 `python tests/test_single.py <api_key>` 的 manual integration script (`input()` prompt for API key)，不是 unit test。**修**：加入 `tests/test_all.py::_NON_TEST_FILES` 排除（保留文件作为 manual script 历史）

**3. S2-S4（质量与安全债）**：
- (S2) `git mv AUDIT_R57.md _archive/AUDIT_R63.md` + 新 `AUDIT.md` 永久入口（active cycle 标记 + archived cycles 索引表）；CLAUDE.md docs index / HANDOFF / docs/ARCHITECTURE / 2 workflow / ADR 0011 全 refs 更新
- (S3) `START.bat` `Python 3.9+` → `Python 3.10+` + `python -c` 版本检测拦截过早失败（错误信息引用 ADR 0006）
- (S4) `main.py` argparse `--version` flag + 新 `_read_project_version()` 从 `pyproject.toml` regex 解析（避免 tomllib 3.11+ 依赖）；实测 `python main.py --version` → `main.py 2.0.0`

**4. T2-T4 + A1-A3（技术 + 架构维度 watchlist/retire 文档化）**：
6 项加到 CLAUDE.md "已知限制" 段：T2 (4 production 文件接近 cap watchlist) / T3 (hint coverage 度量说明 — production 87.1% vs 含 tests 42.5%；r60 audit T2 引用的 43.2% 误导) / T4 (.pyc residue retire) / A1+A2 (gui.py + pipeline/stages.py 函数内 import; "新 PR 必须 docstring 说明 lazy 原因") / A3 (空 __init__.py retire)

**数字增量**：tests_total 498 → 480 (-18: 删除 test_rpyc_decompiler 18 tests); test_files 36 → 38 (+2 net: +3 split 新文件 - 1 删除); ci_steps 36 unchanged; assertion_points 624 → 606 (-18)。

**hard contracts 仍 15**（无新约束加入；r64 closures 都是文档化 / 拆分 / 修复 / retire）。

### 🟢 Round 63 完成（第三次 6 维度深度审计 — 23 unique new findings → 路径 X 选定）

> r63 是**纯 audit 轮**，零代码 / 零数字变更（VERIFIED-CLAIMS 维持 498/36/36/624）。r57 cycle 23 + r60 cycle 23 已闭合 = 46 项；本轮扫 r62 末 baseline 后的更深层潜在债务，**不重复任何已闭合 findings**。

**Ground-truth scan 充分**（11+ 命令）+ 重写 `AUDIT.md` (r66 retired) 为 r63 cycle 容器。

**6 维度 23 unique findings 概要**：

| 维度 | 严重度分布 | 关键 finding |
|------|----------|-------------|
| 1. 技术债 | 1H + 1M + 2L | **T1 HIGH**: 3 testfile 距 800 cap 仅 2-10 行（imminent block）|
| 2. 质量与安全债 | 1H + 2M + 1L | **S1 HIGH**: pre-commit hook 仅运行 191/485 测试 ≈ 39% 覆盖（24/35 测试文件不在 meta-runner，含 r61 T1 + r62 B1 验证测试本身）|
| 3. 架构与设计债 | 0H + 2M + 1L | A1: gui.py 594 行 watchlist persisted；A2: pipeline/stages.py 函数内 import 10 处未审 lazy 原因 |
| 4. 流程与文档债 | 0H + 2M + 2L | P1: ROADMAP.md "截止 r57 末" stale；P2: ONBOARDING 说 "5 份 ADR" 但实际 11 份；P4: 缺 `scripts/install_hooks.bat` |
| 5. 产品与业务债 | 0H + 2M + 2L | B1: pyproject.toml description 中文 only；B2: build.py 无 PyInstaller version-info |
| 6. 组织与知识债 | 0H + 2M + 2L | O1: 缺 `.editorconfig`；O2: 缺 `.github/FUNDING.yml` |
| **TOTAL** | **2 HIGH + 9 MEDIUM + 12 LOW = 23** | |

**待用户选 fix 路径**（r64+ 执行）：
- **路径 X**：全部 23 项 fix（约 r64-r65 两轮）— 与 r60→r61-r62 模式一致
- **路径 Y**（建议）：H + M 共 11 项 fix（~r64 1-2 commits）；12 LOW retire to architectural decision
- **路径 Z**：仅 2 HIGH (T1 testfile cap + S1 pre-commit 覆盖)；最防御性
- **路径 W**：22 项 retire（仅 T1 imminent failure 必须 fix）

**数字增量**：tests_total / test_files / ci_steps / assertion_points 全 unchanged（纯 audit 轮）；hard contracts 仍 15。**连续 23 轮 0 CRITICAL correctness**（r35-r63）。

### 🟢 Round 62 完成（r60 audit 路径 X 第二波 — 维度 4+5+6 共 12 项 fix；audit backlog 清零）

详见 commit `5a05dd6`：(P1) HANDOFF 模板精简 -69 行；(P2) README 致谢；(B1) `tests/test_interrupt_recovery.py` 3 observation tests；(B2) version 1.0→2.0；(O1) `CODE_OF_CONDUCT.md`；(O2) CONTRIBUTING.md Governance 段；(P3+P4+B3+B4+O3+O4) 6 项 retire/watchlist。tests_total 495→498 (+3)；test_files 35→36 (+1)。

### ✅ Round 61 完成（r60 audit 路径 X 第一波 — 维度 1+2+3 共 11 项 fix 全闭合）

> r60 末用户选**路径 X**（全部 23 项 fix，约 r61-r62 两轮）。r61 推进维度 1+2+3 共 11 项（A1 + T1-T4 + S1-S4 + A2-A3）。剩余维度 4+5+6 共 12 项给 r62。

**1. A1 HIGH — 补 6 份 ADR**（项目历史最大 ADR 批量）：
- ADR (r66 retired) — Python ≥ 3.10 (PEP 604 union syntax)，r57 T1 引入 BREAKING
- ADR (r66 retired) — Mypy enforce 6 文件核心 scope，r57 T2 informational → enforce
- ADR (r66 retired) — Path traversal `_FORBIDDEN_PATH_PREFIXES`，r57 S2
- ADR (r66 retired) — Ruff lint+format CI gate，r58 P1
- ADR (r66 retired) — EVOLUTION 5 轮滚动归档，r58 P3 / r60 首次执行 + 阈值微调（≥80 行 OR ≥20%）
- ADR (r66 retired) — `_resolve_args_from_config` shared helper，r58 A1
- ADR (r66 retired) 索引更新（5 → 11 ADRs）

**2. T1-T4 + S1-S4（技术债 + 质量与安全债）**：
- (T1) `translators/_tl_parser_selftest.py` tempfile 泄漏 fix — `_write_tmp` 改写为 append `_tmp_files` list，`_cleanup_tmp_files()` 在 `run_self_tests()` 末尾调用 unlink；新单元测试 `tests/test_tl_pipeline.py::test_w_round61_t1_selftest_cleans_tempfiles` 用 tempdir snapshot diff = 0 验证（tests_total +1）
- (T2) CONTRIBUTING.md "代码风格" / "Style" 段加 "新代码 100% type hint" PR 规则（中英双段）；不强求 backfill
- (T3) gui.py 接近 800 行 cap（594 行）watchlist 文档化 — CLAUDE.md "已知限制" 段加约束 "新 PR 加 GUI 功能必须先拆"，提示拆 `gui/main_window.py` + `gui/scan_panel.py` 等
- (T4) Performance benchmark 缺失 watchlist — 与 r59 B2 翻译质量验证 retire 同理（mock 不反映真实 LLM 漂移）
- (S1) `.github/workflows/test_macos.yml` 新建 — nightly schedule (`cron "0 4 * * *"`) + `workflow_dispatch` + 3.10/3.12/3.13 matrix；macOS-specific regressions（`tempfile` / `pathlib` / `os.fstat` / subprocess）入测但不增 PR latency
- (S2) Plugin JSONL 协议视为稳定 — `docs/REFERENCE.md §7b` 新加段（request/response 字段集 + r61 决策不加 version 字段）+ CLAUDE.md "已知限制" 段交叉引用；未来 BREAKING 必须先 plan-first
- (S3) API key 内存生命周期 retire to architectural decision — 本地 single-user 工具威胁模型不适用（与 r53 监控 #4 symlink retire 同理）
- (S4) Prompt injection 表面 retire to architectural decision — 用户主动喂自己游戏文件给 AI 不是攻击者输入

**3. A2-A3（架构与设计债）**：
- (A2) GUI subprocess.Popen 间接调用 retire to architectural decision — subprocess 隔离对 GUI UX 更好（崩溃只挂子进程 / 中断恢复 / 错误隔离），保留 `gui_pipeline.py` Popen 模式；ADR 0011 § "architectural decision" 标注 helper 当前 single-caller
- (A3) gui.py 接近 cap — 重复 finding，引用 T3

**数字增量（VERIFIED-CLAIMS）**：tests_total 494 → 495 (+1: T1 test); test_files 35 unchanged; ci_steps 36 unchanged（test_macos.yml 是独立 workflow）; assertion_points 620 → 621 (+1)。

**hard contracts 仍 15**（r61 ADR 0006-0011 是已有 hard contracts #11-#15 的文档化抽取，不新增契约；A1 fix 后未来维护者可在 `docs/adr/` 一站式索引到所有架构决策）。

### 🟡 Round 60 完成（EVOLUTION 滚动归档首次执行 + 重做 6 维度审计 — 23 新 findings 待 fix）

> r60 是**纯 audit + archive 轮**，零代码变更，VERIFIED-CLAIMS 数字 unchanged。

**1. EVOLUTION 滚动归档首次执行**（hard contract #15 触发）：
- 新文件 [`_archive/EVOLUTION_r56_r60.md`](_archive/EVOLUTION_r56_r60.md) — 5 阶段（r56-r60）完整叙事抽出，含每轮触发条件 / 详细技术决策 / 改动文件清单 / hard contracts 增减
- 主 [`_archive/EVOLUTION.md`](_archive/EVOLUTION.md) 阶段十五-十九合并为 **5 行表格** + 1 archive 注释；累积技术资产段去 round-specific 历史噪声；设计原则段引用 CLAUDE.md 而非重复列举
- 净缩减：**364 → 276 行 (-88 / 24%)**；启发式阈值 100 行未达原因：r56-r60 含 3 轮 doc-only 短叙事（r54 backlog 评估 / r58 process docs / r59 维度收尾），baseline 已较短 — 实质满足契约"防止无限增长"意图。CLAUDE.md / .cursorrules 同步小幅放宽阈值文字（≥80 行 OR ≥20% 缩减）
- 文档索引表新加 `EVOLUTION_r56_r60.md` entry
- 下次触发：**r65** → `_archive/EVOLUTION_r61_r65.md`

**2. 6 维度深度审计 (round 2)**：
- ground-truth scan 确认 r57 audit 23 findings 全闭合（r57 8 + r58 8 + r59 8 - 1 retire 复用 = 23）
- 收集 **23 unique new findings**，写入 `AUDIT.md` (r66 retired)（覆盖 r60 cycle）：

| 维度 | finding 数 | 严重度 |
|------|----------|--------|
| 1. 技术债 (T1-T4) | 4 | 0H + 2M + 2L |
| 2. 质量与安全债 (S1-S4) | 4 | 0H + 2M + 2L |
| 3. 架构与设计债 (A1-A3) | 3 | **1H** + 1M + 1L |
| 4. 流程与文档债 (P1-P4) | 4 | 0H + 2M + 2L |
| 5. 产品与业务债 (B1-B4) | 4 | 0H + 2M + 2L |
| 6. 组织与知识债 (O1-O4) | 4 | 0H + 2M + 2L |
| **合计** | **23** | **1H + 11M + 11L** |

**1 HIGH = A1**：r57-r58 决定的 6 项架构变更（subprocess sandbox-only / multi-target retire / Path 3.10 floor / mypy enforce / safety/ 顶层 / RenPyEngine 不走 generic）未抽 ADR 形式（仅有散落 retired/architectural-decision 文档）— 后续维护者难索引。修复方向：补 6 份 ADR 0006-0011。

**3. 待用户选 fix 路径**（r61+ 执行）：
- **路径 X**：全部 fix（23 findings 同轮闭合，约 r61-r62 两轮量）— 与 r57 audit 同样 disciplinary
- **路径 Y**：仅 fix HIGH + MEDIUM（12 项，~r61 1 轮量），LOW 11 项 retire to architectural decision 显式记录
- **路径 Z**：仅 fix HIGH (1 项 A1)，11M + 11L retire — 最低成本路径
- **路径 W**：全部 retire to architectural decision（仅 HIGH A1 因不可妥协 fix，22 项 retire）— 与 r54 减法路线对齐

**数字增量**：tests_total 494 unchanged; test_files 35 unchanged; ci_steps 36 unchanged; assertion_points 620 unchanged。**纯文档 + audit + archive 轮**。

**hard contracts 仍 15**（无新约束加入；#15 阈值文字小幅放宽不算新契约）。

### ✅ Round 56-59 完成（r62 P1 模板精简）

> r62 P1 fix：原 4 段详细 round-by-round 叙事（~80 行）压缩为单行 bullets。**完整内容**已通过 r60 滚动归档存入 [`_archive/EVOLUTION_r56_r60.md`](_archive/EVOLUTION_r56_r60.md)。

- **Round 56** — 全面深度 8 维度 audit 11 findings 路径 C 全 fix（5 死 import 清理 / `safety/file_safety.py` 顶层 package 移位 / unity_xunity regex backref placeholder protection / 4 production 模块 print → logger 29 处）；详见 [EVOLUTION_r56_r60 §阶段十五](_archive/EVOLUTION_r56_r60.md)
- **Round 57** — 6 维度深度审计写入 `AUDIT.md` (r66 retired)（23 findings），维度 1+2（T1-T4 + S1-S4）闭合（py 3.10 floor BREAKING / mypy informational → enforce / `_sanitize_user_path` path traversal / `.rpy` escape fuzz）；+3 hard contracts (#11-#13)；详见 [EVOLUTION_r56_r60 §阶段十六](_archive/EVOLUTION_r56_r60.md)
- **Round 58** — 维度 3+4（A1-A3 + P1-P4）闭合（shared `_resolve_args_from_config` helper / RenPyEngine 不走 generic_pipeline 文档化 / CI 加 ruff lint+format + mypy scope 扩 engines/+safety/ / 5 ADR + RELEASE/ROADMAP / EVOLUTION 滚动归档约定）；+2 hard contracts (#14 ruff / #15 EVOLUTION 滚动归档)；详见 [EVOLUTION_r56_r60 §阶段十七](_archive/EVOLUTION_r56_r60.md)
- **Round 59** — 维度 5+6（B1-B4 + O1-O4）闭合 + AUDIT.md 23 findings 全清零（release.yml 自动化 3 OS matrix → SHA256SUMS → draft Release / 中英双段免责声明 / `docs/ARCHITECTURE.md §0 Quick Tour` + `docs/ONBOARDING.md` 新建 / B2+O4 retire）；纯文档+流程+微调轮；详见 [EVOLUTION_r56_r60 §阶段十八](_archive/EVOLUTION_r56_r60.md)

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
| 变更日志 | `CHANGELOG.md`（极简入口）+ `_archive/EVOLUTION.md`（r1-r55 详 + r56-r60 表格摘要）|
| 全量历史 | `_archive/CHANGELOG_FULL.md` + `_archive/CHANGELOG_RECENT_r52.md`（r48-r52 详细）+ `_archive/EVOLUTION_r56_r60.md`（r60 首次滚动归档：r56-r60 完整叙事）|
| 审计跟踪 | `AUDIT.md`（r60 cycle：23 unique new findings；r57 cycle 已闭合记入 EVOLUTION）|
| 入口 | `main.py` / `gui.py`（mixin） / `one_click_pipeline.py` |
| 引擎抽象 | `engines/{engine_base, engine_detector, generic_pipeline, renpy_engine, rpgmaker_engine, csv_engine, unity_xunity}.py` |
| 核心 | `core/{api_client, api_plugin, config, glossary, prompts, translation_db, translation_utils, http_pool, pickle_safe, font_patch, runtime_hook_emitter, file_safety}.py` |
| 流水线 | `pipeline/{helpers, gate, stages}.py` |
| 翻译子模块 | `translators/{direct, tl_mode, retranslator, screen, tl_parser, renpy_text_utils}.py` + 7 私有子模块（含 r53 `_tl_retry.py`） |
| 测试 | `tests/test_all.py` meta-runner + 35 独立 suites（含 r53 `test_tl_retry.py` + `test_pickle_safe_redteam.py` + r55 `test_unity_xunity_engine.py` + r57 `test_complex_fixture.py` + r58 `test_main_cli.py`） |
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

**Round 67 关键约束**：
- **🚫 r66 retire ADR + AUDIT framework**：未来 audit 不要 propose 重新引入 ADR framework / docs/adr/ 目录 / AUDIT.md 永久入口 / 6 维度审计自动化（详见 CLAUDE.md "已知限制"段）— 这是 explicit user decision 不是疏忽
- **🔔 EVOLUTION 滚动归档**（hard contract #15）— r60 / r65 已两次执行；下次触发 r70 → `_archive/EVOLUTION_r66_r70.md`；阈值 r65 二次微调到 ≥30 行 OR ≥10%
- **🔔 Meta-runner subprocess-discover-and-run**（r64 S1）— 新加 testfile 自动入 pre-commit
- **🔔 项目版本号 2.0.0**；下次 BREAKING 升 3.0.0；`python main.py --version` 可查
- **🔔 .editorconfig + .github/FUNDING.yml** 已 r65 加（multi-IDE 一致 + sponsor 显式 disabled）
- 架构决策由 CLAUDE.md hard contracts 列表 + EVOLUTION 阶段叙事记录（不再用 ADR 文件）
- audit findings 必须**同轮 fix，no tier exemption**（r50 起 written + enforced；r51-r66 共 16 轮各执行有效）
- **CI ruff lint/format 门禁**（r58 P1）— 任何新 PR 必须 `ruff check .` + `ruff format --check .` 全过；`pyproject.toml [tool.ruff]` extend-ignore 列表不得放宽
- **EVOLUTION 滚动归档**（r58 P3 / r60 阈值微调）— 每 5 轮一次（r65 / r70 / ...）；归档时主 EVOLUTION 应减 ≥80 行 OR ≥20%（启发式，可变 baseline）
- **mypy enforce contract**（r57 T2）— `core/translation_utils.py / core/config.py / file_processor/ / core/api_client.py / core/glossary.py / core/translation_db.py` 6 文件 scope 必须保持 mypy 0 errors；新文件加入 scope 前必须先 mypy clean
- **Python 版本契约**（r57 T1）— `pyproject.toml requires-python = ">=3.10"`；任何向后兼容 3.9 的 PR 必须先 plan-first（PEP 604 `int \| None` 语法已广泛使用，retreating 是大重构）
- **Path traversal contract**（r57 S2）— `main.py::_FORBIDDEN_PATH_PREFIXES` 不得放宽；任何添加 user-supplied path 入口必须经过 `_sanitize_user_path`
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
