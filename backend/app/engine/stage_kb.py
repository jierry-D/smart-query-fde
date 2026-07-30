"""Stage 1.2: 知识库增强 — 同义词扩展 + 业务逻辑注入"""

import time
from pathlib import Path

from ..core.logging import get_logger

logger = get_logger(__name__)


_kb_resolver = None

def get_kb_resolver():
    """懒加载全局知识库解析器（模块级单例缓存，避免每次请求 YAML I/O）"""
    global _kb_resolver
    if _kb_resolver is None:
        from ..semantic.kb_resolver import KBResolver
        kb_dir = Path(__file__).parent.parent.parent / "metrics"
        _kb_resolver = KBResolver(
            enterprise_kb_path=str(kb_dir / "enterprise_kb.yaml"),
            dataset_kb_dir=str(kb_dir / "dataset_kb"),
        )
    return _kb_resolver


def enhance_with_kb(ctx) -> None:
    """
    知识库增强:
      1. 同义词扩展: 将NER提取的hint映射到标准指标名
      2. 业务逻辑注入: 检测业务术语 → SQL条件

    结果存入 ctx.kb_synonyms 和 ctx.entities["kb_conditions"]
    """
    t_kb = time.perf_counter()
    try:
        kb = get_kb_resolver()
        hint = ctx.entities.get("metric_hint", ctx.query)

        # 1. 同义词扩展 + 业务逻辑注入 (合并为一次遍历)
        kb_synonyms = []
        for w in hint.replace('的', ' ').split():
            if len(w) < 2:
                continue
            # 同义词
            resolved = kb.resolve_synonym(w)
            if resolved and resolved != w:
                kb_synonyms.append(resolved)
            # 业务逻辑
            logic = kb.resolve_business_logic(w)
            if logic and isinstance(logic, dict):
                cond = logic.get("condition", "")
                if cond:
                    ctx.entities.setdefault("kb_conditions", []).append({
                        "term": w,
                        "condition": cond,
                        "description": logic.get("description", ""),
                    })

        if kb_synonyms:
            ctx.kb_synonyms = kb_synonyms

        elapsed = (time.perf_counter() - t_kb) * 1000
        detail_parts = []
        if kb_synonyms:
            detail_parts.append(f"同义词: {len(kb_synonyms)}")
        if ctx.entities.get("kb_conditions"):
            detail_parts.append(f"业务逻辑: {len(ctx.entities['kb_conditions'])}")
        if detail_parts:
            ctx.add_stage("知识库增强", "done", elapsed, ", ".join(detail_parts))

    except Exception as e:
        logger.debug("KB增强跳过: %s", e)
