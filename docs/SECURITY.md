# 安全边界与生产化清单

> 最近更新：2026-10-23（阶段 1 信任工程 + 阶段 2B 六场景覆盖落地后）。
> 实现依据：`backend/aegisbank_api/trust/`、`gateway.py`、`scheduler.py`、`audit.py`、`main.py`、`db.py`、`planning/llm.py`、`scenarios/`；测试依据：`backend/tests/test_trust.py` 与各场景测试。

## 1. 信任层实现（阶段 1）

### 1.1 ActionEnvelope/v1：一次性确认凭证

黄色/红色操作在创建待确认动作时，为**每个计划节点**生成一份 envelope（`trust/action_envelope.py`、`build_envelopes`）：

| 字段 | 含义 |
|---|---|
| `schema_version` | 固定 `action-envelope/v1` |
| `user_id` | 确认者身份（演示期为 `demo-user`） |
| `plan_hash` | 编译后规范化计划的 SHA-256 |
| `step_id` / `tool_name` | 绑定的计划步骤与工具 |
| `arguments_hash` | 规范化参数的 SHA-256 |
| `risk_level` / `risk_reasons` | 确认时的风险等级与原因 |
| `permission` | 工具声明的最小权限 |
| `nonce` | 一次性随机串（`uuid4().hex`） |
| `issued_at` / `expires_at` | 签发与过期时间（默认 TTL `AEGIS_CONFIRMATION_TTL_SECONDS=300`） |
| `confirmation_state` | `pending / approved / rejected / expired` |
| `approval_token` | 演示审批令牌；API 与审计只返回掩码结果（`masked()` 不暴露明文） |

执行前服务端复核（`EnvelopeService.verify`）：

1. `schema_version` 必须是 `action-envelope/v1`；
2. 未过期（否则 `ENVELOPE_EXPIRED`）；
3. `nonce` 未被使用（`used_nonces` 表，一次性；否则 `NONCE_REUSED`）；
4. `user_id` 与当前请求一致；
5. `plan_hash` 与重新编译的计划一致；
6. `step_id` / `tool_name` 与计划节点一致；
7. `arguments_hash` 与当前计划参数重新计算值一致；
8. `risk_level` 与重新评估的动态风险一致；
9. `permission` 与工具当前声明一致。

任一不一致 → `409 ENVELOPE_MISMATCH`（版本不支持为 `ENVELOPE_VERSION_UNSUPPORTED`），**不执行、不创建业务流水、不写业务审计**；批准/拒绝时统一 `claim_nonces` 消费 nonce，捕获重放。确认接口对 envelope 错误的响应体为 `{"code": ..., "message": ...}`。

### 1.2 幂等键与重放

- 入口：`POST /api/agent/run` 与 `POST /api/confirmations/{action_id}` 接受 `Idempotency-Key` 请求头；
- 存储：`idempotency_keys(scope, key, request_hash, status, response_json, created_at, updated_at)`，`scope` 分别为 `agent.run` / `confirmation`；
- 首次请求写入 `status=running` 与请求体规范化哈希；成功后保存首次响应（`completed`），重复请求直接返回首次结果，不产生第二个待确认动作或第二次执行；
- 同一 key 携带不同请求体 → `409 IDEMPOTENCY_KEY_REUSED`；相同 key 正在处理 → `409 IDEMPOTENCY_IN_PROGRESS`；
- 失败路径释放键（`release`），允许重试；
- 确认动作本身也持久化 `result_json`，即使不带幂等键，重复确认同一 `action_id` 也返回首次结果，不会二次执行。

### 1.3 任务状态机

`trust/state_machine.py` 的 `ActionState`：

```text
DRAFT → AWAITING_CONFIRMATION → AWAITING_REAUTH → APPROVED → EXECUTING → COMPLETED
   │            │                    │                        ├→ FAILED
   ├→ REJECTED  ├→ REJECTED          └→ EXPIRED               └→ UNKNOWN
   └→ EXPIRED   └→ EXPIRED                                        ├→ RECONCILED
                                                                   └→ ROLLED_BACK
```

