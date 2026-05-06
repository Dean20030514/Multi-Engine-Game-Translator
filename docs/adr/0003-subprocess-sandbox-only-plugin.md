# 0003. Custom plugin 强制 subprocess sandbox

* 状态：Accepted (BREAKING)
* 引入轮次：r52 C3
* 决策者：@Dean20030514
* 关联：[`_archive/EVOLUTION.md`](../../_archive/EVOLUTION.md) 阶段十一 + [`custom_engines/example_echo.py`](../../custom_engines/example_echo.py)

## 背景

r35-r51 期间 custom plugin (`--provider custom --custom-module my_engine`) 支持两种加载模式：
1. **importlib in-process**（默认）：`importlib.import_module(name)` 直接加载到主进程
2. **Subprocess sandbox**（opt-in `--sandbox-plugin`）：派生子进程通过 JSONL 通信

importlib 模式问题：
- Plugin 代码与主进程共享内存空间 → 崩溃 / 内存泄漏 / OOM 风险传染
- 恶意 plugin 可以读 `os.environ`（含 API key）/ 调用 `os.system` / 访问主进程任意对象
- 调试痛点（plugin 崩溃 traceback 不清晰）

实际用户场景中 plugin 都是用户自己写的（`custom_engines/` 目录），但**用户共享 plugin 给他人时**（git fork / 论坛分享），接收方等于在主进程跑陌生代码，是真实安全风险。

## 考虑的方案

1. **保留 dual-mode**：默认 importlib + opt-in subprocess（现状）
2. **默认 subprocess + opt-in importlib**：仍保留 importlib 给信任 plugin 用
3. **Hard retire importlib**：subprocess sandbox 成唯一模式

## 决策

选择**方案 3** (Hard retire BREAKING)。

实施细节：
- 删 `core/api_plugin.py::_load_custom_engine` (65 行) — importlib 加载入口
- 删 `APIConfig.sandbox_plugin: bool = False` field
- 删 `--sandbox-plugin` CLI flag
- 删 6 处 caller 的 `sandbox_plugin=...` kwarg
- 强制所有 `provider="custom"` 走 `_SubprocessPluginClient`
- 加**启动期 readiness probe**：5×20ms poll catch missing `--plugin-serve` block（plugin 必须实现这个 entry，否则 init 阶段报错而非运行时神秘卡死）
- Plugin 必须实现 `_plugin_serve()` 处理 `--plugin-serve` 参数
- Migration guide 见 `custom_engines/example_echo.py`（reference 实现）

## 后果

正面：
- **三通道防护**：stdout 50M chars per-line cap / stderr 10K read tail-600 chars / stdin lifecycle 控制
- 主进程 OOM / 崩溃 / 安全风险隔离
- Plugin 输出可独立 audit（JSONL 协议透明）
- 启动期 readiness probe 让 plugin bug 在 init 阶段就报错（debug 友好）

负面：
- BREAKING：所有 r51 之前的 plugin 必须改写实现 `_plugin_serve()`
- subprocess 通信开销（每次调用 ~1-2ms 序列化）— 实测 r52 zh path 影响 < 0.1%
- Plugin 不能再 share 主进程 state（必须自己 maintain state）

中立：
- Plugin 调试需要看 stderr（subprocess 写入），但 `core/api_plugin.py` 已自动 tail-600 chars 显示

## 关联

* 关联 ADR：[0001 zero-deps](0001-zero-third-party-dependencies.md)（subprocess 是标准库，符合契约）
* CI 验证：`tests/test_custom_engine.py` + `tests/test_sandbox_response_cap.py`
* 重新引入条件：必须先 plan-first 撤销本 ADR + 提供量化数据证明 importlib 模式比 subprocess 更安全 / 更高效
