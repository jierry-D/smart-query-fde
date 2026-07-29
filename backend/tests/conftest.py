"""测试夹具 — 隔离 SQLite 数据库"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 确保 backend/ 和项目根都在 python 路径中
_backend_dir = Path(__file__).resolve().parent.parent
_project_root = _backend_dir.parent
sys.path.insert(0, str(_backend_dir))
sys.path.insert(0, str(_project_root))


@pytest.fixture
def tmp_db_path():
    """创建临时数据库文件路径"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except Exception:
        pass


@pytest.fixture
def db_connector(tmp_db_path):
    """创建带种子数据的隔离数据库连接器"""
    from backend.app.database import DatabaseConnector
    import sqlite3

    # 建表结构
    conn = sqlite3.connect(tmp_db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS data_snapshots (
        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT NOT NULL DEFAULT '',
        data_period TEXT NOT NULL,
        ingestion_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        description TEXT,
        total_rows INTEGER DEFAULT 0,
        UNIQUE(table_name, data_period)
    )""")

    # 建业务表
    conn.execute("""CREATE TABLE IF NOT EXISTS bid_management (
        _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        contract_name TEXT,
        amount REAL,
        region TEXT,
        business_line TEXT,
        is_won INTEGER DEFAULT 1,
        bid_date TEXT,
        FOREIGN KEY (snapshot_id) REFERENCES data_snapshots(snapshot_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS contracts (
        _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        contract_name TEXT,
        amount REAL,
        region TEXT,
        business_line TEXT,
        signed_date TEXT,
        FOREIGN KEY (snapshot_id) REFERENCES data_snapshots(snapshot_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS opportunities (
        _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        opportunity_name TEXT,
        estimated_amount REAL,
        region TEXT,
        business_line TEXT,
        status TEXT DEFAULT '有效跟进',
        FOREIGN KEY (snapshot_id) REFERENCES data_snapshots(snapshot_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS metric_registry (
        metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        display_name TEXT,
        category TEXT DEFAULT '',
        status TEXT DEFAULT 'available',
        complexity TEXT DEFAULT 'L1',
        explanation TEXT,
        formula TEXT,
        source TEXT,
        table_name TEXT,
        sql_template TEXT,
        result_format TEXT DEFAULT 'number',
        result_unit TEXT DEFAULT '',
        alert_level TEXT,
        tags TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name TEXT,
        role TEXT DEFAULT 'employee',
        department TEXT DEFAULT '',
        region TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS refresh_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""")

    # 种子数据
    conn.execute("INSERT OR IGNORE INTO users (user_id, username, password_hash, display_name, role, department, region) VALUES (1, 'admin', '$2b$12$LJ3m4ys3YsmYS5S0mRQx0eCw/JvO8V.JuDBG9qNKaDZHDaFQrGUqG', '管理员', 'admin', '', '')")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username, password_hash, display_name, role, department, region) VALUES (2, 'employee', '$2b$12$LJ3m4ys3YsmYS5S0mRQx0eCw/JvO8V.JuDBG9qNKaDZHDaFQrGUqG', '员工', 'employee', '数字政务事业部', '南宁市')")

    # 快照
    conn.execute("INSERT OR IGNORE INTO data_snapshots (snapshot_id, table_name, data_period, total_rows) VALUES (1, 'bid_management', '2026-07', 10)")
    conn.execute("INSERT OR IGNORE INTO data_snapshots (snapshot_id, table_name, data_period, total_rows) VALUES (2, 'bid_management', '2026-08', 10)")
    conn.execute("INSERT OR IGNORE INTO data_snapshots (snapshot_id, table_name, data_period, total_rows) VALUES (3, 'bid_management', '2026-09', 10)")

    # 业务数据
    regions = ['南宁市', '柳州市', '桂林市']
    biz_lines = ['数字政务', '信创产业', '智慧城市']
    for sid in [1, 2, 3]:
        for i in range(5):
            conn.execute(
                "INSERT INTO bid_management (snapshot_id, contract_name, amount, region, business_line, is_won) VALUES (?, ?, ?, ?, ?, ?)",
                (sid, f"项目{sid}-{i}", 100.0 + i * 50, regions[i % 3], biz_lines[i % 3], 1 if i % 2 == 0 else 0)
            )

    # 指标注册
    metrics = [
        ("年度累计中标总额", "经营总览", "available", "L1", "number", "万元",
         "bid_management", "SELECT ROUND(SUM(amount),2) AS value FROM bid_management WHERE is_won=1"),
        ("本期中标额", "经营总览", "available", "L1", "number", "万元",
         "bid_management", "SELECT ROUND(SUM(amount),2) AS value FROM bid_management"),
        ("各地市中标额", "区域管理", "available", "L2", "table", "万元",
         "bid_management", "SELECT region AS label, ROUND(SUM(amount),2) AS value FROM bid_management WHERE is_won=1 GROUP BY region"),
        ("逾期应收账款", "风险管理", "pending", "L3", "number", "万元",
         None, None),
    ]
    for m in metrics:
        conn.execute(
            "INSERT OR IGNORE INTO metric_registry (name, category, status, complexity, result_format, result_unit, table_name, sql_template) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            m
        )

    conn.commit()
    conn.close()

    # 创建连接器
    db = DatabaseConnector(tmp_db_path)
    return db


@pytest.fixture
def admin_user():
    return {"user_id": 1, "username": "admin", "role": "admin",
            "department": "", "region": "", "display_name": "管理员"}


@pytest.fixture
def employee_user():
    return {"user_id": 2, "username": "employee", "role": "employee",
            "department": "数字政务事业部", "region": "南宁市", "display_name": "员工"}
