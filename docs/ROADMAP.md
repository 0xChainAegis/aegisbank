# AegisBank 产品路线图

> 2026-10-29 F0收尾：卡片受控解析、按用户熔断、到期任务补验证、上海业务时区和账务口径已合入；新增元旦凌晨的日/月累计与 SemanticFrame/定时跨年回归。当前验收为后端631项、前端136项、组装器18项、六场景30/30。U1正式保留集和真实模型效果仍未验收，生产化边界不变。

> 2026-10-28 P1补缺：关闭完整句回退与无tool参数旁路，新增槽位参数绑定、上海午夜一致性及扩展口语回归。工程实现已补强，正式开放表达与真实模型泛化验收仍待完成；P2–P4边界保持。详见 [补缺验收](NLP-P1-COMPLETION-2026-10-28.md)。

> 2026-10-27 NLP P1 有界语义模块已落地：候选契约、槽位来源、受控实体、金额/UTC 日期、否定作用域和哈希绑定。P1 泛化验收未完成，P2–P4 未实施；本轮集成团队主线 `43fe645`，验收与限制见 [P1 报告](NLP-P1-2026-10-27.md)。

> 2026-10-26 六模块版与可运行修复版整合：六包目录保留，通过 `scripts/assemble.py` 生成运行工程，补齐测试、CI、参赛文件和图片。详情见 [整合记录](INTEGRATION-2026-10-26.md)。NLP 待办和生产化边界保持不变。

> 2026-10-26：协作集成主线迁入 `0xChainAegis/aegisbank`，原作者历史保留。NLP P1–P4 仍未实施，已拆分为 [独立待办和验收标准](NLP-BACKLOG.md)，本轮仅整理，不承诺赛前全部完成。

> 2026-10-25 前端复验完成一轮：确认恢复与 MFA、六场景入口、状态展示与请求竞态已修复；前端 73 项、后端 252 项、六场景 29/29、15 个实际入口通过。详见 [本轮修复与验收](FRONTEND-REPAIR-2026-10-25.md)。视频和更广泛的人工体验测试仍待开展。

