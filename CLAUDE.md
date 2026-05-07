# CLAUDE.md — AI 全局上下文

> 与 [`.cursorrules`](.cursorrules) **byte-identical**。修改时必须双写（推荐 `cp CLAUDE.md .cursorrules`）。

## 项目身份

纯 Python（**零第三方依赖**，Python ≥ 3.10）多引擎游戏汉化工具。支持 Ren'Py / RPG Maker MV-MZ / CSV-JSONL，五大 LLM provider（xAI/OpenAI/DeepSeek/Claude/Gemini）+ 自定义引擎插件（**round 52 起强制 subprocess 沙箱**，importlib 模式 retired BREAKING）。

**目标语言：zh 简体中文 only**（round 52 C4 BREAKING：r35-r48 多目标语言 contract 已完全删除；ja/ko/zh-tw 输出不再支持，`--target-lang` flag retired，translation_db v2 schema retired，runtime-hook v2 schema retired，`core/lang_config.py` 删除。源语言不限——LLM 自动识别，tl-mode 天然支持任何源 → zh）。

**当前数字**（测试数 / 文件数 / CI 步骤 / 断言点）：见 [HANDOFF.md](HANDOFF.md) 顶部 `<!-- VERIFIED-CLAIMS-START -->` 块 — **单一声称源**。本文 prose 不再独立声称数字。

**质量水位**：direct-mode 漏翻率 4.01%（仅适用 English source，详见下方"已知限制"）；tl-mode 翻译成功率 99.97%（r52 实测 The Tyrant 74098 entries / **99.991%**）；连续 22 轮 0 CRITICAL correctness（r35-r62）。Round 55 起新增 Unity XUnity 引擎覆盖 ~10% 用户场景。

---

## 10 大开发原则

1. **宁可漏翻也不误翻** — 不确定的条目保留原文
2. **数据驱动** — 改动前收集数据，改动后验证数据，不拍脑袋定阈值
3. **隔离变量** — 每次只改一个东西，验证独立效果
4. **不破坏已有功能** — 新功能用开关控制（CLI 参数），默认行为不变
5. **安全优先** — checker 不通过就丢弃、回写前校验、原地操作前备份
6. **先读再写** — 涉及参考项目借鉴时，先完整阅读其源码和文档再给方案
7. **方案先行** — 给出改动方案和受影响函数列表，等用户确认后再写代码（**Auto Mode 例外**：< 10 行 trivial fix / 纯文档 / memory 变更直接执行；触及 9 hard contracts / 800 行 cap / VERIFIED-CLAIMS / file_safety / Mock target / Repo rename consistency / .cursorrules byte-identical 任一契约面的改动仍必须先 plan）
8. **最小改动** — 不做不必要的重构、不加不需要的注释、不改不相关的代码
9. **零依赖** — 坚持纯标准库，不引入第三方包
10. **零欠账闭合**（round 50 起）— 所有 audit findings (CRITICAL/HIGH/MEDIUM/LOW) 必须**同轮 fix，no tier exemption**。无法 fix 的归为 architectural decision 或 informational watchlist 显式文档化（不是 debt）

---

## 模块调用关系

