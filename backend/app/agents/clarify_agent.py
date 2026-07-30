"""ClarifyAgent — 反问澄清生成 + 用户回复解析"""

from .base import BaseAgent, AgentContext, AgentResult
from ..core.logging import get_logger

logger = get_logger(__name__)


class ClarifyAgent(BaseAgent):
    """检测歧义并生成反问澄清问题"""

    name = "clarify"
    description = "反问澄清 + 回复解析"

    async def run(self, ctx: AgentContext) -> AgentResult:
        from ..engine.stage_clarify import check_clarification

        # 委托给现有 Pipeline 的 stage_clarify
        try:
            clarification = check_clarification(ctx)
            if clarification and clarification.get("clarification"):
                return AgentResult.ok(clarification["clarification"])
        except Exception as e:
            logger.debug("Clarify check error: %s", e)

        return AgentResult.ok(None)  # 无需澄清
