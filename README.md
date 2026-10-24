# AegisBank · 可信银行 AI 智能体

**让「说话就能办银行业务」建立在可解释、可拦截、可验证的控制平面之上。**

| 项目 | 说明 |
|---|---|
| 赛题 | 人工智能赛道 · 银行 AI 智能体 |
| 作品形态 | 本地可运行的银行 AI 智能体（AI Banking Agent）原型；全部金融数据来自 Mock Bank Core |
| 代码仓库 | <https://github.com/LQZ5885/aegisbank>（Public · MIT License） |
| 当前基线 | 2026-10-24 后端补强；后端 200 项 pytest、前端 53 项 Vitest、六场景回归 29/29；[本轮记录](docs/BACKEND-HARDENING-2026-10-24.md) |

## 作品简介（≤ 200 字）

> AegisBank 是银行场景的可信 AI 智能体：把自然语言指令编译为可审核的 DAG 计划，经动态风险与统一网关分为绿/黄/红，高风险操作需人工确认并二次验证；执行前后用 ActionEnvelope 与 SHA-256 哈希链绑定并留痕。覆盖转账、账单、理财、卡片、订阅与跨场景联动六类场景，支持回滚补偿、可疑熔断、工具沙箱与多角色撤权。数据均为模拟，不连接真实银行，核心是可信执行控制平面。

> [!IMPORTANT]
> **诚实声明**：本项目是本地可运行的演示原型。所有账户、卡片、账单、交易、订阅、理财与转账结果均来自确定性的 Mock Bank Core 模拟数据，不连接任何真实银行系统、支付网络或客户数据，不产生真实资金变动，理财内容不构成任何投资建议。演示 OTP `246810` 与模拟生物识别 token `FACE-888888` 仅用于本地流程展示，不代表生产级身份认证或 MFA；`X-Aegis-Role` 是演示请求头，不是真实认证；工具沙箱是进程内演示级守卫，不是 OS 容器。

---

## 1. 作品定位与创作理念

### 1.1 要解决的问题

传统手机银行操作路径长、入口深；大模型与 Agent 技术让「说话就能办业务」成为可能，但金融场景无法接受大模型直接连接银行函数：计划不可见、越权拦不住、确认后可被调包、重复提交会重复扣款、失败可能被伪装成成功、日志不可验证。AegisBank 的创作理念是——**不把模型当作执行者，而是为银行 Agent 增加一层可审计的「金融操作控制平面」**：

```text
自然语言意图
  → 结构化 Planner（只生成计划，不执行工具）
  → 确定性 Plan Compiler（Schema / DAG / plan_hash 校验）
  → 动态风险引擎（绿 / 黄 / 红 + 可解释原因）
  → 统一权限网关（最小权限 / 注入拦截 / 角色能力 / 分级决策）
  → 分级确认 + ActionEnvelope + 演示 MFA
  → ToolExecutor + 执行守卫（超时 / 网络 / 体积 / 白名单）
  → Mock Bank Core 工具执行
  → 证据分层 + SHA-256 审计哈希链
```

### 1.2 八项可信承诺

AegisBank 试图证明八件事：

1. 用户能看见 Agent 准备做什么；
2. 高风险操作能被准确拦住；
3. 用户能随时撤回授权；
4. 每次放行或拒绝都有可解释原因；
5. 确认之后执行的就是用户刚刚确认的那一笔；
6. 重复提交不会重复扣款；
7. 失败与未知状态不会被伪装成成功；
8. 日志可验证、事实来源可分层。

> 以上为对外表述的八项承诺；内部 10 条信任不变量与逐条状态见 [安全自评报告](deliverables/05-安全自评报告.md) §3.2。

### 1.3 可替换性：控制平面独立于数据源

所有余额、流水、账单、持仓与订阅事实都来自仓库中的 Mock Bank Core，Planner 与 LLM 不能编造金融数据。当前用 SQLite 承载 Mock 数据只是为了本地一键运行；控制平面（Planner / Compiler / 风险 / 网关 / 信任层 / 审计）与具体数据源解耦，接入真实银行核心时可替换数据层而不改变 Agent 主流程。

### 1.4 使用的 AI 技术

| 环节 | 技术选型 | 说明 |
|---|---|---|
| 意图理解 | 规则 Planner（默认） + 可选 OpenAI-compatible LLM Planner | 规则模式完全离线、无模型依赖；`auto` 模式优先 LLM，不可用时自动回退规则 Planner |
| 任务规划 | 结构化计划 `ExecutionPlan/v1` + 确定性 Plan Compiler | 校验工具注册、参数 Schema、步骤 ID、依赖与环，拓扑排序后生成 `plan_hash` |
| 模型约束 | 模型候选字段白名单 + 冲突转澄清 | LLM 只产出候选计划，不得执行工具、决定权限或降低风险；未知工具与额外字段直接拒绝 |
| 风险决策 | 确定性动态风险引擎 | 基于金额、当日累计、产品等级等事实输出绿/黄/红；只允许 `max(工具基线, 动态规则)`，不信任模型输出 |
| 安全执行 | 统一权限网关 + 信任层 + 执行守卫 | 注入拦截、最小权限、确认绑定、幂等、状态机、readiness fail-closed、进程内沙箱 |
| 可验证性 | 证据分层 + SHA-256 审计哈希链 | 每条审计记录可在线复算校验，事实来源分为 Mock 数据 / 人工确认 / 策略判断 / 审计链四类 |

### 1.5 适合谁，不替代什么

AegisBank 适合作为银行 Agent 原型的安全控制面参考实现、多工具 DAG 与人机确认的可运行 Demo，以及「Agent 如何被治理」的端到端样例。它**不**替代核心银行系统、真实风控决策引擎、生产身份认证或监管级审计存储。

---

## 2. 赛题要求与实现对照

