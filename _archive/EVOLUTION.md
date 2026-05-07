# 项目演进史 (Round 1 — Round 51)

> 本文件吸收原 `CLAUDE.md` 的"r31-r50 演进段"与原 `CHANGELOG_RECENT.md`（现归档为 [`_archive/CHANGELOG_RECENT_r51.md`](CHANGELOG_RECENT_r51.md)）的演进摘要，按 round 编号组织，**不含 commit hash**（如需精确改动请查 `git log`）。
>
> - **最近 5 轮详情**：见 [`_archive/CHANGELOG_RECENT_r51.md`](CHANGELOG_RECENT_r51.md)（归档于 round 51 末，保 r47-r51）
> - **r1-r45 总览表**：见 [`_archive/CHANGELOG_FULL.md`](CHANGELOG_FULL.md)
> - **r12-r19 引擎扩展方案历史快照**：见 [`_archive/EXPANSION_PLAN_FULL.md`](EXPANSION_PLAN_FULL.md)
> - **当前状态**：见根目录 [`HANDOFF.md`](../HANDOFF.md) 顶部 `VERIFIED-CLAIMS` 块

---

## 阶段零（r1-r10）— 翻译质量基线

| 轮 | 主题 |
|----|------|
| 1 | 质量校验体系 — W430/W440/W441/W442/W251 告警 + E411/E420 术语锁定 |
| 2 | 功能增强 — 结构化报告 + translation_db + 字体补丁 |
| 3 | 降低漏翻率 — 12.12% → 4.01%（占位符保护 + 密度自适应 + retranslate） |
| 4 | tl-mode — 独立 tl_parser + 并发翻译 + 精确回填 |
| 5 | tl-mode 全量验证 — 引号剥离修复 + 99.97% 翻译成功率 |
| 6 | 代码优化 — chunk 重试 + logging + 模块拆分 + 术语提取 |
| 7 | 全量验证 — 99.99% 成功率（未翻译 25→7，Checker 丢弃 4→2） |
| 8 | 代码质量 — 消除重复 + 大函数拆分 + validator 结构化 |
| 9 | 深度优化 — 线程安全 + O(1) fallback + API 错误处理 |
| 10 | 功能加固 — 控制标签确认 + CI 零依赖 + 跨平台路径 |

## 阶段一（r11-r17）— 架构成型

| 轮 | 主题 |
|----|------|
| 11 | `main.py` 拆分 2400→233 行 + Config 类 + Review HTML + 类型注解 + 多语言 |
| 12 | 引擎抽象层 — `EngineProfile` + `EngineBase` + RPG Maker MV/MZ + CSV/JSONL + GUI |
| 13 | 四项优化 — pipeline review.html + 可配置字体 + tl/none 模板 + CoT |
| 14 | Ren'Py 专项五阶段升级（基础重构 + 健壮性 + 性能 + 质量 + 体验） |
| 15 | nvl clear ID 修正 — 8.6+ say-only → 7.x nvl+say 哈希自动修正 |
| 16 | screen 文本翻译 — `screen_translator.py` + 缓存清理 .rpymc 补全 |
| 17 | 项目结构重构 — 根目录 25→5 .py + `core/translators/tools` 分层 |

## 阶段二（r18-r19）— 工具链补全

| 轮 | 主题 |
|----|------|
| 18 | 预处理工具链 — RPA 解包 + rpyc 双层反编译 + lint 自动修复 + locked_terms 预替换 + tl 跨文件去重 + Hook 模板 |
| 19 | 翻译后工具链 + 插件系统 — `tools/rpa_packer` + `tools/translation_editor` HTML 校对 + `custom_engines/` 插件接口 + 默认语言自动生成 |

> **r12-r19 整体扩展方案的设计动机**（为什么 EngineProfile 用数据类而非继承多态、为什么 RPGMakerMVEngine 不实现 plugin commands 等）见 [`EXPANSION_PLAN_FULL.md`](EXPANSION_PLAN_FULL.md)。

## 阶段三（r20-r30）— 安全与稳健化

| 轮 | 主题 |
|----|------|
| 20 | CRITICAL 修复 — pipeline 悬空 import × 3 + pickle RCE × 3 + ZIP Slip 防护 + CONTRIBUTING/SECURITY 治理文档 |
| 21 | Top 5 HIGH 收敛 — HTTP 连接池（节省 ~90s/600 次握手）+ ProgressTracker 双锁解串行 + API Key 走 subprocess env（关闭进程列表泄露） |
| 22 | 测试基础 + 响应体上限 — `MAX_API_RESPONSE_BYTES = 32 MB` + `read_bounded` 共享工具 |
| 23 | A-H-4 Part 1 — `translators/direct.py` 1301 → 584 + 拆 `_direct_chunk/_direct_file/_direct_cli` |
| 24 | A-H-4 Part 2 — `translators/tl_mode.py` 928 → 558 + `tl_parser.py` 1106 → 532 |
| 25 | 七项 HIGH/MEDIUM 收敛 — A-H-1 + A-H-6 + S-H-3 + PF-H-2 + PF-C-2 + 测试加固 |
| 26 | 综合包 A+B+C — TranslationDB 三件套（RLock + 原子写 + line=0）+ RPA 大小预检查 + RPYC 白名单同步 |
| 27 | 分层收尾 — A-H-2（3 wrapper 下沉 `file_processor/checker.py`）+ A-H-5（`tools/font_patch.py` → `core/font_patch.py`） |
| 28 | A-H-3 Minimal 路由统一 + S-H-4 Dual-mode 插件沙箱（`--sandbox-plugin` opt-in） |
| 29 | `tests/test_all.py` 2539 行拆为 5 聚焦 suite + 49 行 meta-runner |
| 30 | 冷启动审计 4 项 robustness — `_SubprocessPluginClient` stderr 10 KB 上限 + Popen atexit 兜底 |

