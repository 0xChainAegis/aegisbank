# AegisBank · 可信银行 AI 智能体

> 让每一次金融操作，都经过可解释的动态风险判断、最小权限和可验证的审计。

AegisBank 是一个面向银行场景的安全自治智能体原型：用户用自然语言发起账户、卡片、转账或订阅任务，系统将意图编译为结构化 DAG 计划，在执行前经过动态风险引擎与统一权限网关，高风险动作进入确认/MFA 流程，执行过程和结果同步写入 SHA-256 审计哈希链。

> [!IMPORTANT]
> **本项目是本地可运行的演示原型。** 所有账户、卡片、账单、交易、订阅与转账结果均来自确定性的 Mock Bank Core 模拟数据，不连接任何真实银行系统、支付网络或客户数据。演示 OTP 仅用于本地流程展示，不代表生产级身份认证或 MFA 能力。

## 产品定位

AegisBank 不是把大模型直接接上几个银行函数，而是为 Agent 增加一层可审计的「金融操作控制平面」：

```text
自然语言意图
  → 结构化 Planner（只生成计划，不执行工具）
  → 确定性 Plan Compiler（Schema / DAG / plan_hash 校验）
  → 动态风险引擎（绿 / 黄 / 红 + 可解释原因）
  → 统一权限网关（授权 / 越权 / 注入 / 分级决策）
  → 分级确认与演示 MFA
  → Mock Bank Core 工具执行
  → SHA-256 审计哈希链
```

它适合用作银行 Agent 原型的安全控制面参考实现、多工具 DAG 与人机确认的可运行 Demo，以及「Agent 如何被治理」的端到端样例；它**不**替代核心银行系统、真实风控决策引擎或生产身份认证系统。

## 界面预览

以下图片均来自本地运行中的真实控制台，存放于 `docs/screenshots/`。

### 银行概览

![AegisBank 银行概览](docs/screenshots/banking-overview.png)

### 任务控制台

![AegisBank 任务控制台](docs/screenshots/task-console.png)

### 操作审计

![AegisBank 操作审计](docs/screenshots/audit.png)

更多真实界面：[确认/MFA 弹窗](docs/screenshots/confirmation-modal.png) · [权限控制台](docs/screenshots/permissions.png) · [银行概览移动端](docs/screenshots/banking-overview-mobile.png)。截图规范见 [docs/screenshots/README.md](docs/screenshots/README.md)。

## 核心能力

| 能力 | 说明 |
|---|---|
| **Mock Bank Core** | SQLite 驱动的确定性银行数据层，提供账户、卡片、交易、订阅与账单分析；所有余额、流水和订阅事实来自仓库，Planner 与 LLM 不能编造金融数据。 |
| **可插拔 Planner** | 规则 Planner 为默认与安全兜底；可配置 OpenAI-compatible LLM Planner；统一输出 `ExecutionPlan/v1`，不直接调用工具。 |
| **确定性 Plan Compiler** | 校验工具注册、参数 Schema、步骤 ID、依赖关系与环，完成拓扑排序并生成 `plan_hash`。 |
| **动态风险引擎** | 基于单笔金额、当日累计转账、卡片操作类型等确定性事实，输出绿/黄/红风险、评分与可解释原因；只能保持或上调工具基线风险。 |
| **统一权限网关** | 所有工具调用只有一条入口；按工具最小权限校验，拦截常见 Prompt 注入/越权指令，任一节点拒绝则整个 DAG 阻断。 |
| **跨场景 DAG 调度** | 支持步骤依赖、顺序执行和前序结果变量解析，实现「分析账单 → 取消异常订阅」等跨工具任务。 |
| **确认 / MFA 演示** | 黄色操作等待用户确认；红色操作确认之外还需演示 OTP；确认后执行前重新校验权限与动态风险。 |
| **SHA-256 审计链** | 指令、DAG 路径、工具入参、确认状态、风险与结果同步写入哈希链，可通过 API 校验完整性。 |
| **React 控制台** | 银行概览、任务控制台、权限控制台和操作审计四个核心视图，展示计划、风险原因、确认状态与审计证据。 |

## 三场景闭环

### 场景一：智能转账

示例指令：

```text
向 ACC-2002 转账 880 元
```

执行路径：

1. Planner 解析收款账户与金额，生成单步 `transfer` 计划。
2. Plan Compiler 校验工具、参数与 `plan_hash`。
3. 动态风险引擎按金额与当日累计金额评估等级。
4. 绿色直接执行；黄色进入轻量确认；红色进入确认 + 演示 OTP。
5. Mock Bank Core 更新模拟余额并写入模拟交易流水。
6. 执行结果与风险原因写入审计链。

