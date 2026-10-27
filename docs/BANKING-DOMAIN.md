# 银行领域模型与六场景闭环

> 2026-10-25 NLP P0：转账、AA、定时转账、生日预算、卡片与理财共用完整人民币金额解析。支持明确中文数字、千分位与千/万单位；歧义金额、可识别但未支持的条件/组合任务转澄清，模型不能自动丢弃条件或只执行部分步骤。六场景工具覆盖不等于任意表达覆盖，详见 [P0 记录](NLP-ASSESSMENT-AND-PLAN-2026-10-25.md)。


> 2026-10-23 安全复审后更新；本轮修复、反例与验收见 [安全修复记录](REMEDIATION-PLAN-2026-10-23.md)。
> 最近更新：2026-10-23（阶段 2A 六项硬要求完成后，基线 `bf36895`）。
> 所有银行数据都来自确定性的 Mock Bank Core（SQLite），LLM 与 Planner 不得编造余额、账单、交易、联系人、持仓或理财收益。

## 1. 目标与范围

当前覆盖赛题六个参考场景 **6/6**：

1. 智能转账（含联系人簿、人名/手机号转账、AA 拆分、定时转账）
2. 账单分析（月报/年报、异常检测）
3. 理财操作（产品、持仓、风险测评、申购、赎回；全部模拟数据）
4. 卡片管理（额度/还款日/限额/挂失/解挂、虚拟卡申请与发卡、密码重置、限额解锁）
5. 订阅/代扣（查询、取消、扣费识别、续费提醒）
6. 跨场景联动（账单 → 取消异常订阅；生日 → 查生日 → 锁预算 → 预订鲜花/蛋糕）

业务场景以 `backend/aegisbank_api/scenarios/` 下的可自动发现模块落地；信任层（ActionEnvelope、幂等、状态机、证据、readiness、熔断）见 [SECURITY.md](SECURITY.md) 与 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 2. 数据模型

### 2.1 Mock Bank Core（核心）

| 表 | 说明 |
|---|---|
| `bank_accounts` | 账户余额、可用余额、账户类型 |
| `bank_cards` | 卡号掩码、状态、额度、还款日、交易限额 |
| `bank_transactions` | 交易流水、分类、金额、时间、状态 |
| `bank_subscriptions` | 订阅商户、金额、周期、状态、风险标记 |

### 2.2 信任层与核心状态表

| 表 | 关键列 | 说明 |
|---|---|---|
| `permissions` | `(user_id, tool_name, granted, updated_at)` | 每个工具的最小权限授权 |
| `pending_actions` | `id / dag_json / plan_json / envelopes_json / risk_level / requires_reauth / status / state / state_history_json / result_json / expires_at` | 待确认动作、计划快照、ActionEnvelope、状态机历史与首次结果 |
| `audit_log` | `event / instruction / dag_path / tool_name / arguments_json / result_json(含 evidence) / confirmation_state / risk_level / prev_hash / entry_hash` | 追加式审计与 SHA-256 哈希链 |
| `idempotency_keys` | `(scope, key, request_hash, status, response_json, created_at, updated_at)` | 幂等键与首次响应 |
| `used_nonces` | `(nonce, action_id, used_at)` | ActionEnvelope 一次性 nonce |
| `circuit_breaker` | `(name, failures, last_failure_at, opened_at, updated_at)` | 熔断 open 状态（连续失败/红色/注入规则共享） |
| `breaker_events` | `(id, created_at, kind, user_id, detail_json)` | 熔断规则事件（red_operation / injection_hit / circuit_open / reset 等） |

### 2.3 阶段 2A 自建表

