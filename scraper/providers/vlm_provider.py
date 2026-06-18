# -*- coding: utf-8 -*-
"""
多模态大模型（视觉）provider —— 兼容 OpenAI Chat Completions 接口
=============================================================

优先使用 openai 官方库（与公司 venus 代理文档示例一致），未安装则回退到 requests。
切换厂商只需改 config 的 base_url / model / api_key，无需改代码。

已支持的配置示例（填到 config.json 的 image_understanding 里）：

  公司 venus 代理（OpenAI 兼容）:
    base_url: http://v2.open.venus.oa.com/llmproxy
    model:    需选「支持视觉/多模态」的模型（见 README，纯文本模型无法读图）
    api_key:  你的 venus API Key（结合应用组使用）

  通义千问 Qwen-VL（阿里云百炼）:
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    model:    qwen-vl-max / qwen-vl-plus

  OpenAI GPT-4o:
    base_url: https://api.openai.com/v1
    model:    gpt-4o / gpt-4o-mini
"""

import base64
import mimetypes
import time
from pathlib import Path

from .base import ImageUnderstandingProvider


DEFAULT_PROMPT = (
    "这是一张小红书技术帖子里的图片，内容多为 AI/LLM/Agent 相关的知识干货。"
    "请准确提取图片中的所有文字内容；如果是图表、流程图或代码截图，"
    "请用简洁的文字描述其表达的关键信息和知识点。"
    "只输出图片里实际包含的内容，不要补充你自己的知识，不要臆测。"
    "直接输出提取/描述的正文，不要加任何开场白。"
)


class OpenAICompatVLMProvider(ImageUnderstandingProvider):
    def __init__(self, conf: dict):
        super().__init__(conf)
        self.base_url = (conf.get("base_url") or "").rstrip("/")
        self.model = conf.get("model") or ""
        self.api_key = conf.get("api_key") or ""
        self.prompt = conf.get("prompt") or DEFAULT_PROMPT
        self.timeout = int(conf.get("timeout", 60))
        self.max_retries = int(conf.get("max_retries", 2))
        self.retry_interval = float(conf.get("retry_interval", 3))
        self.detail = conf.get("detail", "high")

        if not self.base_url or not self.model or not self.api_key:
            raise ValueError(
                "使用 vlm provider 需在 config.json 的 image_understanding 中填写 "
                "base_url、model、api_key。详见 providers/vlm_provider.py 顶部示例。"
            )

        # 优先用 openai 官方库
        self._client = None
        try:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        except ImportError:
            self._client = None  # 回退 requests

    def _encode_image(self, image_path: Path) -> str:
        """把本地图片转成 base64 的 data URL，这样能直接塞进 API 请求里发给模型。"""
        mime, _ = mimetypes.guess_type(str(image_path))
        mime = mime or "image/jpeg"
        b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    def _messages(self, data_url: str):
        """拼装多模态对话消息：一段文字指令 + 一张图片。这是 OpenAI 视觉接口的标准格式。"""
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self.prompt},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": self.detail}},
                ],
            }
        ]

    def _call_openai(self, data_url: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=self._messages(data_url),
            temperature=0,
            timeout=self.timeout,
        )
        return (resp.choices[0].message.content or "").strip()

    def _call_requests(self, data_url: str) -> str:
        import requests
        payload = {
            "model": self.model,
            "messages": self._messages(data_url),
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()

    def extract(self, image_path: Path) -> str:
        """对外统一入口：输入一张图片，返回模型识别/描述出的文字。"""
        try:
            data_url = self._encode_image(image_path)
        except Exception as e:
            print(f"    [VLM 读图失败] {image_path.name}: {e}")
            return ""

        # 带重试地调用模型：优先用 openai 官方库，没装则用 requests 兜底；
        # 失败会重试 max_retries 次，最终仍失败返回空字符串（不打断整体批处理）。
        for attempt in range(self.max_retries + 1):
            try:
                if self._client is not None:
                    return self._call_openai(data_url)
                return self._call_requests(data_url)
            except Exception as e:
                print(f"    [VLM 请求异常] {image_path.name} (第{attempt+1}次): {str(e)[:160]}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_interval)
        return ""