演示数据包含 `ACC-1001`（工资卡）与 `ACC-2002`（日常储蓄）。单笔 880 元通常为黄色；同日再发起 500 元，使累计超过 1000 元后升级为红色强验证。

### 场景二：账单分析

示例指令：

```text
分析我的本月账单
```

返回内容：

- 本月支出总额与消费分类；
- 账单关联的近期交易；
- 异常订阅提示与可疑订阅 ID；
- 面向用户的异常说明。

银行概览接口返回 `monthly_spend_cny`、`daily_transfer_total_cny`、`suspicious_subscription_id` 等字段。当前 Mock 数据中，`SUB-3002`（AI 工具订阅）带有「本月扣费较上月上涨 120%」的风险标记，用于演示从账单洞察到订阅处置的闭环。

### 场景三：卡片管理

支持的示例指令：

```text
把还款日调整到每月 18 日
把信用卡额度调整到 8000 元
把 CARD-8821 的单日交易限额设置为 3000 元
挂失卡片 CARD-9902
解挂卡片 CARD-9902
```

- 调整还款日、交易限额：黄色，需一次确认；
- 调整额度不超过 5000 元：黄色；超过 5000 元：红色强验证；
- 挂失/解挂：红色强验证；
- 所有变更均落到 Mock Bank Core，并写入审计链。

### 跨场景 DAG：账单分析 → 取消异常订阅

示例指令：

```text
分析我的账单并取消异常订阅
```

系统生成两步 DAG：

```text
step-1: query_bill
   │  data.suspicious_subscription_id
   ▼
step-2: cancel_subscription
```

计划中的步骤 2 使用前序结果引用：

```json
{
  "subscription_id": "${steps.step-1.data.suspicious_subscription_id}"
}
```

调度器在运行步骤 2 前解析该引用，确保取消的是本次账单分析实际发现的异常订阅，而不是 Planner 猜测的 ID。整个 DAG 的风险等级取所有节点的最高值；任一步骤需要确认时，整个任务先进入待确认状态，避免执行到一半才中断。

## 动态风险分级

风险引擎位于工具基线与权限网关之间。工具 Manifest 声明基线风险，`DynamicRiskEngine` 只能保持或上调，不会因为模型输出而降低风险。

| 操作 / 条件 | 风险等级 | 系统行为 |
|---|---|---|
| 账单分析、订阅查询 | 🟢 绿色 | 最小权限满足后自动执行 |
| 单笔转账且当日累计不超过 1000 元 | 🟡 黄色 | 创建待确认动作，用户确认后执行 |
| 单笔转账超过 5000 元，或当日累计将超过 1000 元 | 🔴 红色 | 确认 + 演示 OTP 强验证 |
| 调整还款日、设置交易限额、取消订阅 | 🟡 黄色 | 一次用户确认 |
| 调整卡片额度不超过 5000 元 | 🟡 黄色 | 一次用户确认 |
| 调整卡片额度超过 5000 元 | 🔴 红色 | 确认 + 演示 OTP |
| 卡片挂失 / 解挂 | 🔴 红色 | 确认 + 演示 OTP |

风险结果会同时出现在：

- Agent 响应的 `risk.level`、`risk.reasons`、`risk.requires_reauth`；
- 计划步骤的 `risk_level`、`risk_score`、`risk_reasons`；
- 待确认动作与审计记录；
- 前端任务控制台的风险徽标与原因列表。

> 动态风险使用确定性演示规则，不是信用评分、反欺诈模型或生产风控决策。LLM 只负责生成结构化计划，风险判断不信任 LLM 输出。

## 架构

```text
┌─────────────────────────────────────────────────────────────┐
│ React 19 + TypeScript + Vite 控制台                          │
│ 银行概览 │ 任务控制台 │ 权限控制台 │ 操作审计                  │
└────────────────────────────┬────────────────────────────────┘
                             │ /api
┌────────────────────────────▼────────────────────────────────┐
│ FastAPI + Pydantic                                          │
│                                                             │
│  Planner（rule / OpenAI-compatible LLM / auto fallback）     │
│      │ ExecutionPlan/v1                                     │
│      ▼                                                      │
│  Plan Compiler ── Schema / 工具注册 / DAG / plan_hash         │
│      │                                                      │
│      ▼                                                      │
│  DagScheduler ── 依赖排序 / 前序结果变量解析                  │
│      │                                                      │
│      ├── DynamicRiskEngine ── 金额 / 累计 / 操作类型          │
│      ├── PermissionGateway ── 最小权限 / 注入拦截 / 决策      │
│      └── Confirmation ── pending_actions / TTL / 演示 OTP     │
│      │                                                      │
│      ▼                                                      │
│  9 个银行工具 ── BankingRepository（SQLite Mock Bank Core）   │
│      │                                                      │
│      ▼                                                      │
│  AuditService ── SHA-256 哈希链 / 完整性校验                  │
└─────────────────────────────────────────────────────────────┘
```

