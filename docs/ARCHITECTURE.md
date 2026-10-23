# 架构说明

> 最近更新：2026-10-23（阶段 1 信任工程与阶段 2B 六场景模块落地后）。
> 文中数字与实现一致：34 个工具、29 个 `/api` 接口、5 个可自动发现场景模块、后端 85 项 pytest。

## 1. 设计目标

AegisBank 要证明的不是「能调用银行函数」，而是：**一笔金融操作从自然语言意图到工具执行，全程可审核、可拦截、可追溯；用户确认的就是实际执行的那一笔；失败与未知状态不会被伪装成成功。**

因此架构优先保证：

1. Planner 只产出结构化计划，不能直接访问数据库或执行工具；
2. 计划必须通过确定性的 Schema、工具注册和 DAG 依赖校验；
3. 所有工具调用只有一个入口：统一权限网关；
4. 用户确认绑定 `ActionEnvelope`（计划哈希、参数、风险、权限、nonce、过期时间），执行前重新校验；
5. 高风险操作分级确认，写操作受幂等键与状态机保护；
6. 审计证据在操作链路中同步产生，并按来源分层，而不是事后补写；
7. 服务未就绪时 fail closed，不把离线显示成成功；
8. 业务场景以模块形式自动发现装配，新增场景不修改核心文件。

完整架构图：

![AegisBank 完整架构图](architecture/aegisbank-architecture.png)

可编辑源文件：[Mermaid 源文件](architecture/aegisbank-architecture.mmd)、[SVG 矢量图](architecture/aegisbank-architecture.svg)；渲染脚本 `scripts/render_architecture.py`。

## 2. 端到端数据流

```text
用户自然语言
  │
  ▼
API（FastAPI）── /api/health/ready（readiness，未就绪则写操作 503）
  │  PlanningRequest
  ▼
注入扫描（gateway.scan_injection：指令 + 参数，命中整条拒绝）
  │
  ▼
Planner Interface
  ├── RuleBasedPlanner                （本地默认 / 安全兜底）
  └── OpenAI-Compatible Planner       （可选，结构化 JSON 候选 + 白名单/冲突校验）
  │  ExecutionPlan/v1
  ▼
Deterministic Plan Compiler
  ├── 工具注册校验 / 参数 Schema
  ├── step id / depends_on / 环检测 / 拓扑排序
  └── plan_hash
  │  CompiledPlan
  ▼
DAG Scheduler（幂等键 + 熔断检查）
  │  preflight every node
  ▼
Permission Gateway
  ├── Permission + Scope
  ├── Injection / Overreach Guard
  └── Decision: allow / confirm / reauth / deny
  │
  ├── allow   → Tool Runtime → Evidence → Audit（SHA-256 链）
  ├── confirm → pending_actions + ActionEnvelope →
  │             用户确认/OTP → 执行前复核 envelope/权限/风险 →
  │             StateMachine（APPROVED→EXECUTING→COMPLETED/FAILED/UNKNOWN）→ Audit
  └── deny    → Audit（blocked）
```

## 3. 结构化计划契约

Planner 可替换，契约固定（`planning/contracts.py`）。

### PlanningRequest

```json
{
  "user_id": "demo-user",
  "instruction": "向 ACC-2002 转账 880 元",
  "tool_name": null,
  "arguments": {}
}
```

### ExecutionPlan

```json
{
  "intent": "transfer",
  "steps": [
    {
      "id": "step-1",
      "tool_name": "transfer",
      "arguments": {
        "from_account": "ACC-1001",
        "to_account": "ACC-2002",
        "amount_cny": 880
      },
      "depends_on": [],
      "description": "向指定账户发起小额转账。"
    }
  ],
  "confidence": 0.93,
  "assumptions": ["未指定转出账户，默认使用演示账户 ACC-1001。"],
  "needs_clarification": false,
  "clarification": null,
  "planner": "rule"
}
```

必填约束：

- `steps` 最多 12 个；`needs_clarification=true` 时必须给 `clarification` 且不能带可执行 steps；
- `step.id` 唯一；`depends_on` 必须引用已有节点且不能成环；
- 工具必须已在 `ToolRegistry` 注册；参数必须通过工具自己的 Pydantic Schema；
- 高风险必要参数缺失时返回澄清，不能由 Planner 擅自编造；
- 契约启用 `extra="forbid"`，契约外字段直接失败。

编译结果包含：拓扑排序后的 `PlanNode` 列表、每节点风险/权限/标题、`plan_hash`（规范化 intent + steps 的 SHA-256）、`dag_path`、Planner 来源/置信度/假设。

预览接口不执行任何工具：

