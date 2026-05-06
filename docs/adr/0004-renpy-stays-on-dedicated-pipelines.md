# 0004. Ren'Py 不走 generic_pipeline，保持三条专用管线

* 状态：Accepted
* 引入轮次：r54（同时 retire A-H-3 Medium / Deep）
* 决策者：@Dean20030514
* 关联：[`docs/REFERENCE.md`](../REFERENCE.md) §13.2.1 + [`_archive/EVOLUTION.md`](../../_archive/EVOLUTION.md) 阶段十三

## 背景

r28 提出 "A-H-3 Adapter Hammered House" 三档方案让所有引擎走统一抽象：
- **Minimal** ✅ 已完成 — `main.py` 不再分派 translators/，全部走 `engines.resolve_engine(...).run(args)`
- **Medium** ⏸ Ren'Py 走 `generic_pipeline` 6 阶段
- **Deep** ⏸ 完全退役 `DialogueEntry`

r28 当时项目还在多引擎 + 多语言（zh / zh-tw / ja / ko）时代，"统一抽象"有 ROI。

r52 C4（[ADR 0002](0002-zh-only-target-language.md)）retire 多语言后，项目用户场景收窄到单一 zh 目标 + Ren'Py 主用户面，Medium / Deep 的实际价值需要重新评估。

## 考虑的方案

1. **A-H-3 Medium**：让 Ren'Py 走 generic_pipeline 6 阶段（refactor + byte-identical 输出 baseline 验证）
2. **A-H-3 Deep**：完全退役 DialogueEntry，所有引擎统一用 TranslatableUnit + metadata
3. **保持现状**（Ren'Py 三条专用管线）+ 显式 retire Medium/Deep

## 决策

选择**方案 3**：r54 retire Medium/Deep 到 architectural decision。

理由（详见 [`docs/REFERENCE.md`](../REFERENCE.md) §13.2.1 完整对比表）：

1. **generic_pipeline 是从 tl-mode 派生的**：让 Ren'Py 反向接入是绕路（`build_generic_chunks` 是 `build_tl_chunks` 简化版，倒接是降级）
2. **r52 C4 后 zh-only**：multi-engine 抽象的核心动机（per-language 处理）已不存在
3. **r53 W1/W2/W3 优化集中在 Ren'Py 路径**：retry 并发化 / JSON escape repair / ID drift detection layer-6 全是 Ren'Py 专门优化，无法搬到 generic_pipeline
4. **DialogueEntry 三个特有字段** (`tl_file` / `tl_line` / `block_start_line`) 搬到 `metadata` 字典只是换位置，没真正统一；attribute access → dict lookup 是降级
5. **75+ 引用 / 11 文件 refactor**：删除无回滚（git revert 是唯一手段）

## 后果

正面：
- **保留 99.991% 翻译成功率** + 17 轮 0 CRITICAL streak（r35-r57，全在专用管线下达成）
- 减少 backlog 12 → 11 actionable（r54 共 retire 8 项，本 ADR 是其中 2 项）
- 给 r53 W1/W2/W3 优化留出空间（不必担心未来 generic 化丢失）

负面：
- `engines/renpy_engine.py::extract_texts` 抛 `NotImplementedError` 看似不一致（实际是 explicit）
- 新引擎接入（如 Unity XUnity r55 / 候选 Godot）走 generic_pipeline，与 Ren'Py 的两套机制并存

中立：
- DialogueEntry 保留为 Ren'Py 专有数据类型，不污染 generic_pipeline 抽象层
- 新工程师读 docs 会看到 `engines/renpy_engine.py` 的 `NotImplementedError` 困惑——已在 [`docs/REFERENCE.md`](../REFERENCE.md) §13.2.1 + 本 ADR 显式说明

## 关联

* 被本 ADR 影响：[0002 zh-only](0002-zh-only-target-language.md) 是 retire 触发条件
* 同轮其他 retire（r54）：见 [`HANDOFF.md`](../../HANDOFF.md) "Round 54 retire" 段
* 重新引入条件：用户场景出现"需要 Ren'Py 与其他引擎共享流程的真实需求" + 提供 byte-identical 输出 baseline 验证 + plan-first 论证 ROI 翻转（当前 ROI 严重为负）
