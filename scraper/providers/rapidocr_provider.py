# -*- coding: utf-8 -*-
"""本地免费 OCR provider（rapidocr_onnxruntime）。"""

from pathlib import Path

from .base import ImageUnderstandingProvider


class RapidOcrProvider(ImageUnderstandingProvider):
    """
    纯本地、免费、离线的 OCR。
    原理：DBNet 文本检测 + CRNN 文本识别（PP-OCR 模型转 ONNX）。
    适合白底黑字的干货截图；对花字 / 复杂背景 / 手写体效果一般。
    """

    def __init__(self, conf: dict):
        super().__init__(conf)
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise ImportError(
                "缺少 rapidocr_onnxruntime，请执行：pip install -r requirements.txt"
            )
        # 置信度阈值，低于此分数的识别结果丢弃
        self.min_score = float(conf.get("min_score", 0.5))
        self.engine = RapidOCR()

    def extract(self, image_path: Path) -> str:
        try:
            result, _ = self.engine(str(image_path))
            if not result:
                return ""
            lines = []
            for item in result:
                # item 结构: [box, text, score]
                text = (item[1] or "").strip()
                score = item[2] if len(item) > 2 else 1.0
                if text and score and score > self.min_score and len(text) >= 2:
                    lines.append(text)
            return "\n".join(lines)
        except Exception as e:
            print(f"    [RapidOCR 失败] {image_path.name}: {e}")
            return ""
