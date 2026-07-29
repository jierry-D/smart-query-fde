#!/usr/bin/env python3
"""端到端集成测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.app.main import app
    return TestClient(app)


@pytest.fixture
def admin_token(client):
    resp = client.post("/api/auth/login", json={
        "username": "admin", "password": "admin123"
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def emp_token(client):
    resp = client.post("/api/auth/login", json={
        "username": "employee", "password": "emp123"
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ── Auth Tests ──

def test_login_success(client):
    resp = client.post("/api/auth/login", json={
        "username": "admin", "password": "admin123"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["role"] == "admin"


def test_login_fail(client):
    resp = client.post("/api/auth/login", json={
        "username": "admin", "password": "wrong"
    })
    assert resp.status_code == 401


def test_me(client, admin_token):
    resp = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {admin_token}"
    })
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_me_no_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


# ── Query Tests ──

def test_query_number(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "年度累计中标总额"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "number"
    assert data["value"] is not None
    assert data["data_scope"] == "全部数据"


def test_query_table(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "各地市中标额"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "table"
    assert data["row_count"] > 0


def test_query_with_time(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "Q3 年度累计中标总额"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "number"


def test_query_with_filter(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "南宁市 年度累计中标总额"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "number"
    assert data.get("entity_tags")


def test_query_top_n(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "Top 3 各地市中标额"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("row_count", 0) <= 3


def test_query_not_found(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "不存在的指标XYZ"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "error"


# ── RBAC Tests ──

def test_employee_query_limited(client, emp_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {emp_token}"
    }, json={"q": "各地市中标额"})
    assert resp.status_code == 200
    data = resp.json()
    assert "数字政务事业部" in data.get("data_scope", "")
    assert "南宁市" in data.get("data_scope", "")


def test_employee_cannot_admin(client, emp_token):
    resp = client.get("/api/admin/users", headers={
        "Authorization": f"Bearer {emp_token}"
    })
    assert resp.status_code == 403


# ── Command Tests ──

def test_cmd_list(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "/list"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "metric_list"


def test_cmd_db(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "/db"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "db_status"


def test_cmd_help(client, admin_token):
    resp = client.post("/api/chat", headers={
        "Authorization": f"Bearer {admin_token}"
    }, json={"q": "/help"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "help"


# ── Admin Tests ──

def test_admin_users(client, admin_token):
    resp = client.get("/api/admin/users", headers={
        "Authorization": f"Bearer {admin_token}"
    })
    assert resp.status_code == 200
    assert resp.json()["total"] == 6


def test_admin_stats(client, admin_token):
    resp = client.get("/api/admin/stats", headers={
        "Authorization": f"Bearer {admin_token}"
    })
    assert resp.status_code == 200
    assert resp.json()["users"] == 6


# ── Status Test ──

def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "2.0.0"
    assert data["users"] == 6
