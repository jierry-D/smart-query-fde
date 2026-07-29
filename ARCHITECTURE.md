# 智慧问数系统 v2.0 — 架构文档

> 企业级 NL2SQL 智能数据查询平台 | 24 commits | 123 tests | 30 API

---

## 一、系统分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    前端 SPA (独立部署)                        │
│              frontend/index.html + js/ + css/                │
│  仪表盘 │ 智能问数 │ 指标目录 │ 数据管理 │ 导入 │ 管理后台    │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP REST (JWT Bearer Token)
                         │ 30 API Endpoints
┌────────────────────────┴────────────────────────────────────┐
│                    L5: API 层                                │
│   backend/app/api/routers/                                   │
│   auth | chat | metrics | snapshots | admin | feedback       │
│   import_route | export_csv | dashboard | history            │
├─────────────────────────────────────────────────────────────┤
│                    L4: 引擎层 (8-Stage Pipeline)              │
│   backend/app/engine/                                        │
│   pipeline.py         → 编排器 (NL2SQLPipeline)              │
│   stage0_preflight.py → 数据预检                             │
│   ner_engine.py       → NER 实体提取 (Stage 1)               │
│   stage_kb.py         → 知识库增强 (Stage 1.2)               │
│   stage_clarify.py    → 反问澄清 (Stage 1.5)                 │
│   time_resolver.py    → 时间解析 (Stage 2)                   │
│   sql_filter.py       → SQL 动态注入                         │
│   time_intelligence.py→ 同比/环比计算                        │
├─────────────────────────────────────────────────────────────┤
│                    L3: 语义层                                 │
│   backend/app/semantic/                                      │
│   loader.py          → 指标加载/匹配 (4层策略)               │
│   kb_resolver.py     → 三级知识库 (数据集>业务域>企业)       │
│   vector_store.py    → ChromaDB 向量检索                     │
├─────────────────────────────────────────────────────────────┤
│                    L2: 治理层 (5层防护)                       │
│   backend/app/governance/                                    │
│   __init__.py        → GovernanceManager (统一入口)          │
│   layer1_auth.py     → RBAC 权限 + 数据范围                  │
│   layer2_sql.py      → SQL 安全 (DDL/DML拦截)                │
│   layer3_resource.py → 资源预估 (EXPLAIN)                    │
│   layer4_exec.py     → 熔断保护                              │
│   layer5_cache.py    → LRU 结果缓存                          │
│   feedback_analyzer.py → 反馈→知识库建议                     │
├─────────────────────────────────────────────────────────────┤
│                    L1: 数据层                                 │
│   backend/app/database.py    → SQLite/PostgreSQL 抽象        │
│   backend/app/onboarding/    → Excel导入 + 7步接入流水线     │
│   backend/db/init_db.py      → 数据库初始化 (2种模式)        │
├─────────────────────────────────────────────────────────────┤
│                 横切模块                                      │
│   backend/app/core/    → JWT/日志/配置/依赖注入               │
│   backend/app/llm/     → DeepSeek Provider (可选增强)         │
│   backend/app/schemas/ → Pydantic 请求/响应模型               │
│   backend/metrics/     → 企业知识库 YAML                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、NL2SQL 查询流水线