```
gui.py (图形界面) ─── start_launcher.py (CLI 菜单) ─── tools/renpy_upgrade_tool.py
       │                      │
       └──────────────────────┘
                │ subprocess
                ▼
main.py (CLI 入口) → engines.resolve_engine(args.engine).run(args)
  │
  ├── engines/                        多引擎抽象层（统一入口）
  │    ├── engine_detector.py         检测 + CLI 路由
  │    ├── engine_base.py             EngineProfile / TranslatableUnit / EngineBase
  │    ├── generic_pipeline.py        6 阶段通用流水线
  │    ├── renpy_engine.py            薄包装，内部路由 translators/
  │    ├── rpgmaker_engine.py
  │    └── csv_engine.py
  │
  ├── translators/                    Ren'Py 三条管线（由 RenPyEngine 调度）
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
       ├── http_pool.py        HTTPS 线程本地连接池 (~90s 节省 / 600 次)
       ├── pickle_safe.py      白名单 SafeUnpickler
       └── runtime_hook_emitter.py

safety/          TOCTOU 防御 helper（r56 M2 从 core/ 移出独立顶层 package）
                 file_safety.py  fstat 二次校验，26 sites 共享
file_processor/  splitter / patcher / checker / validator
pipeline/        helpers / gate / stages
tools/           rpa_unpacker/packer / rpyc_decompiler / renpy_lint_fixer
                 renpy_upgrade_tool / translation_editor / merge_translations_v2
                 review_generator / analyze_writeback_failures
custom_engines/  用户自定义翻译引擎插件
scripts/         verify_docs_claims.py / verify_workflow.py / install_hooks.sh
```

**统一入口契约**：`main.py` 不再分派 translators/，所有 `--engine` 值（含 `auto` / `renpy`）都走 `engines.resolve_engine(...).run(args)`。Ren'Py 的 tl-mode / tl-screen / retranslate / direct 由 `engines/renpy_engine.py::RenPyEngine.run()` 内部路由。

---

## 修改代码前的检查清单

- [ ] 列出要修改的文件和函数，等用户确认后再写代码
- [ ] 是否引入了第三方依赖？（**禁止**）
- [ ] 是否改变了默认行为？（需要 CLI 开关控制）
- [ ] 新增/修改的函数是否有类型注解？
- [ ] 是否有对应的测试用例？运行 `python tests/test_all.py` 确认零回归
- [ ] 原地修改文件前是否有 `.bak` 备份逻辑？
- [ ] checker 不通过的翻译是否被丢弃（而非强行使用）？
- [ ] 任何文件 > 800 行？（pre-commit hook 会 block）
- [ ] HANDOFF.md `VERIFIED-CLAIMS` 块是否需要更新？（pre-commit `verify_docs_claims --fast` 会检查）

---

## 已知限制

