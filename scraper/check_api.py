# -*- coding: utf-8 -*-
"""
API 连通性自检
=============

在正式抓取前，先验证 config.json 里配置的多模态模型是否可用：
  - api_key 是否有效
  - model 名是否正确（venus 上 Gemini/GPT 等的具体名称可能不同）
  - 能否正常读图并返回文字

会临时生成一张带中文的测试图，发给模型识别，打印返回结果，然后删除测试图。

用法：
  python scraper/check_api.py
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import get_provider  # noqa: E402


def make_test_image() -> Path:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (700, 160), "white")
    d = ImageDraw.Draw(img)
    font = None
    for fp in ["/System/Library/Fonts/PingFang.ttc",
               "/System/Library/Fonts/STHeiti Medium.ttc"]:
        try:
            font = ImageFont.truetype(fp, 36)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    d.text((20, 30), "测试：RAG 检索增强生成", fill="black", font=font)
    d.text((20, 90), "向量数据库 + 重排序 rerank", fill="black", font=font)
    tmp = Path(tempfile.gettempdir()) / "_api_check.png"
    img.save(tmp)
    return tmp


def main():
    if not CONFIG_PATH.exists():
        print("未找到 config.json，请先 cp config.example.json config.json 并填写。")
        return
    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    iu = cfg.get("image_understanding", {})
    print(f"provider = {iu.get('provider')}")
    print(f"base_url = {iu.get('base_url')}")
    print(f"model    = {iu.get('model')}")

    if iu.get("provider") != "vlm":
        print("当前 provider 不是 vlm（多模态），无需检测 API。若要用大模型读图，请把 provider 改为 vlm。")
        return
    if "填你的" in (iu.get("api_key") or "") or not iu.get("api_key"):
        print("\n[!] 还没填 api_key，请先在 config.json 填入你的 venus API Key。")
        return

    try:
        provider = get_provider(cfg)
    except Exception as e:
        print(f"\n[X] 初始化失败：{e}")
        return

    tmp = make_test_image()
    print("\n正在调用模型识别测试图片...")
    result = provider.extract(tmp)
    try:
        tmp.unlink()
    except Exception:
        pass

    if result and result.strip():
        print("\n[OK] API 连通，模型成功返回内容：")
        print("-" * 50)
        print(result)
        print("-" * 50)
        print("\n配置正确，可以开始正式抓取了。")
    else:
        print("\n[X] 调用未返回有效内容。常见原因：")
        print("  1. model 名在 venus 上不叫这个 —— 试试 gemini-2.5-flash / gemini-1.5-flash / gemini-flash 等，改 config.json 重试")
        print("  2. api_key 无权限调用该模型 / 应用组未开通")
        print("  3. 该 model 其实不支持视觉（不能读图）")
        print("  4. 网络无法访问 venus 代理（确认在公司网络/VPN 内）")


if __name__ == "__main__":
    main()
