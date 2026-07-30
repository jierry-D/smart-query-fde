"""多轮对话记忆 — 上下文保持 + 追问意图识别"""

import re
import threading
from collections import OrderedDict
from typing import Optional

from ..core.logging import get_logger

logger = get_logger(__name__)

# 每用户最多保留的对话轮数
MAX_TURNS = 10
# 全局内存存储 (user_id → OrderedDict[turn_id → dict])
_memory: dict[int, OrderedDict] = {}
_lock = threading.Lock()


class ConversationMemory:
    """用户对话记忆管理"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        with _lock:
            if user_id not in _memory:
                _memory[user_id] = OrderedDict()
        self._store = _memory[user_id]

    def add_turn(self, query: str, result: dict):
        """记录一轮对话"""
        turn_id = str(len(self._store) + 1)
        # 提取上下文关键信息
        context = self._extract_context(result)
        with _lock:
            self._store[turn_id] = {
                "query": query,
                "metric_name": result.get("metric_name", ""),
                "sql": result.get("sql", ""),
                "type": result.get("type", ""),
                "entities": result.get("entity_tags", []),
                "context": context,
            }
            if len(self._store) > MAX_TURNS:
                self._store.popitem(last=False)

    def last_turn(self) -> Optional[dict]:
        """获取最近一轮对话"""
        if not self._store:
            return None
        with _lock:
            return next(reversed(self._store.values()))

    def detect_followup(self, query: str) -> Optional[dict]:
        """
        检测是否为追问，并返回增强后的查询上下文.

        追问模式:
        - "那XX呢?" / "XX呢?" → 替换维度, 复用上次查询
        - "和上月比呢?" / "环比呢?" → 添加时间对比
        - "按XX分呢?" → 添加分组维度
        - "Top N呢?" → 添加排序限制
        """
        last = self.last_turn()
        if not last:
            return None

        last_query = last.get("query", "")
        last_metric = last.get("metric_name", "")
        last_entities = last.get("entities", [])

        # 模式1: "那XX呢?" → 替换地区/业务线
        m = re.match(r'那?(.+?)呢[?？]?$', query.strip())
        if m:
            new_dim = m.group(1).strip()
            if new_dim and len(new_dim) <= 10:
                # 构建增强查询: 替换旧查询中的维度词
                enhanced = self._replace_dimension(last_query, new_dim)
                if enhanced:
                    return {
                        "is_followup": True,
                        "followup_type": "dimension_replace",
                        "original_query": query,
                        "enhanced_query": enhanced,
                        "context": last,
                    }

        # 模式2: "和上月比呢?" / "环比呢?" / "同比呢?"
        if any(kw in query for kw in ["上月", "上个月", "环比", "同比", "和.*比"]):
            return {
                "is_followup": True,
                "followup_type": "time_compare",
                "original_query": query,
                "enhanced_query": f"{'同比' if '同比' in query else '环比'} {last_metric or last_query}",
                "context": last,
            }

        # 模式3: "按XX分呢?" → 添加分组
        m = re.match(r'按(.+)[分看].*?[呢?]?$', query.strip())
        if m:
            dim = m.group(1).strip()
            return {
                "is_followup": True,
                "followup_type": "add_grouping",
                "original_query": query,
                "enhanced_query": f"各{dim} {last_metric or last_query}",
                "context": last,
            }

        # 模式4: 极短查询 (≤5字) → 可能为指代追问
        if len(query.strip()) <= 5 and last_metric:
            return {
                "is_followup": True,
                "followup_type": "short_followup",
                "original_query": query,
                "enhanced_query": f"{query} {last_metric}",
                "context": last,
            }

        return None

    def _replace_dimension(self, original_query: str, new_dim: str) -> Optional[str]:
        """替换查询中的维度词 (地区/业务线)"""
        # 常见地区词汇
        cities = ["南宁市", "柳州市", "桂林市", "梧州市", "北海市", "玉林市", "百色市",
                   "河池市", "钦州市", "防城港市", "贵港市", "贺州市", "来宾市", "崇左市"]
        biz_lines = ["数字政务", "信创", "智慧城市", "医疗健康", "教育信息化"]

        for city in cities:
            if city in original_query:
                return original_query.replace(city, new_dim)

        for bl in biz_lines:
            if bl in original_query:
                return original_query.replace(bl, new_dim)

        # 无维度词 → 在查询前添加
        return f"{new_dim} {original_query}"

    @staticmethod
    def _extract_context(result: dict) -> dict:
        """从结果中提取上下文摘要"""
        ctx = {}
        if result.get("metric_name"):
            ctx["metric_name"] = result["metric_name"]
        if result.get("sql"):
            ctx["sql"] = result["sql"][:200]
        if result.get("value") is not None:
            ctx["value"] = result["value"]
        if result.get("rows") and len(result["rows"]) <= 5:
            ctx["rows"] = result["rows"]
        return ctx

    @classmethod
    def clear(cls, user_id: int):
        with _lock:
            _memory.pop(user_id, None)
