"""反馈分析器 — 从用户反馈中提取改进建议

设计理念 (DataFlow 10K > 1M):
- 少量高质量反馈 > 大量噪声数据
- 只分析有文字评论的 down 反馈
- 自动提取术语映射建议
- 人工审核后应用
"""

from ..core.logging import get_logger

logger = get_logger(__name__)


class FeedbackAnalyzer:
    """分析用户反馈, 生成语义层改进建议"""

    def __init__(self, db):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self):
        """确保反馈分析相关表存在"""
        try:
            self.db.execute_write("""
                CREATE TABLE IF NOT EXISTS kb_suggestions (
                    suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT DEFAULT 'feedback',
                    suggestion_type TEXT NOT NULL,
                    original_query TEXT,
                    matched_metric TEXT,
                    user_comment TEXT,
                    proposed_change TEXT,
                    status TEXT DEFAULT 'pending',
                    feedback_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    applied_at TIMESTAMP
                )
            """)
        except Exception as e:
            logger.debug("kb_suggestions 表: %s", e)

    def analyze(self, feedback_id: int, query_log_id: int | None = None) -> list[dict]:
        """分析一条反馈, 生成改进建议"""
        # 获取反馈详情
        fb = self._get_feedback(feedback_id)
        if not fb:
            return []

        suggestions = []

        # 只分析 down 反馈
        if fb.get("rating") != "down":
            return []

        comment = (fb.get("comment") or "").strip()
        sql = (fb.get("suggested_sql") or "").strip()

        # 场景1: 用户提供了修正后的 SQL
        if sql and "SELECT" in sql.upper():
            suggestions.append(self._create_suggestion(
                fb, "sql_correction",
                f"用户对指标 '{fb.get('matched_metric', '?')}' 提供了修正SQL",
                sql,
            ))

        # 场景2: 用户评论中提到不同说法
        if comment:
            # 提取可能的术语映射
            terms = self._extract_terms(comment, fb)
            for t in terms:
                suggestions.append(self._create_suggestion(
                    fb, "term_mapping",
                    f"用户用 '{t['user_term']}' 指代 '{t['system_term']}'",
                    t,
                ))

            # 场景3: 通用改进建议
            if not suggestions and len(comment) >= 3:
                suggestions.append(self._create_suggestion(
                    fb, "general_improvement",
                    f"用户反馈: {comment[:200]}",
                    comment,
                ))

        # 保存建议
        for s in suggestions:
            try:
                self.db.execute_write(
                    """INSERT INTO kb_suggestions
                       (source_type, suggestion_type, original_query, matched_metric,
                        user_comment, proposed_change, feedback_id)
                       VALUES ('feedback', ?, ?, ?, ?, ?, ?)""",
                    (s["suggestion_type"], s["original_query"],
                     s["matched_metric"], s["user_comment"],
                     s["proposed_change"], feedback_id),
                )
            except Exception as e:
                logger.debug("保存建议失败: %s", e)

        return suggestions

    def _get_feedback(self, feedback_id: int) -> dict | None:
        try:
            row = self.db.execute_one(
                "SELECT * FROM query_feedback WHERE feedback_id=?", (feedback_id,)
            )
            if not row:
                return None

            # 尝试获取关联的查询日志
            log = None
            if row.get("query_log_id"):
                log = self.db.execute_one(
                    "SELECT * FROM query_logs WHERE log_id=?",
                    (row["query_log_id"],)
                )

            return {
                "feedback_id": row["feedback_id"],
                "rating": row.get("rating", "up"),
                "comment": row.get("comment", ""),
                "suggested_sql": row.get("suggested_sql", ""),
                "query_log_id": row.get("query_log_id"),
                "original_query": log["original_query"] if log else "",
                "matched_metric": log["matched_metric"] if log else "",
            }
        except Exception as e:
            logger.debug("获取反馈失败: %s", e)
            return None

    def _extract_terms(self, comment: str, fb: dict) -> list[dict]:
        """从评论中提取术语映射"""
        results = []
        original = fb.get("original_query", "")
        matched = fb.get("matched_metric", "")

        if not original or not matched:
            return results

        # 简单启发式: 原始查询中的关键词 vs 匹配的指标名
        orig_words = set(original.replace('的', ' ').replace('了', ' ').split())
        metric_words = set(matched.replace('_', ' ').split())

        # 在 original 中但不在 metric 中的词 → 可能的同义词
        for w in orig_words:
            if len(w) >= 2 and w not in metric_words:
                results.append({
                    "user_term": w,
                    "system_term": matched,
                })

        return results[:3]  # 最多3个

    def _create_suggestion(self, fb: dict, s_type: str, comment: str,
                           proposed: str | dict) -> dict:
        return {
            "suggestion_type": s_type,
            "original_query": fb.get("original_query", ""),
            "matched_metric": fb.get("matched_metric", ""),
            "user_comment": comment,
            "proposed_change": proposed if isinstance(proposed, str)
                               else str(proposed),
        }

    def list_pending(self, limit: int = 20) -> list[dict]:
        """列出待处理的改进建议"""
        try:
            return self.db.execute(
                "SELECT * FROM kb_suggestions WHERE status='pending' "
                "ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        except Exception:
            return []

    def apply_suggestion(self, suggestion_id: int) -> dict:
        """应用一条建议到知识库"""
        try:
            row = self.db.execute_one(
                "SELECT * FROM kb_suggestions WHERE suggestion_id=?",
                (suggestion_id,)
            )
            if not row:
                return {"status": "error", "message": "建议不存在"}

            s_type = row["suggestion_type"]
            proposed = row["proposed_change"]

            if s_type == "sql_correction":
                # 更新指标 SQL 模板
                matched = row["matched_metric"]
                if matched:
                    self.db.execute_write(
                        "UPDATE metric_registry SET sql_template=? WHERE name=?",
                        (proposed, matched),
                    )

            elif s_type == "term_mapping":
                # 添加同义词 (简化: 记录到日志)
                logger.info("术语映射建议需手动添加到知识库: %s → %s",
                            proposed, row["matched_metric"])

            # 标记为已应用
            self.db.execute_write(
                "UPDATE kb_suggestions SET status='applied', "
                "applied_at=CURRENT_TIMESTAMP WHERE suggestion_id=?",
                (suggestion_id,),
            )

            return {"status": "applied", "suggestion_id": suggestion_id,
                    "action": s_type}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def dismiss_suggestion(self, suggestion_id: int) -> dict:
        """忽略一条建议"""
        try:
            self.db.execute_write(
                "UPDATE kb_suggestions SET status='dismissed', "
                "applied_at=CURRENT_TIMESTAMP WHERE suggestion_id=?",
                (suggestion_id,),
            )
            return {"status": "dismissed", "suggestion_id": suggestion_id}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_stats(self) -> dict:
        try:
            rows = self.db.execute(
                "SELECT suggestion_type, status, COUNT(*) AS cnt "
                "FROM kb_suggestions GROUP BY suggestion_type, status"
            )
            stats = {"total": 0, "pending": 0, "applied": 0, "dismissed": 0}
            for r in rows:
                stats["total"] += r["cnt"]
                stats[r["status"]] = stats.get(r["status"], 0) + r["cnt"]
            return stats
        except Exception:
            return {"total": 0, "pending": 0, "applied": 0, "dismissed": 0}
