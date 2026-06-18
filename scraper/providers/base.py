# -*- coding: utf-8 -*-
"""Provider 抽象基类。"""

from abc import ABC, abstractmethod
from pathlib import Path


class ImageUnderstandingProvider(ABC):
    """把图片转成文字/知识点描述的统一接口。"""

    def __init__(self, conf: dict):
        self.conf = conf or {}

    @abstractmethod
    def extract(self, image_path: Path) -> str:
        """
        输入一张图片路径，返回从中提取到的文字 / 内容描述（纯文本）。
        失败时应返回空字符串，不要抛异常打断整个批处理。
        """
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__