## 阶段四（r31-r35）— 多语言与运行时注入

| 轮 | 主题 |
|----|------|
| 31 | inject_hook.rpy 模板 + `--emit-runtime-hook` opt-in CLI |
| 32 | UI 白名单可配置化（sidecar JSON）+ 字体自动打包 + `translations.json` v2 多语言 schema |
| 33 | `tools/merge_translations_v2.py` + `--font-config` 透传 runtime hook + `tools/translation_editor.py` v2 适配 |
| 34 | TranslationDB schema v2 + `language` 字段 + 4-tuple 索引 + editor HTML dropdown 多语言切换 |
| 35 | `--target-lang zh,ja,zh-tw` 逗号分隔 + main.py 外层语言循环 + editor side-by-side 多列 |

## 阶段五（r36-r42）— 防御加固与契约化

| 轮 | 主题 |
|----|------|
| 36 | 深度审计驱动 2 个 edge-case bug 修 — H1 跨语言 bare-key 污染 + H2 `_sanitise_overrides` 加 `math.isfinite` 过滤 |
| 37 | M 级防御加固包 M1-M5 — partial v2 backfill + 4 处 JSON loader 50 MB cap + multi-lang try/finally restore + CWD path 白名单 + empty-cell SKIP 语义 |
| 38 | "收尾包" — 拆 `test_translation_editor.py` 847→376 + M2 扩 4 处 + `config_overrides` 扩 bool + editor mobile 自适应 |
| 39 | "收尾包 Part 2" — tl-mode/retranslate per-language prompt（zh 中文模板 byte-identical / 非 zh generic 英文）+ M2 phase-2 × 3 |
| 40 | pre-existing 大文件拆 3/4 — `test_engines.py` / `rpyc_decompiler.py` / `api_client.py` 全部 < 800 行（`gui.py` 挂 r41） |
| 41 | gui.py 拆 4/4 mixin — `gui.py` 815→489 + `gui_handlers/_pipeline/_dialogs` 三个 mixin（MRO 架构）；**源码全 < 800 首次达成** |
| 42 | 内部 JSON loader cap 收尾 + checker per-language 化（`lang_config` kwarg + deferred import 保 layering） |

## 阶段六（r43-r45）— 累计审计期

| 轮 | 主题 |
|----|------|
| 43 | r36-r42 累计三维度专项审计（correctness / coverage / security）— 0 CRITICAL/0 HIGH，3 MEDIUM defensive + plugin stdout 50 MB cap |
| 44 | 10 项综合清算 — 3 漏网 JSON loader cap 补齐 + plugin cap rename `_BYTES`→`_CHARS`（澄清 char-vs-byte 语义）+ CI 扩 Windows matrix + PyInstaller build 33.9 MB exe smoke 通过 |
| 45 | 11 项维护清算 + r41-r45 累计 audit-tail（**首次发现 CI 覆盖 regression** — Commit 1 拆 test_ui_whitelist 但 CI verify script 未同步，**ghost tests** in CI；同轮 fix） |

## 阶段七（r46-r48）— Auto Mode 综合执行

| 轮 | 主题 |
|----|------|
| 46 | 7 step Auto-mode 执行 — install_hooks 启用 + test_runtime_hook 拆 v2_schema + r45 audit 4 MEDIUM gap 闭合 + r46 三维度审计 + **真实桌面 GUI smoke via computer-use**（5 轮积压 UX 缺口闭合） |
| 47 | 5 step 综合执行 — r43 detail archive + 7 LOW gap 全补 + **TOCTOU 升级 ACCEPTABLE doc → MITIGATED code**（csv_engine `os.fstat(f.fileno())` 二次校验） + test_translation_state 拆 progress_tracker_language |
| 48 | 4 step 深度优化 — TOCTOU helper 抽取到 `core/file_safety.py::check_fstat_size` + 扩展到 csv/jsonl/json 三 readers 全 MITIGATED + **首次 security CRITICAL 同轮 fix**（r47 mock target 在 helper 抽取后失效，spuriously pass） |

### r48 audit-tail（用户反馈触发）

