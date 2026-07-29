"""模型路由器 — 根据复杂度选择最优模型"""

from ..core.logging import get_logger

logger = get_logger(__name__)


class ModelRouter:
    """
    根据任务复杂度路由到合适的模型。

    L1-L2: 简单查询 → deepseek-coder (快, 省)
    L3-L4: 复杂查询 → deepseek-chat (强, 准)
    """

    COMPLEXITY_MAP = {
        "L1": {"model": "deepseek-coder", "temperature": 0.1, "max_tokens": 1000},
        "L2": {"model": "deepseek-coder", "temperature": 0.1, "max_tokens": 1500},
        "L3": {"model": "deepseek-chat", "temperature": 0.2, "max_tokens": 2000},
        "L4": {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 3000},
        "L5": {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 4000},
        "L6": {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 4000},
    }

    def get_config(self, complexity: str) -> dict:
        """获取模型配置"""
        return self.COMPLEXITY_MAP.get(
            complexity,
            {"model": "deepseek-coder", "temperature": 0.1, "max_tokens": 1000},
        )

    def should_use_llm(self, complexity: str, has_ner_filters: bool) -> bool:
        """
        判断是否应使用 LLM 生成 SQL。

        - L1 且有精确指标匹配 + 无NER筛选: 优先模板
        - L3+: 使用 LLM
        - 有 NER 筛选条件: 使用模板 (更可靠)
        """
        if has_ner_filters:
            return False  # NER 筛选用模板更可靠
        if complexity in ("L3", "L4", "L5", "L6"):
            return True
        return False  # L1-L2 模板即可
