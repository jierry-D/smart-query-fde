"""Prompt 模板管理 — Jinja2 模板加载与渲染"""

from pathlib import Path
from ..core.logging import get_logger

logger = get_logger(__name__)

# 内建 Prompt 模板 (文件系统中的 .md 文件优先)
BUILTIN_PROMPTS = {
    "sql_generator": """你是一位 SQL 专家。根据以下信息生成 SQL 查询。

## 数据库方言
SQLite

## 表结构
{table_schema}

## 指标定义
指标名: {metric_name}
计算公式: {formula}
来源表: {table_name}

## 用户查询
{query}

## 约束
- 只生成 SELECT 语句
- 所有表名和字段名必须来自上述表结构
- 数值结果 AS value
- 分组结果 AS label, value
- 只输出 SQL，不要解释""",

    "intent_classifier": """分析以下用户查询的意图。

## 查询
{query}

## 可用意图
- aggregate: 求和、合计、总额
- ranking: 排名、Top-N、最高/最低
- distribution: 分布、占比、分组
- count: 计数、个数
- average: 平均、均值
- trend: 趋势、变化、走势

## 可筛选维度
{dimensions}

返回 JSON: {{"intent": "aggregate", "confidence": 0.9, "explanation": "..."}}""",

    "clarification": """用户查询存在歧义，需要澄清。

## 查询
{query}

## 可能的歧义
{ambiguities}

## 候选选项
{options}

请用友好的中文反问用户，提供选项让用户选择。最多反问 2 轮。""",

    "result_interpreter": """根据查询结果生成自然语言解读。

## 用户查询
{query}

## 指标
{metric_name}: {explanation}

## 查询结果
{result_summary}

## 时间范围
{time_range}

用 1-2 句简洁的中文解读结果，突出关键发现。""",
}


class PromptManager:
    """Prompt 模板管理器"""

    def __init__(self, prompts_dir: str = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else None
        self._templates: dict[str, str] = dict(BUILTIN_PROMPTS)

        # 加载文件系统中的模板 (覆盖内建)
        if self.prompts_dir and self.prompts_dir.exists():
            for fp in self.prompts_dir.glob("*.md"):
                name = fp.stem
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        self._templates[name] = f.read()
                except Exception:
                    pass
            logger.info("已加载 %d 个 Prompt 模板", len(self._templates))

    def render(self, name: str, **kwargs) -> str:
        """渲染 Prompt 模板"""
        template = self._templates.get(name, "")
        if not template:
            logger.warning("Prompt 模板不存在: %s", name)
            return ""

        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning("Prompt 渲染缺少变量: %s", e)
            return template

    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        return (
            "你是智慧问数系统的 AI 助手。"
            "你的任务是帮助用户用自然语言查询企业数据库。"
            "你需要理解用户的查询意图，并生成准确的 SQL。"
            "如果用户查询有歧义，请友好地反问澄清。"
        )