用户在 r48 末发现 `tests/test_engines.py` 1090 + `tests/test_custom_engine.py` 1020 **远超 800 软限**，而 r45-r48 多次 HANDOFF/CHANGELOG 错误声称"all tests < 800 maintained"。同轮 fix 拆分两文件，**所有 .py 现真正 < 800**；连续 audit-2/3/4/5 修 5 项数字 drift；本次 incident 直接催生 r49 的 4 项自动化 prevention。

## 阶段八（r49）— Drift Prevention 自动化

7 commits（C1-C7）综合执行：

- **C1+C2 prelude — 4 项 prevention 工具落地**：
  - `.git-hooks/pre-commit` 加 file-size guard（>800 行 .py 直接 block）
  - 新建 `scripts/verify_docs_claims.py`（`--fast` 在 pre-commit ~1s + `--full` 在 CI 实跑）
  - `HANDOFF.md` 顶部 fenced `<!-- VERIFIED-CLAIMS-START -->` **单一声称源**契约
  - 顺手修了 r17 起 31 轮无人发现的 pre-existing tl_parser self-test CI bug（audit 工具用上才出土，**反向证明工具价值**）
- **C3** — 关 r48 推迟的 2 LOW（NFC/NFD design choice docstring + regression test）
- **C4-C5** — `file_safety.check_fstat_size` helper 推广到 **26 sites / 12 modules**：
  - 整个 user-facing JSON ingestion surface 全 TOCTOU MITIGATED
  - attack window 从 path-based stat→open 全部缩到 fd-based fstat 微秒级
  - 演进：r46 audit 4 ACCEPTABLE → r47 csv only MITIGATED → r48 csv 3 readers MITIGATED → **r49 全 26 sites MITIGATED**
- **C6** — r49 三维度审计：连续 9 轮 0 CRITICAL ✓ / 2 HIGH 同轮 fix
- **C7** — docs sync + audit-tail：跑 `verify_docs_claims --full` 时发现 C2 引入的 self-recursion bug（`--full` 实跑 CI test steps 包含自己 → 死循环 → WinError 32），同轮 fix `execute_all_ci_test_steps` 加 self-skip guard

## 阶段九（r50）— Zero-Debt Closure 模式确立

3 commits + 1 deep-audit-tail：

- **本轮起新规则**（用户指令 + written + enforced）：所有 audit findings (CRITICAL/HIGH/MEDIUM/LOW) 必须**同轮 fix，no tier exemption**。修正 r41-r49 默认 defer LOW/MEDIUM 的不成文做法。无法 fix 的归 **architectural decision** 显式文档化（不算 debt）。
- **C1** — 关 r49 6 项 audit-deferred + **同轮 fix 2 latent r49 C4 fixture bugs**：
  - `test_glossary_actors/system_json_rejects_toctou_growth_attack` 调错 method（`scan_game_directory` 而非 `scan_rpgmaker_database`），function early-return 致 mock 从未触发，rejection 巧合成立 → false-positive pass
  - r49 audit agent 看 test 函数存在就判 covered，未深查测试逻辑是否真触发 mock
  - 教训：**audit agent 提示词应明确要求"verify test really exercises mock target, not just function exists"**
- **C2** — r50 三维度审计 7 findings + 4 architectural decisions 全部同轮 fix（**新规则首次执行**）
- **C3** — docs sync + 5 轮滚动删 r45 detail
- **C4 deep-audit-tail**（用户"深度检查"触发）— 同轮 fix 1 个 r50 C2 自身引入的 Security MEDIUM（CI grep filter `core\.file_safety` 改为 `file_safety` 防 qualified mock false-positive）

**连续 10 轮 0 CRITICAL correctness 保持**（r35-r50）。

## 阶段十（r51）— Repo Rename Sync + 11th 0-CRITICAL Streak

5 commits（A2 + A3 + A4 + A5/A6 + B3）：

- **本轮触发**：用户在 r50 末已将 GitHub 远端从 `Renpy-Translator` 重命名为 `Multi-Engine-Game-Translator`，本地目录从 `Renpy汉化（我的）` 改名为 `Multi-Engine Game Translator`。Round 51 把项目内 self-references + project-wide logger namespace + docs 全部同步到位。
- **Track A 仓库重命名 sync** — 本地 `git remote set-url`；`pyproject.toml` 包名 `multi-engine-game-translator` + Repository URL；`renpy_translate.example.json $schema`；README "文档" / "Documentation" table 各加 1 行历史注解；Logger namespace 17 sites `getLogger("renpy_translator")` → `"multi_engine_translator"`（16 模块级 + 1 测试函数内；6 处 anonymousException 上游归属完整保留）；新 `tests/test_repo_rename_consistency.py` 4 contract tests + CI workflow `Run repo rename consistency tests` 步（37 → 38）
- **Track B r51 起始三维度审计**（zero-debt closure 模式第二次执行）— Correctness 0 / Coverage 5（1 HIGH / 2 MEDIUM / 2 LOW）/ Security 0；4 Coverage findings 同轮 fix（SKIP_PARTS 显式 test + UPSTREAM_ATTRIBUTION inverse exhaustiveness + self-skip invariant + CI mock-target guard regex shape pin）；Coverage HIGH-1 logger 行为测试归 **architectural decision**（`logging.getLogger(NAME)` 是 stdlib 纯标识符派发，静态 orphan grep 是充分契约，behavioural test 要么 tautological 要么测 Python stdlib）
- **Track C docs sync** — `git mv CHANGELOG_RECENT_r50.md → r51.md` + 内容 rewrite（5 轮滚动删 r46 detail）；本文件加 r51 段；HANDOFF 重写为 r52 起点；CLAUDE.md ↔ `.cursorrules` byte-identical 同步

