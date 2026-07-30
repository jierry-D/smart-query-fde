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
_SENSITIVE_PATTERNS = [
    re.compile(r'\bpassword\b', re.IGNORECASE),
    re.compile(r'\bphone\b', re.IGNORECASE),
    re.compile(r'\bid_card\b', re.IGNORECASE),
    re.compile(r'\bbank_card\b', re.IGNORECASE),
    re.compile(r'\bsecret\b', re.IGNORECASE),
    re.compile(r'\btoken\b', re.IGNORECASE),
    re.compile(r'\bapi_key\b', re.IGNORECASE),
]

# 字符串字面量移除 (用于关键字检查前清洗)
_RE_SINGLE_QUOTED = re.compile(r"'[^']*'")
_RE_DOUBLE_QUOTED = re.compile(r'"[^"]*"')

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
            for pattern in _SENSITIVE_PATTERNS:
                if pattern.search(sql):
                    return {"denied": True, "reason": f"查询涉及敏感字段"}

        return {"denied": False}

    @staticmethod
    def _has_keyword_outside_strings(sql: str, keyword: str) -> bool:
        """检查关键字是否出现在 SQL 的字符串字面量之外"""
        cleaned = _RE_SINGLE_QUOTED.sub('', sql)
        cleaned = _RE_DOUBLE_QUOTED.sub('', cleaned)
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', cleaned, re.IGNORECASE))
