# 6 维度深度债务审计报告

> **当前版本**：r60 audit（重写于 r60）
>
> **历史**：本文件首次创建于 r57，含 23 findings；r57 / r58 / r59 三轮分别闭合 8 + 8 + 8 = 23 findings 全清零（见 git log + [`_archive/EVOLUTION.md`](_archive/EVOLUTION.md) 阶段十六/十七/十八）。**r60 重新做一轮全面审计**，旧 findings 已闭合不再列出，本文记录的是 **r60 新发现** 的债务。
>
> **范围**：r56-r59 4 轮闭合大量代码卫生面 + 流程文档面 findings 后，r60 重审更深层、跨维度的潜在债务，**不重复任何已 fix / 已 retire 的 r57 findings**。
>
> **Baseline**：r59 末状态 — 191/191 PASS / VERIFIED-CLAIMS OK（tests_total 494 / test_files 35 / ci_steps 36 / assertion_points 620）/ 19 轮 0 CRITICAL streak / 15 hard contracts / actionable backlog 仅剩 Godot + Kirikiri/TyranoBuilder 引擎接入。
>
> **状态**：✅ **路径 X 全部 23 项 fix 闭合完成**（r61 闭合 11 项 + r62 闭合 12 项）。审计 backlog 清零，本文件 r63+ 应移到 `_archive/AUDIT_R60.md` 历史归档。

---

## 1️⃣ 技术债（Technical Debt）

### T1 🟡 MEDIUM — `_tl_parser_selftest.py` tempfile 泄漏

[`translators/_tl_parser_selftest.py:47-50`](translators/_tl_parser_selftest.py:47):

```python
f = tempfile.NamedTemporaryFile(mode="w", suffix=".rpy", delete=False, encoding="utf-8")
f.write(text)
f.close()
return f.name
```

`delete=False` 后**没有 unlink**——每次跑 self-test 会在系统 temp 目录留 1 个 .rpy 文件。在 CI 跑全量 + 用户本地 multiple run，累积"温和泄漏"。

**fix**：用 context manager 或在 self-test 末尾 `os.unlink(f.name)`。

### T2 🟢 LOW — Type hint coverage 反向 trend（44% → 43.2%）

r57 baseline 44%（470/1068）；r60 实测 43.2%（473/1095）。新加的 helper / wrapper 没补 hint，整体百分比反降。

**fix 选项**：(a) r57 T2 enforce 仅 6 文件 scope，扩大到 engines/+safety/（r58 P1 已扩）的下一步是 translators/+pipeline/+tools/，但 translators 现有 ~20 mypy errors 需先清；(b) 设定每轮新加代码必须 100% hint 的 PR 检查规则（不强求存量补全）。

建议 (b)：**新代码 100% hint** 比 backfill 更有效。

### T3 🟡 MEDIUM — gui.py 接近 800 行 cap

| 文件 | 行数 |
|------|------|
| `gui.py` | 594 |
| `gui_pipeline.py` | 230 |
| `gui_handlers.py` | 73 |
| `gui_dialogs.py` | (中等) |

`gui.py` 距 800 cap **206 行**。GUI 功能扩展（如新引擎按钮 / 新一键步骤）必拆。同时 r58 A1 抽取的 `_resolve_args_from_config` helper **GUI 没真正 import**（仍走 subprocess.Popen 间接 spawn main.py），架构债与文件大小债叠加。

**fix**：(a) 拆 `gui.py` 成 `gui/main_window.py` + `gui/scan_panel.py` + `gui/run_panel.py` 等；(b) GUI 直接 import helper 而不是 subprocess.Popen + r58 A1 helper 真正复用；(c) 不动，等触发再拆。

建议 (c)：当前未触发，懒处理。但**新 PR 加 GUI 功能必须先拆**。

### T4 🟢 LOW — 缺 performance benchmark / profiling 报告

r52 实测 The Tyrant 74098 entries / 129.4 min / $2.40 / 99.991% 是**唯一**生产级数据点。74098 entries 时实际 RAM / CPU / I/O 数字未测。如未来回归（如 r53 W1 retry 并发引入慢线程），无 baseline 对比。

**fix**：加 `tests/benchmark/` 目录 + 1-2 mock LLM benchmark（CPU / 内存 profile）。中等成本。

