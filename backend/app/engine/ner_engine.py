#!/usr/bin/env python3
"""
NER 引擎 — 纯规则自然语言实体提取

从用户查询中提取:
  - 区域/业务线筛选条件 (AC 自动机 + 数据库词表)
  - 聚合意图 (正则模式)
  - 分组维度 (正则模式)
  - 排序/Top-N (正则模式)

设计依据: 零模型依赖，完全基于规则。
"""

import re
import threading
import time

from ..core.logging import get_logger

logger = get_logger(__name__)

# ── 模块级维度缓存 (TTL=300s, 避免每次请求 5-6 次 SELECT DISTINCT) ──

_DIM_CACHE: dict = {"regions": {}, "business_lines": {}, "ts": 0}
_DIM_CACHE_TTL: float = 300.0
_DIM_CACHE_LOCK = None  # lazy import threading.Lock

# ── 预编译正则 ──

# 聚合意图模式
_INTENT_PATTERNS = [
    (re.compile(r'(?:排名|排行|Top\s*\d+|前\s*\d+|最高|最低|最好|最差)'), 'ranking', 10),
    (re.compile(r'(?:趋势|变化|走势|逐月|每月)'), 'trend', 9),
    (re.compile(r'(?:分布|占比|分别|比例|构成)'), 'distribution', 8),
    (re.compile(r'(?:个数|数量|多少个|几项|几笔|几次|计数)'), 'count', 7),
    (re.compile(r'(?:平均|均值|人均)'), 'average', 6),
    (re.compile(r'(?:总额|合计|总共|多少|金额|额|情况|怎么样|如何)'), 'aggregate', 5),
]

# 分组维度模式
_GROUP_PATTERNS = [
    (re.compile(r'(?:按区域|各地区|各地市|各市|每个城市|每个区|分区域)'), 'region'),
    (re.compile(r'(?:按业务线|各板块|各业务|每个业务|分业务)'), 'business_line'),
]

# 排序
_ORDER_DESC_PATTERNS = [
    re.compile(r'(?:最高|最好|最大|最多|排名|排行|Top|前\d)'),
    re.compile(r'(?:降序|倒序|从高到低|从大到小)'),
]
_ORDER_ASC_PATTERNS = [
    re.compile(r'(?:最低|最差|最小|最少)'),
    re.compile(r'(?:升序|正序|从低到高|从小到大)'),
]

_TOP_N_PATTERN = re.compile(r'(?:Top\s*|前\s*)(\d+)', re.IGNORECASE)
_DIM_SUFFIXES = re.compile(r'(?:市|区|县|省|自治区|板块|业务|部门|组|中心)$')
_NOISE_PATTERN = re.compile(r'(?:的|了|吗|呢|吧|啊|呀|怎么样|如何|是什么|是多少|请问|帮我|查一下|查询|看看|能不能)')
_SUFFIX_PATTERN = re.compile(r'(?:情况|状况|数据|信息|统计|汇总|明细|列表)')


