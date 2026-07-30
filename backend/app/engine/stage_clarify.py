"""Stage 1.5: 反问澄清检测 — 信息不完整时反问用户"""

import time

from ..core.logging import get_logger

logger = get_logger(__name__)

# 时间关键词 (在 Stage 2 时间解析之前检测)
TIME_KEYWORDS = [
    "Q1", "Q2", "Q3", "Q4", "月", "季度", "年", "本周", "本月", "本期",
    "今年", "去年", "同比", "环比", "上半年", "下半年", "上个", "上个月",
    "上季度", "本季度", "近", "最近",
]


def check_clarification(ctx) -> dict | None:
    """
    检测是否需要反问澄清。需要则返回 clarify 响应，否则返回 None。

    场景:
      1. 查询 ≤3 字符 → 引导使用命令
      2. 缺时间 + 无维度 + <4字符 → 反问时间
      3. 有维度 + 缺时间 → 反问时间
      4. KB 同义词命中 → 跳过澄清
      5. 分布/排名意图 → 跳过澄清
    """
    t1 = time.perf_counter()
    entities = ctx.entities
    completeness = entities.get("completeness", {})
    kb_synonyms = getattr(ctx, 'kb_synonyms', [])

    # 构建 entity_tags
    tags = _build_tags(entities)

    # 检测时间词
    has_time_keyword = any(kw in ctx.query for kw in TIME_KEYWORDS)
    if has_time_keyword:
        completeness["has_time"] = True
        completeness["score"] = min(1.0, completeness.get("score", 0) + 0.3)

    query_len = len(ctx.cleaned_query.strip())
    has_time = completeness.get("has_time", False)
    has_dimension = completeness.get("has_dimension", False)
    intent = entities.get("intent", "aggregate")
    has_metric = completeness.get("has_metric", False)

    # 场景: KB 同义词成功解析 → 跳过
    if kb_synonyms:
        ctx.add_stage("反问澄清", "done", 0,
                      f"KB同义词={len(kb_synonyms)}, 默认最新数据")
        return None

    # 场景: 分布/排名/趋势意图 → 跳过
    if intent in ("distribution", "ranking", "trend"):
        ctx.add_stage("反问澄清", "done", 0,
                      f"意图={intent}, 默认最新数据")
        return None

    # 场景1: 查询太短或无实质内容
    if (query_len < 4 and not has_metric) or query_len <= 2:
        ctx.add_stage("反问澄清", "done", (time.perf_counter() - t1) * 1000,
                      "查询太短, 引导使用命令" if query_len <= 2 else "无实质指标内容")
        return {
            "type": "clarify",
            "question": "请问您想查什么数据？",
            "options": [
                {"label": "查看所有指标", "action": "command", "value": "/list"},
                {"label": "查看数据状态", "action": "command", "value": "/db"},
                {"label": "查看帮助", "action": "command", "value": "/help"},
            ],
            "hint": "您也可以直接输入自然语言查询，如'Q3 年度累计中标总额'",
            "completeness": completeness,
            "entity_tags": tags,
        }

    # 场景2: 缺时间 + 无维度 + 短查询
    if not has_time and not has_dimension and query_len < 4:
        ctx.add_stage("反问澄清", "done", (time.perf_counter() - t1) * 1000,
                      "缺少时间和筛选条件")
        return {
            "type": "clarify",
            "question": "请补充查询条件，以便精准查询：",
            "options": [
                {"label": "📅 本月", "action": "refine", "value": f"本月 {ctx.query}"},
                {"label": "📅 本季度", "action": "refine", "value": f"本季度 {ctx.query}"},
                {"label": "📅 今年", "action": "refine", "value": f"今年 {ctx.query}"},
                {"label": "⏭️ 跳过, 用最新数据", "action": "refine", "value": ctx.query},
            ],
            "hint": "添加时间范围可以获得更精确的结果",
            "completeness": completeness,
            "entity_tags": tags,
        }

    # 场景3: 有维度 + 缺时间
    if not has_time and has_dimension:
        ctx.add_stage("反问澄清", "done", (time.perf_counter() - t1) * 1000,
                      "已识别筛选条件但缺少时间范围")
        return {
            "type": "clarify",
            "question": "已识别您的筛选条件，请补充时间范围：",
            "options": [
                {"label": "📅 本月", "action": "refine", "value": f"本月 {ctx.query}"},
                {"label": "📅 本季度", "action": "refine", "value": f"本季度 {ctx.query}"},
                {"label": "📅 今年 (YTD)", "action": "refine", "value": f"今年 {ctx.query}"},
                {"label": "⏭️ 跳过, 用最新数据", "action": "refine", "value": ctx.query},
            ],
            "hint": "添加时间后可以获得对应期间的数据",
            "completeness": completeness,
            "entity_tags": tags,
        }

    # 场景4: 无时间但查询较长 → 默认最新, 不反问
    if not has_time and completeness.get("score", 0) >= 0.4:
        ctx.add_stage("反问澄清", "done", (time.perf_counter() - t1) * 1000,
                      "未指定时间, 默认使用最新数据")
        return None

    return None  # 信息完整, 继续


def _build_tags(entities: dict) -> list[dict]:
    """从 NER entities 构建前端展示标签"""
    tags = []
    for f in entities.get("filters", []):
        tags.append({"type": "filter", "label": f"{f['field']}={f['value']}"})
    if entities.get("group_by"):
        tags.append({"type": "group", "label": f"按{entities['group_by']}"})
    return tags
