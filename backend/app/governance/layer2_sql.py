"""Layer 2: SQL 安全检查 — 拦截破坏性操作和敏感数据"""

import re

from ..core.logging import get_logger

logger = get_logger(__name__)

# 禁止的关键字 (非 SELECT 或危险函数)
DESTRUCTIVE_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "ATTACH", "DETACH",
    "PRAGMA", "VACUUM", "REINDEX",
]

# 敏感字段模式
SENSITIVE_PATTERNS = [
    r'\bpassword\b', r'\bphone\b', r'\bid_card\b', r'\bbank_card\b',
    r'\bsecret\b', r'\btoken\b', r'\bapi_key\b',
]

MAX_QUERY_LENGTH = 10000


class SQLSecurityChecker:
    """SQL 安全检查器"""

    def apply(self, sql: str, user: dict) -> dict:
        """
        Returns:
            {"denied": bool, "reason": str | None}
        """
        # 长度检查
        if len(sql) > MAX_QUERY_LENGTH:
            return {"denied": True, "reason": f"SQL 过长 ({len(sql)} > {MAX_QUERY_LENGTH})"}

        upper_sql = sql.strip().upper()

        # 必须是 SELECT 开头
        if not upper_sql.startswith("SELECT"):
            return {"denied": True, "reason": "仅允许 SELECT 查询"}

        # 检查危险关键字 (在非字符串上下文中)
        for kw in DESTRUCTIVE_KEYWORDS:
            if self._has_keyword_outside_strings(sql, kw):
                return {"denied": True, "reason": f"禁止使用关键字: {kw}"}

        # 检查敏感字段 (admin 可豁免)
        if user.get("role") != "admin":
            for pattern in SENSITIVE_PATTERNS:
                if re.search(pattern, sql, re.IGNORECASE):
                    return {"denied": True, "reason": f"查询涉及敏感字段"}

        return {"denied": False}

    @staticmethod
    def _has_keyword_outside_strings(sql: str, keyword: str) -> bool:
        """检查关键字是否出现在 SQL 的字符串字面量之外"""
        # 移除字符串字面量后检查
        cleaned = re.sub(r"'[^']*'", '', sql)
        cleaned = re.sub(r'"[^"]*"', '', cleaned)
        pattern = r'\b' + re.escape(keyword) + r'\b'
        return bool(re.search(pattern, cleaned, re.IGNORECASE))
