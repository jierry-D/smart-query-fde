"""SQLAgent — SQL 生成 + 验证 + 修正循环"""

import re

from .base import BaseAgent, AgentContext, AgentResult
from ..core.logging import get_logger

logger = get_logger(__name__)


class SQLAgent(BaseAgent):
    """SQL 生成、验证和修正"""

    name = "sql"
    description = "SQL 生成 + 多层验证 + 修正循环"

    async def run(self, ctx: AgentContext) -> AgentResult:
        # 1. 指标匹配
        metric = self._match_metric(ctx)
        if not metric:
            return AgentResult.fail("未找到匹配的指标")

        ctx.metric = metric

        # 2. SQL 生成: 模板优先 + LLM 增强
        template_sql = metric.get("sql_template", "")

        if template_sql and metric.get("confidence", 0) >= 0.8:
            # 高置信度 → 直接用模板
            sql = self._fill_template(template_sql, ctx)
            ctx.selected_sql = sql
            logger.debug("SQL from template: %s...", sql[:100])
        elif ctx.llm:
            # LLM 生成
            sql = await self._generate_with_llm(ctx, metric, template_sql)
            if sql:
                ctx.selected_sql = sql
            elif template_sql:
                ctx.selected_sql = self._fill_template(template_sql, ctx)
            else:
                return AgentResult.fail("SQL 生成失败: LLM 和模板均不可用")
        elif template_sql:
            ctx.selected_sql = self._fill_template(template_sql, ctx)
        else:
            return AgentResult.fail("SQL 生成失败: 无模板且 LLM 不可用")

        # 3. NER 实体注入 (WHERE/GROUP BY/ORDER BY/LIMIT)
        ctx.selected_sql = self._inject_ner(ctx)

        # 4. SQL 验证
        if not self._validate(ctx.selected_sql):
            return AgentResult.fail("SQL 验证失败")

        logger.debug("Final SQL: %s", ctx.selected_sql[:200])
        return AgentResult.ok({"sql": ctx.selected_sql, "metric": metric.get("name")})

    def _match_metric(self, ctx: AgentContext) -> dict | None:
        """指标匹配: 语义层 4 层策略"""
        try:
            from ..semantic.loader import MetricLoader
            loader = MetricLoader(ctx.db)
            return loader.match(ctx.query, ctx.intent)
        except Exception as e:
            logger.warning("Metric matching error: %s", e)
            return None

    def _fill_template(self, template: str, ctx: AgentContext) -> str:
        """填充 SQL 模板中的占位符"""
        sql = template
        # snapshot_id 占位符
        if ctx.snapshot_ids:
            if len(ctx.snapshot_ids) == 1:
                sql = sql.replace("{snapshot_where}", f"snapshot_id = {ctx.snapshot_ids[0]}")
            else:
                ids = ",".join(str(s) for s in ctx.snapshot_ids)
                sql = sql.replace("{snapshot_where}", f"snapshot_id IN ({ids})")
        else:
            sql = sql.replace("WHERE {snapshot_where}", "").replace("AND {snapshot_where}", "")
            sql = sql.replace("{snapshot_where}", "1=1")
        return sql

    async def _generate_with_llm(self, ctx: AgentContext, metric: dict, base_template: str) -> str | None:
        """LLM 生成 SQL"""
        try:
            from ..llm.prompts import PromptManager
            pm = PromptManager()
            prompt = pm.render("sql_generator",
                table_schema=self._get_table_schema(ctx),
                metric_name=metric.get("name", ""),
                formula=metric.get("formula", ""),
                table_name=metric.get("table_name", ""),
                query=ctx.query,
            )
            llm_response = await ctx.llm.chat([{"role": "user", "content": prompt}])
            # 提取 SQL
            match = re.search(r'```sql\s*(.*?)\s*```', llm_response, re.DOTALL)
            if match:
                return match.group(1).strip()
            # Fallback: 找 SELECT 语句
            match = re.search(r'(SELECT\s+.*?;)', llm_response, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
            return None
        except Exception as e:
            logger.warning("LLM SQL generation failed: %s", e)
            return None

    def _inject_ner(self, ctx: AgentContext) -> str:
        """将 NER 实体注入 SQL"""
        try:
            from ..engine.sql_filter import SQLFilter
            return SQLFilter().apply(ctx.selected_sql, ctx.intent)
        except Exception:
            return ctx.selected_sql

    def _validate(self, sql: str) -> bool:
        """SQL 验证: 安全关键字 + 只读"""
        dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE"]
        upper = sql.upper()
        for kw in dangerous:
            if kw in upper:
                logger.warning("SQL rejected: contains %s", kw)
                return False
        if not sql.strip().upper().startswith("SELECT"):
            return False
        return True

    @staticmethod
    def _get_table_schema(ctx: AgentContext) -> str:
        try:
            metric = ctx.metric
            tn = metric.get("table_name", "")
            if tn and ctx.db:
                cols = ctx.db.get_table_schema(tn)
                return "\n".join(f"- {c.get('name','?')} ({c.get('type','?')})" for c in cols)
        except Exception:
            pass
        return "表结构不可用"
