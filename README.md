# 十方灵犀 — 金融智能对话系统

对标同花顺问财 / 东财妙想的金融多 Agent 对话系统，基于 **LangGraph** 编排，支持 **Anthropic Claude / OpenAI GPT / 阿里通义千问** 三大模型提供商，内置双轨风控、全链路可观测、Web 实时对话界面。

---

## 架构总览

```
用户输入（CLI / Web / WebSocket）
  ↓
前置风控（违禁词拦截）
  ↓
路由 Agent（三级意图识别：关键词 → LLM → 场景锁定）
  ↓
并行分发（多意图时同时调用多个 Agent）
  ├── 诊股 Agent     → 行情 / 财报 / 估值工具
  ├── 选股 Agent     → 板块 / 行业 / 筛选工具
  ├── 客服 Agent     → FAQ / 研报 RAG 检索
  └── 闲聊 Agent     → 轻量对话
  ↓
结果合并
  ↓
后置风控（投资建议过滤 + 强制风险提示）
  ↓
持久化（会话状态 + 对话历史）
  ↓
输出
```

---

## 项目结构

```
talented-financial-copilot/
├── main.py                       # CLI 入口（交互 / 演示两种模式）
├── config/
│   ├── settings.py               # 多提供商模型分层配置
│   ├── llm_factory.py            # LLM 工厂：提供商选择 + 自动降级
│   ├── prompts.py                # 全部 System Prompt
│   └── risk_rules.py             # 风控规则库
├── graph/
│   ├── state.py                  # LangGraph 全局 State 定义
│   └── workflow.py               # 13 节点 StateGraph（含异常装饰器）
├── agents/
│   ├── router_agent.py           # 路由：三级意图识别 + 场景锁定
│   ├── stock_diagnosis_agent.py  # 诊股（强工具锁，禁预测涨跌）
│   ├── stock_selection_agent.py  # 选股（禁个股推荐）
│   ├── customer_service_agent.py # 客服（强 RAG，答案 100% 溯源）
│   └── chat_agent.py             # 闲聊（轻量）
├── api/                          # Web API 层（FastAPI）
│   ├── main.py                   # FastAPI 应用入口
│   ├── schemas.py                # 请求 / 响应 Pydantic 模型
│   ├── middleware.py             # CORS 中间件
│   ├── websocket.py              # WebSocket 实时对话处理器
│   └── routes/
│       ├── chat.py               # POST /api/chat  &  POST /api/chat/stream
│       └── metrics.py            # GET  /api/metrics
├── frontend/                     # React 前端（Vite + React 18）
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/           # ChatInterface / MessageBubble / InputBar
│   │   ├── hooks/useChat.js      # SSE 流式 / REST 双模式通信
│   │   └── styles/main.css
│   ├── index.html
│   └── package.json
├── utils/
│   └── exception_handler.py      # 三级降级装饰器（complete/partial/fallback）
├── tools/
│   ├── gateway.py                # 统一工具网关：熔断 + 限流 + 注册
│   ├── financial_tools.py        # 行情 / 财报 / 估值 / 板块工具
│   ├── rag_tools.py              # FAQ / 研报 / 知识库检索
│   └── risk_tools.py             # 风控检测函数
├── risk/
│   ├── pre_filter.py             # 前置：违禁词拦截
│   └── post_filter.py            # 后置：违规话术过滤 + 免责声明
├── storage/
│   ├── session.py                # 会话状态（生产替换为 Redis）
│   └── history.py                # 对话历史（生产替换为 MongoDB）
└── observability/
    ├── tracer.py                  # 全链路结构化追踪
    └── metrics.py                 # 业务 / 性能 / 风控三类指标
```

---

## 快速开始

### 1. 配置环境变量

复制并编辑 `.env`：

```bash
cp .env.example .env
```

按需填入 API Key（至少填一个提供商）：

```env
# 选择主提供商（anthropic | openai | qwen）
LLM_PROVIDER_PRIMARY=qwen
LLM_FALLBACK_ENABLED=false

# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx

# OpenAI GPT
OPENAI_API_KEY=sk-proj-xxxxxxxx

# 阿里通义千问（DashScope）
QWEN_API_KEY=sk-xxxxxxxx
```

> **注意**：`LLM_FALLBACK_ENABLED=true` 时系统会在主提供商失败后自动尝试下一个。
> 若多个提供商使用不同 Key，请确保各字段填写正确，否则建议设为 `false`。

### 2. 安装依赖

```bash
# Python 后端（需 Anaconda Python 3.11）
/opt/anaconda3/bin/pip install -r requirements.txt

# 前端
cd frontend && npm install
```

### 3. 启动服务

**方式一：Web 界面（推荐）**

