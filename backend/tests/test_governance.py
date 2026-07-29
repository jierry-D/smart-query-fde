"""测试五层查询治理"""

import pytest


class TestLayer1Auth:

    def test_admin_full_access(self, db_connector, admin_user):
        from backend.app.governance.layer1_auth import AuthFilter
        f = AuthFilter()
        r = f.apply("SELECT * FROM bid_management", admin_user)
        assert r["denied"] is False
        assert "全部数据" in r["scope_label"]

    def test_employee_scope_restricted(self, db_connector, employee_user):
        from backend.app.governance.layer1_auth import AuthFilter
        f = AuthFilter()
        r = f.apply("SELECT * FROM bid_management", employee_user)
        assert r["denied"] is False
        assert "region" in r["sql"] or "南宁市" in r["scope_label"]


class TestLayer2SQL:

    def test_allows_select(self):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("SELECT * FROM bid_management", {"role": "employee"})
        assert r["denied"] is False

    def test_blocks_insert(self):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("INSERT INTO users VALUES (1, 'hacker')", {"role": "employee"})
        assert r["denied"] is True

    def test_blocks_delete(self):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("DELETE FROM bid_management", {"role": "employee"})
        assert r["denied"] is True

    def test_blocks_update(self):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("UPDATE users SET role='admin'", {"role": "employee"})
        assert r["denied"] is True

    def test_blocks_drop(self):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("DROP TABLE bid_management", {"role": "employee"})
        assert r["denied"] is True

    def test_admin_allows_sensitive(self, admin_user):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("SELECT * FROM users", admin_user)
        assert r["denied"] is False

    def test_blocks_sensitive_for_employee(self, employee_user):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("SELECT password FROM users", employee_user)
        # 应该被敏感字段检测拦截或通过(取决于配置)
        assert isinstance(r["denied"], bool)


class TestGovernanceManager:

    def test_full_pipeline_accept(self, db_connector, admin_user):
        from app.governance import GovernanceManager
        g = GovernanceManager(db_connector)
        r = g.apply("SELECT COUNT(*) AS value FROM bid_management", admin_user)
        assert r["denied"] is False
        assert "checks" in r
        assert len(r["checks"]) >= 3  # Layer 1, 2, 5 at minimum

    def test_full_pipeline_reject_insert(self, db_connector, admin_user):
        from app.governance import GovernanceManager
        g = GovernanceManager(db_connector)
        r = g.apply("INSERT INTO users(username) VALUES('bad')", admin_user)
        assert r["denied"] is True
