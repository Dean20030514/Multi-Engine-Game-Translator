# Architecture Decision Records

> r58 P2 引入。每个重要架构决策一个文件，命名 `NNNN-<slug>.md`（NNNN 从 0001 起递增）。
>
> 完整历史叙事仍保留在 [`_archive/EVOLUTION.md`](../../_archive/EVOLUTION.md)（按轮次组织）；ADR 是**主题切片**——同一主题跨多轮的决策汇总到一个 ADR。

## 索引

| ID | 标题 | 状态 | 引入轮次 |
|----|------|------|---------|
| [0001](0001-zero-third-party-dependencies.md) | 零第三方依赖契约 | Accepted | r1 |
| [0002](0002-zh-only-target-language.md) | 目标语言固定 zh 简体中文 | Accepted (BREAKING) | r52 C4 |
| [0003](0003-subprocess-sandbox-only-plugin.md) | Custom plugin 强制 subprocess sandbox | Accepted (BREAKING) | r52 C3 |
| [0004](0004-renpy-stays-on-dedicated-pipelines.md) | Ren'Py 不走 generic_pipeline | Accepted | r54 |
| [0005](0005-safety-as-toplevel-package.md) | `safety/` 顶层独立 package | Accepted | r56 M2 |

## ADR 模板

新建 ADR 时复制下面模板：

```markdown
# NNNN. 标题

* 状态：[Proposed / Accepted / Superseded by NNNN / Deprecated]
* 引入轮次：r__
* 决策者：@username
* 关联 PR / commit：[链接]

## 背景 (Context)

为什么需要这个决策？什么问题或机会触发？

## 考虑的方案 (Considered Options)

1. 方案 A
2. 方案 B
3. ...

## 决策 (Decision)

选择哪个方案？为什么？

## 后果 (Consequences)

* 正面：...
* 负面：...
* 中立：...

## 关联

* 相关 ADR：[NNNN](NNNN-xxx.md)
* HANDOFF / EVOLUTION 段：...
```

## 何时写 ADR

- 引入或退役 hard contract（如 r52 C4 BREAKING / r56 M2 file_safety 移位 / r57 T2 mypy enforce）
- 选择不做某事（"explicit decision to not do X"，如 r54 8 项 retire）
- 跨多轮的主题决策（如 r35-r48 多语言 → r52 C4 retire 是同主题的决策演进）

## 何时不写 ADR

- 单轮代码 fix（写在 commit message + EVOLUTION 即可）
- 已有 ADR 的微调（更新原 ADR 而非新建）
- 个人风格偏好（不是架构层面）
