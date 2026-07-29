"""Layer 1: 权限校验 — RBAC + 数据范围过滤"""

from ..core.security import build_data_scope_sql
from ..engine.sql_filter import inject_data_scope
from ..core.logging import get_logger

logger = get_logger(__name__)


class AuthFilter:
    """将用户 RBAC 数据范围注入 SQL"""

    def apply(self, sql: str, user: dict) -> dict:
        """
        Returns:
            {"denied": bool, "sql": str, "scope_label": str}
        """
        role = user.get("role", "employee")
        scope_sql = build_data_scope_sql(user)

        injected = inject_data_scope(sql, scope_sql)

        if role == "admin":
            label = "全部数据"
        elif role == "leader":
            label = f"{user.get('department', '全部')} (全部区域)"
        else:
            label = f"{user.get('department', '')} - {user.get('region', '')}"

        logger.debug("Layer1 auth: role=%s scope=%s", role, scope_sql)
        return {"denied": False, "sql": injected, "scope_label": label}
