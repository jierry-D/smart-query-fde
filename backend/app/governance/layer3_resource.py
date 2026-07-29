"""Layer 3: 资源预估 — EXPLAIN 扫描行数，超限拒绝"""

from ..core.logging import get_logger
from ..config import config

logger = get_logger(__name__)


class ResourceEstimator:
    """资源预估器 — 通过 EXPLAIN QUERY PLAN 估算查询开销"""

    def __init__(self, connector=None):
        self.connector = connector
        self.max_rows = config.governance_max_scan_rows
        self.warn_rows = config.governance_warn_scan_rows

    def apply(self, sql: str) -> dict:
        """
        Returns:
            {"denied": bool, "warning": bool, "estimated_rows": int | None, "reason": str | None}
        """
        if not self.connector:
            return {"denied": False, "warning": False}

        try:
            plan = self.connector.execute(f"EXPLAIN QUERY PLAN {sql}")
            estimated = self._estimate_rows(plan)

            if estimated and estimated > self.max_rows:
                return {
                    "denied": True,
                    "warning": False,
                    "estimated_rows": estimated,
                    "reason": f"预计扫描 {estimated:,} 行，超过限制 {self.max_rows:,}",
                }

            if estimated and estimated > self.warn_rows:
                return {
                    "denied": False,
                    "warning": True,
                    "estimated_rows": estimated,
                    "reason": f"预计扫描 {estimated:,} 行，可能较慢",
                }

            return {"denied": False, "warning": False, "estimated_rows": estimated}

        except Exception as e:
            logger.debug("EXPLAIN 失败 (非致命): %s", e)
            return {"denied": False, "warning": False}

    @staticmethod
    def _estimate_rows(plan: list[dict]) -> int | None:
        """从 EXPLAIN 结果提取估算行数"""
        total = 0
        for row in plan:
            detail = str(row.get("detail", ""))
            # SQLite EXPLAIN 中 detail 字段包含 "SCAN ... (~N rows)"
            import re
            m = re.search(r'~(\d+)\s*rows', detail)
            if m:
                total = max(total, int(m.group(1)))
        return total if total > 0 else None
