"""FastAPI 应用工厂 — 主入口"""

import sqlite3
import sys
import webbrowser
import threading
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import config
from .core.logging import init_logging, get_logger
from .core.rate_limiter import check_rate_limit
from .core.metrics import metrics_middleware, metrics_endpoint

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""

    app = FastAPI(
        title="智慧问数系统 v2.0",
        description="企业级 NL2SQL 智能数据查询系统 — 支持三级 RBAC 权限",
        version="2.0.0",
    )

    # Rate Limiter 中间件
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi import Request
    from fastapi.responses import JSONResponse

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # 跳过静态文件/文档/健康检查
            if request.url.path.startswith(("/static", "/docs", "/openapi.json", "/api/health", "/metrics")):
                return await call_next(request)
            client_ip = request.client.host if request.client else "127.0.0.1"
            if client_ip in ("127.0.0.1", "localhost", "::1", "testclient"):
                return await call_next(request)

            # 从 JWT token 解码用户 ID (简约版——不依赖完整依赖注入)
            user_id = 0
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    from .core.security import decode_token
                    payload = decode_token(auth_header[7:])
                    user_id = payload.get("user_id", 0)
                except Exception:
                    pass  # token 无效时使用 IP 限流兜底

            result = check_rate_limit(user_id, client_ip)
            if not result["allowed"]:
                return JSONResponse(
                    status_code=429,
                    content={"detail": result["reason"], "retry_after": result["retry_after"]},
                    headers={"X-RateLimit-Remaining": "0", "Retry-After": str(result["retry_after"])},
                )
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(result["remaining"])
            return response

    app.add_middleware(RateLimitMiddleware)

    # Prometheus 指标中间件
    app.middleware("http")(metrics_middleware)

    # 注册 /metrics 端点
    metrics_endpoint(app)

    # CORS (从配置读取)
    cors_origins = getattr(config, 'cors_origins', ["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 安全响应头中间件
    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            if request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # 注册路由
    from .api.routers import auth, chat, metrics, snapshots, import_route, admin, feedback

    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(metrics.router)
    app.include_router(snapshots.router)
    app.include_router(import_route.router)
    app.include_router(admin.router)
    app.include_router(feedback.router)

    # 静态文件 (开发模式: 直接从 frontend/ 提供)
    static_dir = _PROJECT_ROOT.parent / "frontend"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/api/status")
    def get_status():
        """系统状态（完整信息，用于仪表盘）"""
        from .database import DatabaseConnector
        db = DatabaseConnector()

        tables = [t for t in db.get_tables()
                  if t not in ('data_snapshots', 'sqlite_sequence', 'metric_registry')
                  and '指标需求' not in t]

        return {
            "date": str(date.today()),
            "version": "2.0.0",
            "tables": len(tables),
            "snapshots": len(db.get_snapshots()),
            "metrics_total": len(db.execute("SELECT * FROM metric_registry")),
            "metrics_available": len(db.execute(
                "SELECT * FROM metric_registry WHERE status='available'"
            )),
            "users": len(db.get_all_users()),
            "rate_limit": {
                "user_per_minute": config.rate_limit_user_per_minute,
                "ip_per_minute": config.rate_limit_ip_per_minute,
            },
            "cache_type": config.cache_type,
            "db_type": config.db_type,
        }

    @app.get("/api/health")
    def health_check():
        """轻量健康检查 — 供 Docker / K8s liveness probe 使用"""
        from .database import DatabaseConnector
        try:
            db = DatabaseConnector()
            db.execute("SELECT 1")
            return {"status": "ok", "db": "connected"}
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={"status": "unhealthy", "db": str(e)},
            )

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        """服务前端 — React build > legacy SPA > API fallback"""
        # 跳过 API 路由
        if path.startswith("api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # 1. React 生产构建: frontend/dist/
        dist_dir = _PROJECT_ROOT.parent / "frontend" / "dist"
        if dist_dir.exists():
            file_path = dist_dir / path if path else dist_dir / "index.html"
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(dist_dir / "index.html"))

        # 2. Legacy SPA: frontend-legacy/
        legacy_dir = _PROJECT_ROOT.parent / "frontend-legacy"
        if legacy_dir.exists() and (not path or path == "index.html"):
            index = legacy_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))

        # 3. API 信息 (开发模式)
        return {
            "message": "智慧问数系统 v2.1 API",
            "docs": "/docs",
            "login": "/api/auth/login",
            "test_users": {
                "admin": "admin/admin123",
                "leader": "leader/leader123",
                "employee": "employee/emp123",
            },
            "frontend": "React dev: cd frontend && npm run dev (port 3000)",
        }

    return app


app = create_app()


def main():
    """启动入口"""
    import uvicorn

    init_logging(
        level=config.log_level,
        console=config.log_console,
        log_file=config.log_file,
        max_bytes=config.log_max_bytes,
        backup_count=config.log_backup_count,
    )

    # 确保数据库存在
    db_path = Path(config.db_path)
    if not db_path.exists():
        logger.warning("数据库不存在, 请先运行: python backend/db/init_db.py")
        # 尝试自动初始化
        from .database import DatabaseConnector
        db = DatabaseConnector(str(db_path))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS data_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL DEFAULT '',
            data_period TEXT NOT NULL,
            ingestion_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            total_rows INTEGER DEFAULT 0,
            UNIQUE(table_name, data_period))""")
        conn.commit()
        conn.close()
        logger.info("已创建空数据库, 请运行 init_db.py 填充数据")

    # 自动打开浏览器
    if config.web_auto_open:
        def _open():
            webbrowser.open(f"http://{config.web_host}:{config.web_port}")
        threading.Timer(1.0, _open).start()

    logger.info("启动服务: http://%s:%s", config.web_host, config.web_port)
    logger.info("API 文档: http://%s:%s/docs", config.web_host, config.web_port)

    uvicorn.run(
        "backend.app.main:app",
        host=config.web_host,
        port=config.web_port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
