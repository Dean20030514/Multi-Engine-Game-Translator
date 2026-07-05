# Game Translator（多引擎游戏翻译工具）

> 本仓库是**发布库**：提供打包好的可执行程序与使用文档。**源代码不在此处。**

把没有官方中文的游戏，借助大语言模型（LLM）自动翻译成简体中文。工具理解游戏引擎的语义（Ren'Py 的 `tl/` 槽位、占位符冻结、字体方块、say 文法等），目标是**让译文在游戏内正确显示，且不破坏游戏**。

## 支持的引擎

目前支持 **13 个游戏引擎**（Ren'Py 为一等公民；其余按覆盖范围与真机验证程度不同，部分标注为实验性）。

**一等公民**

- **Ren'Py**：解包（`.rpa`）/ 反编译（`.rpyc`）/ `tl/` 槽位生成 / 中文字体注入 / 语言切换器 / 打成可分发补丁

**通用商业引擎**

- **RPG Maker MV / MZ**：加载期按值替换的运行时翻译插件
- **RPG Maker XP / VX / VX Ace**（RGSS）：解包 RGSSAD 归档、就地重写 `Data/` 脚本（XP/VX 为 Shift-JIS，简体显示受限）
- **Unity**（XUnity AutoTranslator）：文本翻译 + 引擎版本探测 + 版本特定的 CJK 字体引导
- **Godot 3 / 4**：向明文 `.tscn` 场景追加 gettext `.po` 译文并注册（需在编辑器重导入一次）
- **Wolf RPG Editor（ウディタ）**：地图 / 公共事件 / 数据库文本回写 + 中文字体注入

**日系视觉小说脚本引擎**

- **NScripter / ONScripter**：脚本解码，追加 / 就地回写（简体渲染需 UTF-8 / CJK 构建，实验性）
- **KiriKiri / KAG**：生成 `patch.xp3` 补丁自动挂载（明文 xp3，绝不改动源文件）
- **TyranoScript / TyranoBuilder**：就地改写 `.ks` 脚本
- **BGI / Ethornell**（Buriko）：DSC 编译脚本解压 + append-and-repoint 回写（实验性；已在一款真实游戏内可视验证简体渲染）
- **Artemis Engine**：`.ast` 对白 + `.tbl` UI 文本 span 精确回写（实验性；`.ast` / `.tbl` 游戏内简体渲染均已真机可视验证）
- **Majiro Script Engine**：MajiroObj 字节码反汇编 + 重打包（实验性；引擎回写正确性已真机实证，游戏内简体显示需非 UTF-8 的 locale 环境）

**通用表格**

- **CSV / JSONL**：通用表格文本（opt-in，不参与自动检测）

## 下载

前往 [Releases](../../releases) 页下载最新版（含单文件 `gt.exe` 与使用说明）。单文件双击即用，免装 Python、免 Ren'Py SDK。

- **最新版**：[v0.3.0](../../releases/latest)（`GameTranslator-v0.3.0.zip`）
- **校验完整性**：下载后与同名 `.sha256` 比对——PowerShell：`certutil -hashfile GameTranslator-v0.3.0.zip SHA256`；解压后单文件 `gt.exe` 的哈希见包内 `checksums.txt`。
- 杀软对单文件打包的 exe 常有误报，可用上述校验自行确认完整性。

## 设计取舍

- **宁可漏翻不误翻**：校验不过的译文会被丢弃、保留原文。
- **谨慎对待游戏文件**：回写前强制 `.bak` 备份，事务式写入、失败回滚。
- **自带 LLM API key**：调用成本由用户承担；支持本地 provider（费用为 0）。

## 使用条款

仅供学习与个人使用。请遵守目标游戏的版权与使用条款；本工具不对加密内容做解密。

---

_本库为 v2 重写版的发布渠道。旧版（v1）的完整源码与提交历史保留在 [`v1-archive`](../../tree/v1-archive) 分支。_
