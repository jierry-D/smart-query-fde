#!/usr/bin/env python3
"""
数据库初始化脚本 — 建表 + 种子数据 + 初始用户

用法:
    python backend/db/init_db.py
"""

import sqlite3
import random
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent / "smart_query.db"

# ── 模拟数据常量 ──
BUSINESS_LINES = ["数字政务", "信创产业", "大数据服务", "智慧城市", "跨境合作"]
REGIONS = ["南宁市", "柳州市", "桂林市", "玉林市", "北海市", "梧州市", "百色市", "河池市", "钦州市", "贵港市"]
DEPARTMENTS = ["数字政务事业部", "信创事业部", "大数据事业部", "智慧城市事业部", "跨境合作事业部"]
CUSTOMERS = [
    ("广西壮族自治区大数据发展局", "政府"),
    ("南宁市人民政府", "政府"),
    ("柳州钢铁集团", "国企"),
    ("广西投资集团", "国企"),
    ("中国—东盟信息港", "国企"),
    ("广西北部湾国际港务集团", "国企"),
    ("广西林业集团", "国企"),
    ("桂林电子科技大学", "事业单位"),
    ("广西医科大学第一附属医院", "事业单位"),
    ("数字广西集团", "国企"),
    ("广西农信社", "金融"),
    ("桂林银行", "金融"),
    ("上汽通用五菱", "制造"),
    ("玉柴机器集团", "制造"),
    ("广西建工集团", "建筑"),
]
CHANNELS = ["公开招标", "竞争性磋商", "邀标", "单一来源", "战略合作"]
STATUS_OPPORTUNITY = ["正常跟进", "停滞预警", "已转化", "已关闭"]
STATUS_CONTRACT = ["已签约", "执行中", "已完工", "已终止"]

TABLES = ["bid_management", "contracts", "opportunities", "accounts_receivable"]
SNAPSHOT_MONTHS = [
    ("2026-07", "2026-08-03 09:15:00", "7月经营月报"),
    ("2026-08", "2026-09-02 10:30:00", "8月经营月报"),
    ("2026-09", "2026-09-28 14:00:00", "9月经营月报"),
]

random.seed(42)


