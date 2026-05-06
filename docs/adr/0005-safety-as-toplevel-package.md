# 0005. `safety/` 顶层独立 package（从 `core/` 移出）

* 状态：Accepted
* 引入轮次：r56 M2
* 决策者：@Dean20030514
* 关联：[`HANDOFF.md`](../../HANDOFF.md) "Round 56 完成" 段

## 背景

r49 推广 TOCTOU 防御 helper `check_fstat_size`，从 `engines/csv_engine.py` inline 抽取到 `core/file_safety.py`，让 22+ user-facing JSON loaders 共享。

但 `file_processor/checker.py:12` 顶层 `from core.file_safety import check_fstat_size` 与 CLAUDE.md 模块图描述"`file_processor` 不在 module load 时 import `core`"冲突。

r56 audit M2 finding：
- 没有循环依赖（`core.file_safety` 是叶子模块，无副作用）
- 但 docs vs code 不一致 → 流程债

## 考虑的方案

1. **修 docs**（保持 `core/file_safety.py` 不动）：把"file_processor 不 import core"改为"file_processor 可以 import core.file_safety"
2. **移到顶层 `safety/` package**：layering 清晰；r48 mock target consistency CI guard 用 fragment match `grep -v "file_safety"` 兼容两种路径，无需改 CI
3. **改名 `_layered_safety`** 内联回 `file_processor/`：还原 r49 之前状态

## 决策

选择**方案 2**：移到顶层 `safety/` package。

实施：
- `core/file_safety.py` → `safety/file_safety.py` (`git mv`，保留 100% 内容)
- 新建 `safety/__init__.py` re-export `check_fstat_size`
- 18 production .py 顶层 import 路径迁移（`from core.file_safety import` → `from safety.file_safety import`）
- 3 测试 mock target 迁移（`mock.patch("core.file_safety.os.fstat")` → `mock.patch("safety.file_safety.os.fstat")`）
- CI workflow `Mock target consistency check` step 文档更新（fragment match 兼容；r48 stale mock trap CLASS guard 仍生效）
- CLAUDE.md 模块图调整：`safety/` 现作为 sibling package 与 `core/` / `file_processor/` / `engines/` 平级
- `tests/test_repo_rename_consistency.py` 文档字符串同步说明 r56 M2 移位

## 后果

正面：
- **Layering 清晰**：`safety/` 是 cross-cutting helper layer，不属于任何特定 domain（`core/` 是 LLM API 层，`file_processor/` 是 .rpy 文本处理层）
- 修复 docs vs code drift（r56 audit M2）
- 未来 cross-cutting helper（如 input validation / sandbox）有自然归处

负面：
- 18 文件的 import 行变更（一次性 cost）
- r51 contract test 文档字符串更新（轻微）

中立：
- r48 stale mock trap CLASS guard 用 fragment match `grep -v "file_safety"`，**无需改 CI guard 逻辑**——两种路径都过滤

## 关联

* 关联 r48 audit：mock target stale trap CLASS（`engines.csv_engine.os.fstat` vs `core.file_safety.os.fstat`），r48 Step 3 CRITICAL fix
* 关联 r50 C4 audit-tail：filter 从 `core\.file_safety` 放宽到 `file_safety` 兼容 qualified form
* 关联 r51 audit-tail：第三级 filter `grep -v "test_repo_rename_consistency"` 豁免 documentation-only file
* 重新引入条件：如未来发现 `safety/` package 反而引入 layering 复杂度（如循环依赖 / 测试 mock 困难），可考虑改回 `core/file_safety.py` + 修 docs 描述
