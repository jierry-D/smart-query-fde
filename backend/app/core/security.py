"""安全模块 — JWT 生成/验证, bcrypt 密码哈希, RBAC 数据范围"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from ..config import config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── 密码 ──────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """创建 access token (短期, 1小时)"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.jwt_access_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, config.jwt_secret_key, algorithm=config.jwt_algorithm)


def create_refresh_token(data: dict) -> str:
    """创建 refresh token (长期, 7天)"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=config.jwt_refresh_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, config.jwt_secret_key, algorithm=config.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    """解码 JWT token, 失败返回 None"""
    try:
        return jwt.decode(token, config.jwt_secret_key, algorithms=[config.jwt_algorithm])
    except JWTError:
        return None


def generate_token_id() -> str:
    """生成随机 token ID"""
    return secrets.token_urlsafe(32)


# ── RBAC 数据范围 ─────────────────────────────────

def get_data_scope(user: dict) -> dict:
    """
    返回该用户的 SQL WHERE 过滤条件.

    Args:
        user: 用户字典, 含 role, department, region

    Returns:
        dict: 过滤条件 {field: value}, 空字典 = 无过滤
    """
    role = user.get("role", "employee")

    if role == "admin":
        return {}  # 管理员: 无过滤, 看全部

    if role == "leader":
        dept = user.get("department", "")
        if dept:
            return {"department": dept}  # 领导: 看本部门全部
        return {}

    # employee: 部门 + 区域双重过滤
    dept = user.get("department", "")
    region = user.get("region", "")
    scope = {}
    if dept:
        scope["department"] = dept
    if region:
        scope["region"] = region
    return scope


def build_data_scope_sql(user: dict, table_alias: str = "") -> str:
    """
    构建数据范围 SQL WHERE 子句.

    安全说明: 值来自数据库中已存储的用户属性 (department/region),
    不是用户直接输入, 且经过字段白名单 + 单引号转义双重防护.

    Args:
        user: 用户字典
        table_alias: 表别名前缀 (如 "b.")

    Returns:
        str: SQL WHERE 条件, 如 "b.department = '数字政务事业部' AND b.region = '南宁市'"
    """
    import re
    scope = get_data_scope(user)
    if not scope:
        return "1=1"

    # 字段白名单: 只允许这两个已知字段
    ALLOWED_FIELDS = {"department", "region"}

    prefix = f"{table_alias}." if table_alias else ""
    conditions = []
    for field, value in scope.items():
        if field not in ALLOWED_FIELDS:
            continue
        # 清理字段名 (防止非法字符)
        safe_field = re.sub(r'[^a-zA-Z_]', '', field)
        # 转义值中的单引号 (标准 SQL 转义)
        safe_value = str(value).replace("'", "''")
        conditions.append(f"{prefix}{safe_field} = '{safe_value}'")

    if not conditions:
        return "1=1"

    return " AND ".join(conditions)


# ── 角色权限检查 ──────────────────────────────────

ROLE_PERMISSIONS = {
    "admin": [
        "query", "view_metrics", "view_all_data",
        "import_data", "manage_users", "manage_system",
        "view_audit_logs", "view_query_logs",
    ],
    "leader": [
        "query", "view_metrics", "view_all_data",
        "import_data",
    ],
    "employee": [
        "query", "view_metrics", "view_own_data",
    ],
}


def get_role_permissions(role: str) -> list[str]:
    return ROLE_PERMISSIONS.get(role, [])


def has_permission(user: dict, permission: str) -> bool:
    role = user.get("role", "employee")
    return permission in get_role_permissions(role)