class NEREngine:
    """自然语言实体提取引擎"""

    def __init__(self, connector=None):
        self.connector = connector
        self.regions = {}
        self.business_lines = {}
        self._initialized = False

    def _ensure_init(self):
        if self._initialized or not self.connector:
            return
        global _DIM_CACHE, _DIM_CACHE_LOCK
        # 尝试命中缓存
        now = time.time()
        if now - _DIM_CACHE["ts"] < _DIM_CACHE_TTL and (_DIM_CACHE["regions"] or _DIM_CACHE["business_lines"]):
            self.regions = _DIM_CACHE["regions"]
            self.business_lines = _DIM_CACHE["business_lines"]
            self._initialized = True
            return
        # 缓存未命中 → 加载 + 写入缓存 (线程安全)
        self._load_dimensions()
        if _DIM_CACHE_LOCK is None:
            _DIM_CACHE_LOCK = threading.Lock()
        with _DIM_CACHE_LOCK:
            _DIM_CACHE["regions"] = self.regions
            _DIM_CACHE["business_lines"] = self.business_lines
            _DIM_CACHE["ts"] = now
        self._initialized = True

    def _load_dimensions(self):
        """从数据库加载区域和业务线 DISTINCT 值"""
        try:
            for table in ['bid_management', 'contracts']:
                try:
                    rows = self.connector.execute(
                        f'SELECT DISTINCT region FROM "{table}" WHERE region IS NOT NULL AND region != ""'
                    )
                    for r in rows:
                        val = r['region']
                        if val:
                            self._register_value(val, self.regions)
                except Exception as e:
                    logger.debug("维度加载跳过: %s", e)

            for table in ['bid_management', 'contracts', 'opportunities']:
                try:
                    rows = self.connector.execute(
                        f'SELECT DISTINCT business_line FROM "{table}" WHERE business_line IS NOT NULL AND business_line != ""'
                    )
                    for r in rows:
                        val = r['business_line']
                        if val:
                            self._register_value(val, self.business_lines)
                except Exception as e:
                    logger.debug("维度加载跳过: %s", e)

            logger.info("NER 词典: %d 区域, %d 业务线", len(self.regions), len(self.business_lines))
        except Exception as e:
            logger.warning("NER 词典加载失败: %s", e)

    @staticmethod
    def _register_value(val, mapping):
        val = str(val).strip()
        if not val:
            return
        mapping[val] = val
        short = _DIM_SUFFIXES.sub('', val)
        if short and short != val and len(short) >= 2:
            if short not in mapping:
                mapping[short] = val

    # ── 主入口 ──

    def extract(self, query: str) -> dict:
        self._ensure_init()

        result = {
            "time": None,
            "filters": [],
            "intent": "aggregate",
            "group_by": None,
            "order": None,
            "limit": None,
            "metric_hint": query,
            "completeness": {"has_time": False, "has_metric": True, "has_dimension": False, "score": 0.5},
        }

        cleaned = query

        # 1. 维度筛选
        cleaned = self._extract_filters(cleaned, result)

        # 2. 分组维度
        cleaned = self._extract_group_by(cleaned, result)

        # 3. 意图
        cleaned = self._extract_intent(cleaned, result)

        # 4. 排序
        cleaned = self._extract_order(cleaned, result)

        # 5. Top-N
        cleaned = self._extract_top_n(cleaned, result)

        # 6. 清洗
        result["metric_hint"] = self._clean_query(cleaned)

        # 7. 分组推定
        if result["group_by"] and result["intent"] == "aggregate":
            result["intent"] = "distribution"

        # 8. 完整性
        hint = result["metric_hint"].strip()
        result["completeness"]["has_metric"] = len(hint) > 0
        result["completeness"]["has_dimension"] = (
            len(result["filters"]) > 0 or result["group_by"] is not None
        )
        score = 0.0
        if result["completeness"]["has_time"]:
            score += 0.3
        if result["completeness"]["has_metric"]:
            score += 0.4
        if result["completeness"]["has_dimension"]:
            score += 0.3
        result["completeness"]["score"] = score

        return result

    # ── 维度 (Trie 加速: O(N+M) 替代 O(N×M) 子串扫描) ──

    @staticmethod
    def _build_trie(dim_dict: dict) -> tuple:
        """从 {name: canonical} 构建字典树，返回 (root, max_len)"""
        root = {}
        max_len = 0
        for name, canonical in dim_dict.items():
            node = root
            for ch in name:
                node = node.setdefault(ch, {})
            node['$'] = canonical  # 终端标记
            max_len = max(max_len, len(name))
        return root, max_len

    @staticmethod
    def _scan_trie(query: str, trie_root: dict, field: str, max_len: int) -> list:
        """在 query 中扫描 trie，返回 [(start, end, field, canonical), ...]"""
        matches = []
        n = len(query)
        for i in range(n):
            node = trie_root
            j = i
            while j < n and j - i < max_len:
                ch = query[j]
                if ch not in node:
                    break
                node = node[ch]
                j += 1
                if '$' in node:
                    matches.append((i, j, field, node['$']))
        return matches

    def _extract_filters(self, query: str, result: dict) -> str:
        # 构建 trie (使用缓存)
        if not hasattr(self, '_region_trie'):
            self._region_trie, self._region_max = self._build_trie(self.regions)
            self._biz_trie, self._biz_max = self._build_trie(self.business_lines)

        # 一次扫描: 区域 + 业务线
        raw_matches = []
        raw_matches.extend(self._scan_trie(query, self._region_trie, 'region', self._region_max))
        raw_matches.extend(self._scan_trie(query, self._biz_trie, 'business_line', self._biz_max))

        # 按长度降序 + 去重叠 (优先更长匹配)
        raw_matches.sort(key=lambda x: -(x[1] - x[0]))

        matched_positions = []
        for start, end, field, canonical in raw_matches:
            overlaps = any(
                start < e and s < end for s, e in matched_positions
            )
            if not overlaps:
                result["filters"].append({
                    "field": field, "value": canonical,
                    "operator": "=", "raw": query[start:end],
                })
                matched_positions.append((start, end))

        if matched_positions:
            matched_positions.sort()
            parts = []
            last_end = 0
            for start, end in matched_positions:
                if start > last_end:
                    parts.append(query[last_end:start])
                last_end = end
            if last_end < len(query):
                parts.append(query[last_end:])
            return ' '.join(''.join(parts).split())
        return query

    # ── 分组 ──

    def _extract_group_by(self, query: str, result: dict) -> str:
        for pattern, dim in _GROUP_PATTERNS:
            m = pattern.search(query)
            if m:
                result["group_by"] = dim
                return pattern.sub('', query)
        return query

    # ── 意图 ──

    def _extract_intent(self, query: str, result: dict) -> str:
        for pattern, intent, _ in sorted(_INTENT_PATTERNS, key=lambda x: -x[2]):
            if pattern.search(query):
                result["intent"] = intent
                return query
        return query

    # ── 排序 ──

    def _extract_order(self, query: str, result: dict) -> str:
        for p in _ORDER_DESC_PATTERNS:
            if p.search(query):
                result["order"] = "desc"
                break
        for p in _ORDER_ASC_PATTERNS:
            if p.search(query):
                result["order"] = "asc"
                break
        if result["intent"] == "ranking" and result["order"] is None:
            result["order"] = "desc"
        return query

    # ── Top-N ──

    def _extract_top_n(self, query: str, result: dict) -> str:
        m = _TOP_N_PATTERN.search(query)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 100:
                result["limit"] = n
                result["intent"] = "ranking"
                if result["order"] is None:
                    result["order"] = "desc"
                query = _TOP_N_PATTERN.sub('', query)
        return query

    # ── 清洗 ──

    @staticmethod
    def _clean_query(query: str) -> str:
        cleaned = _NOISE_PATTERN.sub('', query)
        cleaned = _SUFFIX_PATTERN.sub('', cleaned)
        cleaned = cleaned.replace('板块', '')
        cleaned = ' '.join(cleaned.split())
        return cleaned