def create_tables(conn):
    """建表"""
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

    -- 用户表
    CREATE TABLE users (
        user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username        TEXT NOT NULL UNIQUE,
        display_name    TEXT NOT NULL,
        password_hash   TEXT NOT NULL,
        role            TEXT NOT NULL CHECK(role IN ('admin', 'leader', 'employee')),
        department      TEXT NOT NULL DEFAULT '',
        region          TEXT DEFAULT '',
        position        TEXT DEFAULT '',
        is_active       INTEGER NOT NULL DEFAULT 1,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login      TIMESTAMP,
        login_count     INTEGER DEFAULT 0
    );

    -- 刷新令牌表
    CREATE TABLE refresh_tokens (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL REFERENCES users(user_id),
        token           TEXT UNIQUE NOT NULL,
        expires_at      TIMESTAMP NOT NULL,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 用户数据权限表 (细粒度 RBAC)
    CREATE TABLE user_data_permissions (
        permission_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL REFERENCES users(user_id),
        department      TEXT,
        region          TEXT,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ============================================================
    -- 数据快照元数据 (双时间维度)
    -- ============================================================

    CREATE TABLE data_snapshots (
        snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name      TEXT NOT NULL DEFAULT '',
        data_period     TEXT NOT NULL,
        ingestion_time  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        uploaded_by     INTEGER REFERENCES users(user_id),
        description     TEXT,
        total_rows      INTEGER DEFAULT 0,
        UNIQUE(table_name, data_period)
    );

    -- ============================================================
    -- 业务表 (含 department 字段用于 RBAC 数据隔离)
    -- ============================================================

    CREATE TABLE bid_management (
        bid_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id     INTEGER NOT NULL REFERENCES data_snapshots(snapshot_id),
        project_name    TEXT NOT NULL,
        contract_amount REAL NOT NULL,
        bid_date        TEXT NOT NULL,
        business_line   TEXT NOT NULL,
        region          TEXT NOT NULL,
        department      TEXT NOT NULL DEFAULT '',
        customer_name   TEXT,
        bid_method      TEXT NOT NULL DEFAULT '',
        is_won          INTEGER DEFAULT 1
    );

    CREATE TABLE contracts (
        contract_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id     INTEGER NOT NULL REFERENCES data_snapshots(snapshot_id),
        project_name    TEXT NOT NULL,
        contract_amount REAL NOT NULL,
        signed_date     TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT '已签约',
        business_line   TEXT NOT NULL,
        region          TEXT NOT NULL DEFAULT '',
        department      TEXT NOT NULL DEFAULT '',
        customer_name   TEXT,
        bid_id          INTEGER
    );

    CREATE TABLE opportunities (
        opportunity_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id     INTEGER NOT NULL REFERENCES data_snapshots(snapshot_id),
        project_name    TEXT NOT NULL DEFAULT '',
        estimated_amount REAL NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT '正常跟进',
        created_date    TEXT NOT NULL,
        last_follow_date TEXT,
        source_channel  TEXT NOT NULL DEFAULT '',
        business_line   TEXT NOT NULL,
        department      TEXT NOT NULL DEFAULT '',
        customer_name   TEXT,
        follow_days_gap INTEGER DEFAULT 0
    );

    CREATE TABLE accounts_receivable (
        ar_id           INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id     INTEGER NOT NULL REFERENCES data_snapshots(snapshot_id),
        contract_name   TEXT NOT NULL DEFAULT '',
        total_amount    REAL NOT NULL DEFAULT 0,
        received_amount REAL NOT NULL DEFAULT 0,
        due_date        TEXT NOT NULL,
        overdue_days    INTEGER DEFAULT 0,
        business_line   TEXT NOT NULL DEFAULT '',
        region          TEXT NOT NULL DEFAULT '',
        department      TEXT NOT NULL DEFAULT '',
        customer_name   TEXT,
        status          TEXT DEFAULT '未结清'
    );

    -- ============================================================
    -- 系统表
    -- ============================================================

    -- 查询日志
    CREATE TABLE query_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER REFERENCES users(user_id),
        username        TEXT,
        role            TEXT,
        original_query  TEXT NOT NULL,
        cleaned_query   TEXT,
        generated_sql   TEXT,
        intent          TEXT,
        complexity      TEXT,
        exec_time_ms    REAL,
        row_count       INTEGER,
        status          TEXT DEFAULT 'success',
        error_message   TEXT,
        snapshot_ids    TEXT,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 反馈表
    CREATE TABLE query_feedback (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        query_log_id    INTEGER REFERENCES query_logs(id),
        user_id         INTEGER REFERENCES users(user_id),
        rating          TEXT CHECK(rating IN ('up', 'down')),
        comment         TEXT,
        suggested_sql   TEXT,
        is_resolved     INTEGER DEFAULT 0,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 审计日志
    CREATE TABLE audit_logs (
        log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER REFERENCES users(user_id),
        action          TEXT NOT NULL,
        target_type     TEXT,
        target_id       TEXT,
        details         TEXT,
        success         INTEGER DEFAULT 1,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 指标注册表
    CREATE TABLE metric_registry (
        metric_id       TEXT PRIMARY KEY,
        name            TEXT NOT NULL UNIQUE,
        display_name    TEXT,
        category        TEXT NOT NULL,
        explanation     TEXT,
        formula         TEXT,
        source          TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        complexity      TEXT DEFAULT 'L1',
        table_name      TEXT,
        sql_template    TEXT,
        result_format   TEXT DEFAULT 'number',
        result_unit     TEXT DEFAULT '',
        alert_level     TEXT,
        tags            TEXT,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)


def seed_users(conn):
    """创建初始用户 (密码用 bcrypt hash 预计算)"""
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    users = [
        ("admin", pwd.hash("admin123"), "系统管理员", "admin", "", "", "系统管理员"),
        ("leader", pwd.hash("leader123"), "张总监", "leader", "数字政务事业部", "", "事业部总监"),
        ("employee", pwd.hash("emp123"), "李销售", "employee", "数字政务事业部", "南宁市", "销售经理"),
        ("emp_liuzhou", pwd.hash("emp123"), "王销售", "employee", "数字政务事业部", "柳州市", "销售代表"),
        ("leader_xinchuang", pwd.hash("leader123"), "陈主管", "leader", "信创事业部", "", "事业部主管"),
        ("emp_xinchuang", pwd.hash("emp123"), "赵技术", "employee", "信创事业部", "南宁市", "技术销售"),
    ]

    conn.executemany(
        "INSERT INTO users (username, password_hash, display_name, role, department, region, position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        users,
    )

    # 为 employee 角色创建数据权限
    conn.execute(
        "INSERT INTO user_data_permissions (user_id, department, region) VALUES (3, '数字政务事业部', '南宁市')"
    )
    conn.execute(
        "INSERT INTO user_data_permissions (user_id, department, region) VALUES (4, '数字政务事业部', '柳州市')"
    )
    conn.execute(
        "INSERT INTO user_data_permissions (user_id, department, region) VALUES (6, '信创事业部', '南宁市')"
    )


def seed_snapshots(conn):
    """生成 3 个月 × 4 张表的快照数据"""
    snapshots = []
    sid = 1
    for period, ingestion, desc in SNAPSHOT_MONTHS:
        for table in TABLES:
            snapshots.append((sid, table, period, ingestion, desc, 10))
            sid += 1

    conn.executemany(
        "INSERT INTO data_snapshots (snapshot_id, table_name, data_period, ingestion_time, description, total_rows) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        snapshots,
    )

    _seed_business_data(conn)


def _seed_business_data(conn):
    """生成业务数据"""
    # 中标管理 (每快照 ~10行)
    for snap in range(1, 13):
        table_name = TABLES[(snap - 1) % 4]
        if table_name != "bid_management":
            continue
        for i in range(10):
            bl = random.choice(BUSINESS_LINES)
            region = random.choice(REGIONS)
            dept = f"{bl}事业部" if bl != "跨境合作" else "跨境合作事业部"
            amount = round(random.uniform(50, 800), 2)
            bid_date = f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}"
            customer = random.choice(CUSTOMERS)
            conn.execute(
                "INSERT INTO bid_management (snapshot_id, project_name, contract_amount, bid_date, business_line, region, department, customer_name, bid_method, is_won) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snap, f"{bl}项目-{i+1}", amount, bid_date, bl, region, dept,
                 customer[0], random.choice(CHANNELS), random.choice([0, 1, 1, 1])),
            )

    # 合同管理
    for snap in range(1, 13):
        table_name = TABLES[(snap - 1) % 4]
        if table_name != "contracts":
            continue
        for i in range(7):
            bl = random.choice(BUSINESS_LINES)
            region = random.choice(REGIONS)
            dept = f"{bl}事业部" if bl != "跨境合作" else "跨境合作事业部"
            amount = round(random.uniform(30, 600), 2)
            signed = f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}"
            customer = random.choice(CUSTOMERS)
            status = random.choice(STATUS_CONTRACT)
            conn.execute(
                "INSERT INTO contracts (snapshot_id, project_name, contract_amount, signed_date, status, business_line, region, department, customer_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snap, f"{bl}合同-{i+1}", amount, signed, status, bl, region, dept, customer[0]),
            )

    # 商机管理
    for snap in range(1, 13):
        table_name = TABLES[(snap - 1) % 4]
        if table_name != "opportunities":
            continue
        for i in range(10):
            bl = random.choice(BUSINESS_LINES)
            dept = f"{bl}事业部" if bl != "跨境合作" else "跨境合作事业部"
            amount = round(random.uniform(20, 500), 2)
            created = f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}"
            customer = random.choice(CUSTOMERS)
            status = random.choice(STATUS_OPPORTUNITY)
            last_follow = f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}"
            gap = random.randint(0, 60)
            conn.execute(
                "INSERT INTO opportunities (snapshot_id, project_name, estimated_amount, status, created_date, last_follow_date, source_channel, business_line, department, customer_name, follow_days_gap) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snap, f"{bl}商机-{i+1}", amount, status, created, last_follow,
                 random.choice(CHANNELS), bl, dept, customer[0], gap),
            )

    # 应收账款
    for snap in range(1, 13):
        table_name = TABLES[(snap - 1) % 4]
        if table_name != "accounts_receivable":
            continue
        for i in range(6):
            bl = random.choice(BUSINESS_LINES)
            region = random.choice(REGIONS)
            dept = f"{bl}事业部" if bl != "跨境合作" else "跨境合作事业部"
            total = round(random.uniform(10, 300), 2)
            received = round(total * random.uniform(0, 0.9), 2)
            due = f"2026-{random.randint(1,9):02d}-{random.randint(1,28):02d}"
            overdue = random.randint(0, 200)
            customer = random.choice(CUSTOMERS)
            conn.execute(
                "INSERT INTO accounts_receivable (snapshot_id, contract_name, total_amount, received_amount, due_date, overdue_days, business_line, region, department, customer_name, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snap, f"{bl}应收-{i+1}", total, received, due, overdue,
                 bl, region, dept, customer[0], "已结清" if overdue == 0 else "未结清"),
            )


