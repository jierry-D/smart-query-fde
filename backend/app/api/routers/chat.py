"""对话 API — NL2SQL 查询 + 命令处理 (SSE 流式)"""

import concurrent.futures
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.deps import get_current_user
from ...core.security import build_data_scope_sql, get_data_scope
from ...core.logging import get_logger
from ...database import DatabaseConnector
from ...schemas import ChatRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["对话"])

# Dashboard 专用线程池
_DASHBOARD_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=9, thread_name_prefix="dashboard"
)

# ── 查询历史 ──

@router.get("/history")
def get_history(limit: int = 20, user: dict = Depends(get_current_user)):
    """获取当前用户的查询历史"""
    db = _get_db()
    logs = db.get_query_history(user["user_id"], limit)
    return {
        "logs": [dict(r) for r in logs],
        "total": len(logs),
    }

# ── 仪表盘 ──

@router.get("/dashboard")
def get_dashboard(user: dict = Depends(get_current_user)):
    """获取仪表盘数据 — 核心经营指标一览 (并行执行)"""
    db = _get_db()

    from ...engine.pipeline import NL2SQLPipeline

    key_metrics = [
        ("年度累计中标总额", "💰", "中标总额"),
        ("本期签约额", "📝", "本期签约"),
        ("商机签约转化率", "📈", "签约转化率"),
        ("应收账款总余额", "💳", "应收余额"),
        ("存量客户总数", "👥", "客户总数"),
        ("正常跟进商机数量", "🎯", "在跟商机"),
    ]

    def _run_metric(metric_name):
        """线程安全的单指标查询"""
        pipe = NL2SQLPipeline(db)
        return pipe.run(metric_name, user)

    # 并行执行 9 个查询 (6 key metrics + 1 distribution + 2 alerts)
    all_futures = {}
    for metric_name, icon, label in key_metrics:
        all_futures[("card", metric_name, icon, label)] = _DASHBOARD_EXECUTOR.submit(_run_metric, metric_name)
    all_futures[("dist", "各地市中标额")] = _DASHBOARD_EXECUTOR.submit(_run_metric, "各地市中标额")
    all_futures[("alert", "大额逾期应收款金额")] = _DASHBOARD_EXECUTOR.submit(_run_metric, "大额逾期应收款金额")
    all_futures[("alert", "长期停滞商机数量")] = _DASHBOARD_EXECUTOR.submit(_run_metric, "长期停滞商机数量")

    # 收集结果
    cards = []
    for metric_name, icon, label in key_metrics:
        try:
            r = all_futures[("card", metric_name, icon, label)].result(timeout=30)
            cards.append({
                "label": label, "icon": icon,
                "value": r.get("value"), "unit": r.get("unit", ""),
                "type": r.get("type", "number"),
                "alert_level": r.get("alert_level", ""),
                "metric_name": metric_name,
            })
        except Exception:
            cards.append({
                "label": label, "icon": icon,
                "value": None, "unit": "", "alert_level": "",
                "metric_name": metric_name,
            })

    distribution = None
    try:
        r = all_futures[("dist", "各地市中标额")].result(timeout=30)
        if r.get("type") == "table" and r.get("rows"):
            distribution = {
                "labels": [row.get("label", "") for row in r["rows"][:10]],
                "values": [row.get("value", 0) for row in r["rows"][:10]],
            }
    except Exception:
        pass

    alerts = []
    for metric_name in ["大额逾期应收款金额", "长期停滞商机数量"]:
        try:
            r = all_futures[("alert", metric_name)].result(timeout=30)
            if r.get("value") and r.get("alert_level"):
                alerts.append({
                    "metric": metric_name,
                    "value": r["value"], "unit": r.get("unit", ""),
                    "alert_level": r["alert_level"],
                })
        except Exception:
            pass

    return {
        "cards": cards,
        "distribution": distribution,
        "alerts": alerts,
        "updated_at": db.get_latest_snapshot().get("data_period", "") if db.get_latest_snapshot() else "",
        "metrics_total": len(db.execute("SELECT * FROM metric_registry WHERE status='available'")),
    }

# ── CSV 导出 ──