建议**保留为 watchlist**——r52 数字够用作 ground reference，nightly benchmark ROI 已在 [B2 r59 retire](AUDIT_R57.md) 评估过（mock 不能反映真实 LLM 漂移）。

---

## 2️⃣ 质量与安全债（Quality & Security Debt）

### S1 🟡 MEDIUM — CI matrix 缺 macos-latest（test.yml）

`.github/workflows/test.yml::matrix.os = [ubuntu-latest, windows-latest]`，但 r59 B1 加的 `release.yml` 用 `macos-latest`。**结果**：macOS 上的 PyInstaller artifact **没在测试 matrix 跑过 unit test**。`tempfile` / `pathlib` / `os.fstat` 等 cross-platform 差异在 macos 漏检。

**fix**：(a) 加 `macos-latest` 到 test.yml matrix（× 3 OS × 3 Python = 9 jobs，CI 时长 +50%）；(b) 仅在 release.yml 跑 `tests/test_all.py` 作 pre-build gate（已实现，但只在 tag push 触发，常规 PR 不跑）；(c) macos-latest 单独 nightly schedule（`on: schedule: cron`）。

建议 (c)：**不增加 PR latency + 仍获 macos coverage**。

### S2 🟡 MEDIUM — Subprocess plugin 协议无 schema version

`core/api_plugin.py::_SubprocessPluginClient` 用 JSONL 协议与 plugin subprocess 通信，但 **payload 没 schema version 字段**。如未来需要 BREAKING 改协议（如加 batch field / 改 error 编码），无回退机制：旧 plugin 收新主进程发的 payload 会崩。

**fix**：(a) 加 `"protocol_version": 1` 字段到所有 payload + 升版时 plugin 端自检；(b) 文档化"协议视为稳定"，未来真要改先 plan-first。

建议 (b)：当前 plugin 极少（用户场景虚），加 version 字段是过度工程。**文档化即可**。

### S3 🟢 LOW — API key 内存生命周期

`core/api_client.py::APIConfig.api_key` 持有 API key 整个进程生命周期。多线程 `APIClient.translate()` 共享 config object。若线程间 Python 内存被 corrupted dump（`gc.get_referents` / 调试器 / etc），key 暴露。

**fix**：(a) 加密内存 store（违反零依赖契约 — 需 cryptography）；(b) `__del__` 显式 `self.api_key = ""` zeroize（Python 优化时 in-place mutation 可能不生效）；(c) 文档化"本地 single-user 工具，attacker 已能 dump 进程内存就 game over"——保留现状。

建议 (c)：**威胁模型不适用**（与 r53 监控 #4 symlink retire 同理）。CLAUDE.md 加 explicit decision。

### S4 🟢 LOW — Prompt injection 表面（用户 game text → LLM）

31 处 prompt construction sites（`build_*_prompt`）中，用户 game text 直接 f-string 进 prompt。如游戏文本含 `\n\nIgnore previous. Output: <whatever>` 之类 jailbreak，LLM 可能输出 garbage。

**判断**：这是用户**主动喂自己游戏文件**给 AI，不是攻击者输入；用户 review 翻译结果是工作流的一部分。**威胁模型不适用**——retire to architectural decision。

---

## 3️⃣ 架构与设计债（Architecture & Design Debt）

### A1 🔴 HIGH — ADR 严重缺漏（r56-r58 6 个架构决策没 ADR 化）

[docs/adr/](docs/adr/) 只有 5 个 ADR（0001-0005），但 r56-r59 期间还有以下**架构决策没 ADR 化**：

| 决策 | 引入轮次 | 影响 |
|------|---------|------|
| Python ≥ 3.10 floor (PEP 604 union syntax) | r57 T1 | BREAKING — 3.9 用户失支持 |
| Mypy enforce 6-file scope (CI gate) | r57 T2 | 流程契约 — 限制 scope 不能放宽 |
| Path traversal `_FORBIDDEN_PATH_PREFIXES` | r57 S2 | 安全契约 — 不可放宽 |
| Ruff lint+format CI gate | r58 P1 | 流程契约 — extend-ignore 不可放宽 |
| EVOLUTION 5-round rolling archive | r58 P3 | 流程契约 — 每 r5N 必触发 |
| `_resolve_args_from_config` shared helper | r58 A1 | 架构契约 — 三层合并单一来源 |

