"""三级知识库解析器 — 数据集 > 业务域 > 企业级"""

import yaml
from pathlib import Path
from ..core.logging import get_logger

logger = get_logger(__name__)


class KBResolver:
    """
    知识库解析器 — 优先级: 数据集 > 业务域 > 企业级。

    用于将用户自然语言术语映射到数据库字段和业务逻辑。
    """

    def __init__(self, enterprise_kb_path: str = None, dataset_kb_dir: str = None):
        self.enterprise_kb: dict = {}
        self.dataset_kbs: dict[str, dict] = {}

        if enterprise_kb_path and Path(enterprise_kb_path).exists():
            with open(enterprise_kb_path, "r", encoding="utf-8") as f:
                self.enterprise_kb = yaml.safe_load(f) or {}
            logger.info("企业知识库已加载: %s", enterprise_kb_path)

        if dataset_kb_dir and Path(dataset_kb_dir).exists():
            for fp in Path(dataset_kb_dir).glob("*.yaml"):
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    name = fp.stem
                    self.dataset_kbs[name] = data
                except Exception:
                    pass
            logger.info("数据集知识库已加载: %d 个", len(self.dataset_kbs))

    def resolve_synonym(self, term: str, dataset: str = None) -> str | None:
        """将术语映射到标准名称 (同义词解析)"""
        # 1. 数据集级
        if dataset and dataset in self.dataset_kbs:
            synonyms = self.dataset_kbs[dataset].get("synonyms", {})
            if term in synonyms:
                return synonyms[term]

        # 2. 企业级
        synonyms = self.enterprise_kb.get("synonyms", {})
        if term in synonyms:
            return synonyms[term]

        return None

    def resolve_business_logic(self, term: str, dataset: str = None) -> dict | None:
        """解析业务逻辑 (如 "大额订单" → amount > 10000)"""
        # 1. 数据集级
        if dataset and dataset in self.dataset_kbs:
            logic = self.dataset_kbs[dataset].get("business_logic", {})
            if term in logic:
                return logic[term]

        # 2. 企业级
        logic = self.enterprise_kb.get("business_logic", {})
        if term in logic:
            return logic[term]

        return None

    def resolve_field_mapping(self, field_name: str, dataset: str = None) -> str | None:
        """字段名映射 (如 "成交额" → "contract_amount")"""
        if dataset and dataset in self.dataset_kbs:
            mapping = self.dataset_kbs[dataset].get("field_mapping", {})
            if field_name in mapping:
                return mapping[field_name]

        mapping = self.enterprise_kb.get("field_mapping", {})
        return mapping.get(field_name)
