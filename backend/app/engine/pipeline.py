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
    完整查询流水线:
      Stage 1: NER 实体提取
      Stage 2: 时间解析
      Stage 3: 指标匹配
      Stage 4: SQL 生成 (模板/LLM)
      Stage 5: 治理检查 (五层)
      Stage 6: SQL 执行
      Stage 7: 结果构建
    """

    def __init__(self, db, llm_provider=None):
        self.db = db
        self.llm = llm_provider

    def run(self, query: str, user: dict) -> dict:
        """执行完整流水线，返回响应字典"""
        t_start = time.perf_counter()
        ctx = PipelineContext(query, user, self.db)

        # Stage 1: NER
        self._stage1_ner(ctx)

        # Stage 2: Time
        self._stage2_time(ctx)

        # Stage 3: Metric
        if not self._stage3_metric(ctx):
            return self._error_response(ctx, "未找到匹配指标")

        # Check metric status
        metric = ctx.matched_metric
        if metric.get("status") == "pending" or not metric.get("sql_template"):
            return {
                "type": "pending",
                "metric_name": metric["name"],
                "explanation": metric.get("explanation", ""),
                "hint": "该指标数据尚未接入",
                "process": ctx.stages,
                "entity_tags": ctx.entities.get("entity_tags", []),
            }

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
        return response

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

        # 多级搜索
        search_queries = [ctx.cleaned_query]
        hint = ctx.entities.get("metric_hint", "")
        if hint and hint != ctx.cleaned_query:
            search_queries.append(hint)
        if ctx.query not in search_queries:
            search_queries.append(ctx.query)

        results = []
        for sq in search_queries:
            results = loader.search(sq, top_k=5)
            if results:
                break

        if not results:
            ctx.add_stage("指标匹配", "error", (time.perf_counter() - t3) * 1000, "未找到")
            return False

        best = results[0]
        has_ner = ctx.entities.get("filters") or ctx.entities.get("group_by")
        if best["score"] != 1.0 and not has_ner:
            ctx.add_stage("指标匹配", "error", (time.perf_counter() - t3) * 1000,
                          f"模糊匹配: {best['metric']['name']} (score={best['score']:.2f})")
            ctx._suggestions = [r["metric"]["name"] for r in results]
            return False

        ctx.matched_metric = best["metric"]
        ctx.add_stage("指标匹配", "done", (time.perf_counter() - t3) * 1000,
                      f"{best['metric']['name']} (score={best['score']:.2f})")
        return True

    # ── Stage 4: SQL gen ──

    def _stage4_sql(self, ctx: PipelineContext):
        t4 = time.perf_counter()
        from .sql_filter import apply_entities

        sql = ctx.matched_metric["sql_template"]

        # 应用 NER 实体
        if ctx.entities.get("filters") or ctx.entities.get("group_by") or ctx.entities.get("order"):
            sql = apply_entities(sql, ctx.entities)

        ctx.generated_sql = sql
        ctx.add_stage("SQL生成", "done", (time.perf_counter() - t4) * 1000,
                      "模板生成")

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
                sql = self._build_union(sql, ctx.snapshot_ids,
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

            # Time intelligence
            ti_result = None
            if ctx.time_intelligence and ctx.time_intelligence.get("previous_ids"):
                from .time_intelligence import TimeIntelligenceEngine
                engine = TimeIntelligenceEngine(ctx.db)
                scope_sql = ""
                from ..core.security import build_data_scope_sql
                scope_sql = build_data_scope_sql(ctx.user)

                ti_result = engine.compute(
                    ctx.time_intelligence["function"],
                    value,
                    ctx.matched_metric["sql_template"],
                    scope_sql,
                    ctx.snapshot_ids or [],
                    ctx.time_intelligence.get("previous_ids", []),
                )

            return {
                "type": "number",
                "metric_name": metric.get("name", ""),
                "display_name": metric.get("display_name") or metric.get("name", ""),
                "value": value,
                "unit": metric.get("result_unit", ""),
                "result_format": fmt,
                "explanation": metric.get("explanation", ""),
                "sql": ctx.governance_result.get("final_sql", ""),
                "exec_ms": ctx.exec_ms,
                "row_count": len(rows),
                "alert_level": metric.get("alert_level"),
                "snapshot_label": ctx.period_label or "",
                "time_intelligence": ti_result,
                "data_scope": scope,
                "entity_tags": tags,
            }

        # Table result
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
        }

    # ── Helpers ──

    def _error_response(self, ctx: PipelineContext, message: str) -> dict:
        suggestions = getattr(ctx, "_suggestions", ["输入 /list 查看所有指标"])
        return {
            "type": "error",
            "message": message,
            "suggestions": suggestions,
            "process": ctx.stages,
        }

    @staticmethod
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
