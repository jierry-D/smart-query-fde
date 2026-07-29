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
        return self._get("database", "type", default="sqlite")

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
            import os
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
