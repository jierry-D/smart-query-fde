"""PlannerAgent — 将复杂查询/报告主题拆解为子查询计划"""

from .base import BaseAgent, AgentContext, AgentResult
from ..core.logging import get_logger

logger = get_logger(__name__)


class PlannerAgent(BaseAgent):
    """查询计划分解: 报告主题 → 子查询列表"""

    name = "planner"
    description = "查询计划分解 + 子查询编排"

    # 报告模板: 按主题预设子查询
    REPORT_TEMPLATES = {
        "经营分析": [
            {"query": "年度累计中标总额", "metric": "中标总额", "section": "核心指标"},
            {"query": "年度累计签约总额", "metric": "签约总额", "section": "核心指标"},
            {"query": "各业务线中标金额分布", "metric": "业务线分布", "section": "业务线分析"},
            {"query": "各地市中标额排名", "metric": "区域排名", "section": "区域分析"},
            {"query": "商机签约转化率", "metric": "转化率", "section": "商机分析"},
            {"query": "逾期应收账款金额", "metric": "应收款", "section": "风险预警"},
        ],
        "销售分析": [
            {"query": "本月 本期签约额", "metric": "签约额", "section": "核心指标"},
            {"query": "本月 中标总额", "metric": "中标额", "section": "核心指标"},
            {"query": "各业务线签约额排名", "metric": "业务线排名", "section": "业务线分析"},
            {"query": "同比 商机签约转化率", "metric": "转化率同比", "section": "趋势分析"},
        ],
        "区域分析": [
            {"query": "各地市中标额排名", "metric": "区域排名", "section": "区域总览"},
            {"query": "南宁市 各业务线中标额", "metric": "南宁业务线", "section": "重点城市"},
        ],
        "商机分析": [
            {"query": "商机总金额", "metric": "商机总额", "section": "核心指标"},
            {"query": "各阶段商机数量", "metric": "阶段分布", "section": "漏斗分析"},
            {"query": "商机签约转化率", "metric": "转化率", "section": "转化分析"},
        ],
    }

    async def run(self, ctx: AgentContext) -> AgentResult:
        topic = ctx.report_topic or ctx.query

        # 匹配报告模板
        for key, template in self.REPORT_TEMPLATES.items():
            if key in topic:
                ctx.plan = template
                ctx.is_report = True
                logger.info("Planner: matched template '%s' → %d sub-queries", key, len(template))
                return AgentResult.ok({
                    "plan": template,
                    "is_report": True,
                    "sections": list(set(t["section"] for t in template)),
                })

        # 非报告模式: 单查询
        ctx.plan = [{"query": ctx.query, "metric": "", "section": "查询结果"}]
        ctx.is_report = False
        return AgentResult.ok({"plan": ctx.plan, "is_report": False})
