# Roadmap

> **公开版**（用户/贡献者视角）。Internal-style 工程 backlog 见 [`HANDOFF.md`](HANDOFF.md)。
>
> 本文件 r58 P2 引入。**截止 r66 末**项目历经 3 轮 6 维度深度审计（r57 / r60 / r63 cycles，共 69 unique findings 全闭合）+ r66 用户决策 retire ADR + AUDIT framework；hard contracts 15 条 + 25+ 轮连续 0 CRITICAL streak。

## 当前能力（r66 末）

- ✅ Ren'Py / RPG Maker MV-MZ / CSV-JSONL / Unity XUnity 四引擎成熟（Unity r55 引入）
- ✅ 五大 LLM provider + custom plugin (subprocess sandbox-only，r52 C3 BREAKING)
- ✅ tl-mode 翻译成功率 99.991%（r52 实测 The Tyrant 74098 entries / 0.0013% checker drop）
- ✅ direct-mode 漏翻率 4.01%（仅适用英文源；r53 W4 文档化）
- ✅ **26 轮连续 0 CRITICAL correctness streak（r35-r66）**
- ✅ 26 sites TOCTOU MITIGATED + pickle 红队 verified safe + path traversal guard
- ✅ **CI 三 OS matrix**（ubuntu / windows + macos nightly schedule，r61 S1）+ ruff lint+format gate（r58 P1）+ mypy enforce 6 文件 scope（r57 T2）+ release.yml 自动化（r59 B1，3 OS PyInstaller → SHA256SUMS → draft Release）
- ✅ **完整 docs 体系**：CLAUDE.md / HANDOFF.md / docs/ARCHITECTURE.md / docs/REFERENCE.md / docs/ONBOARDING.md / CODE_OF_CONDUCT.md / CONTRIBUTING.md "Governance" 段（r66 retire ADR + AUDIT framework — 架构决策由 CLAUDE.md hard contracts 列表 + EVOLUTION 阶段叙事 完整记录）
- ✅ **项目版本**：v2.0.0（r62 B2 升级反映 r52 C3/C4 + r57 T1 累积 BREAKING）；`python main.py --version` 可查（r64 S4）

## 短期路线图（按 ROI 排序）

| 优先级 | 项 | 状态 | 备注 |
|--------|----|------|------|
| 🟢 中 ROI | **Godot 引擎接入** | 候选 r66+ | `.tscn` / `.gd` / `.tres` 文本格式；纯标准库可行；~3% 用户面 |
| 🟢 中 ROI | **Kirikiri 2/Z + TyranoBuilder** | 候选 r66+ | `.ks` 文本可正则；~5% + ~3% 用户面 |
| 🟡 流程 | **CI ruff lint+format** | ✅ r58 P1 引入 | 已 enforce |
| 🟡 流程 | **release.yml tag-trigger** | ✅ r59 B1 引入 | v* tag → 3 OS matrix → draft Release |
| 🟡 流程 | **macOS nightly CI** | ✅ r61 S1 引入 | cron + workflow_dispatch |
| 🟡 流程 | **Meta-runner subprocess discover** | ✅ r64 S1 引入 + r67 H1 banner regex 修 | 全部 35 启用文件（test_all.py 自身 + test_single.py 排除）pre-commit 全跑；count 准确性 r67 修复 |

## 中期方向（架构 / 体验）

- **GUI/CLI 配置抽取**：r58 A1 引入 `_resolve_args_from_config` helper；持续观察是否需要 GUI 直接 import（当前 GUI 走 subprocess.Popen 间接调用 main.py）
- **错误信息一致性**（r57 audit B3，LOW）：用户面 prefix 中英混用；统一为中文需扫一遍源码

## 长期愿景（用户场景驱动，不主动推进）

| 项 | 触发条件 |
|---|---------|
| RPG Maker Plugin Commands (code 356) | 用户报告具体 MV/MZ 游戏样本含 plugin command 文本 |
| 加密 RPA / RGSS 归档 | 法律风险评估通过 + 用户场景明确 |
| 真实 ja / ko 端到端验证 | r52 C4 BREAKING 后已 retire；如重启需先 plan-first 撤销 r52 C4 |
| Web 浏览器扩展（在线翻译触发器）| 项目用户量增长到需要 community 版本 |

## 已 retire（不再追求）

详见 [`HANDOFF.md`](HANDOFF.md) "Round 54 retire" 段 + r56/r57 audit。完整列表：

- A-H-3 Medium / Deep（Ren'Py 走 generic_pipeline / 退役 DialogueEntry）— r54 retire（详见 [`docs/REFERENCE.md`](docs/REFERENCE.md) §13.2.1）
- 多目标语言（ja / ko / zh-tw）— r52 C4 BREAKING retire
- importlib in-process plugin — r52 C3 BREAKING retire
- RPG Maker VX/Ace（需 `rubymarshal` 依赖）— r54 retire（违反零依赖契约）
- Wolf RPG Editor（CSVEngine 已间接覆盖）— r54 retire
- Unreal Engine（uasset 工具链复杂度过高）— r54 retire
- HTML5 / 浏览器游戏（用户场景虚）— r54 retire
- `tools/` 共享 base 抽取 — r57 T4 retire（最小改动原则）

## 反馈与贡献

- **Issue / 功能请求**：[GitHub Issues](https://github.com/Dean20030514/Multi-Engine-Game-Translator/issues)（请使用 `.github/ISSUE_TEMPLATE/` 模板）
- **PR**：见 [`CONTRIBUTING.md`](CONTRIBUTING.md)（架构决策记录到 CLAUDE.md hard contracts 列表 + EVOLUTION 阶段叙事；r66 起不再用 ADR 文件）
- **安全漏洞**：见 [`SECURITY.md`](SECURITY.md)
