"""ExecuteAgent — SQL 执行 + 治理检查 + 时间智能计算"""

from .base import BaseAgent, AgentContext, AgentResult
from ..core.logging import get_logger

logger = get_logger(__name__)


class ExecuteAgent(BaseAgent):
    """SQL 执行 + 治理 + 时间智能"""

    name = "execute"
    description = "SQL 执行 + 治理检查 + 时间智能计算"

    async def run(self, ctx: AgentContext) -> AgentResult:
        sql = ctx.selected_sql
        if not sql:
            return AgentResult.fail("无可执行的 SQL")

        user = ctx.user
        db = ctx.db

        # 1. 治理检查 (五层: RBAC / SQL安全 / 资源预估 / 熔断 / 缓存)
        gov_result = self._governance_check(sql, user, db)
        if gov_result is None:
            return AgentResult.fail("治理检查未通过")

        # 2. 使用治理层处理后的 SQL (已注入 RBAC 数据范围)
        sql = gov_result.get("final_sql", sql)

        # 3. 执行 SQL
        try:
            rows = db.execute(sql)
            ctx.executed_rows = rows
            logger.debug("Query returned %d rows", len(rows))
        except Exception as e:
            logger.error("SQL execution error: %s", e)
            return AgentResult.fail(f"SQL 执行失败: {e}")

        # 4. 自动计算环比 (单值结果时)
        if len(rows) == 1 and isinstance(rows[0], dict):
            try:
                from ..engine.time_intelligence import TimeIntelligenceEngine
                ti = TimeIntelligenceEngine(db)
                current_val = list(rows[0].values())[0] if rows[0] else 0
                ctx.time_intel = ti.calculate_mom(ctx.metric, current_val, ctx.snapshot_ids)
            except Exception as e:
                logger.debug("Time intelligence skipped: %s", e)

        # 5. 记录查询日志
        try:
            db.log_query(
                user_id=user.get("user_id"),
                username=user.get("username"),
                role=user.get("role"),
                original_query=ctx.query,
                generated_sql=sql,
                status="success",
                row_count=len(rows),
                snapshot_ids=str(ctx.snapshot_ids) if ctx.snapshot_ids else "",
            )
        except Exception as e:
            logger.debug("Query logging skipped: %s", e)

        return AgentResult.ok({
            "row_count": len(rows),
            "time_intel": ctx.time_intel,
        })

    def _governance_check(self, sql: str, user: dict, db) -> dict | None:
        """五层治理检查，返回治理结果 dict（含 final_sql），被拒时返回 None"""
        try:
            from ..governance import GovernanceManager
            gm = GovernanceManager(db)
            result = gm.apply(sql, user)
            if result.get("denied"):
                logger.warning("Query denied by governance: %s", result.get("reason"))
                return None
            return result
        except Exception as e:
            logger.warning("Governance check error (allowing): %s", e)
            # 治理层异常时放行原始 SQL（宽松策略）
            return {"final_sql": sql, "scope_label": "unknown", "cache_hit": False}