| 表 | 关键列 | 说明 |
|---|---|---|
| `action_pauses` | `action_id / paused / reason / requested_at / resumed_at / updated_at` | 每个 action 的暂停标记与原因 |
| `action_journal` | `action_id / user_id / role / status / next_index / nodes_json / results_json / plan_json / response_json` | 执行进度与恢复所需快照 |
| `action_journal_entries` | `id / action_id / node_id / tool_name / phase / status / arguments_json / result_json` | 节点级执行/暂停/补偿/阻断记录 |
| `im_messages` | `message_id / channel / sender_id / text / reply_json / created_at` | IM 消息幂等回执 |
| `compensation_demo_ledger` | `entry_id / user_id / action_id / kind / amount_cents / status / reverses_entry_id` | 补偿演示账本（仅演示数据，不触碰真实资金） |

### 2.4 场景模块自建表

| 模块 | 表 | 说明 |
|---|---|---|
| `wealth.py` | `wealth_products` | 模拟理财产品（ID/名称/类型/风险等级 R1–R5/起购金额/预期年化/期限/状态） |
| | `wealth_holdings` | 持仓（份额、本金、市值、开仓时间、状态） |
| | `wealth_orders` | 申购/赎回订单（side、金额、份额、状态、时间） |
| | `wealth_profile` | 用户风险偏好（R1–R5） |
| `transfers.py` | `contacts` | 联系人簿：姓名、别名、手机号、收款账户、生日、关系、状态 |
| `bills.py` | `budgets` | 分类月预算（异常检测的「超预算」规则使用） |
| `cards.py` | `card_applications` | 虚拟卡申请：`applying / approved / issued / rejected`，申请额度与关联卡 |
| | `card_secrets` | 仅保存 `password_changed_at`，不存明文密码 |
| `automation.py` | `scheduled_tasks` | 定时任务：转账/礼物、`run_at`、周期（`none/monthly/yearly`）、状态、最近执行结果 |
| | `budget_goals` | 预算目标：目标金额、已锁定金额、状态 |
| | `gift_orders` | 生日礼物订单：鲜花/蛋糕、模拟金额、到期时间、状态 |

## 3. 全量工具清单（50 个）

工具必须继承 `BaseTool`、声明风险等级与最小权限，并统一经权限网关与执行器调用。核心 10 个 + 场景 26 个 + 阶段 2A 扩展 14 个（8 个反向工具 + 6 个演示工具）。其中 **15 个**声明 `compensable=true`，**13 个**在补偿规格中声明不可逆。

### 3.1 核心工具（`tools/finance.py`，10 个）

| 工具 | 标题 | 基线风险 | 最小权限 |
|---|---|---|---|
| `query_balance` | 查询余额 | 绿 | `account:read` |
| `query_bill` | 分析账单 | 绿 | `billing:read` |
| `transfer` | 智能转账 | 黄 | `transfer:execute` |
| `adjust_repayment_date` | 调整还款日 | 黄 | `card:manage` |
| `adjust_card_limit` | 调整卡片额度 | 黄 | `card:manage` |
| `set_transaction_limit` | 设置交易限额 | 黄 | `card:manage` |
| `report_card_lost` | 卡片挂失 | 红 | `card:security` |
| `unlock_card` | 卡片解挂 | 红 | `card:security` |
| `list_subscriptions` | 订阅查询 | 绿 | `subscription:read` |
| `cancel_subscription` | 取消订阅 | 黄 | `subscription:manage` |

### 3.2 场景工具（`scenarios/`，26 个）

