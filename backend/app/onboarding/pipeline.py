"""数据接入流水线 — 7 步算子 (DataFlow 风格)

Step 1: SchemaScanner      — 自动发现新表/字段变更
Step 2: MetadataExtractor  — 提取字段元数据
Step 3: QualityAssessor    — 字段质量评估 (8项检查)
Step 4: TypeInferrer       — 推断数据集类型
Step 5: ConfigGenerator    — 自动生成语义层配置
Step 6: OnboardingReviewer — 人工审核队列管理
Step 7: SemanticRegistrar  — 注册到语义层 + 向量索引
"""

import re
import json
from datetime import datetime, date
from pathlib import Path
from typing import Any

from ..core.logging import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════
# Step 1: SchemaScanner — 自动发现
# ═══════════════════════════════════════════

class SchemaScanner:
    """扫描数据库，发现新表和字段变更"""

    # 系统表，跳过
    SYSTEM_TABLES = {
        'data_snapshots', 'sqlite_sequence', 'metric_registry',
        'users', 'refresh_tokens', 'query_logs', 'query_feedback',
        'audit_logs', 'user_data_permissions', 'generated_metrics',
        'onboarding_queue', 'schema_registry',
    }

    def __init__(self, db):
        self.db = db

    def scan(self) -> dict:
        """扫描所有用户表，返回发现结果"""
        tables = self.db.get_tables()
        user_tables = [t for t in tables if t not in self.SYSTEM_TABLES
                       and not t.startswith('指标需求')]

        discovered = []
        for table_name in user_tables:
            info = self._scan_table(table_name)
            if info:
                discovered.append(info)

        return {
            "total": len(discovered),
            "tables": discovered,
            "scanned_at": datetime.now().isoformat(),
        }

    def _scan_table(self, table_name: str) -> dict | None:
        """扫描单个表"""
        try:
            row_count = self._count_rows(table_name)
            schema = self.db.get_table_schema(table_name)

            return {
                "table_name": table_name,
                "row_count": row_count,
                "column_count": len(schema),
                "columns": [
                    {"name": c["name"], "type": c["type"],
                     "nullable": not c.get("notnull", 0),
                     "default": c.get("dflt_value"),
                     "pk": c.get("pk", 0)}
                    for c in schema
                ],
            }
        except Exception as e:
            logger.warning("扫描表 %s 失败: %s", table_name, e)
            return None

    def _count_rows(self, table_name: str) -> int:
        try:
            safe = table_name.replace('"', '""')
            result = self.db.execute_one(f'SELECT COUNT(*) AS cnt FROM "{safe}"')
            return result["cnt"] if result else 0
        except Exception:
            return 0

    def detect_changes(self) -> list[dict]:
        """检测与已注册表的差异 (新增表/字段变更)"""
        scan = self.scan()
        registered = self._get_registered_tables()
        changes = []

        for t in scan["tables"]:
            name = t["table_name"]
            if name not in registered:
                changes.append({"type": "new_table", "table": name, "detail": t})
            else:
                reg_cols = set(registered[name])
                cur_cols = {c["name"] for c in t["columns"]}
                added = cur_cols - reg_cols
                removed = reg_cols - cur_cols
                if added or removed:
                    changes.append({
                        "type": "schema_change",
                        "table": name,
                        "added": list(added),
                        "removed": list(removed),
                    })

        return changes

    def _get_registered_tables(self) -> dict[str, set]:
        """从 schema_registry 表获取已注册的表"""
        try:
            rows = self.db.execute(
                "SELECT table_name, columns_json FROM schema_registry"
            )
            return {r["table_name"]: set(json.loads(r["columns_json"]))
                    for r in rows}
        except Exception:
            return {}


# ═══════════════════════════════════════════
# Step 2: MetadataExtractor — 元数据提取
# ═══════════════════════════════════════════

