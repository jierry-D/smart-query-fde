"""DeepSeek LLM Provider — OpenAI 兼容接口"""

import os
from typing import AsyncIterator

from openai import AsyncOpenAI

from .base import LLMProvider
from ..core.logging import get_logger

logger = get_logger(__name__)


class DeepSeekProvider(LLMProvider):
    """DeepSeek API (OpenAI 兼容)"""

    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or "https://api.deepseek.com"

        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY 未设置, LLM 功能将不可用")
            self.client = None
        else:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url + "/v1" if not self.base_url.endswith("/v1") else self.base_url,
            )

        self.models = {
            "default": "deepseek-chat",
            "coder": "deepseek-coder",
            "fast": "deepseek-chat",
        }

    async def chat(self, messages: list[dict], **kwargs) -> str:
        """同步对话"""
        if not self.client:
            return self._fallback(messages)

        model = kwargs.get("model", self.models["default"])
        temperature = kwargs.get("temperature", 0.1)
        max_tokens = kwargs.get("max_tokens", 2000)
        timeout = kwargs.get("timeout", 30)

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("DeepSeek API 错误: %s", e)
            return self._fallback(messages)

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """流式对话"""
        if not self.client:
            yield self._fallback(messages)
            return

        model = kwargs.get("model", self.models["default"])
        temperature = kwargs.get("temperature", 0.1)
        max_tokens = kwargs.get("max_tokens", 2000)

        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error("DeepSeek 流式错误: %s", e)
            yield self._fallback(messages)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化 (暂用规则模拟)"""
        # DeepSeek 暂不支持 embedding, 降级为规则
        logger.warning("Embedding not available, using fallback")
        return [[0.0] * 128 for _ in texts]

    def _fallback(self, messages: list[dict]) -> str:
        """LLM 不可用时的降级响应"""
        return "[LLM 服务未配置] 请设置 DEEPSEEK_API_KEY 环境变量以启用智能 SQL 生成"


def get_llm() -> LLMProvider:
    """工厂函数: 获取 LLM provider"""
    from ..config import config
    if config.llm_provider == "deepseek":
        return DeepSeekProvider(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
        )
    # 可扩展: openai provider
    return DeepSeekProvider()