@router.post("/export/csv")
def export_csv(req: ChatRequest, user: dict = Depends(get_current_user)):
    """导出查询结果为 CSV"""
    import io
    import csv

    user_input = ' '.join(req.q.strip().split())
    if not user_input:
        raise HTTPException(400, "查询内容为空")

    db = _get_db()
    llm = None
    try:
        from ...llm.deepseek import get_llm
        llm = get_llm()
    except Exception:
        pass

    from ...engine.pipeline import NL2SQLPipeline
    pipeline = NL2SQLPipeline(db, llm_provider=llm)
    result = pipeline.run(user_input, user)

    rows = result.get("rows", [])
    cols = result.get("columns", [])

    # 数字结果转为单行CSV
    if not rows and result.get("type") == "number" and result.get("value") is not None:
        rows = [{"指标": result.get("metric_name", ""), "数值": result["value"]}]
        cols = ["指标", "数值"]

    if not rows:
        raise HTTPException(404, "查询无结果")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(cols)
    for row in rows:
        writer.writerow([row.get(c, "") for c in cols])

    output.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=query_result.csv"}
    )


def _get_db():
    return DatabaseConnector()


# ── SSE 流式查询 ──

@router.post("/chat")
def chat(req: ChatRequest, request: Request, user: dict = Depends(get_current_user)):
    """
    处理自然语言查询或 / 命令.

    支持 SSE 流式响应 (Accept: text/event-stream) 或 JSON.
    """
    user_input = ' '.join(req.q.strip().split())
    if not user_input:
        return {"type": "error", "message": "请输入查询内容"}

    db = _get_db()

    # 命令路由
    if user_input.startswith("/"):
        return _handle_command(user_input, db, user)

    # 检查是否请求 SSE
    accept_header = request.headers.get("accept", "")
    use_sse = "text/event-stream" in accept_header

    if use_sse:
        return _handle_sse(user_input, db, user)
    else:
        return _handle_query(user_input, db, user)


def _handle_sse(query: str, db, user: dict):
    """SSE 流式查询 — 实时推送 Pipeline 进度"""
    import asyncio
    import threading
    import json as json_module
    from sse_starlette.sse import EventSourceResponse

    async def sse_generator():
        event_queue = asyncio.Queue()
        thread_loop = None

        def _push_safe(item):
            """线程安全地向 asyncio.Queue 推送事件"""
            nonlocal thread_loop
            if thread_loop is None:
                thread_loop = asyncio.new_event_loop()
            thread_loop.call_soon_threadsafe(event_queue.put_nowait, item)

        def run_pipeline():
            try:
                result = _handle_query(query, db, user)
                stages = result.get("process", [])

                for stage in stages:
                    try:
                        _push_safe({"event": "stage", "data": stage})
                    except Exception:
                        pass

                output = {k: v for k, v in result.items()
                          if k not in ("process", "_query")}
                try:
                    _push_safe({"event": "result", "data": output})
                except Exception:
                    pass
            except Exception as e:
                try:
                    _push_safe({"event": "error", "data": {"message": str(e)}})
                except Exception:
                    pass
            finally:
                try:
                    _push_safe(None)
                except Exception:
                    pass

        thread = threading.Thread(target=run_pipeline)
        thread.start()

        yield {"event": "start", "data": json_module.dumps({"query": query})}

        while True:
            item = await event_queue.get()
            if item is None:
                break
            yield item

        thread.join()
        # 清理线程级 event loop
        if thread_loop is not None:
            thread_loop.close()
        yield {"event": "done", "data": json_module.dumps({"status": "complete"})}

    return EventSourceResponse(sse_generator())


# ── 查询处理 ──

def _handle_query(query: str, db: DatabaseConnector, user: dict) -> dict:
    """完整的 NL2SQL 查询流水线 — 支持 Agent 模式 + 多轮对话"""

    # 多轮对话: 检测追问并注入上下文
    original_query = query
    from ...engine.conversation_memory import ConversationMemory
    memory = ConversationMemory(user.get("user_id", 0))
    followup = memory.detect_followup(query)

    if followup:
        logger.info("Follow-up detected: type=%s, enhanced=%s",
                     followup["followup_type"], followup.get("enhanced_query"))
        query = followup.get("enhanced_query", query)

    # 检测是否为报告请求
    is_report = any(kw in query for kw in ["生成报告", "分析报告", "经营分析", "销售分析", "区域分析", "商机分析"])

    # 尝试初始化 LLM
    llm = None
    try:
        from ...llm.deepseek import get_llm
        llm = get_llm()
    except Exception:
        pass

    # Agent 模式: 报告 / 分析类 / LLM 可用时
    result = None
    if is_report and llm:
        result = _handle_agent_query(query, db, user, llm, is_report)
    else:
        result = _handle_pipeline_query(query, db, user, llm)

    # 保存对话记忆
    if result and result.get("type") not in ("error", "clarify", "pending"):
        memory.add_turn(original_query, result)

    return result