```bash
# 终端 1 — 后端
uvicorn api.main:app --reload

# 终端 2 — 前端开发服务器
cd frontend && npm run dev
```

打开浏览器访问 `http://localhost:5173`

**方式二：CLI 命令行**

```bash
# 演示模式（自动运行 5 个预设问题）
/opt/anaconda3/bin/python3 main.py --demo

# 交互模式
/opt/anaconda3/bin/python3 main.py
```

---

## Web 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 单轮 REST 对话（同步返回完整响应） |
| `POST` | `/api/chat/stream` | SSE 流式对话（token 逐步输出） |
| `WS` | `/ws/chat` | WebSocket 双向实时对话 |
| `GET` | `/api/metrics` | 实时指标（场景命中 / 延迟 / 风控拦截） |
| `GET` | `/health` | 健康检查 |

**请求示例：**

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "分析一下贵州茅台600519的基本面", "session_id": "test-001"}'
```

---

## 多模型提供商

通过 `config/llm_factory.py` 统一管理，各 Agent 无需关心底层 SDK。

| 提供商 | 路由模型 | 分析模型 | 对话模型 |
|--------|---------|---------|---------|
| Anthropic | claude-haiku-4-5 | claude-sonnet-4-6 | claude-haiku-4-5 |
| OpenAI | gpt-4o-mini | gpt-4o | gpt-4o-mini |
| 通义千问 | qwen-turbo | qwen-max | qwen-turbo |

**自动降级链**（当 `LLM_FALLBACK_ENABLED=true` 时）：

```
主提供商失败 → 第二提供商 → 第三提供商 → 抛出 RuntimeError
```

---

## 异常三级降级

`utils/exception_handler.py` 提供 `@handle_exceptions` 装饰器，应用于所有工作流节点：

| 级别 | 触发场景 | 行为 |
|------|---------|------|
| `complete` | LLM 不可用、安全违规 | 设置 `error_flag=True`，返回固定兜底语 |
| `partial` | 部分工具失败、限流 | 继续执行可用数据，回复加"部分数据不可用"提示 |
| `fallback` | 次要工具超时、JSON 解析失败 | 静默使用默认值，对用户透明 |

---

## 对话示例

| 输入 | 触发 Agent | 说明 |
|------|-----------|------|
| `分析一下贵州茅台600519的基本面` | 诊股 | 调用行情、财报、估值工具 |
| `白酒板块今天整体表现怎样` | 选股 | 调用板块数据工具 |
| `开户需要什么条件？佣金多少？` | 客服 | RAG 检索 FAQ 知识库 |
| `茅台和白酒板块分别分析一下` | 诊股 + 选股（并行） | 多意图自动拆分并行调用 |
| `你好，你能做什么` | 闲聊 | 轻量对话 |

### CLI 内置指令

| 指令 | 功能 |
|------|------|
| `/metrics` | 查看实时指标 |
| `/scene` | 查看当前会话场景 |
| `/demo` | 运行预设演示问题 |
| `/quit` | 退出 |

---

## 核心设计

### 防幻觉：强工具锁

诊股和选股 Agent 绑定金融数据工具，所有涉及具体数值的问题**强制触发工具调用**，不允许 LLM 凭空生成数字。

### 双轨风控

- **前置**：用户输入经违禁词检测，命中即拦截，不进入任何 Agent
- **后置**：输出经投资建议语义检测，违规话术替换为 `[已过滤]`，金融场景强制附加免责声明

### 场景锁定

路由 Agent 具备多轮上下文记忆。置信度低的意图自动沿用上一轮场景，避免跨场景串扰。

### 并行 Agent 调用

多意图消息通过 LangGraph 的 `Command(goto=[Send(...)])` 同时触发多个 Agent，结果在 `merge_node` 汇总后统一输出。

---

## 替换为真实数据源

当前所有数据工具为 Mock 实现，生产环境只需替换对应函数体：

| 模块 | 当前 | 替换为 |
|------|------|--------|
| `tools/financial_tools.py` | 内置字典 | Tushare / AKShare / Wind API |
| `tools/rag_tools.py` | 关键词匹配 | Milvus 向量检索 + ES 全文检索 |
| `storage/session.py` | 内存字典 | Redis |
| `storage/history.py` | 内存列表 | MongoDB |

---

## 依赖

```
# 核心
langgraph>=1.1.0
langchain-anthropic>=1.4.0
langchain-core>=1.0.0
anthropic>=0.40.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
structlog>=24.0.0

# Web API
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
websockets>=12.0

# 多模型提供商（按需安装）
langchain-openai>=0.1.1
langchain-community>=0.0.36
dashscope>=1.14.0
```

**Python 运行时**：需使用 Anaconda Python 3.11（`/opt/anaconda3/bin/python3`），系统 Python 3.14 缺少必要依赖。
