# 0002. 目标语言固定 zh 简体中文

* 状态：Accepted (BREAKING)
* 引入轮次：r52 C4
* 决策者：@Dean20030514
* 关联：[`_archive/EVOLUTION.md`](../../_archive/EVOLUTION.md) 阶段十一

## 背景

r35-r48 期间项目支持 4 个目标语言（zh / zh-tw / ja / ko），通过 5 层 code-level contract（`core/lang_config.py` + per-language prompts + alias-read + checker per-language + zh-tw 隔离）+ `--target-lang` CLI flag + multi-language outer loop 实现。

r52 用户用 `START.bat` 跑非中文 e2e（ja 流程）暴露真实大规模痛点：
- W1: `tl_mode.py` retry 单线程 + 零 progress logging（27000+ 残留 → 8-45h "卡死"）
- W2: LLM 偶发 JSON mis-escape（ja 多次触发 vs zh 0 次）
- W3: stage 3 fallback miss-rate 36% on ja vs 0.27% on zh
- W4: direct-mode 漏翻检测硬编码英文假设

ja 路径的 36% miss-rate 揭示 **multi-language contract 在大规模真实工作负载下根本不可靠**。

## 考虑的方案

1. **加固 ja 路径**：补 r53-style W1/W2/W3 优化让 ja 也达到 zh 的 99.991% 成功率（工作量大，且 multi-language 5 层 contract 本身脆弱）
2. **Soft retire**：保留 multi-language code 但 docs 警告"未充分测试"（用户继续踩坑）
3. **Hard retire (BREAKING)**：删多语言 contract，固定 zh 目标，源语言由 LLM 自动识别

## 决策

选择**方案 3** (Hard retire BREAKING)。

实施细节：
- 删 `core/lang_config.py`（5 层 contract / `LANGUAGE_CONFIGS` dict / `LanguageConfig` dataclass）
- 删 `--target-lang` CLI flag
- 删 multi-language outer loop（`for lang in args.target_langs: engine.run(args)`）
- 删 translation_db v2 schema（按语言分组的 entries）→ retire 到 v1 flat
- 删 runtime-hook v2 schema → retire 到 v1 flat
- 删 4 个 multi-language 测试文件
- 删 `tools/merge_translations_v2.py`
- hardcode `args.target_lang = "zh"` 在 `main.py:218`
- 加 `scripts/migrate_db_v2_to_v1.py` 给已有 v2 DB 用户迁移

净 -3781 行（37 文件 / +342 -4123）。

## 后果

正面：
- **显著简化 codebase**：5 层 contract → 0 层；multi-language outer loop → 单 zh 调用
- **r53 W1/W2/W3 优化的 ROI 翻倍**：所有改进集中在 zh 路径，不需要 cross-language testing
- **r52 实测 99.991%**：The Tyrant 74098 entries / 0.0013% drop / 129.4 min / $2.40 — 真实生产数据
- 给"减法 + 聚焦"时代定调（r53/r54/r56/r57 都延续此方向）

负面：
- 已有 v2 schema DB 用户必须迁移（提供脚本）
- 想翻译到 ja / ko / zh-tw 的用户失去支持（小众场景）

中立：
- 源语言不限（LLM 自动识别），所以非英文源 → zh 仍然支持

## 关联

* 关联 ADR：[0001 zero-deps](0001-zero-third-party-dependencies.md) / [0004 RenPy stays dedicated](0004-renpy-stays-on-dedicated-pipelines.md)
* 退役 ADR 项：r54 retire 8 项，其中 A-H-3 Medium/Deep 直接受本决策影响（zh-only 后通用化收益消失）
* 重新引入条件：必须先 plan-first 撤销本 ADR + 提供大规模真实测试数据证明 multi-language contract 可靠
