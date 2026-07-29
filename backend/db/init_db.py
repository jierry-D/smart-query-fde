#!/usr/bin/env python3
"""
数据库初始化 — 纯框架模式 (可复用)

创建所有表结构 + 默认admin用户。
不包含任何业务数据、指标、快照。

用法:
    python backend/db/init_db.py          # 初始化空白数据库
    python backend/db/init_db.py --demo   # 带CRM示例数据 (演示用)

新项目接入:
    1. 运行本脚本初始化空白数据库
    2. 通过 Web UI 上传 Excel → 自动接入
    3. 配置 backend/metrics/enterprise_kb.yaml → 添加领域同义词
    4. 开始自然语言查询
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent / "smart_query.db"


def create_tables(conn):
    """建表 — 所有系统表结构"""
    conn.executescript("""
    -- ============================================================
    -- 用户与权限
    -- ============================================================
    DROP TABLE IF EXISTS query_feedback;
    DROP TABLE IF EXISTS query_logs;
    DROP TABLE IF EXISTS audit_logs;
    DROP TABLE IF EXISTS feedback;
    DROP TABLE IF EXISTS metric_registry;
    DROP TABLE IF EXISTS user_data_permissions;
    DROP TABLE IF EXISTS refresh_tokens;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS accounts_receivable;
    DROP TABLE IF EXISTS contracts;
    DROP TABLE IF EXISTS opportunities;
    DROP TABLE IF EXISTS bid_management;
    DROP TABLE IF EXISTS data_snapshots;
    DROP TABLE IF EXISTS onboarding_queue;
    DROP TABLE IF EXISTS schema_registry;
    DROP TABLE IF EXISTS kb_suggestions;

    CREATE TABLE users (
        user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username        TEXT NOT NULL UNIQUE,
        password_hash   TEXT NOT NULL,
        display_name    TEXT,
        role            TEXT NOT NULL DEFAULT 'employee',
        department      TEXT DEFAULT '',
        region          TEXT DEFAULT '',
        position        TEXT DEFAULT '',
        is_active       INTEGER DEFAULT 1,
        last_login      TIMESTAMP,
        login_count     INTEGER DEFAULT 0,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE refresh_tokens (
        token       TEXT PRIMARY KEY,
        user_id     INTEGER NOT NULL,
        expires_at  TIMESTAMP NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );

    CREATE TABLE user_data_permissions (
        perm_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        table_name      TEXT NOT NULL,
        filter_column   TEXT,
        filter_value    TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );

    -- ============================================================
    -- 数据快照元数据
    -- ============================================================
    CREATE TABLE data_snapshots (
        snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name      TEXT NOT NULL DEFAULT '',
        data_period     TEXT NOT NULL,
        ingestion_time  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        description     TEXT,
        total_rows      INTEGER DEFAULT 0,
        UNIQUE(table_name, data_period)
    );

    -- ============================================================
    -- 指标注册表
    -- ============================================================
    CREATE TABLE metric_registry (
        metric_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL UNIQUE,
        display_name    TEXT,
        category        TEXT DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'pending',
        complexity      TEXT DEFAULT 'L1',
        explanation     TEXT DEFAULT '',
        formula         TEXT DEFAULT '',
        source          TEXT DEFAULT '',
        table_name      TEXT,
        sql_template    TEXT,
        result_format   TEXT DEFAULT 'number',
        result_unit     TEXT DEFAULT '',
        alert_level     TEXT,
        tags            TEXT DEFAULT '',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ============================================================
    -- 日志与反馈
    -- ============================================================
    CREATE TABLE query_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER,
        username        TEXT,
        role            TEXT,
        original_query  TEXT,
        cleaned_query   TEXT,
        generated_sql   TEXT,
        intent          TEXT DEFAULT '',
        complexity      TEXT DEFAULT '',
        exec_time_ms    REAL,
        row_count       INTEGER,
        status          TEXT DEFAULT 'success',
        error_message   TEXT DEFAULT '',
        snapshot_ids    TEXT DEFAULT '',
        matched_metric  TEXT DEFAULT '',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE query_feedback (
        feedback_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        query_log_id    INTEGER,
        user_id         INTEGER,
        rating          TEXT DEFAULT 'up',
        comment         TEXT DEFAULT '',
        suggested_sql   TEXT DEFAULT '',
        original_query  TEXT DEFAULT '',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE audit_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER,
        action          TEXT,
        detail          TEXT DEFAULT '',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ============================================================
    -- 数据接入与知识库 (Onboarding Pipeline)
    -- ============================================================
    CREATE TABLE IF NOT EXISTS onboarding_queue (
        queue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name      TEXT NOT NULL,
        config_json     TEXT NOT NULL,
        quality_score   INTEGER DEFAULT 0,
        status          TEXT DEFAULT 'pending',
        reviewer        TEXT,
        reviewed_at     TIMESTAMP,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS schema_registry (
        table_name      TEXT PRIMARY KEY,
        columns_json    TEXT NOT NULL,
        registered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS kb_suggestions (
        suggestion_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type     TEXT DEFAULT 'feedback',
        suggestion_type TEXT NOT NULL,
        original_query  TEXT,
        matched_metric  TEXT,
        user_comment    TEXT,
        proposed_change TEXT,
        status          TEXT DEFAULT 'pending',
        feedback_id     INTEGER,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        applied_at      TIMESTAMP
    );
    """)


def seed_admin(conn):
    """创建默认管理员"""
    from app.core.security import hash_password

    admin_pw = hash_password("admin123")

    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, display_name, role) "
        "VALUES (?, ?, ?, ?)",
        ("admin", admin_pw, "管理员", "admin"),
    )
    print("  ✅ admin 用户已创建 (admin/admin123)")


def seed_demo_data(conn):
    """生成 CRM 演示数据 (仅 --demo 模式)"""
    import random
    random.seed(42)

    BUSINESS_LINES = ["数字政务", "信创产业", "大数据服务", "智慧城市", "跨境合作"]
    REGIONS = ["南宁市", "柳州市", "桂林市", "玉林市", "北海市", "梧州市"]
    DEPARTMENTS = ["数字政务事业部", "信创事业部", "大数据事业部"]
    CUSTOMERS = [
        ("广西大数据发展局", "政府"), ("南宁市人民政府", "政府"),
        ("柳州钢铁集团", "国企"), ("广西投资集团", "国企"),
    ]
    STATUS_OPPORTUNITY = ["正常跟进", "停滞预警", "已转化", "已关闭"]
    STATUS_CONTRACT = ["已签约", "执行中", "已完工"]
    SNAPSHOT_MONTHS = [
        ("2026-07", "2026-08-03 09:15:00", "7月经营月报"),
        ("2026-08", "2026-09-02 10:30:00", "8月经营月报"),
        ("2026-09", "2026-09-28 14:00:00", "9月经营月报"),
    ]

    print("  生成演示数据...")

    # 创建演示用户
    from app.core.security import hash_password
    demo_users = [
        ("leader", "领导", "leader", "数字政务事业部", ""),
        ("employee", "员工", "employee", "数字政务事业部", "南宁市"),
    ]
    for uname, dname, role, dept, region in demo_users:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, display_name, role, department, region) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uname, hash_password("leader123" if role == "leader" else "emp123"),
             dname, role, dept, region),
        )
    print("  ✅ 演示用户: leader/leader123, employee/emp123")

    # 为每个表创建快照
    tables = ["bid_management", "contracts", "opportunities", "accounts_receivable"]
    for table in tables:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{table}" (
                _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                project_name TEXT,
                amount REAL DEFAULT 0,
                estimated_amount REAL DEFAULT 0,
                total_amount REAL DEFAULT 0,
                received_amount REAL DEFAULT 0,
                contract_amount REAL DEFAULT 0,
                balance REAL DEFAULT 0,
                region TEXT DEFAULT '',
                business_line TEXT DEFAULT '',
                department TEXT DEFAULT '',
                customer_name TEXT DEFAULT '',
                status TEXT DEFAULT '',
                is_won INTEGER DEFAULT 0,
                overdue_days INTEGER DEFAULT 0,
                follow_days_gap INTEGER DEFAULT 0,
                bid_date TEXT DEFAULT '',
                signed_date TEXT DEFAULT '',
                created_date TEXT DEFAULT '',
                due_date TEXT DEFAULT '',
                source_channel TEXT DEFAULT '',
                FOREIGN KEY (snapshot_id) REFERENCES data_snapshots(snapshot_id)
            )
        """)

    for table in tables:
        for period, ingest_time, desc in SNAPSHOT_MONTHS:
            conn.execute(
                "INSERT INTO data_snapshots (table_name, data_period, ingestion_time, description) "
                "VALUES (?, ?, ?, ?)",
                (table, period, ingest_time, desc),
            )
    print(f"  ✅ 12 个快照 ({len(tables)}表 × {len(SNAPSHOT_MONTHS)}月)")

    # 生成业务数据
    snapshots = conn.execute("SELECT snapshot_id, table_name FROM data_snapshots").fetchall()
    for sid, table in snapshots:
        for i in range(random.randint(3, 8)):
            bl = random.choice(BUSINESS_LINES)
            region = random.choice(REGIONS)
            dept = random.choice(DEPARTMENTS)
            cust = random.choice(CUSTOMERS)
            amount = round(random.uniform(50, 800), 2)

            if table == "bid_management":
                conn.execute(
                    f'INSERT INTO "{table}" (snapshot_id, project_name, contract_amount, bid_date, business_line, region, department, customer_name, is_won, source_channel) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (sid, f"{bl}项目-{i+1}", amount,
                     f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}",
                     bl, region, dept, cust[0], random.choice([0,1,1]),
                     random.choice(["公开招标","竞争性磋商"])),
                )
            elif table == "contracts":
                conn.execute(
                    f'INSERT INTO "{table}" (snapshot_id, project_name, contract_amount, signed_date, status, business_line, region, department, customer_name) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (sid, f"{bl}合同-{i+1}", amount,
                     f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}",
                     random.choice(STATUS_CONTRACT), bl, region, dept, cust[0]),
                )
            elif table == "opportunities":
                conn.execute(
                    f'INSERT INTO "{table}" (snapshot_id, project_name, estimated_amount, status, created_date, business_line, department, customer_name, follow_days_gap) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (sid, f"{bl}商机-{i+1}", amount,
                     random.choice(STATUS_OPPORTUNITY),
                     f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}",
                     bl, dept, cust[0], random.randint(0, 60)),
                )
            elif table == "accounts_receivable":
                received = round(amount * random.uniform(0.3, 0.9), 2)
                conn.execute(
                    f'INSERT INTO "{table}" (snapshot_id, project_name, total_amount, received_amount, due_date, overdue_days, business_line, region, department, customer_name, status) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (sid, f"{bl}应收-{i+1}", amount, received,
                     f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}",
                     random.randint(0, 200), bl, region, dept, cust[0], "未结清"),
                )

    for table in tables:
        cnt = conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()[0]
        conn.execute("UPDATE data_snapshots SET total_rows = total_rows + ? WHERE table_name = ?",
                     (cnt, table))
    print(f"  ✅ ~150 行业务数据")

    # 演示指标
    demo_metrics = [
        ("年度累计中标总额", "经营总览", "L1", "available",
         "bid_management", "number", "万元", None,
         'SELECT ROUND(SUM(contract_amount),2) AS value FROM bid_management WHERE is_won=1'),
        ("本期签约额", "经营总览", "L1", "available",
         "contracts", "number", "万元", None,
         'SELECT ROUND(SUM(contract_amount),2) AS value FROM contracts WHERE status IN ("已签约","执行中","已完工")'),
        ("存量客户总数", "客户管理", "L1", "available",
         "contracts", "integer", "个", None,
         'SELECT COUNT(DISTINCT customer_name) AS value FROM contracts'),
        ("商机签约转化率", "商机管理", "L3", "available",
         "contracts", "percent", "%", None,
         'SELECT ROUND(CAST(SUM(CASE WHEN status IN ("已签约","执行中","已完工") THEN contract_amount ELSE 0 END) AS REAL)/NULLIF(SUM(contract_amount),0)*100,2) AS value FROM contracts'),
        ("本期中标项目数", "项目管理", "L1", "available",
         "bid_management", "integer", "个", None,
         'SELECT COUNT(*) AS value FROM bid_management WHERE is_won=1'),
        ("应收账款总余额", "财务管理", "L1", "available",
         "accounts_receivable", "number", "万元", None,
         'SELECT ROUND(SUM(total_amount-received_amount),2) AS value FROM accounts_receivable'),
        ("正常跟进商机数量", "商机管理", "L1", "available",
         "opportunities", "integer", "个", None,
         'SELECT COUNT(*) AS value FROM opportunities WHERE status NOT IN ("停滞预警","已关闭")'),
        ("各地市中标额", "区域管理", "L2", "available",
         "bid_management", "table", "万元", None,
         'SELECT region AS label, ROUND(SUM(contract_amount),2) AS value FROM bid_management WHERE is_won=1 GROUP BY region ORDER BY value DESC'),
    ]
    for m in demo_metrics:
        conn.execute(
            "INSERT OR IGNORE INTO metric_registry (name, category, complexity, status, table_name, result_format, result_unit, alert_level, sql_template) "
            "VALUES (?,?,?,?,?,?,?,?,?)", m,
        )
    print(f"  ✅ {len(demo_metrics)} 个演示指标")


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    demo_mode = "--demo" in sys.argv

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    print("创建表结构...")
    create_tables(conn)

    print("创建管理员...")
    seed_admin(conn)

    if demo_mode:
        print("\n🎬 演示模式 — 生成 CRM 示例数据...")
        seed_demo_data(conn)
    else:
        print("\n💡 框架模式 — 空白数据库就绪")
        print("   下一步:")
        print("   1. 启动服务: python3 -m uvicorn backend.app.main:app")
        print("   2. 上传 Excel 数据 → 自动接入")
        print("   3. 配置 enterprise_kb.yaml → 添加领域同义词")
        print("   4. 如需演示数据: python backend/db/init_db.py --demo")

    conn.commit()
    conn.close()

    print(f"\n✅ 数据库初始化完成: {DB_PATH}")
    print(f"   用户: admin/admin123")
    if demo_mode:
        print(f"   演示用户: leader/leader123, employee/emp123")
        print(f"   快照: 12 个 | 业务数据: ~150 行 | 指标: 8 个")


if __name__ == "__main__":
    main()
