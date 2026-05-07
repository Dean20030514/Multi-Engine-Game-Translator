# Release Process

> **状态**：r58 P2 引入手动流程；**r59 B1 加自动化** — `.github/workflows/release.yml` on `v*` tag push 触发 PyInstaller × 3 OS matrix + 上传 draft Release。本文同时保留手动 fallback 流程（自动化 fail 时可走）。

## 版本号管理

`pyproject.toml::version` 是 single source of truth：

```toml
[project]
version = "2.0.0"
```

遵循 [SemVer](https://semver.org/lang/zh-CN/)：

| 增量 | 含义 | 示例触发 |
|------|------|---------|
| MAJOR | BREAKING 变更 | r52 C4 retire 多目标语言 / r52 C3 retire importlib plugin / r57 T1 Python 3.10 floor |
| MINOR | 新功能（向后兼容）| r55 Unity XUnity 引擎接入 |
| PATCH | bugfix + 优化（向后兼容）| r56 audit fix 路径 / r57 mypy enforce |

**当前版本与轮次的对应关系**：版本号不严格跟轮次走（r1-r60 期间版本仅升过 2 次）；建议在用户面 BREAKING 时升 MAJOR，新功能升 MINOR，纯重构 / docs 不动版本号。

**版本演进**：
- v1.0.0（项目初始）— Ren'Py + RPG Maker MV-MZ 多语言支持
- **v2.0.0（r62 B2）** — 反映 r52 C4 BREAKING（multi-target language retire）+ r52 C3 BREAKING（importlib plugin retire）+ r57 T1 BREAKING（Python 3.10 floor）累积；同时新增 Unity XUnity 引擎（r55）+ release 自动化（r59 B1）+ 21 轮 0 CRITICAL streak（r35-r61）实证 production maturity

## 发布流程（手动）

### 1. Pre-release 检查

```bash
# 确保 working tree clean
git status

# 全量回归
python tests/test_all.py

# verify_docs_claims 全过
python scripts/verify_docs_claims.py --fast
python scripts/verify_docs_claims.py --full   # 跑完整 CI sanity gate

# pre-commit hook 4 件套（用 dummy commit 验证）
git commit --allow-empty -m "test: dry-run pre-commit"
git reset --soft HEAD~1   # undo dummy commit if all passed
```

### 2. 升版本号

```bash
# 编辑 pyproject.toml::version
# 例如 2.0.0 → 2.1.0 (新功能) / 2.0.1 (bugfix) / 3.0.0 (BREAKING)
```

提交版本号 bump：

```bash
git add pyproject.toml
git commit -m "chore: bump version to vX.Y.Z"
```

### 3. 打标签 + push

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z

Highlights:
- ...
- ...

Full changelog: see CHANGELOG.md
"

git push origin main
git push origin vX.Y.Z
```

### 4. PyInstaller 打包

```bash
python build.py
```

产物：`dist/多引擎游戏汉化工具.exe`（Windows）/ `dist/MultiEngineTranslator`（Linux/macOS）。

**注意**：PyInstaller 打包仅在打包者本地的 Python + 操作系统下产出对应平台 binary。跨平台需在对应 OS 各打一次。

### 5. 创建 GitHub Release

通过 GitHub Web UI 或 `gh` CLI：

```bash
gh release create vX.Y.Z \
    --title "vX.Y.Z" \
    --notes-file - \
    dist/多引擎游戏汉化工具.exe \
    <<EOF
## 主要更新

（从 CHANGELOG.md 摘录）

## 测试覆盖

测试数 / 文件数 / 断言点：见 HANDOFF.md VERIFIED-CLAIMS 块（提交时刻）

## 校验

- SHA256: \$(sha256sum dist/多引擎游戏汉化工具.exe)

EOF
```

### 6. 验证 release artifact

下载 release `.exe` + 跑一遍 dry-run：

```bash
./多引擎游戏汉化工具.exe --help
./多引擎游戏汉化工具.exe --game-dir <some-game> --dry-run
```

## 自动化（r59 B1 已实现）

[`.github/workflows/release.yml`](.github/workflows/release.yml) 自动跑：

- 触发条件 `on: push: tags: ['v*']`
- matrix `[ubuntu-latest, windows-latest, macos-latest]`
- 每个 OS 跑 `python tests/test_all.py` + `python scripts/verify_docs_claims.py --fast` 作 pre-build gate
- `pip install pyinstaller` + `python build.py` 生成 binary
- `actions/upload-artifact@v4` 上传 per-OS artifact
- `softprops/action-gh-release@v2` 创建 **draft** Release（maintainer review 后手动 publish），含：
  * 3 个 OS binary（按 OS 后缀重命名）
  * `SHA256SUMS.txt`（每个 binary 的 sha256 摘要）
  * 自动从 `CHANGELOG.md` 抽取最近一轮 highlights 作为 release notes
  * `prerelease: true` 当 tag 含 `-`（如 `v2.0.0-beta`）

**零依赖契约保持**：PyInstaller 是 dev / build-time 依赖，不算 runtime 依赖（[ADR 0001](docs/adr/0001-zero-third-party-dependencies.md)）。运行 `python build.py` 期间 pip install 的 PyInstaller 不污染 runtime artifact。

### Manual fallback

如果 GitHub Actions 中断或自动化 fail，走上文"发布流程（手动）"5 步。

## 发布后

- 更新 [`HANDOFF.md`](HANDOFF.md) "同步状态"段反映 push + release 完成
- 更新 [`CHANGELOG.md`](CHANGELOG.md) 加 release 段（区别于 round 段）
- 通知用户（issue / discussion / 项目主页 README）