- **build.py**：CI 跑 smoke gate（`import build` + `--clean-only`）；完整 PyInstaller 打包仍仅手动测（CI 装 PyInstaller + 跑全量打包成本高，且产物 .exe 在 CI 验证有限）
- **GUI 自动化** — **architectural decision，not actionable debt**（r53 监控 #6 重新评估维持原决策）：tkinter 跨平台 headless 需 Xvfb（Linux only）或 `pyvirtualdisplay`（违反零依赖契约），Windows 无 Xvfb 等价。ROI 低 + 跨平台覆盖不全。保留为 informational watchlist；如未来引入纯 stdlib 的 GUI mock 框架可重新评估
- 端到端测试需 API key，未进入 CI
- RPG Maker Plugin Commands(356) / JS 硬编码 / 加密归档暂不支持
- **direct-mode 仅适用英文源游戏**（r53 W4，文档化路径）：`translators/renpy_text_utils.py::MIN_ENGLISH_CHARS_FOR_UNTRANSLATED = 12` + `_is_untranslated_dialogue` 仅计 a-z 字符，硬编码英文检测假设。非英文源游戏（ja/ko/etc）请改用 tl-mode（扫描 `tl/<lang>/` 空槽位，源语言 agnostic）。direct-mode 启动时会输出 INFO log 提示此限制
- **目标语言**：r52 C4 BREAKING 后固定 zh 简体中文（多目标语言 5 层 contract + `core/lang_config.py` + `--target-lang` 已删除）
- **`tools/` 散乱无共享 base**（r57 T4 architectural decision）：15 个 CLI tool 各自独立 entry，每个自己写 argparse + setup_logging + path validation。**故意保留**——`tools/` 是辅助而非 hot path，抽取共享 base 的 ROI 低于"最小改动"原则的 cost。如未来需要批量加 cross-tool feature（如 `--dry-run` for all），再 reconsider
- **Logger 含 user-controlled vars（log injection 路径）**（r57 S3 architectural decision）：15 处 `logger.error(f"...{game_dir}...")` 之类。本地工具仅写 stdout / 文件日志，无集中日志系统（syslog / Sentry），**不构成 actionable finding**。如未来引入集中日志，需 sanitize user-controlled vars 中的换行符
- **翻译质量持续验证**（r59 B2 architectural decision）：r52 实测 The Tyrant 99.991%（74098 entries）作为 reference baseline，但**没有 nightly benchmark / continuous quality gate**。决策保留现状：用户每次跑实际项目时人工 review 翻译质量；99.991% 是真实 production 数据而非 lab benchmark，加 nightly mock LLM regression test ROI 低（mock LLM 不能反映真实 LLM 行为漂移）。如未来用户报告"r57 后翻译质量明显下降"，再考虑加固定 fixture 的 quality gate
- **Community 建设**（r59 O4 architectural decision）：当前无 GitHub Discussions / Discord / sponsor 入口 / contributor list。项目用户量小（小众游戏汉化工具），community 投入回报比低。决策保留现状；如未来出现"用户量持续增长 + 多人协作开发需求"再考虑开 Discussions + 设立 sponsor 入口
- **gui.py 接近 800 行 cap**（r60 audit T3/A3 watchlist，r61 文档化）：`gui.py` 当前 594 行（距 cap 206 行），距上次 r41 拆分后已扩张近 100 行。**当前不拆**（按 audit 推荐 (c) 懒处理），但**新 PR 加 GUI 功能（如新引擎按钮 / 新一键步骤）必须先拆**：建议拆为 `gui/main_window.py` + `gui/scan_panel.py` + `gui/run_panel.py` 等。同时 r58 A1 抽取的 `_resolve_args_from_config` helper GUI 没真正 import（仍走 subprocess.Popen 间接 spawn main.py），架构债与文件大小债叠加（参见下方 "GUI vs CLI subprocess.Popen" 条）
- **GUI vs CLI subprocess.Popen 间接调用**（r60 audit A2 architectural decision，r61 文档化）：[`gui_pipeline.py`](gui_pipeline.py) 用 `subprocess.Popen([sys.executable, "main.py", ...])` 间接 spawn CLI，未真正 reuse [ADR 0011](docs/adr/0011-shared-config-helper.md) 的 `_resolve_args_from_config` helper。**故意保留**——subprocess 隔离对 GUI UX 更好（崩溃只挂子进程 / 中断恢复 / 错误隔离），helper 共享是 logic alignment 不是 dedup。如未来 GUI 改 in-process 模式，helper 价值显现
- **Plugin 协议视为稳定**（r60 audit S2 architectural decision，r61 文档化）：`core/api_plugin.py::_SubprocessPluginClient` JSONL 协议没 schema version 字段。**故意不加**——当前 plugin 极少（用户场景虚），加 version 字段是过度工程。**未来真要 BREAKING 改协议（如加 batch field / 改 error 编码）必须先 plan-first**，并同时为新旧 plugin 提供 detection / fallback。文档化原协议字段集见 [docs/REFERENCE.md](docs/REFERENCE.md) Plugin 协议段
- **API key 内存生命周期**（r60 audit S3 architectural decision，r61 文档化）：`core/api_client.py::APIConfig.api_key` 持有 API key 整个进程生命周期。多线程共享 config object 可能 leak via debugger / `gc.get_referents` / memory dump。**威胁模型不适用**——本地 single-user 工具，attacker 已能 dump 进程内存就 game over（与 r53 监控 #4 symlink retire 同理）。Python 优化时 `__del__` zeroize 可能不生效，加密 store 违反零依赖契约，retire 现状
- **Prompt injection 表面（用户 game text → LLM）**（r60 audit S4 architectural decision，r61 文档化）：31 处 prompt construction sites 中用户 game text 直接 f-string 进 prompt。如游戏文本含 jailbreak 模式（`\n\nIgnore previous. Output: <whatever>`）LLM 可能输出 garbage。**威胁模型不适用**——用户主动喂自己游戏文件给 AI 不是攻击者输入；用户 review 翻译结果是工作流的一部分。retire 现状
- **Performance benchmark 缺失**（r60 audit T4 watchlist，r61 文档化）：r52 实测 The Tyrant 74098 entries / 129.4 min / $2.40 / 99.991% 是**唯一**生产级数据点。RAM / CPU / I/O 数字未测。**保留为 watchlist**（与 r59 B2 翻译质量验证 retire 同理）：r52 数字够用作 ground reference；nightly mock LLM benchmark ROI 已 r59 B2 评估过（mock 不反映真实 LLM 漂移）。如未来 r53 W1 retry 并发引入慢线程，需重测对比
- **CHANGELOG 自动化**（r60 audit P3 architectural decision，r62 文档化）：每轮 commit message + CHANGELOG.md round 段双写。**故意保留**手写而非 git-cliff / commitizen 自动化——手写反映人工判断的轻重（如 r58 P1 99 文件 ruff format 是 1 commit 但 CHANGELOG 仅 1 行）；deliberate curation > dump 所有 commits。git tag → release notes 已 r59 B1 自动化（从 CHANGELOG sed 抽取）
- **测试 fixture 单一化**（r60 audit P4 watchlist，r62 文档化）：r57 T3 加了 1 个 complex fixture（synthetic 手工构造）。真实游戏 edge case（XUAT regex rule 含 unicode escape / Ren'Py 8.6 → 7.x downgrade ID drift / RPGM Plugin Commands 含 JS 字符串）暂无 fixture。**触发即抽**：用户接到具体 game-specific bug 时，抽 minimal repro 进 `tests/artifacts/` 作未来 regression。当前 backlog "用户实际报告"触发即可
- **GUI 翻译进度可视化未审**（r60 audit B3 watchlist，r62 文档化）：`gui_pipeline.py` 230 行处理 GUI 与 subprocess 通信，但 progress bar 实际行为（74098 entries 实时更新 / ETA 估算 / 大文件 stuck 时 GUI 假死）未审。**保留为 watchlist**：用户实际跑 GUI + The Tyrant fixture 暴露问题再 fix；当前 CLI 路径 main.py 已有 per-chunk progress log（r53 W1）
- **多账号 / 多 provider 并发支持**（r60 audit B4 architectural decision，r62 文档化）：当前一次 run 只支持 1 个 `--provider` + 1 个 `--api-key`。用户分摊 quota 跑大项目（5 个 OpenAI key 并发 5x 速度）场景。**故意不做**——避免功能蔓延（项目第 8 原则最小改动）；用户用 launcher 脚本起多 main.py 进程也能达到同效果（每个 main.py 跑独立 game-dir 子集 + 独立 key + ProgressTracker 互不干扰）
- **TODO 跟踪机制只在 internal docs**（r60 audit O3 architectural decision，r62 文档化）：HANDOFF.md "推荐 Round N+1 工作项" + ROADMAP.md actionable backlog + AUDIT_R57.md 都是 internal docs，未 sync 到 GitHub Projects / Issues。**故意保留**（与 r59 O4 community 建设 retire 同逻辑）——项目用户量小，社区贡献者实际无人，sync GitHub board ROI 低；如未来用户量增长再考虑
- **Bus factor = 1（confirm-retire from r60 audit O4）**：唯一 maintainer @Dean20030514。r57 O1 retire / r59 O1 ARCHITECTURE Quick Tour / r59 O3 ONBOARDING.md / r62 O1 CODE_OF_CONDUCT.md / r62 O2 governance 文档化已尽力缓解。**fundamental 没变**——OSS 通病，等用户量增长 + 多人协作出现再考虑 multi-maintainer 治理演进