| 模块 | 工具 | 标题 | 基线风险 | 最小权限 |
|---|---|---|---|---|
| wealth | `list_wealth_products` | 查看理财产品 | 绿 | `wealth:read` |
| wealth | `query_wealth_holdings` | 查询理财持仓 | 绿 | `wealth:read` |
| wealth | `assess_wealth_risk` | 风险测评 | 绿 | `wealth:read` |
| wealth | `purchase_wealth` | 申购理财产品 | 红 | `wealth:execute` |
| wealth | `redeem_wealth` | 赎回理财产品 | 黄 | `wealth:execute` |
| transfers | `list_contacts` | 查看联系人 | 绿 | `contact:read` |
| transfers | `add_contact` | 新增联系人 | 黄 | `contact:manage` |
| transfers | `transfer_to_contact` | 联系人转账 | 黄 | `transfer:execute` |
| bills | `bill_report` | 账单报告 | 绿 | `billing:read` |
| bills | `detect_bill_anomalies` | 账单异常检测 | 绿 | `billing:read` |
| bills | `identify_subscription_charges` | 订阅扣费识别 | 绿 | `subscription:read` |
| bills | `list_renewal_reminders` | 续费提醒 | 绿 | `subscription:read` |
| cards | `apply_virtual_card` | 申请虚拟卡 | 黄 | `card:manage` |
| cards | `issue_virtual_card` | 审核并发放虚拟卡 | 黄 | `card:manage` |
| cards | `reset_card_password` | 重置卡片密码 | 红 | `card:security` |
| cards | `unlock_transaction_limit` | 解锁交易限额 | 黄 | `card:manage` |
| automation | `query_contact_birthday` | 查询联系人生日 | 绿 | `calendar:read` |
| automation | `lock_budget_funds` | 锁定预算资金 | 黄 | `automation:manage` |
| automation | `unlock_budget_funds` | 解锁预算资金 | 绿 | `automation:manage` |
| automation | `schedule_flower_order` | 预约生日鲜花 | 黄 | `automation:manage` |
| automation | `schedule_cake_order` | 预约生日蛋糕 | 黄 | `automation:manage` |
| automation | `schedule_transfer` | 定时转账 | 黄 | `transfer:execute` |
| automation | `list_scheduled_tasks` | 查看定时任务 | 绿 | `automation:read` |
| automation | `cancel_scheduled_task` | 取消定时任务 | 绿 | `automation:manage` |
| automation | `run_due_tasks` | 执行到期任务 | 绿 | `automation:manage` |

### 3.3 阶段 2A 扩展工具（`extensions/compensation.py`，14 个）

| 工具 | 标题 | 基线风险 | 最小权限 | 类型 |
|---|---|---|---|---|
| `reverse_transfer` | 转账冲正 | 黄 | `transfer:execute` | 反向 |
| `restore_repayment_date` | 恢复还款日 | 黄 | `card:manage` | 反向 |
| `restore_card_limit` | 恢复卡片额度 | 黄 | `card:manage` | 反向 |
| `restore_transaction_limit` | 恢复交易限额 | 黄 | `card:manage` | 反向 |
| `reactivate_subscription` | 恢复订阅 | 黄 | `subscription:manage` | 反向 |
| `cancel_virtual_card_application` | 撤销虚拟卡申请 | 黄 | `card:manage` | 反向 |
| `restore_wealth_risk` | 恢复风险偏好 | 黄 | `wealth:execute` | 反向 |
| `reverse_purchase_wealth` | 撤销理财申购 | 黄 | `wealth:execute` | 反向 |
| `reverse_demo_reserve` | 演示释放预留资金 | 绿 | `compensation:demo` | 演示反向 |
| `reverse_demo_charge` | 演示撤销手续费 | 绿 | `compensation:demo` | 演示反向 |
| `demo_reserve_funds` | 演示预留资金 | 绿 | `compensation:demo` | 演示 |
| `demo_charge_fee` | 演示手续费扣减 | 绿 | `compensation:demo` | 演示 |
| `demo_irreversible_marker` | 演示不可撤销步骤 | 绿 | `compensation:demo` | 演示 |
| `demo_fail_step` | 演示可控失败 | 绿 | `compensation:demo` | 演示 |

### 3.4 可补偿 / 不可逆清单（28 条规格）

`GET /api/compensation/specs` 返回 28 条规格：15 条可补偿、13 条不可逆。可补偿工具由 `compensation_tool` 指定反向工具：