> 2026-10-25 NLP P0 已实现：完整金额规范化、条件/组合任务澄清与多入口校验；新增 52 项 NLP 回归。该段为 P0 历史快照，P1 当前进展见上方报告，通用指代与自由组合仍待完善。见 [核验、实现与复现](NLP-ASSESSMENT-AND-PLAN-2026-10-25.md#6-p0-落地2026-10-25)。

> 2026-10-24 后端补强：新增 13 项回归，当时后端 200 项；补偿不覆盖后续设置、红色恢复需 MFA、权限写入与审计原子提交。详见 [补强记录](BACKEND-HARDENING-2026-10-24.md)。生产化剩余项维持下列清单。

> v1.5 安全复审：已修复记录见 [REMEDIATION-PLAN-2026-10-23.md](REMEDIATION-PLAN-2026-10-23.md)。既往阶段记录保留当时快照，当前状态以本轮验收为准。已支持 10 分钟、绑定用户与角色、单次消费的澄清续问；通用指代与长会话仍待完善。
> 总规划与阶段详细设计见 [MASTER-PLAN.md](MASTER-PLAN.md)。
> 最近更新：2026-10-29（F0 收尾：补齐跨年验收并同步当前验证基线；历史阶段记录保留当时快照）。

## 状态速览

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 产品边界与仓库定型 | ✅ 已完成 |
| 1 | 信任工程（ActionEnvelope / 幂等 / 状态机 / readiness / 证据分层 / 注入整条拒绝 / 模型候选白名单） | ✅ 已完成 |
| 2A | 比赛硬要求（回退补偿、MFA Provider、IM、沙箱、多角色） | ✅ 已完成 |
| 2B | 六场景完整覆盖（理财 / 转账形态 / 账单深度 / 卡片补齐 / 订阅深度 / 生日联动） | ✅ 已完成 |
| 2.5 | 人工用户体验（开发者 Dogfooding） | 🔄 进行中（第一轮完成，见 `docs/UX-RECORD.md`） |
| 3 | 比赛交付（简介、PPT、视频、安全自评、部署说明） | ✅ 材料已产出（视频待录制、截图待更新） |

### 历史验证基线（2026-10-25；当前结果见 P1 报告）

| 指标 | 数值 | 来源 |
|---|---|---|
| 后端测试 | **252 项** pytest（17 个测试文件；含本轮 52 项 NLP 回归） | `cd backend && uv run pytest -p no:warnings` |
| 其中信任层 | **17 条** | `backend/tests/test_trust.py` |
| 其中 2A | **51 条**（authz 9 / breaker 7 / compensation 10 / im 7 / mfa 10 / sandbox 8） | `backend/tests/test_{authz,breaker,compensation,im_channel,mfa,sandbox}.py` |
| 前端测试 | **73 项** Vitest 全部通过（8 个测试文件） | `frontend/src/**/*.test.*` |
| 银行工具 | **50 个**（核心 10 + 场景 26 + 2A 扩展 14；compensable=15） | `GET /api/tools` |
| 补偿规格 | **28 条**（15 可补偿 + 13 不可逆） | `GET /api/compensation/specs` |
| HTTP 接口 | **49 个**（2A 新增 20 个） | `create_app().openapi()` paths |
| 六场景覆盖 | **6/6** | [MASTER-PLAN.md](MASTER-PLAN.md) §4.6 |

> 工具数、测试数、接口数必须以代码或测试输出为准；变更实现后需重新核对。

## 阶段 0：产品边界与仓库定型（已完成）

目标：让 `LQZ5885/aegisbank` 成为独立产品仓库，而不是上游 AegisAgent 的附属 PR。

已完成：

- AegisBank 产品主线确定为银行 AI 智能体；
- 上游计划溯源 PR 材料从产品 `main` 移出，归档到 `archive/upstream-plan-provenance`；
- README 不再把上游 PR 作为产品入口；
- 产品、文档、截图、MIT License 和 GitHub 仓库已就绪；
- 工程文件补齐：`AGENTS.md`、`CONTRIBUTING.md`；
- 环境记录更新为 Linux ext4 主线（`docs/DEVELOPMENT-ENVIRONMENT.md`）；
- 新增 `docs/MASTER-PLAN.md` 作为项目总规划。

阶段 0 验收（2026-10-23）：`main` 不包含 `upstream-pr/`；lint / build / test 全绿；文档与实现一致。当时基线为后端 20 项 pytest、前端 7 项 Vitest，已被本轮后端 144 / 前端 38 的新基线取代。

## 阶段 1：信任工程（已完成）

目标：把上游可借鉴的身份、策略、证据和状态恢复设计移植到 Python 银行 Agent，并把「确认后执行的是用户刚刚确认的那一笔」做成可验证契约。

已交付：

| # | 能力 | 实现位置 | 验收证据 |
|---|---|---|---|
| 1 | ActionEnvelope/v1：`plan_hash + arguments_hash + risk_level + permission + nonce + expires_at + user_id` 一次性绑定 | `backend/aegisbank_api/trust/action_envelope.py`；`scheduler.py` 发放与复核 | 篡改计划、过期、nonce 复用均 409 且不执行 |
| 2 | 幂等键与执行前持久化（`Idempotency-Key`，重复请求返回首次结果） | `trust/idempotency.py`；`db.py` 的 `idempotency_keys` | 同键重复提交只产生 1 个待确认动作；改正文 409 |
| 3 | 状态机扩展：`UNKNOWN / RECONCILED / ROLLED_BACK` 与非法迁移拒绝 | `trust/state_machine.py`；`pending_actions.state*` | 非法迁移抛错并写审计；UNKNOWN 不重复执行 |
| 4 | readiness 与 fail closed | `trust/readiness.py`；`GET /api/health/ready`；`/api/agent/run` 与确认接口 503 门禁 | 注入故障时写操作 503，前端禁用写操作 |
| 5 | 证据来源分层 | `trust/evidence.py`；API 的 `evidence/evidence_list` 与审计 `result_json` | 四类 `source` 与 `verified/verification_kind` 可查 |
| 6 | 注入整条拒绝 | `gateway.py` 的 `scan_injection`；`scheduler.py` 在 Planner 之前拒绝 | 命中即阻断、不生成计划、写审计 |
| 7 | 模型候选白名单与冲突校验 | `planning/llm.py` | 契约外字段/未注册工具拒绝；覆盖用户金额、编造收款方转澄清 |
| 8 | 异常熔断骨架（阶段 1 落骨架，2A 完善策略） | `trust/circuit_breaker.py`；`GET/POST /api/trust/circuit-breaker[/reset]` | 连续 3 次失败熔断，写操作被拒，可重置恢复 |

阶段 1 验收：`backend/tests/test_trust.py` 17 条用例覆盖 §8.7 的 12 类矩阵（另含熔断与可读 422），全部通过；接口新增 `GET /api/health/ready`、`GET/POST /api/trust/circuit-breaker[/reset]`、`GET /api/trust/actions/{action_id}`、`POST /api/trust/actions/{action_id}/reconcile`。

## 阶段 2B：六场景完整覆盖（已完成）

目标：把六场景覆盖从 5/6 补齐到 6/6，并让每个场景都有「自然语言 → 工具 → 风险分级 → 审计」的完整链路。

交付的五个可自动发现场景模块（`backend/aegisbank_api/scenarios/`）：

| 模块 | 场景 | 工具（风险基线） | 只读路由 | 测试 |
|---|---|---|---|---|
| `wealth.py` | 理财操作 | `list_wealth_products`(绿)、`query_wealth_holdings`(绿)、`assess_wealth_risk`(绿)、`purchase_wealth`(红)、`redeem_wealth`(黄/按金额升红) | `GET /api/wealth/products`、`/holdings`、`/orders` | `test_wealth.py` 11 条 |
| `transfers.py` | 智能转账形态 | `list_contacts`(绿)、`add_contact`(黄)、`transfer_to_contact`(黄/动态升红)；AA 拆分为并行 DAG | `GET /api/contacts` | `test_transfers.py` 10 条 |
| `bills.py` | 账单分析深化 | `bill_report`(绿)、`detect_bill_anomalies`(绿)、`identify_subscription_charges`(绿)、`list_renewal_reminders`(绿) | `GET /api/bills/report`、`/api/bills/anomalies`、`/api/subscriptions/charges`、`/api/subscriptions/reminders` | `test_bills.py` 8 条 |
| `cards.py` | 卡片管理补齐 | `apply_virtual_card`(黄)、`issue_virtual_card`(黄)、`reset_card_password`(红)、`unlock_transaction_limit`(黄/升红) | `GET /api/cards/applications` | `test_cards.py` 8 条 |
| `automation.py` | 跨场景联动与时间维度 | `query_contact_birthday`(绿)、`lock_budget_funds`(黄)、`unlock_budget_funds`(绿)、`schedule_flower_order`(黄)、`schedule_cake_order`(黄)、`schedule_transfer`(黄/升红)、`list_scheduled_tasks`(绿)、`cancel_scheduled_task`(绿)、`run_due_tasks`(绿) | `GET /api/automation/schedules`、`/goals`、`/orders`；`POST /api/automation/run-due` | `test_automation.py` 11 条（含 run-due readiness 503） |

配套基座与规则：

- `scenarios/__init__.py` 自动发现与装配（schema、seed、tools、routers、background 钩子），核心文件不随场景增加而改动；
- `scenarios/README.md` 记录模块契约与并行开发开关（`AEGIS_SCENARIO_ALLOW` / `AEGIS_SCENARIO_STRICT`）；
- 每个模块自带 `SCHEMA_SQL`、`seed`、`tools`、`intents`、`risk_rules`、只读 `router`；`automation` 额外提供 `start_background` / `stop_background`；
- 两条真实跨场景 DAG：账单分析 → 取消异常订阅；生日场景 `query_contact_birthday → lock_budget_funds → schedule_flower_order / schedule_cake_order`；
- 时间维度：`scheduled_tasks` + `POST /api/automation/run-due`（时间快进）+ 可选后台轮询线程（`AEGIS_AUTOMATION_ENABLED=true`），不做真实常驻 cron。

阶段 2B 验收：六场景 6/6；25 个场景工具全部继承 `BaseTool`、经统一网关、风险只升不降；每个场景至少覆盖正向链路、风险分级、撤权/失败与幂等种子；后端测试由 20 项增至 85 项（阶段 2A 后为 144 项）。

## 阶段 2A：比赛硬要求（已完成，2026-10-23）

阶段 2A 六项硬要求 + 收尾项与证据：

| # | 产物 | 实现 | 验收证据 |
|---|---|---|---|
| 1 | 步骤级暂停 / 回退 / 补偿 | `trust/pause.py`；`compensation.py` + `extensions/compensation.py`；`scheduler.py` 的 `run_dag / pause_action / resume_action / rollback_action / journal_view`；端点 `/api/actions/{id}/pause / resume / rollback / journal`、`/api/compensation/specs / demo/run` | 逆序补偿为 `ROLLED_BACK`；不可逆步骤阻止回滚；暂停恢复不重复已执行节点；`test_compensation.py` 10 条 |
| 2 | 异常熔断策略 | `trust/circuit_breaker.py` + `extensions/breaker.py`；连续失败 / 短时多次红色 / 注入命中累计共用 open 状态；端点 `/api/trust/breaker/events / policy / unlock` | 三次红色或三次注入命中触发；operator 解锁并写 `circuit_breaker_unlock`；`test_breaker.py` 7 条 |
| 3 | 工具执行沙箱 | `executor.py`（`ToolExecutor` / `ExecutionGuard`）+ `trust/sandbox.py` + `extensions/sandbox.py`；端点 `/api/sandbox/policy`、`/api/sandbox/demo/run` | 网络、超时、超大输出、超大入参、白名单拦截并写审计；`test_sandbox.py` 8 条 |
| 4 | 演示 MFA Provider | `trust/mfa.py` + `extensions/mfa.py`；OTP + 模拟生物识别 `FACE-XXXXXX`；端点 `/api/mfa/providers / policy / demo/challenge` | 红色确认可选 provider，审计记录方式与结果；`test_mfa.py` 10 条 |
| 5 | IM 渠道适配器 | `channels/im.py` + `extensions/im.py`；`im / cli / webhook`；端点 `/api/channels/im/message / help` | 绿色查询、红色挂失 + OTP、错误 OTP、`message_id` 幂等；`test_im_channel.py` 7 条 |
| 6 | 多角色与撤权 | `trust/authz.py` + `extensions/authz.py` + `gateway.py`；`X-Aegis-Role`；端点 `/api/authz/roles / me / revoke/{tool} / audit/policy` | operator/auditor 不能执行工具；撤权后重放被阻断并写 `role_revocation`；`test_authz.py` 9 条 |
| 7 | 信任层收尾 | `scenarios/automation.py` 的 `run-due` readiness 门禁 | 未就绪时 `POST /api/automation/run-due` 返回 503；`test_automation.py` 覆盖 |

阶段 2A 验收：后端 **144 项** pytest 通过（2A 新增 51 条 + 回归 8 条）；工具 **48 个**（compensable=15）；补偿规格 **27 条**（15 可补偿 / 12 不可逆）；HTTP 接口 **49 个**；`smoke.sh` 实测审计链 `valid=true`。赛题四项硬要求（熔断、沙箱、MFA、IM）均可一次走通。→ **满足**。

**仍未做（诚实标注）**：幂等 / `used_nonces` TTL 清理、OS 级容器隔离、真实身份认证与 MFA、真实 IM 平台签名与用户映射、工具执行中途强停。按用户熔断隔离已于 2026-10-27 完成。

**下一步**：阶段 2.5（Dogfooding）与阶段 3（比赛材料）。

## 阶段 2.5：人工用户体验（开发者 Dogfooding）

目标：在进入比赛材料制作前，让开发者像真实用户一样连续使用产品，发现交互、状态和恢复问题。

核心原则：

- 不按开发者熟悉的 API 顺序测试，而按用户任务测试；
- 每个场景都必须从第一次打开页面开始；
- 黄色确认、红色 MFA、撤权、审计必须一次性走通；
- 失败、空数据、离线、重复提交必须有可理解的状态；
- 记录真实摩擦，不以代码能跑代替用户能用。

三轮狗粮测试：

1. **第一轮：无脚本首次使用** —— 新开发者只读 README 启动；不看接口文档，完成六场景中的三个代表场景；记录所有卡点。
2. **第二轮：安全与异常路径** —— 撤权后重试、红色 OTP 错误、重复确认/刷新、服务离线/数据为空、readiness 非 ready、注入请求。
3. **第三轮：修复后回归** —— 重跑全部场景；更新真实截图；形成 UX 验收记录。

退出标准：三个代表场景从首次打开到完成均不超过 10 分钟；无 P0/P1 可用性阻塞；关键页面有 loading / empty / error 状态；确认、MFA、撤权、证据可被非开发者理解；真实截图与当前界面一致。

详细执行清单见 [UX-DOGFOODING.md](UX-DOGFOODING.md)。

### 第一轮执行结果（2026-10-23）

- 人工测试 + 静态审计 + 无头浏览器量测，产出 **36 项**分级缺陷（P0×7 / P1×17 / P2×10 / P3×2），记录在 [UX-RECORD.md](UX-RECORD.md)。
- 已合入批 1（止血）+ 批 2（闭环）+ 批 3 前端项：首屏入口、确认弹窗人话摘要与可退出、回执三层、hash 路由、刷新恢复、幂等键、错误码映射、移动端溢出、可读性与焦点、ErrorBoundary；`docs/UX-RECORD.md` §10 有逐条映射与验证证据。
- 验证：前端 **38 项** Vitest、`tsc --noEmit`、`vite build` 通过；全量 gate（encoding / lint / build / test / security）PASS，提交 `25027d8`。
- 尚未完成：第二轮安全/异常路径狗粮、第三轮截图与外部试用；推迟项见 UX-RECORD §10.2（UX-05/21/24/26/32/34 等）。

## 阶段 3：比赛交付

| 交付物 | 状态 | 文件 |
|---|---|---|
| 200 字作品简介 | ✅ 完成 | `deliverables/01-作品简介.md` |
| 技术文档（架构/算法/安全） | ✅ 完成 | `deliverables/02-技术文档.md` |
| 10 分钟答辩 PPT | ✅ 已生成（14 页） | `deliverables/03-AegisBank-答辩PPT.pptx` |
| 5 分钟演示视频 | ⏳ 脚本完成，待人工录制 | `deliverables/04-演示视频脚本.md` |
| 安全自评报告 | ✅ 完成 | `deliverables/05-安全自评报告.md` |
| 部署说明 | ✅ 完成 | `deliverables/06-部署说明.md` |
| 测试用例与复现 | ✅ 完成 | `deliverables/07-测试与复现.md` |
| 最终截图与演示数据 | ⏳ 界面已按阶段 2.5 修复，截图待第三轮统一更新 | 截图目录 / `scripts/seed-demo.sh` |


## 2026-10-23 安全复审修复批次

本轮在 Linux 主线工作分支完成代码修复：补偿内部化、动作并发占有、账本/成功审计/journal 原子性、累计风险与定时授权、确认归属与能力、MFA 熔断、IM 命名空间、提交截止、金额/卡片/预算/持仓不变量、输出契约、前端幂等恢复与 fail closed、限时单次澄清续问。新增后端 43 项安全回归，前端新增接口及 React/jsdom 测试；总计后端 187 / 前端 53，六场景 29 项。

当前清单为 50 个工具（核心 10 / 场景 26 / 扩展 14）、28 条补偿规格（15 可补偿 / 13 不可逆）、49 个 HTTP 操作。已升级 Vitest 与 certifi，依赖扫描结果见 [修复记录](REMEDIATION-PLAN-2026-10-23.md)。本批次的提交与发布记录以 Git 历史为准。

比赛仍需完成：≤5 分钟演示视频、实际答辩时长核验和截图更新；订阅纯查询的黄/绿口径仍需组委会解释。生产化与待验证风险单列，不以本轮回归代替真实认证、OS 隔离或生产安全验收。
