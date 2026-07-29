"""文件导入逻辑 — 从 MVP 迁移并增强"""

import re
from datetime import date
from pathlib import Path

import openpyxl

from ..core.logging import get_logger

logger = get_logger(__name__)


def import_excel(filepath: str, db, user: dict) -> dict:
    """
    导入 Excel 文件:
    1. 自动检测表头和列类型
    2. 去重检测 (table_name + data_period)
    3. 建表 + 导入数据
    4. 注册到 data_snapshots
    5. 自动生成指标
    """
    wb = openpyxl.load_workbook(filepath, data_only=True)
    sheets_result = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))

        if not rows:
            continue

        # 检测表头位置
        header_row_idx = _detect_header(rows)
        if header_row_idx is None:
            sheets_result.append({"sheet": sheet_name, "status": "skipped", "reason": "未检测到表头"})
            continue

        headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[header_row_idx])]
        data_rows = rows[header_row_idx + 1:]

        if not data_rows:
            sheets_result.append({"sheet": sheet_name, "status": "skipped", "reason": "无数据行"})
            continue

        # 生成表名
        table_name = _safe_table_name(sheet_name)

        # 推断列类型
        col_types = _infer_column_types(headers, data_rows)

        # 推断数据期间
        data_period = _infer_period(data_rows, col_types)

        # 去重检测
        existing = db.execute_one(
            "SELECT snapshot_id FROM data_snapshots WHERE table_name = ? AND data_period = ?",
            (table_name, data_period),
        )
        if existing:
            sheets_result.append({
                "sheet": sheet_name, "table_name": table_name, "status": "skipped",
                "reason": f"数据已存在 (snapshot #{existing['snapshot_id']})",
            })
            continue

        # 建表
        _create_table(db, table_name, headers, col_types)

        # 导入数据
        count = _import_data(db, table_name, headers, data_rows, col_types)

        # 注册快照
        snapshot_id = db.insert_and_get_id(
            "INSERT INTO data_snapshots (table_name, data_period, ingestion_time, description, total_rows, uploaded_by) "
            "VALUES (?, ?, datetime('now'), ?, ?, ?)",
            (table_name, data_period, f"{sheet_name} - {data_period}", count, user["user_id"]),
        )

        # 更新 snapshot_id
        db.execute_write(
            f"UPDATE \"{table_name}\" SET snapshot_id = ? WHERE snapshot_id = 0",
            (snapshot_id,),
        )

        # 自动生成指标
        metrics_count = 0
        try:
            metrics_count = _auto_generate_metrics(db, table_name, headers, col_types)
        except Exception as e:
            logger.warning("指标生成失败: %s", e)

        # 自动注册KB同义词 (仅第一次导入时)
        if metrics_count > 0:
            try:
                _auto_register_kb_synonyms(headers, col_types)
            except Exception as e:
                logger.warning("KB同义词注册失败: %s", e)

        sheets_result.append({
            "sheet": sheet_name, "table_name": table_name, "status": "imported",
            "data_period": data_period, "row_count": count, "columns": len(headers),
            "snapshot_id": snapshot_id,
            "metrics_generated": metrics_count,
        })

    wb.close()

    # 刷新指标加载器
    try:
        from ...semantic.loader import MetricLoader
        MetricLoader(db).reload()
    except Exception:
        pass

    return {
        "type": "import_result",
        "sheets": sheets_result,
        "total_imported": sum(1 for s in sheets_result if s["status"] == "imported"),
        "total_skipped": sum(1 for s in sheets_result if s["status"] == "skipped"),
    }


def _detect_header(rows: list) -> int | None:
    """检测表头行: 前10行中第一个含2+非空单元格的行"""
    for i in range(min(10, len(rows))):
        non_empty = sum(1 for v in rows[i] if v is not None and str(v).strip())
        if non_empty >= 2:
            return i
    return None