| 工具 | 反向工具 | 说明 |
|---|---|---|
| `transfer` | `reverse_transfer` | 按原路径冲正模拟转账 |
| `transfer_to_contact` | `reverse_transfer` | 联系人转账同样冲正 |
| `adjust_repayment_date` | `restore_repayment_date` | 恢复调整前还款日 |
| `adjust_card_limit` | `restore_card_limit` | 恢复调整前额度 |
| `unlock_transaction_limit` | `restore_transaction_limit` | 恢复解锁前限额 |
| `cancel_subscription` | `reactivate_subscription` | 恢复已取消订阅 |
| `apply_virtual_card` | `cancel_virtual_card_application` | 撤销仍处于 applying 的申请 |
| `lock_budget_funds` | `unlock_budget_funds` | 解锁预算并退回金额 |
| `schedule_flower_order` | `cancel_scheduled_task` | 取消未执行的鲜花计划 |
| `schedule_cake_order` | `cancel_scheduled_task` | 取消未执行的蛋糕计划 |
| `schedule_transfer` | `cancel_scheduled_task` | 取消未执行的定时转账 |
| `purchase_wealth` | `reverse_purchase_wealth` | 撤销刚完成的模拟申购 |
| `assess_wealth_risk` | `restore_wealth_risk` | 恢复测评前偏好 |
| `demo_reserve_funds` | `reverse_demo_reserve` | 演示释放预留资金 |
| `demo_charge_fee` | `reverse_demo_charge` | 演示撤销手续费 |

不可逆工具（自动回滚会被阻止，转人工对账）：

| 工具 | 不可逆原因 |
|---|---|
| `execute_gift_order` | 内部到期订单消费，不能自动撤销 |
| `report_card_lost` | 挂失是账户安全终态，需人工与银行核实 |
| `reset_card_password` | 安全凭证变更不可自动回退 |
| `unlock_card` | 解挂属安全状态变更，自动重新挂失会放大风险 |
| `set_transaction_limit` | 缺少变更前限额快照，无法精确回退 |
| `issue_virtual_card` | 已发卡写入卡片清单，自动删卡不可逆 |
| `add_contact` | 联系人属 KYC 记录，无删除工具 |
| `cancel_scheduled_task` | 取消后的任务没有恢复接口 |
| `unlock_budget_funds` | 预算解锁本身是补偿动作，重新锁定会改变资金安排 |
| `redeem_wealth` | 赎回是资金退出动作，不能自动反向申购 |
| `run_due_tasks` | 到期任务已实际执行扣款 |
| `demo_irreversible_marker` | 演示节点，用于验证回滚阻断 |
| `demo_fail_step` | 演示可控失败节点，不会成功执行 |

> 上表是**基线**风险；动态风险规则可能在执行时上调（见 §5）。风险只升不降。反向工具不是绕过确认的后门：它们同样经网关、执行器、风险与审计链。

## 4. 六场景能力矩阵

| 场景 | 典型自然语言 | 主要工具 | 只读接口 | 测试 |
|---|---|---|---|---|
| 智能转账 | 「给妈妈转 500」「这顿 300 元 4 个人 AA」「明天给张三转 300」 | `transfer`、`transfer_to_contact`、`list_contacts`、`add_contact`、`schedule_transfer` | `GET /api/contacts` | `test_transfers.py`（10）+ `test_api.py` 转账用例 |
| 账单分析 | 「分析我的本月账单」「去年的年度账单」「哪些扣费异常」 | `query_bill`、`bill_report`、`detect_bill_anomalies` | `GET /api/bills/report`、`/api/bills/anomalies` | `test_bills.py`（8）+ `test_api.py` |
| 理财操作 | 「有哪些理财产品」「买 1000 元稳健短债A」「赎回 500 元」 | `list_wealth_products`、`query_wealth_holdings`、`assess_wealth_risk`、`purchase_wealth`、`redeem_wealth` | `GET /api/wealth/products`、`/holdings`、`/orders` | `test_wealth.py`（11） |
| 卡片管理 | 「申请一张虚拟卡」「把 CARD-8821 密码重置」「解锁交易限额」「挂失 CARD-9902」 | `apply_virtual_card`、`issue_virtual_card`、`reset_card_password`、`unlock_transaction_limit` + 核心卡片工具 | `GET /api/cards/applications` | `test_cards.py`（8）+ `test_api.py` |
| 订阅/代扣 | 「识别我的订阅扣费」「这个月有哪些续费」「取消异常订阅」 | `list_subscriptions`、`cancel_subscription`、`identify_subscription_charges`、`list_renewal_reminders` | `GET /api/subscriptions/charges`、`/api/subscriptions/reminders` | `test_bills.py`、`test_api.py` |
| 跨场景联动 | 「分析我的账单并取消异常订阅」「帮我准备下个月妈妈的生日，预算 1000 元」 | `query_bill → cancel_subscription`；`query_contact_birthday → lock_budget_funds → schedule_flower_order / schedule_cake_order` | 组合上述只读接口 | `test_api.py`、`test_transfers.py`、`test_automation.py`（10） |