- 状态与迁移历史持久化在 `pending_actions.state` / `state_history_json`；
- 每次合法迁移写 `state_transition` 审计；非法迁移写 `state_transition_rejected` 审计并抛 `IllegalTransition`；
- `UNKNOWN` 表示「已发出、结果不确定」，**禁止自动重试**，只能通过人工对账转 `RECONCILED` 或 `ROLLED_BACK`；
- 对账接口：`POST /api/trust/actions/{action_id}/reconcile`（`outcome=reconciled|rolled_back`），查询接口：`GET /api/trust/actions/{action_id}`（返回状态、历史、掩码 envelope 与证据）；
- `UNKNOWN` 的触发方式是工具抛出 `ExecutionOutcomeUnknown`；当前模拟工具正常路径不会触发，测试通过注册测试工具注入（`test_unknown_outcome_is_not_executed_twice`）。

### 1.4 readiness 与 fail-closed

`GET /api/health/ready` 返回：

| 组件 | 级别 | 检查内容 |
|---|---|---|
| `sqlite` | 关键 | 可读写（`SELECT 1`） |
| `audit_chain` | 关键 | 哈希链校验通过 |
| `mock_bank_seed` | 关键 | 账户与卡片种子存在 |
| `planner` | 非关键 | Planner 已初始化 |

- 关键组件任一失败 → `status=not_ready`；仅 Planner 不可用 → `degraded`；否则 `ready`；
- `POST /api/agent/run` 与 `POST /api/confirmations/{action_id}` 调用前执行 `ReadinessService.require_ready()`，非 `ready` 一律 **HTTP 503**，响应说明未就绪原因；
- 前端 `ReadinessBanner` 显示各组件状态，非 `ready` 时禁用任务提交、人工确认与时间快进（fail closed）；
- 已知缺口：`POST /api/automation/run-due` 当前直接调用 `scheduler.run`，尚未接入 readiness 门禁，列入阶段 2A 收尾。

### 1.5 证据分层

`trust/evidence.py` 定义四类来源与四种验证方式：

```text
source:            mock_bank | human_confirmation | policy_engine | audit_chain
verification_kind: tool_result | approval | policy_decision | hash_chain
verified:          true | false
detail:            人类可读说明
```

- 绿色执行返回 `mock_bank`（工具结果）+ `policy_engine`（网关决策）+ `audit_chain`（哈希链校验）；
- 确认执行额外包含 `human_confirmation`（人工批准，红色操作注明完成二次校验）；
- 失败证据标记 `verified=false` 并说明「未自动重试」；
- API 响应同时提供 `evidence` 与 `evidence_list`（两者内容相同，兼容前端）；审计记录把证据写入 `result_json` 的 `evidence` 字段，证据参与哈希链计算，`GET /api/audit/verify` 在新增证据后仍校验通过。

### 1.6 Prompt 注入整条拒绝

- `gateway.scan_injection(instruction, arguments)` 在 **Planner 之前**扫描指令与参数，命中即整条请求拒绝：不生成计划、不写业务状态，审计事件 `injection_blocked`，响应 `status=blocked`、`risk_level=red` 并回传 `matched_rules`；
- 规则覆盖越狱/忽略指令/绕过权限/系统提示词等常见模式；权限网关在节点级再检查一次；
- 预览接口 `POST /api/planner/plan` 同样先拒绝注入请求；
- 这是字符规则基线，不是完整注入分类器（见 §3）。

### 1.7 模型候选白名单与冲突校验

`planning/llm.py` 把模型输出视为不可信候选：

1. 只接受 `ExecutionPlan` / `PlanStep` 契约字段，出现契约外字段或非 JSON 对象直接失败；
2. 模型返回未注册工具 → 失败，不进入执行；
3. 模型不得覆盖用户显式提供的参数、不得丢弃高风险参数（`to_account / from_account / amount_cny / new_day / new_limit_cny / daily_limit_cny / card_id / subscription_id`）；
4. 模型不得补全用户未提供的转账收款方或金额（值必须能在用户原话中找到）；
5. 冲突转为 `needs_clarification`，不会「模型赢」；
6. `auto` 模式下 LLM 失败回退规则 Planner，并显式标注 `planner: auto:rule-fallback`。

### 1.8 异常熔断

