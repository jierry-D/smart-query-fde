"""测试数据接入流水线"""

import pytest


class TestMetadataExtractor:
    def test_extract_metadata(self, db_connector):
        from backend.app.onboarding.pipeline import MetadataExtractor
        e = MetadataExtractor(db_connector)
        meta = e.extract("bid_management")
        assert meta["table_name"] == "bid_management"
        assert len(meta["fields"]) > 0
        assert any(f["name"] == "amount" for f in meta["fields"])

    def test_infer_python_type(self):
        from backend.app.onboarding.pipeline import MetadataExtractor
        e = MetadataExtractor(None)
        assert e._infer_python_type("INTEGER") == "integer"
        assert e._infer_python_type("REAL") == "float"
        assert e._infer_python_type("TEXT") == "text"
        assert e._infer_python_type("DATE") == "date"


class TestQualityAssessor:
    def test_assess(self, db_connector):
        from backend.app.onboarding.pipeline import MetadataExtractor, QualityAssessor
        meta = MetadataExtractor(db_connector).extract("bid_management")
        qa = QualityAssessor()
        result = qa.assess(meta)
        assert "score" in result
        assert "grade" in result
        assert result["total_fields"] > 0

    def test_perfect_score_for_chinese(self):
        from backend.app.onboarding.pipeline import QualityAssessor
        qa = QualityAssessor()
        # 全中文字段名应该没有"英文名"问题
        assert qa._has_chinese("金额")
        assert not qa._has_chinese("amount")


class TestTypeInferrer:
    def test_infer_detail_table(self):
        from backend.app.onboarding.pipeline import TypeInferrer
        ti = TypeInferrer()
        meta = {
            "fields": [
                {"name": "name", "python_type": "text"},
                {"name": "amount", "python_type": "float"},
                {"name": "region", "python_type": "text"},
            ]
        }
        result = ti.infer(meta)
        assert result["type"] == "detail"

    def test_infer_key_value_table(self):
        from backend.app.onboarding.pipeline import TypeInferrer
        ti = TypeInferrer()
        meta = {
            "fields": [
                {"name": "指标名", "python_type": "text"},
                {"name": "指标值", "python_type": "float"},
            ]
        }
        result = ti.infer(meta)
        assert result["type"] == "key_value"


class TestConfigGenerator:
    def test_generate_config(self, db_connector):
        from backend.app.onboarding.pipeline import (
            MetadataExtractor, QualityAssessor,
            TypeInferrer, ConfigGenerator,
        )
        meta = MetadataExtractor(db_connector).extract("bid_management")
        quality = QualityAssessor().assess(meta)
        ds_type = TypeInferrer().infer(meta)
        cg = ConfigGenerator()
        config = cg.generate(meta, quality, ds_type)
        assert config["table_name"] == "bid_management"
        assert len(config["fields"]) > 0
        assert len(config["quick_queries"]) > 0


class TestOnboardingPipeline:
    def test_run_discovery(self, db_connector):
        from backend.app.onboarding.pipeline import OnboardingPipeline
        pipe = OnboardingPipeline(db_connector)
        result = pipe.run_discovery()
        assert "tables" in result
        assert any(t["table_name"] == "bid_management" for t in result.get("tables", []))

    def test_run_full_auto_approve(self, db_connector):
        from backend.app.onboarding.pipeline import OnboardingPipeline
        pipe = OnboardingPipeline(db_connector)
        result = pipe.run_full("bid_management", auto_approve=True)
        assert result["table_name"] == "bid_management"
        assert result["quality"]["score"] > 0
        # auto_approve=True + 质量分>=60 应自动注册
        if result["quality"]["score"] >= 60:
            assert result["registration"] is not None
            assert result["registration"]["metrics_created"] > 0

    def test_reviewer_queue(self, db_connector):
        from backend.app.onboarding.pipeline import OnboardingPipeline, OnboardingReviewer
        # 提交一个不自动通过的表
        pipe = OnboardingPipeline(db_connector)
        pipe.run_full("opportunities", auto_approve=False)

        reviewer = OnboardingReviewer(db_connector)
        pending = reviewer.list_pending()
        stats = reviewer.get_stats()
        assert "pending" in stats
