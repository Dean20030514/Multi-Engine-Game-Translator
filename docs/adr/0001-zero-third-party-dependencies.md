# 0001. 零第三方依赖契约

* 状态：Accepted
* 引入轮次：r1（项目起始）
* 决策者：@Dean20030514
* 关联：CLAUDE.md "10 大开发原则" 第 9 条

## 背景

Ren'Py / RPG Maker 翻译工具的目标用户多数是非 Python 开发者：游戏汉化爱好者、Mod 作者。要求他们 `pip install` 一堆依赖会显著抬高使用门槛。同时，将工具作为 PyInstaller 单文件 .exe 分发时，依赖树越大产物越大、跨平台越脆弱。

## 考虑的方案

1. **零第三方依赖**：仅用 Python 标准库（`urllib` / `json` / `pickle` / `subprocess` / `pathlib` / `re` / `concurrent.futures` / 等）
2. **最小核心依赖**：允许 `requests` / `httpx` 等 HTTP 库 + `pyyaml` 等格式库
3. **完整依赖（pip-managed）**：用 `requirements.txt` + venv 管理

## 决策

选择**方案 1**：零第三方依赖（runtime）。

实施细节：
- `pyproject.toml::dependencies = []`（始终空）
- HTTPS 用 `urllib.request` + 自实现 thread-local connection pool（`core/http_pool.py`，节省 ~90s / 600 次调用）
- JSON 解析用 `json` 标准库 + 6 级降级链（r53 W2 加 layer 7 escape repair）
- pickle 用 `pickle` + 白名单 SafeUnpickler（`core/pickle_safe.py`，r53 红队 8/8 verified）
- 子进程沙箱用 `subprocess.Popen` + JSONL 协议（r52 C3 唯一 plugin 模式）
- TOCTOU 防御用 `os.fstat` + 自实现 helper（`safety/file_safety.py`）
- CI 跑 mypy / ruff 是 dev / build-time 依赖，**不算 runtime 依赖**

## 后果

正面：
- PyInstaller 产物 ~10 MB（vs 含 requests + cryptography 等的 ~50 MB）
- 用户面 `python main.py` 直接跑（无 venv 步骤）
- 攻击面小（标准库经过严格审计；第三方依赖 CVE 风险被根本规避）
- 跨平台跑通成本低（standard library 是 Python 自身保证）

负面：
- 部分功能要从头实现（HTTP 连接池 / pickle 白名单 / JSONL plugin protocol）
- 单元测试 fixture 需要 mock 标准库（如 mock `urllib.request.urlopen`）
- 性能不如优化的第三方库（如 `requests` 的 connection pool）
- 某些复杂特性放弃（如 RPG Maker VX/Ace 需 `rubymarshal`，r54 retire）

中立：
- 部分能力通过外部工具间接覆盖（如 Wolf RPG Editor 走 WolfTrans → CSVEngine）

## 关联

* 关联 ADR：[0002 zh-only target](0002-zh-only-target-language.md) / [0003 subprocess plugin](0003-subprocess-sandbox-only-plugin.md)
* CI 验证：`.github/workflows/test.yml::Verify zero third-party dependencies` step
* 退役决策：r54 retire RPG Maker VX/Ace（需 `rubymarshal`，违反本契约）
