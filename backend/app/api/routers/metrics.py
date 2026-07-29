"""指标 API"""

from fastapi import APIRouter, Depends, HTTPException

from ...core.deps import get_current_user
from ...database import DatabaseConnector
from ...semantic.loader import MetricLoader

router = APIRouter(prefix="/api/metrics", tags=["指标"])


def _get_db():
    return DatabaseConnector()


@router.get("")
def list_metrics(category: str = None, user: dict = Depends(get_current_user)):
    """获取所有指标列表"""
    db = _get_db()
    loader = MetricLoader(db)
    metrics = loader.list_all(category)
    return {
        "metrics": metrics,
        "total": len(metrics),
        "categories": loader.list_categories(),
        "available": loader.available_count,
    }


@router.get("/categories")
def list_categories(user: dict = Depends(get_current_user)):
    """获取指标分类列表"""
    db = _get_db()
    loader = MetricLoader(db)
    return {"categories": loader.list_categories()}


@router.get("/search")
def search_metrics(q: str, top_k: int = 5, user: dict = Depends(get_current_user)):
    """搜索指标"""
    db = _get_db()
    loader = MetricLoader(db)
    results = loader.search(q, top_k=top_k)
    return {
        "query": q,
        "results": [
            {
                "metric": {
                    "metric_id": r["metric"]["metric_id"],
                    "name": r["metric"]["name"],
                    "category": r["metric"]["category"],
                    "status": r["metric"]["status"],
                    "complexity": r["metric"]["complexity"],
                    "explanation": r["metric"].get("explanation", ""),
                },
                "score": r["score"],
                "match_type": r["match_type"],
            }
            for r in results
        ],
    }


@router.get("/{metric_id}")
def get_metric(metric_id: str, user: dict = Depends(get_current_user)):
    """获取单个指标详情"""
    db = _get_db()
    loader = MetricLoader(db)
    metric = loader.get_by_id(metric_id)
    if not metric:
        raise HTTPException(404, f"指标 {metric_id} 不存在")
    return metric
