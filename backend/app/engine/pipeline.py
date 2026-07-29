"""NL2SQL 查询流水线编排器 — Stage 0-7"""

import time

from ..core.logging import get_logger

logger = get_logger(__name__)


class PipelineContext:
    """流水线上下文 — 在各 Stage 间传递数据"""

    def __init__(self, query: str, user: dict, db):
        self.query = query
        self.user = user
        self.db = db

        # 中间结果
        self.cleaned_query = query
        self.entities: dict = {}
        self.snapshot_ids: list = []
        self.period_label: str = ""
        self.time_intelligence: dict | None = None
        self.matched_metric: dict | None = None
        self.generated_sql: str = ""
        self.executed_rows: list = []
        self.exec_ms: float = 0

        # 过程记录
        self.stages: list[dict] = []
        self.errors: list[dict] = []

    def add_stage(self, name: str, status: str, elapsed_ms: float, detail: str = ""):
        self.stages.append({
            "name": name, "status": status,
            "elapsed_ms": round(elapsed_ms, 2), "detail": detail,
        })


class NL2SQLPipeline:
    """
    完整查询流水线 (Stage 0-7):
      Stage 0: 数据预检 (新鲜度/可用性/时间范围提示)
      Stage 1: NER 实体提取 (区域/业务线/意图/排序)
      Stage 2: 时间解析 (自然语言→快照ID)
      Stage 3: 指标匹配 (精确→包含→模糊)
      Stage 4: SQL 生成 (模板/LLM) + NER 注入
      Stage 5: 治理检查 (五层防护: 权限/安全/预估/保护/缓存)
      Stage 6: SQL 执行 (单快照 WHERE / 多快照 UNION ALL)
      Stage 7: 结果构建 (数值卡/表格/时间智能)
    """

    def __init__(self, db, llm_provider=None):
        self.db = db
        self.llm = llm_provider

    def run(self, query: str, user: dict) -> dict:
        """执行完整流水线，返回响应字典"""
        t_start = time.perf_counter()
        ctx = PipelineContext(query, user, self.db)

        # Stage 0: 数据预检
        self._stage0_preflight(ctx)

        # Stage 1: NER
        self._stage1_ner(ctx)

        # Stage 1.2: 知识库增强 (同义词扩展 + 业务逻辑)
        from .stage_kb import enhance_with_kb
        enhance_with_kb(ctx)

        # Stage 1.5: 反问澄清检测
        from .stage_clarify import check_clarification
        clarification = check_clarification(ctx)
        if clarification:
            clarification["elapsed_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
            clarification["process"] = ctx.stages
            return clarification

        # Stage 2: Time
        self._stage2_time(ctx)

        # Stage 3: Metric
        if not self._stage3_metric(ctx):
            return self._error_response(ctx, "未找到匹配指标")

        # Check metric status
        metric = ctx.matched_metric
        if metric.get("status") == "pending" or not metric.get("sql_template"):
            response = {
                "type": "pending",
                "metric_name": metric["name"],
                "explanation": metric.get("explanation", ""),
                "hint": "该指标数据尚未接入",
                "process": ctx.stages,
                "entity_tags": ctx.entities.get("entity_tags", []),
            }
            if hasattr(ctx, 'preflight') and ctx.preflight:
                response["preflight"] = ctx.preflight
            return response

        # Stage 4: SQL gen
        self._stage4_sql(ctx)

        # Stage 5: Governance
        if not self._stage5_governance(ctx):
            return self._error_response(ctx, ctx.errors[-1].get("detail", "查询被拒绝"))

        # Stage 6: Execute
        self._stage6_execute(ctx)

        # Stage 7: Build response
        response = self._stage7_response(ctx)
        response["elapsed_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
        response["process"] = ctx.stages
        if hasattr(ctx, 'preflight') and ctx.preflight:
            response["preflight"] = ctx.preflight
        return response

    # ── Stage 0: Preflight ──

    def _stage0_preflight(self, ctx: PipelineContext):
        t0 = time.perf_counter()
        from .stage0_preflight import Stage0Preflight
        preflight = Stage0Preflight(ctx.db)
        result = preflight.check(ctx.query)
        ctx.preflight = result
        status = result["status"]
        detail = "; ".join(result["messages"]) if result["messages"] else "通过"
        ctx.add_stage("数据预检", status, (time.perf_counter() - t0) * 1000, detail)

    # ── Stage 1: NER ──

    def _stage1_ner(self, ctx: PipelineContext):
        t1 = time.perf_counter()
        from .ner_engine import NEREngine
        ner = NEREngine(ctx.db)
        ctx.entities = ner.extract(ctx.query)
        ctx.add_stage("NER实体提取", "done", (time.perf_counter() - t1) * 1000,
                      f"意图={ctx.entities.get('intent', '?')}, 筛选={len(ctx.entities.get('filters', []))}条")


    # ── Stage 2: Time ──

    def _stage2_time(self, ctx: PipelineContext):
        t2 = time.perf_counter()
        from .time_resolver import resolve_time
        cleaned, ids, label, ti = resolve_time(ctx.query, ctx.db.get_snapshots())
        ctx.cleaned_query = cleaned
        ctx.snapshot_ids = ids
        ctx.period_label = label
        ctx.time_intelligence = ti
        ctx.entities["time"] = {"label": label} if label else None
        ctx.entities["completeness"]["has_time"] = label is not None
        ctx.entities["time_intelligence"] = ti
        ctx.add_stage("时间解析", "done", (time.perf_counter() - t2) * 1000,
                      label or "未指定时间")

    # ── Stage 3: Metric match ──

    def _stage3_metric(self, ctx: PipelineContext) -> bool:
        t3 = time.perf_counter()
        from ..semantic.loader import MetricLoader
        loader = MetricLoader(ctx.db)

        # 多级搜索 (原始查询优先 → KB同义词增强)
        search_queries = []
        # 1. 清洗后的查询 (最高优先级 - 保留用户原意)
        if ctx.cleaned_query not in search_queries:
            search_queries.append(ctx.cleaned_query)
        # 2. NER提取的指标提示
        hint = ctx.entities.get("metric_hint", "")
        if hint and hint not in search_queries:
            search_queries.append(hint)
        # 3. KB同义词扩展 (增强, 不覆盖)
        kb_synonyms = getattr(ctx, 'kb_synonyms', [])
        for syn in kb_synonyms:
            if syn not in search_queries:
                search_queries.append(syn)
        # 4. 原始查询
        if ctx.query not in search_queries:
            search_queries.append(ctx.query)

        # 多轮搜索, 合并结果取最优 (不早停)
        # priority_index: 记录最早匹配的搜索轮次, 用于同分tiebreaker
        all_results = {}
        for qi, sq in enumerate(search_queries):
            round_results = loader.search(sq, top_k=5)
            for rr in round_results:
                mid = rr["metric"]["metric_id"]
                if mid not in all_results:
                    all_results[mid] = rr
                    all_results[mid]["_priority"] = qi  # 越小越优先
                elif rr["score"] > all_results[mid]["score"]:
                    all_results[mid] = rr
                    all_results[mid]["_priority"] = qi
                elif rr["score"] == all_results[mid]["score"] and qi < all_results[mid].get("_priority", 999):
                    # 同分时优先更早搜索轮次的结果 (cleaned_query > KB synonym)
                    all_results[mid] = rr
                    all_results[mid]["_priority"] = qi
        # 按分数降序, 同分按优先级升序
        # 有 group_by 时: 表格型指标加权 (NER 已识别分组意图)
        has_group = ctx.entities.get("group_by")
        def sort_key(x):
            score = x["score"]
            # NER有分组意图时: 表格型指标 boost 0.05
            if has_group and x["metric"].get("result_format") == "table":
                score += 0.05
            prio = x.get("_priority", 999)
            return (score, -prio)
        results = sorted(all_results.values(), key=sort_key, reverse=True)[:5]

        if not results:
            ctx.add_stage("指标匹配", "error", (time.perf_counter() - t3) * 1000, "未找到")
            return False

        best = results[0]
        ctx.matched_metric = best["metric"]
        ctx.matched_metric["_match_score"] = best["score"]
        has_ner = ctx.entities.get("filters") or ctx.entities.get("group_by")
        # KB同义词命中 → 放宽模糊匹配门槛 (无需NER筛选)
        kb_synonyms = getattr(ctx, 'kb_synonyms', [])
        kb_boosted = bool(kb_synonyms) and best["score"] >= 0.7

        if best["score"] != 1.0 and not has_ner and not kb_boosted:
            ctx.add_stage("指标匹配", "error", (time.perf_counter() - t3) * 1000,
                          f"模糊匹配: {best['metric']['name']} (score={best['score']:.2f})")
            ctx._suggestions = [r["metric"]["name"] for r in results]
            return False

        ctx.add_stage("指标匹配", "done", (time.perf_counter() - t3) * 1000,
                      f"{best['metric']['name']} (score={best['score']:.2f})")
        return True

    # ── Stage 4: SQL gen ──

    def _stage4_sql(self, ctx: PipelineContext):
        t4 = time.perf_counter()
        from .sql_filter import apply_entities

        sql = ctx.matched_metric.get("sql_template", "")
        match_score = ctx.matched_metric.get("_match_score", 1.0)
        gen_method = "模板"

        # 决策: 模板匹配分数高 → 用模板; 分数低或LLM可用 → 尝试LLM增强
        if sql and match_score >= 0.8:
            # 高置信度: 直接用模板
            pass
        elif self.llm and sql:
            # 中置信度 + LLM可用: 用LLM优化SQL
            try:
                llm_sql = self._try_llm_sql(ctx, sql)
                if llm_sql:
                    sql = llm_sql
                    gen_method = "LLM增强"
            except Exception as e:
                logger.warning("LLM SQL 生成失败: %s, 回退模板", e)
        elif self.llm and not sql:
            # 无模板 + LLM可用: 完全由LLM生成
            try:
                llm_sql = self._try_llm_sql(ctx, None)
                if llm_sql:
                    sql = llm_sql
                    gen_method = "LLM生成"
            except Exception as e:
                logger.warning("LLM SQL 生成失败: %s", e)

        if not sql:
            ctx.add_stage("SQL生成", "error", (time.perf_counter() - t4) * 1000,
                          "无法生成SQL")
            raise ValueError("无法生成SQL: 无模板且LLM不可用")

        # 应用 NER 实体
        if ctx.entities.get("filters") or ctx.entities.get("group_by") or ctx.entities.get("order"):
            sql = apply_entities(sql, ctx.entities)

        # 应用 KB 业务逻辑条件
        kb_conditions = ctx.entities.get("kb_conditions", [])
        if kb_conditions:
            for kc in kb_conditions:
                cond = kc["condition"]
                if "WHERE" in sql.upper():
                    sql = sql.replace("WHERE", f"WHERE ({cond}) AND ", 1)
                else:
                    # 在 FROM 子句之后插入 WHERE
                    import re
                    sql = re.sub(
                        r'(FROM\s+"?\w+"?\s*)', f'\\1WHERE ({cond}) ', sql,
                        count=1, flags=re.IGNORECASE
                    )

        ctx.generated_sql = sql
        ctx.add_stage("SQL生成", "done", (time.perf_counter() - t4) * 1000,
                      gen_method)

    def _try_llm_sql(self, ctx: PipelineContext, base_template: str | None = None) -> str | None:
        """使用 LLM 生成/优化 SQL (同步包装)"""
        import asyncio
        import concurrent.futures

        from ..llm.prompts import PromptManager

        pm = PromptManager()

        # 构建上下文
        metric = ctx.matched_metric or {}
        tables_info = self._get_tables_info(ctx)

        # 渲染提示词
        if base_template:
            prompt = pm.render("sql_generator", **{
                "query": ctx.query,
                "metric": metric,
                "base_sql": base_template,
                "tables": tables_info,
                "entities": ctx.entities,
            })
        else:
            prompt = pm.render("sql_generator", **{
                "query": ctx.query,
                "tables": tables_info,
                "entities": ctx.entities,
            })

        messages = [{"role": "user", "content": prompt}]

        # 同步调用异步LLM (适配FastAPI事件循环环境)
        result = self._run_async(self.llm.chat(messages))
        if not result or "SELECT" not in result.upper():
            return None

        # 提取SQL (去除markdown包裹)
        import re
        m = re.search(r'```(?:sql)?\s*\n?(SELECT[\s\S]*?)\n?```', result, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r'(SELECT[\s\S]*)', result, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(';').strip()
        return None

    @staticmethod
    def _run_async(coro):
        """在线程池中运行异步协程, 兼容同步调用场景"""
        import asyncio
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)

    def _get_tables_info(self, ctx: PipelineContext) -> str:
        """获取相关表结构信息"""
        tables = []
        metric = ctx.matched_metric or {}
        table_name = metric.get("table_name", "")
        if table_name:
            try:
                info = ctx.db.get_table_schema(table_name)
                if info:
                    cols = ", ".join(f"{c['name']}({c['type']})" for c in info)
                    tables.append(f"表 {table_name}: {cols}")
            except Exception:
                tables.append(f"表: {table_name}")
        return "\n".join(tables)

    # ── Stage 5: Governance ──

    def _stage5_governance(self, ctx: PipelineContext) -> bool:
        t5 = time.perf_counter()
        from ..governance import GovernanceManager

        gov = GovernanceManager(ctx.db)
        result = gov.apply(ctx.generated_sql, ctx.user)

        if result["denied"]:
            ctx.errors.append({"stage": "governance", "detail": result.get("reason", "被拒绝")})
            ctx.add_stage("治理检查", "error", (time.perf_counter() - t5) * 1000,
                          result.get("reason", ""))
            return False

        ctx.governance_result = result
        ctx.add_stage("治理检查", "done", (time.perf_counter() - t5) * 1000,
                      f"{result['scope_label']}" + (" [缓存命中]" if result['cache_hit'] else ""))
        return True

    # ── Stage 6: Execute ──

    def _stage6_execute(self, ctx: PipelineContext):
        t6 = time.perf_counter()
        from .sql_filter import inject_snapshot_where
        import re

        sql = ctx.governance_result["final_sql"]

        # 注入快照过滤
        if ctx.snapshot_ids is not None and len(ctx.snapshot_ids) > 0:
            if len(ctx.snapshot_ids) == 1:
                sql = inject_snapshot_where(sql, ctx.snapshot_ids)
            else:
                sql = _build_union(sql, ctx.snapshot_ids,
                                        ctx.matched_metric.get("result_format", "number"))

        try:
            rows = ctx.db.execute(sql)
            ctx.executed_rows = rows
            ctx.exec_ms = round((time.perf_counter() - t6) * 1000, 2)
            ctx.add_stage("SQL执行", "done", ctx.exec_ms, f"返回 {len(rows)} 行")

            # 记录成功
            ctx.governance_result["_cache_key"] = ctx.governance_result.get("cache_key", "")
            from ..governance import GovernanceManager
            gov = GovernanceManager(ctx.db)
            gov.record_result(ctx.governance_result.get("cache_key", ""),
                              {"rows": rows, "sql": sql}, True)
        except Exception as e:
            ctx.errors.append({"stage": "execute", "detail": str(e)})
            ctx.add_stage("SQL执行", "error", (time.perf_counter() - t6) * 1000, str(e)[:80])
            from ..governance import GovernanceManager
            gov = GovernanceManager(ctx.db)
            gov.record_result(ctx.governance_result.get("cache_key", ""), {}, False)

    # ── Stage 7: Response ──

    def _stage7_response(self, ctx: PipelineContext) -> dict:
        metric = ctx.matched_metric or {}
        fmt = metric.get("result_format", "number")
        rows = ctx.executed_rows

        # Entity tags
        tags = []
        for f in ctx.entities.get("filters", []):
            tags.append({"type": "filter", "label": f"{f['field']}={f['value']}"})
        if ctx.entities.get("group_by"):
            names = {"region": "按区域", "business_line": "按业务线"}
            tags.append({"type": "group", "label": names.get(ctx.entities["group_by"], ctx.entities["group_by"])})
        if ctx.entities.get("limit"):
            tags.append({"type": "limit", "label": f"Top {ctx.entities['limit']}"})

        scope = ctx.governance_result.get("scope_label", "")

        if fmt in ("number", "integer", "percent"):
            value = None
            if rows and "value" in rows[0]:
                raw = rows[0]["value"]
                if fmt == "integer":
                    value = int(raw) if raw else 0
                elif fmt == "percent":
                    value = round(raw, 2) if raw else 0
                else:
                    value = round(raw, 2) if raw else 0

            # Time intelligence (同比/环比/变化解析)
            ti_result = ctx.time_intelligence  # from Stage 2
            if ti_result and ti_result.get("previous_ids"):
                from .time_intelligence import TimeIntelligenceEngine
                engine = TimeIntelligenceEngine(ctx.db)
                from ..core.security import build_data_scope_sql
                ti_result = engine.compute(
                    ti_result.get("function", "mom"),
                    value,
                    ctx.matched_metric["sql_template"],
                    build_data_scope_sql(ctx.user),
                    ctx.snapshot_ids or [],
                    ti_result.get("previous_ids", []),
                )
            # 自动环比: 无time_intelligence时比较相邻快照
            if not ti_result or not ti_result.get("available"):
                ti_result = _auto_mom(ctx.db, ctx.matched_metric, value, ctx.snapshot_ids)

            return {
                "type": "number",
                "metric_name": metric.get("name", ""),
                "display_name": metric.get("display_name") or metric.get("name", ""),
                "value": value,
                "unit": metric.get("result_unit", ""),
                "result_format": fmt,
                "explanation": metric.get("explanation", ""),
                "formula": metric.get("formula", ""),
                "sql": ctx.governance_result.get("final_sql", ""),
                "exec_ms": ctx.exec_ms,
                "row_count": len(rows),
                "alert_level": metric.get("alert_level"),
                "snapshot_label": ctx.period_label or "",
                "time_intelligence": ti_result,
                "data_scope": scope,
                "entity_tags": tags,
            }

        # Table result + drill-down suggestions
        drill = _suggest_drilldown(metric.get("name", ""), rows)
        return {
            "type": "table",
            "metric_name": metric.get("name", ""),
            "display_name": metric.get("display_name") or metric.get("name", ""),
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "result_format": fmt,
            "explanation": metric.get("explanation", ""),
            "sql": ctx.governance_result.get("final_sql", ""),
            "exec_ms": ctx.exec_ms,
            "row_count": len(rows),
            "snapshot_label": ctx.period_label or "",
            "data_scope": scope,
            "entity_tags": tags,
            "drill_down": drill,
        }

    # ── Helpers ──

    def _error_response(self, ctx: PipelineContext, message: str) -> dict:
        suggestions = getattr(ctx, "_suggestions", ["输入 /list 查看所有指标"])
        response = {
            "type": "error",
            "message": message,
            "suggestions": suggestions,
            "process": ctx.stages,
        }
        # 附带预检信息
        if hasattr(ctx, 'preflight') and ctx.preflight:
            response["preflight"] = ctx.preflight
        return response

def _auto_mom(db, metric: dict, current_value, snapshot_ids: list = None) -> dict | None:
    """自动计算环比: 跨同基名表的不同期间值变化"""
    if current_value is None:
        return None
    try:
        table = metric.get("table_name", "")
        if not table:
            return None
        # 提取基名 (去掉 _2026_07 后缀)
        import re
        base = re.sub(r'_\d{4}_\d{2}$', '', table)
        # 找同基名的所有快照
        snaps = db.execute(
            "SELECT snapshot_id, table_name, data_period FROM data_snapshots WHERE table_name LIKE ? ORDER BY data_period",
            (f"{base}%",)
        )
        if len(snaps) < 2:
            return None
        # 取最近两个期间
        prev_snap = snaps[-2]
        cur_snap = snaps[-1]
        # 用上一个快照的表执行相同SQL结构
        sql = metric.get("sql_template", "")
        if not sql:
            return None
        prev_sql = sql.replace(f'"{table}"', f'"{prev_snap["table_name"]}"')
        prev_rows = db.execute(prev_sql)
        prev_val = prev_rows[0]["value"] if prev_rows else None
        if prev_val and prev_val > 0:
            growth = round((current_value - prev_val) / prev_val * 100, 2)
            direction = "↑" if growth >= 0 else "↓"
            return {
                "available": True,
                "label": f"环比 ({prev_snap['data_period']}→{cur_snap['data_period']})",
                "previous_value": prev_val,
                "current_value": current_value,
                "growth_rate": growth,
                "direction": direction,
            }
    except Exception:
        pass
    return None

def _suggest_drilldown(metric_name: str, rows: list) -> list[dict] | None:
    """为表格结果建议下钻维度"""
    if not rows or len(rows) < 2:
        return None
    suggestions = []
    name = metric_name
    # 区域分布 → 建议下钻到业务线
    if "区域" in name or "地市" in name or "城市" in name:
        suggestions.append({"label": "按业务线查看", "query": name.replace("区域", "业务线").replace("地市", "业务线").replace("城市", "业务线")})
    # 业务线分布 → 建议下钻到具体区域
    if "业务线" in name or "板块" in name:
        suggestions.append({"label": "按区域查看", "query": name.replace("业务线", "区域").replace("板块", "区域")})
    # 任何分组 → 可加上时间维度
    if any(kw in name for kw in ("分布", "占比", "排名", "各地市", "各业务")):
        suggestions.append({"label": "查看趋势变化", "query": f"每月 {name}"})
    return suggestions if suggestions else None


def _build_union(base_sql: str, snapshot_ids: list, fmt: str) -> str:
        from .sql_filter import inject_snapshot_where
        import re

        subs = []
        for sid in snapshot_ids:
            sub = inject_snapshot_where(base_sql, [sid])
            sub = re.sub(r'\s*ORDER\s+BY\s+\S+(\s+(ASC|DESC))?\s*$', '', sub,
                         flags=re.IGNORECASE)
            subs.append(sub)

        body = "\nUNION ALL\n".join(subs)

        if fmt == "table":
            return f"SELECT label, ROUND(SUM(value), 2) AS value FROM (\n{body}\n) GROUP BY label ORDER BY value DESC"
        elif fmt in ("number", "integer"):
            return f"SELECT ROUND(SUM(value), 2) AS value FROM (\n{body}\n)"
        elif fmt == "percent":
            return f"SELECT ROUND(AVG(value), 2) AS value FROM (\n{body}\n)"
        return body
