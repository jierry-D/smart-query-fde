"""Agent 基础框架 — BaseAgent, AgentContext, AgentOrchestrator"""

import time
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Callable

from ..core.logging import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════
# AgentResult — Agent 执行结果
# ═══════════════════════════════════════════

@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    data: Any = None
    error: str = ""
    metadata: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @classmethod
    def ok(cls, data: Any, **meta) -> "AgentResult":
        return cls(success=True, data=data, metadata=meta)

    @classmethod
    def fail(cls, error: str, **meta) -> "AgentResult":
        return cls(success=False, error=error, metadata=meta)


# ═══════════════════════════════════════════
# AgentContext — 共享上下文
# ═══════════════════════════════════════════

@dataclass
class AgentContext:
    """Agent 间共享的上下文信息"""
    # 用户输入
    query: str
    user: dict  # {user_id, username, role, department, region}

    # 基础设施
    db: Any  # DatabaseConnector
    llm: Any = None  # LLMProvider (optional)

    # 中间结果 (各 Agent 的产出)
    intent: dict = field(default_factory=dict)       # IntentAgent → {intent, entities, complexity}
    plan: list[dict] = field(default_factory=list)    # PlannerAgent → [{query, metric, reason}]
    sql_candidates: list[str] = field(default_factory=list)  # SQLAgent → [sql1, sql2, ...]
    selected_sql: str = ""                            # 最终选中的 SQL
    executed_rows: list = field(default_factory=list) # 执行结果行
    metric: dict = field(default_factory=dict)        # 匹配到的指标定义
    interpretation: str = ""                          # NL 解读文本
    time_intel: dict = field(default_factory=dict)    # 时间智能 (YTD/YoY/MoM)
    snapshot_ids: list = field(default_factory=list)
    period_label: str = ""

    # 对话历史 (最近 N 轮)
    history: list[dict] = field(default_factory=list)  # [{role, content, result}]

    # 报告模式
    is_report: bool = False
    report_topic: str = ""
    report_sections: list[dict] = field(default_factory=list)

    # 过程记录
    stages: list[dict] = field(default_factory=list)

    # 配置
    engine_mode: str = "agent"  # "agent" | "pipeline" (fallback)

    def add_stage(self, name: str, status: str, elapsed_ms: float, detail: str = ""):
        self.stages.append({
            "name": name, "status": status,
            "elapsed_ms": round(elapsed_ms, 2), "detail": detail,
        })

    def add_to_history(self, role: str, content: str, result: dict = None):
        self.history.append({"role": role, "content": content, "result": result})
        if len(self.history) > 10:
            self.history.pop(0)

    def last_query(self) -> Optional[dict]:
        """获取上一次查询的上下文"""
        for h in reversed(self.history):
            if h["role"] == "assistant" and h.get("result"):
                return h
        return None


# ═══════════════════════════════════════════
# BaseAgent — Agent 抽象基类
# ═══════════════════════════════════════════

class BaseAgent(ABC):
    """所有 Agent 的抽象基类"""

    name: str = "base"
    description: str = "Base agent"

    @abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult:
        """执行 Agent 逻辑"""
        ...

    async def _timed_run(self, ctx: AgentContext) -> AgentResult:
        """带计时和异常保护的执行包装器"""
        t0 = time.perf_counter()
        try:
            result = await self.run(ctx)
            result.elapsed_ms = (time.perf_counter() - t0) * 1000
            if result.success:
                ctx.add_stage(self.name, "done", result.elapsed_ms)
            else:
                ctx.add_stage(self.name, "error", result.elapsed_ms, result.error)
            return result
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning("Agent [%s] failed: %s", self.name, e)
            ctx.add_stage(self.name, "error", elapsed, str(e))
            return AgentResult.fail(str(e), elapsed_ms=elapsed)

    def __repr__(self):
        return f"<{self.name}>"


# ═══════════════════════════════════════════
# AgentOrchestrator — 编排器
# ═══════════════════════════════════════════

