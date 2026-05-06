# Changelog

最新数字（测试数 / 文件数 / CI 步骤 / 断言点）见 [HANDOFF.md](HANDOFF.md) 顶部 `VERIFIED-CLAIMS` 块。完整历史见 [_archive/](_archive/)。

## 最近 5 轮（仅高亮，详细见归档）

- **Round 56** — **全面深度审计 + 8 项 fix（路径 C 全闭合，纯优化轮）**：用户 r55 末要求"全面且深度的检查一遍"。8 维度 audit 收集 11 findings (3 HIGH / 3 MEDIUM / 5 LOW)；用户决策路径 C 全部 fix。(H1) `core/api_client.py` 删 5 死 import (atexit/importlib.util/sys/Optional/Any) — r52 C3 retire 后清理不彻底；(H3) `engines/unity_xunity.py` 删 r55 残留 `field` 死 import；(M3) `_translate_one_tl_chunk` 函数内 import 提到模块顶层 (实测无循环)；(M2) `core/file_safety.py` → `safety/file_safety.py` 顶层独立 package — 避免 `file_processor` 间接依赖 `core` 的 layering 误解；CI mock target guard 用 fragment match `grep -v "file_safety"` 兼容两种路径，r48 stale mock trap CLASS 仍生效；CLAUDE.md 模块图调整；(M1) `UNITY_XUNITY_PROFILE` 加 9 个 `placeholder_patterns` 保护 regex backrefs (`\d`/`\w`/`\s`/`\b`/`\1`-`\9`) — LLM 翻译 regex pattern 时 `protect_placeholders` 自动 round-trip backref；(L1) 4 个 translators 模块共 29 处 print() → logger.info()；(L2) docs "17 sites" 硬编码改为"覆盖所有 production 模块"软描述（避免再 drift）。+2 单元测试 (M1 backref protection)。
- **Round 55** — **Unity XUnity AutoTranslator 引擎接入**（覆盖 ~10% 用户场景）：新增 `engines/unity_xunity.py`（349 行）实现 detect/extract/write_back，支持 XUAT 标准文件格式（`original=translation` 普通行 + `//` 注释保留 + `r:"<pattern>"="<replacement>"` 正则规则）。pattern 必须保留不翻译（hard contract #13），仅 replacement 提交 LLM。UTF-8 BOM round-trip + CRLF/LF 行尾按源文件保留 + 50 MB OOM cap + TOCTOU 防御。CLI `--engine unity` 与 `--engine unity_xunity` 都接受（manual-only，不自动检测）。16 单元测试 PASS（含 round-trip byte-identical assertion）。Actionable backlog 3 → 2（剩 Godot / Kirikiri+TyranoBuilder）。新增 hard contract #13。
- **Round 54** — **Backlog 重新评估（纯文档轮，零代码变更）**：用 r52 起"减法 + 聚焦"标准评估 r53 末 12 项 actionable backlog，将 **8 项 retire 到 architectural decision**：A-H-3 Medium / A-H-3 Deep / RPG Maker Plugin Commands (356) / 加密 RPA-RGSS / RPG Maker VX-Ace / Wolf RPG Editor / Unreal Engine / HTML5。retire 理由：A-H-3 在 r52 C4 zh-only 后通用化收益消失（generic_pipeline 反向接入是绕路 + DialogueEntry 退役无回滚）；RPG Maker Plugin Commands 真实覆盖 ~2.5% 用户场景应按需启动；加密归档涉法律灰色地带；RPG Maker VX/Ace 需 `rubymarshal` 违反零依赖契约；Wolf RPG / CSVEngine 间接已覆盖；Unreal / HTML5 不在项目定位。**Actionable backlog 12 → 3**（剩 Unity XUnity / Godot / Kirikiri+TyranoBuilder）。延续 CLAUDE.md 第 8 原则（最小改动）+ 第 10 原则（零欠账闭合）。
- **Round 53** — **W1-W4 主线全闭合 + 6 监控项重新评估**：(W1) `tl_mode.py` retry 拆到新模块 `translators/_tl_retry.py` (174 行) + ThreadPoolExecutor + per-chunk progress log + 自适应 chunk size；(W2) `core/api_client.py::_extract_json_array` 加 layer-7 char-walker `_repair_unescaped_quotes_in_strings` 修字符串值内未 escape `"`；(W3) layer-6 LLM ID drift detection (`detect_id_drift()` 主 stage + retry stage 各注入；symmetric-difference > 10% warn)；(W4) direct-mode English-only 文档化 (启动 INFO log + 常量 docstring + README + CLAUDE.md)；监控 #1 pickle 白名单 8/8 红队 verified safe；监控 #2 HTTP 64 KB 精度偏差降至 1 B；监控 #3+#5+#6 retire to architectural decision；监控 #4 symlink CLI warning + `--allow-symlink` flag。Plus 36 单元测试新增 (17 W1+W3 / 5 W2 / 3 #2 / 8 #1 / 3 #4)。
- **Round 52** — **scope reduction BREAKING**：(C1) HANDOFF push-status drift checker；(C2) build.py CI smoke + GUI architectural decision；(C3 BREAKING) retire importlib plugin loader（subprocess 沙箱成唯一模式）；**(C4 BREAKING) drop multi-target language support**（删 `core/lang_config.py` + `--target-lang` flag + multi-lang outer loop + 5 层 contract + DB v2 schema + runtime-hook v2 schema + 4 测试文件 + `tools/merge_translations_v2.py`；目标语言固定 zh；存量 v2 DB 用 `scripts/migrate_db_v2_to_v1.py` 迁移）
- **Round 51** — GitHub 仓库重命名 sync `Renpy-Translator` → `Multi-Engine-Game-Translator`；4 contract tests pin repo URL + logger namespace；zero-debt closure 模式第二次执行
- **Round 50** — Zero-debt closure 模式确立（所有 audit findings 同轮 fix，no tier exemption）；r49 6 项 deferred 全 closure；2 latent fixture bug 同轮 fix；CI Mock target consistency check
- **Round 49** — Drift prevention 工具自动化（pre-commit + verify_docs_claims --fast/--full + VERIFIED-CLAIMS 单一声称源）；file_safety helper 推广 26 sites / 12 modules 全 TOCTOU MITIGATED