### 4.1 转账形态

- 联系人解析：姓名/别名/手机号唯一命中才执行；未命中或多命中一律澄清，**不猜测收款人**；
- 人名转账示例：「给妈妈转 500」→ 解析 `contacts` → `transfer_to_contact(to_name="妈妈", amount_cny=500)`；
- AA 拆分：「这顿 300 元 4 个人 AA」→ 总额 ÷ 人数，为其余参与者各生成一笔 `transfer_to_contact`，形成可并行的多步 DAG；风险按 AA 总额与当日累计判定；
- 定时转账：`schedule_transfer(run_at, recurrence=none|monthly|yearly)` 创建 `scheduled_tasks`，到期由 `run_due_tasks` 执行。

### 4.2 理财操作

- 产品清单为 5 个模拟产品（R1–R5，起购 100–10000 元），全部标注「模拟数据，不构成任何投资建议，不产生真实资金变动」；
- `purchase_wealth` 基线红色、始终需要强验证：资金从演示账户投入产品，校验起购金额与产品存在性，写入 `wealth_orders` 与 `wealth_holdings`；
- `redeem_wealth`：赎回金额 ≤ 1000 元为黄色，> 1000 元升红；支持按 `amount_cny` / `shares` / 持仓隐含市值计算；全额赎回后持仓关闭；
- `assess_wealth_risk` 记录用户风险偏好（R1–R5），并在申购风险原因中提示产品风险等级与偏好匹配。

### 4.3 账单与订阅深度

- `bill_report`：`period=month|year`，输出分类汇总、Top 商户、环比、异常说明；
- `detect_bill_anomalies`：确定性规则——同商户重复扣费、单类目超预算（`budgets`）、订阅扣费金额突增（金额/比例双阈值）、非活跃时段交易；
- `identify_subscription_charges`：基于流水聚合成订阅实体并标记未登记扣费；
- `list_renewal_reminders`：基于订阅周期与下次扣费日生成站内提醒，支持 `cycle` 过滤与 `days_ahead` 窗口；不含外部推送。

### 4.4 卡片补齐

- `apply_virtual_card`：申请额度默认 3000 元、上限 20000 元，写入 `card_applications(status=applying)`；
- `issue_virtual_card`：审核 `applying` 状态的申请，校验通过后置为 `issued` 并生成虚拟卡（卡号掩码、额度、还款日、交易限额）；
- `reset_card_password`：红色 + 演示 OTP；不接收、不保存、不审计明文密码，只记录 `password_changed_at`；
- `unlock_transaction_limit`：默认恢复 10000 元；指定目标限额 > 5000 元时升红。

### 4.5 跨场景 DAG

**DAG 一：账单分析 → 取消异常订阅**

```text
step-1: query_bill
   │  data.suspicious_subscription_id
   ▼
step-2: cancel_subscription
```

步骤 2 参数使用前一步结果：

```json
{
  "subscription_id": "${steps.step-1.data.suspicious_subscription_id}"
}
```

