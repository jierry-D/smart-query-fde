"""FastAPI 应用工厂 — 主入口"""

import sys
import webbrowser
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import config
from .core.logging import init_logging, get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""

    app = FastAPI(
        title="智慧问数系统 v2.0",
        description="企业级 NL2SQL 智能数据查询系统 — 支持三级 RBAC 权限",
        version="2.0.0",
    )

    # CORS (从配置读取)
    cors_origins = getattr(config, 'cors_origins', ["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        """系统状态"""
        from datetime import date
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
        }

    @app.get("/")
    def index():
        # 优先: frontend/index.html
        index_path = _PROJECT_ROOT.parent / "frontend" / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        # 备选: frontend/dist/index.html (构建后)
        dist_path = _PROJECT_ROOT.parent / "frontend" / "dist" / "index.html"
        if dist_path.exists():
            return FileResponse(str(dist_path))
        # 开发模式下返回 API 信息
        return {
            "message": "智慧问数系统 v2.0 API",
            "docs": "/docs",
            "login": "/api/auth/login",
            "test_users": {
                "admin": "admin/admin123",
                "leader": "leader/leader123",
                "employee": "employee/emp123",
            },
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
        import sqlite3
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
