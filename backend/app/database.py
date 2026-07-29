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


# ═══════════════════════════════════════════
# PostgreSQL 连接器 (生产环境)
# ═══════════════════════════════════════════

class PostgresConnector:
    """PostgreSQL — 与 DatabaseConnector 接口兼容"""

    def __init__(self, dsn: str = None):
        self.dsn = dsn or config.db_path
        self._pool = None

    def _get_pool(self):
        if self._pool is None:
            try:
                from psycopg2 import pool
                dsn = self.dsn if self.dsn.startswith("postgres") else (
                    "host=localhost port=5432 dbname=smart_query "
                    "user=smart_query password=smart_query"
                )
                self._pool = pool.ThreadedConnectionPool(1, 10, dsn)
                logger.info("PostgreSQL pool created")
            except ImportError:
                raise RuntimeError("psycopg2 not installed")
        return self._pool

    @contextmanager
    def connect(self):
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            yield conn; conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            pool.putconn(conn)

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        pg_sql = sql.replace('?', '%s')
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(pg_sql, params)
            if cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
            return []

    def execute_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self.execute(sql, params)
        return rows[0] if rows else None

    def execute_write(self, sql: str, params: tuple = ()) -> int:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql.replace('?', '%s'), params)
            return cur.rowcount

    def insert_and_get_id(self, sql: str, params: tuple = ()) -> int:
        pg_sql = sql.replace('?', '%s').rstrip(';') + ' RETURNING id'
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(pg_sql, params)
            row = cur.fetchone()
            return row[0] if row else 0

    def get_tables(self) -> list[str]:
        rows = self.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        return [r["table_name"] for r in rows]

    def table_exists(self, name: str) -> bool:
        return self.execute_one("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s", (name,)) is not None

    def get_table_schema(self, tn: str) -> list[dict]:
        return self.execute("SELECT column_name AS name, data_type AS type FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position", (tn,))

    def get_snapshots(self) -> list[dict]:
        return self.execute("SELECT * FROM data_snapshots ORDER BY data_period")

    def get_latest_snapshot(self) -> dict | None:
        return self.execute_one("SELECT * FROM data_snapshots ORDER BY ingestion_time DESC LIMIT 1")

    def get_all_users(self) -> list[dict]:
        return self.execute("SELECT * FROM users ORDER BY user_id")

    def get_user_by_username(self, username: str) -> dict | None:
        return self.execute_one("SELECT * FROM users WHERE username=%s", (username,))

    def get_query_history(self, user_id: int = None, limit: int = 50) -> list[dict]:
        if user_id:
            return self.execute("SELECT * FROM query_logs WHERE user_id=%s ORDER BY created_at DESC LIMIT %s", (user_id, limit))
        return self.execute("SELECT * FROM query_logs ORDER BY created_at DESC LIMIT %s", (limit,))

    def log_query(self, **kwargs) -> int:
        fields = ["user_id","username","role","original_query","cleaned_query","generated_sql","intent","complexity","exec_time_ms","row_count","status","error_message","snapshot_ids"]
        vals = [kwargs.get(f) for f in fields]
        ph = ",".join(["%s"]*len(fields))
        return self.insert_and_get_id(f"INSERT INTO query_logs ({','.join(fields)}) VALUES ({ph})", tuple(vals))

    def save_feedback(self, query_log_id: int, user_id: int, rating: str, comment: str = "", suggested_sql: str = "") -> int:
        return self.insert_and_get_id("INSERT INTO query_feedback (query_log_id,user_id,rating,comment,suggested_sql) VALUES (%s,%s,%s,%s,%s)", (query_log_id,user_id,rating,comment,suggested_sql))