**DAG 二：生日准备（4 步，含跨模块数据）**

```text
step-1: query_contact_birthday   （读 transfers.contacts 的生日）   绿
   ▼
step-2: lock_budget_funds        （在 ACC-1001 锁定预算，可补偿解锁） 黄
   ├──────────────┐
   ▼              ▼
step-3: schedule_flower_order   step-4: schedule_cake_order         黄
```

到期前 2 天由 `run_due_tasks` 触发礼物下单；`unlock_budget_funds` 可在取消时退回锁定金额。

**DAG 三：AA 并行拆分**

```text
step-1..n: transfer_to_contact（各自独立，可并行执行；风险按 AA 总额与日累计统一评估）
```

调度器在执行前解析变量引用，整条 DAG 风险取最高节点；任一节点需要确认时整个任务先进入待确认状态。

### 4.6 阶段 2A 演示数据与 demo 端点

阶段 2A 不新增业务种子，演示数据由 demo 端点按需创建，全部写入本地 SQLite：

| 端点 | 输入 | 产生的数据 / 行为 |
|---|---|---|
| `POST /api/compensation/demo/run?mode=reversible` | 默认 `amount_cny=199/59` | 两步 DAG 执行后可控失败，逆序补偿；写 `compensation_demo_ledger` 与 `compensation_executed` 审计，状态 `ROLLED_BACK` |
| `POST /api/compensation/demo/run?mode=irreversible` | 追加 `demo_irreversible_marker` | 不可逆步骤阻止回滚，写 `compensation_blocked`，状态 `UNKNOWN` |
| `POST /api/compensation/demo/run?mode=compensation_failure` | `fail_compensation=true` | 部分补偿失败，状态 `UNKNOWN`，写 `compensation_failed` |
| `POST /api/compensation/demo/run?mode=success` | 无失败节点 | DAG 正常完成，状态 `completed` |
| `POST /api/actions/{id}/pause` / `resume` / `rollback` | `action_id` | 暂停标记、恢复剩余节点、人工回退 |
| `GET /api/actions/{id}/journal` | `action_id` | 查看节点、已执行结果、补偿与暂停状态 |
| `POST /api/sandbox/demo/run` | `kind=network / slow / oversize` | 只执行内存演示工具，不写业务表；拦截写 `sandbox_blocked` / `sandbox_timeout` |
| `POST /api/mfa/demo/challenge` | `provider/tool_name/risk_level` | 签发演示挑战提示（不返回真实凭据） |
| `POST /api/channels/im/message` | `channel/sender_id/text/message_id` | 查询/挂失/确认；写 `im_messages` 与 IM 审计事件 |
| `GET /api/trust/breaker/events` | `limit` | 查看红色/注入/熔断/解锁事件 |

演示重置：删除 `backend/data/aegisbank.db` 后重启即可恢复种子；2A 表初始为空。

## 5. 动态风险规则

`DynamicRiskEngine` 使用确定性数据判断；场景模块可通过 `risk_rules()` 提供规则，结果与工具基线取最大值（只升不降），LLM 输出不参与风险判定。

### 5.1 核心工具

```text
单笔转账 > 5000 元                    -> 红色
今日累计转账（含本次） > 1000 元       -> 红色
其他转账                              -> 黄色
额度调整 > 5000 元                    -> 红色
挂失 / 解挂                           -> 红色
其他卡片设置变更 / 取消订阅           -> 黄色
账单分析 / 订阅查询                   -> 绿色
```

### 5.2 场景规则

