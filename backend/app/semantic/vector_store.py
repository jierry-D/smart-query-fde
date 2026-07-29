"""向量存储 — ChromaDB 集成 (可选，降级为文本匹配)"""

from ..core.logging import get_logger

logger = get_logger(__name__)


class VectorStore:
    """
    向量索引 — 用于语义搜索。

    当 ChromaDB 不可用时，降级为精确文本匹配。
    """

    def __init__(self, persist_dir: str = None):
        self.persist_dir = persist_dir
        self._client = None
        self._collection = None
        self._available = False
        self._init_chroma()

    def _init_chroma(self):
        try:
            import chromadb
            self._client = chromadb.PersistentClient(
                path=self.persist_dir or "./chroma_data"
            )
            self._collection = self._client.get_or_create_collection("metrics")
            self._available = True
            logger.info("ChromaDB 向量存储已就绪")
        except Exception as e:
            logger.info("ChromaDB 不可用, 降级为文本匹配: %s", e)
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def index_metrics(self, metrics: list[dict]):
        """将指标索引入向量库"""
        if not self._available:
            return

        try:
            ids = [m["metric_id"] for m in metrics]
            docs = [f"{m['name']}: {m.get('explanation', '')}" for m in metrics]
            metadatas = [{"name": m["name"], "category": m["category"]} for m in metrics]
            self._collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
            logger.info("已索引 %d 个指标到向量库", len(metrics))
        except Exception as e:
            logger.warning("向量索引失败: %s", e)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """向量搜索 (降级时返回空列表)"""
        if not self._available:
            return []

        try:
            results = self._collection.query(query_texts=[query], n_results=top_k)
            if not results or not results.get("ids") or not results["ids"][0]:
                return []

            return [
                {
                    "metric_id": mid,
                    "score": 1.0 - (dist if dist else 0),
                    "metadata": meta,
                }
                for mid, dist, meta in zip(
                    results["ids"][0],
                    results.get("distances", [[]])[0],
                    results.get("metadatas", [[]])[0],
                )
            ]
        except Exception as e:
            logger.debug("向量搜索失败: %s", e)
            return []