class AgentOrchestrator:
    """Agent 编排器: 注册 → DAG 构建 → 并行调度"""

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        """注册 Agent"""
        self._agents[agent.name] = agent
        logger.debug("Registered agent: %s", agent.name)

    def get(self, name: str) -> Optional[BaseAgent]:
        return self._agents.get(name)

    async def run_sequential(self, agent_names: list[str], ctx: AgentContext) -> list[AgentResult]:
        """顺序执行 Agent 列表"""
        results = []
        for name in agent_names:
            agent = self._agents.get(name)
            if not agent:
                results.append(AgentResult.fail(f"Agent '{name}' not found"))
                continue
            result = await agent._timed_run(ctx)
            results.append(result)
            if not result.success:
                logger.warning("Agent [%s] failed, stopping pipeline", name)
                break
        return results

    async def run_parallel(self, agent_specs: list[tuple[str, dict]], ctx: AgentContext) -> list[AgentResult]:
        """并行执行多个 Agent (每个可以有不同的参数覆盖)"""
        async def _run_one(name: str, overrides: dict) -> AgentResult:
            agent = self._agents.get(name)
            if not agent:
                return AgentResult.fail(f"Agent '{name}' not found")

            # 创建子上下文 (带参数覆盖)
            sub_ctx = AgentContext(
                query=overrides.get("query", ctx.query),
                user=ctx.user,
                db=ctx.db,
                llm=ctx.llm,
                history=ctx.history.copy(),
            )
            return await agent._timed_run(sub_ctx)

        tasks = [_run_one(name, overrides) for name, overrides in agent_specs]
        return await asyncio.gather(*tasks)

    async def run_query(self, query: str, user: dict, db, llm=None) -> dict:
        """执行一次完整的 NL2SQL 查询 (Agent 模式)

        流程: Intent → (Clarify?) → SQL → Execute → Interpret
        """
        ctx = AgentContext(query=query, user=user, db=db, llm=llm)

        # 1. Intent 识别 + NER
        intent_result = await self._agents["intent"]._timed_run(ctx)
        if not intent_result.success:
            return {"type": "error", "message": intent_result.error, "process": ctx.stages}

        # 1.5 检查是否需要反问澄清
        clarify_result = await self._agents["clarify"]._timed_run(ctx)
        if clarify_result.success and clarify_result.data:
            return {
                "type": "clarify",
                "clarification": clarify_result.data,
                "process": ctx.stages,
            }

        # 2. SQL 生成
        sql_result = await self._agents["sql"]._timed_run(ctx)
        if not sql_result.success:
            return {"type": "error", "message": sql_result.error, "process": ctx.stages}

        # 3. 执行
        exec_result = await self._agents["execute"]._timed_run(ctx)
        if not exec_result.success:
            return {"type": "error", "message": exec_result.error, "process": ctx.stages}

        # 4. 解读
        interpret_result = await self._agents["interpret"]._timed_run(ctx)

        # 构建响应
        response = build_response(ctx)
        response["process"] = ctx.stages
        return response


def build_response(ctx: AgentContext) -> dict:
    """从上下文构建标准 API 响应"""
    rows = ctx.executed_rows
    metric = ctx.metric

    if not rows:
        return {"type": "error", "message": "查询无结果"}

    if len(rows) == 1 and isinstance(rows[0], dict):
        # 单值结果 → number card
        row = rows[0]
        value = row.get("value", 0)
        return {
            "type": "number",
            "metric_name": metric.get("name", ""),
            "value": value,
            "unit": metric.get("unit", ""),
            "explanation": ctx.interpretation or metric.get("description", ""),
            "formula": metric.get("formula", ""),
            "sql": ctx.selected_sql,
            "time_intelligence": ctx.time_intel or None,
            "elapsed_ms": 0,
            "row_count": 1,
        }

    # 多行结果 → table
    if isinstance(rows, list) and all(isinstance(r, dict) for r in rows):
        columns = list(rows[0].keys()) if rows else []
        return {
            "type": "table",
            "metric_name": metric.get("name", ""),
            "columns": columns,
            "rows": rows,
            "sql": ctx.selected_sql,
            "explanation": ctx.interpretation or "",
            "elapsed_ms": 0,
            "row_count": len(rows),
        }

    return {"type": "error", "message": "无法解析查询结果"}
