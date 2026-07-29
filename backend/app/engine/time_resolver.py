#!/usr/bin/env python3
"""
时间解析器 — 基于实时系统日期，将自然语言时间表达解析为快照 ID 列表。

核心原则:
  - 所有时间计算基于 datetime.date.today()，零硬编码
  - 快照映射从 data_snapshots 表动态查询
  - 无匹配时返回空列表，不报错
  - 支持 YTD/MTD/YoY/MoM 等时间智能模式
"""

import re
from datetime import date
from typing import Optional

from ..core.logging import get_logger

logger = get_logger(__name__)

# ── 中文数字 ──

_CN_NUM = {
    '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}


def _parse_num(s: str) -> Optional[int]:
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s)


def _months_in_range(start_year: int, start_month: int,
                     end_year: int, end_month: int) -> list:
    result = []
    y, m = start_year, start_month
    while (y < end_year) or (y == end_year and m <= end_month):
        result.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def build_period_map(snapshots: list[dict]) -> dict:
    """从快照列表构建 {data_period: [snapshot_id, ...]} 映射"""
    pmap = {}
    for s in snapshots:
        period = s["data_period"]
        if period not in pmap:
            pmap[period] = []
        pmap[period].append(s["snapshot_id"])
    return pmap


def resolve_time(query: str, snapshots: list[dict]) -> tuple:
    """
    从用户查询中提取时间范围。

    Returns:
        (cleaned_query, snapshot_ids, period_label, time_intelligence)
        - snapshot_ids: list[int] | None (None = 未指定时间)
        - period_label: str | None
        - time_intelligence: dict | None (如 {"function": "ytd", ...})
    """
    today = date.today()
    period_map = build_period_map(snapshots)

    cleaned = query.strip()
    snapshot_ids = None
    period_label = None
    time_intel = None

    def _periods_to_ids(periods: list) -> list:
        ids = []
        for p in periods:
            if p in period_map:
                ids.extend(period_map[p])
        return ids

    # ═══ 优先级 1: 绝对时间 ═══

    # Q1-Q4 / 季度
    quarter_match = re.search(
        r'(Q\s*[1-4])\s*(?:季度)?|'
        r'第\s*([一二三四1-4])\s*季度|'
        r'([一二三四1-4])\s*季度|'
        r'([一二三四1-4])\s*季(?!度)',
        cleaned
    )
    if quarter_match:
        q_map = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
        chinese_map = {'一': 1, '二': 2, '三': 3, '四': 4}
        q = None
        if quarter_match.group(1):
            q = int(quarter_match.group(1)[1])
        elif quarter_match.group(2):
            s = quarter_match.group(2)
            q = int(s) if s.isdigit() else chinese_map.get(s, 1)
        elif quarter_match.group(3):
            s = quarter_match.group(3)
            q = int(s) if s.isdigit() else chinese_map.get(s, 1)
        elif quarter_match.group(4):
            s = quarter_match.group(4)
            q = int(s) if s.isdigit() else chinese_map.get(s, 1)

        if q:
            start_m, end_m = q_map.get(q, (1, 3))
            periods = _months_in_range(today.year, start_m, today.year, end_m)
            snapshot_ids = _periods_to_ids(periods)
            period_label = f"{today.year}-Q{q}"
            cleaned = re.sub(
                r'Q\s*[1-4]\s*(?:季度)?|'
                r'第\s*[一二三四1-4]\s*季度|'
                r'[一二三四1-4]\s*季度|'
                r'[一二三四1-4]\s*季(?!度)',
                '', cleaned
            ).strip()
            return cleaned, snapshot_ids, period_label, time_intel

    # 月份范围: "7到9月" / "7-9月"
    range_match = re.search(r'(\d{1,2})\s*月?\s*[-到至]\s*(\d{1,2})\s*月?', cleaned)
    if range_match:
        start_m, end_m = int(range_match.group(1)), int(range_match.group(2))
        if 1 <= start_m <= 12 and 1 <= end_m <= 12 and start_m <= end_m:
            periods = _months_in_range(today.year, start_m, today.year, end_m)
            snapshot_ids = _periods_to_ids(periods)
            period_label = f"{today.year}-{start_m:02d} ~ {today.year}-{end_m:02d}"
            cleaned = re.sub(r'\d{1,2}\s*月?\s*[-到至]\s*\d{1,2}\s*月?', '', cleaned).strip()
            return cleaned, snapshot_ids, period_label, time_intel

    # 上半年 / 下半年
    half_match = re.search(r'(上|下)半年', cleaned)
    if half_match:
        half = half_match.group(1)
        if half == '上':
            periods = _months_in_range(today.year, 1, today.year, 6)
            period_label = f"{today.year}-H1"
        else:
            periods = _months_in_range(today.year, 7, today.year, 12)
            period_label = f"{today.year}-H2"
        snapshot_ids = _periods_to_ids(periods)
        cleaned = re.sub(r'[上下]半年', '', cleaned).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # 单月: "7月"
    single_match = re.search(r'(\d{1,2})\s*月', cleaned)
    if single_match:
        m = int(single_match.group(1))
        if 1 <= m <= 12:
            period = f"{today.year}-{m:02d}"
            snapshot_ids = _periods_to_ids([period])
            period_label = period if snapshot_ids else f"{period} (无数据)"
            cleaned = re.sub(r'\d{1,2}\s*月', '', cleaned).strip()
            return cleaned, snapshot_ids, period_label, time_intel

    # ═══ 优先级 2: 相对时间 ═══

    # "上个季度"
    if re.search(r'(上个?|前[一1]个?)\s*季度', cleaned):
        current_q = (today.month - 1) // 3 + 1
        prev_q = current_q - 1 if current_q > 1 else 4
        prev_year = today.year if current_q > 1 else today.year - 1
        q_map = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
        start_m, end_m = q_map[prev_q]
        periods = _months_in_range(prev_year, start_m, prev_year, end_m)
        snapshot_ids = _periods_to_ids(periods)
        period_label = f"{prev_year}-Q{prev_q}"
        cleaned = re.sub(r'(上个?|前[一1]个?)\s*季度', '', cleaned).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "本季度"
    if re.search(r'(本|这个?|当)\s*季度', cleaned):
        current_q = (today.month - 1) // 3 + 1
        q_map = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
        start_m, end_m = q_map[current_q]
        periods = _months_in_range(today.year, start_m, today.year, end_m)
        snapshot_ids = _periods_to_ids(periods)
        period_label = f"{today.year}-Q{current_q}"
        cleaned = re.sub(r'(本|这个?|当)\s*季度', '', cleaned).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "上个月"
    if re.search(r'(上个?|前[一1]个?)\s*月(?!份)', cleaned):
        prev_m = today.month - 1 if today.month > 1 else 12
        prev_y = today.year if today.month > 1 else today.year - 1
        period = f"{prev_y}-{prev_m:02d}"
        snapshot_ids = _periods_to_ids([period])
        period_label = period if snapshot_ids else f"{period} (无数据)"
        cleaned = re.sub(r'(上个?|前[一1]个?)\s*月', '', cleaned).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "本月"
    if re.search(r'(这个?|本|当)\s*月', cleaned):
        period = f"{today.year}-{today.month:02d}"
        snapshot_ids = _periods_to_ids([period])
        period_label = period if snapshot_ids else f"{period} (无数据)"
        cleaned = re.sub(r'(这个?|本|当)\s*月', '', cleaned).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "今年" / "YTD" → 标记为时间智能
    if re.search(r'(今年|年初至今|YTD|本年度?|当年度?)', cleaned, re.IGNORECASE):
        periods = _months_in_range(today.year, 1, today.year, today.month)
        snapshot_ids = _periods_to_ids(periods)
        period_label = f"{today.year}-01 ~ {today.year}-{today.month:02d} (YTD)"
        time_intel = {"function": "ytd", "year": today.year}
        cleaned = re.sub(r'(今年|年初至今|YTD|本年度?|当年度?)', '', cleaned, re.IGNORECASE).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "同比" → 标记为时间智能
    if re.search(r'同比|YOY|YoY|与去年|较去年', cleaned, re.IGNORECASE):
        # 默认使用当前月份 vs 去年同月
        period = f"{today.year}-{today.month:02d}"
        prev_period = f"{today.year-1}-{today.month:02d}"
        snapshot_ids = _periods_to_ids([period])
        prev_ids = _periods_to_ids([prev_period])
        period_label = f"{period} vs {prev_period} (同比)"
        time_intel = {
            "function": "yoy",
            "current_periods": [period],
            "previous_periods": [prev_period],
            "current_ids": snapshot_ids,
            "previous_ids": prev_ids,
        }
        cleaned = re.sub(r'同比|YOY|YoY|与去年|较去年', '', cleaned, re.IGNORECASE).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "环比" → 标记为时间智能
    if re.search(r'环比|MOM|MoM|较上月|与上月', cleaned, re.IGNORECASE):
        prev_m = today.month - 1 if today.month > 1 else 12
        prev_y = today.year if today.month > 1 else today.year - 1
        period = f"{today.year}-{today.month:02d}"
        prev_period = f"{prev_y}-{prev_m:02d}"
        snapshot_ids = _periods_to_ids([period])
        prev_ids = _periods_to_ids([prev_period])
        period_label = f"{period} vs {prev_period} (环比)"
        time_intel = {
            "function": "mom",
            "current_periods": [period],
            "previous_periods": [prev_period],
            "current_ids": snapshot_ids,
            "previous_ids": prev_ids,
        }
        cleaned = re.sub(r'环比|MOM|MoM|较上月|与上月', '', cleaned, re.IGNORECASE).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "近半年"
    if re.search(r'(?:近|最近|过去)\s*半年', cleaned):
        start_m = today.month - 5
        start_y = today.year
        while start_m <= 0:
            start_m += 12
            start_y -= 1
        periods = _months_in_range(start_y, start_m, today.year, today.month)
        snapshot_ids = _periods_to_ids(periods)
        period_label = f"近半年 ({periods[0]} ~ {periods[-1]})" if periods else "近半年"
        cleaned = re.sub(r'(?:近|最近|过去)\s*半年', '', cleaned).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # "近N个月"
    recent_match = re.search(
        r'(?:近|最近|过去)\s*([0-9一二两三四五六七八九十]+)\s*(?:个)?月', cleaned
    )
    if recent_match:
        n = _parse_num(recent_match.group(1))
        if n and 1 <= n <= 24:
            start_m = today.month - (n - 1)
            start_y = today.year
            while start_m <= 0:
                start_m += 12
                start_y -= 1
            periods = _months_in_range(start_y, start_m, today.year, today.month)
            snapshot_ids = _periods_to_ids(periods)
            period_label = f"近{n}个月 ({periods[0]} ~ {periods[-1]})" if periods else f"近{n}个月"
            cleaned = re.sub(r'(?:近|最近|过去)\s*[0-9一二两三四五六七八九十]+\s*(?:个)?月', '', cleaned).strip()
            return cleaned, snapshot_ids, period_label, time_intel

    # "去年"
    if re.search(r'(去年|上[一1]年)', cleaned):
        prev_year = today.year - 1
        periods = _months_in_range(prev_year, 1, prev_year, 12)
        snapshot_ids = _periods_to_ids(periods)
        period_label = f"{prev_year}年"
        cleaned = re.sub(r'(去年|上[一1]年)', '', cleaned).strip()
        return cleaned, snapshot_ids, period_label, time_intel

    # ═══ 优先级 3: 无时间词 ═══
    return cleaned, None, None, None