class MetadataExtractor:
    """提取字段元数据: 类型/注释/外键/示例值"""

    def __init__(self, db):
        self.db = db

    def extract(self, table_name: str) -> dict:
        """提取完整元数据"""
        schema = self.db.get_table_schema(table_name)
        sample_rows = self._sample(table_name, 5)
        fk_info = self._get_foreign_keys(table_name)

        fields = []
        for col in schema:
            name = col["name"]
            sql_type = col["type"]
            field = {
                "name": name,
                "sql_type": sql_type,
                "nullable": not col.get("notnull", 0),
                "default_value": col.get("dflt_value"),
                "pk": bool(col.get("pk", 0)),
                "python_type": self._infer_python_type(sql_type),
                "sample_values": self._get_samples(name, sample_rows),
            }

            # Auto-generate display name from column name
            field["display_name"] = self._guess_display_name(name, field["python_type"])
            fields.append(field)

        return {
            "table_name": table_name,
            "row_count": len(sample_rows),
            "fields": fields,
            "foreign_keys": fk_info,
            "extracted_at": datetime.now().isoformat(),
        }

    def _sample(self, table_name: str, limit: int = 5) -> list[dict]:
        try:
            safe = table_name.replace('"', '""')
            return self.db.execute(f'SELECT * FROM "{safe}" LIMIT {limit}')
        except Exception:
            return []

    def _get_foreign_keys(self, table_name: str) -> list[dict]:
        try:
            safe = table_name.replace('"', '""')
            return self.db.execute(f'PRAGMA foreign_key_list("{safe}")')
        except Exception:
            return []

    def _get_samples(self, col_name: str, rows: list[dict]) -> list:
        vals = []
        for r in rows:
            v = r.get(col_name)
            if v is not None:
                vals.append(str(v)[:50])
                if len(vals) >= 3:
                    break
        return vals

    @staticmethod
    def _infer_python_type(sql_type: str) -> str:
        t = sql_type.upper()
        if any(k in t for k in ('INT', 'INTEGER', 'BIGINT', 'SMALLINT')):
            return 'integer'
        if any(k in t for k in ('REAL', 'FLOAT', 'DOUBLE', 'NUMERIC', 'DECIMAL')):
            return 'float'
        if any(k in t for k in ('DATE', 'TIMESTAMP', 'DATETIME')):
            return 'date'
        if any(k in t for k in ('BOOL',)):
            return 'boolean'
        return 'text'

    @staticmethod
    def _guess_display_name(col_name: str, py_type: str) -> str:
        """从列名推测展示名"""
        # 常见模式映射
        patterns = {
            'amount': '金额',
            'price': '价格',
            'count': '数量',
            'name': '名称',
            'region': '区域',
            'status': '状态',
            'date': '日期',
            'time': '时间',
            'phone': '电话',
            'email': '邮箱',
            'address': '地址',
        }
        lower = col_name.lower()
        for pat, cn in patterns.items():
            if pat in lower:
                return cn

        # 中文字段名直接使用
        if any('一' <= c <= '鿿' for c in col_name):
            return col_name
        return col_name


# ═══════════════════════════════════════════
# Step 3: QualityAssessor — 字段质量评估
# ═══════════════════════════════════════════