### 2.1 核心技术要求

| 赛题要求（摘要） | AegisBank 的实现 | 可复现证据 |
|---|---|---|
| 至少覆盖 3 个核心场景（鼓励全覆盖） | **六场景 6/6**：智能转账、账单分析、理财操作、卡片管理、订阅/代扣、跨场景联动 | §3；`scripts/scenario-check.py` 29/29 |
| 权限分级：低风险自动、高风险确认、极高风险强验证 | 工具 Manifest 基线风险 + 动态风险引擎输出绿/黄/红；绿色直接执行，黄色一次确认，红色确认 + 演示 MFA；`ActionEnvelope` 绑定确认内容 | §4.1–4.2；`test_trust.py`、`test_mfa.py` |
| 幻觉防护：不得编造交易结果或账户信息 | Planner 只产出计划；Compiler 白名单与 Schema 校验；模型输出字段白名单、冲突转澄清；工具回执必须 `simulated=true` 且匹配输出 Schema；金融事实只来自 Mock Bank Core | §4.3；`test_planner.py`、`test_security_regressions.py` |
| 注入防御：防止特殊 Prompt 绕过权限控制 | 网关 `scan_injection` 在规划前与节点级各扫描一次，命中即整条请求拒绝并写审计；注入命中累计触发熔断 | §4.3；`test_trust.py::test_injection_is_rejected_before_planner` |
| 操作审计：记录完整决策链路与执行日志 | 每条审计包含触发时间、原始指令、DAG 路径、工具入参、执行结果、用户确认状态六字段，并附风险与证据分层；SHA-256 哈希链可在线校验 | §4.3；`GET /api/audit/verify` |
| 异常熔断：连续失败或可疑行为触发安全锁定 | 连续失败、短时多次红色操作、注入命中累计三类规则共用 open 状态；触发后写操作 fail closed；operator 解锁写审计 | §4.3；`test_breaker.py` 7 条 |
| 沙箱环境：受限、可监控的执行环境 | 所有工具经 `ToolExecutor` + `ExecutionGuard`：超时、socket 级网络阻断、入参 8 KB / 出参 64 KB、可选工具白名单；违规先写审计再拒绝。本项目不执行任意生成代码，沙箱作用于注册工具 | §4.3；`test_sandbox.py` 8 条 |
| 意图理解：支持模糊表达、省略上下文、隐含意图 | 规则 Planner 为默认与安全兜底；缺参支持限时单次续问；否定与多意图冲突转澄清，不静默猜测收款人、金额或产品 | §4.3；`test_security_regressions.py` |
| 任务规划：复杂任务拆解为有序 DAG，支持中断、回退与人工接管 | `ExecutionPlan/v1` → 编译器拓扑排序；步骤级暂停/恢复、逆序补偿、执行 journal、`UNKNOWN` 人工对账 | §4.2；`test_compensation.py` 10 条 |
| APP / IM 等渠道 | 响应式 Web 控制台（未打包原生 APP）；`im / cli / webhook` 渠道适配器复用同一 Planner、风险、网关、MFA 与审计链；`message_id` 幂等回放 | §4.3；`test_im_channel.py` 7 条 |

### 2.2 作品资料要求

| 作品资料要求 | 交付位置 |
|---|---|
| 源代码 + README + GitHub 仓库地址 | 本仓库；本文档；<https://github.com/LQZ5885/aegisbank> |
| 技术文档：系统架构图、核心算法说明、安全设计文档 | [`deliverables/02-技术文档.md`](deliverables/02-技术文档.md)、[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)、[`docs/SECURITY.md`](docs/SECURITY.md)、[`docs/architecture/aegisbank-architecture.png`](docs/architecture/aegisbank-architecture.png) |
| 部署说明 | [`deliverables/06-部署说明.md`](deliverables/06-部署说明.md)；§7 快速开始 |
| 测试用例与复现步骤 | [`deliverables/07-测试与复现.md`](deliverables/07-测试与复现.md)；§9 测试与验证 |
| 安全自评报告：权限分级实现说明及已知风险清单 | [`deliverables/05-安全自评报告.md`](deliverables/05-安全自评报告.md) |
| 作品简介（≤ 200 字，含创作理念与 AI 技术） | 本文档开头（创作理念见 §1.1、AI 技术见 §1.4）；[`deliverables/01-作品简介.md`](deliverables/01-作品简介.md) |
| 答辩 PPT（≤ 10 分钟）与演示视频（≤ 5 分钟） | [`deliverables/03-AegisBank-答辩PPT.pptx`](deliverables/03-AegisBank-答辩PPT.pptx)（14 页，含备注；按 10 分钟设计，实际时长待排练）；[`deliverables/04-演示视频脚本.md`](deliverables/04-演示视频脚本.md)（脚本完成，成片待录制） |

---

## 3. 六场景覆盖

赛题要求至少覆盖 3 个核心场景、鼓励全覆盖。AegisBank 已实现 **6/6 场景方向覆盖**——六个方向均有可运行链路，但不等于赛题示例中每个子能力都完整实现（如 AA 为「本人垫付后向参与者分摊付款」，理财不含产品推荐与对比）：

