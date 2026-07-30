# 智慧问数系统 — FDE

企业级 NL2SQL 智能数据查询框架（Framework Development Edition）。

用自然语言查询数据库，零代码接入新项目。

## 特性

- 自然语言查询：用中文直接查数据库，自动转 SQL
- 三级权限：管理员 / 领导 / 员工，数据行级隔离
- Excel 导入：上传即用，自动建表 + 生成指标
- 过程透明：展示从自然语言到 SQL 到结果的每一步
- LLM 可选：无 API Key 时基于规则模板运行，接入后自动增强
- 开箱即用：空白数据库初始化，3 步接入新项目

## 快速开始

```bash
# 1. 安装依赖
pip install -r backend/requirements.txt

# 2. 初始化空白数据库
python backend/db/init_db.py

# 3. 启动服务
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 5000

# 4. 浏览器访问
# http://127.0.0.1:5000
```

## 新项目接入

```
1. python backend/db/init_db.py     → 空白数据库
2. 浏览器上传 Excel                  → 自动建表 + 生成指标
3. 配置 enterprise_kb.yaml           → 添加业务同义词
4. 开始查询
```

## 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |

> 初始化后仅有 admin 账号，其他用户通过管理面板创建。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python / FastAPI |
| 数据库 | SQLite（默认）/ PostgreSQL（可选） |
| 前端 | React 18 + TypeScript + Ant Design 5 |
| LLM | DeepSeek（可选） |
| 向量 | ChromaDB（可选） |
| 缓存 | 内存 LRU / Redis（可选） |
| 部署 | Docker / docker-compose |

## API 文档

启动后访问: http://127.0.0.1:5000/docs

## 运行测试

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest backend/tests/ -v
```

## 项目结构

```
smart-query-fde/
├── backend/app/
│   ├── agents/        # 多 Agent 智能体
│   ├── engine/        # NL2SQL 流水线
│   ├── semantic/      # 语义层 + 知识库
│   ├── governance/    # 五层治理
│   ├── llm/           # LLM 抽象层
│   ├── onboarding/    # 数据接入
│   └── api/routers/   # REST API
├── frontend/          # React SPA
├── config.yaml        # 全局配置
└── docker-compose.yml
```

## 许可证

MIT
