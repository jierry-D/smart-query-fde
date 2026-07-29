"""管理 API — 仅 admin 角色可访问"""

from fastapi import APIRouter, Depends, HTTPException

from ...core.deps import get_current_user, require_admin
from ...core.security import hash_password
from ...database import DatabaseConnector

router = APIRouter(prefix="/api/admin", tags=["管理"])


def _get_db():
    return DatabaseConnector()


@router.get("/users")
def list_users(admin: dict = Depends(require_admin)):
    """获取所有用户列表"""
    db = _get_db()
    return {"users": db.get_all_users(), "total": len(db.get_all_users())}


@router.post("/users")
def create_user(req: dict, admin: dict = Depends(require_admin)):
    """创建或更新用户"""
    db = _get_db()

    username = req.get("username", "").strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")

    existing = db.get_user_by_username(username)

    if existing:
        # 更新
        updates = []
        params = []
        for field in ["display_name", "role", "department", "region", "position"]:
            if field in req:
                updates.append(f"{field} = ?")
                params.append(req[field])
        if req.get("password"):
            updates.append("password_hash = ?")
            params.append(hash_password(req["password"]))
        if updates:
            params.append(existing["user_id"])
            db.execute_write(
                f"UPDATE users SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE user_id = ?",
                tuple(params),
            )
        return {"status": "updated", "user_id": existing["user_id"]}
    else:
        # 创建
        user_id = db.execute_write(
            "INSERT INTO users (username, password_hash, display_name, role, department, region, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, hash_password(req.get("password", "123456")),
             req.get("display_name", username), req.get("role", "employee"),
             req.get("department", ""), req.get("region", ""), req.get("position", "")),
        )
        return {"status": "created", "user_id": user_id}


@router.put("/users/{user_id}/toggle")
def toggle_user(user_id: int, admin: dict = Depends(require_admin)):
    """启用/禁用用户"""
    db = _get_db()
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    new_active = 0 if user.get("is_active") else 1
    db.execute_write("UPDATE users SET is_active = ? WHERE user_id = ?", (new_active, user_id))
    return {"user_id": user_id, "is_active": bool(new_active)}


@router.get("/logs")
def get_logs(limit: int = 50, user_id: int = None,
             admin: dict = Depends(require_admin)):
    """获取查询日志"""
    db = _get_db()
    logs = db.get_query_history(user_id=user_id, limit=limit)
    return {"logs": logs, "total": len(logs)}


@router.get("/stats")
def get_stats(admin: dict = Depends(require_admin)):
    """系统统计"""
    db = _get_db()
    return {
        "users": len(db.get_all_users()),
        "active_users": len([u for u in db.get_all_users() if u.get("is_active")]),
        "snapshots": len(db.get_snapshots()),
        "metrics_registered": len(db.execute("SELECT * FROM metric_registry")),
        "metrics_available": len(db.execute(
            "SELECT * FROM metric_registry WHERE status='available'"
        )),
        "total_queries": db.execute("SELECT COUNT(*) AS cnt FROM query_logs")[0]["cnt"] if _table_exists(db, "query_logs") else 0,
        "recent_queries": db.execute(
            "SELECT COUNT(*) AS cnt FROM query_logs WHERE created_at >= datetime('now', '-7 days')"
        )[0]["cnt"] if _table_exists(db, "query_logs") else 0,
    }


@router.get("/db-tables")
def list_db_tables(admin: dict = Depends(require_admin)):
    """浏览数据库结构 (仅 admin)"""
    db = _get_db()
    tables = db.get_tables()
    result = []
    for t in tables:
        try:
            schema = db.get_table_schema(t)
            cnt = db.execute(f"SELECT COUNT(*) AS cnt FROM \"{t}\"")[0]["cnt"]
            result.append({
                "table_name": t,
                "columns": [{"name": c["name"], "type": c["type"]} for c in schema],
                "row_count": cnt,
            })
        except Exception:
            result.append({"table_name": t, "error": "无法读取"})
    return {"tables": result}


def _table_exists(db, name):
    try:
        db.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except Exception:
        return False