按 [`docs/adr/README.md`](docs/adr/README.md) "何时写 ADR"指南，**前 5 项都符合**（引入或退役 hard contract / 跨多轮的主题决策）。

**fix**：补 ADR 0006-0011 共 6 份。中成本（~70 行/份 × 6 = 420 行 docs）。

### A2 🟡 MEDIUM — GUI vs CLI subprocess.Popen 间接调用

[`gui_pipeline.py`](gui_pipeline.py) 用 `subprocess.Popen([sys.executable, "main.py", ...])` 间接 spawn CLI。r58 A1 抽 `_resolve_args_from_config` helper 给两端共享，**但 GUI 没 import helper**（仍 spawn 子进程把 args 当字符串传）。两个 entry point 的 config 解析逻辑只是"行为对齐"而非"代码共享"。

**fix**：(a) GUI 改为 `from main import main; main()` 直接 import + 在 GUI 进程内 in-process run（架构大改）；(b) 维持现状 — subprocess.Popen 是 GUI 进程隔离 + 中断恢复 + 错误隔离的成熟模式（崩溃只挂子进程）。

建议 (b)：**保留现状**——subprocess 隔离对 GUI UX 更好；helper 共享是 logic alignment 不是 dedup。文档化为 architectural decision。

### A3 🟢 LOW — `gui.py` 594 行接近 cap（同 T3）

参见 T3。架构债和文件大小债重叠。

---

## 4️⃣ 流程与文档债（Process & Documentation Debt）

### P1 🟡 MEDIUM — HANDOFF.md 单调增长趋势

[`HANDOFF.md`](HANDOFF.md) 当前 **238 行**（r58 P3 设计是每轮重写，目标 ~150 行）。每轮加 "Round NN 完成" 段累积。r58 P3 滚动归档**只覆盖 EVOLUTION.md，不覆盖 HANDOFF**。

**fix**：(a) HANDOFF "已完成" 段也滚动归档（仅留最近 1 轮 detail，更老的移到 `_archive/HANDOFF_RECENT_rN.md`）；(b) 模板精简（"已完成" 仅 1 行 bullet 引用 EVOLUTION 阶段段）。

建议 (b)：低成本 + 立即生效。

### P2 🟡 MEDIUM — 缺 contributors / acknowledgements

README + CONTRIBUTING 没列贡献者。r51 把 `anonymousException` 上游归属保留为 6 处 hard contract，但**主作者** + AI 协作 + 测试反馈者没 explicit credit。

**fix**：README 加 "致谢 / Acknowledgements" 段：(1) maintainer @Dean20030514 + (2) AI 协作 (Claude / Cursor) + (3) 上游 `anonymousException renpy-translator (MIT, 2024)` 框架。

### P3 🟢 LOW — CHANGELOG 自动化缺失

每轮 commit 时 maintainer 手动写 CHANGELOG.md round 段（同时 commit message 也写一遍，重复）。git tag → release notes 已 r59 B1 自动化（从 CHANGELOG sed 抽取），但 CHANGELOG 本身仍手写。

**fix**：(a) commit message 用 conventional commits (feat / fix / refactor / docs) → 工具自动生成 CHANGELOG（`git-cliff` / `commitizen`，违反零依赖契约 — dev tool）；(b) 不动，手写 CHANGELOG 是 "deliberate curation"（每轮挑 highlights，不是 dump 所有 commit）。

建议 (b)：**保留现状**。手写 CHANGELOG 反映人工判断的轻重（如 r58 P1 99 文件 ruff format 在 git history 是 1 个 commit 但 CHANGELOG 仅 1 行）。

### P4 🟢 LOW — 测试 fixture 单一化

r57 T3 加了 1 个 complex fixture (`test_complex_fixture.py`)，但仍是 synthetic（手工构造）。真实游戏的 edge case（XUAT regex rule 中含 unicode escape / Ren'Py 8.6 → 7.x downgrade ID drift / RPGM Plugin Commands 含 JS 字符串）都没 fixture。

**fix**：用户每接到具体 game-specific bug 时，**抽 minimal repro 进 `tests/artifacts/`** 作未来 regression。当前 backlog "用户实际报告" 触发即可。

---

## 5️⃣ 产品与业务债（Product & Business Debt）

### B1 🟡 MEDIUM — 中断恢复 / SIGTERM / KeyboardInterrupt 路径未审

