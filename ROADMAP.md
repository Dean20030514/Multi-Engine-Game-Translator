# Roadmap

> **公开版**（用户/贡献者视角）。Internal-style 工程 backlog 见 [`HANDOFF.md`](HANDOFF.md)。
>
> 本文件 r58 P2 引入。**截止 r57 末**项目已闭合 4 大债务维度（5 死 import、file_safety 移到 safety/、Python 3.10、mypy enforce、path traversal、escape fuzz、complex fixture、hard contract 13 → 16）。

## 当前能力（r57 末）

- ✅ Ren'Py / RPG Maker MV-MZ / CSV-JSONL 三引擎成熟
- ✅ Unity XUnity AutoTranslator 文件支持（r55）
- ✅ 五大 LLM provider + custom plugin (subprocess sandbox)
- ✅ tl-mode 翻译成功率 99.991%（r52 实测 The Tyrant 74098 entries）
- ✅ direct-mode 漏翻率 4.01%（仅适用英文源）
- ✅ 17 轮连续 0 CRITICAL correctness streak（r35-r57）
- ✅ 26 sites TOCTOU MITIGATED + pickle 红队 verified safe + path traversal guard

## 短期路线图（按 ROI 排序）

| 优先级 | 项 | 状态 | 备注 |
|--------|----|------|------|
| 🟢 中 ROI | **Godot 引擎接入** | 候选 r59+ | `.tscn` / `.gd` / `.tres` 文本格式；纯标准库可行；~3% 用户面 |
| 🟢 中 ROI | **Kirikiri 2/Z + TyranoBuilder** | 候选 r59+ | `.ks` 文本可正则；~5% + ~3% 用户面 |
| 🟡 流程 | **CI ruff lint** | r58 P1 引入 | 升级代码风格门禁 |
| 🟡 流程 | **GitHub Actions tag-trigger release** | 候选 r59+ | 当前 release 是手动 PyInstaller；见 [`RELEASE.md`](RELEASE.md) §自动化候选 |

## 中期方向（架构 / 体验）

- **GUI/CLI 配置抽取**：r58 A1 引入 `_resolve_args_from_config` helper；持续观察是否需要 GUI 直接 import（当前 GUI 走 subprocess.Popen 间接调用 main.py）
- **错误信息一致性**（r57 audit B3，LOW）：用户面 prefix 中英混用；统一为中文需扫一遍源码
- **架构决策记录 (ADR)**：r58 P2 引入 `docs/adr/` 框架；后续每个架构决策（如 r52 C4 retire / r54 backlog 重新评估 / r56 file_safety 移位）写一个 ADR

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
- **PR**：见 [`CONTRIBUTING.md`](CONTRIBUTING.md) + 在 `docs/adr/` 加新架构决策
- **安全漏洞**：见 [`SECURITY.md`](SECURITY.md)
