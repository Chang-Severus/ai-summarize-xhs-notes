# -*- coding: utf-8 -*-
"""
文本大模型 provider —— 用于知识点总结（兼容 OpenAI Chat Completions 接口）
====================================================================

与图片理解的 vlm_provider 同源，但只做纯文本对话（提炼/去重/归类）。
优先使用 openai 官方库，未安装则回退 requests。

切换总结模型只需改 config.json 的 summarization.base_url / model / api_key。
推荐 Claude（Sonnet 档）做总结；也可用 GPT / Gemini Pro / 国内顶配模型。
"""

import time

from .base import ImageUnderstandingProvider


class TextLLMProvider(ImageUnderstandingProvider):
    """复用基类壳子（conf 存取一致）；对外提供 chat() 方法做纯文本对话。"""

    def __init__(self, conf: dict):
        super().__init__(conf)
        self.base_url = (conf.get("base_url") or "").rstrip("/")
        self.model = conf.get("model") or ""
        self.api_key = conf.get("api_key") or ""
        self.timeout = int(conf.get("timeout", 120))
        self.max_retries = int(conf.get("max_retries", 2))
        self.retry_interval = float(conf.get("retry_interval", 4))
        self.temperature = float(conf.get("temperature", 0))

        if not self.base_url or not self.model or not self.api_key:
            raise ValueError(
                "使用总结功能需在 config.json 的 summarization 中填写 base_url、model、api_key。"
            )

        self._client = None
        try:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        except ImportError:
            self._client = None

    # 文本 provider 不实现图片 extract
    def extract(self, image_path):  # noqa: D401
        raise NotImplementedError("TextLLMProvider 仅用于文本总结，不处理图片。")

    def _chat_openai(self, system: str, user: str) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": user})
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=msgs,
            temperature=self.temperature,
            timeout=self.timeout,
        )
        return (resp.choices[0].message.content or "").strip()

    def _chat_requests(self, system: str, user: str) -> str:
        import requests
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": user})
        payload = {"model": self.model, "messages": msgs, "temperature": self.temperature}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        resp = requests.post(f"{self.base_url}/chat/completions",
                             json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    def chat(self, system: str, user: str) -> str:
        """
        发起一次纯文本对话，返回模型回复文本。
        system = 系统提示（设定角色/约束），user = 具体内容（帖子数据等）。
        带重试；与图片引擎不同，这里最终失败会抛异常，由 summarize.py 决定如何处理
        （因为总结失败不应静默吞掉）。
        """
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                # 优先 openai 官方库，没装则 requests 兜底
                if self._client is not None:
                    return self._chat_openai(system, user)
                return self._chat_requests(system, user)
            except Exception as e:
                last_err = e
                print(f"    [LLM 请求异常] (第{attempt+1}次): {str(e)[:160]}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_interval)
        raise RuntimeError(f"LLM 调用失败：{last_err}")
