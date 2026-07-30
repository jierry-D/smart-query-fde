"""JOIN 路径规划器 — 自动检测表关系 + 生成跨表SQL"""

import re
from collections import deque

from ..core.logging import get_logger

logger = get_logger(__name__)


class JoinGraph:
    """表关系图 — 自动检测外键和快照关联"""

    def __init__(self, db):
        self.db = db
        self.edges: dict[str, list[tuple[str, str, str]]] = {}  # table → [(target, from_col, to_col)]
        self._built = False

    def build(self):
        """扫描所有表, 构建关系图"""
        if self._built:
            return
        tables = self.db.get_tables()
        skip = {'data_snapshots', 'sqlite_sequence', 'users', 'refresh_tokens',
                'query_logs', 'query_feedback', 'audit_logs', 'metric_registry',
                'onboarding_queue', 'schema_registry', 'kb_suggestions',
                'user_data_permissions'}
        user_tables = [t for t in tables if t not in skip and not t.startswith('指标需求')]

        for table in user_tables:
            self.edges.setdefault(table, [])
            try:
                schema = self.db.get_table_schema(table)
                for col in schema:
                    # 检测 snapshot_id 外键 → 连接 data_snapshots
                    if col["name"] == "snapshot_id":
                        self.edges[table].append(("data_snapshots", "snapshot_id", "snapshot_id"))
                    # 检测 bid_id, contract_id 等外键
                    if col["name"].endswith("_id") and col["name"] != "snapshot_id" and col["name"] != "_row_id":
                        ref_table = col["name"].replace("_id", "") + "s"  # 简单推测
                        if ref_table in user_tables or ref_table in tables:
                            self.edges[table].append((ref_table, col["name"], "snapshot_id"))
            except Exception as e:
                logger.debug("关系图构建跳过 %s: %s", table, e)

        # 同数据源快照之间的关联 (同base名不同期间的表通过快照关联)
        base_tables = {}
        for t in user_tables:
            base = re.sub(r'_\d{4}_\d{2}$', '', t)
            base_tables.setdefault(base, []).append(t)
        for base, tbls in base_tables.items():
            if len(tbls) >= 2:
                # 同base的表之间可通过快照时间关联
                for i, t1 in enumerate(tbls):
                    for t2 in tbls[i+1:]:
                        self.edges.setdefault(t1, []).append(
                            (t2, "data_period", "data_period"))
                        self.edges.setdefault(t2, []).append(
                            (t1, "data_period", "data_period"))

        self._built = True
        logger.info("JOIN图: %d 表, %d 边", len(self.edges),
                     sum(len(v) for v in self.edges.values()))

    def find_path(self, from_table: str, to_table: str) -> list[dict] | None:
        """BFS 最短路径"""
        self.build()
        if from_table not in self.edges or to_table not in self.edges:
            return None
        if from_table == to_table:
            return []

        visited = {from_table}
        queue = deque([(from_table, [])])
        while queue:
            current, path = queue.popleft()
            for target, from_col, to_col in self.edges.get(current, []):
                if target in visited:
                    continue
                new_path = path + [{
                    "from_table": current, "to_table": target,
                    "from_col": from_col, "to_col": to_col,
                }]
                if target == to_table:
                    return new_path
                visited.add(target)
                queue.append((target, new_path))
        return None

    def generate_join_sql(self, base_table: str, select_cols: list[str],
                          where_conditions: list[str] = None,
                          target_tables: list[str] = None) -> str:
        """生成跨表 JOIN SQL"""
        if not target_tables:
            return f'SELECT {", ".join(select_cols)} FROM "{base_table}"'

        # 为每个目标表找JOIN路径
        join_clauses = []
        all_tables = {base_table}
        for tt in target_tables:
            if tt == base_table or tt in all_tables:
                continue
            path = self.find_path(base_table, tt)
            if path:
                for step in path:
                    if step["to_table"] not in all_tables:
                        join_clauses.append(
                            f'LEFT JOIN "{step["to_table"]}" '
                            f'ON "{step["from_table"]}"."{step["from_col"]}" = '
                            f'"{step["to_table"]}"."{step["to_col"]}"'
                        )
                        all_tables.add(step["to_table"])

        joins = "\n  ".join(join_clauses)
        wheres = f'\nWHERE {" AND ".join(where_conditions)}' if where_conditions else ''
        return f'SELECT {", ".join(select_cols)}\nFROM "{base_table}"\n  {joins}{wheres}'


def detect_cross_table_metric(name: str, explanation: str = "") -> list[str] | None:
    """检测指标是否需要跨表查询 (如'人均中标额'需要CRM+HR)"""
    cross_keywords = {
        "人均": ["crm", "hr"],
        "转化率": ["opportunities", "contracts"],
        "周转率": ["accounts_receivable", "contracts"],
    }
    for kw, tables in cross_keywords.items():
        if kw in name:
            return tables
    return None
