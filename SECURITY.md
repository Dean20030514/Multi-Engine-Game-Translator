# Security Policy / 安全策略

## Threat Model / 威胁模型

**English** — Local single-user translation tool. Runs on user's own machine, loads game files the user chose, talks to remote LLM APIs with user-provided API keys.

- **Trusted**: user's own filesystem, user-supplied API key, user-configured LLM endpoints, plugins under `custom_engines/` written by the user
- **Untrusted**: game archive contents (`.rpa`, `.rpyc`), game scripts (`.rpy`), LLM-returned translation payloads, file paths embedded in any of the above

Loading a malicious RPA / rpyc archive **must not** lead to arbitrary code execution or write files outside the output directory.

**中文** — 本项目是**本地单用户**翻译工具，运行在用户机器上，加载用户选定的游戏文件，用用户提供的 API Key 调用远程 LLM。

- **可信**：用户自己的文件系统、用户提供的 API Key、用户明确配置的 LLM endpoint、用户自己放在 `custom_engines/` 下的插件
- **不可信**：游戏档案（`.rpa`、`.rpyc`）、游戏脚本（`.rpy`）、LLM 返回的翻译内容、以及这些数据中嵌入的任何文件路径

加载来源不明的 RPA 或 rpyc 档案**绝不能**导致任意代码执行或写入 outdir 之外。

## Reporting / 漏洞报告

**Privately**, not via public issues / 请通过**私密渠道**报告，不要直接开公开 issue：

- Preferred / 推荐：GitHub Security Advisories（Private Vulnerability Reporting）
- Alternative / 替代：邮件维护者，主题 `[SECURITY] <短标题>`
- 在问题修复前请**不要公开披露**

报告请包含 / Include:

1. 受影响文件 + 行号 / Affected file(s) + line number(s)
2. 攻击前提 / Attack prerequisites
3. 最小化 PoC（仅复现，**不要**带武器化载荷） / Minimal PoC (reproduction only, no weaponised payload)
4. 建议缓解（可选） / Suggested mitigation (optional)
5. 公告署名（可选） / Preferred credit name (optional)

**响应时间承诺 / Response time**：
- 7 天内确认收到 / Acknowledge within 7 days
- 14 天内初步评估 / Initial assessment within 14 days
- 90 天内完成修复与协调披露 / Fix + coordinated disclosure within 90 days

## Hardening Applied / 已实施的加固

| 防御 | 位置 | 防御目标 |
|------|------|---------|
| `SafeUnpickler` 白名单 | `core/pickle_safe.py` | 禁 `pickle.loads` 任意 RCE |
| RPA index 反序列化 | `tools/rpa_unpacker.py` | 同上，refuses unknown classes |
| RPA 解包路径校验 | `tools/rpa_unpacker.unpack_rpa` | ZIP-Slip 防护 |
| Tier 2 rpyc 加载 | `tools/rpyc_decompiler._RestrictedUnpickler` | 白名单 + renpy/store 类映射到无害 stub |
| Tier 1 rpyc 子进程 | `_DECOMPILE_HELPER_SCRIPT` | 内联 `_SafeUnpickler` 防游戏自带 Python 内 RCE |
| Plugin sandbox | `core/api_plugin._SubprocessPluginClient` | **强制 subprocess + JSONL 隔离**（r52 BREAKING：不再支持 importlib in-process loader） |
| Plugin stdout cap | 50M chars | DoS 防御（CJK 响应最坏 ~150 MB） |
| Plugin stderr cap | 10 KB chars | 防 OOM crash-diag |
| HTTPS 响应体上限 | `core/http_pool.py` `MAX_API_RESPONSE_BYTES = 32 MB` | 防被劫持 endpoint 流式无限数据 |
| TOCTOU 二次校验 | `safety/file_safety.check_fstat_size` | 26 sites / 12 modules 全 MITIGATED |
| OOM 防护 | 23/23 user-facing JSON loader 50 MB cap | 巨型 JSON 内存炸 |
| `api_key_file` 路径校验 | `core/config.py` | 拒绝指向敏感目录 + 8 KB 上限 |

## Known Constraints / 已知限制

- **Custom plugins** (`custom_engines/`) — round 52 起强制 subprocess 沙箱（denies plugin 直接访问 host env vars / file descriptors / heap）；plugin 必须实现 `_plugin_serve()` JSONL 协议
- **Tier 1 rpyc decompilation** 启动游戏自带 Python 子进程，子进程继承父进程环境变量
- **LLM translation output** 经过校验但未沙箱化；理论上恶意 provider 可构造绕过校验但语法合法的脚本
- **PyInstaller exe** 未代码签名，Windows SmartScreen 首次运行可能告警

## Scope / 范围

This policy covers Python source code in this repository. **Not** covered: upstream dependencies (none — pure stdlib), Ren'Py runtime, LLM provider APIs, user OS.

本策略覆盖本仓库 Python 源代码。**不覆盖**上游依赖（本项目零依赖）、Ren'Py 运行时、LLM 提供商 API、用户操作系统。
