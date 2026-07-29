"""Layer 4: 执行保护 — 超时、熔断、只读确认"""

import time

from ..core.logging import get_logger
from ..config import config

logger = get_logger(__name__)


class ExecutionGuard:
    """执行保护器 — 熔断器 + 超时控制"""

    def __init__(self):
        self.timeout = config.governance_query_timeout
        self._failure_count = 0
        self._failure_threshold = config._get("governance", "circuit_breaker_failures", default=5)
        self._circuit_open_until = 0  # 0 = closed

    def apply(self, sql: str) -> dict:
        """
        Returns:
            {"denied": bool, "reason": str | None, "retry_after": int | None}
        """
        # 熔断器检查
        if self._is_circuit_open():
            wait = int(self._circuit_open_until - time.time())
            return {
                "denied": True,
                "reason": f"系统熔断保护中，请 {wait}s 后重试",
                "retry_after": max(wait, 0),
            }

        return {"denied": False}

    def record_success(self):
        """记录成功，重置失败计数"""
        self._failure_count = 0

    def record_failure(self):
        """记录失败，可能触发熔断"""
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._circuit_open_until = time.time() + config._get(
                "governance", "circuit_breaker_timeout", default=30
            )
            logger.warning("熔断器触发: %d 次连续失败", self._failure_count)

    def _is_circuit_open(self) -> bool:
        return time.time() < self._circuit_open_until
