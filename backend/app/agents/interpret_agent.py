"""InterpretAgent — 自然语言结果解读（趋势/对比/归因/异常检测 + LLM缓存）"""

import asyncio
import hashlib
import json
import statistics
import time
from typing import Any

from .base import BaseAgent, AgentContext, AgentResult
from ..core.logging import get_logger

logger = get_logger(__name__)

# LLM 解读缓存 (key → (text, timestamp))
_interpret_cache: dict[str, tuple[str, float]] = {}
_INTERPRET_CACHE_TTL = 300  # 5 分钟
_INTERPRET_CACHE_MAX = 100
_INTERPRET_TIMEOUT = 5.0  # LLM 解读超时 (秒, 比 SQL 生成的 30s 短)


class InterpretAgent(BaseAgent):
    """智能解读查询结果，生成自然语言洞察"""

    name = "interpret"
    description = "自然语言结果解读 + 趋势归因 + 异常检测"

    async def run(self, ctx: AgentContext) -> AgentResult:
        rows = ctx.executed_rows
        metric = ctx.metric
        time_intel = ctx.time_intel or {}

        if not rows:
            return AgentResult.ok({"text": "未查询到相关数据。"})

        # 构建解读文本
        parts = []

        # 1. 基础数值描述
        parts.append(self._describe_value(rows, metric))

        # 2. 时间对比 (YTD/YoY/MoM)
        if time_intel.get("available"):
            parts.append(self._describe_time_comparison(time_intel, metric))

        # 3. 异常检测
        anomaly = self._detect_anomaly(rows, metric)
        if anomaly:
            parts.append(anomaly)

        # 4. 波动归因 (多行数据时)
        if len(rows) > 1:
            parts.append(self._describe_distribution(rows))

        # 5. LLM 增强解读 (当 LLM 可用时)
        if ctx.llm and len(rows) > 0:
            try:
                llm_text = await self._llm_interpret(ctx, rows, metric)
                if llm_text:
                    parts.append(llm_text)
            except Exception as e:
                logger.debug("LLM interpretation skipped: %s", e)

        interpretation = "\n\n".join(p for p in parts if p)
        ctx.interpretation = interpretation

        return AgentResult.ok({"text": interpretation, "anomaly_detected": anomaly is not None})

    def _describe_value(self, rows: list, metric: dict) -> str:
        """基础数值描述"""
        name = metric.get("name", "查询结果")
        unit = metric.get("unit", "")

        if len(rows) == 1 and isinstance(rows[0], dict):
            row = rows[0]
            value = row.get("value", list(row.values())[0] if row else 0)
            if isinstance(value, (int, float)):
                return f"**{name}**：{value:,.2f} {unit}"
            return f"**{name}**：{value}"

        return f"**{name}**：共 {len(rows)} 条记录"

    def _describe_time_comparison(self, ti: dict, metric: dict) -> str:
        """时间对比描述"""
        label = ti.get("label", "")
        direction = ti.get("direction", "")
        growth = ti.get("growth_rate", 0)

        if direction == "increase":
            emoji = "📈"
            word = "增长"
        elif direction == "decrease":
            emoji = "📉"
            word = "下降"
        else:
            return f"环比基本持平"

        return f"{emoji} **{label}**：{word} {abs(growth):.1f}%"

    def _detect_anomaly(self, rows: list, metric: dict) -> str | None:
        """异常检测 — 基于简单统计"""
        if len(rows) < 2:
            return None

        values = []
        for r in rows:
            if isinstance(r, dict):
                v = r.get("value", 0)
                if isinstance(v, (int, float)):
                    values.append(v)

        if len(values) < 3:
            return None

        try:
            mean = statistics.mean(values)
            stdev = statistics.stdev(values) if len(values) > 1 else 0

            if stdev > 0:
                anomalies = []
                for i, v in enumerate(values):
                    z = abs(v - mean) / stdev
                    if z > 2.0:
                        label = rows[i].get("label", f"第{i+1}项") if isinstance(rows[i], dict) else f"第{i+1}项"
                        direction = "偏高" if v > mean else "偏低"
                        anomalies.append(f"{label} {direction}（{v:,.0f}，偏离均值 {z:.1f}σ）")

                if anomalies:
                    return f"⚠️ **异常检测**：\n" + "\n".join(f"- {a}" for a in anomalies[:3])
        except Exception:
            pass

        return None

    def _describe_distribution(self, rows: list) -> str:
        """分布描述 (多行表格)"""
        if len(rows) <= 1:
            return ""

        # 找最大值和最小值
        label_key = next((k for k in rows[0] if k in ("label", "name", "region", "business_line", "category")), None)
        value_key = next((k for k in rows[0] if k in ("value", "amount", "total")), None)

        if not label_key or not value_key:
            return f"共 {len(rows)} 条记录"

        sorted_rows = sorted(rows, key=lambda r: r.get(value_key, 0), reverse=True)
        top = sorted_rows[0]
        bottom = sorted_rows[-1]

        return (
            f"📊 **数据分布**：最高为 **{top[label_key]}**（{top[value_key]:,.0f}），"
            f"最低为 **{bottom[label_key]}**（{bottom[value_key]:,.0f}）"
        )

    async def _llm_interpret(self, ctx: AgentContext, rows: list, metric: dict) -> str | None:
        """LLM 增强解读 (缓存 + 短超时)"""
        try:
            # 缓存键: (metric_name, query, data_summary)
            data_summary = self._summarize_data(rows, metric)
            cache_key = hashlib.md5(
                f"{metric.get('name','')}|{ctx.query}|{data_summary}".encode()
            ).hexdigest()

            # 命中缓存
            global _interpret_cache
            if cache_key in _interpret_cache:
                text, ts = _interpret_cache[cache_key]
                if time.time() - ts < _INTERPRET_CACHE_TTL:
                    return text

            from ..llm.prompts import PromptManager
            pm = PromptManager()
            prompt = pm.render("result_interpreter",
                metric_name=metric.get("name", ""),
                data=data_summary,
                query=ctx.query,
            )

            # 短超时 LLM 调用
            response = await asyncio.wait_for(
                ctx.llm.chat([{"role": "user", "content": prompt}]),
                timeout=_INTERPRET_TIMEOUT,
            )
            if response and len(response) > 5:
                text = f"💡 **AI 解读**：{response.strip()}"
                # 写入缓存 (LRU 淘汰)
                if len(_interpret_cache) >= _INTERPRET_CACHE_MAX:
                    oldest = min(_interpret_cache, key=lambda k: _interpret_cache[k][1])
                    del _interpret_cache[oldest]
                _interpret_cache[cache_key] = (text, time.time())
                return text
        except asyncio.TimeoutError:
            logger.debug("LLM interpret timeout (%.1fs)", _INTERPRET_TIMEOUT)
        except Exception as e:
            logger.debug("LLM interpret failed: %s", e)
        return None

    @staticmethod
    def _summarize_data(rows: list, metric: dict) -> str:
        """将数据压缩为文本摘要供 LLM 解读"""
        if not rows:
            return "无数据"

        name = metric.get("name", "")
        unit = metric.get("unit", "")

        if len(rows) == 1 and isinstance(rows[0], dict):
            v = list(rows[0].values())[0]
            return f"{name}: {v} {unit}"

        lines = [f"{name} ({len(rows)} 条):"]
        for r in rows[:10]:  # 限制 10 行
            line = " | ".join(f"{k}: {v}" for k, v in r.items())
            lines.append(f"  - {line}")
        return "\n".join(lines)
