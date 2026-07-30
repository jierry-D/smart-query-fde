# 智慧问数系统 — 架构文档

## 系统分层

```
┌─────────────────────────────────────────────┐
│              前端 SPA (React 18)             │
│  仪表盘 │ 智能问数 │ 指标目录 │ 数据管理      │
└──────────────────┬──────────────────────────┘
                   │ REST + SSE
┌──────────────────┴──────────────────────────┐
│              API 层 (FastAPI)                │
│  auth / chat / metrics / snapshots / admin   │
├─────────────────────────────────────────────┤
│           Agent 层 (7 Agent)                 │
│  Intent → Planner → SQL → Execute → Interpret│
│          Clarify ← → Report                  │
├─────────────────────────────────────────────┤
│           引擎层 (10-Stage Pipeline)          │
│  Preflight → NER → KB → Clarify → Time       │
│  → Metric → SQL → Governance → Exec → Build  │
├─────────────────────────────────────────────┤
│              语义层                          │
│  4层指标匹配 + 3级知识库 + ChromaDB          │
├─────────────────────────────────────────────┤
│           治理层 (5层防护)                    │
│  RBAC → SQL安全 → 资源预估 → 熔断 → 缓存     │
├─────────────────────────────────────────────┤
│              数据层                          │
│  SQLite / PostgreSQL + 数据接入流水线         │
└─────────────────────────────────────────────┘
```

## Agent 体系

| Agent | 职责 |
|-------|------|
| IntentAgent | 意图分类 + NER 实体提取 + 复杂度评估 |
| PlannerAgent | 报告主题分解为子查询计划 |
| SQLAgent | SQL 生成 + 验证 + NER 注入 |
| ExecuteAgent | SQL 执行 + 治理检查 + 时间智能 |
| InterpretAgent | NL 结果解读 + 异常检测 |
| ClarifyAgent | 歧义反问澄清 |
| ReportAgent | 多维度 Markdown 报告生成 |

## 查询流水线

```
用户输入 → Stage0 预检 → Stage1 NER → Stage1.2 KB增强
→ Stage1.5 反问澄清 → Stage2 时间解析 → Stage3 指标匹配
→ Stage4 SQL生成 → Stage5 治理 → Stage6 执行 → Stage7 响应
```

## 目录结构

```
backend/
├── app/
│   ├── agents/          # 多 Agent 智能体 (7个)
│   ├── api/routers/     # REST API (7个模块)
│   ├── engine/          # NL2SQL 引擎 (10模块)
│   ├── semantic/        # 语义层 (指标+知识库+向量)
│   ├── governance/      # 五层查询治理
│   ├── llm/             # LLM抽象层 (DeepSeek)
│   ├── onboarding/      # 数据接入流水线
│   ├── core/            # JWT/日志/限流/安全
│   └── schemas/         # Pydantic 模型
├── db/
│   ├── init_db.py       # 数据库初始化 (空白/演示)
│   └── migrations/      # Alembic 迁移
├── metrics/             # 企业知识库 YAML
├── prompts/             # LLM 提示模板
└── tests/               # 128 测试用例

frontend/
├── src/
│   ├── components/      # Layout
│   ├── pages/           # 6 页面
│   ├── stores/          # Zustand 状态
│   ├── api/             # Axios 客户端
│   └── types/           # TypeScript 类型
├── public/
└── dist/                # 构建产物
```

## 数据库表

```
users / refresh_tokens        — 用户认证
data_snapshots                — 数据快照元数据 (双时间维度)
metric_registry               — 指标注册表
query_logs / query_feedback   — 查询审计 + 反馈
audit_logs                    — 系统审计
onboarding_queue              — 数据接入审核
schema_registry               — 表结构注册
kb_suggestions                — 知识库改进建议
```

## 关键设计

- **LLM 可选**：无 API Key 时用规则模板，接入后自动增强
- **Agent/Pipeline 双模式**：Agent 异常时自动回退 Pipeline
- **双时间维度**：data_period（业务时间）+ ingestion_time（录入时间）
- **降级设计**：ChromaDB→文本匹配，LLM→模板，PostgreSQL→SQLite，Redis→内存LRU
