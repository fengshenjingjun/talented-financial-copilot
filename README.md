# 金融智能对话系统

对标同花顺问财 / 东财妙想的金融多 Agent 对话系统，基于 **LangGraph** 编排，**Claude** 驱动，内置双轨风控与全链路可观测。

---

## 架构总览

```
用户输入
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

## 项目结构

```
talented-financial-copilot/
├── main.py                       # 入口（交互 / 演示两种模式）
├── config/
│   ├── settings.py               # 模型分层配置
│   ├── prompts.py                # 全部 System Prompt
│   └── risk_rules.py             # 风控规则库（可动态更新）
├── graph/
│   ├── state.py                  # LangGraph 全局 State 定义
│   └── workflow.py               # 13 节点 StateGraph 编排
├── agents/
│   ├── router_agent.py           # 路由：三级意图识别 + 场景锁定
│   ├── stock_diagnosis_agent.py  # 诊股（强工具锁，禁预测涨跌）
│   ├── stock_selection_agent.py  # 选股（禁个股推荐）
│   ├── customer_service_agent.py # 客服（强 RAG，答案 100% 溯源）
│   └── chat_agent.py             # 闲聊（轻量）
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

### 1. 获取 API Key

前往 [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) 创建一个 Anthropic API Key。

### 2. 配置环境变量

在项目根目录创建 `.env` 文件：

```bash
cd /Users/macadmin/PycharmProjects/talented-financial-copilot
cp .env.example .env
```

编辑 `.env`，填入你的 Key：

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
```

### 3. 确认 Python 环境

项目依赖安装在 Anaconda 的 Python 3.11，启动前验证：

```bash
/opt/anaconda3/bin/python3 -c "import langgraph; print('环境 OK')"
```

### 4. 启动

**演示模式**（自动运行 5 个预设问题，适合首次体验）：

```bash
/opt/anaconda3/bin/python3 main.py --demo
```

**交互模式**（直接对话）：

```bash
/opt/anaconda3/bin/python3 main.py
```

可选：添加别名方便日常使用：

```bash
alias copilot="/opt/anaconda3/bin/python3 /Users/macadmin/PycharmProjects/talented-financial-copilot/main.py"
copilot          # 交互模式
copilot --demo   # 演示模式
```

---

## 对话示例

| 你输入的内容 | 触发的 Agent | 说明 |
|-------------|-------------|------|
| `分析一下贵州茅台600519的基本面` | 诊股 Agent | 调用行情、财报、估值工具 |
| `白酒板块今天整体表现怎样` | 选股 Agent | 调用板块数据工具 |
| `开户需要什么条件？佣金多少？` | 客服 Agent | RAG 检索 FAQ 知识库 |
| `茅台和白酒板块分别分析一下` | 诊股 + 选股（并行） | 多意图自动拆分并行调用 |
| `你好，你能做什么` | 闲聊 Agent | 轻量对话 |

### 内置指令

| 指令 | 功能 |
|------|------|
| `/metrics` | 查看实时指标（场景命中数 / 延迟 / 风控拦截次数） |
| `/scene` | 查看当前会话场景 |
| `/demo` | 随时运行预设演示问题 |
| `/quit` | 退出 |

---

## 核心设计

### 防幻觉：强工具锁

诊股和选股 Agent 使用 `bind_tools` 绑定金融数据工具，所有涉及具体数值（价格、PE、涨跌幅等）的问题**强制触发工具调用**，不允许 LLM 凭空生成数字。

### 双轨风控

- **前置**：用户输入经过违禁词检测，命中即拦截，不进入任何 Agent
- **后置**：Agent 输出经过投资建议语义检测，违规话术替换为 `[已过滤]`，金融场景强制附加免责声明

风控规则在 `config/risk_rules.py` 统一管理，修改规则无需改动 Agent 代码。

### 场景锁定

路由 Agent 具备多轮上下文记忆。用户在同一话题下追问时，置信度低的意图会自动沿用上一轮场景，避免跨场景串扰。

### 并行 Agent 调用

当一条消息包含多个意图（如"茅台怎么样？白酒板块呢？"），`dispatch_node` 通过 LangGraph 的 `Send` API 同时触发多个 Agent，结果在 `merge_node` 汇总后统一输出。

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
langgraph>=1.1.0
langchain-anthropic>=1.4.0
langchain-core>=1.0.0
anthropic>=0.40.0
pydantic>=2.0.0
python-dotenv>=1.0.0
structlog>=24.0.0
```