def _handle_pipeline_query(query: str, db: DatabaseConnector, user: dict, llm=None) -> dict:
    """使用传统 Pipeline 处理查询"""
    from ...engine.pipeline import NL2SQLPipeline
    pipeline = NL2SQLPipeline(db, llm_provider=llm)
    result = pipeline.run(query, user)
    _log_query(db, user, query, result)
    result["_query"] = query
    return result


def _handle_agent_query(query: str, db: DatabaseConnector, user: dict, llm, is_report: bool) -> dict:
    """使用 Agent 体系处理查询"""
    import asyncio

    from ...agents.base import AgentContext, AgentOrchestrator
    from ...agents.intent_agent import IntentAgent
    from ...agents.planner_agent import PlannerAgent
    from ...agents.sql_agent import SQLAgent
    from ...agents.execute_agent import ExecuteAgent
    from ...agents.interpret_agent import InterpretAgent
    from ...agents.clarify_agent import ClarifyAgent
    from ...agents.report_agent import ReportAgent

    orchestrator = AgentOrchestrator()
    orchestrator.register(IntentAgent())
    orchestrator.register(PlannerAgent())
    orchestrator.register(SQLAgent())
    orchestrator.register(ExecuteAgent())
    orchestrator.register(InterpretAgent())
    orchestrator.register(ClarifyAgent())
    orchestrator.register(ReportAgent())

    async def _run():
        ctx = AgentContext(query=query, user=user, db=db, llm=llm)

        if is_report:
            ctx.is_report = True
            ctx.report_topic = query
            plan_result = await orchestrator.get("planner")._timed_run(ctx)
            if not plan_result.success:
                return {"type": "error", "message": plan_result.error, "process": ctx.stages}
            report_result = await orchestrator.get("report")._timed_run(ctx)
            if not report_result.success:
                return {"type": "error", "message": report_result.error, "process": ctx.stages}
            return {
                "type": "report",
                "report": report_result.data.get("report", ""),
                "sections": report_result.data.get("sections", []),
                "queries_executed": report_result.data.get("queries_executed", 0),
                "process": ctx.stages,
            }
        else:
            return await orchestrator.run_query(query, user, db, llm)

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_run())
            loop.close()
        else:
            # 已有运行中的事件循环 (async context)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, _run()).result(timeout=60)
        _log_query(db, user, query, result)
        result["_query"] = query
        return result
    except Exception as e:
        logger.warning("Agent mode failed (%s), falling back to Pipeline", e)
        return _handle_pipeline_query(query, db, user, llm)


def _log_query(db, user: dict, query: str, result: dict):
    """记录查询日志 (非阻塞)"""
    try:
        import json
        db.log_query(
            user_id=user["user_id"], username=user["username"],
            role=user["role"], original_query=query,
            cleaned_query=query, generated_sql=result.get("sql", ""),
            intent="",
            exec_time_ms=result.get("elapsed_ms", 0),
            row_count=result.get("row_count", 0),
            status="success" if result.get("type") not in ("error", "pending", "clarify") else result.get("type"),
            error_message=result.get("message", ""),
            snapshot_ids=json.dumps([s.get("snapshot_id") for s in db.get_snapshots()[:1]]) if db.get_snapshots() else None,
        )
    except Exception:
        pass


# ── 命令处理 ──