| 场景 | 已实现的典型能力 | 风险分级示例 |
|---|---|---|
| 一、智能转账 | 按账户/联系人/别名/手机号转账；AA 拆分（本人垫付后向其余参与者分摊付款）并生成可并行的多步 DAG；定时/周期转账（到期由 `run_due_tasks` 执行，重复调用不重复扣款）；联系人多命中或未命中一律澄清，不猜测收款人 | 880 元黄色；同日再转 500 元使累计超过 1000 元后升级红色 + OTP；单笔 > 5000 元红色 |
| 二、账单分析 | 月度/年度账单（分类汇总、Top 商户、环比、异常说明）；异常检测（重复扣费、超预算、订阅金额突增、非活跃时段交易）；订阅扣费识别与续费提醒 | 纯查询，绿色自动执行 |
| 三、理财操作 | 5 个模拟产品（R1–R5）与风险测评；模拟持仓与收益；申购、赎回；接口返回 `simulated=true` 与免责声明 | 申购红色；赎回 ≤ 1000 元黄色 / > 1000 元红色 |
| 四、卡片管理 | 还款日调整、额度调整、单日交易限额设置/解锁、挂失/解挂、密码重置、虚拟卡申请与发卡 | 还款日/限额/虚拟卡黄色；额度或限额 > 5000 元、挂失、密码重置红色 |
| 五、订阅/代扣 | 订阅查询与风险标记；一键取消订阅；订阅扣费识别与续费提醒（站内提醒，无外部推送） | 查询绿色；取消黄色 |
| 六、跨场景联动 | 账单分析 → 取消异常订阅（步骤间变量引用）；生日准备 4 步 DAG（查生日 → 锁预算 → 鲜花 → 蛋糕，支持时间快进演示） | 锁预算、礼物预订黄色；取消定时任务、解锁预算绿色（补偿路径） |

示例指令：

```text
向 ACC-2002 转账 880 元
分析我的本月账单
买 1000 元稳健短债A
把 CARD-8821 的单日交易限额设置为 3000 元
取消异常订阅
帮我准备下个月妈妈的生日，预算 1000 元
```

跨场景 DAG 的步骤间通过 `${steps.step-1.data...}` 引用前序结果，例如「分析我的账单并取消异常订阅」：

```text
step-1: query_bill
   │  data.suspicious_subscription_id
   ▼
step-2: cancel_subscription
```

生日准备则生成 4 步 DAG：`query_contact_birthday`（绿）→ `lock_budget_funds`（黄，可补偿解锁）→ 并行预约 `schedule_flower_order` 与 `schedule_cake_order`（黄，两者均只依赖前两步），礼物在生日前 2 天由 `run_due_tasks` 触发。全部数据为模拟数据，不产生真实资金变动。

---

## 4. 权限分级与安全机制

### 4.1 绿 / 黄 / 红三级权限分级

| 等级 | 判定（确定性演示规则） | 系统行为 |
|---|---|---|
| 🟢 绿色 | 只读查询或低风险、无资金副作用：余额、账单、持仓、订阅、联系人查询、账单报告、异常检测、风险测评 | 最小权限满足后直接执行，不弹确认 |
| 🟡 黄色 | 会修改账户设置、订阅状态、预算或小额动账：单笔转账 ≤ 5000 元且当日累计（含本次）≤ 1000 元；改还款日；额度/限额调整 ≤ 5000 元；取消订阅；虚拟卡申请/发卡；理财赎回 ≤ 1000 元；预算锁定、生日礼物预订 | 创建待确认动作，用户在有效期内确认一次后执行 |
| 🔴 红色 | 资金变动、账户安全或高风险设置：单笔转账 > 5000 元，或当日累计将 > 1000 元；挂失/解挂；密码重置；理财申购；赎回 > 1000 元；额度/限额调整 > 5000 元；定时转账 > 1000 元 | 确认 + 二次身份校验（演示 OTP / 模拟生物识别）+ `ActionEnvelope` 执行前复核 |

> 以上阈值是确定性演示规则，不是生产反欺诈、信用评分或监管风控模型。风险结果会同时出现在 Agent 响应、计划步骤的 `risk_level / risk_reasons`、待确认动作、审计记录与前端风险徽标中。
>
> 口径说明：赛题权限分级示例把「订阅查询/取消」归入黄色；本项目按「只读纯查询不弹确认」原则将订阅查询归绿色、取消订阅归黄色。该差异已在 [安全修复记录](docs/REMEDIATION-PLAN-2026-10-23.md) 中标注，等待组委会口径确认。

### 4.2 统一网关、确认绑定与状态机

**唯一网关**：所有工具调用只有一条入口，检查顺序固定为「注入拦截 → 角色能力 → 工具授权 → 分级决策」；任一节点被拒绝，整条 DAG 阻断并写 `gateway_blocked` 审计。

**风险只升不降**：`final_level = max(工具基线, 动态规则)`，任何模型输出都不能降低风险等级。

**确认绑定**：黄色/红色操作为每个计划节点生成 `ActionEnvelope/v1`，绑定 `plan_hash`、`arguments_hash`、风险等级、最小权限、一次性 `nonce` 与过期时间；执行前服务端逐项复核，任一不一致返回 `409` 且不执行、不写业务流水。

**确认后复检**：确认与执行之间会再次调用网关复检角色、权限与风险；等待确认期间被撤权、触发熔断或风险升级都会被拦截。

**幂等与状态机**：`Idempotency-Key` 防止重复提交与重复扣款；任务状态机覆盖 `DRAFT / AWAITING_CONFIRMATION / AWAITING_REAUTH / APPROVED / EXECUTING / PAUSED / COMPLETED / FAILED / REJECTED / EXPIRED / UNKNOWN / RECONCILED / ROLLED_BACK` 共 13 态。`UNKNOWN` 不自动重试，必须人工对账或回滚，不会把「结果未知」伪装成成功或失败。

**Readiness fail-closed**：`GET /api/health/ready` 检查 SQLite、审计链、Mock 种子与 Planner；未就绪时写操作返回 `503`，前端同时禁用写操作。

**中断、回退与人工接管**：支持节点间暂停/恢复（恢复不重复已执行步骤）、失败后逆序补偿、执行 journal 查询、`UNKNOWN` 人工对账与回滚；补偿执行前经网关复检，不可逆步骤阻止自动回滚并转人工对账。

### 4.3 安全机制清单

