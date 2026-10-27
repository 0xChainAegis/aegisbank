# 架构说明

> 2026-10-24 后端补强：补偿设置冲突保护、恢复额度风险复检、事务内 MFA 拒绝、权限与审计原子提交。见 [本轮记录](BACKEND-HARDENING-2026-10-24.md)。

> 2026-10-23 安全复审后更新；本轮修复、反例与验收见 [安全修复记录](REMEDIATION-PLAN-2026-10-23.md)。
> 最近更新：2026-10-24（补偿设置冲突、风险/MFA 复检与权限审计事务）。
> 文中数字与实现一致：50 个工具、49 个 `/api` 接口、5 个场景模块 + 6 个 2A 扩展模块、后端 252 项 pytest（17 个测试文件）。

## 1. 设计目标

AegisBank 要证明的不是「能调用银行函数」，而是：**一笔金融操作从自然语言意图到工具执行，全程可审核、可拦截、可追溯；用户确认的就是实际执行的那一笔；失败与未知状态不会被伪装成成功。**

因此架构优先保证：

1. Planner 只产出结构化计划，不能直接访问数据库或执行工具；
2. 计划必须通过确定性的 Schema、工具注册和 DAG 依赖校验；
3. 所有工具调用先经统一权限网关决策，再经 `ToolExecutor` 的 `ExecutionGuard` 链执行；
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
注入扫描（gateway.scan_injection：指令 + 参数，命中整条拒绝并累计熔断）
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
DAG Scheduler（幂等键 + 熔断检查 + 节点间暂停标记 + 执行 journal）
  │  preflight every node
  ▼
Permission Gateway
  ├── Permission + Scope
  ├── Injection / Overreach Guard
  ├── Role capability（tool:execute）
  └── Decision: allow / confirm / reauth / deny
  │
  ├── allow   → ToolExecutor（ExecutionGuard 链：SandboxGuard）→ Tool
  │              → Evidence → Audit（SHA-256 链）
  ├── confirm → pending_actions + ActionEnvelope →
  │             用户确认 / MFA Provider（otp | biometric）→ 执行前复核 envelope/权限/风险 →
  │             StateMachine（APPROVED→EXECUTING→PAUSED/COMPLETED/FAILED/UNKNOWN）→
  │             ToolExecutor → Audit
  ├── deny    → Audit（blocked）
  └── failure → 逆序补偿（补偿工具经网关复检）→ ROLLED_BACK / 人工对账
```

IM / CLI / webhook（`channels/im.py`）不是第二条执行路径：适配器解析确认语法后调用同一个 `DagScheduler.run/confirm`，因此复用上图的 Planner、风险、网关、MFA 与审计链。

## 3. 结构化计划契约

Planner 可替换，契约固定（`planning/contracts.py`）。

P0 在规则和 LLM 规划前共用 `planning/safety.py` 检查条件、组合、多目标与金额冲突；模型候选再次校验。`planning/amounts.py` 使用 Decimal 完整解析金额，返回原文片段/位置和值；各场景通过 `planning/intents.py` 的统一入口使用它。对未支持语义返回空步骤澄清；已支持的预置 DAG 沿用原编译和执行链。原始指令不被规范化文本覆盖，金额来源进入计划 assumptions。详情见 [NLP P0](NLP-ASSESSMENT-AND-PLAN-2026-10-25.md)。

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

`registry.py` 定义 `BaseTool` 与 `ToolRegistry`。每个工具声明 `name / title / description / risk_level / permission / input_schema / output_schema / arguments_model`，阶段 2A 增加 `compensable / compensation_tool`。当前注册 **50** 个工具：核心 10 + 五个场景模块 26 + 2A 扩展 14（8 个反向工具 + 6 个演示工具）。权限仅预置 demo-user 的显式工具白名单；新用户与新工具默认拒绝，GET 不隐式授予权限。

### 5.2 ToolExecutor / ExecutionGuard 执行链

阶段 2A 起，scheduler 不再直接调用 `tool.execute`，统一经 `executor.py`：

```text
DagScheduler._execute_nodes
  → tool_executor.execute(tool, arguments, context)
      for guard in guards: guard.before_execute(...)
      result = tool.execute(arguments, context)
      for guard in reversed(guards): guard.after_execute(..., result)
  → result.as_dict()
  → journal.record_execution / audit.record(tool_executed)