---

## 文档索引

| 你在做什么 | 加载 |
|-----------|------|
| 修改翻译模式 / 流水线 / 校验链 / 引擎 / 测试体系 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 调整阈值常量 / 校验规则 / 路线图 | [docs/REFERENCE.md](docs/REFERENCE.md) |
| 当前 build / 数字 / 推荐下一步 | [HANDOFF.md](HANDOFF.md) |
| 历史决策（r1-r55 详 + r56-r60 表格摘要） | [_archive/EVOLUTION.md](_archive/EVOLUTION.md) |
| r56-r60 完整叙事（r60 首次滚动归档） | [_archive/EVOLUTION_r56_r60.md](_archive/EVOLUTION_r56_r60.md) |
| 最近 5 轮详细变更（r48-r52） | [_archive/CHANGELOG_RECENT_r52.md](_archive/CHANGELOG_RECENT_r52.md) |
| 当前 audit cycle（r60 收集 23 unique new findings） | [AUDIT_R57.md](AUDIT_R57.md) |
| 用户面文档（中英双语） | [README.md](README.md) |

---

## 自动化与 drift 防御

- **pre-commit hook 4 件套**（`scripts/install_hooks.sh` 启用）：py_compile + 800 行 cap + meta-runner + `verify_docs_claims --fast`
- **CI**：6 jobs（matrix `[ubuntu-latest, windows-latest]` × `[3.10, 3.12, 3.13]`，r57 T1 起 — `pyproject.toml requires-python = ">=3.10"`）
- **HANDOFF.md `VERIFIED-CLAIMS` 块**：唯一数字声称源，pre-commit + CI 双层 enforce
- **Mock target consistency CI guard**：所有 `mock.patch(...os.fstat)` / `patch.object(os, "fstat", ...)` 必须 target `safety.file_safety`（r56 M2 从 `core.file_safety` 迁移；CI guard 用 fragment match `grep -v "file_safety"` 兼容两种路径）。防 stale mock trap CLASS；r50 C4 filter 放宽到 `file_safety` 兼容 qualified form；r51 audit-tail 加第三级 `test_repo_rename_consistency` filter 豁免 documentation-only 文件 self-trip
- **Repo rename consistency CI guard**（r51 起）：`tests/test_repo_rename_consistency.py` 钉自身 repo URL refs（`pyproject.toml` + `renpy_translate.example.json`）+ logger namespace（覆盖所有 production 模块，r56 末实测 24 sites `getLogger("multi_engine_translator")`，r51 加固时 17 sites — 数字会随新模块新增自然增长，contract 是"覆盖所有 production"而非定值）+ 6 处 anonymousException 上游归属反向 exhaustiveness