## 阶段总览

详见 [_archive/EVOLUTION.md](_archive/EVOLUTION.md)。

| 阶段 | 轮次 | 主题 |
|------|------|------|
| 阶段零 | r1-r10 | 翻译质量基线 |
| 阶段一 | r11-r17 | 架构成型（main.py 拆分 + 引擎抽象 + GUI） |
| 阶段二 | r18-r19 | 工具链补全（RPA/rpyc/lint/editor/插件） |
| 阶段三 | r20-r30 | 安全与稳健化（pickle 白名单 + ZIP Slip + 大文件拆分 + 沙箱） |
| 阶段四 | r31-r35 | 多语言与运行时注入（v2 schema + 外层语言循环） |
| 阶段五 | r36-r42 | 防御加固与契约化（OOM cap + checker per-language） |
| 阶段六 | r43-r45 | 累计审计期（CI Windows + plugin char/byte 澄清） |
| 阶段七 | r46-r48 | Auto Mode 综合执行（GUI smoke + TOCTOU helper） |
| 阶段八 | r49 | Drift Prevention 自动化（4 项工具 + 26 sites MITIGATED） |
| 阶段九 | r50 | Zero-Debt Closure 模式确立 |
| 阶段十 | r51 | GitHub 仓库重命名 sync + 4 contract tests pin |
| 阶段十一 | r52 | **Scope reduction BREAKING**（retire importlib plugin + drop multi-target language；只保留 zh 目标） |
| 阶段十二 | r53 | **W1-W4 主线 + 6 监控项重新评估**（retry 并发化 + JSON escape-fix + ID drift detection + direct-mode 文档化；pickle 红队 verified + HTTP 精度收紧 + symlink mitigation + 3 项 retire） |
| 阶段十三 | r54 | **Backlog 重新评估**（纯文档轮；8 项 retire to architectural decision：A-H-3 Medium-Deep + RPG Maker Plugin Commands + 加密归档 + RPG Maker VX-Ace + Wolf RPG + Unreal + HTML5；actionable backlog 12 → 3） |
| 阶段十四 | r55 | **Unity XUnity AutoTranslator 引擎接入**（~10% 用户面，新引擎从 0 到 1；XUAT 标准格式 + 正则规则 + BOM/CRLF round-trip + 16 单元测试；hard contract #13） |
| 阶段十五 | r56 | **全面深度审计 + 8 项 fix（路径 C）**（5 死 import 删 + file_safety 移到 safety/ 顶层 package + regex backref placeholder protection + 4 production 模块 print → logger + docs 数字软描述化） |

## 归档索引

- [_archive/EVOLUTION.md](_archive/EVOLUTION.md) — r1-r50 演进概览（无 commit hash，保 round 编号）
- [_archive/CHANGELOG_RECENT_r50.md](_archive/CHANGELOG_RECENT_r50.md) — Round 50 末归档的最近 5 轮详细
- [_archive/CHANGELOG_FULL.md](_archive/CHANGELOG_FULL.md) — r1-r45 总览表 + r19/r43 完整正文
- [_archive/TEST_PLAN_r50.md](_archive/TEST_PLAN_r50.md) — Round 50 末归档的测试覆盖明细