def _safe_table_name(name: str) -> str:
    """去除特殊字符, 转蛇形命名"""
    name = re.sub(r'[^\w一-鿿]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name or "imported_table"


def _infer_column_types(headers: list, data_rows: list) -> dict:
    """推断列类型: DATE / REAL / INTEGER / TEXT"""
    types = {}
    for i, h in enumerate(headers):
        samples = [row[i] for row in data_rows[:20] if i < len(row) and row[i] is not None]
        if not samples:
            types[h] = "TEXT"
            continue

        # 尝试将字符串转为数字
        def try_num(v):
            if isinstance(v, (int, float)): return v
            if isinstance(v, str):
                try: return int(v)
                except: pass
                try: return float(v)
                except: pass
            return v

        # 检测日期
        date_count = sum(1 for v in samples if isinstance(v, (date,)) or
                         (isinstance(v, str) and re.match(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', str(v))))
        if date_count > len(samples) * 0.5:
            types[h] = "DATE"
            continue

        # 检测数字 (含字符串数字)
        nums = [try_num(v) for v in samples]
        num_count = sum(1 for v in nums if isinstance(v, (int, float)))
        if num_count == len(samples):
            if all(isinstance(v, int) for v in nums):
                types[h] = "INTEGER"
            else:
                types[h] = "REAL"
            continue

        types[h] = "TEXT"

    return types


def _infer_period(data_rows: list, col_types: dict) -> str:
    """从日期列推断数据期间"""
    today = date.today()
    for h, t in col_types.items():
        if t == "DATE":
            dates = []
            for row in data_rows[:20]:
                val = row[list(col_types.keys()).index(h)] if h in col_types else None
                if val:
                    if isinstance(val, date):
                        dates.append(val)
                    elif isinstance(val, str):
                        m = re.match(r'(\d{4})-(\d{1,2})', val)
                        if m:
                            dates.append(date(int(m.group(1)), int(m.group(2)), 1))
            if dates:
                min_d = min(dates)
                max_d = max(dates)
                if min_d.strftime("%Y-%m") == max_d.strftime("%Y-%m"):
                    return min_d.strftime("%Y-%m")
                return f"{min_d.strftime('%Y-%m')}~{max_d.strftime('%Y-%m')}"
    return f"{today.year}-{today.month:02d}"


def _create_table(db, table_name: str, headers: list, col_types: dict):
    """创建表"""
    type_map = {"DATE": "TEXT", "REAL": "REAL", "INTEGER": "INTEGER", "TEXT": "TEXT"}
    cols = ['_row_id INTEGER PRIMARY KEY AUTOINCREMENT', 'snapshot_id INTEGER DEFAULT 0']
    for h in headers:
        safe_h = re.sub(r'[^\w一-鿿]', '_', str(h))
        cols.append(f'"{safe_h}" {type_map.get(col_types[h], "TEXT")}')

    # 如果表已存在, 删除重建
    try:
        db.execute_write(f'DROP TABLE IF EXISTS "{table_name}"')
    except Exception:
        pass

    db.execute_write(f'CREATE TABLE "{table_name}" ({", ".join(cols)})')


def _import_data(db, table_name: str, headers: list, data_rows: list, col_types: dict) -> int:
    """导入数据"""
    safe_headers = [re.sub(r'[^\w一-鿿]', '_', str(h)) for h in headers]
    placeholders = ','.join(['?'] * (len(headers) + 1))
    cols = ','.join(['snapshot_id'] + [f'"{h}"' for h in safe_headers])

    count = 0
    for row in data_rows:
        values = [0]  # snapshot_id = 0, 后续更新
        for i, h in enumerate(headers):
            val = row[i] if i < len(row) else None
            if val is None:
                values.append(None)
            elif col_types[h] == "DATE":
                if isinstance(val, date):
                    values.append(val.strftime("%Y-%m-%d"))
                else:
                    values.append(str(val))
            else:
                values.append(val)

        try:
            db.execute_write(f'INSERT INTO "{table_name}" ({cols}) VALUES ({placeholders})', tuple(values))
            count += 1
        except Exception:
            pass

    return count


def _humanize_metric_name(col_name: str, agg: str) -> str:
    """生成人性化指标名: '合同金额(万元)' + '合计' → '合同金额 合计'"""
    # 去掉括号中的单位: 合同金额(万元) → 合同金额
    clean = re.sub(r'\([^)]*\)', '', col_name).strip()
    # 去掉下划线残留
    clean = re.sub(r'_+', ' ', clean).strip()
    if not clean:
        clean = col_name
    return f"{clean} {agg}"


def _auto_generate_metrics(db, table_name: str, headers: list, col_types: dict) -> int:
    """自动生成指标: 每个数值列生成合计/平均, 人性化命名"""
    count = 0
    safe_headers = [re.sub(r'[^\w一-鿿]', '_', str(h)) for h in headers]

    for i, h in enumerate(headers):
        safe_h = safe_headers[i]
        if col_types[h] in ("REAL", "INTEGER"):
            clean_name = _humanize_metric_name(h, "").strip()

            # 合计 (不同表同名指标自动跳过)
            metric_name = f"{clean_name} 合计"
            sql_sum = f'SELECT ROUND(SUM("{safe_h}"), 2) AS value FROM "{table_name}"'
            if not db.execute_one("SELECT 1 FROM metric_registry WHERE name=?", (metric_name,)):
                try:
                    db.execute_write(
                        "INSERT INTO metric_registry (name, display_name, category, status, complexity, table_name, sql_template, result_format, result_unit) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (metric_name, clean_name, "自动生成", "available", "L1",
                         table_name, sql_sum, "number", h),
                    )
                    count += 1
                except Exception as e:
                    logger.warning("指标生成(合计)失败: %s", e)

            # 平均
            metric_name = f"{clean_name} 平均"
            sql_avg = f'SELECT ROUND(AVG("{safe_h}"), 2) AS value FROM "{table_name}"'
            if not db.execute_one("SELECT 1 FROM metric_registry WHERE name=?", (metric_name,)):
                try:
                    db.execute_write(
                        "INSERT INTO metric_registry (name, display_name, category, status, complexity, table_name, sql_template, result_format, result_unit) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (metric_name, clean_name, "自动生成", "available", "L1",
                         table_name, sql_avg, "number", h),
                    )
                    count += 1
                except Exception as e:
                    logger.warning("指标生成(平均)失败: %s", e)

    return count


def _auto_register_kb_synonyms(headers: list, col_types: dict):
    """自动将列名注册为企业知识库同义词"""
    import yaml
    from pathlib import Path

    kb_path = Path(__file__).parent.parent.parent / "metrics" / "enterprise_kb.yaml"
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = yaml.safe_load(f) or {}
    except Exception:
        kb = {}

    synonyms = kb.get("synonyms", {})
    if synonyms is None:
        synonyms = {}

    added = 0
    for h in headers:
        if col_types.get(h) in ("REAL", "INTEGER"):
            clean = _humanize_metric_name(h, "").strip()
            # 多种口语变体 → 指标名
            variants = [
                clean,
                h.replace('(', '').replace(')', ''),
                re.sub(r'\([^)]*\)', '', h).strip(),
            ]
            for v in variants:
                v2 = v.strip()
                if v2 and v2 not in synonyms:
                    # SUM variants
                    synonyms[v2] = f"{clean} 合计"
                    synonyms[f"{v2}合计"] = f"{clean} 合计"
                    synonyms[f"{v2}总和"] = f"{clean} 合计"
                    synonyms[f"{v2}总额"] = f"{clean} 合计"
                    # AVG variants
                    synonyms[f"{v2}平均"] = f"{clean} 平均"
                    synonyms[f"{v2}均值"] = f"{clean} 平均"
                    added += 1

    if added > 0:
        kb["synonyms"] = synonyms
        with open(kb_path, "w", encoding="utf-8") as f:
            yaml.dump(kb, f, allow_unicode=True, default_flow_style=False)
        logger.info("已注册 %d 个KB同义词到 %s", added, kb_path)
