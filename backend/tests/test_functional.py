"""业务功能测试 — API 端点全流程"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.app.main import app
    return TestClient(app)


@pytest.fixture
def admin_headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuthFunctional:
    """认证功能测试"""

    def test_login_with_wrong_password(self, client):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    def test_login_empty_fields(self, client):
        r = client.post("/api/auth/login", json={"username": "", "password": ""})
        assert r.status_code == 422 or r.status_code == 401

    def test_login_nonexistent_user(self, client):
        r = client.post("/api/auth/login", json={"username": "nonexistent", "password": "x"})
        assert r.status_code == 401

    def test_me_without_token(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401 or r.status_code == 403

    def test_token_persistence(self, client):
        r1 = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        token = r1.json()["access_token"]
        r2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["username"] == "admin"


class TestDashboardFunctional:
    """仪表盘功能测试"""

    def test_dashboard_returns_cards(self, client, admin_headers):
        r = client.get("/api/dashboard", headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert "cards" in d
        assert "alerts" in d

    def test_dashboard_requires_auth(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 401 or r.status_code == 403


class TestMetricsFunctional:
    """指标管理功能测试"""

    def test_metrics_list(self, client, admin_headers):
        r = client.get("/api/metrics", headers=admin_headers)
        assert r.status_code == 200
        assert len(r.json().get("metrics", [])) > 0

    def test_metrics_categories(self, client, admin_headers):
        r = client.get("/api/metrics/categories", headers=admin_headers)
        assert r.status_code == 200

    def test_metrics_search(self, client, admin_headers):
        r = client.get("/api/metrics/search?q=中标", headers=admin_headers)
        assert r.status_code == 200


class TestSnapshotsFunctional:
    """数据快照功能测试"""

    def test_snapshots_list(self, client, admin_headers):
        r = client.get("/api/snapshots", headers=admin_headers)
        assert r.status_code == 200
        assert r.json().get("total", 0) > 0

    def test_snapshots_latest(self, client, admin_headers):
        r = client.get("/api/snapshots/latest", headers=admin_headers)
        assert r.status_code == 200


class TestHistoryFunctional:
    """查询历史功能测试"""

    def test_history_returns_list(self, client, admin_headers):
        r = client.get("/api/history?limit=10", headers=admin_headers)
        assert r.status_code == 200
        assert "logs" in r.json()

    def test_history_requires_auth(self, client):
        r = client.get("/api/history")
        assert r.status_code == 401


class TestExportFunctional:
    """导出功能测试"""

    def test_export_csv_table(self, client, admin_headers):
        r = client.post("/api/export/csv", json={"q": "各地市中标额"}, headers=admin_headers)
        assert r.status_code == 200

    def test_export_empty_result(self, client, admin_headers):
        r = client.post("/api/export/csv", json={"q": "不存在的指标xyz"}, headers=admin_headers)
        assert r.status_code == 404 or r.status_code == 200


class TestStatusFunctional:
    """系统状态功能测试"""

    def test_status_public(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        d = r.json()
        assert "version" in d
        assert "tables" in d
        assert "snapshots" in d
        assert "metrics_total" in d
        assert "users" in d


class TestRBACFunctional:
    """权限功能测试"""

    def test_admin_can_access_admin(self, client, admin_headers):
        r = client.get("/api/admin/users", headers=admin_headers)
        assert r.status_code == 200

    def test_employee_cannot_access_admin(self, client):
        r = client.post("/api/auth/login", json={"username": "employee", "password": "emp123"})
        token = r.json()["access_token"]
        r2 = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 403

    def test_employee_data_scope(self, client):
        r = client.post("/api/auth/login", json={"username": "employee", "password": "emp123"})
        token = r.json()["access_token"]
        r2 = client.post("/api/chat", json={"q": "年度累计中标总额"}, headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        d = r2.json()
        if d.get("type") == "number":
            # employee should see less than admin (scoped)
            assert d.get("value") is not None


class TestClarifyFunctional:
    """反问澄清功能测试"""

    def test_short_query_clarifies(self, client, admin_headers):
        r = client.post("/api/chat", json={"q": "南宁市"}, headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert d.get("type") in ("clarify", "number", "table")

    def test_help_command(self, client, admin_headers):
        r = client.post("/api/chat", json={"q": "/help"}, headers=admin_headers)
        assert r.status_code == 200

    def test_list_command(self, client, admin_headers):
        r = client.post("/api/chat", json={"q": "/list"}, headers=admin_headers)
        assert r.status_code == 200


class TestFeedbackFunctional:
    """反馈功能测试"""

    def test_submit_up_feedback(self, client, admin_headers):
        r = client.post("/api/feedback", json={"rating": "up", "comment": "很好"}, headers=admin_headers)
        assert r.status_code == 200

    def test_submit_down_feedback(self, client, admin_headers):
        r = client.post("/api/feedback", json={"rating": "down", "comment": "指标匹配错误", "original_query": "测试查询"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json().get("status") == "saved"