**连续 11 轮 0 CRITICAL correctness 保持**（r35-r51）。

## 阶段十一（r52）— Scope Reduction BREAKING + 12th 0-CRITICAL Streak

6 commits（C1 + C2 + C3 BREAKING + C4 BREAKING + 2 prelude），净 -3781 行（删 8 文件 + 加 1 migration script）：

- **本轮触发**：用户用 START.bat 跑非中文 e2e（ja 流程）暴露 r35-r48 多语言 contract 真实大规模痛点 — `tl_mode.py:484-532` retry 单线程 + 零 progress logging（27000+ 残留 → 8-45h "卡死"）/ LLM 偶发 JSON mis-escape / stage 3 fallback miss-rate 36% / 网络中断后 stage 3-5 全部没跑。User 决定 **scope reduction**：retire dual-mode plugin + multi-target language。
- **C1 push-status drift checker**（`scripts/verify_docs_claims.py` +3 函数 + `tests/test_verify_docs_claims_push_status.py` 7 unit tests + CI step）— catches r51 trap "L29 5 commits 待 push" but already pushed
- **C2 build.py CI smoke**（`Run build.py smoke (import + --clean-only)` step）+ **GUI architectural decision**（reclassified 为 informational watchlist；tkinter 跨平台 headless 需 Xvfb / 违反零依赖 / ROI 低）
- **C3 BREAKING — retire importlib plugin mode**（`core/api_plugin.py::_load_custom_engine` 65 行 + APIConfig.sandbox_plugin field + `--sandbox-plugin` flag + 6 caller sites kwarg 全删；新加 `_SubprocessPluginClient.__init__` startup readiness probe 5×20ms poll catch missing `--plugin-serve` block）
- **C4 BREAKING — drop non-zh target language**（**最大单 commit**：37 文件 / +342 -4123）：删 `core/lang_config.py` + `tools/merge_translations_v2.py` + 6 测试文件；retire `--target-lang` flag + multi-language outer loop + 5 层 contract（prompt per-lang / alias-read / checker per-lang / zh-tw 隔离 / generic fallback）+ DB v2 schema + runtime-hook v2 schema + ProgressTracker language namespace；hardcode `args.target_lang = "zh"`；加 `scripts/migrate_db_v2_to_v1.py` 迁移工具
- **zh sanity validation（A3）**：用户跑 The Tyrant 项目 74098 entries → 99.991% 成功 / 0.0013% drop / 0.27% retry residual / 129.4 min / $2.40。**对比 ja 路径**：W1 retry 单线程在 zh 上 7 min 无感 vs ja 8-45h；W2 JSON mis-escape 在 zh 上 0 触发 vs ja 多次；W3 stage 3 fallback miss 在 zh 上 0.27% vs ja 36%。reduction scope 后**严重模式永远不再触发**到生产痛点。
- **W1-W4 actionable 升级**：r52 末用户决定升级 4 informational watchlist 到 r53 actionable backlog（即使 zh 路径不痛也作为长期稳健性 r53 工作落地）

**连续 12 轮 0 CRITICAL correctness 保持**（r35-r52）。

## 阶段十二（r53）— W1-W4 闭合 + 6 监控项重新评估 + 13th 0-CRITICAL Streak

11 phases（W1 + W2 + W3 + W4 + 6 monitor items + docs sync），新增 1 模块 + 2 测试文件 + 36 单元测试：