```

- `ExecutionGuard` 是协议：`name`、`before_execute`、`after_execute`；默认配置下 guard 是 `SandboxGuard`；
- `ToolExecutor` 按注册顺序执行前置钩子、逆序执行后置钩子；任一前置钩子抛 `SandboxViolation` 即阻止工具执行；
- `SandboxedToolExecutor` 在 guard 链外再包一层墙钟超时（`ThreadPoolExecutor` + `future.result(timeout)`）；超时后禁止新的数据库提交、保留该工作线程的网络限制并写 `sandbox_timeout`；不强杀 Python 线程；
- 沙箱违规先写审计再抛错；scheduler 记录 `tool_failed` 与熔断失败计数，不会把违规伪装成业务成功；
- 补偿工具同样经该执行器，不存在「回滚绕过沙箱」的旁路。

### 5.3 权限网关与角色能力校验

`gateway.py` 在 DAG 执行前统一校验：

1. `scan_injection(instruction, arguments)`：命中即整条请求拒绝（scheduler 随后累计注入熔断）；
2. **角色能力**：`AuthzService.allowed(role, "tool:execute")`；operator/auditor 不能执行银行工具；
3. 用户对工具的最小权限判断（撤权立即生效）；
4. 绿色放行；黄色生成待确认动作；红色生成待确认动作并要求二次校验。

确认执行前会再次调用网关复检权限、角色与风险，防止等待期间撤权或角色变化。

角色矩阵是单一真源（`trust/authz.py`）：`user` 持 `tool:execute / permission:manage / audit:read / trust:inspect`；`operator` 持 `ops:manage / permission:manage / audit:read / trust:inspect`；`auditor` 只持 `audit:read / trust:inspect`。API 层按端点检查能力，执行层由网关再检查一次。演示期角色来自 `X-Aegis-Role` 请求头（缺省 `user`，未知 403），**不是认证机制**。

### 5.4 信任层 `trust/`

| 模块 | 职责 | 关键接口/数据 |
|---|---|---|
| `action_envelope.py` | 计划/参数/风险/权限/身份/一次性 nonce 的一次性确认绑定 | `ActionEnvelope`、`EnvelopeService.verify/approve`、`build_envelopes` |
| `idempotency.py` | 请求幂等键与首次结果重放 | `IdempotencyStore.begin/complete/release`、`idempotency_keys` 表 |
| `state_machine.py` | 13 状态任务生命周期与审计化迁移（含 `PAUSED`） | `ActionState`、`ALLOWED_TRANSITIONS`、`UNKNOWN → RECONCILED/ROLLED_BACK` |
| `evidence.py` | 证据分层（mock/人工/策略/审计链） | `EvidenceSource`、`VerificationKind`、`merge_evidence` |
| `readiness.py` | 就绪探针与写操作 fail-closed | `GET /api/health/ready`、`require_ready()` |
| `circuit_breaker.py` | 三类规则熔断（连续失败 / 红色 / 注入），共享 open 状态 | `threshold/window/lock`、`breaker_events` |
| `authz.py` | 角色能力矩阵 | `AuthzService.normalize/require/describe` |
| `mfa.py` | MFA Provider 与强制策略 | `MfaService.verify`、`OtpProvider`、`SimulatedBiometricProvider` |
| `pause.py` | 暂停标记 + 执行 journal | `PauseRegistry`、`ActionJournal`、`action_pauses` / `action_journal*` |
| `sandbox.py` | 进程内沙箱 Guard / 沙箱执行器 | `SandboxPolicy`、`SandboxGuard`、`SandboxedToolExecutor` |

接线位置：`main.py`（路由、503 门禁、角色解析）、`scheduler.py`（envelope、状态机、熔断、暂停、补偿、证据）、`db.py`（持久化表）、`audit.py`（证据进审计链）、`gateway.py`（注入/权限/角色）、`planning/llm.py`（候选白名单）、`config.py`（TTL、OTP、熔断、沙箱）、`domain.py`（`ExecutionStatus.UNKNOWN/RECONCILED/ROLLED_BACK`）。

### 5.5 DAG 调度、暂停与补偿数据流

调度器先对全部节点做 preflight：任一节点被拒绝则整条任务阻断；任一节点需要确认则整条任务进入 `pending_actions`，避免只执行一半再弹窗。

**暂停/恢复**

- 每个 action 在 `action_pauses` 有暂停标记；`_execute_nodes` 在**节点之间**检查标记，命中即停，记录 `action_paused` 审计并返回 `status=paused` + 已执行结果 + `next_index` + 剩余步骤；
- `POST /api/actions/{id}/resume` 清除标记，从 `next_index` 继续，`prior_results` 由 journal 恢复，已执行节点不重复；
- `GET /api/actions/{id}/journal` 返回节点、结果、暂停状态与 `executed / compensations` 分组。

**执行 journal**

```text
action_journal        action_id / status / next_index / nodes_json / results_json / plan_json
action_journal_entries id / action_id / node_id / tool_name / phase / status / arguments_json / result_json
```

`phase` 取值包括 `executed / paused / compensated / compensation_failed / rollback_blocked`；journal 是回滚的事实来源。

**补偿/回滚**

```text
执行失败
  → 取 journal 中 phase=executed 且未补偿的节点
  → 检查每条补偿规格：不可逆 → 整条回滚 blocked（写 compensation_blocked）
  → 否则按相反顺序：
       动态风险评估 → PermissionGateway.evaluate（role/权限/注入）
       → denied 或 requires_reauth → compensation_failed（转人工）
       → ToolExecutor.execute(补偿工具) → compensation_executed
  → 全部成功 ROLLED_BACK；部分/全部失败 UNKNOWN（人工对账）