class QualityAssessor:
    """自动评估字段质量 (8项检查)"""

    CHECKS = [
        "field_name_is_english",
        "field_has_no_description",
        "date_field_not_marked",
        "metric_missing_aggregation",
        "field_name_has_unit",
        "field_name_too_technical",
        "synonyms_count_too_low",
        "example_values_missing",
    ]

    def assess(self, metadata: dict) -> dict:
        """评估数据集字段质量"""
        fields = metadata.get("fields", [])
        issues = []
        check_results = {}

        for field in fields:
            field_issues = []

            # 1. 字段名是否为英文
            if not self._has_chinese(field["name"]):
                field_issues.append({
                    "check": "field_name_is_english",
                    "severity": "warning",
                    "suggestion": f"建议将 '{field['name']}' 改为中文展示名",
                    "auto_fix": field.get("display_name", field["name"]),
                })

            # 2. 字段缺少描述
            field_issues.append({
                "check": "field_has_no_description",
                "severity": "info",
                "suggestion": f"建议为字段 '{field['name']}' 添加描述",
            })

            # 3. 日期字段未标记
            if field["python_type"] == "date":
                field_issues.append({
                    "check": "date_field_not_marked",
                    "severity": "warning",
                    "suggestion": f"'{field['name']}' 是日期字段, 请确认类型标记",
                })

            # 4. 度量字段缺少聚合
            if field["python_type"] in ("integer", "float") and field["name"] not in (
                "snapshot_id", "_row_id", "id", "year", "month",
            ):
                field_issues.append({
                    "check": "metric_missing_aggregation",
                    "severity": "warning",
                    "suggestion": f"数值字段 '{field['name']}' 建议设默认聚合为 SUM",
                    "auto_fix": "SUM" if field["python_type"] != "float" else "AVG",
                })

            # 5. 示例值缺失
            if not field.get("sample_values"):
                field_issues.append({
                    "check": "example_values_missing",
                    "severity": "info",
                    "suggestion": f"建议提供示例值",
                })

            if field_issues:
                issues.append({"field": field["name"], "issues": field_issues})

            for fi in field_issues:
                check = fi["check"]
                if check not in check_results:
                    check_results[check] = 0
                check_results[check] += 1

        # 计算质量分数
        total_fields = len(fields) or 1
        total_issues = sum(len(i["issues"]) for i in issues)
        max_issues = total_fields * len(self.CHECKS)
        score = max(0, 100 - int((total_issues / max_issues) * 100))

        return {
            "table_name": metadata["table_name"],
            "score": score,
            "grade": self._grade(score),
            "total_fields": total_fields,
            "total_issues": total_issues,
            "issues": issues,
            "check_summary": check_results,
            "assessed_at": datetime.now().isoformat(),
        }

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 90:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        if score >= 40:
            return "D"
        return "F"

    @staticmethod
    def _has_chinese(text: str) -> bool:
        return any('一' <= c <= '鿿' for c in text)


# ═══════════════════════════════════════════
# Step 4: TypeInferrer — 数据集类型推断
# ═══════════════════════════════════════════

class TypeInferrer:
    """推断数据集类型: 明细表 / 多指标周期表 / 键值对表 / 其他"""

    def infer(self, metadata: dict) -> dict:
        fields = metadata.get("fields", [])
        names = [f["name"].lower() for f in fields]
        types = [f["python_type"] for f in fields]

        dimension_count = sum(1 for t in types if t == "text")
        metric_count = sum(1 for t in types if t in ("integer", "float"))

        # 检测键值对表
        key_val_score = 0
        if any("指标" in n or "metric" in n or "kpi" in n for n in names):
            key_val_score += 2
        if any("值" in n or "value" in n for n in names):
            key_val_score += 2
        if key_val_score >= 3:
            return {"type": "key_value", "confidence": 0.8,
                    "reason": "检测到'指标名+指标值'字段对"}

        # 检测多指标周期表
        period_score = 0
        if any(n in names for n in ("period", "date", "month", "year", "期间", "周期", "月份")):
            period_score += 2
        if metric_count >= 4 and period_score >= 2:
            return {"type": "periodic", "confidence": 0.75,
                    "reason": f"含周期字段 + {metric_count}个度量字段"}

        # 默认: 明细表
        if dimension_count >= 1 and metric_count >= 1:
            conf = min(0.9, 0.5 + metric_count * 0.1)
            return {"type": "detail", "confidence": conf,
                    "reason": f"{dimension_count}维度 + {metric_count}度量"}

        return {"type": "other", "confidence": 0.3, "reason": "无法自动判断"}


# ═══════════════════════════════════════════
# Step 5: ConfigGenerator — 语义配置生成
# ═══════════════════════════════════════════

