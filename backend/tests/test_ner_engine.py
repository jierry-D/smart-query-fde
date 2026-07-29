"""测试 NER 引擎 — 实体提取、意图识别 (迁移自 MVP)"""

import pytest
from backend.app.engine.ner_engine import NEREngine


@pytest.fixture
def ner(db_connector):
    engine = NEREngine(db_connector)
    engine._ensure_init()
    return engine


class TestNEREngine:

    def test_extract_region(self, ner):
        result = ner.extract("南宁市数字政务中标总额")
        regions = [f for f in result["filters"] if f["field"] == "region"]
        assert len(regions) >= 1
        assert any(f["value"] == "南宁市" for f in regions)

    def test_extract_business_line(self, ner):
        result = ner.extract("数字政务板块的中标情况")
        bls = [f for f in result["filters"] if f["field"] == "business_line"]
        assert len(bls) >= 1
        assert any(f["value"] == "数字政务" for f in bls)

    def test_extract_region_short_name(self, ner):
        result = ner.extract("南宁中标总额")
        regions = [f for f in result["filters"] if f["field"] == "region"]
        assert any(f["value"] == "南宁市" for f in regions)

    def test_intent_aggregate_default(self, ner):
        result = ner.extract("年度累计中标总额")
        assert result["intent"] == "aggregate"

    def test_intent_ranking(self, ner):
        result = ner.extract("各地市中标额排名")
        assert result["intent"] == "ranking"
        assert result["order"] == "desc"

    def test_intent_distribution(self, ner):
        result = ner.extract("按业务线分布合同")
        assert result["intent"] == "distribution"
        assert result["group_by"] == "business_line"

    def test_intent_count(self, ner):
        result = ner.extract("商机数量")
        assert result["intent"] == "count"

    def test_intent_average(self, ner):
        result = ner.extract("平均中标金额")
        assert result["intent"] == "average"

    def test_top_n(self, ner):
        result = ner.extract("Top 5 中标金额")
        assert result["limit"] == 5
        assert result["intent"] == "ranking"

    def test_chinese_top_n(self, ner):
        result = ner.extract("前10 最大合同")
        assert result["limit"] == 10

    def test_group_by_region(self, ner):
        result = ner.extract("各地区中标分布")
        assert result["group_by"] == "region"
        assert result["intent"] == "distribution"

    def test_metric_hint_cleaning(self, ner):
        result = ner.extract("今年南宁市数字政务板块的中标情况怎么样")
        hint = result["metric_hint"]
        assert "南宁市" not in hint
        assert "数字政务" not in hint
        assert "中标" in hint or len(hint) > 0

    def test_completeness(self, ner):
        result = ner.extract("南宁市数字政务中标总额")
        assert result["completeness"]["has_dimension"] is True
        assert result["completeness"]["has_metric"] is True

    def test_no_filters(self, ner):
        result = ner.extract("年度累计中标总额")
        assert len(result["filters"]) == 0

    def test_multiple_filters(self, ner):
        result = ner.extract("南宁市和柳州市的中标情况")
        regions = [f for f in result["filters"] if f["field"] == "region"]
        assert len(regions) >= 1

    def test_empty_query(self, ner):
        result = ner.extract("")
        assert result["intent"] == "aggregate"

    def test_noise_only(self, ner):
        result = ner.extract("的了吗呢吧啊")
        assert result is not None
        assert isinstance(result["filters"], list)


class TestSQLFilter:

    def test_inject_single_filter(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT SUM(amount) AS value FROM bid_management WHERE is_won = 1"
        entities = {"filters": [{"field": "region", "value": "南宁市", "operator": "="}]}
        result = apply_entities(sql, entities)
        assert "region" in result
        assert "南宁市" in result

    def test_inject_filter_no_where(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT SUM(amount) AS value FROM bid_management"
        entities = {"filters": [{"field": "region", "value": "南宁市", "operator": "="}]}
        result = apply_entities(sql, entities)
        assert "WHERE" in result
        assert "南宁市" in result

    def test_apply_limit(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT region AS label, SUM(amount) AS value FROM bid_management GROUP BY region"
        entities = {"limit": 5, "order": "desc"}
        result = apply_entities(sql, entities)
        assert "LIMIT 5" in result
        assert "ORDER BY value DESC" in result

    def test_inject_group_by(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT SUM(amount) AS value FROM bid_management"
        entities = {"group_by": "region", "intent": "distribution"}
        result = apply_entities(sql, entities)
        assert "region" in result
        assert "GROUP BY" in result

    def test_inject_multiple_filters(self):
        from backend.app.engine.sql_filter import apply_entities
        sql = "SELECT SUM(amount) AS value FROM bid_management WHERE is_won = 1"
        entities = {"filters": [
            {"field": "region", "value": "南宁市", "operator": "="},
            {"field": "business_line", "value": "数字政务", "operator": "="},
        ]}
        result = apply_entities(sql, entities)
        assert "region" in result
        assert "business_line" in result
