"""Stage 0: 数据准备检查 — 查询前预检"""

from datetime import date, datetime

from ..core.logging import get_logger

logger = get_logger(__name__)


class Stage0Preflight:
    """查询前预检: 数据质量、新鲜度、时间范围提示"""

    def __init__(self, db):
        self.db = db

    def check(self, query: str, matched_metric: dict | None = None) -> dict:
        """
        Returns:
            {"status": "ok"|"warning"|"error", "messages": [...]}
        """
        messages = []
        status = "ok"

        # 1. 数据新鲜度检查
        latest = self.db.get_latest_snapshot()
        if latest:
            try:
                ingestion = latest.get("ingestion_time", "")
                if isinstance(ingestion, str):
                    ingestion_date = datetime.strptime(
                        ingestion[:10], "%Y-%m-%d"
                    ).date()
                else:
                    ingestion_date = date.today()

                days_ago = (date.today() - ingestion_date).days
                if days_ago > 30:
                    status = "warning"
                    messages.append(
                        f"最新数据 {days_ago} 天前 ({latest['data_period']})，建议更新数据"
                    )
                elif days_ago > 7:
                    messages.append(
                        f"数据最后更新: {days_ago} 天前 ({latest['data_period']})"
                    )
            except Exception:
                pass
        else:
            status = "error"
            messages.append("暂无数据，请先导入数据")

        # 2. 指标可用性检查
        if matched_metric:
            if matched_metric.get("status") == "pending":
                status = "error"
                messages.append(f"指标 '{matched_metric['name']}' 数据尚未接入")

        # 3. 时间范围缺失提示
        has_time = any(kw in query for kw in [
            "Q1", "Q2", "Q3", "Q4", "月", "季度", "年", "本周", "本月",
            "今年", "去年", "同比", "环比", "上半年", "下半年",
        ])
        if not has_time and status == "ok":
            messages.append("未指定时间范围，将使用最新数据")

        return {"status": status, "messages": messages}