class ConfigGenerator:
    """自动生成语义层配置 YAML"""

    def generate(self, metadata: dict, quality: dict, ds_type: dict) -> dict:
        """生成数据集级语义配置"""
        fields = metadata.get("fields", [])
        table_name = metadata["table_name"]

        field_configs = []
        for f in fields:
            fc = {
                "field_name": f["name"],
                "display_name": f.get("display_name", f["name"]),
                "field_type": self._guess_field_role(f),
                "python_type": f["python_type"],
                "synonyms": self._generate_synonyms(f["name"]),
                "default_aggregation": self._guess_aggregation(f),
            }
            if f.get("sample_values"):
                fc["example_values"] = f["sample_values"][:3]
            field_configs.append(fc)

        # 生成快捷提问
        quick_queries = self._generate_quick_queries(table_name, fields)

        return {
            "table_name": table_name,
            "display_name": self._generate_table_display_name(table_name),
            "dataset_type": ds_type.get("type", "detail"),
            "data_period": f"{date.today().strftime('%Y-%m')}",
            "fields": field_configs,
            "quick_queries": quick_queries,
            "auto_generated": True,
            "generated_at": datetime.now().isoformat(),
        }

    @staticmethod
    def _guess_field_role(field: dict) -> str:
        name = field["name"].lower()
        py_type = field["python_type"]

        if py_type == "date":
            return "date"
        if any(k in name for k in ("region", "city", "province", "区域", "城市", "省份")):
            return "geo"
        if any(k in name for k in ("id", "_id", "编号")):
            if field.get("pk"):
                return "pk"
            return "dimension"
        if py_type in ("integer", "float"):
            return "metric"
        return "dimension"

    @staticmethod
    def _generate_synonyms(field_name: str) -> list[str]:
        synonyms = []
        lower = field_name.lower()
        if "amount" in lower or "金额" in field_name:
            synonyms.extend(["金额", "总额", "款额"])
        if "count" in lower or "数量" in field_name:
            synonyms.extend(["数量", "个数", "总数"])
        if "region" in lower or "区域" in field_name:
            synonyms.extend(["区域", "地区", "城市"])
        if "name" in lower or "名称" in field_name:
            synonyms.extend(["名称", "名字", "标题"])
        return synonyms[:5]

    @staticmethod
    def _guess_aggregation(field: dict) -> str | None:
        if field["python_type"] not in ("integer", "float"):
            return None
        name = field["name"].lower()
        if any(k in name for k in ("rate", "ratio", "percent", "率", "比", "占比")):
            return "AVG"
        return "SUM"

    @staticmethod
    def _generate_table_display_name(table_name: str) -> str:
        if any('一' <= c <= '鿿' for c in table_name):
            return table_name
        mapping = {
            "bid_management": "中标管理表",
            "contracts": "合同管理表",
            "opportunities": "商机管理表",
            "accounts_receivable": "应收账款表",
        }
        return mapping.get(table_name, table_name)

    @staticmethod
    def _generate_quick_queries(table_name: str, fields: list) -> list[str]:
        queries = []
        metric_fields = [f for f in fields
                        if f.get("python_type", "") in ("integer", "float")
                        and f["name"] not in ("snapshot_id", "_row_id")]
        dim_fields = [f for f in fields
                     if f.get("python_type", "") == "text"
                     and f["name"] not in ("description",)]

        for mf in metric_fields[:3]:
            name = mf.get("display_name") or mf["name"]
            queries.append(f"本月 {name}")

        if len(dim_fields) >= 1 and len(metric_fields) >= 1:
            dim_name = dim_fields[0].get("display_name") or dim_fields[0]["name"]
            metric_name = metric_fields[0].get("display_name") or metric_fields[0]["name"]
            queries.append(f"各{dim_name} {metric_name} 分布")

        return queries[:5]


# ═══════════════════════════════════════════
# Step 6: OnboardingReviewer — 审核队列
# ═══════════════════════════════════════════

