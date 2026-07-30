"""IntentAgent — 意图分类 + NER 实体提取 + 复杂度评估"""

from .base import BaseAgent, AgentContext, AgentResult
from ..core.logging import get_logger

logger = get_logger(__name__)


class IntentAgent(BaseAgent):
    """识别用户查询的意图、提取实体、评估复杂度"""

    name = "intent"
    description = "意图分类 + NER 实体提取 + 复杂度评估"

    async def run(self, ctx: AgentContext) -> AgentResult:
        from ..engine.ner_engine import NEREngine
        from ..engine.time_resolver import TimeResolver

        query = ctx.query

        # 1. 检查是否为命令
        if query.startswith("/"):
            return self._handle_command(query, ctx)

        # 2. NER 实体提取
        ner = NEREngine()
        entities = ner.extract(query)
        ctx.intent = entities

        # 3. 知识库增强 (同义词扩展)
        try:
            from ..engine.stage_kb import enhance_with_kb
            kb_result = enhance_with_kb(ctx)
            if kb_result:
                ctx.intent.update(kb_result)
        except Exception as e:
            logger.debug("KB enhancement skipped: %s", e)

        # 4. 时间解析
        try:
            resolver = TimeResolver()
            db = ctx.db
            snapshots = db.get_snapshots() if db else []
            time_result = resolver.resolve(query, snapshots)
            if time_result:
                ctx.snapshot_ids = time_result.get("snapshot_ids", [])
                ctx.period_label = time_result.get("label", "")
                ctx.intent["time_resolved"] = time_result
        except Exception as e:
            logger.debug("Time resolution skipped: %s", e)

        # 5. 复杂度评估
        complexity = self._assess_complexity(entities)
        ctx.intent["complexity"] = complexity

        logger.debug("Intent: %s (L%s)", entities.get("intent", "unknown"), complexity)
        return AgentResult.ok({
            "intent": entities.get("intent"),
            "entities": entities.get("filters", {}),
            "complexity": complexity,
        })

    def _assess_complexity(self, entities: dict) -> str:
        """评估查询复杂度 L1-L4"""
        filters = entities.get("filters", {})
        intent = entities.get("intent", "")
        filter_count = len(filters)

        if intent == "trend" or filter_count >= 3:
            return "L3"
        elif intent == "ranking" or filter_count >= 2:
            return "L2"
        else:
            return "L1"

    def _handle_command(self, query: str, ctx: AgentContext) -> AgentResult:
        cmd = query.lower()
        if "/list" in cmd or "/metrics" in cmd:
            return AgentResult.ok({"type": "metric_list"})
        elif "/snapshots" in cmd:
            return AgentResult.ok({"type": "snapshot_list"})
        elif "/db" in cmd:
            return AgentResult.ok({"type": "db_status"})
        elif "/help" in cmd:
            return AgentResult.ok({"type": "help"})
        return AgentResult.ok({"intent": "command", "cmd": query})
