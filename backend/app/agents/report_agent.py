"""ReportAgent — 多维度分析报告自动生成"""

import asyncio
from datetime import date

from .base import BaseAgent, AgentContext, AgentResult, AgentOrchestrator
from ..core.logging import get_logger

logger = get_logger(__name__)


class ReportAgent(BaseAgent):
    """自动生成多维度经营分析报告"""

    name = "report"
    description = "多维度分析报告生成（Markdown + HTML）"

    async def run(self, ctx: AgentContext) -> AgentResult:
        """执行报告生成完整流程"""
        if not ctx.plan:
            return AgentResult.fail("无查询计划 — 需先执行 PlannerAgent")

        sections = {}
        for item in ctx.plan:
            section = item.get("section", "其他")
            if section not in sections:
                sections[section] = []
            sections[section].append(item)

        # 并行执行所有子查询
        sub_results = await self._execute_all(ctx, ctx.plan)

        # 组装报告
        report_md = self._build_report(ctx, sections, sub_results)

        ctx.report_sections = [
            {"section": sec, "items": items}
            for sec, items in sections.items()
        ]
        ctx.interpretation = report_md

        return AgentResult.ok({
            "report": report_md,
            "sections": list(sections.keys()),
            "queries_executed": len(ctx.plan),
        })

    async def _execute_all(self, ctx: AgentContext, plan: list[dict]) -> list[dict]:
        """并行执行所有子查询 (asyncio.gather)"""
        from .intent_agent import IntentAgent
        from .sql_agent import SQLAgent
        from .execute_agent import ExecuteAgent
        from .interpret_agent import InterpretAgent

        async def _run_one(item: dict) -> dict:
            """执行单个子查询: Intent → SQL → Execute → Interpret"""
            q = item["query"]
            sub_ctx = AgentContext(
                query=q,
                user=ctx.user,
                db=ctx.db,
                llm=ctx.llm,
                history=ctx.history.copy(),
            )

            # 每个子查询需要独立的 Agent 实例 (避免状态污染)
            intent = IntentAgent()
            sql_agent = SQLAgent()
            execute = ExecuteAgent()
            interpret = InterpretAgent()

            try:
                intent_r = await intent._timed_run(sub_ctx)
                if not intent_r.success:
                    return {"query": q, "error": intent_r.error, "section": item.get("section", "")}

                sql_r = await sql_agent._timed_run(sub_ctx)
                if not sql_r.success:
                    return {"query": q, "error": sql_r.error, "section": item.get("section", "")}

                exec_r = await execute._timed_run(sub_ctx)
                if not exec_r.success:
                    return {"query": q, "error": exec_r.error, "section": item.get("section", "")}

                await interpret._timed_run(sub_ctx)

                return {
                    "query": q,
                    "metric": item.get("metric", ""),
                    "section": item.get("section", ""),
                    "sql": sub_ctx.selected_sql,
                    "rows": sub_ctx.executed_rows,
                    "interpretation": sub_ctx.interpretation or "",
                    "time_intel": sub_ctx.time_intel or {},
                    "stages": sub_ctx.stages,
                }
            except Exception as e:
                logger.warning("Sub-query failed [%s]: %s", q, e)
                return {"query": q, "error": str(e), "section": item.get("section", "")}

        # 并行执行所有子查询
        results = await asyncio.gather(*[_run_one(item) for item in plan])
        return list(results)

    def _build_report(self, ctx: AgentContext, sections: dict, results: list[dict]) -> str:
        """构建 Markdown 格式报告"""
        today = date.today().strftime("%Y年%m月%d日")
        user_name = ctx.user.get("display_name", ctx.user.get("username", "用户"))

        lines = [
            f"# 📊 {ctx.report_topic or '经营分析报告'}",
            f"",
            f"**生成日期**：{today}",
            f"**生成用户**：{user_name}",
            f"**数据范围**：{ctx.period_label or '最新可用数据'}",
            f"",
            f"---",
            f"",
            f"## 📋 摘要",
            f"",
            self._build_summary(results),
            f"",
            f"---",
            f"",
        ]

        # 按 section 组织
        for section_name, items in sections.items():
            lines.append(f"## {section_name}")
            lines.append("")

            for item in items:
                q = item["query"]
                result = next((r for r in results if r["query"] == q), None)

                if not result:
                    lines.append(f"- **{q}**：执行失败")
                    continue
                if result.get("error"):
                    lines.append(f"- **{q}**：{result['error']}")
                    continue

                lines.append(f"### {item.get('metric', q)}")
                lines.append("")

                # 数值结果
                rows = result.get("rows", [])
                if len(rows) == 1 and isinstance(rows[0], dict):
                    row = rows[0]
                    value = row.get("value", list(row.values())[0] if row else 0)
                    lines.append(f"> **{value:,.2f}** {ctx.metric.get('unit', '')}")
                    lines.append("")

                # 表格结果
                elif len(rows) > 1:
                    lines.append(self._build_table(rows))
                    lines.append("")

                # 解读
                if result.get("interpretation"):
                    lines.append(result["interpretation"])
                    lines.append("")

                # 时间对比
                ti = result.get("time_intel", {})
                if ti.get("available"):
                    direction = "📈" if ti.get("direction") == "increase" else "📉"
                    lines.append(f"{direction} 环比 {ti.get('growth_rate', 0):+.1f}%")
                    lines.append("")

            lines.append("")

        # 风险预警
        lines.append("---")
        lines.append("")
        lines.append("## ⚠️ 风险预警")
        lines.append("")
        risks = self._build_risks(results)
        if risks:
            lines.extend(risks)
        else:
            lines.append("> 当前未检测到明显风险指标。")
        lines.append("")

        # 建议
        lines.append("## 💡 建议与行动项")
        lines.append("")
        lines.append("> 以上分析基于系统当前数据，建议结合实际业务情况综合判断。")
        lines.append("")

        # 附录: 查询明细
        lines.append("---")
        lines.append("")
        lines.append("## 📎 附录：查询明细")
        lines.append("")
        for r in results:
            if r.get("sql"):
                lines.append(f"- **{r['query']}**")
                lines.append(f"  ```sql")
                lines.append(f"  {r['sql'][:200]}")
                lines.append(f"  ```")
                lines.append("")

        return "\n".join(lines)

    def _build_summary(self, results: list[dict]) -> str:
        """报告摘要"""
        total = len(results)
        success = len([r for r in results if not r.get("error") and r.get("rows")])
        lines = [
            f"本次报告共执行 **{total}** 个查询，成功 **{success}** 个。",
            f"",
        ]

        # 提取核心指标
        for r in results[:3]:
            rows = r.get("rows", [])
            if len(rows) == 1 and isinstance(rows[0], dict):
                row = rows[0]
                value = row.get("value", list(row.values())[0] if row else 0)
                lines.append(f"- {r.get('metric', r['query'])}：**{value:,.2f}**")

        return "\n".join(lines)

    def _build_table(self, rows: list) -> str:
        """构建 Markdown 表格"""
        if not rows:
            return ""

        columns = list(rows[0].keys())
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for row in rows[:10]:
            values = [str(row.get(c, "")) for c in columns]
            lines.append("| " + " | ".join(values) + " |")

        if len(rows) > 10:
            lines.append(f"\n*（仅显示前 10 行，共 {len(rows)} 行）*")

        return "\n".join(lines)

    def _build_risks(self, results: list[dict]) -> list[str]:
        """风险预警"""
        risks = []
        for r in results:
            rows = r.get("rows", [])
            metric = r.get("metric", r.get("query", ""))

            # 简单启发式: 逾期/下降/下降率 > 阈值
            if len(rows) == 1 and isinstance(rows[0], dict):
                row = rows[0]
                value = row.get("value", 0)
                if isinstance(value, (int, float)):
                    # 高应收款预警
                    if "应收" in metric and value > 500:
                        risks.append(f"- 🔴 **{metric}**：{value:,.0f}，超过 500 万预警阈值")

            # 环比下降预警
            ti = r.get("time_intel", {})
            if ti.get("direction") == "decrease" and abs(ti.get("growth_rate", 0)) > 10:
                risks.append(f"- 🟡 **{metric}**：环比下降 {abs(ti['growth_rate']):.1f}%")

        return risks