```http
POST /api/planner/plan
Content-Type: application/json

{"instruction":"向 ACC-2002 转账 880 元"}
```

## 4. Planner 可插拔机制与候选校验

`backend/aegisbank_api/planning/`：

| 文件 | 职责 |
|---|---|
| `contracts.py` | `PlanningRequest` / `ExecutionPlan` / `PlanStep` / `Planner` 协议 |
| `rule.py` | 确定性规则 Planner，默认实现与安全兜底 |
| `llm.py` | OpenAI-compatible 模型 Planner + 候选字段白名单、未知工具拒绝、参数冲突校验 |
| `compiler.py` | Schema、工具、参数、DAG、环检测、plan hash |
| `intents.py` | 场景模块可注册的意图规则接口 |
| `factory.py` | 根据环境变量选择 `rule` / `llm` / `auto` |

配置：

```bash
AEGIS_PLANNER_MODE=rule          # rule | llm | auto
AEGIS_LLM_BASE_URL=
AEGIS_LLM_API_KEY=
AEGIS_LLM_MODEL=
AEGIS_LLM_TIMEOUT_SECONDS=20
```

`auto` 模式优先 LLM，模型不可用/超时/输出非法时回退规则 Planner，并在计划中标注 `planner: auto:rule-fallback`。无论哪种模式，模型输出都要经过同一 Compiler、风险引擎与权限网关。

## 5. 核心模块

### 5.1 Tool SDK

`registry.py` 定义 `BaseTool` 与 `ToolRegistry`。每个工具声明 `name / title / description / risk_level / permission / input_schema / output_schema / arguments_model`。当前注册 **34** 个工具：核心 9 个 + 五个场景模块 25 个。

### 5.2 权限网关

`gateway.py` 在 DAG 执行前统一校验：

1. `scan_injection(instruction, arguments)`：命中即整条请求拒绝；
2. 用户对工具的最小权限判断（撤权立即生效）；
3. 绿色放行；黄色生成待确认动作；红色生成待确认动作并要求二次校验。

确认执行前会再次调用网关复检权限与风险，防止等待期间撤权。

### 5.3 信任层 `trust/`

| 模块 | 职责 | 关键接口/数据 |
|---|---|---|
| `action_envelope.py` | 计划/参数/风险/权限/身份/一次性 nonce 的一次性确认绑定 | `ActionEnvelope`、`EnvelopeService.verify/approve`、`build_envelopes` |
| `idempotency.py` | 请求幂等键与首次结果重放 | `IdempotencyStore.begin/complete/release`、`idempotency_keys` 表 |
| `state_machine.py` | 12 状态任务生命周期与审计化迁移 | `ActionState`、`ALLOWED_TRANSITIONS`、`UNKNOWN → RECONCILED/ROLLED_BACK` |
| `evidence.py` | 证据分层（mock/人工/策略/审计链） | `EvidenceSource`、`VerificationKind`、`merge_evidence` |
| `readiness.py` | 就绪探针与写操作 fail-closed | `GET /api/health/ready`、`require_ready()` |
| `circuit_breaker.py` | 连续失败熔断（持久化，可重置） | `threshold/window/lock`、`GET/POST /api/trust/circuit-breaker[/reset]` |

接线位置：`main.py`（路由与 503 门禁）、`scheduler.py`（envelope 发放/复核、状态机、熔断、证据）、`db.py`（持久化表）、`audit.py`（证据进审计链）、`gateway.py`（注入扫描）、`planning/llm.py`（候选白名单）、`config.py`（TTL、OTP、熔断阈值）、`domain.py`（`ExecutionStatus.UNKNOWN/RECONCILED/ROLLED_BACK`）。

### 5.4 DAG 调度与确认状态机

调度器先对全部节点做 preflight：任一节点被拒绝则整条任务阻断；任一节点需要确认则整条任务进入 `pending_actions`，避免只执行一半再弹窗。

```text
DRAFT → AWAITING_CONFIRMATION → AWAITING_REAUTH → APPROVED → EXECUTING → COMPLETED
   │            │                    │                        ├→ FAILED
   ├→ REJECTED  ├→ REJECTED          └→ EXPIRED               └→ UNKNOWN
   └→ EXPIRED   └→ EXPIRED                                      ├→ RECONCILED
                                                                └→ ROLLED_BACK
```

- 待确认记录同时保存 `dag_json`、`plan_json`、`envelopes_json`、`state` 与 `state_history_json`；
- 确认时重新编译计划并复核 envelope（`plan_hash`、`arguments_hash`、风险、权限、nonce、expiry）；
- 执行结果未知时进入 `UNKNOWN`，`result_json` 保存首次结果，后续确认请求返回同一结果而不会重复执行；
- 人工对账：`POST /api/trust/actions/{action_id}/reconcile`；查询：`GET /api/trust/actions/{action_id}`。

