"""数据库连接管理 — SQLite (dev) / PostgreSQL (prod)"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

from .config import config
from .core.logging import get_logger

logger = get_logger(__name__)


class DatabaseConnector:
    """统一的数据库访问抽象层"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.db_path

    @contextmanager
    def connect(self):
        """获取连接 (自动提交/回滚/关闭)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        """执行 SELECT, 返回字典列表"""
        logger.debug("SQL: %s", sql[:200])
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def execute_one(self, sql: str, params: tuple = ()) -> dict | None:
        """执行 SELECT, 返回单条"""
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def execute_write(self, sql: str, params: tuple = ()) -> int:
        """执行 INSERT/UPDATE/DELETE, 返回影响行数"""
        logger.debug("Write SQL: %s", sql[:200])
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.rowcount

    def insert_and_get_id(self, sql: str, params: tuple = ()) -> int:
        """执行 INSERT 并返回自增ID"""
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.lastrowid

    def table_exists(self, table_name: str) -> bool:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            return cur.fetchone() is not None

    def get_tables(self) -> list[str]:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            return [row["name"] for row in cur.fetchall()]

    def get_table_schema(self, table_name: str) -> list[dict]:
        if not self.table_exists(table_name):
            return []
        safe_name = table_name.replace('"', '""')
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(f'PRAGMA table_info("{safe_name}")')
            return [dict(row) for row in cur.fetchall()]

    # ── 快照查询 ──

    def get_snapshots(self) -> list[dict]:
        return self.execute(
            "SELECT * FROM data_snapshots ORDER BY data_period"
        )

    def get_latest_snapshot(self) -> dict | None:
        return self.execute_one(
            "SELECT * FROM data_snapshots ORDER BY ingestion_time DESC LIMIT 1"
        )

    def get_snapshots_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        return self.execute(
            f"SELECT * FROM data_snapshots WHERE snapshot_id IN ({placeholders})",
            tuple(ids),
        )

    def get_snapshots_by_period(self, period: str) -> list[dict]:
        return self.execute(
            "SELECT * FROM data_snapshots WHERE data_period = ?", (period,)
        )

    # ── 用户查询 ──

    def get_user_by_username(self, username: str) -> dict | None:
        return self.execute_one(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,),
        )

    def get_user_by_id(self, user_id: int) -> dict | None:
        return self.execute_one(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )

    def get_all_users(self) -> list[dict]:
        return self.execute(
            "SELECT user_id, username, display_name, role, department, region, position, is_active, created_at, last_login "
            "FROM users ORDER BY user_id"
        )

    # ── 查询日志 ──

    def log_query(self, **kwargs) -> int:
        fields = ["user_id", "username", "role", "original_query", "cleaned_query",
                   "generated_sql", "intent", "complexity", "exec_time_ms",
                   "row_count", "status", "error_message", "snapshot_ids"]
        values = [kwargs.get(f) for f in fields]
        placeholders = ",".join("?" * len(fields))
        cols = ",".join(fields)
        sql = f"INSERT INTO query_logs ({cols}) VALUES ({placeholders})"
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, values)
            return cur.lastrowid

    def get_query_history(self, user_id: int = None, limit: int = 50) -> list[dict]:
        if user_id:
            return self.execute(
                "SELECT * FROM query_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        return self.execute(
            "SELECT * FROM query_logs ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    # ── 反馈 ──

    def save_feedback(self, query_log_id: int, user_id: int, rating: str,
                      comment: str = "", suggested_sql: str = "") -> int:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO query_feedback (query_log_id, user_id, rating, comment, suggested_sql) "
                "VALUES (?, ?, ?, ?, ?)",
                (query_log_id, user_id, rating, comment, suggested_sql),
            )
            return cur.lastrowid
