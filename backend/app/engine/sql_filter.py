"""
SQL 动态过滤器 — 将 NER 提取的实体注入 SQL 模板

根据 NER 结果:
  - 注入 WHERE 筛选条件 (区域、业务线)
  - 替换 GROUP BY / ORDER BY / LIMIT 子句
  - 根据 intent 选择合适的 SQL 变体
"""

import re

from ..core.logging import get_logger

logger = get_logger(__name__)

# ── 预编译 SQL 子句模式 ──
_RE_WHERE = re.compile(r'\bWHERE\b', re.IGNORECASE)
_RE_GROUP_BY = re.compile(r'\bGROUP\s+BY\b', re.IGNORECASE)
_RE_ORDER_BY = re.compile(r'\bORDER\s+BY\b', re.IGNORECASE)
_RE_LIMIT = re.compile(r'\bLIMIT\b', re.IGNORECASE)
_RE_FROM_TABLE = re.compile(r'\bFROM\s+\w+', re.IGNORECASE)
_RE_SELECT_VALUE = re.compile(
    r'SELECT\s+(.+?)\s+AS\s+value', re.IGNORECASE
)
_RE_ORDER_CLAUSE = re.compile(
    r'ORDER\s+BY\s+\S+(\s+(?:ASC|DESC))?', re.IGNORECASE
)
_RE_LIMIT_N = re.compile(r'LIMIT\s+\d+', re.IGNORECASE)


def apply_entities(base_sql: str, entities: dict) -> str:
    """将 NER 实体应用到 SQL"""
    sql = base_sql

    # 1. WHERE 筛选
    sql = _inject_filters(sql, entities.get("filters", []))

    # 2. GROUP BY
    sql = _apply_group_by(sql, entities)

    # 3. ORDER BY
    sql = _apply_order(sql, entities)

    # 4. LIMIT
    sql = _apply_limit(sql, entities)

    return sql


def _inject_filters(sql: str, filters: list) -> str:
    if not filters:
        return sql

    conditions = []
    for f in filters:
        field = f["field"]
        value = str(f.get("value", ""))
        safe_value = value.replace("'", "''")
        operator = f.get("operator", "=")
        if operator == "=":
            conditions.append(f'"{field}" = \'{safe_value}\'')
        elif operator == "LIKE":
            conditions.append(f'"{field}" LIKE \'%{safe_value}%\'')

    filter_str = " AND ".join(conditions)

    where_match = _RE_WHERE.search(sql)
    if where_match:
        group_match = _RE_GROUP_BY.search(sql)
        order_match = _RE_ORDER_BY.search(sql)
        limit_match = _RE_LIMIT.search(sql)

        end_positions = []
        if group_match:
            end_positions.append(group_match.start())
        if order_match:
            end_positions.append(order_match.start())
        if limit_match:
            end_positions.append(limit_match.start())
        end_pos = min(end_positions) if end_positions else len(sql)

        before = sql[:end_pos].rstrip()
        after = sql[end_pos:]
        return f"{before}\n    AND {filter_str}\n{after}"

    from_match = _RE_FROM_TABLE.search(sql)
    if from_match:
        insert_pos = from_match.end()
        return f"{sql[:insert_pos]}\nWHERE {filter_str}\n{sql[insert_pos:]}"

    return sql


def _apply_group_by(sql: str, entities: dict) -> str:
    group_by = entities.get("group_by")
    intent = entities.get("intent", "aggregate")

    if intent not in ("distribution", "ranking", "trend"):
        return sql
    if not group_by:
        return sql

    group_field_map = {"region": "region", "business_line": "business_line"}
    field = group_field_map.get(group_by, group_by)

    if _RE_GROUP_BY.search(sql):
        return sql

    if 'AS label' not in sql and 'AS value' in sql:
        sql = _RE_SELECT_VALUE.sub(
            f'SELECT "{field}" AS label, \\1 AS value',
            sql, count=1
        )
        sql = sql.rstrip().rstrip(';')
        sql += f'\nGROUP BY "{field}"'

    return sql


def _apply_order(sql: str, entities: dict) -> str:
    order = entities.get("order")
    if not order:
        return sql

    order_clause = f'ORDER BY value {order.upper()}'

    if _RE_ORDER_BY.search(sql):
        sql = _RE_ORDER_CLAUSE.sub(order_clause, sql)
    else:
        sql = sql.rstrip().rstrip(';')
        sql += f'\n{order_clause}'

    return sql


def _apply_limit(sql: str, entities: dict) -> str:
    limit = entities.get("limit")
    if limit is None:
        return sql

    if _RE_LIMIT.search(sql):
        sql = _RE_LIMIT_N.sub(f'LIMIT {limit}', sql)
    else:
        sql = sql.rstrip().rstrip(';')
        sql += f'\nLIMIT {limit}'

    return sql


def inject_snapshot_where(sql: str, snapshot_ids: list) -> str:
    """在 SQL 的 WHERE 子句中注入 snapshot_id 过滤"""
    ids_str = ','.join(str(int(sid)) for sid in snapshot_ids)
    filter_clause = f"snapshot_id IN ({ids_str})"

    where_match = _RE_WHERE.search(sql)
    group_match = _RE_GROUP_BY.search(sql)
    order_match = _RE_ORDER_BY.search(sql)

    if where_match:
        where_end = where_match.end()
        end_positions = []
        if group_match:
            end_positions.append(group_match.start())
        if order_match:
            end_positions.append(order_match.start())
        end_pos = min(end_positions) if end_positions else len(sql)

        before = sql[:end_pos].rstrip()
        after = sql[end_pos:]
        return f"{before}\n    AND {filter_clause}\n{after}"

    from_match = _RE_FROM_TABLE.search(sql)
    if from_match:
        insert_pos = from_match.end()
        before = sql[:insert_pos]
        after = sql[insert_pos:]
        return f"{before}\nWHERE {filter_clause}\n{after}"

    return sql


def inject_data_scope(sql: str, scope_sql: str) -> str:
    """注入 RBAC 数据范围过滤"""
    if scope_sql == "1=1":
        return sql

    where_match = _RE_WHERE.search(sql)
    if where_match:
        group_match = _RE_GROUP_BY.search(sql)
        order_match = _RE_ORDER_BY.search(sql)
        end_positions = [len(sql)]
        if group_match:
            end_positions.append(group_match.start())
        if order_match:
            end_positions.append(order_match.start())
        end_pos = min(end_positions)

        before = sql[:end_pos].rstrip()
        after = sql[end_pos:]
        return f"{before}\n    AND {scope_sql}\n{after}"

    from_match = _RE_FROM_TABLE.search(sql)
    if from_match:
        insert_pos = from_match.end()
        return f"{sql[:insert_pos]}\nWHERE {scope_sql}\n{sql[insert_pos:]}"

    return sql
