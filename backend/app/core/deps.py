"""FastAPI 依赖注入 — 用户认证、角色检查"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .security import decode_token, has_permission

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> dict:
    """
    从 JWT token 提取当前用户信息.
    如果无 token 或 token 无效, 抛出 401.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期, 请重新登录",
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请使用 access token",
        )

    return {
        "user_id": int(payload.get("sub", 0)),
        "username": payload.get("username", ""),
        "role": payload.get("role", "employee"),
        "department": payload.get("department", ""),
        "region": payload.get("region", ""),
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Optional[dict]:
    """获取当前用户, 无 token 时返回 None (不抛异常)"""
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None:
        return None
    return {
        "user_id": int(payload.get("sub", 0)),
        "username": payload.get("username", ""),
        "role": payload.get("role", "employee"),
        "department": payload.get("department", ""),
        "region": payload.get("region", ""),
    }


def require_role(*roles: str):
    """依赖工厂: 要求用户具备指定角色之一"""

    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {roles} 权限",
            )
        return user

    return checker


def require_permission(permission: str):
    """依赖工厂: 要求用户具备指定权限"""

    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {permission} 权限",
            )
        return user

    return checker


# 预定义的角色检查器
require_admin = require_role("admin")
require_leader_or_admin = require_role("leader", "admin")