- **本轮触发**：r52 末用户决策把 W1-W4 informational watchlist 升级到 r53 actionable backlog；同时要求重新评估 6 个监控项（不再被动留作 watchlist）。
- **W1 — retry 阶段并发化 + per-chunk progress logging**（`translators/_tl_retry.py` 新模块 174 行 + `tl_mode.py:463-516` 替换为 `run_retry_stage()` 调用）：ThreadPoolExecutor (max_workers = `args.workers`) + per-chunk `[TL-RETRY n/N]` log + 自适应 chunk size（≤50 entries → 5/chunk; >50 → 10/chunk）+ cross-file 任务列表（一个慢文件不阻塞其他文件）。17 单元测试覆盖 (drift detection 边界 / chunk size adaptation / progress log 输出 / per-thread r_kept lock 安全)。
- **W2 — JSON mis-escape layer-7 char-walker repair**（`core/api_client.py::_extract_json_array` + `_repair_unescaped_quotes_in_strings`）：在 6 级结构降级链之后加 layer 7，char-by-char 跟踪 string scope，遇到 stray `"`（next non-whitespace 不是 `,]}:`）自动 escape 为 `\"`，然后 retry layer 1 + layer 3。pathological 输入仍可能 fail，但典型 LLM mis-escape pattern (嵌套引号 / 中文标点边界) 全恢复。5 单元测试 (4 mis-escape pattern + 1 helper boundary)。
- **W3 — LLM ID drift detection (layer 6)**：`detect_id_drift(expected_ids, returned_ids, threshold=0.10)` 计算 symmetric-difference / |expected| 比例，> 阈值时 warn (drift_count = missing + extra)。主 stage `_translate_one_tl_chunk` 加 returned_ids 收集 + drift warning 注入 warnings list；retry stage 在 per-chunk callback 直接 log `[W3-DRIFT n%]`。修正 HANDOFF stale "4 层 fallback" 表述（r31 起就是 5 层 precise → strip → token → escape → tagstripped；W3 在其上加 layer 6 ID drift detection 是 observation-only，从不 abort chunk）。
- **W4 — direct-mode English-only 文档化**（路径 b 最小改动）：`translators/direct.py::run_pipeline` 启动加 INFO log 提示限制；`translators/renpy_text_utils.py::MIN_ENGLISH_CHARS_FOR_UNTRANSLATED` 常量加 docstring；CLAUDE.md "已知限制" + README + docs/REFERENCE 全部交叉引用。**不加 `--source-lang` CLI flag** — 避免功能蔓延（项目第 8 原则最小改动）。
- **监控 #1 Pickle 红队 audit verified safe**（`tests/test_pickle_safe_redteam.py` 8 测试）：构造 4 个直接调用 gadget (os.system / subprocess.Popen / eval / exec) + 1 个 `_codecs.encode` chain attack 尝试 + 1 个 `copyreg._reconstructor` GadgetChain (with `os.system` as base) + 2 个 boundary control (legitimate payload / arbitrary class deny)。结果：直接 gadget 全部 raise UnpicklingError；`_codecs.encode` 仅返回 inert bytes/str（passive transformation，无可执行 callable）；`_reconstructor` 在 base callable resolve 阶段被 SafeUnpickler 拒绝，链断。**升级**：监控 #1 从 informational watchlist → architectural decision (verified safe)。
- **监控 #2 HTTP 64KB 精度偏差降至 1B**（`core/http_pool.py::read_bounded`）：`chunk = readable.read(min(_READ_CHUNK_SIZE, limit - total + 1))`，+1 byte 用作 overshoot detector，触发 raise 时 `total = limit + 1` 最大偏差 1 byte。fast path（数据 << limit）保持 64 KB chunk size。3 单元测试覆盖 (precision at cap / exact limit / limit + 1 byte raises)。
- **监控 #3 TOCTOU fstat race retire to architectural decision**：microsecond-level OS-atomic 边界已是当前实现下限；进一步缩小依赖 OS-level FD-ops 实现细节（fstat 内部 syscall 时序），无 actionable improvement path。
- **监控 #4 symlink path-swap mitigation**（`main.py::_maybe_warn_on_symlink` + `--allow-symlink` flag）：`--game-dir` / `--config` 是 symlink 时输出 warning（非阻断），`--allow-symlink` 抑制（NAS / 挂载场景）。本地 single-user 工具无 realistic exploit vector，warning 仅作审计提示。3 单元测试 (warn unflagged / allow suppresses / regular path no-warn)。
- **监控 #5 Logger namespace retire to architectural decision**：r51 4 contract tests pin 覆盖所有 production 模块（r51 时 17 sites）已充分；contract 是"覆盖"而非定值数字（r56 末实测 24 sites）；如未来引入 logging filter / sink / metric pipeline，需 reconsider。
- **监控 #6 GUI 自动化 maintained as architectural decision**：r53 重新评估维持原决策（tkinter 跨平台 headless 需违反零依赖契约 + ROI 低 + 跨平台覆盖不全）。
- **数字增量**：tests_total 431 → 467 (+36); test_files 30 → 32 (+2: `test_tl_retry.py` + `test_pickle_safe_redteam.py`); ci_steps 34 unchanged; assertion_points 557 → 593 (+36, 跟随 tests_total)。
- **9 hard contracts 累积到 12**（CLAUDE.md 维护规则 +3）：`tl_mode.py` retry 必须并发 / LLM ID drift detection layer-6 必须保留 / Pickle 白名单不得放宽（修改前必跑红队 audit）。

**连续 13 轮 0 CRITICAL correctness 保持**（r35-r53）。

## 阶段十三（r54）— Backlog 重新评估 + 14th 0-CRITICAL Streak

单 docs sync commit，零代码变更：