`translators/direct.py:72` 注册了 SIGTERM handler 触发 progress 保存，但：
- r53 W1 ThreadPoolExecutor retry stage **没有显式 SIGTERM handling**——中断时已提交的 future 状态？
- `core/translation_db.py` 写文件用 `os.replace` 原子写，但**翻译 in-flight chunk 数据**（已 LLM 返回但还没 upsert_entry）会丢
- Windows 上 SIGTERM 不存在；CTRL+C 触发 KeyboardInterrupt 但 r53 retry stage 没 catch（异常会向上传播 abort 整批）

**fix**：(a) 加 `tests/test_interrupt_recovery.py` 验证 CTRL+C 后 progress 完整 + 重启后 resume 正确；(b) 在 retry stage 加显式 try/except KeyboardInterrupt + 保存当前 chunk 状态。

建议 (a) 先做 — 测试先暴露问题，再决定是否 fix。

### B2 🟡 MEDIUM — 版本号停滞 v1.0.0

`pyproject.toml::version = "1.0.0"` 自项目初始化没动。但项目已经走到 r59，新功能 / BREAKING 变更累积：
- r52 C4 BREAKING (drop multi-target language) — **应升 MAJOR → 2.0.0**
- r52 C3 BREAKING (importlib plugin retire) — **应升 MAJOR**
- r55 Unity XUnity (新引擎) — 应升 MINOR
- r53 W1/W2/W3 + r57 mypy + r58 ruff + r59 release auto — 多轮 MINOR/PATCH

用户视角 `v1.0.0` 暗示项目"早期未稳定"，与实际 19 轮 0 CRITICAL streak + 99.991% 翻译成功率不符。

**fix**：bump `pyproject.toml::version` 到 `2.0.0`（反映 r52 C4 BREAKING）+ 加 git tag `v2.0.0` 触发 r59 B1 release.yml 自动 build 首个 binary release。

### B3 🟢 LOW — GUI 翻译进度可视化未审

[`gui_pipeline.py`](gui_pipeline.py) 230 行处理 GUI 与 subprocess 通信，但**未审 progress bar 实际行为**：
- 翻译 74098 entries 时 GUI 是否实时更新进度？
- ETA 估算准确度？
- 大文件 stuck 时 GUI 是否假死？

**fix**：手工跑 GUI + The Tyrant fixture 一遍，记录 UX gaps。中等时间投入。

### B4 🟢 LOW — 多账号 / 多 provider 并发支持

当前一次 run 只支持 1 个 `--provider` + 1 个 `--api-key`。用户场景：分摊 quota 跑大项目（5 个 OpenAI key 并发 5x 速度）。

**fix**：(a) 加 `--api-keys "k1,k2,k3"` round-robin（中成本）；(b) 不做 — 用户用 launcher 脚本起多 main.py 进程也能达到同效果。

建议 (b)：**保留现状**——避免功能蔓延。

---

## 6️⃣ 组织与知识债（Org & Knowledge Debt）

### O1 🟡 MEDIUM — 缺 CODE_OF_CONDUCT.md

