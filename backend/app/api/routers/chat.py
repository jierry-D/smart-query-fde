"""对话 API — NL2SQL 查询 + 命令处理 (SSE 流式)"""

import json
import time
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ...core.deps import get_current_user
from ...core.security import build_data_scope_sql, get_data_scope
from ...database import DatabaseConnector
from ...schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["对话"])


def _get_db():
    return DatabaseConnector()


# ── SSE 流式查询 ──

@router.post("/chat")
def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
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

    # 自然语言查询
    return _handle_query(user_input, db, user)


# ── 查询处理 ──

def _handle_query(query: str, db: DatabaseConnector, user: dict) -> dict:
    """完整的 NL2SQL 查询流水线 — 使用 Pipeline + Governance 模块"""

    # 尝试初始化 LLM (可选, 无 Key 时降级为模板)
    llm = None
    try:
        from ...llm.deepseek import get_llm
        llm = get_llm()
    except Exception:
        pass

    # 使用统一流水线
    from ...engine.pipeline import NL2SQLPipeline
    pipeline = NL2SQLPipeline(db, llm_provider=llm)
    result = pipeline.run(query, user)

    # 记录查询日志
    try:
        db.log_query(
            user_id=user["user_id"], username=user["username"],
            role=user["role"], original_query=query,
            cleaned_query=query, generated_sql=result.get("sql", ""),
            intent=result.get("entity_tags", [{}])[0].get("type", "") if result.get("entity_tags") else "",
            exec_time_ms=result.get("exec_ms", 0), row_count=result.get("row_count", 0),
            status="success" if result.get("type") not in ("error", "pending") else result.get("type"),
            error_message=result.get("message", ""),
            snapshot_ids=json.dumps([s.get("snapshot_id") for s in db.get_snapshots()[:1]]) if db.get_snapshots() else None,
        )
    except Exception:
        pass  # 日志失败不影响主流程

    # 附带原始查询供前端反馈使用
    result["_query"] = query
    return result


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


def _build_entity_tags(entities: dict) -> list:
    tags = []
    for f in entities.get("filters", []):
        tags.append({"type": "filter", "label": f"{f['field']}={f['value']}"})
    if entities.get("group_by"):
        names = {"region": "按区域", "business_line": "按业务线"}
        tags.append({"type": "group", "label": names.get(entities["group_by"], entities["group_by"])})
    if entities.get("limit"):
        tags.append({"type": "limit", "label": f"Top {entities['limit']}"})
    return tags


def _scope_desc(user: dict) -> str:
    role = user.get("role", "employee")
    if role == "admin":
        return "全部数据"
    elif role == "leader":
        return f"{user.get('department', '全部')} 部门"
    else:
        return f"{user.get('department', '')} - {user.get('region', '')}"


def _build_union_sql(base_sql: str, result_format: str, snapshot_ids: list) -> str:
    """多快照 UNION ALL 聚合"""
    from ...engine.sql_filter import inject_snapshot_where

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
