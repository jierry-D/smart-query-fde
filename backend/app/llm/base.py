"""LLM 抽象层 — Provider 接口"""

from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    """LLM Provider 抽象接口"""

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> str:
        """同步对话"""
        ...

    @abstractmethod
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """流式对话"""
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化"""
        ...
