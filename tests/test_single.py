#!/usr/bin/env python3
"""单文件测试 — 验证整文件翻译流程"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.api_client import APIClient, APIConfig
from file_processor import apply_translations, validate_translation, read_file, estimate_tokens
from core.glossary import Glossary
from core.prompts import build_system_prompt, build_user_prompt

GAME_DIR = Path(
    os.environ.get(
        "TEST_GAME_DIR", r"E:\浏览器下载\TheTyrant-0.9.4b.with.Official.SAZmod-pc-compressed\game"
    )
)
TEST_FILE = GAME_DIR / "tutorial.rpy"


def main():
    # 从环境变量或命令行获取 API key
    api_key = os.environ.get("XAI_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not api_key:
        api_key = input("请输入 xAI API Key: ").strip()
    if not api_key:
        print("错误: 需要 API Key")
        sys.exit(1)

    # 1. 读取文件
    content = read_file(TEST_FILE)
    tokens = estimate_tokens(content)
    print(f"文件: {TEST_FILE.name}")
    print(f"Token: {tokens}")
    print()

    # 2. 构建术语表
    glossary = Glossary()
    glossary.scan_game_directory(str(GAME_DIR))
    print(f"角色: {glossary.characters}")
    print()

    # 3. 构建 prompt
    system_prompt = build_system_prompt(genre="adult", glossary_text=glossary.to_prompt_text())
    user_prompt = build_user_prompt("tutorial.rpy", content)
    print(f"System prompt 长度: {len(system_prompt)} 字符")
    print(f"User prompt 长度: {len(user_prompt)} 字符")
    print()

    # 4. 调用 API
    config = APIConfig(
        provider="xai",
        api_key=api_key,
        model="grok-3-fast",
        rpm=60,
        rps=5,
        timeout=120,
    )
    client = APIClient(config)

    print("调用 API...")
    translations = client.translate(system_prompt, user_prompt)
    print(f"获得 {len(translations)} 条翻译:")
    print()
    for t in translations:
        print(f'  行 {t.get("line", "?"):3d}: "{t.get("original", "")}"')
        print(f'      → "{t.get("zh", "")}"')
    print()

    # 5. 应用翻译
    patched, warnings, _ = apply_translations(content, translations)
    if warnings:
        print("警告:")
        for w in warnings:
            print(f"  {w}")
        print()

    # 6. 校验
    issues = validate_translation(content, patched, "tutorial.rpy")
    if issues:
        print("校验问题:")
        for i in issues:
            print(f"  [{i['level']}] 行 {i['line']}: {i['message']}")
        print()

    # 7. 显示翻译结果
    print("=" * 60)
    print("翻译后文件:")
    print("=" * 60)
    print(patched)

    # 8. 保存
    out = Path("test_output/tutorial.rpy")
    out.parent.mkdir(exist_ok=True)
    out.write_text(patched, encoding="utf-8")
    print(f"\n已保存到: {out}")


if __name__ == "__main__":
    main()
