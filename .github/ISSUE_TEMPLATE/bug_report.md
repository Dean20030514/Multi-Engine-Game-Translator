---
name: Bug 报告 / Bug report
about: 报告项目中的 bug 或异常行为 / Report a bug or unexpected behavior
title: "[BUG] "
labels: bug
assignees: ''
---

> 中文 / English 都可以；信息越具体我们越能复现。

## 描述 / Description

描述遇到的问题。
Describe what happened.

## 复现步骤 / Reproduce

```bash
# 你跑的命令（脱敏 API key）/ The command you ran (redact API key)
python main.py --game-dir <path> --provider xai --api-key sk-XXX ...
```

## 期望行为 / Expected

期望发生什么。
What you expected to happen.

## 实际行为 / Actual

实际发生了什么 + 完整错误信息 / Actual behaviour + full error output:

```text
（粘贴错误日志，脱敏路径如有需要 / Paste error log, redact paths if needed）
```

## 环境 / Environment

- OS: <Windows 11 / Linux / macOS>
- Python 版本 / Python version: <`python --version`>
- 项目轮次 / Project round: <`git log --oneline -1` 的第一行>
- 引擎 / Engine: <renpy / rpgmaker / csv / unity / ...>
- LLM provider: <xai / openai / deepseek / claude / gemini / custom>

## 附件 / Attachments

- [ ] 完整错误日志 / Full error log（如能够脱敏后附上 / If you can redact and attach）
- [ ] 触发问题的最小 fixture / Minimal reproducer fixture（如能构造 / If feasible）
- [ ] `output/translation_db.json` 片段 / Snippet of translation_db
- [ ] 截图 / Screenshot（仅 GUI 问题 / GUI issues only）

## 已尝试 / Tried

- [ ] 看了 [`HANDOFF.md`](../../HANDOFF.md) 当前状态
- [ ] 看了 [`docs/REFERENCE.md`](../../docs/REFERENCE.md) 错误码索引（W4xx / E2xx 等）
- [ ] 跑过 `python tests/test_all.py` 确认本地测试通过
- [ ] 升级到最新 `git pull` 仍能复现
