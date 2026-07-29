"""结构化日志系统"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def init_logging(
    level: str = "INFO",
    console: bool = True,
    log_file: str | None = None,
    max_bytes: int = 10485760,
    backup_count: int = 7,
):
    """初始化全局日志配置"""
    root = logging.getLogger("smart_query")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if console:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(fmt)
        root.addHandler(h)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        h.setFormatter(fmt)
        root.addHandler(h)

    # 降低第三方库日志等级
    for name in ("uvicorn", "chromadb", "httpx", "openai", "sqlalchemy"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger"""
    return logging.getLogger(f"smart_query.{name}")