| 工具 | 规则 |
|---|---|
| `purchase_wealth` | 始终红色（资金投入 + 强验证；标注产品风险等级） |
| `redeem_wealth` | ≤ 1000 元黄色；> 1000 元红色；无法确认金额按红色 |
| `transfer_to_contact` | 单笔（AA 取总额）> 5000 元红色；预计日累计 > 1000 元红色；否则黄色 |
| `unlock_transaction_limit` | 指定目标限额 > 5000 元红色；否则黄色 |
| `reset_card_password` | 红色（账户安全凭证） |
| `apply_virtual_card` / `issue_virtual_card` | 黄色 |
| `bill_report` / `detect_bill_anomalies` / 订阅查询 | 绿色（只读） |
| `schedule_transfer` | 单笔 > 5000 元红色；否则黄色 |
| `lock_budget_funds` / 生日礼物预订 | 黄色（锁定可补偿、礼物为模拟订单） |
| `cancel_scheduled_task` / `unlock_budget_funds` / `run_due_tasks` | 绿色（取消未执行任务 / 补偿退回 / 到期触发） |

风险结果会同时写入 Agent 响应的 `risk`、计划步骤的 `risk_level / risk_reasons`、工具执行结果与审计记录。

## 6. 演示数据（`demo-user`）

Mock Bank Core 种子：

- `ACC-1001` 工资卡（主账户）、`ACC-2002` 日常储蓄；
- `CARD-8821` / `CARD-9902`；
- 工资、餐饮、购物、交通、订阅等本月流水；
- `SUB-3001` 云端影音、`SUB-3002` AI 工具订阅（带异常标记）、`SUB-3003` 健身房月卡。

场景种子：

| 模块 | 种子事实 |
|---|---|
| wealth | 5 个模拟产品 `WPRD-R1` 稳健货币A / `WPRD-R2` 稳健短债A / `WPRD-R3` 平衡混合A / `WPRD-R4` 指数增强A / `WPRD-R5` 行业主题A；1 笔演示持仓 `HLTH-DEMO-R2`（3000 份，本金 3000 元，市值 3060 元）；风险偏好表初始为空 |
| transfers | 4 个联系人：妈妈（`ACC-9001`）、老爸（`ACC-9002`）、张三（`ACC-9003`）、李四（`ACC-9004`），姓名/别名/手机号可解析 |
| bills | 4 个分类预算：餐饮 1500 元、购物 2000 元、订阅 500 元、交通 500 元/月；账单数据读取 `bank_transactions` 与 `bank_subscriptions` |
| cards | 1 条已发卡申请 `APP-8001`（虚拟卡，额度 8000 元，关联 `CARD-8821`）；密码修改表初始为空 |
| automation | 定时任务、预算目标、礼物订单初始为空，由演示操作创建；鲜花 199 元、蛋糕 159 元，提前 2 天预订 |
| 2A 扩展 | `action_pauses` / `action_journal*` / `breaker_events` / `im_messages` / `compensation_demo_ledger` 初始为空；由补偿 demo、熔断触发、IM 消息与暂停操作按需创建 |

所有种子幂等（`INSERT OR IGNORE` / 先查存在），重复启动不会重复写入。演示前可删除 `backend/data/aegisbank.db` 恢复初始种子。

## 7. API（49 个路径）

核心（16）：

```text
GET  /api/banking/overview
GET  /api/tools
GET  /api/planner/info
POST /api/planner/plan
POST /api/agent/run
POST /api/confirmations/{action_id}
GET  /api/permissions
PUT  /api/permissions/{tool_name}
GET  /api/audit
GET  /api/audit/verify
GET  /api/health
GET  /api/health/ready
GET  /api/trust/actions/{action_id}
POST /api/trust/actions/{action_id}/reconcile
GET  /api/trust/circuit-breaker
POST /api/trust/circuit-breaker/reset
```

场景（13）：

```text
GET  /api/wealth/products | /holdings | /orders
GET  /api/contacts
GET  /api/bills/report | /api/bills/anomalies
GET  /api/subscriptions/charges | /api/subscriptions/reminders
GET  /api/cards/applications
GET  /api/automation/schedules | /goals | /orders
POST /api/automation/run-due            （演示时间快进，readiness 503）
```

阶段 2A（20）：

