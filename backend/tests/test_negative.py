"""基础负向测试 — 异常输入/边界/注入攻击"""

import pytest


class TestSQLFilterNegative:
    """sql_filter.py — 负向测试"""

    def test_empty_sql(self):
        from backend.app.engine.sql_filter import apply_entities
        result = apply_entities("", {"filters": [{"field": "x", "value": "y", "operator": "="}]})
        assert isinstance(result, str)

    def test_empty_entities(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT 1"
        result = apply_entities(sql, {})
        assert result == sql

    def test_sql_injection_filter_value(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT * FROM t WHERE 1=1"
        entities = {"filters": [{"field": "x", "value": "'; DROP TABLE users--", "operator": "="}]}
        result = apply_entities(sql, entities)
        assert isinstance(result, str)

    def test_sql_injection_field_name(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT * FROM t"
        entities = {"filters": [{"field": "1;DROP TABLE users--", "value": "x", "operator": "="}]}
        result = apply_entities(sql, entities)
        assert isinstance(result, str)

    def test_none_filter_list(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT 1"
        result = apply_entities(sql, {"filters": None})
        assert isinstance(result, str)

    def test_negative_limit(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT * FROM t"
        entities = {"limit": -5}
        result = apply_entities(sql, entities)
        assert isinstance(result, str)

    def test_large_limit(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT * FROM t"
        entities = {"limit": 99999}
        result = apply_entities(sql, entities)
        assert isinstance(result, str)


class TestNERNegative:
    """NER 引擎 — 负向测试"""

    def test_sql_injection_query(self, db_connector):
        from backend.app.engine.ner_engine import NEREngine
        ner = NEREngine(db_connector)
        result = ner.extract("'; DROP TABLE users--")
        assert result is not None
        assert isinstance(result["filters"], list)

    def test_xss_query(self, db_connector):
        from backend.app.engine.ner_engine import NEREngine
        ner = NEREngine(db_connector)
        result = ner.extract("<script>alert(1)</script>")
        assert result is not None
        assert result["intent"] in ("aggregate", "count", "average", "ranking", "distribution", "trend")

    def test_unicode_query(self, db_connector):
        from backend.app.engine.ner_engine import NEREngine
        ner = NEREngine(db_connector)
        result = ner.extract("中标总额 🎉💰 测试")
        assert result is not None

    def test_very_long_query(self, db_connector):
        from backend.app.engine.ner_engine import NEREngine
        ner = NEREngine(db_connector)
        long_q = "南宁市 " * 1000 + "中标总额"
        result = ner.extract(long_q)
        assert result is not None

    def test_whitespace_only(self, db_connector):
        from backend.app.engine.ner_engine import NEREngine
        ner = NEREngine(db_connector)
        result = ner.extract("   \t\n  ")
        assert result is not None


class TestTimeResolverNegative:
    """时间解析器 — 负向测试"""

    def test_empty_query(self, db_connector):
        from backend.app.engine.time_resolver import resolve_time
        snapshots = db_connector.get_snapshots()
        result = resolve_time("", snapshots)
        assert result is not None

    def test_invalid_month(self, db_connector):
        from backend.app.engine.time_resolver import resolve_time
        snapshots = db_connector.get_snapshots()
        result = resolve_time("13月 中标总额", snapshots)
        assert result is not None

    def test_no_snapshots(self):
        from backend.app.engine.time_resolver import resolve_time
        result = resolve_time("本月 中标总额", [])
        assert result is not None

    def test_mixed_time_formats(self, db_connector):
        from backend.app.engine.time_resolver import resolve_time
        snapshots = db_connector.get_snapshots()
        result = resolve_time("Q1和Q3 中标总额", snapshots)
        assert result is not None


class TestGovernanceNegative:
    """治理层 — 负向测试"""

    def test_empty_sql(self, admin_user):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("", {"role": "employee"})
        assert isinstance(r["denied"], bool)

    def test_none_user_handled(self):
        from backend.app.governance.layer1_auth import AuthFilter
        f = AuthFilter()
        # 传入空dict → 应使用默认employee角色
        r = f.apply("SELECT 1", {})
        assert "denied" in r
        assert r["denied"] is False  # 空用户不应被拒绝(使用默认角色)

    def test_sql_with_comments(self):
        from backend.app.governance.layer2_sql import SQLSecurityChecker
        c = SQLSecurityChecker()
        r = c.apply("SELECT * FROM users -- comment", {"role": "employee"})
        assert isinstance(r["denied"], bool)

    def test_circuit_breaker_state(self):
        from backend.app.governance.layer4_exec import ExecutionGuard
        g = ExecutionGuard()
        # 触发熔断
        for _ in range(10):
            g.record_failure()
        r = g.apply("SELECT 1")
        assert r["denied"] is True
        # 恢复
        g.record_success()