| 机制 | 实现要点 | 当前边界（如实说明） |
|---|---|---|
| 幻觉与越权防护 | Planner 只出计划；Compiler 校验工具/Schema/步骤/环；模型输出字段白名单，冲突转澄清；工具回执必须 `simulated=true` 并通过输出 Schema | 规则意图覆盖有限；LLM 为可选依赖；不是通用事实核查器 |
| Prompt 注入拒绝 | 规划前与节点级各扫描一次，命中即整条拒绝并审计；注入命中累计熔断 | 字符规则基线，可被改写、编码或多轮方式绕过；不能替代专用注入分类器 |
| 统一权限网关 | 注入 → 角色能力 → 工具授权 → 分级决策，任一拒绝整条阻断；确认与补偿执行前复检 | `X-Aegis-Role` 是自报请求头，不是认证 |
| 确认绑定 | `ActionEnvelope/v1` 绑定计划哈希、参数哈希、风险、权限、`nonce`、过期时间；执行前 9 项复核，不一致 `409` | 演示级审批令牌；无生产级密钥托管 |
| 幂等与状态机 | 幂等键重放首次结果；13 态状态机；`UNKNOWN / RECONCILED / ROLLED_BACK` 分离对账结论与真实补偿 | 幂等键、`nonce` 无 TTL 清理；单机 SQLite |
| 审计与证据分层 | 六字段审计 + 四类证据来源（Mock 数据 / 人工确认 / 策略判断 / 审计链）+ SHA-256 哈希链在线校验 | 本地可验证审计，不是 WORM 监管存储；高权限者可重算整链 |
| 可疑行为熔断 | 连续失败、短时多次红色操作、注入命中累计三类规则共用 open 状态；写操作 fail closed；operator 解锁留痕 | 系统级计数，未按用户/租户分桶 |
| 可插拔 MFA | OTP + 模拟生物识别；策略按风险等级与敏感工具给出提示，执行取允许 provider 交集；成功/失败均入审计 | 固定演示 token；错误计数进入系统级熔断，但无按用户的失败锁定与速率限制 |
| 工具沙箱 | `ToolExecutor` + `ExecutionGuard`：超时、socket 级网络阻断、入参 8 KB / 出参 64 KB、可选白名单；违规先写审计再拒绝；不执行任意生成代码 | 进程内演示级守卫，不是 OS 容器；无内存/CPU/文件系统隔离 |
| 渠道复用同一链路 | `im / cli / webhook` 复用同一 Planner、风险、网关、MFA 与审计；`message_id` 幂等 | 未校验 IM 平台签名；`sender_id` 未与真实用户绑定 |
| 补偿与回退 | 28 条补偿规格（15 可补偿 / 13 不可逆）；逆序补偿；补偿前网关复检；不可逆步骤阻断 | 仅覆盖已登记规格；部分红色补偿需二次校验并转人工 |
| 多角色与撤权 | `user / operator / auditor` 能力矩阵；operator 可解锁熔断与紧急撤权但不能执行银行工具；auditor 只读；撤权立即阻断并留痕 | 角色能力由 `AuthzService` 统一口径，前端只做展示 |

### 4.4 2026-10-23 安全复审与修复

交付前，项目对照赛题要求与安全边界做了一轮系统复审：隔离复现了 **37 项后端问题与 11 项前端问题**（含漏洞、数据正确性与体验缺陷），逐项修复并补齐回归。在首轮修复之后，最终复核又追加了两项正常用户流程反例（理财申购后全额赎回再回滚、本人账户互转后回滚），修复后通过。重点加固包括：

- **账本/审计/执行事务原子性**：工具副作用、成功审计与 journal 统一事务，任一提交点故障不得出现「扣款但失败且无证据」；
- **并发资金安全**：事务内条件扣款与受影响行校验，并发转账不出现负余额；并发回滚与恢复最多一次冲正；
- **累计风险不可绕过**：计划预估累计暴露，逐节点复核授权风险上限；DAG 多笔累计与定时转账覆盖同一确定性风险链；
- **授权逐步骤复核**：撤权、熔断、失效确认在恢复/执行前重新校验，只读角色不能写状态；
- **MFA 与通道隔离**：错误强验证计数进入熔断，provider 必须在策略允许交集内；IM 确认绑定通道/发送者/动作/角色；
- **输入与输出契约**：金额必须为有限数且精确到分，缺参不补默认金额；50 个工具均有业务字段输出 Schema，坏输出不提交；
- **确认绑定完整**：`ActionEnvelope` 必须与计划步骤一一对应，缺失或重复一律 `409`。

2026-10-23 验证记录：新增后端安全回归 43 项（`backend/tests/test_security_regressions.py`）、前端 React/jsdom 回归 8 项与 API 回归 3 项；全量后端 187 项、前端 53 项、六场景 29/29、门禁五阶段 PASS、依赖扫描 0 项已知漏洞。逐项复现与原代码位置见 [安全修复记录](docs/REMEDIATION-PLAN-2026-10-23.md)。

> 安全复审只能覆盖已确认的问题与反例，不承诺系统不存在其他漏洞；这不是渗透测试或生产安全认证。

---

## 5. 系统架构

### 5.1 端到端架构

