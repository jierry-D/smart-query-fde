"""查询治理 — 五层防护管理器"""

from .layer1_auth import AuthFilter
from .layer2_sql import SQLSecurityChecker
from .layer3_resource import ResourceEstimator
from .layer4_exec import ExecutionGuard
from .layer5_cache import ResultCache, get_cache
from ..core.logging import get_logger

logger = get_logger(__name__)


class GovernanceManager:
    """统一治理入口 — 串联五层防护"""

    def __init__(self, connector=None):
        self.layer1 = AuthFilter()
        self.layer2 = SQLSecurityChecker()
        self.layer3 = ResourceEstimator(connector)
        self.layer4 = ExecutionGuard()
        self.layer5 = get_cache()

    def apply(self, sql: str, user: dict) -> dict:
        """
        执行五层治理检查。

        Returns:
            {
                "denied": bool,
                "final_sql": str,
                "scope_label": str,
                "cache_hit": bool,
                "cached_result": dict | None,
                "checks": list[dict],  # 每层检查结果
            }
        """
        checks = []

        # Layer 1: 权限 + 数据范围
        r1 = self.layer1.apply(sql, user)
        checks.append({"layer": 1, "name": "权限校验", "passed": not r1["denied"]})
        if r1["denied"]:
            return {"denied": True, "reason": "权限不足", "checks": checks}
        sql = r1["sql"]

        # Layer 2: SQL 安全
        r2 = self.layer2.apply(sql, user)
        checks.append({"layer": 2, "name": "SQL安全检查", "passed": not r2["denied"]})
        if r2["denied"]:
            return {"denied": True, "reason": r2["reason"], "checks": checks}

        # Layer 5: 缓存 (先查缓存，避免重复执行)
        r5 = self.layer5.apply(sql)
        checks.append({"layer": 5, "name": "缓存检查", "passed": True,
                       "cache_hit": r5["cache_hit"]})
        if r5["cache_hit"]:
            return {
                "denied": False, "final_sql": sql,
                "scope_label": r1["scope_label"],
                "cache_hit": True, "cached_result": r5["cached_result"],
                "cache_key": r5["cache_key"], "checks": checks,
            }

        # Layer 3: 资源预估
        r3 = self.layer3.apply(sql)
        checks.append({"layer": 3, "name": "资源预估", "passed": not r3["denied"]})
        if r3["denied"]:
            return {"denied": True, "reason": r3["reason"], "checks": checks}

        # Layer 4: 执行保护 (熔断)
        r4 = self.layer4.apply(sql)
        checks.append({"layer": 4, "name": "执行保护", "passed": not r4["denied"]})
        if r4["denied"]:
            return {"denied": True, "reason": r4["reason"], "checks": checks}

        return {
            "denied": False, "final_sql": sql,
            "scope_label": r1["scope_label"],
            "cache_hit": False, "cached_result": None,
            "cache_key": r5["cache_key"], "checks": checks,
        }

    def record_result(self, cache_key: str, result: dict, success: bool):
        """记录执行结果 (更新缓存和熔断器)"""
        if success:
            self.layer4.record_success()
            self.layer5.store(cache_key, result)
        else:
            self.layer4.record_failure()