### 5.5 场景模块自动发现契约

`scenarios/__init__.py` 在 `create_app()` 装配阶段扫描包内所有非 `_` 开头的 `.py`，按文件名排序加载，并依次调用模块契约（详见 `scenarios/README.md`）：

| 导出 | 类型 | 调用时机 | 说明 |
|---|---|---|---|
| `NAME` | `str` | — | 场景标识（如 `wealth`） |
| `SCHEMA_SQL` | `str` | 启动 | `CREATE TABLE IF NOT EXISTS ...`，可为空 |
| `seed(db, user_id)` | 函数 | 启动 | 幂等写入模拟数据 |
| `tools(services)` | 函数 | 注册表构造 | 返回 `list[BaseTool]` |
| `intents()` | 函数 | Planner 构造 | 返回 `list[IntentRule]` |
| `risk_rules()` | 函数 | 风控引擎构造 | 返回 `list[RiskRule]`，只升不降 |
| `router(services)` | 函数 | 应用装配 | 返回只读 `APIRouter` 或 `None` |
| `start_background(services)` | 函数 | 启动钩子 | 可选；后台轮询（时间维度） |
| `stop_background()` | 函数 | 关闭钩子 | 与启动钩子成对 |

装配顺序：`prepare_persistence`（schema → seed）→ 核心工具注册 → 场景工具注册 → 权限种子 → 网关/风险/审计/Planner/Scheduler → `include_scenario_routers` → lifespan 中 `start_scenario_background`。

并行开发开关：`AEGIS_SCENARIO_ALLOW`（`wealth` / `a,b` / `none`）与 `AEGIS_SCENARIO_STRICT`（默认严格，`0` 时跳过加载失败模块并告警）。

当前场景模块与产物：

| 模块 | 能力 | 工具数 | 只读路由 |
|---|---|---|---|
| `wealth.py` | 理财：产品/持仓/风险测评/申购/赎回 | 5 | `/api/wealth/products`、`/holdings`、`/orders` |
| `transfers.py` | 联系人簿、人名/手机号转账、AA 拆分 | 3 | `/api/contacts` |
| `bills.py` | 月报/年报、异常检测、订阅扣费识别、续费提醒 | 4 | `/api/bills/report`、`/api/bills/anomalies`、`/api/subscriptions/charges`、`/api/subscriptions/reminders` |
| `cards.py` | 虚拟卡申请/发卡、密码重置、限额解锁 | 4 | `/api/cards/applications` |
| `automation.py` | 定时任务、预算锁定、生日 DAG、时间快进 | 9 | `/api/automation/schedules`、`/goals`、`/orders`、`POST /run-due` |

### 5.6 时间维度

需求不做真实常驻 cron，而是「持久化任务表 + 按需/可选轮询触发」：

- 任务表 `scheduled_tasks(task_id, kind, payload_json, run_at, recurrence, status, last_run_at, last_result_json, ...)`；
- 创建：`schedule_transfer`（一次性/每月/每年）与生日场景的 `schedule_flower_order` / `schedule_cake_order`（到期前 2 天）；
- 执行：`run_due_tasks` 工具按 `run_at <= now` 取到期任务；`POST /api/automation/run-due` 提供**演示时间快进**（可传 `now` 覆盖当前时间），到期执行前重新调用网关复检权限，审计写入 `trigger_source="scheduled"`；
- 幂等：先用条件 UPDATE 原子抢占任务（`pending → done`）再执行，重复调用不会重复扣款；
- 可选后台线程：`AEGIS_AUTOMATION_ENABLED=true` 时启动守护线程按 `AEGIS_AUTOMATION_INTERVAL_SECONDS` 轮询 `run_due`；默认关闭，测试与演示均可用快进接口触发。

### 5.7 证据流与审计链

- 证据在响应生成时同步产生：工具结果（`mock_bank`）、网关/风险判断（`policy_engine`）、人工确认（`human_confirmation`）、哈希链校验（`audit_chain`）；
- 每个审计事件（规划、确认、执行、失败、状态迁移、熔断、注入拒绝）把 `evidence` 写入 `audit_log.result_json` 的 `{"result": ..., "evidence": [...]}`；
- 哈希链：`entry_hash = SHA256(prev_hash + canonical(entry))`，证据参与计算；`GET /api/audit/verify` 全链校验，readiness 也调用同一校验；
- 证据只存「来源 + 是否验证 + 验证方式 + 说明」，不存原始敏感数据。