```text
┌─────────────────────────────────────────────────────────────┐
│ React 19 + TypeScript + Vite 控制台                          │
│ 银行概览 │ 六场景面板 │ 任务控制台 │ 权限控制台 │ 2A/运维/审计 │
└────────────────────────────┬────────────────────────────────┘
                             │ /api（readiness 未就绪时禁用写操作）
┌────────────────────────────▼────────────────────────────────┐
│ FastAPI + Pydantic                                          │
│                                                             │
│  Planner（rule / OpenAI-compatible LLM / auto fallback）     │
│      │ ExecutionPlan/v1                                     │
│      ▼                                                      │
│  Plan Compiler ── Schema / 工具注册 / DAG / plan_hash         │
│      │                                                      │
│      ▼                                                      │
│  DagScheduler ── 注入拒绝 / 幂等 / 熔断 / 依赖排序 / 暂停     │
│      │                                                      │
│      ├── DynamicRiskEngine ── 金额 / 累计 / 产品 / 操作类型   │
│      ├── PermissionGateway ── 最小权限 / 注入拦截 / 角色能力  │
│      ├── Trust ── Envelope / 状态机 / 证据 / readiness / MFA  │
│      │                                                      │
│      ▼                                                      │
│  ToolExecutor + ExecutionGuard（进程内沙箱：超时/网络/体积）  │
│      │                                                      │
│      ▼                                                      │
│  50 个银行工具（核心 10 + 场景 26 + 2A 扩展 14）              │
│      │      scenario：wealth / transfers / bills /          │
│      │                cards / automation（自动发现）          │
│      │      extensions：compensation / authz / breaker /     │
│      │                  mfa / sandbox / im                   │
│      │      channels：IM / CLI / webhook 复用同一链路        │
│      ▼                                                      │
│  BankingRepository（SQLite Mock Bank Core）                  │
│      │                                                      │
│      ▼                                                      │
│  AuditService ── 证据分层 + SHA-256 哈希链 / 完整性校验        │
└─────────────────────────────────────────────────────────────┘
```

![AegisBank 系统架构图（PNG）](docs/architecture/aegisbank-architecture.png)

完整模块边界、数据流与计划契约见 [架构说明](docs/ARCHITECTURE.md)、[银行领域模型与六场景闭环](docs/BANKING-DOMAIN.md) 和 [完整架构图 PNG](docs/architecture/aegisbank-architecture.png)。

### 5.2 核心机制与算法说明

| 机制 | 实现 | 关键点 |
|---|---|---|
| 结构化计划与编译 | `planning/` | `ExecutionPlan/v1` 计划契约；Compiler 校验工具注册、参数 Schema、步骤 ID、依赖与环，拓扑排序后生成 `plan_hash`；Preview 接口只出计划不执行 |
| 动态风险引擎 | `risk.py`、`risk_rules.py` | 读取金额、当日累计、产品风险等级、操作类型等确定性事实，输出等级/评分/可解释原因；只允许保持或上调基线风险 |
| 统一权限网关 | `gateway.py` | 注入扫描、角色能力、最小权限、分级决策四步；所有工具调用唯一入口；返回 allow / confirm / deny |
| 确认绑定 | `trust/action_envelope.py` | `ActionEnvelope/v1` 逐节点绑定计划与参数哈希、风险、权限、nonce、过期时间；执行前重新编译并复核，不一致 `409` |
| 幂等 | `trust/idempotency.py` | 同一 `Idempotency-Key` 返回首次结果；同键异体 `409`；并发同键原子占有 |
| 状态机与对账 | `trust/state_machine.py`、`scheduler.py` | 13 态迁移全部审计；`UNKNOWN` 需人工对账；对账结论与真实补偿分离 |
| 执行收口与沙箱 | `executor.py`、`trust/sandbox.py` | 工具副作用经 `ToolExecutor` + `ExecutionGuard`；违规先审计再抛错；补偿工具同样经网关复检 |
| 审计哈希链 | `audit.py` | `entry_hash = SHA-256(prev_hash + canonical(entry))`；证据写入并参与哈希；全链可在线校验 |
| 模块自动发现 | `scenarios/`、`extensions/` | 场景/扩展模块自带 schema、种子、工具、意图、风险规则与路由，自动装配，新增能力不改核心文件 |

### 5.3 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.11+ · FastAPI · Pydantic | API、工具 SDK、动态风险、权限网关、信任层与 DAG 调度 |
| Planner | Rule + OpenAI-compatible LLM | 结构化 `ExecutionPlan/v1`，可插拔、可回退、可校验 |
| 持久化 | SQLite（stdlib） | 本地零依赖；保存 Mock Bank Core、授权、待确认动作、信任状态与审计链 |
| 前端 | React 19 · TypeScript · Vite | 银行概览、六场景面板、2A 能力、运维面板、任务控制台、权限控制台、操作审计七个页面 |
| 测试 | pytest · httpx · Vitest | 后端 200 项（16 个文件）、前端 53 项（7 个文件） |

### 5.4 工具目录

核心工具 **10 个**：

| 工具 | 权限 | 基线风险 | 作用 |
|---|---|---|---|
| `query_balance` | `account:read` | 绿色 | 查询账户余额快照 |
| `query_bill` | `billing:read` | 绿色 | 账单分析、分类与异常订阅识别 |
| `transfer` | `transfer:execute` | 黄色 | 智能转账，按金额与日累计动态升级 |
| `adjust_repayment_date` | `card:manage` | 黄色 | 修改信用卡还款日 |
| `adjust_card_limit` | `card:manage` | 黄色 | 调整卡片额度，超过阈值升级红色 |
| `set_transaction_limit` | `card:manage` | 黄色 | 设置单日交易限额 |
| `report_card_lost` | `card:security` | 红色 | 卡片挂失 |
| `unlock_card` | `card:security` | 红色 | 卡片解挂 |
| `list_subscriptions` | `subscription:read` | 绿色 | 查询订阅与风险标记 |
| `cancel_subscription` | `subscription:manage` | 黄色 | 取消指定订阅 |

场景工具 **26 个**（理财 5、转账 3、账单 4、卡片 4、自动化 10）；阶段 2A 扩展工具 **14 个**（反向工具 + 演示工具）；合计 **50 个**。完整清单、可补偿/不可逆映射与风险规则见 [BANKING-DOMAIN.md](docs/BANKING-DOMAIN.md) §3。

### 5.5 关键接口

