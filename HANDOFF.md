# HANDOFF — Round 58 末 → Round 59 起点

<!-- VERIFIED-CLAIMS-START -->
tests_total: 494
test_files: 35
ci_steps: 36
assertion_points: 620
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

纯 Python 零依赖**zh-only**游戏汉化工具。**Round 58 余下 4 维度审计 — 架构设计 + 流程文档维度全闭合（8 项 fix）**：(A1) `core/config.py::resolve_args_from_config` 抽取——三层合并逻辑（CLI > config file > defaults）从 main.py inline 提到共享 helper + 2 单元测试；(A2) `docs/REFERENCE.md §7a` 配置层级优先级文档化（API key 5 层 fallback + 三层合并逻辑）；(A3) `docs/REFERENCE.md §13.2.1` RenPyEngine 不走 generic_pipeline 6 项对比 + r54 retire 理由；(P1) **CI 加 ruff check + ruff format --check + mypy scope 扩大到 engines/+safety/**——一次性 ruff format 99 文件；pyproject.toml 加 `[tool.ruff]` 配置（target-version py310 + extend-ignore E402/E501/F841）；(P2) **process docs 大补**——RELEASE.md / ROADMAP.md / docs/adr/（5 份 ADR：zero-deps / zh-only / subprocess-plugin / RenPy-dedicated-pipelines / safety-toplevel）/ ISSUE_TEMPLATE bug+feature / PULL_REQUEST_TEMPLATE / dependabot.yml；(P3) **EVOLUTION 滚动归档约定**——每 5 轮（r60/r65/...）抽离详细叙事到 `_archive/EVOLUTION_rN-4_rN.md`；(P4) README 顶部加 i18n 说明（项目主要面向中文用户，README + CONTRIBUTING 双语）。Plus **800 行 cap split**：test_translators.py 832 → 654（拆 6 main CLI 测试到新 test_main_cli.py）+ test_file_safety.py docstring 精简 798。**连续 18 轮 0 CRITICAL correctness**（r35-r58）。

## 同步状态

- r58 单 commit 待 push（NEVER push 政策保留给用户）
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
| Process docs | ✅ **r58 P2**：RELEASE / ROADMAP / 5 ADR / ISSUE_TEMPLATE / PR_TEMPLATE / dependabot.yml |
| EVOLUTION 滚动归档约定 | ✅ **r58 P3**：每 5 轮 (r60/r65/...) 归档详细叙事到 `_archive/EVOLUTION_rN-4_rN.md` |
| 累计审计 | ✅ 连续 18 轮 0 CRITICAL correctness（r35-r58） |

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

### ✅ Round 58 完成（8 项 audit fix；架构设计 + 流程文档维度全闭合）

> r57 末完成 [`AUDIT_R57.md`](AUDIT_R57.md) 6 维度共 23 findings 中的维度 1+2 (T1-T4, S1-S4) 8 项；本轮推进**维度 3 (架构与设计) + 维度 4 (流程与文档) 共 8 项**，剩余维度 5 (产品与业务，B1-B4) + 维度 6 (组织与知识，O1-O4) 给 r59+。

- **A1 — `_resolve_args_from_config` helper 抽取**：从 `main.py::main()` L249-266 inline 三层合并代码（CLI > config file > defaults）抽到 `core/config.py::resolve_args_from_config(args, cfg)`，~70 行。GUI / one-click pipeline / 未来 entry point 共享同一 helper，改 config 逻辑只改一处。+2 单元测试（fills_defaults / target_lang_hardcoded_zh）。
- **A2 — 配置层级优先级文档化**：`docs/REFERENCE.md §7a` 新加段，含 6 层 API key fallback 表格 + 三层 config 合并逻辑说明 + 引用 r58 A1 helper 路径。
- **A3 — RenPyEngine 不走 generic_pipeline 解释**：`docs/REFERENCE.md §13.2.1` 新加 6 项对比表（提取单位 / 分块策略 / 回写精度 / Retry 阶段 / Fallback 链 / LLM mis-escape），交叉引用 r54 retire 理由。
- **P1 — CI lint/format/mypy-expanded 门禁**：(a) 加 `ruff check .` + `ruff format --check .` 两个 CI step（ruff 是 dev-time tool，不破坏零依赖契约 — ADR 0001 仍 hold）；(b) `pyproject.toml` 加 `[tool.ruff]` 配置（target py310 + select E/F/W + extend-ignore E402/E501/F841 含理由注释 + format quote-style double）；(c) 一次性 `ruff format .` 99 files reformatted（baseline 立起）+ `ruff check --fix .` 132 errors auto-fixed；(d) mypy scope 扩大到 `engines/+safety/`（用 `--follow-imports=silent` 不让 translators/ 拖累 — translators/ 仍有 ~20 mypy errors，留 follow-up 不 gate）。
- **P2 — Process docs 大补**：(a) [`RELEASE.md`](RELEASE.md) — 手动 PyInstaller 流程 + 自动化 GitHub Actions tag-trigger 候选；(b) [`ROADMAP.md`](ROADMAP.md) — 公开版（用户/贡献者视角），按当前能力 / 短期 / 中期 / 长期 / 已 retire 5 段；(c) [`docs/adr/`](docs/adr/) — 索引 + 模板 + 5 份 ADR：0001 zero-deps / 0002 zh-only / 0003 subprocess-only-plugin / 0004 RenPy-dedicated / 0005 safety-toplevel；(d) [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) — bug_report.md + feature_request.md + config.yml（禁 blank issue + 引导到 Discussions / Security advisory）；(e) [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) — 改动类型 / hard contracts 检查 / docs sync checklist；(f) [`.github/dependabot.yml`](.github/dependabot.yml) — github-actions ecosystem monthly（runtime 零依赖不需 pip ecosystem）。
- **P3 — EVOLUTION 滚动归档约定**：CLAUDE.md 加"文档归档节奏"段。每 5 轮（r60 / r65 / r70 / ...）归档详细叙事到 `_archive/EVOLUTION_rN-4_rN.md`，主 EVOLUTION 仅留 1-2 句摘要 + 阶段表格行。**下次触发 r60**（当前 r58 后再 2 轮）。
- **P4 — README 顶部 i18n 说明**：明确告诉国际贡献者：README + CONTRIBUTING 双语；其他 docs 仅中文（项目主要面向中文用户）；in-repo 代码 / commit 仍英文。

**Plus 800-line cap split**（ruff format 让 2 测试文件越界）：
- `tests/test_translators.py` 832 → 654 行：拆 6 个 main.py CLI 测试到新 [`tests/test_main_cli.py`](tests/test_main_cli.py)（test_w_monitor4_* + test_w_round57_s2_*）
- `tests/test_file_safety.py` 807 → 798 行：精简模块顶部 docstring（保留所有测试逻辑）

**数字增量**：tests_total 492 → 494 (+2: A1); test_files 34 → 35 (+1: test_main_cli.py); ci_steps 34 → 36 (+2: ruff check + ruff format --check); assertion_points 618 → 620 (+2)。

### ✅ Round 57 完成（8 项 audit fix；技术债 + 质量与安全债维度全闭合）

> r56 末用户要求 6 维度（技术 / 质量与安全 / 架构与设计 / 流程与文档 / 产品与业务 / 组织与知识）债务审计；总 23 findings。Round 57 推进**技术债 + 质量与安全债**两维度（T1-T4 + S1-S4 共 8 项），余下 4 维度（A1-A3 / P1-P4 / B1-B4 / O1-O4）保留给 r58+。审计全程留底 [`AUDIT_R57.md`](AUDIT_R57.md)。

- **T1 — Python 版本契约统一**：`pyproject.toml requires-python = ">=3.10"`；CI matrix `[3.9, 3.12, 3.13]` → `[3.10, 3.12, 3.13]`；CLAUDE.md / README / CONTRIBUTING 全文 "Python ≥ 3.9" → "Python ≥ 3.10"。根因：项目 7 个文件用 PEP 604 `int \| None` 语法，运行时支持 3.10+，3.9 仅 `from __future__ import annotations` 才能 lazy eval — 任何 missing future import 的文件在 3.9 上都是 latent bug
- **T2 — Mypy enforce 升级（informational → enforce）**：CI step 移除 `\|\| true` + `continue-on-error: true`；6 文件 scope 实测 32 errors 全 fix（21 `# type: ignore[union-attr]` 标记 `core/api_plugin.py` runtime-safe Optional Popen 访问 + 11 真修：`translation_db.py` 加 Optional import / `splitter.py` chunks dict type hint + `read_file` accepts `Union[str, Path]` / `checker.py` rv tuple type / `api_client.py` rate limiter loop var rename）
- **T3 — Complex fixture 测试覆盖**：`tests/test_complex_fixture.py` 新建（synthetic 复杂 .rpy fixture：nvl_clear / nvl_narrator 块 / multi-line ``\\n`` say / `{i}` `{b}` `{color}` `{size}` 标签 / `[name]` 变量 / 转义引号 / SAZMOD 模组路径 + `translate chinese strings` block）+ 2 集成测试（scan extracts all + fill round-trip 验证 6 dialogues + 3 strings 全部正确填回 + 注释 / 空行 / 源文件 annotation 全保留）
- **T4 — `tools/` 散乱无共享 base** retire to architectural decision：CLAUDE.md "已知限制" 段记录 — 15 个 CLI tool 各自 entry 是项目第 8 原则"最小改动"接受的代价
- **S1 — `.gitignore` secrets patterns**：加 `.env` / `.env.*` / `*.key` / `*.pem` / `api_keys.json` / `secrets.json`（`renpy_translate.json` + `*.bak` 已存在）— defense-in-depth 防止 `git add .` 误提交
- **S2 — `main.py::_sanitize_user_path`**：path traversal 防护，拒绝用户路径 resolve 到 `_FORBIDDEN_PATH_PREFIXES`（`/etc/` `/sys/` `/proc/` `/dev/` `/root/` `/boot/` `/var/log/` + `c:/windows/` `c:/program files/` `c:/programdata/` 等）；3 测试覆盖（forbidden resolved path / Windows System32 mock / legitimate user path）；本地 single-user 工具威胁模型不变，主要 protect 多用户共享环境（CI runner / 教学 / 实验室）
- **S3 — Logger user-controlled var log injection** retire to architectural decision：CLAUDE.md "已知限制" 段记录 — 本地工具仅写 stdout，无集中日志系统，不构成 actionable
- **S4 — `.rpy` escape fuzz 测试**：`tests/test_file_processor.py` 加 2 测试 — fuzz with 12 adversarial LLM payloads (bare `"`, `\\`, `\\\\`, `"""`, mixed line endings, control chars, 1000-char input, non-ASCII + quotes, empty string) + 不变量断言（escape 后所有 `"` 必有奇数前导反斜杠 / 无裸 `\\r` 泄漏）+ idempotence 测试（safe input 不被错误转义）

**数字增量**：tests_total 485 → 492 (+7); test_files 33 → 34 (+1: `test_complex_fixture.py`); ci_steps 34 unchanged; assertion_points 611 → 618 (+7)。

**3 个新 hard contracts**（CLAUDE.md / .cursorrules）：
- mypy enforce 6 文件 scope 必须保持 0 errors
- Python ≥ 3.10 不可降级（PEP 604 已普遍使用）
- `_FORBIDDEN_PATH_PREFIXES` 不可放宽 + 任何新 path 入口需经 `_sanitize_user_path`

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

**Round 59 关键约束**：
- audit findings 必须**同轮 fix，no tier exemption**（r50 起 written + enforced；r51 / r52 / r53 / r54 / r55 / r56 / r57 / r58 各执行有效）
- **CI ruff lint/format 门禁**（r58 P1）— 任何新 PR 必须 `ruff check .` + `ruff format --check .` 全过；`pyproject.toml [tool.ruff]` extend-ignore 列表不得放宽
- **EVOLUTION 滚动归档**（r58 P3）— r60 触发首次归档（每 5 轮一次）；归档时主 EVOLUTION 减 ≥ 100 行
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
