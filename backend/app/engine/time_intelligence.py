"""时间智能引擎 — YTD/MTD/YoY/MoM/目标完成率"""

from datetime import date
from ..core.logging import get_logger

logger = get_logger(__name__)


class TimeIntelligenceEngine:
    """时间智能函数注册与执行"""

    def __init__(self, connector=None):
        self.connector = connector
        self._functions = {
            "ytd": self.compute_ytd,
            "mtd": self.compute_mtd,
            "yoy": self.compute_yoy,
            "mom": self.compute_mom,
            "target_completion": self.compute_target,
        }

    def compute(
        self, func_name: str, current_value: float,
        base_sql: str, scope_sql: str,
        current_ids: list[int], previous_ids: list[int],
    ) -> dict | None:
        """
        计算时间智能指标。

        Args:
            func_name: 函数名 (ytd/mtd/yoy/mom/target_completion)
            current_value: 当前期间的指标值
            base_sql: 基础 SQL (未注入快照过滤)
            scope_sql: RBAC 数据范围 SQL
            current_ids: 当前期间快照 ID
            previous_ids: 对比期间快照 ID

        Returns:
            {"function", "current_value", "previous_value", "growth_rate", "direction", "label"}
        """
        func = self._functions.get(func_name)
        if not func:
            return None

        return func(current_value, base_sql, scope_sql, current_ids, previous_ids)

    def compute_yoy(
        self, current_value: float, base_sql: str, scope_sql: str,
        current_ids: list[int], previous_ids: list[int],
    ) -> dict | None:
        """同比: (当期 - 去年同期) / 去年同期 × 100%"""
        prev_value = self._execute_sql(base_sql, scope_sql, previous_ids)
        return self._build_response("yoy", "同比", current_value, prev_value)

    def compute_mom(
        self, current_value: float, base_sql: str, scope_sql: str,
        current_ids: list[int], previous_ids: list[int],
    ) -> dict | None:
        """环比: (当期 - 上期) / 上期 × 100%"""
        prev_value = self._execute_sql(base_sql, scope_sql, previous_ids)
        return self._build_response("mom", "环比", current_value, prev_value)

    def compute_ytd(
        self, current_value: float, base_sql: str, scope_sql: str,
        current_ids: list[int], previous_ids: list[int],
    ) -> dict | None:
        """YTD: 年初至今累计"""
        today = date.today()
        prev_value = self._execute_sql(base_sql, scope_sql, previous_ids)
        return self._build_response(
            "ytd", f"{today.year} YTD", current_value, prev_value
        )

    def compute_mtd(
        self, current_value: float, base_sql: str, scope_sql: str,
        current_ids: list[int], previous_ids: list[int],
    ) -> dict | None:
        """MTD: 月初至今累计"""
        today = date.today()
        prev_value = self._execute_sql(base_sql, scope_sql, previous_ids)
        return self._build_response(
            "mtd", f"{today.month}月 MTD", current_value, prev_value
        )

    def compute_target(
        self, current_value: float, base_sql: str, scope_sql: str,
        current_ids: list[int], previous_ids: list[int],
    ) -> dict | None:
        """目标完成率 (需 target_value 从外部传入, 此处返回 None)"""
        return None  # 实现需从配置/DB 获取目标值

    def _execute_sql(
        self, base_sql: str, scope_sql: str, snapshot_ids: list[int],
    ) -> float | None:
        """执行 SQL 并提取数值"""
        if not self.connector or not snapshot_ids:
            return None

        from .sql_filter import inject_snapshot_where, inject_data_scope
        sql = inject_snapshot_where(base_sql, snapshot_ids)
        sql = inject_data_scope(sql, scope_sql)

        try:
            rows = self.connector.execute(sql)
            if rows and "value" in rows[0]:
                return rows[0]["value"]
        except Exception as e:
            logger.warning("Time intelligence SQL failed: %s", e)
        return None

    @staticmethod
    def _build_response(
        func: str, label: str, current: float | None, previous: float | None,
    ) -> dict | None:
        """构建标准响应"""
        if current is None or previous is None or previous == 0:
            return {
                "function": func, "label": label, "available": False,
                "error": "对比期间无数据",
            }

        growth = round((current - previous) / previous * 100, 2)
        return {
            "function": func,
            "label": label,
            "current_value": round(current, 2),
            "previous_value": round(previous, 2),
            "growth_rate": growth,
            "direction": "增长" if growth > 0 else "下降" if growth < 0 else "持平",
            "available": True,
        }