后端当前共 **49 个** `/api` 路径（`create_app().openapi()` 实测），以下为关键入口：

```text
GET  /api/banking/overview            银行概览：账户、卡片、订阅与异常提示
GET  /api/tools                       工具目录与当前授权状态（50 个工具）
GET  /api/planner/info                Planner 模式、工具与计划契约
POST /api/planner/plan                仅预览结构化计划，不执行工具
POST /api/agent/run                   规划、风险评估、网关校验并执行（支持 Idempotency-Key）
POST /api/confirmations/{action_id}   确认/拒绝待执行动作，红色动作校验演示 OTP（支持 Idempotency-Key）
GET  /api/permissions                 权限列表
PUT  /api/permissions/{tool_name}     授予或撤回工具权限
GET  /api/audit                       查看审计记录（含证据分层）
GET  /api/audit/verify                校验 SHA-256 审计哈希链
GET  /api/health/ready                就绪检查（sqlite / audit_chain / mock_bank_seed / planner）
GET  /api/trust/actions/{action_id}   查询任务状态机历史与掩码 envelope
POST /api/trust/actions/{action_id}/reconcile   UNKNOWN 人工对账（operator）
GET  /api/trust/circuit-breaker       熔断状态
GET  /api/actions/{action_id}/journal 执行日志
POST /api/actions/{action_id}/pause|resume|rollback  暂停 / 恢复 / 人工回退
GET  /api/compensation/specs          补偿规格目录
POST /api/compensation/demo/run       回退补偿演示（reversible/irreversible/compensation_failure/success）
GET  /api/mfa/providers|policy        MFA Provider 与策略
POST /api/sandbox/demo/run            沙箱演示（network/slow/oversize）
POST /api/channels/im/message         IM/CLI/webhook 消息入口
GET  /api/authz/roles|me              角色能力矩阵与当前能力
POST /api/authz/revoke/{tool_name}    紧急撤权
GET  /api/wealth/products|holdings|orders      理财（模拟数据）
GET  /api/bills/report | /api/bills/anomalies  账单报告与异常
GET  /api/subscriptions/charges | /api/subscriptions/reminders  扣费识别与续费提醒
GET  /api/cards/applications          虚拟卡申请
POST /api/automation/run-due          演示时间快进：执行到期定时任务（支持 now 参数）
```

---

## 6. 界面预览

以下为界面截图（来自本地运行中的控制台）与产品介绍页渲染图，存放于 `docs/screenshots/`。

### 银行概览

![AegisBank 银行概览](docs/screenshots/banking-overview.png)

### 任务控制台

![AegisBank 任务控制台](docs/screenshots/task-console.png)

### 操作审计

![AegisBank 操作审计](docs/screenshots/audit.png)

更多真实界面：[确认/MFA 弹窗](docs/screenshots/confirmation-modal.png) · [权限控制台](docs/screenshots/permissions.png) · [银行概览移动端](docs/screenshots/banking-overview-mobile.png) · [产品介绍页渲染图](docs/screenshots/product-overview.png)。截图规范见 [docs/screenshots/README.md](docs/screenshots/README.md)。

---

## 7. 快速开始

前置条件：

- Python 3.11+、`uv`
- Node.js 22.22.2+（22.x）、24.15.0+（24.x）或 26.0.0+、`pnpm`
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
- 就绪检查：<http://127.0.0.1:8000/api/health/ready>

也可以分别启动：

```bash
# 终端 1：后端（默认只监听回环地址）
cd backend
uv run uvicorn aegisbank_api.main:app --reload --host 127.0.0.1 --port 8000

# 终端 2：前端
cd frontend
pnpm dev
```

> 演示数据（含 3000 元虚拟卡 `ACC-3003` / `CARD-9001`）需先执行 `bash scripts/seed-demo.sh`，并让后端指向该文件的**绝对路径**（例如 `/home/<user>/aegisbank/backend/data/dogfood.db`）；`scripts/dev.sh` 默认使用 `backend/data/aegisbank.db`。详见 [`deliverables/06-部署说明.md`](deliverables/06-部署说明.md) §3。

可选配置（复制根目录 `.env.example` 到 `backend/.env`；以下为可用变量示例，`.env.example` 只含基础项，其余可直接在 `backend/.env` 追加）：

```bash
AEGIS_DATABASE_PATH=data/aegisbank.db
AEGIS_DEMO_OTP=246810
AEGIS_CONFIRMATION_TTL_SECONDS=300
AEGIS_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AEGIS_PLANNER_MODE=rule   # rule | llm | auto
AEGIS_LLM_BASE_URL=
AEGIS_LLM_API_KEY=
AEGIS_LLM_MODEL=
AEGIS_AUTOMATION_ENABLED=false
AEGIS_CIRCUIT_BREAKER_THRESHOLD=3
AEGIS_CIRCUIT_BREAKER_WINDOW_SECONDS=60
AEGIS_CIRCUIT_BREAKER_LOCK_SECONDS=60
```

`rule` 模式完全本地、无模型依赖；`auto` 模式优先调用 LLM，不可用时自动回退到规则 Planner。

演示账号与凭据：用户 `demo-user`；红色操作演示 OTP `246810`；模拟生物识别 token `FACE-888888`；角色 `user / operator / auditor` 通过演示请求头 `X-Aegis-Role` 切换（不是真实认证）。

---

## 8. 评审演示路径

建议按以下顺序在 5–8 分钟内走完主要能力（全部为模拟数据）：

