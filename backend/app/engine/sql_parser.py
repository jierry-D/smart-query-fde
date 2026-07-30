"""
SQL 子句解析器 — 一次解析定位所有子句边界，供注入函数复用。

处理系统生成的 SQL 模式:
  SELECT ... FROM ... WHERE ... GROUP BY ... ORDER BY ... LIMIT ...

支持:
  - 双引号标识符 ("region")
  - 单引号字符串字面量 ('text')
  - 子查询跳过 (括号深度追踪)
  - 重建 (rebuild) 和逐子句修改
"""

import re
from dataclasses import dataclass, field

# ── 预编译子句定位模式 ──
_RE_CLAUSE = re.compile(
    r'\b(SELECT|FROM|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b',
    re.IGNORECASE,
)


@dataclass
class ParsedSQL:
    """解析后的 SQL 子句集合"""

    select: str = ""
    from_clause: str = ""
    where: str = ""
    group_by: str = ""
    having: str = ""
    order_by: str = ""
    limit: str = ""
    _raw: str = ""  # 原始 SQL (调试用)

    def rebuild(self) -> str:
        """重建完整 SQL"""
        parts = [p for p in [
            self.select, self.from_clause, self.where,
            self.group_by, self.having, self.order_by, self.limit,
        ] if p]
        return "\n".join(parts)

    def add_where_condition(self, condition: str) -> "ParsedSQL":
        """在 WHERE 后追加 AND 条件"""
        if self.where:
            self.where += f"\n    AND {condition}"
        else:
            self.where = f"WHERE {condition}"
        return self

    def set_group_by(self, field: str) -> "ParsedSQL":
        """替换 GROUP BY"""
        self.group_by = f'GROUP BY "{field}"'
        return self

    def set_order_by(self, clause: str) -> "ParsedSQL":
        """替换 ORDER BY"""
        self.order_by = clause
        return self

    def set_limit(self, n: int) -> "ParsedSQL":
        """替换 LIMIT"""
        self.limit = f"LIMIT {n}"
        return self


def parse_sql(sql: str) -> ParsedSQL:
    """
    一次扫描定位所有 SQL 子句边界。

    通过跟踪括号深度跳过子查询和字符串字面量，
    将 SQL 拆分为 SELECT / FROM / WHERE / GROUP BY / HAVING / ORDER BY / LIMIT。
    """
    parsed = ParsedSQL(_raw=sql)

    # Step 1: 找到所有子句关键字的位置 (跳过字符串和嵌套括号)
    positions = _find_clause_positions(sql)

    if not positions:
        # 无法解析 → 保留为 select
        parsed.select = sql
        return parsed

    # Step 2: 按位置切分
    clauses = []
    for i, (pos, keyword) in enumerate(positions):
        clause_start = pos
        if i + 1 < len(positions):
            clause_end = positions[i + 1][0]
        else:
            clause_end = len(sql)
        clauses.append((keyword, sql[clause_start:clause_end].strip()))

    # Step 3: 分配到 ParsedSQL 字段
    for keyword, text in clauses:
        kw_upper = keyword.upper().replace(" ", "_")
        if kw_upper == "SELECT":
            parsed.select = text
        elif kw_upper == "FROM":
            parsed.from_clause = text
        elif kw_upper == "WHERE":
            parsed.where = text
        elif kw_upper == "GROUP_BY":
            parsed.group_by = text
        elif kw_upper == "HAVING":
            parsed.having = text
        elif kw_upper == "ORDER_BY":
            parsed.order_by = text
        elif kw_upper == "LIMIT":
            parsed.limit = text

    return parsed


def _find_clause_positions(sql: str) -> list[tuple[int, str]]:
    """
    在 SQL 中找到所有顶层子句关键字的位置。

    跳过:
      - 单引号字符串 '...'
      - 双引号标识符 "..."
      - 括号内的子查询 ( ... )
    """
    positions = []
    i = 0
    n = len(sql)
    depth = 0  # 括号深度

    while i < n:
        ch = sql[i]

        # 跳过空白
        if ch in (' ', '\t', '\n', '\r'):
            i += 1
            continue

        # 单引号字符串
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2  # 转义引号
                    else:
                        i += 1
                        break
                else:
                    i += 1
            continue

        # 双引号标识符
        if ch == '"':
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            continue

        # 括号
        if ch == '(':
            depth += 1
            i += 1
            continue
        if ch == ')':
            depth -= 1
            i += 1
            continue

        # 顶层才检查关键字
        if depth == 0:
            m = _RE_CLAUSE.match(sql, i)
            if m:
                keyword = m.group(0)
                # 对于 GROUP BY / ORDER BY，需要两个词
                kw_upper = keyword.upper()
                if kw_upper in ("GROUP", "ORDER"):
                    keyword = m.group(0)  # 如 "GROUP BY"
                positions.append((i, keyword))
                i = m.end()
                continue

        i += 1

    return positions
