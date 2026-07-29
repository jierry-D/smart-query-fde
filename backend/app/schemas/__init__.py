"""请求/响应 Pydantic 模型"""

from pydantic import BaseModel, Field
from typing import Optional


# ── 认证 ──

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


# ── 对话 ──

class ChatRequest(BaseModel):
    q: str = Field(..., max_length=500, description="自然语言查询或 /命令")
    conversation_id: Optional[str] = None


# ── 指标 ──

class MetricItem(BaseModel):
    metric_id: str
    name: str
    category: str
    status: str
    explanation: str = ""
    formula: str = ""
    source: str = ""
    complexity: str = "L1"
    result_format: str = "number"
    result_unit: str = ""


# ── 通用 ──

class StatusResponse(BaseModel):
    date: str
    version: str
    tables: int
    snapshots: int
    metrics_total: int
    metrics_available: int
    users: int
