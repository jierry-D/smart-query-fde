"""集中配置管理 — YAML + 环境变量"""

import os
import re
from pathlib import Path
from typing import Optional

import yaml


PROJECT_ROOT = Path(__file__).parent.parent.parent


def _resolve_path(relative: str) -> str:
    """将相对路径转为绝对路径"""
    p = Path(relative)
    if p.is_absolute():
        return str(p)
    return str(PROJECT_ROOT / p)


def _expand_env(value: str) -> str:
    """展开 ${VAR:-default} 格式的环境变量"""
    pattern = re.compile(r'\$\{(\w+)(?::-(.*?))?\}')

    def _replace(match):
        var_name = match.group(1)
        default = match.group(2) if match.group(2) is not None else ""
        return os.environ.get(var_name, default)

    return pattern.sub(_replace, value)


class Config:
    """配置单例"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self):
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self):
        config_path = PROJECT_ROOT / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                raw = f.read()
            raw = _expand_env(raw)
            self._data = yaml.safe_load(raw) or {}
        else:
            self._data = {}

    def _get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
            else:
                return default
        return node if node is not None else default

    # ── 数据库 ──

    @property
    def cors_origins(self) -> list[str]:
        return self._get("cors", "origins", default=["*"])

    @property
    def db_path(self) -> str:
        return _resolve_path(self._get("database", "path", default="backend/db/smart_query.db"))

    @property
    def db_type(self) -> str:
        env = os.environ.get("DATABASE_URL", "")
        if env.startswith("postgres"):
            return "postgresql"
        return self._get("database", "type", default="sqlite")

    @property
    def database_url(self) -> str:
        """环境变量 DATABASE_URL 优先，否则从 YAML 构建"""
        env = os.environ.get("DATABASE_URL", "")
        if env:
            return env
        if self.db_type == "postgresql":
            pg = self._get("database", "postgresql", default={})
            return (
                f"postgresql://{pg.get('user','smart_query')}:{pg.get('password','smart_query')}"
                f"@{pg.get('host','localhost')}:{pg.get('port',5432)}/{pg.get('dbname','smart_query')}"
            )
        return self.db_path

    @property
    def pg_host(self) -> str:
        return self._get("database", "postgresql", "host", default="localhost")

    @property
    def pg_port(self) -> int:
        return self._get("database", "postgresql", "port", default=5432)

    @property
    def pg_dbname(self) -> str:
        return self._get("database", "postgresql", "dbname", default="smart_query")

    @property
    def pg_user(self) -> str:
        return self._get("database", "postgresql", "user", default="smart_query")

    @property
    def pg_password(self) -> str:
        return self._get("database", "postgresql", "password", default="smart_query")

    @property
    def pg_pool_min(self) -> int:
        return self._get("database", "postgresql", "pool_min", default=1)

    @property
    def pg_pool_max(self) -> int:
        return self._get("database", "postgresql", "pool_max", default=10)

    # ── 缓存 ──

    @property
    def cache_type(self) -> str:
        return self._get("cache", "type", default="memory")

    @property
    def cache_redis_url(self) -> str:
        return self._get("cache", "redis_url", default="redis://localhost:6379/0")

    @property
    def cache_ttl(self) -> int:
        return self._get("cache", "ttl_seconds", default=300)

    # ── 限流 ──

    @property
    def rate_limit_user_per_minute(self) -> int:
        return self._get("rate_limit", "user_per_minute", default=30)

    @property
    def rate_limit_ip_per_minute(self) -> int:
        return self._get("rate_limit", "ip_per_minute", default=100)

    # ── 向量存储 ──

    @property
    def vector_store_type(self) -> str:
        return self._get("vector_store", "type", default="chromadb")

    @property
    def vector_store_persist_dir(self) -> str:
        return _resolve_path(self._get("vector_store", "persist_dir", default="backend/db/chroma"))

    # ── Web ──

    @property
    def web_host(self) -> str:
        env = os.environ.get("SQ_WEB_HOST")
        return env or self._get("web", "host", default="127.0.0.1")

    @property
    def web_port(self) -> int:
        env = os.environ.get("SQ_WEB_PORT")
        return int(env) if env else self._get("web", "port", default=5000)

    @property
    def web_auto_open(self) -> bool:
        return self._get("web", "auto_open_browser", default=True)

    # ── JWT ──

    @property
    def jwt_secret_key(self) -> str:
        key = self._get("jwt", "secret_key", default="smart-query-dev-secret-change-in-production")
        if "change-in-production" in key:
            if os.environ.get("SQ_ENV", "dev") != "dev":
                raise ValueError("JWT_SECRET_KEY 未设置! 生产环境通过环境变量 JWT_SECRET_KEY 设置")
        return key

    @property
    def jwt_algorithm(self) -> str:
        return self._get("jwt", "algorithm", default="HS256")

    @property
    def jwt_access_expire_minutes(self) -> int:
        return self._get("jwt", "access_token_expire_minutes", default=60)

    @property
    def jwt_refresh_expire_days(self) -> int:
        return self._get("jwt", "refresh_token_expire_days", default=7)

    # ── 日志 ──

    @property
    def log_level(self) -> str:
        env = os.environ.get("SQ_LOG_LEVEL")
        return env or self._get("logging", "level", default="INFO")

    @property
    def log_console(self) -> bool:
        return self._get("logging", "console", default=True)

    @property
    def log_file(self) -> Optional[str]:
        f = self._get("logging", "file")
        return _resolve_path(f) if f else None

    @property
    def log_max_bytes(self) -> int:
        return self._get("logging", "max_bytes", default=10485760)

    @property
    def log_backup_count(self) -> int:
        return self._get("logging", "backup_count", default=7)

    # ── 指标 ──

    @property
    def metrics_yaml_path(self) -> str:
        return _resolve_path(self._get("metrics", "yaml_path", default="backend/metrics/metric_dict.yaml"))

    @property
    def enterprise_kb_path(self) -> str:
        return _resolve_path(self._get("metrics", "enterprise_kb_path", default="backend/metrics/enterprise_kb.yaml"))

    # ── LLM ──

    @property
    def llm_provider(self) -> str:
        return self._get("llm", "provider", default="deepseek")

    @property
    def deepseek_api_key(self) -> str:
        return self._get("llm", "deepseek", "api_key", default="")

    @property
    def deepseek_base_url(self) -> str:
        return self._get("llm", "deepseek", "base_url", default="https://api.deepseek.com")

    @property
    def llm_timeout(self) -> int:
        return self._get("llm", "timeout_seconds", default=30)

    @property
    def llm_max_retries(self) -> int:
        return self._get("llm", "max_retries", default=2)

    # ── 查询治理 ──

    @property
    def governance_max_scan_rows(self) -> int:
        return self._get("governance", "max_scan_rows", default=500000)

    @property
    def governance_warn_scan_rows(self) -> int:
        return self._get("governance", "warn_scan_rows", default=100000)

    @property
    def governance_query_timeout(self) -> int:
        return self._get("governance", "query_timeout_seconds", default=30)

    @property
    def governance_cache_ttl(self) -> int:
        return self._get("governance", "cache_ttl_seconds", default=300)

    @property
    def governance_max_result_rows(self) -> int:
        return self._get("governance", "max_result_rows", default=10000)


config = Config()
