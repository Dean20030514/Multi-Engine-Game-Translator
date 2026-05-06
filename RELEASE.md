# Release Process

> **状态**：r58 P2 引入；当前为**手动流程**（PyInstaller 打包 + GitHub Release 上传）。未来如需自动化（GitHub Actions tag-trigger workflow），见本文末"自动化候选"段。

## 版本号管理

`pyproject.toml::version` 是 single source of truth：

```toml
[project]
version = "1.0.0"
```

遵循 [SemVer](https://semver.org/lang/zh-CN/)：

| 增量 | 含义 | 示例触发 |
|------|------|---------|
| MAJOR | BREAKING 变更 | r52 C4 retire 多目标语言 / r52 C3 retire importlib plugin |
| MINOR | 新功能（向后兼容）| r55 Unity XUnity 引擎接入 |
| PATCH | bugfix + 优化（向后兼容）| r56 audit fix 路径 / r57 mypy enforce |

**当前版本与轮次的对应关系**：版本号不严格跟轮次走（r1-r57 期间版本仅升过 1 次）；建议在用户面 BREAKING 时升 MAJOR，新功能升 MINOR，纯重构 / docs 不动版本号。

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
# 例如 1.0.0 → 1.1.0 (新功能) / 1.0.1 (bugfix) / 2.0.0 (BREAKING)
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

## 自动化候选（r58+ backlog）

当前 release 流程是手动；自动化候选见 [`AUDIT_R57.md`](AUDIT_R57.md) §B1：

> 加 GitHub Actions workflow on tag push → PyInstaller → 上传 .exe 到 Release。一次性投入 ~50 行 workflow yaml。

**实现要点**（如未来推进）：
- `.github/workflows/release.yml` 触发条件 `on: push: tags: ['v*']`
- matrix `[ubuntu-latest, windows-latest, macos-latest]`
- 每个 OS 装 PyInstaller + 跑 `python build.py`
- 上传 artifact 到 `actions/upload-artifact@v4`
- 全部 OS done 后 `softprops/action-gh-release@v2` 创建 Release + attach 所有 OS binary
- **零依赖契约**：PyInstaller 是 dev / build-time dependency，不算 runtime 依赖（CLAUDE.md 第 9 原则）

## 发布后

- 更新 [`HANDOFF.md`](HANDOFF.md) "同步状态"段反映 push + release 完成
- 更新 [`CHANGELOG.md`](CHANGELOG.md) 加 release 段（区别于 round 段）
- 通知用户（issue / discussion / 项目主页 README）