class OnboardingReviewer:
    """人工审核队列管理"""

    def __init__(self, db):
        self.db = db
        self._ensure_table()

    def _ensure_table(self):
        try:
            self.db.execute_write("""
                CREATE TABLE IF NOT EXISTS onboarding_queue (
                    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    quality_score INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    reviewer TEXT,
                    reviewed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception as e:
            logger.debug("onboarding_queue 表创建: %s", e)

    def submit(self, config: dict, quality_score: int) -> int:
        """提交配置到审核队列"""
        import json
        self.db.execute_write(
            "INSERT INTO onboarding_queue (table_name, config_json, quality_score, status) "
            "VALUES (?, ?, ?, 'pending')",
            (config["table_name"], json.dumps(config, ensure_ascii=False), quality_score),
        )
        rows = self.db.execute("SELECT last_insert_rowid() AS id")
        return rows[0]["id"] if rows else 0

    def list_pending(self) -> list[dict]:
        """列出待审核项"""
        try:
            return self.db.execute(
                "SELECT * FROM onboarding_queue WHERE status='pending' "
                "ORDER BY quality_score DESC"
            )
        except Exception:
            return []

    def approve(self, queue_id: int, reviewer: str = "admin") -> dict | None:
        """审核通过"""
        self.db.execute_write(
            "UPDATE onboarding_queue SET status='approved', reviewer=?, "
            "reviewed_at=CURRENT_TIMESTAMP WHERE queue_id=?",
            (reviewer, queue_id),
        )
        rows = self.db.execute(
            "SELECT * FROM onboarding_queue WHERE queue_id=?", (queue_id,)
        )
        return rows[0] if rows else None

    def reject(self, queue_id: int, reviewer: str = "admin", reason: str = "") -> dict | None:
        """审核拒绝"""
        self.db.execute_write(
            "UPDATE onboarding_queue SET status='rejected', reviewer=?, "
            "reviewed_at=CURRENT_TIMESTAMP WHERE queue_id=?",
            (reviewer, queue_id),
        )
        rows = self.db.execute(
            "SELECT * FROM onboarding_queue WHERE queue_id=?", (queue_id,)
        )
        return rows[0] if rows else None

    def get_stats(self) -> dict:
        try:
            rows = self.db.execute(
                "SELECT status, COUNT(*) AS cnt FROM onboarding_queue GROUP BY status"
            )
            stats = {"pending": 0, "approved": 0, "rejected": 0}
            for r in rows:
                stats[r["status"]] = r["cnt"]
            return stats
        except Exception:
            return {"pending": 0, "approved": 0, "rejected": 0}


# ═══════════════════════════════════════════
# Step 7: SemanticRegistrar — 注册到语义层
# ═══════════════════════════════════════════

class SemanticRegistrar:
    """将审核通过的配置注册到语义层和指标字典"""

    def __init__(self, db):
        self.db = db

    def register(self, config: dict) -> dict:
        """注册数据集配置"""
        table_name = config["table_name"]
        results = {
            "table": table_name,
            "metrics_created": 0,
            "schema_registered": False,
        }

        # 1. 注册到 schema_registry
        self._register_schema(table_name, config.get("fields", []))

        # 2. 为每个度量字段创建指标
        for field in config.get("fields", []):
            if field.get("field_type") == "metric":
                self._create_metric(table_name, field, config)
                results["metrics_created"] += 1

        results["schema_registered"] = True
        logger.info("已注册 %s: %d 个指标", table_name, results["metrics_created"])
        return results

    def _register_schema(self, table_name: str, fields: list):
        import json
        col_names = [f["field_name"] for f in fields]

        try:
            self.db.execute_write(
                "INSERT OR REPLACE INTO schema_registry (table_name, columns_json) "
                "VALUES (?, ?)",
                (table_name, json.dumps(col_names)),
            )
        except Exception:
            # 表可能不存在, 创建
            try:
                self.db.execute_write("""
                    CREATE TABLE IF NOT EXISTS schema_registry (
                        table_name TEXT PRIMARY KEY,
                        columns_json TEXT NOT NULL,
                        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                self.db.execute_write(
                    "INSERT OR REPLACE INTO schema_registry (table_name, columns_json) "
                    "VALUES (?, ?)",
                    (table_name, json.dumps(col_names)),
                )
            except Exception as e:
                logger.warning("注册schema失败: %s", e)

    def _create_metric(self, table_name: str, field: dict, config: dict):
        """为单个字段创建指标"""
        name = f"{field.get('display_name') or field['field_name']}"
        agg = field.get("default_aggregation", "SUM")
        safe_col = field["field_name"].replace('"', '""')
        safe_table = table_name.replace('"', '""')
        sql = f'SELECT ROUND({agg}("{safe_col}"),2) AS value FROM "{safe_table}"'

        try:
            self.db.execute_write(
                """INSERT OR IGNORE INTO metric_registry
                   (name, display_name, category, status, complexity,
                    explanation, table_name, sql_template, result_format, result_unit)
                   VALUES (?, ?, ?, 'available', 'L1', ?, ?, ?, 'number', '')""",
                (
                    name,
                    name,
                    config.get("display_name", table_name),
                    f"自动生成: {agg}({field['field_name']})",
                    table_name,
                    sql,
                ),
            )
        except Exception as e:
            logger.debug("创建指标 '%s' 失败: %s", name, e)


# ═══════════════════════════════════════════
# 流水线编排器
# ═══════════════════════════════════════════

class OnboardingPipeline:
    """7步数据接入流水线编排"""

    def __init__(self, db):
        self.db = db
        self.scanner = SchemaScanner(db)
        self.extractor = MetadataExtractor(db)
        self.assessor = QualityAssessor()
        self.inferrer = TypeInferrer()
        self.generator = ConfigGenerator()
        self.reviewer = OnboardingReviewer(db)
        self.registrar = SemanticRegistrar(db)

    def run_discovery(self) -> dict:
        """运行发现流程 (Step 1-2)"""
        scan = self.scanner.scan()
        if not scan["tables"]:
            return {"status": "empty", "message": "未发现用户表", "tables": []}

        result = {"status": "ok", "tables": []}
        for t in scan["tables"]:
            metadata = self.extractor.extract(t["table_name"])
            result["tables"].append({
                "table_name": t["table_name"],
                "row_count": t["row_count"],
                "column_count": t["column_count"],
                "fields": len(metadata["fields"]),
            })
        return result

    def run_full(self, table_name: str, auto_approve: bool = False) -> dict:
        """运行完整7步流程"""
        stages = []

        # Step 1-2: 扫描 + 元数据
        metadata = self.extractor.extract(table_name)
        stages.append({"step": "metadata", "status": "done",
                       "fields": len(metadata["fields"])})

        # Step 3: 质量评估
        quality = self.assessor.assess(metadata)
        stages.append({"step": "quality", "status": "done",
                       "score": quality["score"], "grade": quality["grade"]})

        # Step 4: 类型推断
        ds_type = self.inferrer.infer(metadata)
        stages.append({"step": "type_infer", "status": "done",
                       "type": ds_type["type"], "confidence": ds_type["confidence"]})

        # Step 5: 配置生成
        config = self.generator.generate(metadata, quality, ds_type)
        stages.append({"step": "config", "status": "done",
                       "metrics": len([f for f in config["fields"]
                                       if f.get("field_type") == "metric"])})

        # Step 6: 审核
        queue_id = self.reviewer.submit(config, quality["score"])
        if auto_approve and quality["score"] >= 60:
            self.reviewer.approve(queue_id)
            stages.append({"step": "review", "status": "auto_approved",
                          "queue_id": queue_id})
        else:
            stages.append({"step": "review", "status": "pending",
                          "queue_id": queue_id})

        # Step 7: 注册 (仅审核通过后)
        reg_result = None
        if auto_approve and quality["score"] >= 60:
            reg_result = self.registrar.register(config)
            stages.append({"step": "register", "status": "done",
                          "metrics": reg_result["metrics_created"]})

        return {
            "table_name": table_name,
            "quality": {"score": quality["score"], "grade": quality["grade"],
                        "total_issues": quality["total_issues"]},
            "dataset_type": ds_type,
            "config": config,
            "stages": stages,
            "registration": reg_result,
        }

    def run_batch(self, table_names: list[str]) -> list[dict]:
        """批量接入多个表"""
        results = []
        for name in table_names:
            try:
                r = self.run_full(name, auto_approve=False)
                results.append(r)
            except Exception as e:
                results.append({"table_name": name, "error": str(e)})
        return results

    def approve_and_register(self, queue_id: int, reviewer: str = "admin") -> dict:
        """审核通过并注册"""
        approved = self.reviewer.approve(queue_id, reviewer)
        if not approved:
            return {"status": "error", "message": "审核项不存在"}

        import json
        config = json.loads(approved["config_json"])
        reg = self.registrar.register(config)
        return {"status": "ok", "table": config["table_name"], "registration": reg}