- 持久化在 `circuit_breaker` 表；默认 `threshold=3` 次连续失败、`window_seconds=60` 窗口、`lock_seconds=60` 锁定时长，可用 `AEGIS_CIRCUIT_BREAKER_*` 配置；
- 工具执行失败计数，成功清零；达到阈值后写 `opened_at`，熔断打开；
- 打开期间：`POST /api/agent/run` 与确认接口直接返回 `status=blocked` 并说明原因（HTTP 200，业务状态 blocked），审计事件 `circuit_breaker_open`；绿色查询同样被拒；
- 运维接口：`GET /api/trust/circuit-breaker` 查看状态与 `retry_after_seconds`，`POST /api/trust/circuit-breaker/reset` 手动重置；
- 当前为阶段 1 骨架，只统计「连续失败」；可疑行为（短时间多次红色操作、注入命中累计）属于阶段 2A。

## 2. 工具权限与风险基线

工具必须继承 `BaseTool` 并声明 `risk_level` 与 `permission`；动态风险只能保持或上调。当前工具目录共 **34** 个（核心 9 + 场景 25）。

### 2.1 核心工具（`backend/aegisbank_api/tools/finance.py`）

| 工具 | 基线风险 | 最小权限 | 作用 |
|---|---|---|---|
| `query_bill` | 绿 | `billing:read` | 账单分析、分类与异常订阅识别 |
| `transfer` | 黄 | `transfer:execute` | 智能转账，按金额与日累计升红 |
| `adjust_repayment_date` | 黄 | `card:manage` | 修改还款日 |
| `adjust_card_limit` | 黄 | `card:manage` | 调整额度，> 5000 元升红 |
| `set_transaction_limit` | 黄 | `card:manage` | 设置单日交易限额，> 5000 元升红 |
| `report_card_lost` | 红 | `card:security` | 卡片挂失 |
| `unlock_card` | 红 | `card:security` | 卡片解挂 |
| `list_subscriptions` | 绿 | `subscription:read` | 查询订阅与风险标记 |
| `cancel_subscription` | 黄 | `subscription:manage` | 取消指定订阅 |

### 2.2 场景工具（`backend/aegisbank_api/scenarios/`）

| 模块 | 工具 | 标题 | 基线风险 | 最小权限 |
|---|---|---|---|---|
| wealth | `list_wealth_products` | 查看理财产品 | 绿 | `wealth:read` |
| wealth | `query_wealth_holdings` | 查询理财持仓 | 绿 | `wealth:read` |
| wealth | `assess_wealth_risk` | 风险测评 | 绿 | `wealth:read` |
| wealth | `purchase_wealth` | 申购理财产品 | 红 | `wealth:execute` |
| wealth | `redeem_wealth` | 赎回理财产品 | 黄（> 1000 元升红） | `wealth:execute` |
| transfers | `list_contacts` | 查看联系人 | 绿 | `contact:read` |
| transfers | `add_contact` | 新增联系人 | 黄 | `contact:manage` |
| transfers | `transfer_to_contact` | 联系人转账 | 黄（> 5000 元或日累计 > 1000 元升红） | `transfer:execute` |
| bills | `bill_report` | 账单报告 | 绿 | `billing:read` |
| bills | `detect_bill_anomalies` | 账单异常检测 | 绿 | `billing:read` |
| bills | `identify_subscription_charges` | 订阅扣费识别 | 绿 | `subscription:read` |
| bills | `list_renewal_reminders` | 续费提醒 | 绿 | `subscription:read` |
| cards | `apply_virtual_card` | 申请虚拟卡 | 黄 | `card:manage` |
| cards | `issue_virtual_card` | 审核并发放虚拟卡 | 黄 | `card:manage` |
| cards | `reset_card_password` | 重置卡片密码 | 红 | `card:security` |
| cards | `unlock_transaction_limit` | 解锁交易限额 | 黄（> 5000 元升红） | `card:manage` |
| automation | `query_contact_birthday` | 查询联系人生日 | 绿 | `calendar:read` |
| automation | `lock_budget_funds` | 锁定预算资金 | 黄 | `automation:manage` |
| automation | `unlock_budget_funds` | 解锁预算资金 | 绿 | `automation:manage` |
| automation | `schedule_flower_order` | 预约生日鲜花 | 黄 | `automation:manage` |
| automation | `schedule_cake_order` | 预约生日蛋糕 | 黄 | `automation:manage` |
| automation | `schedule_transfer` | 定时转账 | 黄（> 5000 元升红） | `transfer:execute` |
| automation | `list_scheduled_tasks` | 查看定时任务 | 绿 | `automation:read` |
| automation | `cancel_scheduled_task` | 取消定时任务 | 绿 | `automation:manage` |
| automation | `run_due_tasks` | 执行到期任务 | 绿 | `automation:manage` |