```text
GET  /api/actions/{action_id}/journal
POST /api/actions/{action_id}/pause | /resume | /rollback
GET  /api/compensation/specs
POST /api/compensation/demo/run          （reversible / irreversible / compensation_failure / success）
GET  /api/mfa/providers | /policy
POST /api/mfa/demo/challenge
GET  /api/sandbox/policy
POST /api/sandbox/demo/run              （network / slow / oversize）
GET  /api/channels/im/help
POST /api/channels/im/message
GET  /api/authz/roles | /me
POST /api/authz/revoke/{tool_name}
GET  /api/authz/audit/policy
GET  /api/trust/breaker/events | /policy
POST /api/trust/breaker/unlock          （仅 operator）
```

除只读查询与只读演示端点外，写操作统一走 `/api/agent/run`、确认链路或对应的受控动作端点；所有工具执行仍经统一网关、执行器与审计链。

## 8. 当前边界

- 银行数据仍为本地模拟数据，不连接真实银行核心；理财内容不构成投资建议，不产生真实资金变动；
- 强验证使用演示 OTP `246810` 与模拟生物识别 token `FACE-888888`，不冒充真实短信/人脸/U 盾；
- DAG 支持依赖、变量解析、幂等、节点间暂停/恢复与逆序补偿；**不可逆步骤会阻止自动回滚**，需人工对账；
- 沙箱是**进程内演示级**（超时/网络/入参出参/白名单），不是 OS 容器；熔断计数为系统级，未按用户隔离；
- IM 适配器未校验真实平台签名，`sender_id` 仅写审计；角色来自演示请求头 `X-Aegis-Role`；
- 幂等键 / `used_nonces` 仍无 TTL 清理；
- 时间维度用「持久化任务表 + 按需/可选轮询」实现，不是真实常驻 cron；
- 前端 2A 面板（角色切换 / MFA 选择 / 步骤日志与回滚 / 2A 能力页 / 运维面板）已合入；比赛文档、PPT、演示视频和安全自评报告仍需阶段 3 补齐。

## 9. 下一步

1. 阶段 2.5：开发者 Dogfooding（六场景 + 2A 安全路径），修复可用性问题；
2. 生产化收尾：TTL 清理、按用户熔断、OS 级隔离、真实身份/MFA、真实 IM 平台接入；
3. 通用指代消解与长会话（后续，现已支持限时单次澄清续问）；
4. 准备比赛材料（阶段 3）。


## 2026-10-23 账本与定时授权修正

- 50 个工具：核心 10、场景 26、扩展 14；新增 `query_balance` 与仅限定时链调用的 `execute_gift_order`。
- 金额必须为有限正数并精确到分；并发扣款使用条件更新。额度调整保留已用额度；持仓按实际市值和份额同比例赎回，全部赎回关闭持仓。
- 生日预约不能超锁定预算；到期扣款同事务更新订单、剩余预算与 `bank_transactions`。新增 `scheduled_authorizations` 绑定来源 action、参数哈希、风险和 MFA；旧任务没有授权记录时拒绝执行，需取消后重新创建。
- `compensation_reversals` 按原交易唯一登记冲正；`im_actions` 绑定发送者与动作，`clarification_uses` 记录已消费澄清上下文；审计 `result_json` 新增 run_id / step_id，旧哈希链不改写。
- 反向工具只能由补偿链调用。到期执行与补偿同样经过网关、执行器、输出校验与审计；自动化订单扣款是不可逆操作，不能以对账标记代替退款。

## P1 实体和日期规范化

语义槽位仅从当前用户 Mock 账户、卡片、联系人、有效订阅及共享产品目录解析；不猜测陌生对象。尾号由银行卡展示号码提取，同尾号要求澄清。金额复用完整 token 的 Decimal 校验，仍仅支持 CNY。日期按照后端 UTC 规范化，支持明天、后天、下周指定星期和有效未来 ISO 日期；账单月份支持本月/上月，还款日 1–28。未指定账户或月份时保留演示策略默认值，并在服务端语义报告中标注来源；这不是从用户原文抽出的事实。