### 5.8 前端

React 控制台（`frontend/src/`）五个页面：

- **银行概览**：账户、卡片、订阅、异常提示；
- **六场景面板**：理财、账单、订阅、卡片申请、联系人、定时任务/目标/礼物订单与时间快进；
- **任务控制台**：指令输入、结构化计划预览、风险徽标、确认/OTP 弹窗、`UNKNOWN`/对账状态；
- **权限控制台**：查看/授予/撤回每个工具的最小权限；
- **操作审计**：审计字段、证据分层与哈希链校验。

全局 `ReadinessBanner` 展示就绪组件，非 `ready` 时禁用写操作。

## 6. 数据模型

| 类别 | 表 | 用途 |
|---|---|---|
| 核心 | `permissions` | 用户对每个工具的授权状态 |
| 核心 | `pending_actions` | DAG/计划快照/envelope/状态与历史/结果 |
| 核心 | `audit_log` | 追加式审计记录与哈希链字段 |
| 信任 | `idempotency_keys` | 幂等键与首次响应 |
| 信任 | `used_nonces` | ActionEnvelope 一次性 nonce |
| 信任 | `circuit_breaker` | 连续失败熔断状态 |
| Mock Bank | `bank_accounts` / `bank_cards` / `bank_transactions` / `bank_subscriptions` | 确定性银行事实 |
| 理财 | `wealth_products` / `wealth_holdings` / `wealth_orders` / `wealth_profile` | 模拟产品、持仓、订单与风险偏好 |
| 转账 | `contacts` | 联系人簿（姓名/别名/手机号/生日） |
| 账单 | `budgets` | 分类月预算（异常检测用） |
| 卡片 | `card_applications` / `card_secrets` | 虚拟卡申请状态、密码修改时间戳（不存明文） |
| 时间维度 | `scheduled_tasks` / `budget_goals` / `gift_orders` | 定时任务、预算目标、生日礼物订单 |

## 7. HTTP 接口总览

共 **29** 个 `/api` 接口（核心 16 + 场景 13）：

```text
健康/规划      GET  /api/health
              GET  /api/health/ready
              GET  /api/planner/info
              POST /api/planner/plan
              GET  /api/tools
执行/确认      POST /api/agent/run                     （支持 Idempotency-Key）
              POST /api/confirmations/{action_id}      （支持 Idempotency-Key）
权限           GET  /api/permissions
              PUT  /api/permissions/{tool_name}
信任           GET  /api/trust/actions/{action_id}
              POST /api/trust/actions/{action_id}/reconcile
              GET  /api/trust/circuit-breaker
              POST /api/trust/circuit-breaker/reset
审计           GET  /api/audit
              GET  /api/audit/verify
银行           GET  /api/banking/overview
场景只读       GET  /api/wealth/products | /holdings | /orders
              GET  /api/contacts
              GET  /api/bills/report | /api/bills/anomalies
              GET  /api/subscriptions/charges | /api/subscriptions/reminders
              GET  /api/cards/applications
              GET  /api/automation/schedules | /goals | /orders
              POST /api/automation/run-due             （演示时间快进）
```

确认链路状态码约定：`409`（envelope 不匹配/过期/nonce 复用、幂等键冲突）、`422`（可预期业务错误，如余额不足）、`403`（二次校验失败）、`503`（readiness 未就绪）、`400`（请求不合法/未知动作）。

## 8. 当前落地范围

已完成：

- ✅ 可插拔 Planner、规则 Planner、OpenAI-compatible Planner 与安全回退
- ✅ 结构化 `ExecutionPlan/v1` 契约、确定性 Plan Compiler、`plan_hash`
- ✅ ActionEnvelope/v1 与执行前复核
- ✅ 幂等键、状态机（含 `UNKNOWN/RECONCILED/ROLLED_BACK`）与对账接口
- ✅ readiness fail-closed 与前端就绪横幅
- ✅ 证据分层与审计哈希链
- ✅ 注入整条拒绝、模型候选白名单
- ✅ 连续失败熔断与运维接口
- ✅ 场景模块自动发现 + 六场景 6/6（25 个场景工具）
- ✅ 时间维度（任务表 + run-due + 可选后台线程）

尚未落地（阶段 2A）：

- ⏳ 步骤级暂停/回退/补偿
- ⏳ 演示 MFA Provider（OTP + 模拟人脸/设备）
- ⏳ IM 渠道适配器
- ⏳ 工具执行沙箱
- ⏳ 多角色权限与撤权演示
- ⏳ 可疑行为熔断规则、幂等/nonce 过期清理、`run-due` readiness 门禁