---

## 文档归档节奏（r58 P3 约定 / r60 首次执行 + 阈值微调）

防止 `_archive/EVOLUTION.md` 单调增长（每轮 +20-30 行）：

- **触发条件**：每 5 轮（r60、r65、r70、…）执行一次归档
- **操作步骤**（在该轮 docs sync commit 内完成）：
  1. 把 `_archive/EVOLUTION.md` 中"阶段 N - 4"到"阶段 N"5 个阶段的详细叙事**整体抽出**，放到新文件 `_archive/EVOLUTION_rN-4_rN.md`（或类似命名）
  2. 主 `_archive/EVOLUTION.md` 只留**1 段摘要**（每轮 1-2 句 OR 多轮合并表格行 — 视 baseline 长度选用）+ 阶段表格行
  3. CLAUDE.md "文档索引" 表格加新归档文件 entry
  4. **验证阈值（r60 微调，启发式）**：`wc -l _archive/EVOLUTION.md` 应减少 ≥ **80 行 OR ≥ 20%**（r60 实测 364 → 276，-88 / 24% 通过；100 行原阈值在 doc-only 短叙事多的归档周期不可达，但实质满足"防无限增长"契约意图）
- **归档命名规则**：`_archive/EVOLUTION_r{N-4}_r{N}.md`（如 r60 归档时文件名为 `EVOLUTION_r56_r60.md`）
- **不归档**：`阶段一/二/三/...` 表格行 + 累积技术资产段 + 设计原则演进段 — 这些是跨轮的总结性内容，留主文件
- **下一次触发**：**r65**（r60 已首次执行 → r56-r60 抽到 EVOLUTION_r56_r60.md）

