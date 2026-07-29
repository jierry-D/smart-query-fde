"""认证 API — 登录、刷新、获取当前用户"""

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_token_id,
)
from ...core.deps import get_current_user
from ...database import DatabaseConnector
from ...schemas import LoginRequest, RefreshRequest

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _get_db():
    return DatabaseConnector()


@router.post("/login")
def login(req: LoginRequest):
    """
    用户登录 — 返回 JWT access_token + refresh_token

    测试用户:
    - admin / admin123 (管理员，看全部数据)
    - leader / leader123 (领导，看本部门全部数据)
    - employee / emp123 (员工，只看自己部门+区域)
    """
    db = _get_db()
    user = db.get_user_by_username(req.username)

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    # 创建 tokens
    token_data = {
        "sub": str(user["user_id"]),
        "username": user["username"],
        "role": user["role"],
        "department": user.get("department", ""),
        "region": user.get("region", ""),
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # 更新登录统计
    db.execute_write(
        "UPDATE users SET last_login = CURRENT_TIMESTAMP, login_count = login_count + 1 "
        "WHERE user_id = ?",
        (user["user_id"],),
    )

    # 保存 refresh token
    from datetime import datetime, timedelta, timezone
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    db.execute_write(
        "INSERT INTO refresh_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["user_id"], refresh_token, expires.strftime("%Y-%m-%d %H:%M:%S")),
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "department": user.get("department", ""),
            "region": user.get("region", ""),
            "position": user.get("position", ""),
        },
    }


@router.post("/refresh")
def refresh_token(req: RefreshRequest):
    """刷新 access token"""
    payload = decode_token(req.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token 无效或已过期",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请使用 refresh token",
        )

    # 创建新的 access token
    token_data = {
        "sub": payload["sub"],
        "username": payload["username"],
        "role": payload["role"],
        "department": payload.get("department", ""),
        "region": payload.get("region", ""),
    }

    return {
        "access_token": create_access_token(token_data),
        "token_type": "bearer",
        "expires_in": 3600,
    }


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """获取当前用户信息与权限范围"""
    db = _get_db()
    full_user = db.get_user_by_id(user["user_id"])

    from ...core.security import get_data_scope, get_role_permissions

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": full_user.get("display_name", "") if full_user else "",
        "role": user["role"],
        "department": user.get("department", ""),
        "region": user.get("region", ""),
        "position": full_user.get("position", "") if full_user else "",
        "permissions": get_role_permissions(user["role"]),
        "data_scope": get_data_scope(user),
        "data_scope_description": _describe_scope(user),
    }


def _describe_scope(user: dict) -> str:
    """描述用户数据范围 (供前端展示)"""
    role = user["role"]
    if role == "admin":
        return "全部数据 (管理员)"
    elif role == "leader":
        dept = user.get("department", "全部")
        return f"{dept} 全部数据 (领导视图)"
    else:
        dept = user.get("department", "")
        region = user.get("region", "")
        return f"{dept} - {region} (员工视图)"
