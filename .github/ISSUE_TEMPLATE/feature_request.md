---
name: 功能请求 / Feature request
about: 提出新功能或增强 / Propose new feature or enhancement
title: "[FEATURE] "
labels: enhancement
assignees: ''
---

> 提交前请阅读 [`ROADMAP.md`](../../ROADMAP.md) — 已 retire 的项需要新证据才能重启。

## 用户场景 / Use case

你想解决什么实际问题？多少用户会受益？
What real problem are you solving? How many users benefit?

## 提议方案 / Proposed solution

具体怎么做？尽量给出实现思路。
Concrete approach. Sketch the implementation if possible.

## 替代方案 / Alternatives considered

有没有现有方法解决？为什么不行？
Existing workarounds? Why aren't they enough?

## 是否触及零依赖契约 / Touches zero-deps contract?

- [ ] **不触及**（仅用 Python 标准库）/ No (stdlib-only)
- [ ] **触及**（需要新第三方依赖）/ Yes (new third-party dep) — 必须先 plan-first 撤销 [ADR 0001](../../docs/adr/0001-zero-third-party-dependencies.md)

## 是否触及已有 hard contract / Touches existing hard contracts?

参考 [`CLAUDE.md`](../../CLAUDE.md) "维护规则"段。例如：
- [ ] 触及 mypy enforce 6 文件 scope
- [ ] 触及 Python ≥ 3.10 floor
- [ ] 触及 path traversal `_FORBIDDEN_PATH_PREFIXES`
- [ ] 触及 Unity XUnity 解析契约（partition / 注释 round-trip / regex pattern preservation）
- [ ] 触及 Pickle 白名单（需先跑红队 audit）
- [ ] 触及 retry 并发 / ID drift detection layer-6（r53 W1 / W3）
- [ ] 触及目标语言 zh-only contract（[ADR 0002](../../docs/adr/0002-zh-only-target-language.md)）
- [ ] 触及 plugin subprocess sandbox 契约（[ADR 0003](../../docs/adr/0003-subprocess-sandbox-only-plugin.md)）
- [ ] **以上都不触及** / None of the above

## 验证策略 / Verification

如何确认实现正确？需要新测试 / fixture 吗？
How will correctness be verified? New tests / fixtures needed?

## 关联 / Related

- 相关 issue: #
- 相关 ADR: [docs/adr/](../../docs/adr/)
- 相关历史决策: [_archive/EVOLUTION.md](../../_archive/EVOLUTION.md)