1. 打开银行概览，查看账户、卡片、订阅和异常标记；顶部就绪横幅显示四个组件 OK；
2. 任务控制台执行「分析我的本月账单」，观察分类汇总与异常订阅；
3. 执行「分析我的账单并取消异常订阅」，查看两步 DAG 与变量解析结果；
4. 执行「向 ACC-2002 转账 880 元」完成黄色确认；同日再转 500 元，观察累计风险升级为红色并输入演示 OTP `246810`；
5. 执行「买 1000 元稳健短债A」（红色 + OTP）与「给妈妈转 500 元」；场景数据页（只读）核对理财持仓、账单与订阅明细；
6. 执行「和妈妈、老爸、张三 AA 300 元（4 人）」，观察 3 笔并行转账 DAG；
7. 执行「帮我准备下个月妈妈的生日，预算 1000 元」，观察 4 步跨场景 DAG（查生日 → 锁预算 → 鲜花/蛋糕）；
8. 把时间快进到生日前 2 天（`POST /api/automation/run-due?now=2026-11-16T12:00:00%2B08:00`），观察鲜花/蛋糕到期下单与审计 `trigger_source=scheduled`；前端「时间快进」按当前时间执行，当前无到期任务时返回 0 条；
9. 权限控制台撤回某工具权限，再次执行应被网关阻断；
10. 操作审计页校验 SHA-256 哈希链并展开证据分层；
11. 演示回退补偿、熔断解锁、MFA 生物识别、IM 通道、沙箱拦截与多角色切换（前端 2A 能力页 / 运维面板，或对应 `/api` 端点）；执行不可逆回滚演示后，任务控制台会出现 `UNKNOWN` 与人工对账入口。

接口级快速验证（服务启动后）：

```bash
# 绿色：只读查询直接执行并返回证据
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"分析我的本月账单"}'

# 红色：挂失返回待确认动作，再用演示 OTP 完成确认
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"挂失 CARD-9902"}'

# 审计哈希链校验
curl -s http://127.0.0.1:8000/api/audit/verify

# 回退补偿演示：可逆 / 不可逆
curl -s -X POST 'http://127.0.0.1:8000/api/compensation/demo/run?mode=reversible'
curl -s -X POST 'http://127.0.0.1:8000/api/compensation/demo/run?mode=irreversible'
```

---

## 9. 测试与验证

当前后端补强见 [2026-10-24 记录](docs/BACKEND-HARDENING-2026-10-24.md)；历史复审记录保留当时快照。以下为当前验证口径：

| 指标 | 结果 | 复现命令 |
|---|---|---|
| 后端测试 | **200 passed**（16 个测试文件，含 56 项安全回归） | `cd backend && uv run pytest` |
| 前端测试 | **53 passed**（7 个测试文件，含 8 项 React/jsdom 安全回归） | `cd frontend && pnpm test` |
| 六场景端到端回归 | **29/29 PASS** | `cd backend && uv run python ../scripts/scenario-check.py` |
| 工具 / 接口 | **50 个工具 / 49 个 `/api` 路径** | `GET /api/tools`、`GET /api/planner/info`、`/docs` |
| 补偿规格 | **28 条（15 可补偿 / 13 不可逆）** | `GET /api/compensation/specs` |
| 审计链 | `{"valid": true, "checked": N}` | `GET /api/audit/verify` |
| 门禁 | encoding / lint / build / test / security **五阶段 PASS** | 维护者 DSH gate（仓库外脚本）；等价验证：`bash scripts/lint.sh` + `build.sh` + `test.sh` + 依赖扫描 |
| 依赖扫描 | 扫描当时 `pnpm audit`（全量）与 `pip-audit`（生产依赖）均 **0 项已知漏洞**；零命中不证明不存在未知漏洞 | 见 [安全修复记录](docs/REMEDIATION-PLAN-2026-10-23.md) |

工程命令：

```bash
bash scripts/lint.sh    # 后端 ruff + 前端 TypeScript 类型检查
bash scripts/build.sh   # 后端 compileall + 前端 Vite 生产构建
bash scripts/test.sh    # pytest（200 项）+ Vitest（53 项）
bash scripts/smoke.sh   # 启动 API，跑一条绿色链路并校验审计链
```

> 自动化测试通过只说明已知用例可复现，不等同于人工测试完成、渗透测试通过或生产安全验收。阶段 2.5（人工体验回归）已推迟，本轮不声称已完成人工验收。

---

## 10. 参赛交付物

| 编号 | 交付物 | 位置 | 状态 |
|---|---|---|---|
| 01 | 作品简介（≤ 200 字，含压缩版） | [`deliverables/01-作品简介.md`](deliverables/01-作品简介.md) | ✅ 已完成 |
| 02 | 技术文档（架构图 / 核心算法 / 安全设计） | [`deliverables/02-技术文档.md`](deliverables/02-技术文档.md) | ✅ 已完成 |
| 03 | 答辩 PPT（14 页，含备注；按 10 分钟设计） | [`deliverables/03-AegisBank-答辩PPT.pptx`](deliverables/03-AegisBank-答辩PPT.pptx) | ✅ 已生成；实际汇报时长待排练 |
| 04 | 演示视频（≤ 5 分钟）分镜与口播稿 | [`deliverables/04-演示视频脚本.md`](deliverables/04-演示视频脚本.md) | ⚠️ 未完成：脚本完成，成片待录制 |
| 05 | 安全自评报告（权限分级 + 已知风险清单） | [`deliverables/05-安全自评报告.md`](deliverables/05-安全自评报告.md) | ✅ 已完成 |
| 06 | 部署说明（环境、启动、配置、排障） | [`deliverables/06-部署说明.md`](deliverables/06-部署说明.md) | ✅ 已完成 |
| 07 | 测试与复现（用例矩阵、命令、预期输出） | [`deliverables/07-测试与复现.md`](deliverables/07-测试与复现.md) | ✅ 已完成 |
| — | 架构图（PNG / SVG / Mermaid）与界面截图 | [`docs/architecture/`](docs/architecture/)、[`docs/screenshots/`](docs/screenshots/) | ✅ 架构图已完成；⚠️ 截图待阶段 2.5 更新 |

