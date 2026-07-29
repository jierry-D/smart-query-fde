"""Layer 5: 结果缓存 — SQL 规范化 + TTL 缓存 + 相似查询提示"""

import hashlib
import time

from ..core.logging import get_logger
from ..config import config

logger = get_logger(__name__)


class ResultCache:
    """结果缓存 (内存 LRU + TTL)"""

    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self.ttl = config.governance_cache_ttl  # 默认 300s
        self._cache: dict[str, dict] = {}  # key → {result, ts}

    def apply(self, sql: str) -> dict:
        """
        Returns:
            {"cache_hit": bool, "cached_result": dict | None, "cache_key": str}
        """
        key = self._normalize(sql)

        if key in self._cache:
            entry = self._cache[key]
            if time.time() - entry["ts"] < self.ttl:
                logger.debug("Cache hit: %s...", key[:60])
                return {"cache_hit": True, "cached_result": entry["result"], "cache_key": key}
            else:
                del self._cache[key]

        return {"cache_hit": False, "cached_result": None, "cache_key": key}

    def store(self, key: str, result: dict):
        """存入缓存"""
        if len(self._cache) >= self.max_size:
            # 淘汰最老的条目
            oldest = min(self._cache.items(), key=lambda x: x[1]["ts"])
            del self._cache[oldest[0]]

        self._cache[key] = {"result": result, "ts": time.time()}

    @staticmethod
    def _normalize(sql: str) -> str:
        """规范化 SQL 用于缓存 key"""
        import re
        normalized = sql.strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.lower()
        return hashlib.md5(normalized.encode()).hexdigest()
