# 贡献指南 / Contributing

[简体中文](#简体中文) · [English](#english)

---

## 简体中文

### 环境

- Python ≥ 3.10，**零第三方依赖**（PR 引入任何 `requirements` 或 `pip install` 会被驳回）
- 文件编码 UTF-8（无 BOM），换行 LF（见 `.gitattributes`）
- Windows 是主要开发环境，但代码须保证 Linux / macOS 可跑通测试

### 10 大开发原则

详见 [CLAUDE.md](CLAUDE.md)。摘要：

1. 宁可漏翻也不误翻 / 2. 数据驱动 / 3. 隔离变量 / 4. 不破坏已有功能 / 5. 安全优先
6. 先读再写 / 7. 方案先行 / 8. 最小改动 / 9. 零依赖 / **10. 零欠账闭合**（r50 起新规则：所有 audit findings 同轮 fix）

### 工作流

1. **Issue 讨论方案**：非 trivial 改动（>20 行 / 新功能）先开 issue，列出目的 / 受影响模块 / 兼容性 / 测试策略
2. **分支策略**：`feat/xxx` 或 `fix/xxx` 从 `main` 创建。一个 PR 只做一件事
3. **TDD**：先写测试（RED）→ 实现（GREEN）→ 重构（IMPROVE）。修 bug 必须先补回归测试
4. **运行测试**：

```bash
python tests/test_all.py                    # meta-runner（~5s）
python tests/test_engines.py                # 独立 suite，按需挑选
python scripts/verify_docs_claims.py --fast # docs claim 同步性
```

5. **Conventional Commits**：`feat:` / `fix:` / `refactor:` / `docs:` / `test:` / `chore:` / `perf:` / `ci:` / `security:`
6. **更新 CHANGELOG**：详细变更进 `_archive/CHANGELOG_RECENT_*.md`；阶段总览进 `CHANGELOG.md`；如声称数字变化必须同步 `HANDOFF.md` 顶部 `VERIFIED-CLAIMS` 块
7. **pre-commit hook**：通过 `scripts/install_hooks.sh` 启用；自动跑 4 件套（py_compile + 800 行 cap + meta-runner + verify_docs_claims --fast）

### PR 检查清单

- [ ] 已列出修改的文件和函数
- [ ] 未引入任何第三方依赖
- [ ] 未改变默认行为，或新增功能由 CLI 开关控制
- [ ] 新增/修改的函数有类型注解 + docstring
- [ ] 任何文件 ≤ 800 行
- [ ] 有对应测试用例，`python tests/test_all.py` 全绿
- [ ] 原地修改文件前有 `.bak` 备份逻辑（如适用）
- [ ] checker 不通过的翻译被丢弃（而非强行使用）
- [ ] CHANGELOG / HANDOFF 已同步

### 代码风格

- PEP 8，`snake_case` / `PascalCase` / `UPPER_SNAKE_CASE`
- 公共函数签名必须有类型注解
- 文档字符串必须解释**为什么**（不是"做了什么"）
- 单文件 ≤ 800 行（pre-commit hook 自动 enforce）
- **新代码 100% type hint**（r61 T2 规则）：新增 `def` 必须有完整签名 hint（args + return）；不强求 backfill 存量代码；6 文件核心 scope（见 [ADR 0007](docs/adr/0007-mypy-enforce-scope.md)）必须 mypy 0 errors

### 引入新引擎

参见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) "5.4 新引擎添加流程（7 步）"。

### 报告安全问题

**不要**通过公开 issue 报告。请按 [SECURITY.md](SECURITY.md) 流程私密报告。

### Governance（r62 O2 文档化）

