# -*- coding: utf-8 -*-
"""
图片理解 Provider 抽象层
======================

把「一张图片 -> 文字 / 知识点」这个能力做成可插拔的 provider，便于自由切换：
  - "rapidocr"：本地免费 OCR（默认，零成本，但对花字/复杂排版效果一般）
  - "vlm"     ：多模态大模型视觉理解（效果好，按量付费，兼容 OpenAI 接口，可切换厂商）

通过 config.json 的 image_understanding.provider 选择。
新增厂商时：若该厂商兼容 OpenAI 接口，直接改 config 的 base_url/model 即可，无需改代码。
"""

from .base import ImageUnderstandingProvider


def get_provider(cfg: dict) -> "ImageUnderstandingProvider":
    """
    工厂函数：根据 config.json 里 image_understanding.provider 字段，
    返回对应的「图片理解引擎」实例。上层代码无需关心具体用哪个引擎，
    换引擎只改配置即可。想新增引擎就在下面加一个分支 + 实现对应类。
    """
    iu = (cfg or {}).get("image_understanding", {}) or {}
    name = (iu.get("provider") or "rapidocr").lower()  # 默认本地免费 OCR

    if name == "rapidocr":
        # 引擎1：本地免费 OCR
        from .rapidocr_provider import RapidOcrProvider
        return RapidOcrProvider(iu)
    elif name in ("vlm", "openai", "qwen", "doubao", "gpt4o"):
        # 引擎2：多模态大模型读图。兼容 OpenAI 接口的厂商共用这一实现，
        # 靠 config 的 base_url/model 区分，无需为每家单独写代码。
        from .vlm_provider import OpenAICompatVLMProvider
        return OpenAICompatVLMProvider(iu)
    else:
        raise ValueError(
            f"未知的 image_understanding.provider: {name!r}。"
            f"可选：rapidocr / vlm"
        )