```
用户输入: "年度累计中标总额"
    │
    ▼
┌──────────────────────────────────────────────┐
│ Stage 0: 数据预检 (stage0_preflight.py)       │
│  ├─ 数据新鲜度 (最后更新>30天告警)             │
│  ├─ 指标可用性 (pending状态提示)               │
│  └─ 时间范围提示 (未指定时建议添加)            │
├──────────────────────────────────────────────┤
│ Stage 1: NER 实体提取 (ner_engine.py)         │
│  输入: 自然语言字符串                          │
│  输出: {filters, intent, group_by, order,     │
│          limit, metric_hint, completeness}    │
│  ├─ 维度筛选: AC自动机匹配区域/业务线          │
│  ├─ 意图识别: 正则匹配聚合/排名/分布/趋势      │
│  ├─ 分组/排序: 正则提取 group_by/order/limit  │
│  └─ 完整性评分: time(0.3)+metric(0.4)+dim(0.3)│
├──────────────────────────────────────────────┤
│ Stage 1.2: 知识库增强 (stage_kb.py)           │
│  ├─ 同义词扩展: 指标hint → KB映射 → 标准指标名 │
│  └─ 业务逻辑: 术语 → SQL条件 (如"大额订单")    │
├──────────────────────────────────────────────┤
│ Stage 1.5: 反问澄清 (stage_clarify.py)        │
│  ├─ ≤3字符 → 引导使用命令                     │
│  ├─ 缺时间+维度 → 反问时间范围                 │
│  ├─ KB命中 → 跳过反问                         │
│  └─ 分布/排名意图 → 跳过反问                   │
├──────────────────────────────────────────────┤
│ Stage 2: 时间解析 (time_resolver.py)          │
│  输入: 查询 + 快照列表                         │
│  输出: (cleaned_query, snapshot_ids, label,   │
│          time_intelligence)                    │
│  ├─ 绝对时间: Q1-Q4/月份/半年                  │
│  ├─ 相对时间: 本月/上月/本季/YTD/YoY/MoM      │
│  └─ 智能默认: 无时间词→最新快照                │
├──────────────────────────────────────────────┤
│ Stage 3: 指标匹配 (semantic/loader.py)         │
│  4层策略: 精确→向量→包含→模糊                  │
│  多轮搜索合并, 同分tiebreaker                   │
│  NER分组意图 → 表格型指标加权(+0.05)           │
│  KB同义词 → 放宽模糊门槛(score≥0.7)            │
├──────────────────────────────────────────────┤
│ Stage 4: SQL 生成                              │
│  ├─ 模板: 高置信度(≥0.8)直接用SQL模板          │
│  ├─ LLM增强: 低置信度+LLM可用 → 优化SQL        │
│  ├─ NER注入: filters→WHERE/group→GROUP BY      │
│  └─ KB注入: 业务逻辑条件→WHERE                  │
├──────────────────────────────────────────────┤
│ Stage 5: 治理检查 (governance/)                │
│  Layer 1: RBAC数据范围注入                      │
│  Layer 2: SQL安全检查 (DDL/DML/敏感字段)        │
│  Layer 5: 缓存命中 → 直接返回 (跳过3-4)         │
│  Layer 3: 资源预估 (扫描行>50万拒绝)            │
│  Layer 4: 熔断保护 (连续5次失败→30秒熔断)       │
├──────────────────────────────────────────────┤
│ Stage 6: SQL 执行                              │
│  ├─ 单快照: WHERE snapshot_id=N               │
│  └─ 多快照: UNION ALL + 外层聚合               │
├──────────────────────────────────────────────┤
│ Stage 7: 响应构建                              │
│  ├─ 数值卡: type=number, value, unit, SQL     │
│  ├─ 表格: type=table, columns, rows           │
│  ├─ 解释: explanation + formula                │
│  └─ 趋势: 自动环比 (_auto_mom跨表对比)         │
└──────────────────────────────────────────────┘
    │
    ▼
  返回: {type, metric_name, value, explanation,
         formula, time_intelligence, sql, process}
```

---

## 三、目录结构

