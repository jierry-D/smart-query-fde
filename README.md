# 智慧问数系统 v2.0

企业级 NL2SQL 智能数据查询平台 — 自然语言 → SQL → 数据结果。

## 特性

- 🔍 **自然语言查询**: 用中文直接查询数据库，自动转 SQL
- 🔐 **三级 RBAC**: 管理员(全部数据) / 领导(部门数据) / 员工(个人数据)
- ⏰ **智能时间解析**: 支持 Q3、本月、同比、环比、YTD 等 20+ 种时间表达
- 🏷️ **NER 实体提取**: 自动识别区域、业务线、排名等筛选条件
- 📊 **多快照聚合**: UNION ALL 跨月/跨季数据自动合并
- 🎨 **过程透明**: 展示 NER → 时间解析 → 指标匹配 → SQL → 执行的每一步

## 快速开始

```bash
# 1. 安装依赖
cd smart-query-v2
pip install -r backend/requirements.txt

# 2. 初始化数据库
python3 backend/db/init_db.py

# 3. 启动服务
python3 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 5000 --reload

# 4. 打开浏览器访问
# http://127.0.0.1:5000
```

## 测试账号

| 角色 | 用户名 | 密码 | 数据范围 |
|------|--------|------|---------|
| 🔧 管理员 | admin | admin123 | 全部数据 + 管理面板 |
| 📊 领导 | leader | leader123 | 数字政务事业部 (全部区域) |
| 👤 员工 | employee | emp123 | 数字政务事业部 - 南宁市 |
| 👤 员工2 | emp_liuzhou | emp123 | 数字政务事业部 - 柳州市 |
| 📊 领导2 | leader_xinchuang | leader123 | 信创事业部 |
| 👤 员工3 | emp_xinchuang | emp123 | 信创事业部 - 南宁市 |

## API 文档

启动后访问: http://127.0.0.1:5000/docs

### 主要端点

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | /api/auth/login | 登录 | 公开 |
| GET | /api/auth/me | 当前用户信息 | 登录 |
| POST | /api/chat | NL2SQL 查询 | 登录 |
| GET | /api/metrics | 指标列表 | 登录 |
| GET | /api/snapshots | 数据快照 | 登录 |
| POST | /api/import | Excel 导入 | admin/leader |
| GET | /api/admin/users | 用户管理 | admin |
| GET | /api/admin/logs | 查询日志 | admin |
| POST | /api/feedback | 提交反馈 | 登录 |

## 查询示例

```
# 时间聚合
Q3 年度累计中标总额

# 时间 + 筛选
本月 南宁市 本期签约额

# 排名
Top 10 各地市中标额

# 同比分析
同比 商机签约转化率

# 命令
/list           → 查看所有指标
/snapshots      → 查看数据快照
/db             → 数据库状态
/help           → 使用帮助
```

## 项目结构

```
smart-query-v2/
├── backend/app/
│   ├── core/          # 安全、认证、依赖注入
│   ├── engine/        # NL2SQL 引擎 (NER/时间/SQL过滤)
│   ├── semantic/      # 语义层 (指标加载/匹配)
│   ├── llm/           # LLM 抽象层
│   ├── governance/    # 查询治理
│   ├── onboarding/    # 数据接入
│   └── api/routers/   # FastAPI 路由
├── frontend/          # 纯 HTML/CSS/JS SPA
├── config.yaml        # 全局配置
└── backend/db/        # 数据库初始化
```

## LLM 集成 (可选)

设置环境变量以启用 DeepSeek 智能 SQL 生成:

```bash
export DEEPSEEK_API_KEY=sk-xxx
```

未设置时系统使用预定义 SQL 模板，不影响基本查询功能。

## 运行测试

```bash
cd smart-query-v2
python3 -m pytest backend/tests/ -v
```
