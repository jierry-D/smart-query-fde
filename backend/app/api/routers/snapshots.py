"""快照 API"""

from fastapi import APIRouter, Depends

from ...core.deps import get_current_user
from ...database import DatabaseConnector

router = APIRouter(prefix="/api/snapshots", tags=["数据快照"])


@router.get("")
def list_snapshots(user: dict = Depends(get_current_user)):
    """获取所有数据快照"""
    db = DatabaseConnector()
    snapshots = db.get_snapshots()
    latest = db.get_latest_snapshot()
    return {
        "snapshots": snapshots,
        "total": len(snapshots),
        "latest_id": latest["snapshot_id"] if latest else None,
        "latest_period": latest["data_period"] if latest else "无数据",
    }


@router.get("/latest")
def get_latest(user: dict = Depends(get_current_user)):
    """获取最新数据"""
    db = DatabaseConnector()
    latest = db.get_latest_snapshot()
    if not latest:
        return {"error": "暂无数据"}
    return latest