```
smart-query-v2/
│
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 应用工厂
│   │   ├── config.py            # YAML + 环境变量配置
│   │   ├── database.py          # 数据库抽象层 (SQLite/PostgreSQL)
│   │   │
│   │   ├── api/routers/         # L5: API层
│   │   │   ├── auth.py          # 登录/刷新/me (3 endpoints)
│   │   │   ├── chat.py          # 查询/命令/导出/仪表盘/历史 (5)
│   │   │   ├── metrics.py       # 指标CRUD (4)
│   │   │   ├── snapshots.py     # 快照浏览 (2)
│   │   │   ├── admin.py         # 用户/日志/统计/接入/建议 (11)
│   │   │   ├── feedback.py      # 反馈提交 (1)
│   │   │   └── import_route.py  # Excel上传 (1)
│   │   │
│   │   ├── engine/              # L4: 引擎层
│   │   │   ├── pipeline.py      # NL2SQLPipeline (8-Stage编排)
│   │   │   ├── stage0_preflight.py
│   │   │   ├── ner_engine.py    # 纯规则NER
│   │   │   ├── stage_kb.py      # 知识库增强
│   │   │   ├── stage_clarify.py # 反问澄清
│   │   │   ├── time_resolver.py # 20+时间模式
│   │   │   ├── sql_filter.py    # NER→SQL注入
│   │   │   └── time_intelligence.py
│   │   │
│   │   ├── semantic/            # L3: 语义层
│   │   │   ├── loader.py        # 4层指标匹配 + 向量检索
│   │   │   ├── kb_resolver.py   # 三级知识库
│   │   │   └── vector_store.py  # ChromaDB (可选降级)
│   │   │
│   │   ├── governance/          # L2: 治理层
│   │   │   ├── __init__.py      # GovernanceManager
│   │   │   ├── layer1_auth.py
│   │   │   ├── layer2_sql.py
│   │   │   ├── layer3_resource.py
│   │   │   ├── layer4_exec.py
│   │   │   ├── layer5_cache.py
│   │   │   └── feedback_analyzer.py
│   │   │
│   │   ├── onboarding/          # L1: 数据接入
│   │   │   ├── pipeline.py      # 7步接入流水线 (6个算子类)
│   │   │   └── importer.py      # Excel导入引擎
│   │   │
│   │   ├── llm/                 # LLM 抽象 (可选)
│   │   │   ├── base.py          # LLMProvider 接口
│   │   │   ├── deepseek.py      # DeepSeek 实现
│   │   │   ├── router.py        # 模型路由 (L1-L4)
│   │   │   └── prompts.py       # Jinja2 模板管理
│   │   │
│   │   ├── core/                # 横切基础设施
│   │   │   ├── security.py      # JWT/bcrypt/RBAC
│   │   │   ├── deps.py          # FastAPI 依赖注入
│   │   │   ├── config.py        # 配置管理
│   │   │   └── logging.py       # 结构化日志
│   │   │
│   │   └── schemas/             # Pydantic 模型
│   │       └── __init__.py
│   │
│   ├── db/
│   │   └── init_db.py           # 数据库初始化 (2种模式)
│   │
│   ├── metrics/
│   │   ├── enterprise_kb.yaml   # 企业知识库 (自动维护)
│   │   └── dataset_kb/          # 数据集级知识库
│   │
│   ├── prompts/                 # LLM 提示模板
│   │   └── sql_generator.md
│   │
│   └── tests/                   # 123 tests
│       ├── conftest.py          # 隔离SQLite夹具
│       ├── test_core.py         # 核心模块 (17)
│       ├── test_e2e.py          # 端到端 (18)
│       ├── test_ner_engine.py   # NER+SQL过滤 (22)
│       ├── test_governance.py   # 五层治理 (11)
│       ├── test_onboarding.py   # 数据接入 (10)
│       ├── test_negative.py     # 负向测试 (22)
│       └── test_functional.py   # 功能测试 (23)
│
├── frontend/                    # 独立SPA (零框架)
│   ├── index.html               # 单页应用入口
│   ├── css/style.css            # 企业级样式 (含响应式)
│   └── js/app.js                # 前端逻辑
│
├── config.yaml                  # 全局配置
├── Dockerfile                   # 容器化
├── docker-compose.yml           # 后端 + ChromaDB
├── .env.example                 # 环境变量模板
├── .gitignore
└── ARCHITECTURE.md              # 本文档
```

---

## 四、数据库表结构

```
users                    # 用户 (RBAC: admin/leader/employee)
refresh_tokens           # JWT 刷新令牌
user_data_permissions    # 行级数据权限
data_snapshots           # 快照元数据 (table_name+data_period唯一)
metric_registry          # 指标注册表 (name唯一, status=pending/available)
query_logs               # 查询审计日志
query_feedback           # 用户反馈 (👍/👎)
audit_logs               # 系统审计日志
onboarding_queue         # 数据接入审核队列
schema_registry          # 已注册表schema
kb_suggestions           # 反馈驱动的知识库建议
```

---

## 五、关键设计决策

| 决策 | 原因 |
|------|------|
| **LLM 可选** | 无API Key时用模板, 不影响核心功能 |
| **模板优先+LLM增强** | 高置信度用模板(快+准), 低置信度LLM兜底 |
| **前后端完全分离** | 仅通过REST API通信, 可独立部署 |
| **双时间维度** | data_period(业务时间) + ingestion_time(录入时间) |
| **去重检测** | table_name + data_period UNIQUE约束 |
| **2种数据库模式** | `init_db.py` 空白框架 / `--demo` CRM演示 |
| **自动指标连接** | 关键词匹配→自动生成SQL→pending→available |
| **KB自动注册** | 导入时自动将列名注册为同义词 |
| **降级设计** | ChromaDB→文本匹配, LLM→模板, PostgreSQL→SQLite |

---

## 六、数据接入流水线 (7步)

```
1. SchemaScanner     → 扫描数据库, 发现用户表
2. MetadataExtractor → 提取字段名/类型/示例值/外键
3. QualityAssessor   → 8项质量检查, 0-100评分
4. TypeInferrer      → 推断数据集类型 (明细/周期/键值对)
5. ConfigGenerator   → 自动生成语义配置 + 快捷提问
6. OnboardingReviewer→ 人工审核队列 (pending→approved/rejected)
7. SemanticRegistrar → 注册schema + 自动创建指标
```

---

## 七、部署

```bash
# 开发
python backend/db/init_db.py          # 空白框架
python backend/db/init_db.py --demo   # CRM演示
python -m uvicorn backend.app.main:app --port 5000

# Docker
docker-compose up                      # 后端 + ChromaDB(可选)

# 新项目接入
1. init_db.py → 空白数据库
2. 上传Excel → 自动建表+指标+KB同义词
3. 配置 enterprise_kb.yaml → 领域术语
4. 自然语言查询
```