```

- 失败不会「自动重试原操作」；`UNKNOWN` 只能对账或回滚；
- `POST /api/actions/{id}/rollback` 供人工触发同一补偿流程；`POST /api/actions/{id}/pause|resume` 控制暂停；
- `run_dag` 是扩展演示 DAG 的公共入口：仍逐节点走网关、风险、执行器与审计，只接受可立即执行的绿色节点。

### 5.6 2A 扩展自动发现契约与装配顺序

`extensions/__init__.py` 扫描包内所有非 `_` 开头的 `.py`，按文件名排序加载（`authz → breaker → compensation → im → mfa → sandbox`）。模块契约（详见 `extensions/README.md`）：

| 导出 | 类型 | 调用时机 | 说明 |
|---|---|---|---|
| `NAME` | `str` | — | 扩展标识 |
| `SCHEMA_SQL` | `str` | 启动 | 幂等建表，可为空 |
| `seed(db, user_id)` | 函数 | 启动 | 幂等演示数据（可选） |
| `activate(services)` | 函数 | scheduler 构造后 | 替换熔断器、登记补偿规格、挂 IM 适配器、注册 MFA provider、包装执行器 |
| `tools(services)` | 函数 | 注册表构造 | 额外工具节点（进权限种子） |
| `router(services)` | 函数 | 应用装配 | 返回 `APIRouter` 或 `None` |
| `start_background(services)` / `stop_background()` | 函数 | lifespan | 可选后台线程 |

装配顺序（`main.py`）：

```text
Schema/seed（scenarios + extensions）
  → 核心工具注册 → 场景工具注册 → 扩展工具注册
  → 权限种子
  → gateway / risk / audit / planner / scheduler（注入 authz/mfa/executor/compensation）
  → activate_extensions（breaker 替换、compensation 登记、im 挂载、mfa 注册、sandbox 包装）
  → include_scenario_routers / include_extension_routers
  → lifespan: start_scenario_background / start_extension_background
