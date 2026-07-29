"""反馈 API — 提交 + 自动分析"""

from fastapi import APIRouter, Depends

from ...core.deps import get_current_user
from ...database import DatabaseConnector

router = APIRouter(prefix="/api/feedback", tags=["反馈"])


@router.post("")
def submit_feedback(req: dict, user: dict = Depends(get_current_user)):
    """提交查询反馈 (👍/👎) + 自动分析"""
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

    # 自动分析反馈 (异步, 不阻塞响应)
    suggestions = []
    if rating == "down" and (comment or suggested_sql):
        try:
            from ...governance.feedback_analyzer import FeedbackAnalyzer
            analyzer = FeedbackAnalyzer(db)
            suggestions = analyzer.analyze(feedback_id, query_log_id)
        except Exception:
            pass

    return {
        "feedback_id": feedback_id,
        "status": "saved",
        "suggestions_created": len(suggestions),
    }
