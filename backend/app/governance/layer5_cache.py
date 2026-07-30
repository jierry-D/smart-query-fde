"""Layer 5: 结果缓存 — SQL 规范化 + TTL 缓存 + 相似查询提示"""

import hashlib
import re
import threading
import time
import json
from collections import OrderedDict

from ..core.logging import get_logger
from ..config import config

logger = get_logger(__name__)

# 预编译模式
_RE_WHITESPACE = re.compile(r'\s+')


class ResultCache:
    """结果缓存 (内存 LRU + TTL, O(1) 淘汰, 线程安全)"""

    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self.ttl = config.governance_cache_ttl
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def apply(self, sql: str) -> dict:
        """
        Returns:
            {"cache_hit": bool, "cached_result": dict | None, "cache_key": str}
        """
        key = self._normalize(sql)

        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry["ts"] < self.ttl:
                    logger.debug("Cache hit: %s...", key[:60])
                    self._cache.move_to_end(key)
                    return {"cache_hit": True, "cached_result": entry["result"], "cache_key": key}
                else:
                    del self._cache[key]

        return {"cache_hit": False, "cached_result": None, "cache_key": key}

    def store(self, key: str, result: dict):
        """存入缓存 (LRU 淘汰)"""
        with self._lock:
            if len(self._cache) >= self.max_size:
                oldest_key, _ = self._cache.popitem(last=False)
                logger.debug("Cache eviction: %s", oldest_key[:60])
            self._cache[key] = {"result": result, "ts": time.time()}

    def clear(self):
        with self._lock:
            self._cache.clear()

    @staticmethod
    def _normalize(sql: str) -> str:
        """规范化 SQL 用于缓存 key"""
        normalized = _RE_WHITESPACE.sub(' ', sql.strip())
        normalized = normalized.lower()
        return hashlib.md5(normalized.encode()).hexdigest()


# ═══════════════════════════════════════════
# Redis 缓存层
# ═══════════════════════════════════════════

class RedisCache:
    """Redis 分布式缓存 — 与 ResultCache 接口兼容"""

    def __init__(self, redis_url: str = None, ttl: int = None):
        self.redis_url = redis_url or config.cache_redis_url
        self.ttl = ttl or config.cache_ttl
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import redis
                self._client = redis.Redis.from_url(
                    self.redis_url,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                    decode_responses=False,
                )
                self._client.ping()  # 验证连接
                logger.info("Redis cache connected: %s", self.redis_url)
            except ImportError:
                raise RuntimeError("redis-py not installed. Run: pip install redis")
            except Exception as e:
                logger.warning("Redis unavailable (%s), falling back to memory cache", e)
                raise
        return self._client

    def apply(self, sql: str) -> dict:
        key = self._normalize(sql)
        try:
            raw = self.client.get(key)
            if raw:
                result = json.loads(raw)
                logger.debug("Redis cache hit: %s...", key[:60])
                return {"cache_hit": True, "cached_result": result, "cache_key": key}
        except Exception as e:
            logger.debug("Redis get error: %s", e)
        return {"cache_hit": False, "cached_result": None, "cache_key": key}

    def store(self, key: str, result: dict):
        try:
            self.client.setex(key, self.ttl, json.dumps(result, ensure_ascii=False))
        except Exception as e:
            logger.debug("Redis set error: %s", e)

    @staticmethod
    def _normalize(sql: str) -> str:
        import re
        normalized = sql.strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.lower()
        return f"sq:cache:{hashlib.md5(normalized.encode()).hexdigest()}"


def get_cache() -> ResultCache:
    """工厂函数: 根据配置返回缓存实例"""
    if config.cache_type == "redis":
        try:
            return RedisCache()
        except Exception:
            logger.info("Falling back to memory cache")
    return ResultCache()