def _handle_command(cmd: str, db: DatabaseConnector, user: dict) -> dict:
    """处理 / 命令"""
    parts = cmd.strip().split()
    command = parts[0].lower() if parts else ""

    if command in ("/list", "/metrics"):
        loader = _get_loader(db)
        category = parts[1] if len(parts) > 1 else None
        metrics = loader.list_all(category)
        return {
            "type": "metric_list",
            "metrics": metrics,
            "total": len(metrics),
            "categories": loader.list_categories(),
            "available": loader.available_count,
        }

    elif command in ("/help", "/h"):
        return {
            "type": "help",
            "text": "\n".join([
                "📋 命令列表:",
                "  /list [分类]  — 列出所有可用指标",
                "  /snapshots    — 查看所有数据快照",
                "  /db           — 查看数据库状态",
                "  /detail <名称> — 查看指标详情",
                "  /help         — 显示此帮助",
                "",
                "⏰ 时间维度:",
                "  Q3 年度累计中标总额      → 跨月聚合",
                "  本月 本期签约额          → 单月查询",
                "  上个季度 投标中标率      → 相对时间",
                "  同比 商机签约转化率      → 同比分析",
                "",
                "🔍 筛选条件:",
                "  南宁市 中标总额          → 区域筛选",
                "  数字政务 中标总额        → 业务线筛选",
                "  Top 5 各地市中标额       → 排名筛选",
                "",
                f"👤 当前: {user.get('display_name') or user.get('username', '?')} | 角色: {user['role']} | 范围: {_scope_desc(user)}",
            ]),
        }

    elif command in ("/db", "/tables"):
        tables = db.get_tables()
        data_tables = [t for t in tables
                       if t not in ('data_snapshots', 'sqlite_sequence', 'metric_registry',
                                    'query_logs', 'query_feedback', 'audit_logs',
                                    'users', 'refresh_tokens', 'user_data_permissions')]
        table_info = []
        for t in data_tables:
            try:
                cnt = db.execute(f"SELECT COUNT(*) AS cnt FROM \"{t}\"")[0]["cnt"]
                table_info.append({"table_name": t, "row_count": cnt})
            except Exception:
                table_info.append({"table_name": t, "row_count": 0})

        # admin 可以看系统表
        if user.get("role") == "admin":
            table_info.append({"table_name": "users", "row_count": len(db.get_all_users())})
            try:
                cnt = db.execute("SELECT COUNT(*) AS cnt FROM query_logs")[0]["cnt"]
                table_info.append({"table_name": "query_logs", "row_count": cnt})
            except Exception:
                pass

        return {
            "type": "db_status",
            "tables": table_info,
            "total_tables": len(table_info),
            "is_admin": user.get("role") == "admin",
        }

    elif command == "/snapshots":
        snapshots = db.get_snapshots()
        latest = db.get_latest_snapshot()
        return {
            "type": "snapshot_list",
            "snapshots": snapshots,
            "total": len(snapshots),
            "latest_id": latest["snapshot_id"] if latest else None,
            "latest_period": latest["data_period"] if latest else "无数据",
        }

    elif command == "/detail":
        if len(cmd.split()) > 1:
            name = " ".join(cmd.split()[1:])
            loader = _get_loader(db)
            metric = loader.get_by_name(name)
            if metric:
                return {
                    "type": "metric_detail",
                    "metric_id": metric["metric_id"],
                    "name": metric["name"],
                    "category": metric["category"],
                    "explanation": metric.get("explanation", ""),
                    "formula": metric.get("formula", ""),
                    "source": metric.get("source", ""),
                    "sql_template": metric.get("sql_template"),
                    "result_format": metric.get("result_format"),
                    "result_unit": metric.get("result_unit", ""),
                    "status": metric["status"],
                    "complexity": metric["complexity"],
                    "alert_level": metric.get("alert_level"),
                }
        return {"type": "error", "message": "用法: /detail <指标名称>", "suggestions": []}

    elif command == "/import":
        if user.get("role") not in ("admin", "leader"):
            return {"type": "error", "message": "您没有导入权限 (需 admin 或 leader 角色)"}
        return {"type": "error", "message": "请使用导入按钮上传 Excel 文件",
                "suggestions": ["点击页面上的 '导入Excel' 按钮"]}

    else:
        return {"type": "error", "message": f"未知命令: {command}",
                "suggestions": ["输入 /help 查看可用命令"]}


# ── 辅助函数 ──

def _get_loader(db):
    from ...semantic.loader import MetricLoader
    return MetricLoader(db)



def _scope_desc(user: dict) -> str:
    role = user.get("role", "employee")
    if role == "admin":
        return "全部数据"
    elif role == "leader":
        return f"{user.get('department', '全部')} 部门"
    else:
        return f"{user.get('department', '')} - {user.get('region', '')}"


    sub_queries = []
    for sid in snapshot_ids:
        sub = inject_snapshot_where(base_sql, [sid])
        sub = re.sub(r'\s*ORDER\s+BY\s+\S+(\s+(ASC|DESC))?\s*$', '', sub,
                     flags=re.IGNORECASE)
        sub_queries.append(sub)

    union_body = "\nUNION ALL\n".join(sub_queries)

    if result_format == "table":
        return (
            f"SELECT label, ROUND(SUM(value), 2) AS value "
            f"FROM (\n{union_body}\n) "
            f"GROUP BY label ORDER BY value DESC"
        )
    elif result_format in ("number", "integer"):
        return f"SELECT ROUND(SUM(value), 2) AS value FROM (\n{union_body}\n)"
    elif result_format == "percent":
        return f"SELECT ROUND(AVG(value), 2) AS value FROM (\n{union_body}\n)"
    else:
        return union_body