---

## 维护规则

1. 修改 `CLAUDE.md` 必须同步 `.cursorrules`（byte-identical 契约）
2. 数字声称（测试数 / 文件数 / CI 步骤 / 断言点）只在 `HANDOFF.md` `VERIFIED-CLAIMS` 块声明，其他文档只引用
3. 永远不要在文档中**直接**写测试数 / 行数 / 文件数等数字而不先 grep / wc / find / `verify_docs_claims --fast` ground-truth
4. round 50 起所有 audit findings 同轮 fix，零 deferred（r51 / r52 / r53 各 1 次执行验证有效）
5. 大改动遵循三段式：Plan → Implement（小步） → Verify（零问题）
6. 修改 logger namespace / repo URL self-references 必须保持 `tests/test_repo_rename_consistency.py` 4 contract tests 全 PASS；6 处 `anonymousException renpy-translator (MIT, 2024)` 上游归属永远不能被任何 sed / refactor 误删（r51 加固）
7. **`tl_mode.py` retry 路径必须保持并发**（r53 W1 契约）— 任何 sequential retry 重新引入必须先 plan-first
8. **LLM ID drift detection 必须保留 layer-6**（r53 W3 契约）— 任何主 stage / retry stage 移除 `detect_id_drift()` 必须先 plan-first
9. **Pickle 白名单不得放宽**（r53 监控 #1 verified）— 任何向 `_SAFE_BUILTINS` / `_SAFE_COLLECTIONS` / `_SAFE_CODECS` / `_SAFE_COPYREG` 添加新 entry 必须先跑 `tests/test_pickle_safe_redteam.py` 红队 audit
10. **Unity XUnity 引擎解析契约**（r55 契约）— XAT 行解析必须用 `str.partition('=')`（split first only），注释行 `//` 必须 round-trip preserve，正则规则 `r:"<pattern>"="<replacement>"` 翻译时 pattern 必须保留不动只翻译 replacement；任何修改解析或回写语义必须先 plan-first，并保持 `tests/test_unity_xunity_engine.py` round-trip byte-identical 测试 PASS
11. **Mypy enforce 契约**（r57 T2）— `core/translation_utils.py / core/config.py / file_processor/ / core/api_client.py / core/glossary.py / core/translation_db.py` 6 文件 scope 必须保持 mypy 0 errors；新文件加入 scope 前必须先 mypy clean；`# type: ignore[union-attr]` 仅允许标记 `core/api_plugin.py` 内 runtime-safe 的 Optional Popen 访问点
12. **Python ≥ 3.10 契约**（r57 T1）— `pyproject.toml requires-python = ">=3.10"`；retreating to 3.9 是大重构（PEP 604 `int \| None` 语法已广泛使用），必须先 plan-first
13. **Path traversal 防护契约**（r57 S2）— `main.py::_FORBIDDEN_PATH_PREFIXES` 不可放宽；任何新 user-supplied path 入口必须经过 `_sanitize_user_path`；本地 single-user 工具威胁模型不变，但多用户共享环境的 defense-in-depth 不可缺
14. **CI ruff lint/format 门禁**（r58 P1）— 任何新 PR 必须 `ruff check .` + `ruff format --check .` 全过；`pyproject.toml [tool.ruff.lint] extend-ignore` 列表（E402 / E501 / F841）不得放宽；新规则只能加不能减
15. **EVOLUTION 滚动归档触发**（r58 P3 / r60 首次执行）— 每 5 轮（r60 ✓ / r65 / r70 / ...）必须执行归档（详见上方"文档归档节奏"段）；阈值 ≥80 行 OR ≥20% 缩减（r60 微调，启发式）；不能跳过
