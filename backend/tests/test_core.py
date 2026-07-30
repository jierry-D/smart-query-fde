#!/usr/bin/env python3
"""单元测试 — 核心引擎"""

import sys
import pytest
from pathlib import Path

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.database import DatabaseConnector
from backend.app.core.security import (
    hash_password, verify_password,
    create_access_token, decode_token,
    get_data_scope, build_data_scope_sql,
)
from backend.app.engine.time_resolver import resolve_time, build_period_map
from backend.app.semantic.loader import MetricLoader


# ── 安全模块 ──

def test_password_hash():
    hashed = hash_password("test123")
    assert verify_password("test123", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_token():
    data = {"sub": "1", "username": "admin", "role": "admin"}
    token = create_access_token(data)
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded["username"] == "admin"
    assert decoded["role"] == "admin"


def test_jwt_invalid_token():
    assert decode_token("invalid.token.here") is None


def test_rbac_admin():
    admin = {"role": "admin", "department": "", "region": ""}
    assert get_data_scope(admin) == {}
    assert build_data_scope_sql(admin) == "1=1"


def test_rbac_leader():
    leader = {"role": "leader", "department": "数字政务事业部", "region": ""}
    scope = get_data_scope(leader)
    assert scope == {"department": "数字政务事业部"}


def test_rbac_employee():
    emp = {"role": "employee", "department": "数字政务事业部", "region": "南宁市"}
    scope = get_data_scope(emp)
    assert scope["department"] == "数字政务事业部"
    assert scope["region"] == "南宁市"


# ── 时间解析 ──

def test_time_resolve_quarter():
    snapshots = [
        {"snapshot_id": 1, "data_period": "2026-07"},
        {"snapshot_id": 2, "data_period": "2026-08"},
        {"snapshot_id": 3, "data_period": "2026-09"},
    ]
    cleaned, ids, label, ti = resolve_time("Q3 中标总额", snapshots)
    assert label == "2026-Q3"
    assert len(ids) == 3


def test_time_resolve_single_month():
    snapshots = [
        {"snapshot_id": 1, "data_period": "2026-07"},
    ]
    cleaned, ids, label, ti = resolve_time("7月 中标额", snapshots)
    assert label == "2026-07"
    assert len(ids) == 1


def test_time_resolve_yoy():
    snapshots = [
        {"snapshot_id": 1, "data_period": "2026-07"},
        {"snapshot_id": 2, "data_period": "2025-07"},
    ]
    cleaned, ids, label, ti = resolve_time("同比 签约率", snapshots)
    assert ti is not None
    assert ti["function"] == "yoy"


def test_time_resolve_no_time():
    snapshots = [{"snapshot_id": 1, "data_period": "2026-07"}]
    cleaned, ids, label, ti = resolve_time("中标总额", snapshots)
    assert ids is None
    assert label is None


def test_time_resolve_ytd():
    snapshots = [
        {"snapshot_id": 1, "data_period": "2026-01"},
        {"snapshot_id": 2, "data_period": "2026-07"},
    ]
    cleaned, ids, label, ti = resolve_time("今年 中标总额", snapshots)
    assert ti is not None
    assert ti["function"] == "ytd"


# ── 指标加载 ──

def test_metric_loader(db_connector):
    loader = MetricLoader(db_connector)
    assert loader.total_count >= 4
    assert loader.available_count >= 3

    # 精确匹配
    results = loader.search("年度累计中标总额")
    assert len(results) > 0
    assert results[0]["score"] == 1.0

    # 模糊匹配
    results = loader.search("中标额")
    assert len(results) > 0
    assert results[0]["score"] >= 0.45


def test_metric_list_categories(db_connector):
    loader = MetricLoader(db_connector)
    cats = loader.list_categories()
    assert len(cats) > 0


# ── 数据库 ──

def test_db_users(db_connector):
    users = db_connector.get_all_users()
    assert len(users) >= 2
    roles = {u["role"] for u in users}
    assert "admin" in roles
    assert "employee" in roles


def test_db_snapshots(db_connector):
    snapshots = db_connector.get_snapshots()
    assert len(snapshots) == 12


def test_db_user_login(db_connector):
    admin = db_connector.get_user_by_username("admin")
    assert admin is not None
    assert admin["role"] == "admin"


def test_kb_synonym_resolve():
    """知识库加载与解析 (通用模板模式)"""
    from backend.app.semantic.kb_resolver import KBResolver
    # 不传路径 = 空知识库, 确认不报错
    kb = KBResolver()
    assert kb is not None
    assert kb.resolve_synonym("任意术语") is None
    assert kb.resolve_business_logic("任意术语") is None


# ── Fixtures ──

@pytest.fixture
def db_connector():
    from backend.app.config import config
    return DatabaseConnector(config.db_path)
