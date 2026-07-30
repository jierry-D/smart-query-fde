"""Alembic 迁移环境配置"""

from logging.config import fileConfig
from alembic import context

# Alembic Config 对象
config = context.config

# 日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从环境变量读取数据库 URL
import os
database_url = os.environ.get("DATABASE_URL", "sqlite:///backend/db/smart_query.db")
config.set_main_option("sqlalchemy.url", database_url)

# 目标元数据 (空 — 因为我们不使用 SQLAlchemy ORM，直接手写迁移)
target_metadata = None


def run_migrations_offline() -> None:
    """离线模式 — 仅生成 SQL"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式 — 直接执行"""
    from sqlalchemy import create_engine
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