完整模块边界、数据流与计划契约见 [架构说明](docs/ARCHITECTURE.md)、[银行领域模型与三场景闭环](docs/BANKING-DOMAIN.md) 和 [完整架构图 PNG](docs/architecture/aegisbank-architecture.png)。

### 工具目录

| 工具 | 权限 | 基线风险 | 作用 |
|---|---|---|---|
| `query_bill` | `billing:read` | 绿色 | 账单分析、分类与异常订阅识别 |
| `transfer` | `transfer:execute` | 黄色 | 智能转账，按金额与日累计动态升级 |
| `adjust_repayment_date` | `card:manage` | 黄色 | 修改信用卡还款日 |
| `adjust_card_limit` | `card:manage` | 黄色 | 调整卡片额度，超过阈值升级红色 |
| `set_transaction_limit` | `card:manage` | 黄色 | 设置单日交易限额 |
| `report_card_lost` | `card:security` | 红色 | 卡片挂失 |
| `unlock_card` | `card:security` | 红色 | 卡片解挂 |
| `list_subscriptions` | `subscription:read` | 绿色 | 查询订阅与风险标记 |
| `cancel_subscription` | `subscription:manage` | 黄色 | 取消指定订阅 |

### 关键 API

```text
GET  /api/banking/overview          银行概览：账户、卡片、订阅与异常提示
GET  /api/tools                     工具目录与当前授权状态
GET  /api/planner/info              Planner 模式、工具与计划契约
POST /api/planner/plan              仅预览结构化计划，不执行工具
POST /api/agent/run                 规划、风险评估、网关校验并执行
POST /api/confirmations/{id}        确认/拒绝待执行动作，红色动作校验演示 OTP
GET  /api/permissions               权限列表
PUT  /api/permissions/{tool_name}   授予或撤回工具权限
GET  /api/audit                     查看审计记录
GET  /api/audit/verify              校验 SHA-256 审计哈希链
```

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.11+ · FastAPI · Pydantic | API、工具 SDK、动态风险、权限网关与 DAG 调度 |
| Planner | Rule + OpenAI-compatible LLM | 结构化 `ExecutionPlan/v1`，可插拔、可回退、可校验 |
| 持久化 | SQLite（stdlib） | 本地零依赖；保存 Mock Bank Core、授权、待确认动作与审计链 |
| 前端 | React 19 · TypeScript · Vite | 银行概览、任务控制台、权限控制台、操作审计 |
| 测试 | pytest · httpx · Vitest | 后端 API 闭环与前端纯逻辑测试 |
| 运行方式 | Linux 本地开发 | 推荐 Ubuntu 24.04 / WSL Ubuntu |

## 快速开始

前置条件：

- Python 3.11+、`uv`
- Node.js 20.19+（或 22.12+）、`pnpm`
- Linux / WSL Ubuntu 24.04 环境

```bash
# 进入项目根目录
cd /path/to/aegisbank

# 安装 Python / Node 依赖
bash scripts/bootstrap.sh

# 同时启动后端 API 与前端
bash scripts/dev.sh
```

打开：

- 前端控制台：<http://127.0.0.1:5173>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

也可以分别启动：

```bash
# 终端 1：后端
cd backend
uv run uvicorn aegisbank_api.main:app --reload --host 0.0.0.0 --port 8000

# 终端 2：前端
cd frontend
pnpm dev
```

可选配置（复制根目录 `.env.example` 到 `backend/.env`）：

```bash
AEGIS_DATABASE_PATH=data/aegisbank.db
AEGIS_DEMO_OTP=246810
AEGIS_CONFIRMATION_TTL_SECONDS=300
AEGIS_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AEGIS_PLANNER_MODE=rule   # rule | llm | auto
AEGIS_LLM_BASE_URL=
AEGIS_LLM_API_KEY=
AEGIS_LLM_MODEL=
```

`rule` 模式完全本地、无模型依赖；`auto` 模式优先调用 LLM，不可用时自动回退到规则 Planner。

## 测试与工程命令

```bash
bash scripts/lint.sh    # 后端 ruff + 前端 TypeScript 类型检查
bash scripts/build.sh   # 后端 compileall + 前端 Vite 生产构建
bash scripts/test.sh    # pytest + Vitest
bash scripts/smoke.sh   # 启动 API，跑一条绿色链路并校验审计链
```