交付包总索引见 [`deliverables/README.md`](deliverables/README.md)。

---

## 11. 已知边界与生产化清单

AegisBank 是**安全自治 Agent 的可运行原型**，以下边界是刻意保留并主动声明的：

- **模拟银行数据**：全部账户、卡片、交易、账单、订阅、理财、余额与转账结果为 Mock Bank Core 模拟数据，不连接真实银行接口，不产生真实资金变动；理财内容不构成投资建议；
- **无真实身份认证**：固定演示用户 `demo-user`，未接入登录、会话、设备指纹或真实身份服务；`X-Aegis-Role` 由客户端自报，服务端只做角色能力与权限校验；
- **Web 与 IM 渠道**：内置响应式 Web 控制台（未打包原生 APP）与 `im / cli / webhook` 模拟适配器；IM 适配器未校验平台签名，`sender_id` 未与真实用户绑定；
- **演示级 MFA**：固定 OTP `246810`、模拟生物识别 token `FACE-888888` 与演示审批令牌仅用于本地流程展示；错误强验证会计数并进入系统级熔断，但没有按用户的失败锁定、速率限制与生产级抗重放；
- **演示级风险规则**：动态风险引擎是确定性规则，不是生产反欺诈、信用评分或监管风控模型；
- **进程内沙箱**：socket 级网络阻断、线程超时、入参/出参体积与白名单，不是 OS 容器；Python 线程无法强杀，超时后数据库外副作用仍依赖 OS 隔离；本项目只执行注册工具，不提供任意生成代码入口；
- **单机持久化**：SQLite 适合本地原型，不满足银行级高可用、容灾与隔离；幂等键、`used_nonces` 与 `im_messages` 无 TTL 清理；熔断为系统级计数；
- **有限安全防护**：注入检测、权限网关、`ActionEnvelope`、幂等与哈希链是基线，不替代专用安全策略引擎、OS 沙箱、限流、CSRF/mTLS 与渗透测试；本地哈希链只能发现记录级篡改，不是 WORM；
- **补偿有边界**：只覆盖已登记的 28 条规格；不可逆步骤阻止自动回滚；部分红色补偿需二次校验并转人工对账；
- **LLM 可选**：规则 Planner 离线可用；接入 OpenAI-compatible 模型时仍需经过同一 Compiler、候选白名单、风险引擎与权限网关；
- **意图理解有限**：已支持限时单次缺参续问与否定/多意图冲突澄清，通用指代消解与长会话尚未实现；
- **演示视频与截图**：视频成片待录制，阶段 2.5 人工体验回归已推迟，后续统一更新截图。

上生产前仍需完成的关键项（P0/P1）：真实身份认证与租户隔离、真实 MFA、OS 级沙箱、HA 数据库、按用户熔断、可取消执行、IM 平台签名、WORM 审计与外部锚点、限流与安全响应头、TTL 清理、故障矩阵与压力测试。完整清单见 [`deliverables/05-安全自评报告.md`](deliverables/05-安全自评报告.md) §4。

当前阶段状态：

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 产品边界与仓库定型 | ✅ 已完成 |
| 1 | 信任工程（Envelope / 幂等 / 状态机 / readiness / 证据分层 / 注入整条拒绝 / 模型白名单 / 熔断骨架） | ✅ 已完成 |
| 2A | 赛题硬要求（回退补偿、可疑行为熔断、沙箱、MFA Provider、IM、多角色） | ✅ 已完成 |
| 2B | 六场景完整覆盖 | ✅ 已完成（6/6） |
| 2.5 | 人工体验回归（Dogfooding） | 已推迟：第一轮记录见 [`docs/UX-RECORD.md`](docs/UX-RECORD.md)，第二轮安全/异常路径与截图更新待做 |
| 3 | 参赛交付材料 | 材料已产出（见 `deliverables/`）；视频待录制 |

---

## 12. 文档索引与许可

### 12.1 文档索引

- [项目总规划（Master Plan）](docs/MASTER-PLAN.md)
- [产品路线图](docs/ROADMAP.md)
- [架构说明（模块边界、信任层与扩展契约）](docs/ARCHITECTURE.md)
- [银行领域模型与六场景闭环](docs/BANKING-DOMAIN.md)
- [安全边界、信任层实现与生产化清单](docs/SECURITY.md)
- [2026-10-23 安全复审与修复记录](docs/REMEDIATION-PLAN-2026-10-23.md)
- [开发工具与技术栈](docs/TECH-STACK.md)
- [开发环境与验收记录](docs/DEVELOPMENT-ENVIRONMENT.md)
- [人工用户体验（Dogfooding）](docs/UX-DOGFOODING.md)
- [新手教程（第一次使用）](docs/NEWBIE-TUTORIAL.md)
- [上游设计参考说明](docs/UPSTREAM-NOTES.md)
- [单文件产品介绍页](docs/product-overview.html)
- [真实截图目录](docs/screenshots/README.md)
- [完整架构图 PNG](docs/architecture/aegisbank-architecture.png) ｜ [Mermaid 源文件](docs/architecture/aegisbank-architecture-v2.mmd)

> 部分历史规划/环境文档（如 MASTER-PLAN、DEVELOPMENT-ENVIRONMENT）保留阶段性数字（48 个工具、144 项测试、27 条补偿规格等），当前口径以本 README、[后端补强记录](docs/BACKEND-HARDENING-2026-10-24.md) 与实际测试输出（50 / 200 / 28）为准；deliverables 为 2026-10-23 交付快照，后续补强以本 README 和补强记录为准。

### 12.2 贡献

欢迎通过 Issue / Pull Request 参与：[CONTRIBUTING.md](CONTRIBUTING.md)。

### 12.3 License

本项目采用 [MIT License](LICENSE)。

Copyright (c) 2026 LQZ5885
