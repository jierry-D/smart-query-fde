"""指标加载与匹配引擎 — 从 metric_registry 表查询"""

from difflib import SequenceMatcher

from ..database import DatabaseConnector
from ..core.logging import get_logger

logger = get_logger(__name__)


class MetricLoader:
    """从 metric_registry 表加载和查询指标"""

    def __init__(self, connector: DatabaseConnector = None):
        self.connector = connector or DatabaseConnector()
        self._all_metrics = []
        self._name_index = {}
        self.reload()

    def reload(self):
        """重新加载全部指标"""
        self._all_metrics = []
        self._name_index = {}

        try:
            rows = self.connector.execute("SELECT * FROM metric_registry ORDER BY metric_id")
        except Exception:
            logger.warning("metric_registry 表不存在或为空")
            return

        for r in rows:
            m = {
                "metric_id": r["metric_id"],
                "name": r["name"],
                "display_name": r.get("display_name") or r["name"],
                "category": r["category"],
                "explanation": r.get("explanation", ""),
                "formula": r.get("formula", ""),
                "source": r.get("source", ""),
                "status": r.get("status", "pending"),
                "complexity": r.get("complexity", "L1"),
                "table_name": r.get("table_name"),
                "sql_template": r.get("sql_template"),
                "result_format": r.get("result_format", "number"),
                "result_unit": r.get("result_unit", ""),
                "alert_level": r.get("alert_level"),
                "tags": r.get("tags", ""),
            }
            self._all_metrics.append(m)
            self._name_index[m["name"]] = m

        logger.info("指标加载: %d 个 (%d 可用)",
                     len(self._all_metrics),
                     sum(1 for m in self._all_metrics if m["status"] == "available"))

    def list_all(self, category: str = None) -> list[dict]:
        result = []
        for m in self._all_metrics:
            if category and m["category"] != category:
                continue
            result.append({
                "metric_id": m["metric_id"],
                "name": m["name"],
                "category": m["category"],
                "status": m["status"],
                "explanation": m["explanation"],
                "complexity": m["complexity"],
                "result_format": m["result_format"],
            })
        return result

    def list_categories(self) -> list[str]:
        return sorted(set(m["category"] for m in self._all_metrics))

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """三层匹配策略: 精确 → 包含 → 模糊"""
        query_stripped = ' '.join(query.strip().split())

        # Tier 1: 精确匹配
        if query_stripped in self._name_index:
            m = self._name_index[query_stripped]
            return [{"metric": m, "score": 1.0, "match_type": "exact"}]

        # Tier 2-3: 包含 + 模糊
        results = []
        for m in self._all_metrics:
            name = m["name"]
            score = 0.0
            match_type = "none"

            if name in query_stripped:
                score = 0.98
                match_type = "name_in_query"
            elif query_stripped in name:
                score = 0.85
                match_type = "query_in_name"
            else:
                ratio = SequenceMatcher(None, query_stripped, name).ratio()
                if ratio > 0.35:
                    score = 0.45 + ratio * 0.35
                    match_type = "fuzzy"

            if score > 0:
                results.append({"metric": m, "score": score, "match_type": match_type})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_by_id(self, metric_id: str) -> dict | None:
        for m in self._all_metrics:
            if m["metric_id"] == metric_id:
                return m
        return None

    def get_by_name(self, name: str) -> dict | None:
        return self._name_index.get(name)

    @property
    def available_count(self) -> int:
        return sum(1 for m in self._all_metrics if m["status"] == "available")

    @property
    def total_count(self) -> int:
        return len(self._all_metrics)