- **本轮触发**：r53 末用户重读 HANDOFF backlog 后质疑 #1 (A-H-3 Medium) + #2 (A-H-3 Deep) 的真实价值。澄清后用户要求重新评估**所有**待办项。
- **评估标准**：用 r52 起"减法 + 聚焦"原则（CLAUDE.md 第 8 原则最小改动 + 第 10 原则零欠账闭合），按 真实用户价值 / 实施成本 / 架构契约阻塞 / 法律与维护风险 综合判断 ROI。
- **结论**：r53 末 12 项 actionable backlog 中 8 项是负 ROI 或已被现有方案间接覆盖，**应 retire 到 architectural decision**。剩余 actionable 缩减到 3 项（Unity XUnity / Godot / Kirikiri+TyranoBuilder），按 ROI 排序。
- **r54 retire 8 项**（详见 [HANDOFF.md "Round 54 retire"](../HANDOFF.md) + [docs/REFERENCE.md §13.2 / §13.4](../docs/REFERENCE.md)）：
  - **A-H-3 Medium**（让 Ren'Py 走 generic_pipeline）—— r52 C4 后 Ren'Py 是 zh-only 单一目标，"统一抽象"用户场景消失；generic_pipeline 反而是从 tl-mode 派生的，反向接入是绕路；99.991% 翻译成功率 + 14 轮 0 CRITICAL streak 全在专有管线下达成
  - **A-H-3 Deep**（退役 DialogueEntry）—— 3 个 Ren'Py 特有字段搬到 metadata 字典只是换位置，没真正统一；attribute access → dict lookup 是降级；75+ 引用 / 11 文件 / 删除无回滚
  - **RPG Maker Plugin Commands (356)**—— 真实覆盖 ~25% × ~10% = ~2.5% 用户场景；按需启动模式（用户报告具体游戏样本时再开新轮）比 standing backlog 合理
  - **加密 RPA / RGSS 归档**—— 涉及反编译加密算法（破解 DRM），法律灰色地带；用户群体小；非加密版本已支持
  - **RPG Maker VX/Ace**（P1）—— 需 `rubymarshal` 第三方依赖，违反零依赖核心契约（CLAUDE.md 第 9 原则）
  - **Wolf RPG Editor**（P1）—— 走 WolfTrans 导出 CSV → 已通过 CSVEngine 间接支持，重复造轮子
  - **Unreal Engine**（P3）—— uasset 工具链极复杂，主流 Unreal 走专用 LocText 工具，不是项目定位
  - **HTML5 / 浏览器**（P3）—— HTML5 游戏极少做汉化（往往 web app i18n 已有现成方案），用户场景虚
- **Actionable backlog 12 → 3**（剩 Unity XUnity / Godot / Kirikiri+TyranoBuilder）。
- **新增 backlog 评估纪律**（写入 HANDOFF Round 55 关键约束）：r54 retired 8 项不应被无证据重新打开，重新打开必须先有具体用户场景证据 + plan-first 论证 ROI 翻转。
- **数字 unchanged**：tests_total / test_files / ci_steps / assertion_points 保持 r53 末数值（467 / 32 / 34 / 593）；r54 是纯文档轮，未引入新测试 / 新 CI step / 新源代码。

**连续 14 轮 0 CRITICAL correctness 保持**（r35-r54）。

## 阶段十四（r55）— Unity XUnity AutoTranslator 引擎接入 + 15th 0-CRITICAL Streak

5 phases（engine module + 注册 + CLI + tests + docs sync），新增 1 引擎模块 + 1 测试文件 + 16 单元测试：

- **本轮触发**：r54 末重新评估后 actionable backlog 仅剩 3 项（Unity XUnity / Godot / Kirikiri+TyranoBuilder），用户选择"路径 A"推进 Unity XUnity（最高 ROI：10% 用户面 / 实现简单 / 不动核心 hot path）。
- **设计原则**：不解析 Unity AssetBundle 或 .dll 资源（项目定位之外），只支持 XUAT 自身导出的纯文本翻译文件，这覆盖了 Unity 汉化工作流的大多数场景。
- **XUAT 文件格式**：每行一种类型 — 空行 / `//` 注释 / `original=translation` / `r:"<pattern>"="<replacement>"`（正则规则）/ malformed。等号解析必须用 `str.partition('=')`（split first only）以正确处理 original 含 `=` 的情形。
- **正则规则**（用户 Q3 选支持）：pattern 是 Unity 运行时 regex 不可翻译，replacement 是用户期望的目标语言文本，仅 replacement 提交 LLM；write_back 重组 `r:"<pattern>"="<translated>"`。pattern 保留不动是 hard contract #13。
- **Round-trip byte-identity**：write_back 重读源文件 line-by-line，仅替换有 translation 的行；空行 / 注释 / 行序 / line ending（LF vs CRLF 按源文件）/ BOM 全保留；输出到 `output_dir/<relative_path>`。
- **OOM cap**：50 MB 文件大小上限 + TOCTOU `check_fstat_size` 防御（与其他用户面 loaders 一致）。
- **CLI**（用户 Q4 选两者都接受）：`--engine unity` 与 `--engine unity_xunity` 都路由到 `UnityXUnityEngine`。`detect()` 返回 False（用户 Q2 选 manual-only，因为 XUAT 文件常被复制到任意位置手动管理，自动检测会过度触发）。
- **测试覆盖**（16 测试）：detect manual-only / engine profile / 普通行解析 / 已翻译行不重发 / 注释和空行跳过 / `=` in original / UTF-8 BOM / malformed 跳过 / regex rule pending+filled / write_back round-trip / BOM preserve / regex pattern preserve / CRLF preserve / OOM cap / `_parse_lines` 全类型分类。
- **数字增量**：tests_total 467 → 483 (+16); test_files 32 → 33 (+1: `test_unity_xunity_engine.py`); ci_steps 34 unchanged; assertion_points 593 → 609 (+16)。
- **12 hard contracts 累积到 13**（CLAUDE.md 维护规则 +1）：Unity XUnity 引擎解析契约（partition 而非 split / `//` 注释 round-trip / 正则 pattern 不动只翻译 replacement）。
- **Actionable backlog 3 → 2**（Godot + Kirikiri/TyranoBuilder）。