后端闭环测试覆盖：9 个工具注册与权限种子、绿色自动执行、黄色确认、红色 OTP、转账金额与日累计触发风险升级、账单分析与异常订阅识别、账单分析 → 取消订阅的跨场景 DAG、卡片额度调整升级红色、撤权拦截、待确认期间撤权复检、Prompt 注入拦截、计划 Schema/DAG 校验、LLM 输出解析与自动回退、SHA-256 审计链完整性校验。
建议按以下顺序体验 Demo：

1. 打开银行概览，查看账户、卡片、订阅和异常标记；
2. 在任务控制台执行「分析我的本月账单」，观察分类与异常订阅；
3. 执行「分析我的账单并取消异常订阅」，查看两步 DAG 和变量解析结果；
4. 执行「向 ACC-2002 转账 880 元」，完成黄色确认；
5. 同日再次转账 500 元，观察累计风险升级为红色并输入演示 OTP `246810`；
6. 在权限控制台撤回某工具权限，再次执行应被网关阻断；
7. 在操作审计页校验 SHA-256 哈希链。

## 目录结构

```text
aegisbank/
├─ backend/
│  ├─ aegisbank_api/
│  │  ├─ banking/          # Mock Bank Core 领域模型与 SQLite 仓库
│  │  │  ├─ models.py
│  │  │  └─ repository.py
│  │  ├─ planning/         # Planner 契约、规则/LLM 实现、Compiler
│  │  ├─ tools/finance.py  # 9 个银行工具与 Manifest
│  │  ├─ risk.py           # 动态风险引擎与可解释原因
│  │  ├─ gateway.py        # 统一权限网关、注入拦截、分级决策
│  │  ├─ scheduler.py      # DAG 调度、变量解析、确认恢复与复检
│  │  ├─ audit.py          # SHA-256 审计哈希链
│  │  ├─ db.py             # SQLite 表与事务
│  │  └─ main.py           # FastAPI 入口与 API 路由
│  └─ tests/               # API 闭环与 Planner 契约测试
├─ frontend/
│  └─ src/                 # React 控制台、API 客户端、风险展示与测试
├─ docs/
│  ├─ screenshots/         # 真实运行截图
│  ├─ architecture/        # 架构图 PNG / SVG / Mermaid
│  ├─ ARCHITECTURE.md      # 模块边界与端到端数据流
│  ├─ BANKING-DOMAIN.md    # 银行领域模型、三场景与跨场景 DAG
│  ├─ SECURITY.md          # 安全边界与生产化清单
│  └─ TECH-STACK.md        # 开发工具与技术栈
├─ scripts/                # bootstrap / dev / lint / build / test / smoke
├─ LICENSE                 # MIT License
└─ README.md
```

## 文档索引

- [银行领域模型与三场景闭环](docs/BANKING-DOMAIN.md)
- [架构说明](docs/ARCHITECTURE.md)
- [完整架构图](docs/architecture/aegisbank-architecture.png)
- [安全边界与生产化清单](docs/SECURITY.md)
- [开发工具与技术栈](docs/TECH-STACK.md)
- [开发环境与验收记录](docs/DEVELOPMENT-ENVIRONMENT.md)
- [上游项目对齐说明](docs/UPSTREAM-ALIGNMENT.md)
- [单文件产品介绍页](docs/product-overview.html)
- [产品介绍页渲染图](docs/screenshots/product-overview.png)
- [真实截图目录](docs/screenshots/README.md)

## 已知边界

AegisBank 是**安全自治 Agent 的可运行原型**，以下边界是刻意保留的：

- **模拟银行数据**：所有账户、卡片、交易、账单、订阅、余额与转账结果均为 Mock Bank Core 数据，不连接真实银行接口，不产生真实资金变动；
- **固定演示用户**：使用 `demo-user`，未接入登录、会话、设备指纹或真实身份认证；
- **演示 OTP**：默认验证码 `246810` 仅用于本地演示，不是生产 MFA，不可用于任何真实业务；
- **演示风险规则**：动态风险引擎是确定性规则，不是生产反欺诈/信用决策模型；
- **单机持久化**：SQLite 适合本地原型，不满足银行级高可用、隔离、容灾和 WORM 审计要求；
- **无步骤补偿**：DAG 支持依赖和变量解析，但尚未实现步骤级回滚、补偿交易与异常熔断；
- **有限安全防护**：注入检测、权限网关和哈希链是基线，不替代专门的安全策略引擎、沙箱、限流、CSRF/mTLS 与渗透测试；
- **LLM 可选**：规则 Planner 无模型依赖；接入 OpenAI-compatible 模型时仍需经过同一 Compiler、风险引擎和权限网关。

这些边界被隔离在 Mock Bank Core、Planner、Risk、Gateway、Audit 等模块中，后续可替换为银行级实现而不改变 Agent 主流程。

## License

本项目采用 [MIT License](LICENSE)。

Copyright (c) 2026 LQZ5885