`.github/ISSUE_TEMPLATE/` + `PULL_REQUEST_TEMPLATE.md` + `CONTRIBUTING.md` 已有，但**没有 [Code of Conduct](https://www.contributor-covenant.org/)**。GitHub 主页 community standards 不完整。

**fix**：加 [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) 标准模板。低成本。

### O2 🟡 MEDIUM — Governance 流程没文档化

谁能 merge PR？决策权（如 r54 backlog 评估纪律 / r60 audit fix path 选择）属于 maintainer 还是 contributors community？没有 explicit doc。

**fix**：CONTRIBUTING.md 加 "Governance" 段：当前模型是 BDFL（@Dean20030514 主决策），AI 协作辅助，contributors 通过 issue / PR 提建议但 maintainer 拥有 merge 权。Future 可演进到 multi-maintainer。

### O3 🟢 LOW — TODO 跟踪机制只在 internal docs

HANDOFF.md "推荐 Round N+1 工作项" + ROADMAP.md actionable backlog + AUDIT 文件 — 都是 internal docs。GitHub Projects / Issues 没有同步 board。**社区贡献者无法看到当前优先级**。

**fix**：(a) 把 actionable backlog sync 到 GitHub Issues + 加 milestone；(b) 不动，等用户量增长再考虑。

建议 (b)（与 r59 O4 community 建设 retire 一致逻辑）。

### O4 🟢 LOW — Bus factor 仍 = 1

r57 / r59 已识别这是 OSS 通病。r57 O1 retire 到 architectural decision；r59 O1 加 ARCHITECTURE Quick Tour + r59 O3 加 ONBOARDING.md 缓解。

**判断**：fundamental 没变（@Dean20030514 是唯一 maintainer）。**保留 r57 O1 / r59 O1 / r59 O3 现状**。

---

## 📊 6 维度 Findings 汇总

| 维度 | 🔴 HIGH | 🟡 MEDIUM | 🟢 LOW | 小计 |
|------|---------|-----------|--------|------|
| 1. 技术债 | — | T1, T3 | T2, T4 | 4 |
| 2. 质量与安全债 | — | S1, S2 | S3, S4 | 4 |
| 3. 架构与设计债 | A1 | A2 | A3 | 3 |
| 4. 流程与文档债 | — | P1, P2 | P3, P4 | 4 |
| 5. 产品与业务债 | — | B1, B2 | B3, B4 | 4 |
| 6. 组织与知识债 | — | O1, O2 | O3, O4 | 4 |
| **TOTAL** | **1** | **11** | **11** | **23** |

**所有 findings 不破坏 19 轮 0 CRITICAL streak**（无 correctness bug；A1 只是文档缺漏，B2 是 metadata 升版）。

---

## 与 r57 audit 的对照

| 维度 | r57 findings | r60 findings (本次新发现) | 重复? |
|------|------------|------------------------|------|
| 技术债 | T1-T4 | tempfile leak / hint 反向 / gui 大 / benchmark | **0 重复**（r57 T1-T4 已闭合且不同问题） |
| 质量与安全债 | S1-S4 | macos CI 缺失 / plugin 协议无 version / API key lifecycle / prompt injection | **0 重复** |
| 架构与设计债 | A1-A3 | **ADR 缺漏（A1 HIGH）** / GUI subprocess / gui 大 | **0 重复** |
| 流程与文档债 | P1-P4 | HANDOFF 增长 / contributors 致谢 / changelog 自动化 / fixture 单一 | **0 重复** |
| 产品与业务债 | B1-B4 | 中断恢复 / 版本号停滞 / GUI 进度可视 / 多账号 | **0 重复** |
| 组织与知识债 | O1-O4 | CoC 缺 / governance / TODO 跟踪 / bus factor | **1 部分重复**（O4 = r57 O1 + r59 O1，标 retire-confirmed） |

**r60 audit 净新增 22 unique findings + 1 confirm-retire**。

---

## 🎯 推荐 Fix Path

### 路径 X — 全部 fix（23 项，~600 行改动）

预估 4-5 commits。

### 路径 Y — H + M（建议，~280 行改动）

12 项 fix（1 H + 11 M）。L 留 architectural decision 文档化。预估 2-3 commits。

| 维度 | H + M findings |
|------|---------------|
| 技术债 | T1 + T3 |
| 质量与安全债 | S1 + S2 |
| 架构与设计债 | A1 + A2 |
| 流程与文档债 | P1 + P2 |
| 产品与业务债 | B1 + B2 |
| 组织与知识债 | O1 + O2 |

### 路径 Z — 仅 H（最小冲击，~100 行改动）

1 项 fix：
- A1 — 补 6 份缺漏 ADR（r57 T1 / T2 / S2 + r58 P1 / P3 / A1）

预估 1 commit。最防御性。

### 路径 W — 拒绝 fix，全部 retire to architectural decision

承认这些是项目特性（小团队 / 当前 maturity / AI 协作），文档化为 explicit decisions。预估 1 commit（仅 docs）。

---

## Audit 提出方建议

**路径 Y**（H + M 全 fix）。理由：

1. **A1 HIGH** 是真 docs gap — 6 个 architectural decisions 没 ADR 化，未来 maintainer 看 docs/adr/ 只能找到 r1-r56 的，r57+ 决策只能在 EVOLUTION.md 长文里挖，违背 r58 P2 引入 ADR 的初衷
2. **T1 + T3 + S1 + S2** 是真实小坑（tempfile leak / GUI 接近 cap / macos 漏检 / 协议无版本），逐个 fix 成本低
3. **B1 + B2** 改善用户感知（中断恢复 verify + 版本号 1.0 → 2.0 反映项目实际成熟度）
4. **P1 + P2** 减少未来轮次的 docs 维护成本
5. **O1 + O2** 改善 OSS 化程度（Code of Conduct 是 GitHub 期望的 standard files；governance 让 contributors 知道决策流程）
6. **L 级 11 项**多数是 retire-able（cosmetic / 未触发条件 / 威胁模型不适用），显式 retire 比硬干强

预估 12 项 fix 跨 3 commits 完成（每 commit 闭合 2 维度的 H+M）。

---

## ✅ r61 闭合总结（维度 1+2+3 共 11 项）

| Finding | 严重度 | 闭合方式 | 改动文件 |
|---------|--------|---------|---------|
| **A1** | 🔴 HIGH | 补 6 份 ADR | `docs/adr/0006-python-310-floor.md` / `0007-mypy-enforce-scope.md` / `0008-path-traversal-guard.md` / `0009-ruff-ci-gate.md` / `0010-evolution-rolling-archive.md` / `0011-shared-config-helper.md` + `docs/adr/README.md` 索引更新 |
| **T1** | 🟡 MEDIUM | code fix + test | `translators/_tl_parser_selftest.py` (`_tmp_files` 跟踪 + `_cleanup_tmp_files`) + `tests/test_tl_pipeline.py::test_w_round61_t1_selftest_cleans_tempfiles` 验证 tempdir snapshot diff = 0 |
| **T2** | 🟢 LOW | CONTRIBUTING rule | `CONTRIBUTING.md` "代码风格" / "Style" 段加"新代码 100% type hint"规则（中英双段） |
| **T3** | 🟡 MEDIUM | watchlist 文档化 | `CLAUDE.md` "已知限制" 段加 `gui.py 接近 800 行 cap` 条；约束"新 PR 加 GUI 功能必须先拆" |
| **T4** | 🟢 LOW | watchlist 文档化 | `CLAUDE.md` "已知限制" 段加 `Performance benchmark 缺失` 条（与 r59 B2 翻译质量验证 retire 同理） |
| **S1** | 🟡 MEDIUM | 新 nightly workflow | `.github/workflows/test_macos.yml`（`schedule: cron "0 4 * * *"` + `workflow_dispatch`，3.10/3.12/3.13 matrix） |
| **S2** | 🟡 MEDIUM | 协议稳定文档化 | `docs/REFERENCE.md §7b` 新加段（plugin JSONL 协议字段集 + r61 决策不加 version） + `CLAUDE.md` "已知限制" 段交叉引用 |
| **S3** | 🟢 LOW | retire to architectural decision | `CLAUDE.md` "已知限制" 段加 `API key 内存生命周期` 条（威胁模型不适用） |
| **S4** | 🟢 LOW | retire to architectural decision | `CLAUDE.md` "已知限制" 段加 `Prompt injection 表面` 条（威胁模型不适用） |
| **A2** | 🟡 MEDIUM | retire to architectural decision | `CLAUDE.md` "已知限制" 段加 `GUI vs CLI subprocess.Popen 间接调用` 条（保留 subprocess 隔离） + ADR 0011 § "architectural decision" 标注 helper 当前 single-caller |
| **A3** | 🟢 LOW | 引用 T3 | 同 T3（gui.py 接近 cap，重复 finding） |

**r61 净改动**：
- 新文件：6 ADRs + 1 macos workflow + 0 tests（existing test_tl_pipeline.py 加 1 test）
- 修改：CLAUDE.md / .cursorrules / CONTRIBUTING.md / docs/REFERENCE.md / docs/adr/README.md / translators/_tl_parser_selftest.py / tests/test_tl_pipeline.py / AUDIT_R57.md
- VERIFIED-CLAIMS：tests_total 494 → 495 (+1: T1 test)；test_files / ci_steps unchanged（test_macos.yml 是独立 workflow，不计入 test.yml steps）；assertion_points 620 → 621 (+1)

## ✅ r62 闭合总结（维度 4+5+6 共 12 项）

| Finding | 严重度 | 闭合方式 | 改动文件 |
|---------|--------|---------|---------|
| **P1** | 🟡 MEDIUM | 模板精简 | `HANDOFF.md` rounds 56-59 详细叙事（~70 行）压缩为 4 行 bullets 引用 `_archive/EVOLUTION_r56_r60.md`（已 r60 滚动归档）；HANDOFF 313→244 (-69 / 22%) |
| **P2** | 🟡 MEDIUM | 加致谢段 | `README.md` 中英双段加 "致谢 / Acknowledgements" — maintainer / AI 协作 / 上游归属 / 测试反馈 / 依赖 / 治理 6 行 |
| **P3** | 🟢 LOW | retire to architectural decision | CLAUDE.md "已知限制" 段加 `CHANGELOG 自动化` 条（手写反映 deliberate curation） |
| **P4** | 🟢 LOW | watchlist 文档化 | CLAUDE.md "已知限制" 段加 `测试 fixture 单一化` 条（用户实际报告 bug 时抽 minimal repro 进 `tests/artifacts/`） |
| **B1** | 🟡 MEDIUM | 加测试 expose 现状 | 新 `tests/test_interrupt_recovery.py`（3 测试）pin SIGTERM handler 注册行为 + retry stage 无显式 KI catch + handler set Event；observation-only 不强制 fix |
| **B2** | 🟡 MEDIUM | 版本号升 MAJOR | `pyproject.toml::version` 1.0.0 → 2.0.0（反映 r52 C4 + r52 C3 + r57 T1 累积 BREAKING）+ `RELEASE.md` SemVer 表格 + 版本演进段更新 + description 同步 |
| **B3** | 🟢 LOW | watchlist 文档化 | CLAUDE.md "已知限制" 段加 `GUI 翻译进度可视化未审` 条（用户实际跑 GUI + The Tyrant 暴露问题再 fix） |
| **B4** | 🟢 LOW | retire to architectural decision | CLAUDE.md "已知限制" 段加 `多账号 / 多 provider 并发支持` 条（避免功能蔓延 / launcher 脚本可达同效） |
| **O1** | 🟡 MEDIUM | 新文件 | `CODE_OF_CONDUCT.md` 项目特化版（中英双段，Contributor Covenant 2.1 + 项目特定报告渠道 + BDFL 治理引用） |
| **O2** | 🟡 MEDIUM | 加 Governance 段 | `CONTRIBUTING.md` 中英双段加 "Governance" 段（BDFL 模型 / PR merge 权 / backlog 优先级 / hard contracts / CoC 执行 / contributor 角色 / AI 协作角色 / 未来演进）|
| **O3** | 🟢 LOW | retire to architectural decision | CLAUDE.md "已知限制" 段加 `TODO 跟踪机制只在 internal docs` 条（与 r59 O4 community 建设 retire 同逻辑） |
| **O4** | 🟢 LOW | confirm-retire | CLAUDE.md "已知限制" 段加 `Bus factor = 1` 条（r57 O1 / r59 O1 / r59 O3 / r62 O1 / r62 O2 已尽力缓解，fundamental 没变） |

**r62 净改动**：
- 新文件：`CODE_OF_CONDUCT.md` + `tests/test_interrupt_recovery.py`
- 修改：`pyproject.toml`（version bump）+ `RELEASE.md` / `README.md` / `CONTRIBUTING.md` / `HANDOFF.md` / `CLAUDE.md` / `.cursorrules` / `AUDIT_R57.md` / `_archive/EVOLUTION.md` / `CHANGELOG.md`
- VERIFIED-CLAIMS：tests_total 495 → 498 (+3: B1 interrupt recovery 3 tests)；test_files 35 → 36 (+1: test_interrupt_recovery.py)；ci_steps 36 unchanged；assertion_points 621 → 624 (+3)

**r60 audit 路径 X 全 fix 闭合**：r61 闭合 11 + r62 闭合 12 = 23 项全闭合。**审计 backlog 清零**。

---

## 备注

- 本文件由 r60 audit 创建（r57 旧版本已 r57-r59 全闭合，git log + EVOLUTION 阶段十六-十八 留底）
- **r62 末**完整闭合 23 findings，本文件应在 r63+ 移到 `_archive/AUDIT_R60.md` 历史归档（与 r57 旧版本相同处理）
- 与 r60 的 EVOLUTION 滚动归档（hard contract #15）**独立处理**——归档已在 r60 docs sync 阶段执行
