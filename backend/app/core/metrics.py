"""Prometheus 指标 — 请求计数、延迟、错误率、缓存命中率"""

import time
from functools import wraps
from typing import Callable

from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from fastapi import Request, Response

# ── 指标定义 ──

# API 请求
http_requests_total = Counter(
    "sq_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "sq_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# 查询
query_total = Counter(
    "sq_query_total",
    "Total NL2SQL queries",
    ["status", "user_role"],
)

query_duration_seconds = Histogram(
    "sq_query_duration_seconds",
    "NL2SQL query latency",
    ["complexity"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# 缓存
cache_hits = Counter("sq_cache_hits_total", "Cache hit count")
cache_misses = Counter("sq_cache_misses_total", "Cache miss count")

# 系统
active_users = Gauge("sq_active_users", "Active users (last 5 min)")
db_connections = Gauge("sq_db_connections", "Active DB connections")
circuit_breaker_open = Gauge("sq_circuit_breaker_open", "Circuit breaker state (0=closed, 1=open)")


# ── 中间件 ──

async def metrics_middleware(request: Request, call_next) -> Response:
    """记录所有 HTTP 请求指标"""
    path = request.url.path
    # 跳过 metrics 端点自身
    if path == "/metrics":
        return await call_next(request)

    method = request.method
    endpoint = path.split("/")[2] if len(path.split("/")) > 2 else "root"

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    http_requests_total.labels(method=method, endpoint=endpoint, status=response.status_code).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(elapsed)

    return response


def metrics_endpoint(app):
    """注册 /metrics 端点"""

    @app.get("/metrics")
    async def metrics():
        return Response(
            content=generate_latest(REGISTRY),
            media_type="text/plain; charset=utf-8",
        )


# ── 辅助函数 ──

def record_query(status: str, user_role: str, complexity: str = "L1", duration: float = 0.0):
    """记录查询指标"""
    query_total.labels(status=status, user_role=user_role).inc()
    query_duration_seconds.labels(complexity=complexity).observe(duration)


def record_cache(hit: bool):
    """记录缓存命中/未命中"""
    if hit:
        cache_hits.inc()
    else:
        cache_misses.inc()
