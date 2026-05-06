# CLAUDE.md — AI 全局上下文

> 与 [`.cursorrules`](.cursorrules) **byte-identical**。修改时必须双写（推荐 `cp CLAUDE.md .cursorrules`）。

## 项目身份

纯 Python（**零第三方依赖**，Python ≥ 3.9）多引擎游戏汉化工具。支持 Ren'Py / RPG Maker MV-MZ / CSV-JSONL，五大 LLM provider（xAI/OpenAI/DeepSeek/Claude/Gemini）+ 自定义引擎插件（dual-mode：importlib 快路径 + opt-in subprocess 沙箱）。

**当前数字**（测试数 / 文件数 / CI 步骤 / 断言点）：见 [HANDOFF.md](HANDOFF.md) 顶部 `<!-- VERIFIED-CLAIMS-START -->` 块 — **单一声称源**。本文 prose 不再独立声称数字。

**质量水位**：direct-mode 漏翻率 4.01%；tl-mode 翻译成功率 99.97%；连续 11 轮 0 CRITICAL correctness（r35-r51）。

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
       ├── config.py / lang_config.py / font_patch.py
       ├── http_pool.py        HTTPS 线程本地连接池 (~90s 节省 / 600 次)
       ├── pickle_safe.py      白名单 SafeUnpickler
       ├── file_safety.py      TOCTOU 防御 (fstat 二次校验，26 sites 共享)
       └── runtime_hook_emitter.py

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

- GUI / build 仅手动测试，未纳入自动化
- 端到端测试需 API key，未进入 CI
- RPG Maker Plugin Commands(356) / JS 硬编码 / 加密归档暂不支持
- 非中文目标语言（ja / ko / zh-tw）有 5 层 code-level contract 锁死，但端到端验证仍需真实 API + 游戏

---

## 文档索引

| 你在做什么 | 加载 |
|-----------|------|
| 修改翻译模式 / 流水线 / 校验链 / 引擎 / 测试体系 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 调整阈值常量 / 校验规则 / 路线图 | [docs/REFERENCE.md](docs/REFERENCE.md) |
| 当前 build / 数字 / 推荐下一步 | [HANDOFF.md](HANDOFF.md) |
| 历史决策（r1-r51） | [_archive/EVOLUTION.md](_archive/EVOLUTION.md) |
| 最近 5 轮详细变更（r47-r51） | [_archive/CHANGELOG_RECENT_r51.md](_archive/CHANGELOG_RECENT_r51.md) |
| 用户面文档（中英双语） | [README.md](README.md) |

---

## 自动化与 drift 防御

- **pre-commit hook 4 件套**（`scripts/install_hooks.sh` 启用）：py_compile + 800 行 cap + meta-runner + `verify_docs_claims --fast`
- **CI**：6 jobs（matrix `[ubuntu-latest, windows-latest]` × `[3.9, 3.12, 3.13]`）
- **HANDOFF.md `VERIFIED-CLAIMS` 块**：唯一数字声称源，pre-commit + CI 双层 enforce
- **Mock target consistency CI guard**：所有 `mock.patch(...os.fstat)` / `patch.object(os, "fstat", ...)` 必须 target `core.file_safety`（防 stale mock trap CLASS；r50 C4 filter 放宽到 `file_safety` 兼容 qualified form；r51 audit-tail 加第三级 `test_repo_rename_consistency` filter 豁免 documentation-only 文件 self-trip）
- **Repo rename consistency CI guard**（r51 起）：`tests/test_repo_rename_consistency.py` 钉自身 repo URL refs（`pyproject.toml` + `renpy_translate.example.json`）+ logger namespace（17 sites `getLogger("multi_engine_translator")`）+ 6 处 anonymousException 上游归属反向 exhaustiveness

---

## 维护规则

1. 修改 `CLAUDE.md` 必须同步 `.cursorrules`（byte-identical 契约）
2. 数字声称（测试数 / 文件数 / CI 步骤 / 断言点）只在 `HANDOFF.md` `VERIFIED-CLAIMS` 块声明，其他文档只引用
3. 永远不要在文档中**直接**写测试数 / 行数 / 文件数等数字而不先 grep / wc / find / `verify_docs_claims --fast` ground-truth
4. round 50 起所有 audit findings 同轮 fix，零 deferred（r51 第二次执行验证有效）
5. 大改动遵循三段式：Plan → Implement（小步） → Verify（零问题）
6. 修改 logger namespace / repo URL self-references 必须保持 `tests/test_repo_rename_consistency.py` 4 contract tests 全 PASS；6 处 `anonymousException renpy-translator (MIT, 2024)` 上游归属永远不能被任何 sed / refactor 误删（r51 加固）
