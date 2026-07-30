"""API 限流器 — per-user + per-IP 滑动窗口"""

import time
import threading
from collections import defaultdict

from ..config import config
from .logging import get_logger

logger = get_logger(__name__)


class SlidingWindowLimiter:
    """滑动窗口限流器 (线程安全)"""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """检查是否允许请求, 自动清理过期记录"""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            window = self._windows[key]
            # 清理过期
            while window and window[0] < cutoff:
                window.pop(0)
            # 检查
            if len(window) >= self.max_requests:
                return False
            window.append(now)
            return True

    def remaining(self, key: str) -> int:
        """剩余可用次数"""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            window = self._windows[key]
            while window and window[0] < cutoff:
                window.pop(0)
            return max(0, self.max_requests - len(window))

    def reset(self, key: str):
        """重置计数"""
        with self._lock:
            self._windows.pop(key, None)


# 全局实例 (延迟初始化以使用配置)
_user_limiter = None
_ip_limiter = None
_lock = threading.Lock()


def _get_limiters():
    global _user_limiter, _ip_limiter
    if _user_limiter is None:
        with _lock:
            if _user_limiter is None:
                _user_limiter = SlidingWindowLimiter(
                    max_requests=config.rate_limit_user_per_minute,
                    window_seconds=60,
                )
                _ip_limiter = SlidingWindowLimiter(
                    max_requests=config.rate_limit_ip_per_minute,
                    window_seconds=60,
                )
    return _user_limiter, _ip_limiter


def check_rate_limit(user_id: int, client_ip: str) -> dict:
    """检查限流, 返回 {allowed, retry_after, remaining}"""
    user_limiter, ip_limiter = _get_limiters()
    user_key = f"user:{user_id}"
    ip_key = f"ip:{client_ip}"

    if not ip_limiter.allow(ip_key):
        return {
            "allowed": False,
            "reason": "IP 请求过于频繁",
            "retry_after": 60,
            "remaining": 0,
        }

    if not user_limiter.allow(user_key):
        return {
            "allowed": False,
            "reason": f"用户请求过于频繁 ({user_limiter.max_requests}次/分钟)",
            "retry_after": 60,
            "remaining": 0,
        }

    return {
        "allowed": True,
        "remaining": user_limiter.remaining(user_key),
        "retry_after": 0,
    }