```

并行开发开关：`AEGIS_EXTENSION_ALLOW=a,b`、`AEGIS_EXTENSION_ALLOW=none`、`AEGIS_EXTENSION_STRICT=0`（开发期容忍加载失败）。

### 5.7 IM 渠道适配层

`channels/im.py` 是薄适配器：

- `ImMessage(channel, sender_id, text, message_id)` 做长度/枚举校验；
- 命中 `确认 <action_id> [验证码] <otp>` 则调用 `scheduler.confirm`，否则调用 `scheduler.run`；
- 结果渲染成人类可读回执，同时保留原始 `structured` 结果；
- 每个入站消息写 `im_message_executed / im_message_rejected` 审计；
- 按通道/发送者/消息 ID 命名空间加内容哈希；动作锁覆盖检查与执行；相同消息回放，不同正文冲突；
- `extensions/im.py` 提供 `POST /api/channels/im/message`（readiness 503 门禁）与 `GET /api/channels/im/help`。

适配器不实现 Planner、不做权限判断、不持有 MFA 逻辑，也不另建审计链。

### 5.8 场景模块自动发现契约

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

### 5.9 时间维度

需求不做真实常驻 cron，而是「持久化任务表 + 按需/可选轮询触发」：

- 任务表 `scheduled_tasks(task_id, kind, payload_json, run_at, recurrence, status, last_run_at, last_result_json, ...)`；
- 创建：`schedule_transfer`（一次性/每月/每年）与生日场景的 `schedule_flower_order` / `schedule_cake_order`（到期前 2 天）；
- 执行：`run_due_tasks` 工具按 `run_at <= now` 取到期任务；`POST /api/automation/run-due` 提供**演示时间快进**（可传 `now` 覆盖当前时间），到期执行前重新调用网关复检权限，审计写入 `trigger_source="scheduled"`；该端点已接 readiness 503 门禁；
- 幂等：在同一个执行事务中读取 pending、执行副作用并提交 done，重复调用不会重复扣款；
- 可选后台线程：`AEGIS_AUTOMATION_ENABLED=true` 时启动守护线程按 `AEGIS_AUTOMATION_INTERVAL_SECONDS` 轮询 `run_due`；默认关闭，测试与演示均可用快进接口触发。

### 5.10 证据流与审计链

- 证据在响应生成时同步产生：工具结果（`mock_bank`）、网关/风险/角色判断（`policy_engine`）、人工确认与 MFA（`human_confirmation`）、哈希链校验（`audit_chain`）；
- 每个审计事件（规划、确认、执行、失败、状态迁移、熔断、注入拒绝、暂停、补偿、沙箱拦截、IM 消息）把 `evidence` 写入 `audit_log.result_json` 的 `{"result": ..., "evidence": [...]}`；
- 哈希链：`entry_hash = SHA256(prev_hash + canonical(entry))`，证据参与计算；`GET /api/audit/verify` 全链校验，readiness 也调用同一校验；
- 证据只存「来源 + 是否验证 + 验证方式 + 说明」，不存原始敏感数据。

### 5.11 前端

React 控制台（`frontend/src/`）七个页面：

- **银行概览**：账户、卡片、订阅、异常提示；
- **场景数据（只读，原六场景面板）**：理财、账单、订阅、卡片申请、联系人、定时任务/目标/礼物订单与时间快进；
- **任务控制台**：指令输入、结构化计划预览、风险徽标、确认/OTP 弹窗、`UNKNOWN`/对账状态；
- **权限控制台**：查看/授予/撤回每个工具的最小权限；
- **2A 能力**：MFA Provider、沙箱策略与演示、IM 渠道；
- **运维面板**：熔断状态、事件与恢复；
- **操作审计**：审计字段、证据分层与哈希链校验。

全局 `ReadinessBanner` 展示就绪组件，非 `ready` 时禁用写操作。`roles.ts` 从 `/api/authz/me` 获取能力列表，获取失败时关闭写入口；授权、MFA、沙箱、IM、熔断和任务面板均检查能力与 readiness。

## 6. 数据模型

| 类别 | 表 | 用途 |
|---|---|---|
| 核心 | `permissions` | 用户对每个工具的授权状态 |
| 核心 | `pending_actions` | DAG/计划快照/envelope/状态与历史/结果 |
| 核心 | `audit_log` | 追加式审计记录与哈希链字段 |
| 信任 | `idempotency_keys` | 幂等键与首次响应 |
| 信任 | `used_nonces` | ActionEnvelope 一次性 nonce |
| 信任 | `circuit_breaker` | 熔断 open 状态与失败计数（三类规则共享） |
| 信任 | `breaker_events` | 规则事件（red_operation / injection_hit / circuit_open / reset 等）；解锁另写 `circuit_breaker_unlock` 审计 |
| 2A | `action_pauses` | 每个 action 的暂停标记、原因与恢复时间 |
| 2A | `action_journal` | 执行进度、`next_index`、节点/结果/计划快照 |
| 2A | `action_journal_entries` | 节点级 `executed / paused / compensated / compensation_failed / rollback_blocked` |
| 2A | `im_messages` | IM `message_id` 幂等回执 |
| 2A | `compensation_demo_ledger` | 补偿演示账本（仅演示数据） |
| Mock Bank | `bank_accounts` / `bank_cards` / `bank_transactions` / `bank_subscriptions` | 确定性银行事实 |
| 理财 | `wealth_products` / `wealth_holdings` / `wealth_orders` / `wealth_profile` | 模拟产品、持仓、订单与风险偏好 |
| 转账 | `contacts` | 联系人簿（姓名/别名/手机号/生日） |
| 账单 | `budgets` | 分类月预算（异常检测用） |
| 卡片 | `card_applications` / `card_secrets` | 虚拟卡申请状态、密码修改时间戳（不存明文） |
| 时间维度 | `scheduled_tasks` / `budget_goals` / `gift_orders` | 定时任务、预算目标、生日礼物订单 |

## 7. HTTP 接口总览

共 **49** 个 `/api` 路径（核心 16 + 场景 13 + 2A 20）：

```text
健康/规划      GET  /api/health
              GET  /api/health/ready
              GET  /api/planner/info
              POST /api/planner/plan
              GET  /api/tools