新增场景风险规则统一遵守「只升不降」：`RiskGuess` 与工具基线取最大值，且规则是确定性的（金额、日累计、产品风险等级、申请单状态等），LLM 输出不参与风险判定。

## 3. 明确不适用于生产的部分

1. `demo-user` 是固定用户，没有登录、会话、设备绑定或真实 MFA；
2. 演示 OTP `246810` 是代码内默认值，不可用于任何生产环境；`approval_token` 也只是演示用确定性令牌；
3. 工具返回模拟账单/转账/理财结果，没有接入银行核心或开放平台；理财内容不构成投资建议，不产生真实资金变动；
4. 规则注入检测只是字符基线，不能替代专门的安全策略引擎或模型输入输出防护；
5. SQLite 单机存储不满足银行级高可用、权限隔离、WORM 审计与分布式并发要求；幂等/nonce 存储是单机库，未实现跨进程锁与 TTL 清理；
6. API 未做速率限制、CSRF、mTLS、细粒度 RBAC/ABAC；
7. 前端尚未配置完整内容安全策略（CSP）与第三方资源白名单；当前 UI 使用本地系统字体，不依赖外部字体 CDN；
8. 无工具沙箱，工具与 API 同进程执行；无步骤级补偿回退；无 IM 渠道。

## 4. 上线前必须完成

- 接入银行统一身份认证、MFA 与设备指纹（替换固定 `demo-user` 与演示 OTP）；
- 用 OPA/Cedar 等策略引擎替换硬编码风险判断，并补齐角色/权限矩阵；
- 幂等键与 nonce 迁移到带 TTL 清理与分布式一致性的存储（如 Redis/数据库唯一约束 + 过期策略）；
- 将确认、证据与审计写入独立、只追加、可校验的合规存储；
- 引入密钥管理服务，移除代码默认 OTP；
- 对工具输入输出做严格 schema 与金额/账户白名单校验，并隔离执行环境（沙箱、超时、无外网）；
- 增加速率限制、审计告警、可疑行为熔断与人工复核；
- 通过威胁建模、渗透测试、依赖供应链扫描和数据合规评审。

## 5. 已知边界与后续阶段

| 边界 | 状态 | 归属 |
|---|---|---|
| 熔断仅统计连续失败，缺少可疑行为规则 | 骨架已有 | 阶段 2A |
| 步骤级暂停 / 回退 / 补偿 | 未实现 | 阶段 2A |
| 演示 MFA Provider（OTP + 模拟人脸/设备） | 仅演示 OTP | 阶段 2A |
| IM 渠道适配器 | 未实现 | 阶段 2A |
| 工具执行沙箱 | 未实现 | 阶段 2A |
| 多角色权限与撤权演示 | 仅单用户 | 阶段 2A |
| `POST /api/automation/run-due` 未接 readiness 门禁 | 已知缺口 | 阶段 2A 收尾 |
| 幂等键 / used_nonces 过期清理 | 未实现 | 阶段 2A |
| 多轮上下文与指代消解 | 仅单轮澄清 | 后续阶段 |

## 6. 开发约定

- 不提交 `.env`、私钥、真实账号、真实客户数据；
- 新工具必须声明风险等级、最小权限和输入/输出 schema，并继承 `BaseTool`；
- 新增工具调用路径必须经过 `PermissionGateway`；
- 新增场景必须遵守 `backend/aegisbank_api/scenarios/README.md` 契约，不得绕过幂等与状态机；
- 修改后运行 `gate.ps1`，再通过 `checkpoint.ps1` 提交；
- 涉及公开、发布、部署时先执行 DSH 工作区的安全审计流程。
