"""反馈 API"""

from fastapi import APIRouter, Depends

from ...core.deps import get_current_user
from ...database import DatabaseConnector

router = APIRouter(prefix="/api/feedback", tags=["反馈"])


@router.post("")
def submit_feedback(req: dict, user: dict = Depends(get_current_user)):
    """提交查询反馈 (👍/👎)"""
    db = DatabaseConnector()
    query_log_id = req.get("query_log_id")
    rating = req.get("rating", "up")
    comment = req.get("comment", "")
    suggested_sql = req.get("suggested_sql", "")

    if rating not in ("up", "down"):
        return {"error": "rating 必须为 up 或 down"}

    feedback_id = db.save_feedback(
        query_log_id=query_log_id,
        user_id=user["user_id"],
        rating=rating,
        comment=comment,
        suggested_sql=suggested_sql,
    )

    return {"feedback_id": feedback_id, "status": "saved"}