执行/确认      POST /api/agent/run                     （支持 Idempotency-Key + X-Aegis-Role）
              POST /api/confirmations/{action_id}      （支持 Idempotency-Key + mfa_provider）
权限           GET  /api/permissions
              PUT  /api/permissions/{tool_name}
信任           GET  /api/trust/actions/{action_id}
              POST /api/trust/actions/{action_id}/reconcile
              GET  /api/trust/circuit-breaker
              POST /api/trust/circuit-breaker/reset
              GET  /api/trust/breaker/events | /policy
              POST /api/trust/breaker/unlock           （operator）
审计           GET  /api/audit
              GET  /api/audit/verify
银行           GET  /api/banking/overview
场景只读       GET  /api/wealth/products | /holdings | /orders
              GET  /api/contacts
              GET  /api/bills/report | /api/bills/anomalies
              GET  /api/subscriptions/charges | /api/subscriptions/reminders
              GET  /api/cards/applications
              GET  /api/automation/schedules | /goals | /orders
              POST /api/automation/run-due             （演示时间快进，readiness 503）
2A 动作        GET  /api/actions/{action_id}/journal
              POST /api/actions/{action_id}/pause | /resume | /rollback
2A 补偿        GET  /api/compensation/specs
              POST /api/compensation/demo/run          （reversible / irreversible /
                                                        compensation_failure / success）
2A MFA         GET  /api/mfa/providers | /policy
              POST /api/mfa/demo/challenge
2A 沙箱        GET  /api/sandbox/policy
              POST /api/sandbox/demo/run               （network / slow / oversize）
2A IM          GET  /api/channels/im/help
              POST /api/channels/im/message
2A 角色        GET  /api/authz/roles | /me
              POST /api/authz/revoke/{tool_name}
              GET  /api/authz/audit/policy