def seed_metrics(conn):
    """导入指标注册数据 (含 SQL 模板)"""
    metrics = [
        ("m001", "年度累计中标总额", "集团经营总览表", "L1", "available",
         "bid_management", "number", "万元", None,
         'SELECT ROUND(SUM(contract_amount), 2) AS value FROM bid_management WHERE is_won = 1'),
        ("m002", "本期中标额", "集团经营总览表", "L1", "available",
         "bid_management", "number", "万元", None,
         'SELECT ROUND(SUM(contract_amount), 2) AS value FROM bid_management WHERE is_won = 1'),
        ("m003", "年度累计签约总额", "集团经营总览表", "L1", "available",
         "contracts", "number", "万元", None,
         'SELECT ROUND(SUM(contract_amount), 2) AS value FROM contracts WHERE status IN ("已签约", "执行中", "已完工")'),
        ("m004", "本期签约额", "集团经营总览表", "L1", "available",
         "contracts", "number", "万元", None,
         'SELECT ROUND(SUM(contract_amount), 2) AS value FROM contracts WHERE status IN ("已签约", "执行中", "已完工")'),
        ("m005", "当期营业收入", "集团经营总览表", "L1", "pending",
         None, "number", "万元", None, None),
        ("m014", "存量客户总数", "客户全景管理表", "L1", "available",
         "contracts", "integer", "个", None,
         'SELECT COUNT(DISTINCT customer_name) AS value FROM contracts'),
        ("m025", "商机签约转化率", "商机全生命周期管理表", "L3", "available",
         "contracts", "percent", "%", None,
         'SELECT ROUND(CAST(SUM(CASE WHEN status IN ("已签约","执行中","已完工") THEN contract_amount ELSE 0 END) AS REAL) / NULLIF(SUM(contract_amount), 0) * 100, 2) AS value FROM contracts'),
        ("m034", "本期中标项目数", "中标与项目执行管理表", "L1", "available",
         "bid_management", "integer", "个", None,
         'SELECT COUNT(*) AS value FROM bid_management WHERE is_won = 1'),
        ("m048", "应收账款总余额", "营收与应收账款管理表", "L1", "available",
         "accounts_receivable", "number", "万元", None,
         'SELECT ROUND(SUM(total_amount - received_amount), 2) AS value FROM accounts_receivable'),
        # ── 新增8个指标 (v2.1 从MVP迁移) ──
        ("m052", "正常跟进商机数量", "商机全生命周期管理表", "L1", "available",
         "opportunities", "integer", "个", None,
         'SELECT COUNT(*) AS value FROM opportunities WHERE status NOT IN ("停滞预警","已关闭")'),
        ("m053", "有效储备商机总数量", "商机全生命周期管理表", "L1", "available",
         "opportunities", "integer", "个", None,
         'SELECT COUNT(*) AS value FROM opportunities WHERE status="正常跟进"'),
        ("m054", "储备商机总金额", "商机全生命周期管理表", "L1", "available",
         "opportunities", "number", "万元", None,
         'SELECT ROUND(SUM(estimated_amount),2) AS value FROM opportunities WHERE status="正常跟进"'),
        ("m055", "投标中标率", "商机全生命周期管理表", "L2", "available",
         "bid_management", "percent", "%", None,
         'SELECT ROUND(SUM(CASE WHEN is_won=1 THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0),2) AS value FROM bid_management'),
        ("m056", "在手执行项目总数", "中标与项目执行管理表", "L1", "available",
         "contracts", "integer", "个", None,
         'SELECT COUNT(*) AS value FROM contracts WHERE status="执行中"'),
        ("m057", "各业务线中标金额占比", "区域与渠道管理表", "L2", "available",
         "bid_management", "percent", "%", None,
         'SELECT business_line AS label, ROUND(SUM(CASE WHEN is_won=1 THEN contract_amount ELSE 0 END)*100.0/NULLIF((SELECT SUM(contract_amount) FROM bid_management WHERE is_won=1),0),2) AS value FROM bid_management WHERE is_won=1 GROUP BY business_line ORDER BY value DESC'),
        ("m058", "应收账款周转率", "营收与应收账款管理表", "L3", "available",
         "accounts_receivable", "percent", "%", None,
         'SELECT ROUND(AVG(total_amount)*100.0/NULLIF((SELECT AVG(total_amount) FROM accounts_receivable),0),2) AS value FROM accounts_receivable'),
        ("m059", "大额逾期应收款金额", "风险预警管理表", "L2", "available",
         "accounts_receivable", "number", "万元", "紧急",
         'SELECT ROUND(SUM(total_amount),2) AS value FROM accounts_receivable WHERE overdue_days > 180'),
        # ── 原有指标 ──
        ("m051", "逾期90天以上应收款金额", "营收与应收账款管理表", "L2", "available",
         "accounts_receivable", "number", "万元", "紧急",
         'SELECT ROUND(SUM(total_amount - received_amount), 2) AS value FROM accounts_receivable WHERE overdue_days > 90'),
        ("m069", "各地市中标额", "区域与渠道管理表", "L1", "available",
         "bid_management", "table", "万元", None,
         'SELECT region AS label, ROUND(SUM(contract_amount), 2) AS value FROM bid_management WHERE is_won = 1 GROUP BY region ORDER BY value DESC'),
        ("m078", "长期停滞商机数量", "风险预警管理表", "L1", "available",
         "opportunities", "integer", "个", "重要",
         'SELECT COUNT(*) AS value FROM opportunities WHERE status = "停滞预警" OR follow_days_gap > 30'),
    ]
    conn.executemany(
        "INSERT INTO metric_registry (metric_id, name, category, complexity, status, table_name, result_format, result_unit, alert_level, sql_template) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        metrics,
    )


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    print("创建表结构...")
    create_tables(conn)

    print("创建初始用户...")
    seed_users(conn)

    print("生成快照和业务数据...")
    seed_snapshots(conn)

    print("导入指标注册数据...")
    seed_metrics(conn)

    conn.commit()
    conn.close()

    print(f"✅ 数据库初始化完成: {DB_PATH}")
    print(f"   用户: admin/admin123, leader/leader123, employee/emp123")
    print(f"   快照: 12 个 (3个月 × 4张表)")
    print(f"   业务数据: ~400 行")
    print(f"   指标注册: 12 个核心指标")


if __name__ == "__main__":
    main()
