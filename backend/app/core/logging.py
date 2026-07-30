"""结构化日志系统"""

import logging
import sys
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 请求级 correlation_id — 跨模块追踪
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class CorrelationFilter(logging.Filter):
    """将 correlation_id 注入日志记录"""

    def filter(self, record):
        cid = correlation_id.get()
        record.correlation_id = cid if cid else "-"
        return True


def init_logging(
    level: str = "INFO",
    console: bool = True,
    log_file: str | None = None,
    max_bytes: int = 10485760,
    backup_count: int = 7,
):
    """初始化全局日志配置"""
    root = logging.getLogger("smart_query")
    root.setLevel(_LEVELS.get(level.upper(), logging.INFO))
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(correlation_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 关联 ID 过滤器
    cid_filter = CorrelationFilter()

    if console:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(fmt)
        h.addFilter(cid_filter)
        root.addHandler(h)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        h.setFormatter(fmt)
        h.addFilter(cid_filter)
        root.addHandler(h)

    # 降低第三方库日志等级
    for name in ("uvicorn", "chromadb", "httpx", "openai", "sqlalchemy"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger"""
    return logging.getLogger(f"smart_query.{name}")


def set_correlation_id() -> str:
    """生成并设置新的 correlation_id，返回 ID"""
    cid = uuid.uuid4().hex[:12]
    correlation_id.set(cid)
    return cid