**连续 15 轮 0 CRITICAL correctness 保持**（r35-r55）。

## 阶段十五-十九（r56-r60）— 6 维度审计周期 + 16th-20th 0-CRITICAL Streak

> **r60 滚动归档触发**（hard contract #15 首次执行）：5 阶段完整叙事抽到 [`_archive/EVOLUTION_r56_r60.md`](EVOLUTION_r56_r60.md)，本段仅留摘要表格。

| 轮 | 主题 |
|----|------|
| 56 | 8 维度审计 11 findings 路径 C 全 fix；`safety/file_safety.py` 顶层 package（M2，18 imports）；4 模块 print → logger 29 处；unity_xunity regex backref placeholder 保护 |
| 57 | 6 维度深度审计写入 [`AUDIT_R57.md`](../AUDIT_R57.md)（23 findings）；维度 1+2（T1-T4 + S1-S4）闭合：Python 3.10 floor BREAKING + mypy informational → enforce（6 文件 32 errors fix）+ `_sanitize_user_path` path traversal + .rpy escape fuzz；+3 hard contracts (#11-#13) |
| 58 | 维度 3+4（A1-A3 + P1-P4）闭合：shared `_resolve_args_from_config` helper + RenPyEngine 不走 generic_pipeline 文档化 + CI 加 ruff lint+format + mypy scope 扩到 engines/+safety/（132 errors auto-fix）+ 5 ADR + RELEASE/ROADMAP；+2 hard contracts (#14 ruff / #15 EVOLUTION 滚动归档) |
| 59 | 维度 5+6（B1-B4 + O1-O4）闭合 + AUDIT_R57.md 收尾：release 自动化（3 OS matrix → SHA256SUMS → draft Release）+ 中英双段免责声明 + `docs/ARCHITECTURE.md §0 Quick Tour` + `docs/ONBOARDING.md` 新建；纯文档+流程+微调轮 |
| 60 | EVOLUTION 滚动归档首次执行（hard contract #15）；重做 6 维度审计收集 23 unique new findings（1 HIGH A1 ADR 缺漏 + 11 MEDIUM + 11 LOW）重写 [`AUDIT_R57.md`](../AUDIT_R57.md)；fix 由 r61+ 执行 |

## 阶段二十-二二（r61-r63）— r60 audit 路径 X 全闭合 + r63 第三次审计 + 21st-23rd 0-CRITICAL Streak

| 轮 | 主题 |
|----|------|
| 61 | r60 audit 路径 X 第一波闭合 11 项（维度 1+2+3）：(A1 HIGH) 补 6 份 ADR 0006-0011 文档化 r57-r58 全部架构决策（py 3.10 floor / mypy enforce / path traversal / ruff CI / EVOLUTION rolling archive / shared config helper）+ ADR 索引 5→11；(T1) `_tl_parser_selftest.py` tempfile 泄漏 fix + 1 unit test；(T2) CONTRIBUTING.md 加"新代码 100% type hint"PR 规则；(T3+A3) gui.py 594 行 cap watchlist + "新 PR 加 GUI 功能必须先拆"约束；(T4) benchmark watchlist；(S1) `.github/workflows/test_macos.yml` nightly schedule 新建（cron + workflow_dispatch，3.10/3.12/3.13 matrix）；(S2) Plugin JSONL 协议视为稳定（`docs/REFERENCE.md §7b` 字段集 + 不加 version 决策）；(S3+S4+A2) 3 项 retire to architectural decision（API key 内存 / prompt injection / GUI subprocess.Popen 隔离）。+1 测试；hard contracts 仍 15 |
| 62 | r60 audit 路径 X 第二波闭合 12 项（维度 4+5+6）+ AUDIT_R57.md 收尾清零：(P1) HANDOFF.md 模板精简 r56-r59 详细叙事 → 4 行 bullets 引用 EVOLUTION_r56_r60.md（313→244 行 / -69 / 22%）；(P2) README 中英双段加"致谢 / Acknowledgements"段；(P3+P4+B3+B4+O3+O4) 6 项 retire/watchlist 文档化；(B1) `tests/test_interrupt_recovery.py` 新建 3 observation tests pin SIGTERM/KI 现状；(B2) `pyproject.toml::version` 1.0.0 → 2.0.0 反映累积 BREAKING (r52 C3+C4 / r57 T1) + RELEASE.md 同步；(O1) `CODE_OF_CONDUCT.md` 新建（项目特化 Contributor Covenant 2.1，中英双段）；(O2) CONTRIBUTING.md 加"Governance"段。**r60 audit 23 findings 全闭合（r61 11 + r62 12）**；hard contracts 仍 15 |
| 63 | **第三次 6 维度深度债务审计**（r57 cycle 23 + r60 cycle 23 已闭合 = 46 项；r63 不重复）：扫 r62 末 baseline 后更深层潜在债务，**收集 23 unique new findings 重写 [`AUDIT_R57.md`](../AUDIT_R57.md)**（**2 HIGH + 9 MEDIUM + 12 LOW**）。2 HIGH 是 imminent failure：(T1) 3 testfile 距 800 cap 仅 2-10 行（test_file_safety 798 / test_api_client 792 / test_verify_docs_claims 790）；(S1) **pre-commit hook 仅运行 191/485 测试 ≈ 39% 覆盖**（24/35 测试文件不在 meta-runner，含 r61 T1 + r62 B1 测试本身）。其他重要 finding：S2 (`AUDIT_R57.md` 命名 drift) / S3 (START.bat 错误说 Python 3.9+) / S4 (无 `--version` flag) / P1 (ROADMAP "截止 r57 末" stale) / P2 (ONBOARDING 说 "5 份 ADR" 但 11 份) / B2 (.exe 无 PyInstaller version-info) / O1 (`.editorconfig` 缺) 等。**纯 audit 轮**，零代码 / 零数字变更；fix 由 r64+ 执行（用户决策路径 X/Y/Z/W）|

**连续 23 轮 0 CRITICAL correctness 保持**（r35-r63）。下次滚动归档：**r65** → `_archive/EVOLUTION_r61_r65.md`。

---

## 累积技术资产（r1-r60 视角）

### 翻译能力
- 三种 Ren'Py 翻译模式（direct / tl / retranslate） + screen 补充
- 三种引擎（Ren'Py / RPG Maker MV-MZ / CSV-JSONL 通用）
- 五大 LLM provider + 自定义引擎插件（**round 52 C3 BREAKING：subprocess sandbox-only**，importlib in-process loader retired）
- **目标语言：zh 简体中文 only**（round 52 C4 BREAKING：r35-r48 多语言 5 层 contract 完全删除；源语言不限 — LLM 自动识别）

### 质量保障链
- 占位符保护 + ResponseChecker + 50+ 项 validate_translation
- 漏翻率 12.12% → 4.01%（direct）/ 99.97% → **99.991% 翻译成功率**（tl-mode；r52 实测 The Tyrant 74098 entries / 0.0013% checker drop）

### 架构健康度
- 所有源 .py < 800 行（pre-commit 自动 enforce）
- 26 sites / 12 modules 全 TOCTOU MITIGATED
- 23/23 user-facing JSON loader OOM cap 全覆盖
- 3 处 pickle 全白名单（pickle_safe + rpyc Tier 1+2 + rpa_unpacker）
- 插件**强制 subprocess sandbox**（r52 C3）+ startup readiness probe + 三通道防护（stdout 50M chars + stderr 10K + stdin lifecycle）
- HTTPS 持久连接池（节省 ~90s / 600 次调用） + 32 MB 响应硬上限

### 自动化工程
- CI：6 jobs（2 OS × 3 Python）+ ruff lint+format gate + mypy enforce on 6+engines/+safety/ scope
- pre-commit hook 4 件套（py_compile + 800 行 cap + meta-runner + verify_docs_claims --fast）
- HANDOFF.md VERIFIED-CLAIMS 单一声称源 + push-status drift check
- Mock target / Repo rename / build.py CI smoke / EVOLUTION 滚动归档（r60 首次） — 5 项 drift prevention guards
- Pickle 红队 audit 8/8 verified；HTTP 响应体精度 1 B；retry stage 并发 + per-chunk log；LLM ID drift detection layer-6；JSON mis-escape layer-7 char-walker repair

### 文档体系
- 根目录：`README.md` / `CLAUDE.md` (= `.cursorrules`) / `HANDOFF.md` / `CHANGELOG.md` / `CONTRIBUTING.md` / `SECURITY.md` / `AUDIT_R57.md`
- `docs/`：`ARCHITECTURE.md` / `REFERENCE.md` / `ONBOARDING.md` / `RELEASE.md` / `ROADMAP.md` / `adr/0001-0005.md`
- `_archive/`：本文件 + `EVOLUTION_r56_r60.md`（r60 首次滚动归档）+ `CHANGELOG_FULL.md` + `CHANGELOG_RECENT_r52.md` + `TEST_PLAN_r50.md`
- `scripts/`：`verify_docs_claims.py` / `verify_workflow.py` / `install_hooks.sh` / `migrate_db_v2_to_v1.py`

---

## 设计原则的演进

最初 9 大原则在 r1-r10 沉淀；r41-r49 因 audit-tail 累计 4 项工具化 prevention；r50 起加入第 10 条**零欠账闭合**（findings 同轮 fix，无法 fix 归 architectural decision）。完整 15 hard contracts（r1-r58 累积）见 [`CLAUDE.md`](../CLAUDE.md) §维护规则。