当前治理模型：**BDFL (Benevolent Dictator For Life)** — [@Dean20030514](https://github.com/Dean20030514) 是唯一 maintainer，拥有：

- **PR merge 权**：所有 PR 由 maintainer 评审 + merge；contributor 可通过 issue / PR 提建议但不直接 merge
- **Backlog 优先级决策**：actionable backlog（见 [ROADMAP.md](ROADMAP.md)）+ audit fix path 选择（如 r54 backlog 评估纪律 / r60 audit 路径 X 选择）由 maintainer 决定
- **Hard contracts 制定与放宽**：[CLAUDE.md §维护规则](CLAUDE.md) 当前 15 条 hard contracts；新增需 plan-first，放宽需 BREAKING-level 评估
- **CoC 执行**：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 违规处理由 maintainer 裁定

**Contributor 角色**：通过 issue / PR / Discussions（如未来开放）提供建议、报告 bug、贡献代码。所有 contributor 在 git history 中保留作者署名（[hard contract #6](CLAUDE.md) — 6 处 `anonymousException` 上游归属永久保留 + 未来 contributors 通过 git log 留底）。

**AI 协作角色**：当前主开发流程含 AI 辅助（Claude / Cursor）— 由 maintainer 主导 + AI 加速 + 人工 review。AI 生成代码不享有作者身份（按工具属性归 maintainer），但可在 commit message / docs 中说明 AI 协作上下文。

**未来演进**：当用户量增长 + 出现稳定的多人协作 contributors，治理模型可演进到 multi-maintainer（需 plan-first 评估流程，如 PR 评审权、merge 权、release 权的分配）。

---

## English

### Environment

- Python ≥ 3.10, **zero third-party dependencies** (PRs introducing any `requirements` or `pip install` will be rejected)
- Encoding UTF-8 (no BOM), line endings LF (see `.gitattributes`)
- Windows is the primary dev environment, but code must pass tests on Linux / macOS

### 10 Development Principles

See [CLAUDE.md](CLAUDE.md). Summary:

1. Skip rather than mistranslate / 2. Data-driven / 3. Isolate variables / 4. Don't break existing features / 5. Safety first
6. Read before write / 7. Plan first / 8. Minimal change / 9. Zero deps / **10. Zero-debt closure** (Round 50+ rule: all audit findings fixed same-round)

### Workflow

1. **Discuss in an issue first**: non-trivial changes (>20 lines / new features) need an issue listing goal / modules affected / compatibility / test strategy
2. **Branch**: `feat/xxx` or `fix/xxx` off `main`. One PR, one thing
3. **TDD**: tests first (RED) → impl (GREEN) → refactor (IMPROVE). Bug fix MUST add regression test before fix
4. **Run tests**:

```bash
python tests/test_all.py                    # meta-runner (~5s)
python tests/test_engines.py                # individual suites as needed
python scripts/verify_docs_claims.py --fast # docs claim sync check
```

5. **Conventional Commits**: `feat:` / `fix:` / `refactor:` / `docs:` / `test:` / `chore:` / `perf:` / `ci:` / `security:`
6. **Update CHANGELOG**: detailed changes go to `_archive/CHANGELOG_RECENT_*.md`; stage overview to `CHANGELOG.md`; if claimed numbers change you MUST sync the `VERIFIED-CLAIMS` block at the top of `HANDOFF.md`
7. **pre-commit hook**: enable via `scripts/install_hooks.sh`; auto-runs 4 checks (py_compile + 800-line cap + meta-runner + verify_docs_claims --fast)

### PR Checklist

- [ ] Listed modified files and functions
- [ ] No third-party dependencies introduced
- [ ] Default behaviour unchanged, or new feature gated by CLI flag
- [ ] New/modified functions have type annotations + docstrings
- [ ] All files ≤ 800 lines
- [ ] Tests added; `python tests/test_all.py` all green
- [ ] In-place file modifications have `.bak` backup logic (if applicable)
- [ ] Failed-checker translations are discarded (not force-used)
- [ ] CHANGELOG / HANDOFF synced

### Style

- PEP 8, `snake_case` / `PascalCase` / `UPPER_SNAKE_CASE`
- Public function signatures must have type annotations
- Docstrings must explain **why** (not "what")
- Single file ≤ 800 lines (pre-commit hook auto-enforces)
- **New code 100% type hint** (r61 T2 rule): new `def` must have full signature hints (args + return); no backfill required for existing code; the 6-file core scope (see [ADR 0007](docs/adr/0007-mypy-enforce-scope.md)) must remain mypy clean

### Adding a New Engine

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) "5.4 New engine flow (7 steps)".

### Reporting Security Issues

**Do not** open a public issue. Follow the private process in [SECURITY.md](SECURITY.md).

### Governance (r62 O2 documentation)

Current model: **BDFL (Benevolent Dictator For Life)** — [@Dean20030514](https://github.com/Dean20030514) is the sole maintainer, holding:

- **PR merge authority**: All PRs reviewed + merged by the maintainer; contributors propose via issue / PR but do not merge directly.
- **Backlog priority**: actionable backlog (see [ROADMAP.md](ROADMAP.md)) + audit fix path selection (e.g. r54 backlog discipline / r60 audit path X) decided by the maintainer.
- **Hard contracts**: [CLAUDE.md §维护规则](CLAUDE.md) currently has 15 hard contracts; additions require plan-first, relaxations require BREAKING-level evaluation.
- **CoC enforcement**: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) violations adjudicated by the maintainer.

**Contributor role**: Submit issues / PRs / Discussions (if opened later) to propose, report bugs, or contribute code. All contributors keep authorship in git history ([hard contract #6](CLAUDE.md) — 6 `anonymousException` upstream attribution sites permanently preserved; future contributors recorded via git log).

**AI collaboration role**: The current development flow includes AI assistance (Claude / Cursor) — driven by the maintainer + accelerated by AI + reviewed manually. AI-generated code does not carry authorship (attributed to the maintainer as a tool property), but commit messages / docs may describe the AI collaboration context.

**Future evolution**: As user base grows and stable multi-person contributor patterns emerge, the model can evolve to multi-maintainer (requires plan-first evaluation of PR review, merge, release authority distribution).
