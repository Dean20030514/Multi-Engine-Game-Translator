# Pull Request

> 中文 / English 都可以。

## 摘要 / Summary

简短说明改动内容。
Brief description of what this PR does.

## 改动类型 / Type

- [ ] feat — 新功能 / New feature
- [ ] fix — Bug 修复 / Bug fix
- [ ] refactor — 重构（不改外部行为）/ Refactor (no behaviour change)
- [ ] docs — 仅文档 / Documentation only
- [ ] test — 仅测试 / Tests only
- [ ] chore — 构建 / 工具链 / 其他
- [ ] perf — 性能优化 / Performance
- [ ] ci — CI 配置 / CI workflow
- [ ] **BREAKING** — 含破坏性变更（需 plan-first 撤销相关 hard contract）

## 关联 issue / Related

Closes #
Refs #

## 验证 / Verification

- [ ] `python tests/test_all.py` 全过 / All tests pass
- [ ] `python scripts/verify_docs_claims.py --fast` 全过 / verify_docs_claims passes
- [ ] `diff CLAUDE.md .cursorrules` 无差异（如改了 CLAUDE.md）/ byte-identical (if CLAUDE.md changed)
- [ ] 新加的 production .py 通过 mypy（核心 6 文件 scope）/ New production .py passes mypy (6-file scope)
- [ ] 新加的 .py 文件 < 800 行 / New .py files < 800 lines
- [ ] HANDOFF.md `VERIFIED-CLAIMS` 块更新（如 tests / 文件数变化）/ VERIFIED-CLAIMS updated if numbers changed

## Hard contracts 检查 / Hard contracts check

参考 [`CLAUDE.md`](../CLAUDE.md) "维护规则"段（13 条）。本 PR 是否触及任一契约？

- [ ] **不触及任何 hard contract**
- [ ] 触及，已 plan-first 论证（请在下方说明）/ Touches one — see plan below

如触及请说明：
<details>
<summary>plan / 论证</summary>

（粘贴 plan-first 文档或链接）

</details>

## 文档同步 / Docs sync

- [ ] CHANGELOG.md 加了 round 段（含 brief 高亮）
- [ ] HANDOFF.md "推荐 Round N+1 工作项"或"已完成"段更新
- [ ] `_archive/EVOLUTION.md` 加了阶段段（如该轮独立成阶段）
- [ ] 新建架构决策有对应 [`docs/adr/`](../docs/adr/) entry（如适用）
- [ ] README / docs/REFERENCE / docs/ARCHITECTURE 同步（如改了 user-facing 行为或常量）

## 测试覆盖 / Test coverage

新加 / 修改的功能有对应测试？
- [ ] 是 / Yes
- [ ] 否，理由：/ No, reason:

## 备注 / Notes

任何 reviewer 应该额外注意的：
（如：影响 hot path 的优化 / 引入了 `# type: ignore` / 触及契约面但已论证 / 等）

Anything reviewers should pay extra attention to:
