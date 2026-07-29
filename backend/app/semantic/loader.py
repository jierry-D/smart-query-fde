"""指标加载与匹配引擎 — 从 metric_registry 表查询 + 向量检索增强"""

from difflib import SequenceMatcher

from ..database import DatabaseConnector
from ..core.logging import get_logger

logger = get_logger(__name__)


class MetricLoader:
    """从 metric_registry 表加载和查询指标 (向量检索 + 文本匹配)"""

    def __init__(self, connector: DatabaseConnector = None):
        self.connector = connector or DatabaseConnector()
        self._all_metrics = []
        self._name_index = {}
        self._vector_store = None
        self._init_vector_store()
        self.reload()

    def _init_vector_store(self):
        """初始化向量存储 (可选)"""
        try:
            from .vector_store import VectorStore
            from ..config import config
            self._vector_store = VectorStore(
                persist_dir=getattr(config, 'vector_persist_dir', None)
            )
        except Exception as e:
            logger.info("向量存储初始化失败, 仅使用文本匹配: %s", e)
            self._vector_store = None

    def reload(self):
        """重新加载全部指标并索引到向量库"""
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

        # 索引到向量库
        if self._vector_store and self._vector_store.is_available:
            try:
                available = [m for m in self._all_metrics if m["status"] == "available"]
                if available:
                    self._vector_store.index_metrics(available)
            except Exception as e:
                logger.debug("向量索引失败: %s", e)

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
        """四层匹配策略: 向量 → 精确 → 包含 → 模糊"""
        query_stripped = ' '.join(query.strip().split())

        # Tier 0: 精确匹配 (最快, 最高优先级)
        if query_stripped in self._name_index:
            m = self._name_index[query_stripped]
            return [{"metric": m, "score": 1.0, "match_type": "exact"}]

        # Tier 1: 向量检索 (缩小候选范围)
        vector_candidates = set()
        if self._vector_store and self._vector_store.is_available:
            try:
                vec_results = self._vector_store.search(query, top_k=min(top_k * 3, 20))
                for vr in vec_results:
                    if vr.get("score", 0) > 0.3:  # 最低相似度阈值
                        mid = vr.get("metric_id")
                        if mid:
                            vector_candidates.add(mid)
            except Exception as e:
                logger.debug("向量搜索跳过: %s", e)

        # Tier 2-4: 包含 + 模糊 (在向量候选或全集中搜索)
        candidates = self._all_metrics
        if vector_candidates:
            # 优先搜索向量候选, 但也保留全集兜底
            vec_metrics = [m for m in self._all_metrics if m["metric_id"] in vector_candidates]
            if vec_metrics:
                candidates = vec_metrics

        results = []
        for m in candidates:
            name = m["name"]
            display = m.get("display_name") or ""
            score = 0.0
            match_type = "none"

            # 匹配 name 或 display_name (取较高分)
            for text in (name, display):
                if not text:
                    continue
                if text in query_stripped:
                    s = 0.98
                    mt = "name_in_query"
                elif query_stripped in text:
                    s = 0.85
                    mt = "query_in_name"
                else:
                    ratio = SequenceMatcher(None, query_stripped, text).ratio()
                    if ratio > 0.35:
                        s = 0.45 + ratio * 0.35
                        mt = "fuzzy"
                    else:
                        continue
                if s > score:
                    score = s
                    match_type = mt

            # 向量候选加分
            if vector_candidates and m["metric_id"] in vector_candidates and match_type != "none":
                score = min(1.0, score + 0.05)

            if score > 0:
                results.append({"metric": m, "score": score, "match_type": match_type})

        results.sort(key=lambda x: x["score"], reverse=True)

        # 如果向量候选没结果, 回退到全量搜索
        if not results and vector_candidates:
            results = self._search_all(query_stripped, top_k)

        return results[:top_k]

    def _search_all(self, query_stripped: str, top_k: int = 5) -> list[dict]:
        """全量文本搜索 (向量不可用时的兜底)"""
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