```

确认链路状态码约定：`409`（envelope 不匹配/过期/nonce 复用、幂等键冲突）、`422`（可预期业务错误，如余额不足/沙箱输出超限）、`403`（二次校验失败、角色能力不足、未知 MFA provider）、`503`（readiness 未就绪/沙箱执行器未装配）、`400`（请求不合法/未知动作/未知演示模式）。

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
- ✅ 场景模块自动发现 + 六场景 6/6（26 个场景工具）
- ✅ 时间维度（任务表 + run-due + 可选后台线程；readiness 503 门禁）
- ✅ 步骤级暂停/恢复、执行 journal、逆序补偿与人工回退（15 可补偿 / 13 不可逆）
- ✅ 可疑行为熔断（短时多次红色、注入命中累计）与 operator 解锁
- ✅ 演示 MFA Provider（OTP + 模拟生物识别）与强制 provider 策略
- ✅ IM / CLI / webhook 渠道适配器（复用同一网关、MFA 与审计链）
- ✅ `ToolExecutor` + `ExecutionGuard` 执行链与进程内沙箱（超时/网络/体积/白名单）
- ✅ 多角色能力矩阵与撤权（`X-Aegis-Role` 演示头）
- ✅ 2A 扩展自动发现（authz / breaker / compensation / im / mfa / sandbox）

尚未落地（生产化，不阻塞比赛演示）：

- ⏳ 幂等键 / `used_nonces` / `im_messages` TTL 清理
- ⏳ 熔断按用户/租户隔离
- ⏳ OS 级容器/命名空间/资源配额隔离（替换进程内沙箱）
- ⏳ 真实身份认证、真实 MFA、真实 IM 平台签名与用户映射
- ⏳ 工具执行中途强停
- ✅ 前端 2A 面板（角色切换 / MFA 选择 / 步骤日志与回滚 / 按角色禁写 / 2A 能力页 / 运维面板）
- ⏳ WORM/合规审计存储、速率限制、CSRF/mTLS、CSP


## 2026-10-23 安全复审后的执行契约

- 网关先决定是否允许，执行器在 `BEGIN IMMEDIATE` 事务内再次复核权限、风险和熔断。工具业务写入、输出契约校验、成功审计、步骤 journal 一起提交；故障全部回滚。嵌套工具使用同一线程连接与 SAVEPOINT。
- confirm / resume / rollback / reconcile 使用按动作的 Linux 文件锁；并发请求返回 `409 ACTION_IN_PROGRESS`，不能以“请求失败”推断尚未扣款。已确认 envelope 必须与节点完整对应；补偿工具标记 internal_only，只接受持久化 journal 生成的原操作证据。
- 定时任务绑定 source_action、参数哈希、风险和原 MFA 授权。来源未完成、撤权、到期风险超授权上限均拒绝；真实子工具逐笔走网关和执行器。旧任务缺授权记录时不继续执行，需取消后重新创建。
- 工具输出强制 `simulated=true`、有限 JSON 值、工具名一致，并验证声明 Schema；旧工具的业务输出契约集中于 `tool_outputs.py`。不以空对象或缺失字段伪造金融事实。
- 沙箱使用有界线程池、ContextVar 网络限制、提交截止时间。只能保护统一 SQLite 提交边界，不能强杀线程或隔离任意 Python、文件、子进程和 C 扩展；未提供任意生成代码执行入口。
- 前端先保存原请求体和幂等键，再发出请求；断线/刷新查询原请求。待确认动作使用独立队列；恢复先取服务端计划与状态。能力来自 `/authz/me`，全部写页面在状态未知或非 ready 时禁用。
- 澄清续问使用 `clarification_run_id`：绑定用户和角色、10 分钟、只能消费一次。调用者明确选择补充，否定或修改意图要求重新给出完整指令。通用代词和重复扣款指令仍需明确核对。
- `audit.result_json` 新增受哈希保护的 run_id / step_id，支持 `GET /api/audit?run_id=...`；历史链不重写。对账只记结论，实际资金补偿使用 rollback。

仍需后续验证：kill -9 / 多 worker 故障恢复、长期 TTL 清理、按用户熔断、OS 隔离、真实身份与 MFA / IM、外部审计锚点与长时间压力测试。详见 [修复记录](REMEDIATION-PLAN-2026-10-23.md)。

### 2026-10-24 补偿与权限补强

恢复设置在同一执行事务内核对原 journal 与当前状态，并拒绝覆盖同资源的后续未补偿写操作；成功逆序补偿和不同资源操作仍可继续。恢复额度按实际目标金额重评风险，事务内再次检查 MFA 要求；策略拒绝记 compensation_blocked。权限更新和独立撤权与审计追加原子提交。详见 [后端补强记录](BACKEND-HARDENING-2026-10-24.md)。

## NLP P1：候选语义与执行计划分层（2026-10-27）

`SemanticPlanner` 包装原规则 Planner。离线规则或可选模型只产生 `SemanticFrame/v1`：意图、原文跨度、槽位、极性、条件、顺序、未覆盖片段、缺失槽位。候选不允许工具名、风险、权限、实体规范值或 verified 字段。服务端逐项核验来源、范围、覆盖、极性及场景注册的表达；不支持的条件/通用组合保持澄清。

场景可提供 `semantic_intents` 和 `semantic_entities`。通过当前用户事实目录解析实体；金额沿用 Decimal 完整 token 校验；日期基于 UTC。可信模板将已验证槽位交给原规则 Planner 生成 DAG，并核对工具序列。新增语义路径没有工具执行入口，仍通过现有 Compiler → 风险/权限 → 确认 → Executor/Guard → 审计。

`ExecutionPlan.semantic` 是服务端 `SemanticAnalysis/v1` 报告，包含原文哈希、规范值、来源和校验类型。报告加入 `plan_hash`，确认时恢复并复算；畸形契约或内容篡改返回 409。旧计划没有 semantic 时保持原哈希算法。显式工具调用和未迁移旧表达标为 `legacy`；这不表示全句语义已验证。

模型服务未配置时默认离线；`auto` 的传输/契约失败回退仍经过语义校验，语义冲突直接澄清。`AEGIS_SEMANTIC_ENABLED=false` 可回退原规划实现。当前未开放超出可独立核验模板的模型表达，不能以“候选覆盖全文”替代理解限定词。详见根目录 P1 报告。
