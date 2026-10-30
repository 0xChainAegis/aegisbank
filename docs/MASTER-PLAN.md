# AegisBank 总规划（Master Plan）

> 2026-10-30 U2 最小多轮闭环完成（仅联系人转账，最小范围）：新增会话草稿、金额补槽/修订、旧确认失效、版本 CAS 和本人最近转账回读；后端 646 项 pytest、前端 144 项 Vitest、组装器 18 项、六场景 30/30、工具 51 个、HTTP 路径 49 个。U1 正式人工复核与真实模型对照仍未完成；U3/U5 未实施。详见 [U2 报告](U2-CONVERSATION-2026-10-30.md)。
> 2026-10-30 U1离线评测与有界语义补强：304 条 AI 辅助静态金标按 76 个表达家族隔离；开发集完整计划语义 156/156，独立保留集 116/148（78.38%），新语义两组安全反例均 0/48 业务误写。真实模型对照为 `not_run`，正式人工复核为 `pending`，U1不整体关闭。详见 [U1 报告](U1-NLP-EVALUATION-2026-10-30.md)。

> 2026-10-29 F0收尾：卡片受控解析、按用户熔断、到期任务补验证、上海业务时区和账务口径已合入；新增元旦凌晨的日/月累计与 SemanticFrame/定时跨年回归。当前验收为后端631项、前端136项、组装器18项、六场景30/30。U1正式保留集和真实模型效果仍未验收，生产化边界不变。

> 2026-10-28 P1补缺：关闭完整句回退与无tool参数旁路，新增槽位参数绑定、上海午夜一致性及扩展口语回归。工程实现已补强，正式开放表达与真实模型泛化验收仍待完成；P2–P4边界保持。详见 [补缺验收](NLP-P1-COMPLETION-2026-10-28.md)。

> 2026-10-27 NLP P1 有界语义模块已落地：候选契约、槽位来源、受控实体、金额/UTC 日期、否定作用域和哈希绑定。P1 泛化验收未完成，P2–P4 未实施；本轮集成团队主线 `43fe645`，验收与限制见 [P1 报告](NLP-P1-2026-10-27.md)。

> 2026-10-26 六模块整合：保留 `NLP/agent/backend/fronted/plans/skills` 源码职责目录，加入确定性组装入口生成 `.runtime/`；前端修复与被分类包排除的回归测试已恢复。当前目录、运行与验证流程见 [整合记录](INTEGRATION-2026-10-26.md)；运行目录不作为另一条开发主线。

> 2026-10-26 协作仓库：团队改用 [0xChainAegis/aegisbank](https://github.com/0xChainAegis/aegisbank) 的 main 集成；原作者仓库、开发路径与既往阶段决策保留作历史记录。NLP 仅 P0 已完成，后续按 [NLP 待办](NLP-BACKLOG.md) 独立验收。

> 2026-10-25 前端复验：修复确认恢复、MFA 提交锁定、请求竞态、快捷指令与日期/金额展示；前端 73 项、后端 252 项、六场景 29/29、15 个实际入口通过。详见 [本轮修复与验收](FRONTEND-REPAIR-2026-10-25.md)。历史阶段数字保持当时快照。

> 2026-10-25 NLP P0 已实现：完整金额规范化、条件/组合任务澄清与多入口校验；新增 52 项 NLP 回归。该段为 P0 历史快照，P1 当前进展见上方报告，通用指代与自由组合仍待完善。见 [核验、实现与复现](NLP-ASSESSMENT-AND-PLAN-2026-10-25.md#6-p0-落地2026-10-25)。

> 2026-10-24 后端补强：新增 13 项回归，当时后端 200 项；补偿不覆盖后续设置、红色恢复需 MFA、权限写入与审计原子提交。详见 [补强记录](BACKEND-HARDENING-2026-10-24.md)。生产化剩余项维持下列清单。

> v1.5 安全复审：已修复记录见 [REMEDIATION-PLAN-2026-10-23.md](REMEDIATION-PLAN-2026-10-23.md)。既往阶段记录保留当时快照，当前状态以本轮验收为准。已支持 10 分钟、绑定用户与角色、单次消费的澄清续问；通用指代与长会话仍待完善。
> 版本：v1.5　更新日期：2026-10-23　复审基线：`main` @ `82c5d75`；修复源分支：`codex/audit-remediation-20261023`
> 适用对象：参赛团队、工程实施者、评审与答辩
> 信息来源：《项目总结与规划一》（Word）、上一轮工作轨迹与结论、三个仓库/分支实测、本轮实现与测试输出
> v1.4 变更：阶段 2.5 第一轮完成——36 项 UX 缺陷报告落 [`docs/UX-RECORD.md`](UX-RECORD.md)，批 1/2/3 前端修复已合入（提交 `25027d8`，gate 全 PASS）；前端测试更新为 **38 项 / 5 个测试文件**；阶段 3 材料保持已产出，视频与截图待人工。
> v1.3 变更：阶段 2A 六项硬要求（步骤级暂停/回退/补偿、可疑行为熔断、演示 MFA Provider、IM 渠道、工具沙箱、多角色撤权）的**后端/API 与前端面板实现标记为已完成**；新增 §9.1.1「2A 落地实现与测试映射」、§12 D12–D15 决策；工具更新为 **48 个**、后端测试 **144 项**、HTTP 接口 **49 个**；下一步改为阶段 2.5 / 3。
> v1.2 变更：阶段 1（信任工程）与阶段 2B（六场景完整覆盖）标记为**已完成**；六场景覆盖更新为 **6/6**；新增 §8.9「阶段 1 落地实现与测试映射」、§12 D9–D11 决策；工具/测试/接口数字更新为当前实现基线。
> v1.1 变更：新增「六场景覆盖现状与完整覆盖扩展计划」（§4.6、§6、§9.2），阶段 2 拆分为 2A（硬要求）与 2B（场景完整覆盖）。

---

## 1. 一页速览

| 项 | 内容 |
|---|---|
| 一句话 | AegisBank 是一个把「自然语言银行指令」编译成可审核 DAG、并在执行前经过动态风险与统一权限网关、执行前用 ActionEnvelope 绑定确认、执行后写入 SHA-256 审计链的银行 AI 智能体原型。 |
| 赛题 | 人工智能赛道 · 银行 AI 智能体（至少 3 个核心场景 + 权限分级 + 安全机制 + 意图规划 + 五类交付物） |
| 产品主线 | <https://github.com/0xChainAegis/aegisbank>（Public / MIT / `main`；保留原作者历史） |
| 开发位置 | 每位成员使用独立 Linux / WSL 检出；下文原作者绝对路径属历史环境记录 |
| 当前阶段 | 阶段 0 ✅ → 阶段 1 ✅ → 阶段 2B ✅（六场景 6/6）→ 阶段 2A ✅（六项硬要求）→ **阶段 3 交付材料 ✅**（`deliverables/`，视频待人工录制）→ **阶段 2.5 人工体验 🔄 第一轮完成**（`docs/UX-RECORD.md`，前端修复 `25027d8`）→ **U2 最小多轮闭环 ✅（仅联系人转账，最小范围）** |
| 已完成能力 | 动态风险（金额/日累计/产品等级/操作类型）、**51 个银行工具**（核心 10 + 场景 27 + 2A 扩展 14）、跨场景 DAG、绿/黄/红分级、统一权限网关、ActionEnvelope 确认绑定、幂等键、任务状态机（含 `UNKNOWN / PAUSED / ROLLED_BACK`）、readiness fail-closed、证据分层、注入整条拒绝、模型候选白名单、三类规则熔断、**步骤级暂停/回退/补偿、可疑行为熔断、演示 MFA Provider、IM 渠道、进程内工具沙箱、多角色与撤权**、七页 React 控制台、阶段 3 交付包（简介/技术文档/PPT/视频脚本/安全自评/部署/测试复现） |
| 六场景覆盖 | **6/6**：账单分析 ✅ / 卡片管理 ✅ / 智能转账 ✅ / 订阅代扣 ✅ / 跨场景联动 ✅ / 理财操作 ✅ |
| 硬缺口 | 生产化收尾：幂等/nonce TTL 清理、OS 级容器隔离、真实身份认证与 MFA、IM 平台接入、WORM 审计；**后续**：通用指代消解与长会话 |
| 验证基线 | 后端 **646 项** pytest；前端 **144 项** Vitest（12 个测试文件）；根组装器 **18 项**；六场景 **30/30**；HTTP 接口 **49 个**（FastAPI OpenAPI paths）；工具 **51 个**（其中 compensable=15、不可逆=13） |

---

## 2. 赛题要求与产品定位

### 2.1 赛题硬要求（摘要）

- **场景**：至少覆盖 3 个核心场景（鼓励全覆盖），参考智能转账、账单分析、理财操作、卡片管理、订阅/代扣管理、跨场景联动。
- **权限分级**：绿色自动执行；黄色用户确认（小额转账日累计 ≤ 1000 元等）；红色强验证（大额转账 > 1000 元、挂失/解挂、密码修改、理财申购等，需人脸/短信/U 盾等多因子）。
- **安全机制**：幻觉防护、Prompt 注入防御、完整操作审计、异常熔断、代码/工具运行沙箱。
- **意图规划**：支持模糊表达、省略上下文、隐含意图；复杂任务拆成有序 DAG；执行中支持中断、回退和人工接管。
- **交付物**：200 字作品简介、技术文档（架构图/算法说明/安全设计）、≤10 分钟答辩 PPT、≤5 分钟演示视频、源码 + README + 部署说明 + 测试用例、安全自评报告。

### 2.2 产品定义

AegisBank 不把大模型直接接上几个银行函数，而是给 Agent 增加一层**金融操作控制平面**：

```text
自然语言意图
  → 结构化 Planner（只生成计划，不执行工具；候选字段白名单）
  → 确定性 Plan Compiler（Schema / DAG / plan_hash 校验）
  → 动态风险引擎（绿 / 黄 / 红 + 可解释原因）
  → 统一权限网关（最小权限 / 越权 / 注入 / 分级决策）
  → 分级确认 + ActionEnvelope + 演示 MFA
  → ToolExecutor + 执行守卫（沙箱 / 超时 / 网络 / 体积）
  → Mock Bank Core 工具执行
  → 证据分层 + SHA-256 审计哈希链
```

### 2.3 差异化：证明的是「信任链路」，不是工具数量

普通银行 AI 助手也能查账单、转账。本项目要证明的是：

1. 用户能看见 Agent 准备做什么（结构化计划 + 参数 + 风险原因）；
2. 高风险操作能被准确拦住（动态风险只能升不能降）；
3. 用户能随时撤回授权（撤权后立即阻断，待确认动作执行前复检）；
4. 每次操作为什么被放行/拒绝都有可解释原因；
5. 确认之后执行的就是用户刚刚确认的那一笔（计划哈希 + 参数哈希 + nonce + 过期时间绑定）；
6. 重复提交不会重复扣款（幂等键 + 状态机 + 首次结果重放）；
7. 失败与未知状态不会被伪装成成功（readiness 503 + `UNKNOWN` + 人工对账）；
8. 日志可验证未被篡改，且事实来源可分层（SQLite 哈希链 + 四类证据）。

### 2.4 上一轮工作沉淀的六条结论

1. **上游 AegisAgent 不能作为参赛作品**：它是链上钱包 Gas 储备单动作系统，产品形态与银行 AI 智能体赛题不符。
2. **新库 `LQZ5885/aegisbank` 才是比赛产品主线**，原本地原型是它的历史起点。
3. **上游的价值是「信任工程参考」**：身份/执行分离、统一策略网关、LLM draft-only、严格结构化输出、Action Envelope、幂等与状态恢复、分层证据、readiness + fail closed。
4. **不能直接搬上游业务或技术栈**：不搬 Gas 钱包、Chainlink 定价、Owner 钱包审批、链上 PolicyEngine；后端继续 Python/FastAPI，只做概念移植 + 小模块实现。
5. **开发文件必须放 Linux 原生 ext4**：Windows 目录只做展示与备份，避免续用 `/mnt/d` 与两套环境漂移。
6. **比赛材料之前必须单列「人工用户体验」阶段**：开发者像真实用户一样走通全流程，避免「代码能跑但人不会用」。

---

## 3. 三个对象与仓库边界

| 对象 | 定位 | 仓库/位置 | 状态 |
|---|---|---|---|
| 原 Windows 本地 AegisBank | 最初方向验证骨架，3 个工具 | `D:\开发交流\mia03-ether\aegisbank智能体` | **已冻结**，仅作历史与展示，不再开发 |
| 新库 AegisBank | **比赛产品主线**，48 工具 + 信任层 + 六场景 + 2A 横切能力 + 五页前端 | <https://github.com/LQZ5885/aegisbank> | 活跃开发 |
| 上游 AegisAgent | 钱包/支付安全工程参考库 | <https://github.com/0xChainAegis/aegis-agent> | 只读参考，不并入产品链路 |

三条铁律：

1. 新库是**独立产品**，不是上游的 PR 或附属品；
2. 上游业务范围（Gas 储备、native ETH、Chainlink、Owner 钱包审批）**不进入**银行产品主流程；
3. 历史上游 PR 材料只存在于归档分支 `archive/upstream-plan-provenance`，`main` 不包含 `upstream-pr/`。

---

## 4. 当前实况（可验证基线）

### 4.1 仓库与分支

| 项 | 值 |
|---|---|
| 默认分支 | `main` |
| 已提交基线 | `bf36895 feat(2a): 六项硬要求落地：回退补偿/可疑熔断/MFA/IM/沙箱/多角色`（已合入 `main`；本轮文档同步未提交） |
| 归档分支 | `archive/upstream-plan-provenance`（含 `upstream-pr/` 4 个文件） |
| 许可证 | MIT（Copyright (c) 2026 LQZ5885） |
| 代码规模 | 后端 `aegisbank_api/` 53 个 Python 文件 / 约 18.3k 行；测试 14 个文件 / 约 4.3k 行；前端 `src/` 26 个文件 / 约 8.7k 行 |
| 技术栈 | FastAPI + Pydantic v2 + SQLite｜React 19 + TypeScript 5.9 + Vite 7｜pytest + Vitest |

### 4.2 已落地能力

| 能力 | 实现位置 | 说明 |
|---|---|---|
| Mock Bank Core | `backend/aegisbank_api/banking/` | SQLite 确定性数据：`bank_accounts` / `bank_cards` / `bank_transactions` / `bank_subscriptions` |
| 可插拔 Planner | `backend/aegisbank_api/planning/` | `rule`（默认与兜底）/ `llm`（OpenAI-compatible，候选白名单与冲突校验）/ `auto`（自动回退），统一输出 `ExecutionPlan/v1` |
| Plan Compiler | `planning/compiler.py` | 工具注册、参数 Schema、步骤 ID、依赖与环检测、拓扑排序、`plan_hash` |
| 动态风险引擎 | `backend/aegisbank_api/risk.py` + 各场景 `risk_rules()` | 单笔金额 / 当日累计 / 操作类型 / 产品风险等级；只升不降；输出 `level/score/reasons/requires_reauth` |
| 统一权限网关 | `backend/aegisbank_api/gateway.py` | 最小权限、注入拦截、分级决策；任一节点拒绝则整条 DAG 阻断 |
| DAG 调度 | `backend/aegisbank_api/scheduler.py` | 依赖排序、前序结果变量解析、待确认动作、确认后复核 envelope/权限/风险；节点间暂停/恢复、失败逆序补偿、执行 journal |
| 信任层 | `backend/aegisbank_api/trust/` | ActionEnvelope、幂等、状态机、证据、readiness、熔断、角色、MFA、暂停、沙箱（10 个功能模块，11 个文件） |
| 场景模块 | `backend/aegisbank_api/scenarios/` | 5 个可自动发现场景模块，25 个工具；契约见 `scenarios/README.md` |
| 审计哈希链 | `backend/aegisbank_api/audit.py` | 六字段审计 + 证据分层 + SHA-256 链 + 完整性校验接口 |
| 银行工具 | `tools/finance.py` + `scenarios/*.py` + `extensions/compensation.py` | 48 个（核心 9 + 场景 25 + 2A 扩展 14） |
| 2A 执行链 | `executor.py` + `trust/sandbox.py` + `extensions/sandbox.py` | 每次工具执行经 `ToolExecutor` 的 `ExecutionGuard` 链（默认 `SandboxGuard`）；超时/网络/入参/出参/白名单越界写 `sandbox_blocked` / `sandbox_timeout` 审计 |
| 补偿与回退 | `compensation.py` + `extensions/compensation.py` + `scheduler.py` | 27 条补偿规格（15 可补偿 / 12 不可逆）；失败后逆序补偿、补偿前经网关复检；成功为 `ROLLED_BACK`，部分失败/不可逆转人工对账 |
| 暂停与执行日志 | `trust/pause.py` + `scheduler.py` | 节点间暂停/恢复，已执行步骤不重复；`action_pauses` / `action_journal` / `action_journal_entries` |
| 可疑行为熔断 | `trust/circuit_breaker.py` + `extensions/breaker.py` | 连续失败 / 短时多次红色 / 注入命中累计共用 open 状态；operator 解锁并写 `circuit_breaker_unlock` 审计 |
| 演示 MFA Provider | `trust/mfa.py` + `extensions/mfa.py` | OTP + 模拟生物识别（`FACE-XXXXXX`）；红色确认按请求选择 provider，审计记录方式与结果 |
| IM 渠道 | `channels/im.py` + `extensions/im.py` | `im / cli / webhook` 复用同一 Planner/网关/MFA/审计链；`message_id` 幂等回放 |
| 多角色与撤权 | `trust/authz.py` + `extensions/authz.py` + `gateway.py` | `user / operator / auditor` 能力矩阵；`X-Aegis-Role` 演示头；撤权立即阻断并写 `role_revocation` 审计 |
| 核心扩展自动发现 | `extensions/__init__.py` + `extensions/README.md` | 6 个扩展模块（authz / breaker / compensation / im / mfa / sandbox），按文件名排序加载；`AEGIS_EXTENSION_ALLOW/STRICT` 并行开关 |
| React 控制台 | `frontend/src/` | 银行概览、场景数据（只读）、2A 能力页、运维面板、任务控制台（步骤日志与回滚）、权限控制台、操作审计、确认/MFA 弹窗（provider 选择）、就绪横幅、角色切换 |

### 4.3 演示链路（评审现场可直接复现）

```text
分析我的本月账单                              → 绿色，直接执行，返回分类与异常订阅
分析我的账单并取消异常订阅                     → 两步 DAG：query_bill → cancel_subscription（变量解析）
向 ACC-2002 转账 880 元                       → 黄色，确认后执行
给妈妈转 500 元 / 这顿 300 元 4 个人 AA        → 联系人解析 / 并行转账 DAG
同日再转 500 元（累计 > 1000 元）              → 红色，确认 + 演示 OTP 246810
挂失卡片 CARD-9902 / 重置 CARD-8821 密码        → 红色，确认 + 演示 OTP
买 1000 元稳健短债A                           → 红色（理财申购），确认 + OTP
帮我准备下个月妈妈的生日，预算 1000 元          → 4 步跨场景 DAG（查生日→锁预算→鲜花/蛋糕）
时间快进（POST /api/automation/run-due）       → 到期定时任务/礼物订单执行，审计记录 trigger_source=scheduled
回退补偿演示（POST /api/compensation/demo/run?mode=reversible） → 失败后逆序补偿，状态 ROLLED_BACK
不可逆 / 补偿失败（mode=irreversible / compensation_failure） → 回滚被阻止或部分失败，转人工对账
三次红色操作 / 三次注入命中                    → 可疑行为熔断打开，后续写操作被拒；operator 解锁
挂失 CARD-9902 + mfa_provider=biometric        → 模拟生物识别（FACE-888888）完成红色确认
POST /api/channels/im/message                  → IM 渠道查询/挂失，复用同一网关与审计链
POST /api/sandbox/demo/run（network/slow/oversize） → 沙箱拦截并写审计
X-Aegis-Role: auditor / operator               → 只读 / 不可执行；operator 可解锁熔断
```

### 4.4 验证结果（2026-10-23）

| 命令/检查 | 结果 |
|---|---|
| `cd backend && uv run pytest -p no:warnings` | **144 项** pytest 全部通过（15 个测试文件；2A 新增 51 条 + 回归 8 条） |
| `cd frontend && pnpm test` | **38 项** Vitest 全部通过（5 个测试文件；阶段 2.5 新增 `errors` / `session` 用例与 `viewModel` 扩展） |
| HTTP 接口枚举（`create_app().openapi()`） | **49 个** `/api` 路径 / 49 个 operation（2A 新增 20 个） |
| 工具目录（`GET /api/tools`） | **48 个**（核心 9 + 场景 25 + 2A 扩展 14；compensable=15） |
| 补偿规格（`GET /api/compensation/specs`） | **27 条**（15 可补偿 + 12 不可逆） |
| `bash scripts/smoke.sh` | 通过；实测 48 个工具、审计链 `valid=true`（10 条） |
| `bash scripts/lint.sh` / `build.sh` | 通过（本轮文档同步前复验） |
| DSH `gate.ps1` | 本轮为纯文档改动，未重跑全量门禁；交付前需补跑（含 test / security） |

> 数字必须以代码或测试输出为准；实现变更后需重新核对。

### 4.5 刻意保留的边界（不得在对外材料中夸大）

- 银行数据全部为 Mock Bank Core 模拟数据，**不连接真实银行系统**，不产生真实资金变动；理财内容不构成投资建议；
- 固定演示用户 `demo-user`，未接入登录、会话、设备指纹或真实身份认证；**`X-Aegis-Role` 是演示用请求头**，服务端不校验调用者身份，生产必须由真实认证后的身份推导角色；
- 演示 OTP `246810` 与模拟生物识别 token `FACE-888888` 不是生产 MFA；`approval_token` 为演示用确定性令牌；
- 动态风险是确定性演示规则，不是生产反欺诈/信用决策模型；
- **沙箱是进程内演示级**：socket 级网络阻断、线程超时（Python 线程无法强杀，超时后可能继续跑到返回）、入参上限 8 KB / 出参上限 64 KB、可选工具白名单；不是 OS 容器、命名空间或强制资源配额；
- **补偿只覆盖已登记规格的工具**：15 个可补偿、12 个声明不可逆；不可逆步骤会阻止自动回滚；补偿工具若被网关判定需二次校验，自动补偿拒绝并转人工对账；
- 熔断为系统级计数（单库单实例），未按用户隔离；幂等键 / `used_nonces` 仍无 TTL 清理；
- SQLite 单机持久化，不满足银行级高可用、隔离、容灾与 WORM 审计；
- IM 适配器不绑定真实 IM 平台身份，`sender_id` 仅写入审计；生产需接入平台签名校验与用户映射；
- 时间维度用任务表 + 时间快进 + 可选轮询，不是真实常驻 cron；
- LLM 为可选依赖，规则 Planner 完全离线可用；已支持限时、单次消费的澄清续问；通用指代与长会话尚未实现；
- **六场景已完整覆盖 6/6**，但「完整覆盖」指典型能力可跑通、分级正确、审计可见、前端可展示，不等于生产级业务完整性。

### 4.6 六场景覆盖现状（v1.2 更新：6/6）

赛题要求「至少覆盖 3 个核心场景，鼓励全覆盖」。当前实测覆盖 **6/6**：

| 场景 | 状态 | 已落地能力 | 实现位置 |
|---|---|---|---|
| 账单分析 | ✅ 完整 | 月报/年报（分类汇总、Top 商户、环比、异常说明）；异常检测（重复扣费、超预算、订阅金额突增、非活跃时段）；订阅扣费识别；续费提醒 | `scenarios/bills.py`：`bill_report`、`detect_bill_anomalies`、`identify_subscription_charges`、`list_renewal_reminders`；路由 `/api/bills/report`、`/api/bills/anomalies`、`/api/subscriptions/charges`、`/api/subscriptions/reminders` |
| 卡片管理 | ✅ 完整 | 额度/还款日/限额/挂失/解挂 + 虚拟卡申请→审核→发卡 + 密码重置（红，不存明文）+ 限额解锁 | `scenarios/cards.py`：`apply_virtual_card`、`issue_virtual_card`、`reset_card_password`、`unlock_transaction_limit` + 核心卡片工具；路由 `/api/cards/applications` |
| 智能转账 | ✅ 完整 | 账户 ID 转账；联系人簿与人名/别名/手机号转账（多命中澄清）；AA 拆分并行 DAG；定时转账（一次/每月/每年） | `scenarios/transfers.py`：`list_contacts`、`add_contact`、`transfer_to_contact`；`scenarios/automation.py`：`schedule_transfer`；路由 `/api/contacts` |
| 订阅/代扣 | ✅ 完整 | 订阅查询/取消 + 扣费识别（流水聚合、未登记扣费标记）+ 续费提醒（按周期过滤、days_ahead 窗口） | `scenarios/bills.py` 两个订阅工具 + 核心 `list_subscriptions`/`cancel_subscription` |
| 跨场景联动 | ✅ 完整 | DAG 一：`query_bill → cancel_subscription`；DAG 二：`query_contact_birthday → lock_budget_funds → schedule_flower_order / schedule_cake_order`（4 步、跨模块读联系人、资金锁定可补偿） | `scenarios/automation.py` 生日意图 + `test_automation.py::test_birthday_flow_is_four_step_dag_and_locks_budget` |
| 理财操作 | ✅ 完整 | 产品清单（5 个模拟产品 R1–R5）、持仓、风险测评、申购（红）、赎回（≤1000 黄 / >1000 红） | `scenarios/wealth.py`：`list_wealth_products`、`query_wealth_holdings`、`assess_wealth_risk`、`purchase_wealth`、`redeem_wealth`；路由 `/api/wealth/products`、`/holdings`、`/orders` |

准确的对外表述：**「六个参考场景已完整覆盖：每类场景的典型能力可用自然语言发起，风险分级正确，审计可见，前端可展示；所有数据为模拟数据。」** 阶段 2A 的步骤暂停/回退/补偿、可疑行为熔断、MFA Provider、IM 渠道、进程内沙箱与多角色撤权已落地；仍须同时说明 §4.5 的生产化边界。

---

## 5. 架构与信任不变量

### 5.1 端到端数据流

```text
┌──────────────────────────────────────────────────────────────┐
│ React 19 + TypeScript + Vite 控制台                           │
│ 银行概览 │ 场景数据 │ 任务控制台 │ 权限控制台 │ 2A 能力 / 运维 / 审计       │
└─────────────────────────────┬────────────────────────────────┘
                              │ /api（readiness 未就绪时禁用写操作）
┌─────────────────────────────▼────────────────────────────────┐
│ FastAPI + Pydantic                                           │
│  Planner ──► Plan Compiler ──► DagScheduler                  │
│                                   │                          │
│      ┌────────────────────────────┼──────────────────────┐   │
│      ▼              ▼             ▼                      ▼   │
│  DynamicRisk  PermissionGateway  Trust(Envelope/幂等/    Audit │
│                                 状态机/暂停/journal/熔断) 链  │
│                                   ▼                          │
│              ToolExecutor + ExecutionGuard（沙箱/超时/网络）  │
│                                   ▼                          │
│        银行工具 48（核心 9 + 场景 25 + 2A 扩展 14）           │
│        扩展：compensation / authz / breaker / mfa /          │
│              sandbox / im；IM 渠道复用同一链路                │
│                                   ▼                          │
│                    BankingRepository（SQLite Mock Bank Core） │
│                    + scenario 自建表 + 2A 表（暂停/日志/熔断   │
│                      事件/IM 消息/补偿演示账本）               │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 模块边界

| 目录 | 职责 | 禁止 |
|---|---|---|
| `planning/` | 意图 → 结构化计划；Compiler 校验；模型候选校验 | 直接执行工具、决定权限 |
| `trust/` | 确认绑定、幂等、状态机、证据、readiness、熔断、角色、MFA、暂停、沙箱 | 绕过 scheduler/gateway 直接执行 |
| `scenarios/` | 场景 schema/种子/工具/意图/风险规则/只读路由 | 在路由层直接改资金/账户；跨模块私有约定 |
| `risk.py` | 确定性风险判定与原因 | 接受模型输出降级风险 |
| `gateway.py` | 唯一权限决策入口；权限/注入/角色/分级；执行再经 `executor.py` | 被绕过；在工具内部做权限判断 |
| `scheduler.py` | DAG 顺序、变量解析、确认恢复、复检、信任层接线 | 跳过确认直接执行高风险节点 |
| `executor.py` | 工具执行收口、`ExecutionGuard` 前后置钩子、`SandboxViolation` | 绕过 Guard 直接 `tool.execute` |
| `compensation.py` | 补偿规格（可逆/不可逆、逆工具） | 未登记规格却自动回滚 |
| `extensions/` | 2A 横切能力自动发现（authz/breaker/compensation/im/mfa/sandbox） | 修改核心装配文件；绕过网关执行 |
| `channels/` | IM / CLI / webhook 适配层 | 在适配器内做权限判断或另起业务逻辑 |
| `tools/` | 银行操作 + Manifest 声明 | 读写权限表、写审计链之外的旁路状态 |
| `audit.py` | 六字段审计、证据分层、哈希链、校验 | 被业务代码裁剪字段 |
| `banking/` | Mock 数据与仓储 | 编造数据 / 连接真实银行 |

### 5.3 十条信任不变量（任何改动不得破坏）

1. **LLM 只产出计划**：不签名、不授权、不执行、不解释审计结果；模型输出只作为候选并通过字段白名单。
2. **统一网关**：所有工具调用只有一条入口，权限判断不散落在工具内部。
3. **确认绑定动作**：确认凭证绑定用户、计划哈希、参数哈希、风险等级、权限、一次性 nonce 与过期时间；执行前重算校验。
4. **风险只升不降**：工具基线风险 + 动态规则决定等级，模型输出不得降低。
5. **审计不可裁剪**：触发时间、原始指令、DAG 路径、工具入参、执行结果、确认状态 + 哈希链 + 证据分层。
6. **失败不伪装成功**：服务未就绪、依赖失败、结果未知都必须显式暴露（fail closed / `UNKNOWN`）。
7. **数据来源可分层**：Mock 数据、人工确认、策略判断、审计链必须可区分。
8. **最小数据**：不存真实凭证与客户数据；证据优先存哈希而非原文。
9. **执行统一收口**：工具调用必须经 `ToolExecutor` 与 `ExecutionGuard` 链；沙箱违规、超时、网络访问都必须先写审计再抛错。
10. **回退可审计**：补偿/回滚必须经统一权限网关复检并按逆序执行；不可逆步骤阻止自动回滚；`compensation_executed / failed / blocked` 全部入哈希链。

### 5.4 不变量与当前实现的差距（诚实标注）

| 不变量 | 当前状态 | 归属 |
|---|---|---|
| 1 LLM 只产出计划 | ✅ 已实现（Planner 不执行 + 候选白名单/冲突校验） | 阶段 1 完成 |
| 2 统一网关 | ✅ 已实现 | — |
| 3 确认绑定动作 | ✅ ActionEnvelope/v1 + nonce + expiry + 执行前重算 + 409 语义 | 阶段 1 完成 |
| 4 风险只升不降 | ✅ 已实现（含场景规则） | — |
| 5 审计不可裁剪 | ✅ 哈希链 + 证据分层（证据进 `result_json` 参与链计算） | 阶段 1 完成 |
| 6 失败不伪装成功 | ✅ `/api/health/ready` + 写操作 503 + `UNKNOWN`/对账；`run-due` 已接 readiness（2A 完成） | 阶段 1 + 2A |
| 7 数据来源可分层 | ✅ 四类 `source` + 四种 `verification_kind` | 阶段 1 完成 |
| 8 最小数据 | ✅ 哈希链 + 库内状态；密码不存明文 | — |
| 9 执行统一收口 | ✅ 所有工具经 `ToolExecutor` + `SandboxGuard`；超时/网络/体积违规写审计 | 阶段 2A 完成 |
| 10 回退可审计 | ✅ 逆序补偿 + 网关复检 + 不可逆阻断；`ROLLED_BACK` / 人工对账 | 阶段 2A 完成 |

> 仍未闭合：幂等键 / `used_nonces` TTL 清理、OS 级容器隔离、真实身份认证。按用户熔断隔离已于 2026-10-27 完成。

---

## 6. 赛题差距矩阵

| 赛题要求 | 当前状态 | 剩余差距 | 归属 |
|---|---|---|---|
| 至少 3 个核心场景 | ✅ **6/6** | — | 阶段 2B 完成 |
| 智能转账典型能力（人名/手机号/备注、定时、AA） | ✅ 联系人簿 + 人名/手机号/别名 + AA 并行 DAG + 定时转账 | — | 阶段 2B 完成 |
| 理财操作（产品对比、风险评估、一键申购/赎回） | ✅ 产品/持仓/风险测评/申购/赎回（全模拟 + 免责声明） | — | 阶段 2B 完成 |
| 账单报告与异常检测 | ✅ 月报/年报 + 4 类确定性异常规则 | — | 阶段 2B 完成 |
| 卡片管理完整能力 | ✅ 虚拟卡申请/发卡/密码重置/限额解锁 + 原卡片工具 | — | 阶段 2B 完成 |
| 订阅扣费识别与续费提醒 | ✅ 扣费识别 + 站内续费提醒 + IM 回执入口 | 真实短信/IM 平台推送、退订合规 | 生产化 |
| 跨场景联动 | ✅ 两条真实 DAG（账单→取消订阅；生日→锁资金→订购） | — | 阶段 2B 完成 |
| 绿色自动执行 | ✅ 已实现 | — | — |
| 黄色用户确认 | ✅ 已实现（≤1000 元日累计、卡片设置、订阅取消、理财赎回小额等） | — | — |
| 红色强验证（>1000 元） | ✅ 分级 + OTP / 模拟生物识别 Provider + ActionEnvelope 复核 | 真实人脸/短信/U 盾与身份绑定 | 生产化 |
| 幻觉防护 | ✅ Mock 仓库 + Schema + 模型候选白名单/冲突校验 | 独立事实校验/自述拦截增强 | 后续 |
| Prompt 注入防御 | ✅ 命中整条请求拒绝 + 候选白名单 + 注入累计熔断 | 更完整注入分类器 | 后续 |
| 完整操作审计 | ✅ 六字段 + 哈希链 + 证据分层 + 补偿/暂停/journal 审计 | WORM/合规存储 | 生产化 |
| 异常熔断 | ✅ 连续失败 + 短时多次红色 + 注入命中累计；按用户隔离；operator 解锁 | 告警联动 | 生产化 |
| 工具沙箱 | ✅ 进程内超时/网络阻断/入参出参上限/工具白名单，违规入审计 | OS 容器/命名空间/资源配额 | 生产化 |
| 模糊/省略/隐含意图 | ✅ 单轮澄清 + 联系人/AA/账单/理财/自动化意图；⚠ 多轮上下文未做 | 指代消解、多轮澄清循环 | 后续 |
| 复杂任务 DAG + 中断/回退/人工接管 | ✅ 节点间暂停/恢复、逆序补偿、`ROLLED_BACK`、不可逆阻断与人工对账 | 工具执行中途强停 | 生产化 |
| 定时/触发能力 | ✅ 任务表 + run-due 时间快进 + readiness 门禁 + 可选后台轮询 | 真实常驻调度、分布式触发 | 生产化 |
| APP / IM 入口 | ✅ IM / CLI / webhook 适配器复用同一网关与审计 | 真实 IM 平台签名与用户映射 | 生产化 |
| 多角色与撤权 | ✅ user / operator / auditor 能力矩阵；撤权立即阻断并审计 | 真实身份认证、RBAC/ABAC 策略引擎 | 生产化 |
| 五类交付物 | 源码 / README / 部署 / 测试较完整 | 简介、PPT、视频、安全自评 | 阶段 3 |

---

## 7. 路线图：阶段 0 → 1 → 2（2A/2B）→ 2.5 → 3

| 阶段 | 目标 | 关键产出 | 状态 |
|---|---|---|---|
| 0 | 产品边界与仓库定型 | 归档分支、产品 README、工程文件与环境记录、本规划 | ✅ 已完成 |
| 1 | 信任工程 | Action Envelope、幂等、状态机、readiness、证据分层、注入整条拒绝、模型白名单、熔断骨架 | ✅ 已完成 |
| 2A | 比赛硬要求 | 回退补偿、可疑行为熔断、沙箱、MFA Provider、IM、多角色撤权 | ✅ 已完成 |
| 2B | 六场景完整覆盖 | 理财、转账形态、账单报告、卡片补齐、订阅深度、生日联动 | ✅ 已完成（6/6） |
| 2.5 | 人工用户体验（Dogfooding） | 三轮狗粮测试、UX 记录、截图更新 | 计划中 |
| 3 | 比赛交付 | 简介、技术文档、PPT、视频、安全自评、部署说明 | 计划中 |

> 赛题只硬性要求「至少 3 个场景」；2B 已作为加分项完成。阶段 2A 六项硬要求已于 `bf36895` 合入，当前无阻塞性赛题缺口；下一阶段是人工体验（2.5）与比赛材料（3）。

### 7.0 阶段 0：产品边界与仓库定型（已完成）

已完成的清理：

- 上游 PR 材料从产品 `main` 移出，归档到 `archive/upstream-plan-provenance`；
- README 只保留银行 Agent 产品叙事，新增 `docs/UPSTREAM-NOTES.md` 说明参考边界；
- 新增 `docs/ROADMAP.md`、`docs/UX-DOGFOODING.md`、产品介绍页与真实截图；
- MIT License、GitHub Public 仓库、默认分支 `main`；
- 重写 `AGENTS.md`、新增 `CONTRIBUTING.md`、重写 `docs/DEVELOPMENT-ENVIRONMENT.md`、更新 `docs/TECH-STACK.md` 与 `docs/ROADMAP.md`；
- 新增本总规划文档 `docs/MASTER-PLAN.md` 并加入 README 文档索引。

**阶段 0 退出标准**：`main` 无上游材料、文档与实现一致、根目录工程文件齐全、门禁与测试全绿、环境记录可复现。→ **满足**。

### 7.1 阶段 1：信任工程（✅ 已完成）

| # | 任务 | 产出文件/接口 | 验收结果 |
|---|---|---|---|
| 1 | Action Envelope | `trust/action_envelope.py` | ✅ 篡改/过期/nonce 复用均 409 且不执行 |
| 2 | 幂等键与执行前持久化 | `trust/idempotency.py` + `idempotency_keys` | ✅ 重复提交不产生第二笔；改正文 409 |
| 3 | 状态机扩展 | `trust/state_machine.py` | ✅ `UNKNOWN/RECONCILED/ROLLED_BACK`；非法迁移被拒并审计 |
| 4 | readiness 与 fail closed | `trust/readiness.py` + `GET /api/health/ready` + 前端横幅 | ✅ 未就绪写操作 503 |
| 5 | 证据来源分层 | `trust/evidence.py` | ✅ API 与审计均含 `source/verified/verification_kind` |
| 6 | 注入整条拒绝 | `gateway.py` + `scheduler.py` | ✅ 命中时无计划、无执行、写审计 |
| 7 | 模型候选白名单与冲突校验 | `planning/llm.py` | ✅ 契约外字段/未知工具拒绝；覆盖金额/编造收款方转澄清 |

实现细节与测试映射见 §8。

### 7.2 阶段 2A：比赛硬要求补齐（后端/API ✅ 已完成，2026-10-23）

| # | 任务 | 落地 | 验收证据 |
|---|---|---|---|
| 1 | 步骤级暂停、回退、补偿 | `trust/pause.py`、`compensation.py`、`extensions/compensation.py`、`scheduler.py`（`run_dag/pause_action/resume_action/rollback_action/journal_view`） | 可逆 DAG 失败后逆序补偿为 `ROLLED_BACK`；不可逆步骤阻止回滚；暂停后可恢复且不重复已执行节点。`test_compensation.py` 10 条 |
| 2 | 异常熔断策略完善 | `trust/circuit_breaker.py`、`extensions/breaker.py`；连续失败 / 短时多次红色 / 注入命中累计共用 open 状态 | 达到阈值后熔断打开、后续写操作被拒；operator 解锁写 `circuit_breaker_unlock` 审计。`test_breaker.py` 7 条 |
| 3 | 工具执行沙箱 | `executor.py` 的 `ToolExecutor/ExecutionGuard`、`trust/sandbox.py`、`extensions/sandbox.py` | 网络阻断、超时、超大输出、超大入参、工具白名单均拦截并写审计。`test_sandbox.py` 8 条 |
| 4 | 演示 MFA Provider | `trust/mfa.py`、`extensions/mfa.py`；OTP + 模拟生物识别 `FACE-XXXXXX` | 红色确认可选 provider，审计记录 provider / verification_kind / 结果。`test_mfa.py` 10 条 |
| 5 | IM 渠道适配器 | `channels/im.py`、`extensions/im.py`；`POST /api/channels/im/message` | 绿色查询、红色挂失 + OTP 确认、错误 OTP、`message_id` 幂等回放。`test_im_channel.py` 7 条 |
| 6 | 多角色与撤权 | `trust/authz.py`、`extensions/authz.py`、`gateway.py`；`X-Aegis-Role` | operator/auditor 不能执行工具；撤权后重放被阻断并写 `role_revocation`。`test_authz.py` 9 条 |
| 7 | 信任层收尾 | `run-due` readiness 门禁已完成（`test_automation.py`）；幂等/nonce TTL 清理**仍未做** | 写入口统一 fail-closed；存储增长列入生产化清单 |

**2A 退出标准**：赛题四项硬要求（熔断、沙箱、MFA、IM）均可在演示中一次走通，并有自动化测试；暂停/回退/补偿与多角色撤权同样有测试覆盖。→ **满足**（2A 新增 51 条 + 回归 8 条测试，后端合计 144 条）。

**仍未做（诚实标注）**：`used_nonces` / `idempotency_keys` TTL 清理、OS 级容器隔离、真实身份认证与 MFA、真实 IM 平台接入、工具执行中途强停。按用户熔断隔离已于 2026-10-27 完成。

### 7.3 阶段 2B：六场景完整覆盖（✅ 已完成）

目标已达成：§4.6 的 5/6 补齐到 6/6，并加深三个部分覆盖场景。交付物：

| 工作包 | 交付 | 测试 |
|---|---|---|
| 理财场景全套 | `scenarios/wealth.py`（5 工具、4 表、3 路由、5 意图） | `test_wealth.py` 11 |
| 转账形态 | `scenarios/transfers.py`（联系人簿、人名/手机号转账、AA 并行 DAG） | `test_transfers.py` 10 |
| 账单报告与异常检测 | `scenarios/bills.py`（月报/年报、4 类异常、订阅扣费、续费提醒） | `test_bills.py` 8 |
| 卡片补齐 | `scenarios/cards.py`（虚拟卡申请/发卡、密码重置、限额解锁） | `test_cards.py` 8 |
| 生日联动 + 定时任务 + 时间维度 | `scenarios/automation.py`（9 工具、生日 4 步 DAG、预算锁定、时间快进、run-due readiness） | `test_automation.py` 11 |
| 自动发现基座 | `scenarios/__init__.py` + `scenarios/README.md`（模块契约、并行开关） | 各场景测试均经统一装配 |

### 7.4 阶段 2.5：人工用户体验（开发者 Dogfooding）

目的：在制作比赛材料前，开发者暂时忘掉实现细节，按真实用户路径连续使用产品，找出「代码能跑但人不会用」的问题。

三轮计划：

1. **第一轮 · 无脚本首次使用**：只读 README 启动，不看 API 文档，完成银行概览 / 账单分析 / 转账 / 理财 / 卡片 / 权限与审计；记录所有卡点。
2. **第二轮 · 安全与异常路径**：撤权后重试、OTP 错误、重复确认与刷新、服务离线（readiness 非 ready）、空数据、注入请求、`UNKNOWN` 对账。
3. **第三轮 · 修复后回归**：连续完成六个场景中的三个代表场景，更新真实截图，形成 UX 验收记录。

退出标准：

- 3 个核心场景从首次打开到完成均不超过 10 分钟；
- 无 P0/P1 可用性阻塞；
- 关键页面均有 loading / empty / error 状态；
- 确认、MFA、撤权、`UNKNOWN` 与审计证据能被非开发者理解；
- 截图与当前界面一致，README 与产品介绍页同步更新。

详细执行清单见 [`docs/UX-DOGFOODING.md`](UX-DOGFOODING.md)；执行记录落到 [`docs/UX-RECORD.md`](UX-RECORD.md)（阶段 2.5 创建）。

**第一轮执行结果（2026-10-23）**：人工测试复盘 + 静态审计 + 无头浏览器量测，识别 36 项缺陷（P0×7 / P1×17 / P2×10 / P3×2）；批 1（首屏/反馈/移动端/可读性）、批 2（确认弹窗、回执、术语收口、演示路径）、批 3 前端项（hash 路由、刷新恢复、幂等、错误码映射、统一刷新、对账入口、审计三态）已合入 `25027d8`。验证：`tsc --noEmit` 0 error、Vitest 38 项通过、`vite build` 通过、全量 gate PASS。未完成：第二轮安全/异常路径狗粮、第三轮截图与外部试用；推迟项见 UX-RECORD §10.2。

### 7.5 阶段 3：比赛交付

| 交付物 | 要求 | 状态 |
|---|---|---|
| 作品简介 | ≤200 字，含创作理念与所用 AI 技术 | ✅ `deliverables/01-作品简介.md`（199 字符/190 字） |
| 技术文档 | 系统架构图、核心算法说明、安全设计文档 | ✅ `deliverables/02-技术文档.md`（含 Mermaid 架构图） |
| 答辩 PPT | 汇报 ≤10 分钟 | ✅ `deliverables/03-AegisBank-答辩PPT.pptx`（14 页，含演讲备注与时间控制） |
| 演示视频 | ≤5 分钟 | ⏳ 分镜与口播稿已完成（`deliverables/04-演示视频脚本.md`）；**视频待人工录制** |
| 作品信息 | 源码、README、GitHub 地址、部署说明、测试用例 | ✅ `deliverables/06/07` + 仓库 README |
| 安全自评报告 | 权限分级实现说明 + 已知风险清单 | ✅ `deliverables/05-安全自评报告.md` |

---

## 8. 阶段 1 详细设计（信任层，已实现）

### 8.1 目录

```text
backend/aegisbank_api/trust/
├─ __init__.py            # 统一导出
├─ action_envelope.py     # 计划/参数/风险/身份的一次性绑定（阶段 1）
├─ idempotency.py         # 幂等键与执行前持久化（阶段 1）
├─ state_machine.py       # 13 状态迁移（含 PAUSED/UNKNOWN/ROLLED_BACK）（2A 扩展）
├─ evidence.py            # 证据来源分层（阶段 1）
├─ readiness.py           # 就绪检查与写操作 fail closed（阶段 1）
├─ circuit_breaker.py     # 三类规则熔断（2A 扩展）
├─ authz.py               # 角色能力矩阵（2A）
├─ mfa.py                 # MFA Provider 与强制策略（2A）
├─ pause.py               # 暂停标记 + 执行 journal（2A）
└─ sandbox.py             # 进程内执行沙箱 Guard/Executor（2A）
```

### 8.2 ActionEnvelope/v1 契约

```text
ActionEnvelope
  - schema_version: "action-envelope/v1"
  - user_id: str                 # 演示期固定 demo-user
  - plan_hash: str               # 编译后规范化计划 SHA-256
  - step_id: str
  - tool_name: str
  - arguments_hash: str          # 规范化参数 SHA-256
  - risk_level: green|yellow|red
  - risk_reasons: list[str]
  - permission: str              # 工具声明的最小权限
  - nonce: str                   # 一次性随机串（uuid4）
  - issued_at / expires_at: ISO8601（默认 TTL 300 秒）
  - confirmation_state: pending|approved|rejected|expired
  - approval_token: str | null   # 演示审批令牌，API/审计只返回掩码
```

规则：

- 用户在黄/红确认时确认的是**这份 envelope**（每个计划节点一份）；
- 执行前由服务端重新计算 `plan_hash`、`arguments_hash`、风险等级与权限；
- 任一不一致 → `409 ENVELOPE_MISMATCH`，不执行、不创建业务流水、不写业务审计；
- 过期 → `409 ENVELOPE_EXPIRED`；`nonce` 复用 → `409 NONCE_REUSED`；
- 批准/拒绝时消费 nonce（`used_nonces`），捕获重放。

### 8.3 状态机

```text
DRAFT
 → AWAITING_CONFIRMATION → AWAITING_REAUTH → APPROVED → EXECUTING → COMPLETED
        │                        │                          ├→ PAUSED → EXECUTING
        ├→ REJECTED              └→ EXPIRED                 ├→ FAILED
        └→ EXPIRED                                         └→ UNKNOWN → RECONCILED
                                                                       └→ ROLLED_BACK
```

- `PAUSED`：在节点之间暂停，`resume` 从 `next_index` 继续，已执行节点不重复；
- `UNKNOWN`：执行已发出但结果不确定，**不得自动重复下单**，先核对原操作再决定 `RECONCILED` 或 `ROLLED_BACK`；
- 所有迁移写入审计（`state_transition`），非法迁移写 `state_transition_rejected` 并拒绝；
- 状态与历史持久化在 `pending_actions.state` / `state_history_json`；
- `POST /api/trust/actions/{action_id}/reconcile` 完成人工对账，`GET /api/trust/actions/{action_id}` 查看状态与历史。

### 8.4 证据分层

```text
source:            mock_bank | human_confirmation | policy_engine | audit_chain
verified:          true | false
verification_kind: tool_result | approval | policy_decision | hash_chain
detail:            人类可读说明
```

前端据此展示「哪些是 Mock 数据、哪些有人工确认、哪些是策略判断、哪些只是业务状态」。证据写入审计 `result_json` 并参与哈希链计算。

### 8.5 readiness 与 fail closed

`GET /api/health/ready` 返回各组件状态：

```json
{
  "status": "ready|degraded|not_ready",
  "components": {
    "sqlite": {"ok": true, "detail": "SQLite 可读写"},
    "audit_chain": {"ok": true, "detail": "哈希链校验通过，共 N 条"},
    "mock_bank_seed": {"ok": true, "detail": "模拟银行种子就绪：2 个账户 / 2 张卡"},
    "planner": {"ok": true, "detail": "Planner 可用：rule"}
  }
}
```

- 关键组件（sqlite / audit_chain / mock_bank_seed）任一失败 → `not_ready`；仅 Planner 不可用 → `degraded`；
- `POST /api/agent/run` 与 `POST /api/confirmations/{action_id}` 调用前 `require_ready()`，非 `ready` → **503**；
- 前端禁用写操作并显示原因；不允许把“服务离线”显示成“执行成功”。

### 8.6 注入与候选校验

- 注入命中：整条请求拒绝（不进入 Planner，不产生可执行计划），审计记录拒绝原因与命中规则；
- 严格字段白名单：Planner 输出只接受契约内字段；
- 模型不得补全用户未提供的信息，不得覆盖用户新输入的账户/金额，冲突时转澄清；
- fallback 到规则 Planner 时必须显式标记 `planner: auto:rule-fallback`。

### 8.7 阶段 1 测试矩阵（12 类，已全部自动化）

1. envelope 参数被篡改 → 拒绝执行；
2. envelope 过期 → 拒绝；
3. nonce 复用 → 拒绝；
4. 确认后撤权 → 执行前复检阻断；
5. 重复提交同一请求 → 只产生一次执行；
6. 执行中结果未知 → 状态 `UNKNOWN` 且不重复执行；
7. readiness 未就绪 → 写操作被拒且错误可读；
8. 注入命中 → 整条请求拒绝、无可执行计划；
9. 模型试图覆盖用户金额/收款方 → 被白名单拦截；
10. 证据分层字段在审计与 API 中完整出现；
11. 状态机非法迁移被拒；
12. 审计哈希链在新增证据字段后仍校验通过。

### 8.8 阶段 1 退出标准（已满足）

- 上述 12 类测试全部纳入自动化测试并通过 → ✅（`test_trust.py` 共 17 条 = 12 类矩阵 + 5 条补充：readiness 正向、可读 422、模型冲突 2 条、连续失败熔断）；
- `docs/SECURITY.md`、`docs/ARCHITECTURE.md`、`docs/ROADMAP.md` 同步更新 → ✅（本轮 v1.2 同步）；
- 门禁五阶段通过，`main` 保持可运行、可演示 → ⏳ 本轮为纯文档改动，走 docs 快速通道，交付前补跑完整门禁；
- 前端能展示 readiness 状态、证据来源与 `UNKNOWN` 任务状态 → ✅（`ReadinessBanner`、证据徽标、任务控制台 `UNKNOWN`/对账）。

### 8.9 阶段 1 落地实现与测试映射（v1.2 新增）

| 实现文件 | 关键内容 | 对应测试（`backend/tests/test_trust.py`） |
|---|---|---|
| `trust/action_envelope.py` | `ActionEnvelope`、`build_envelopes`、`verify`、`claim_nonces` | `test_envelope_tampering_is_rejected_without_execution`、`test_expired_envelope_is_rejected`、`test_reused_nonce_is_rejected` |
| `trust/idempotency.py` | `IdempotencyStore.begin/complete/release`、409 冲突 | `test_idempotency_key_prevents_second_pending_action` |
| `trust/state_machine.py` | `ActionState`、`ALLOWED_TRANSITIONS`、`ExecutionOutcomeUnknown` | `test_unknown_outcome_is_not_executed_twice`、`test_state_machine_rejects_illegal_transition` |
| `trust/evidence.py` | 四类 `EvidenceSource`/`VerificationKind`、`merge_evidence` | `test_evidence_is_present_in_api_and_audit` |
| `trust/readiness.py` + `main.py` | 组件探针、`require_ready()`、503 | `test_readiness_not_ready_fails_closed`、`test_readiness_reports_all_components_when_ready` |
| `gateway.py` + `scheduler.py` | `scan_injection`、Planner 前整条拒绝 | `test_injection_is_rejected_before_planner` |
| `planning/llm.py` | 字段白名单、未知工具拒绝、参数冲突转澄清 | `test_model_cannot_override_user_amount`、`test_model_cannot_invent_recipient`、`test_model_candidate_rejects_unknown_tool_and_extra_fields` |
| `trust/circuit_breaker.py` + `scheduler.py` | 连续失败熔断、`/api/trust/circuit-breaker[/reset]` | `test_circuit_breaker_opens_after_consecutive_failures` |
| `audit.py` | 证据写入 `result_json`、哈希链仍可校验 | `test_audit_chain_valid_after_evidence_fields` |
| `scheduler.py` + `main.py` | 确认后复检、可读 422 | `test_permission_revoked_after_confirmation_blocks_execution`、`test_execution_time_business_error_is_readable_422` |

总计 17 条，全部通过；另由既有 `test_api.py`（12）、`test_planner.py`（8）覆盖基础闭环与 Planner 契约。

---

## 9. 阶段 2 详细要点

### 9.1 2A：比赛硬要求（六项，后端/API ✅ 已完成）

1. **步骤级暂停 / 回退 / 补偿**：`ToolMetadata` 增加 `compensable` / `compensation_tool`；`CompensationRegistry` 登记 27 条规格（15 可补偿 / 12 不可逆）；调度器在节点间检查暂停标记，失败时按相反顺序补偿，补偿工具执行前经统一权限网关与动态风险复检；不可逆步骤阻止自动回滚并在计划中标注「不可撤销」。
2. **异常熔断**：连续失败（滑动窗口）、短时多次红色操作、注入命中累计三类规则共用 open 状态与冷却时间；触发后写操作统一拒绝并返回原因与恢复方式；`operator` 可通过 `POST /api/trust/breaker/unlock` 解锁并写审计。
3. **工具沙箱**：`ToolExecutor` + `ExecutionGuard` 收口所有工具执行；`SandboxGuard` 限制入参 8 KB、出参 64 KB、可选工具白名单，执行期间 socket 级阻断网络，`SandboxedToolExecutor` 提供墙钟超时；每次拦截/超时写 `sandbox_blocked` / `sandbox_timeout` 审计。**进程内演示级，不是 OS 容器。**
4. **演示 MFA Provider**：`MfaProvider` 协议 + `OtpProvider` + `SimulatedBiometricProvider`（`FACE-XXXXXX`）；`MfaPolicy` 按风险等级/敏感工具给出允许 provider 与推荐默认值，确认接口接受 `mfa_provider`，审计记录 `provider / verification_kind / result`。策略是提示性的，最终由 `MfaService.verify` 校验。
5. **IM 渠道适配器**：`channels/im.py` + `extensions/im.py`；支持 `im / cli / webhook`，确认语法 `确认 <action_id> <otp>`，其余文本转 `scheduler.run`；`message_id` 命中缓存时回放首次回执，不二次执行；审计事件 `im_message_executed / im_message_rejected`。
6. **多角色与撤权**：`user / operator / auditor` 能力矩阵；`X-Aegis-Role` 演示头驱动角色解析；撤权立即写入权限库并阻断后续执行，`role_revocation` 入审计链。

**2A 收尾项**：`run-due` readiness 门禁已完成并有测试；幂等键与 `used_nonces` 的 TTL 清理**仍未实现**，列入生产化清单。

**2A 退出标准**：赛题四项硬要求（熔断、沙箱、MFA、IM）均可在演示中一次走通，并有自动化测试；暂停/回退/补偿与多角色撤权同样有测试覆盖。→ **满足**。

#### 9.1.1 2A 落地实现与测试映射

| 实现文件 | 关键内容 | 对应测试（`backend/tests/`） |
|---|---|---|
| `trust/pause.py` + `scheduler.py` | `PauseRegistry`、`ActionJournal`、节点间暂停、`resume` 从 `next_index` 继续 | `test_compensation.py::test_pause_after_node_then_resume_without_repeating`、`::test_pause_before_confirmation_then_resume` |
| `compensation.py` + `extensions/compensation.py` + `scheduler.py` | 27 条补偿规格、14 个反向/演示工具、`run_dag` 公共入口与 `pause/resume/rollback/journal` 端点、逆序补偿与网关复检 | `test_compensation.py`（10 条：规格覆盖、逆序补偿、不可逆阻断、部分失败、暂停恢复、人工回退、撤权、状态机、红色不可逆） |
| `executor.py` + `trust/sandbox.py` + `extensions/sandbox.py` | `ExecutionGuard` 链、网络阻断、超时、入参/出参上限、工具白名单、`sandbox/policy` 与 `sandbox/demo/run` | `test_sandbox.py`（8 条：网络、超大输出、超时、正常执行、策略、白名单/入参、关闭开关、隔离加载） |
| `trust/mfa.py` + `extensions/mfa.py` | OTP / 模拟生物识别 Provider、`MfaPolicy`、`providers / policy / demo/challenge` | `test_mfa.py`（10 条：Provider 列表、策略映射、降级、生物识别成功/失败、未知 provider、默认 OTP、挑战提示与拒绝） |
| `trust/circuit_breaker.py` + `extensions/breaker.py` | 三类规则、共享 open 状态、冷却、事件列表、operator 解锁 | `test_breaker.py`（7 条：红色熔断、注入熔断、解锁权限与审计、事件列表、冷却、连续失败、策略端点） |
| `channels/im.py` + `extensions/im.py` | IM/CLI/webhook 适配、确认语法、`message_id` 幂等、审计事件 | `test_im_channel.py`（7 条：绿色、红色确认、错误 OTP、重复 message_id、澄清、help/校验、CLI 直连） |
| `trust/authz.py` + `extensions/authz.py` + `gateway.py` | 角色矩阵、能力校验、`/authz/roles / me / revoke / audit/policy` | `test_authz.py`（9 条：矩阵、me、operator/auditor 拒绝、重置权限、撤权、404、审计只读） |
| `scenarios/automation.py` + `main.py` | `run-due` readiness 503 门禁 | `test_automation.py::test_run_due_write_endpoint_is_fail_closed_when_not_ready` |

2A 测试合计 **51 条**：`test_authz.py` 9 + `test_breaker.py` 7 + `test_compensation.py` 10 + `test_im_channel.py` 7 + `test_mfa.py` 10 + `test_sandbox.py` 8；后端总计 **144 条**（15 个测试文件）。

### 9.2 2B：六场景完整覆盖（✅ 已完成，保留设计记录）

> 2B 范围只包含六场景业务能力与时间维度；**仍未做项**：阶段 2A 的步骤级回退补偿、可疑行为熔断策略、演示 MFA Provider、IM 渠道、工具沙箱、多角色撤权（见 §9.1），不在 2B 交付内。

#### 9.2.1 验收口径

「完整覆盖」不是「工具有了」，而是以下四项同时成立：

1. 该场景的**典型能力示例**都能用自然语言发起并跑通；
2. 风险分级正确（该黄的黄、该红的红，且原因可读）；
3. 每次执行写入审计哈希链，可回放查看；
4. 前端有对应展示与确认路径。

→ 六场景均已满足。

#### 9.2.2 逐场景落地情况

| 场景 | 落地内容 | 状态 |
|---|---|---|
| 理财操作 | 表 `wealth_products / holdings / orders / profile`；工具 `list_wealth_products`、`query_wealth_holdings`、`assess_wealth_risk`、`purchase_wealth`、`redeem_wealth`；风控：申购始终红、赎回 ≤1000 黄 / >1000 红；规则意图 5 个；只读路由 3 个；种子 5 产品 + 1 持仓 | ✅ |
| 智能转账 | `contacts` 联系人簿 + 人名/手机号/别名解析（多命中澄清）+ AA 拆分并行 DAG + 定时转账（`scheduled_tasks`） | ✅ |
| 账单分析 | 月报/年报报告、异常检测（重复扣费/超预算/订阅金额突增/非活跃时段）、Top 商户与环比 | ✅ |
| 卡片管理 | 虚拟卡申请（`applying → issued`）、密码重置（红，不存明文）、限额解锁（>5000 升红） | ✅ |
| 订阅/代扣 | 扣费识别（流水聚合 + 未登记标记）、续费提醒（周期过滤 + days_ahead） | ✅ |
| 跨场景联动 | 生日 4 步 DAG（查生日 → 锁预算 → 鲜花/蛋糕）；账单 → 取消订阅已有 | ✅ |

#### 9.2.3 理财场景设计要点（实现）

- 统一数据契约：`WealthProduct`（产品 ID、名称、类型、风险等级 R1–R5、起购金额、预期年化、期限）、`Holding`（持仓、份额、市值、收益）、`WealthOrder`（申购/赎回单）；
- 工具与风险：`purchase_wealth` 基线红色（金额 ≥ 起购；风险原因包含产品风险等级与偏好匹配提示）；`redeem_wealth` 按金额分级（≤1000 黄、>1000 红）；查询/风险测评绿色；
- 全部为模拟产品与模拟收益，接口返回 `simulated=true` 与 `disclaimer`，README、产品介绍页、答辩材料必须标注「不构成任何投资建议，不产生真实资金变动」；
- Planner 区分「推荐/对比」与「一键申购」：推荐只产出查询类计划，申购必须走确认 + 强验证。

#### 9.2.4 转账形态与联系人簿（实现）

- `contacts`（`contact_id / name / alias / phone / account_id / birthday / relation`）；`给妈妈转 500` → 别名命中 → 解析为 `ACC-9001`；
- 解析失败或多命中 → 澄清（不得由模型猜测）；
- AA 拆分：`这顿 300 元 4 个人 AA` → 为其余参与者生成多笔转账的并行 DAG，风险按 AA 总额与日累计判定；
- 定时转账：`scheduled_tasks` + `run_due_tasks`（见 9.2.8）。

#### 9.2.5 账单与订阅深度（实现）

- 账单报告：`period=month|year`，分类汇总、Top 商户、环比、异常说明；
- 异常规则（确定性、可解释）：同商户重复扣费、单类目超预算、订阅扣费金额突增、非活跃时段交易；
- 订阅：扣费识别基于 `bank_transactions` 的订阅类目聚合成订阅实体；续费提醒基于下次扣费日生成站内提醒列表（不含外部推送）。

#### 9.2.6 卡片补齐（实现）

- 虚拟卡申请：创建 `status=applying` 申请单，审核通过后置为 `issued`（审核即发卡），黄色确认；卡号仅返回掩码；
- 密码修改：红色 + 演示 OTP；不接收/不保存明文密码，只记录 `password_changed_at`；
- 限额解锁：恢复默认 10000 元或指定目标限额，>5000 元升红。

#### 9.2.7 生日跨场景联动（实现）

```text
用户：帮我准备下个月妈妈的生日，预算 1000 元
 → step-1: query_contact_birthday（读 contacts 生日）      绿色
 → step-2: lock_budget_funds（锁定 1000 元，可补偿解锁）   黄色确认
 → step-3/4: schedule_flower_order / schedule_cake_order  黄色确认
```

要点：`step-2` 引入「资金锁定/预算目标」概念（`budget_goals`），`step-3/4` 依赖时间触发；演示用 `POST /api/automation/run-due` 的「时间快进」触发，避免真实等待；`unlock_budget_funds` 提供补偿路径。

#### 9.2.8 两个架构级缺口的处理（实现状态）

**缺口一：时间维度（已用 D10 方案落地）**

- 原状：系统是纯同步「请求 → 计划 → 确认 → 执行」，无后台调度器；
- 现实现：`scheduled_tasks` 任务表 + `run_due_tasks` 工具 + `POST /api/automation/run-due`（可传 `now` 做时间快进）+ 可选后台轮询线程（`AEGIS_AUTOMATION_ENABLED`）；
- 复用阶段 1 状态机与审计：到期执行前重新 `gateway.evaluate` 复检权限，审计记录 `trigger_source="scheduled"`；原子抢占（`pending → done`）保证重复调用不重复扣款；
- **不实现真实常驻 cron**（见 D10）。

**缺口二：自然语言入口（部分落地）**

- 已实现：联系人实体与别名解析、金额/人数抽取、场景意图规则（六场景共 20 个意图）、单轮澄清、模型候选校验；
- 未实现：多轮上下文、指代消解（如「再转一次」「就那个」）；列为后续阶段。

#### 9.2.9 工作量汇总（实际执行）

| 批次 | 内容 | 状态 |
|---|---|---|
| 第一波 | 理财场景 + 转账别名/AA + 账单报告 + 卡片补齐 | ✅ 完成 |
| 第二波 | 生日跨场景联动 + 站内续费提醒 | ✅ 完成 |
| 第三波 | 定时转账 + 联系人解析（后台调度以时间快进 + 可选轮询实现） | ✅ 完成 |

#### 9.2.10 2B 验收标准（已满足）

- 六个场景的典型能力示例均可用自然语言发起，且分级正确、审计可见、前端可展示 → ✅；
- 至少两条真实跨场景 DAG（账单→订阅取消、生日→锁资金→订购）→ ✅；
- 新增工具全部继承 `BaseTool`、经统一网关调用、风险只升不降 → ✅；
- 理财内容明确标注模拟数据与不构成投资建议 → ✅；
- 新增测试覆盖：每个新工具 1 条正向、风险分级 1–2 条、DAG 1 条、撤权/失败 1 条 → ✅（五场景共 48 条新测试）；
- README、BANKING-DOMAIN、SECURITY、ROADMAP 同步更新 → ✅（本轮 v1.2）。

---

## 10. 阶段 3 详细要点

- **作品简介**：≤200 字，突出「可信执行控制平面」而非「聊天机器人」；
- **技术文档**：以 `docs/ARCHITECTURE.md`、`docs/BANKING-DOMAIN.md`、`docs/SECURITY.md` 为底稿整理参赛版，附带架构图与风险规则表；
- **答辩 PPT**：10 分钟内讲清「问题 → 方案 → 演示 → 安全边界 → 工程实现」；
- **演示视频**：5 分钟内完成「账单分析 → 跨场景取消订阅 → 880 元黄色确认 → 累计超限红色 OTP → 理财申购/生日 DAG → 撤权与审计校验 → 补偿回滚/熔断解锁/沙箱拦截」；
- **安全自评报告**：权限分级实现说明 + 已知风险清单（直接用 §4.5 与 `docs/SECURITY.md`）；
- **部署说明**：Linux/WSL 两条路径 + 一键脚本 + 演示数据说明。

---

## 11. 工程约定与协作

### 11.1 环境

| 位置 | 用途 |
|---|---|
| `/home/lqz5885/aegisbank/dev/aegisbank`（WSL ext4） | **唯一开发主线** |
| `D:\开发交流\mia03-ether\aegisbank智能体`（Windows） | 历史副本，冻结；仅作展示/备份 |
| `/home/lqz5885/aegisbank/backup/` | Windows 文档备份与校验清单 |

### 11.2 分支与提交

- `main`：产品主线，始终可构建、可测试；
- `archive/upstream-plan-provenance`：历史上游 PR 材料，只读；
- 功能分支：`feat/*`、`fix/*`、`docs/*`；
- 提交前必须经 `gate.ps1` 五阶段，提交使用 `checkpoint.ps1` 生成带 `Verified-By: dsh-gate` 的提交。

### 11.3 文档维护

- 行为变更同步更新 README / ROADMAP / SECURITY / MASTER-PLAN / ARCHITECTURE / BANKING-DOMAIN；
- 阶段结论进入本文档与 `docs/ROADMAP.md`，不留在对话里；
- 对外材料必须与实现一致，未实现的能力标注「计划中」；
- 文档中的工具数、测试数、接口数必须来自代码或测试输出。

---

## 12. 决策记录（ADR 摘要）

| 编号 | 决策 | 理由 | 日期 |
|---|---|---|---|
| D1 | 产品主线为 `LQZ5885/aegisbank`，不再把新库作为上游 PR 附属 | 上游产品形态与赛题不符；新库才是银行 Agent 产品 | 2026-10-22 |
| D2 | 上游只做概念移植，不换技术栈、不搬链上业务 | Python/FastAPI 已闭环；Gas 钱包业务与银行场景无关 | 2026-10-22 |
| D3 | 开发文件放 Linux 原生 ext4，Windows 只做展示 | 避免 `/mnt/d` 性能与两套环境漂移 | 2026-10-22 |
| D4 | 在阶段 2 与 3 之间新增阶段 2.5「人工用户体验」 | 防止「代码能跑但用户不会用」 | 2026-10-22 |
| D5 | 阶段 0 收尾补全 AGENTS / CONTRIBUTING / 环境记录 / 总规划 | 仓库定型需要对外可读、可复现的工程文档 | 2026-10-23 |
| D6 | 上游 PR #11 暂不 rebase，材料保留归档分支 | 比赛优先；上游无 review 且已 conflicting，保活成本大于收益 | 2026-10-23 |
| D7 | 六场景完整覆盖拆为阶段 2B，采用三波排序（理财/转账形态 → 生日/提醒 → 定时/上下文） | 先用低成本补齐「有无」，再用高价值联动做亮点，最难的时间维度与信任工程合并改造 | 2026-10-23 |
| D8 | 时间维度（定时/提醒/触发）不单独开工，与阶段 1 状态机、阶段 2A 回退补偿合并 | 避免出现两套任务状态机与两套幂等实现 | 2026-10-23 |
| D9 | 业务场景采用「模块即场景」的自动发现契约（`NAME / SCHEMA_SQL / seed / tools / intents / risk_rules / router / start_background / stop_background`） | 六个场景若堆进核心文件会导致装配与评审不可维护；契约让新增场景只加一个文件 + 测试，核心接线零改动 | 2026-10-23 |
| D10 | 时间维度用 `scheduled_tasks` + `run_due_tasks` + `POST /api/automation/run-due` 时间快进 + 可选后台轮询，不做真实常驻 cron | 演示环境无需真实等待；复用同一状态机/幂等/审计（延续 D8），避免引入第二套调度与状态机；真实 cron 留给生产化 | 2026-10-23 |
| D11 | 理财赎回基线为黄色 + 规则按金额升级（≤1000 元黄、>1000 元红）；申购始终红色 | 与转账的金额阈值口径一致，能演示「同级工具按金额分级」；申购是资金投入且需强验证，故固定红色 | 2026-10-23 |
| D12 | 补偿走统一网关复检、不二次确认；红色补偿拒绝自动执行并转人工对账 | 回滚是失败后的收敛动作，若再弹确认会卡住恢复；但补偿仍须最小权限与注入/越权复检，需要强验证的补偿交由人工处理，避免自动放大风险 | 2026-10-23 |
| D13 | 可疑熔断与失败熔断共用同一 `open` 状态与冷却时钟，计数为系统级 | 统一 fail-closed 语义，避免多套锁状态互相绕过；按用户隔离需要真实身份与多租户存储，留待生产化 | 2026-10-23 |
| D14 | MFA Provider 可插拔（OTP + 模拟生物识别）+ 提示性策略；固定演示 token 仅本地 | 证明「验证方式可扩展、审计可区分」；不在原型中伪造真实人脸/设备能力，策略只做 UI/演示提示，最终校验仍由 `MfaService` 完成 | 2026-10-23 |
| D15 | 沙箱为进程内演示级（超时/网络/入参出参/白名单），角色用演示请求头 `X-Aegis-Role` | OS 容器隔离与真实身份认证超出本地原型范围；先把「执行统一收口 + 违规入审计」做可验证，生产化再替换为容器与认证网关 | 2026-10-23 |

---

## 13. 风险登记册

| 风险 | 影响 | 当前状态 / 应对 |
|---|---|---|
| 本轮实现提交前存在工作树 | 演示/回滚风险 | 已解除：`bf36895` 已合入 `main`；本轮仅文档改动，未提交 |
| 2B 场景扩张挤压信任工程 | 评审核心亮点来不及做 | 已解除：阶段 1、2B、2A 均完成 |
| 定时能力引入两套状态机 | 返工与审计割裂 | 已规避：按 D8/D10 复用同一状态机、幂等与审计 |
| 把 2A 演示级沙箱/MFA/角色当成生产级 | 评审高估安全能力 | 文档与 README 明确「进程内沙箱、固定演示 token、演示角色头」；生产化清单单列 |
| 沙箱超时无法强杀 Python 线程 | 超时后工具仍可能完成副作用 | 超时后 force-release 网络阻断并写审计；演示工具无真实副作用；生产改用容器强隔离 |
| 理财场景被质疑金融合规 | 评审风险 | 全部模拟产品/收益，接口与文档明确标注不构成投资建议、无真实资金变动 |
| 前端与后端字段漂移 | 演示失败 | 接口契约集中在 `docs/ARCHITECTURE.md`；前端 Vitest 与后端 pytest 双向兜底 |
| 幂等/nonce 无 TTL 清理 | 单机存储长期增长 | 2A 未做，列入生产化清单；演示环境可删库重建 |
| 角色头可自报 | 越权演示可被伪造 | 明确仅本地演示；生产由认证后的会话/Token 推导角色，禁止信任客户端头 |
| 前端与后端并行开发漂移 | 2A 面板字段不一致 | 已按后端 OpenAPI 与测试对齐并复核（38 项 Vitest）；后续扩展仍以契约为准 |
| 文档与实现再次漂移 | 评审质疑 | 本轮建立「数字来自测试输出」规则；实现变更必须同步更新六份文档 |
| 评审质疑 Mock 数据 | 被误判为「假系统」 | README/PPT 明确边界与可替换性，强调「可信控制平面」而非真实资金 |
| WSL ext4 分区异常 | 开发环境不可用 | 保留备份目录与 GitHub 远端；关键提交及时推送 |
| 上游参考被过度借鉴 | 范围蔓延 | 遵守 D2 与 `docs/UPSTREAM-NOTES.md`，不引入链上组件 |

---

## 14. 里程碑（状态更新）

> 以下按「每周 5 个有效人日」估算；阶段 1、2B、2A 均已实际完成。

| 里程碑 | 内容 | 状态 / 验收 |
|---|---|---|
| M1（已完成） | 阶段 0 收尾 + 总规划 | ✅ 本文档 + 门禁全绿 |
| M2（已完成） | 阶段 1 信任层 | ✅ 17 条信任测试通过，前端展示 readiness/证据/UNKNOWN |
| M3a（已完成） | 阶段 2A 硬要求 | ✅ 回退补偿、可疑熔断、沙箱、MFA、IM、多角色全部可演示；2A 测试 51 条 |
| M3b（已完成） | 阶段 2B 第一波 | ✅ 六场景完整（理财 + 转账形态 + 账单报告 + 卡片补齐） |
| M4（已完成） | 阶段 2B 第二波 | ✅ 生日跨场景联动 + 站内续费提醒可演示 |
| M5（进行中） | 阶段 2.5 Dogfooding | 🔄 第一轮完成：36 项 UX 报告 + 批 1/2/3 前端修复（`25027d8`）；⏳ 第二轮安全/异常路径、第三轮截图与验收记录 |
| M6（部分完成） | 阶段 3 交付 | ✅ 简介 / 技术文档 / PPT / 视频脚本 / 安全自评 / 部署 / 测试复现已产出（`deliverables/`）；⏳ 视频待人工录制、截图待阶段 2.5 更新、仓库 tag 待打 |

（第三波「定时转账 + 多轮上下文」中定时部分已随 D10 完成；多轮上下文仍列为后续项。）

---

## 附录 A：术语表

| 术语 | 含义 |
|---|---|
| Mock Bank Core | 确定性的本地银行数据层，所有金融事实的来源 |
| Planner | 把自然语言编译成结构化计划的组件，只产出计划 |
| Plan Compiler | 校验计划并生成规范化 `plan_hash` 的确定性组件 |
| Action Envelope | 绑定身份、计划、参数、风险、权限、nonce 与过期时间的一次性确认凭证 |
| 幂等键 | `Idempotency-Key`，保证重复提交返回首次结果 |
| 绿/黄/红 | 自动执行 / 用户确认 / 强验证三级执行策略 |
| UNKNOWN | 执行结果不确定的中间态，防止重复下单，需人工对账 |
| Fail closed | 依赖不可用或状态不明时默认拒绝，而非放行 |
| 证据分层 | 用 `source / verified / verification_kind` 区分数据来源与验证方式 |
| 场景模块 | `scenarios/` 下通过统一契约自动发现的业务模块 |
| Dogfooding | 开发者以真实用户身份使用自家产品并记录摩擦 |
| 2A / 2B | 阶段 2 的两条工作线：比赛硬要求 / 六场景完整覆盖 |

## 附录 B：关键文件索引

| 文件 | 内容 |
|---|---|
| `README.md` | 产品介绍、六场景、架构、快速开始、演示路径、已知边界 |
| `docs/MASTER-PLAN.md` | 本文档：总规划与阶段设计 |
| `docs/ROADMAP.md` | 路线图与阶段任务/状态 |
| `docs/UX-DOGFOODING.md` | 阶段 2.5 执行清单 |
| `docs/ARCHITECTURE.md` | 模块边界、端到端数据流、信任层、场景扩展契约、时间维度 |
| `docs/BANKING-DOMAIN.md` | 数据模型、48 个工具、补偿/不可逆表、六场景能力矩阵、演示数据 |
| `docs/SECURITY.md` | 信任层实现、权限/风险表、安全边界与生产化清单 |
| `docs/TECH-STACK.md` | 技术选型与环境 |
| `docs/DEVELOPMENT-ENVIRONMENT.md` | 开发环境、复验记录与目录说明 |
| `docs/UPSTREAM-NOTES.md` | 上游参考边界与归档分支说明 |
| `backend/aegisbank_api/scenarios/README.md` | 场景模块契约与并行开发开关 |
| `AGENTS.md` / `CONTRIBUTING.md` | 工程约定与贡献指南 |

## 附录 C：评审现场演示脚本（5–8 分钟）

1. 打开银行概览：账户、卡片、订阅、异常订阅 `SUB-3002`；顶部就绪横幅四个组件 OK；
2. 任务控制台输入「分析我的本月账单」→ 绿色自动执行，展示分类与异常；
3. 输入「分析我的账单并取消异常订阅」→ 展示两步 DAG、变量解析与确认；
4. 输入「向 ACC-2002 转账 880 元」→ 黄色确认弹窗，展示计划、风险原因与 ActionEnvelope 摘要；
5. 同日再转 500 元 → 累计超 1000 元升级红色，输入演示 OTP `246810`；
6. 任务控制台演示「理财申购」（红色）与「给妈妈转 500 元」（联系人解析）；场景数据页核对持仓与账单；
7. 输入「这顿 300 元 4 个人 AA」→ 展示并行 DAG 与按总额分级；
8. 输入「帮我准备下个月妈妈的生日，预算 1000 元」→ 4 步跨场景 DAG 与预算锁定；点击「时间快进」触发到期任务；
9. 权限控制台撤回 `transfer` 权限 → 再次执行被网关阻断并显示原因；
10. 操作审计页校验 SHA-256 哈希链，展开一条记录查看证据分层；展示 `UNKNOWN` 任务的对账入口；
11. `POST /api/compensation/demo/run?mode=reversible` → 展示逆序补偿、`ROLLED_BACK` 与 `compensation_executed` 审计；再演示 `irreversible` 被阻止；
12. 连续三次红色操作或三次注入命中 → 熔断打开；切换 `X-Aegis-Role: operator` 调用 `/api/trust/breaker/unlock` 解锁；
13. 挂失 CARD-9902 时选择 `mfa_provider=biometric`（`FACE-888888`）；用 `POST /api/channels/im/message` 复现同一红色流程；用 `/api/sandbox/demo/run` 演示网络/超时/超大输出拦截。

## 附录 D：上游 AegisAgent 能力映射

| 上游能力 | 本项目处理方式 |
|---|---|
| LLM draft-only、严格 schema | 吸收（Planner 契约 + Compiler + 候选白名单） |
| 统一 PolicyEngine | 吸收（统一权限网关） |
| preview/submit 绑定哈希 | 吸收（ActionEnvelope/v1，已实现） |
| 幂等、执行前持久化、UNKNOWN | 吸收（trust/idempotency.py、state_machine.py，已实现） |
| readiness / fail closed | 吸收（trust/readiness.py + 503，已实现） |
| 证据与事件绑定 | 吸收（trust/evidence.py，已实现） |
| 注入整条拒绝 | 吸收（gateway.py + scheduler.py，已实现） |
| Gas 储备、native ETH 业务 | 不搬（与银行场景无关） |
| Chainlink ETH/USD 定价 | 不搬（银行风险不用链上价格） |
| Owner 钱包审批替代 MFA | 不搬（改用演示 MFA Provider，阶段 2A） |
| 链上 PolicyEngine 替代业务策略 | 不搬（保留 Python 策略层） |


## 2026-10-23 安全复审修复批次

本轮在 Linux 主线工作分支完成代码修复：补偿内部化、动作并发占有、账本/成功审计/journal 原子性、累计风险与定时授权、确认归属与能力、MFA 熔断、IM 命名空间、提交截止、金额/卡片/预算/持仓不变量、输出契约、前端幂等恢复与 fail closed、限时单次澄清续问。新增后端 43 项安全回归，前端新增接口及 React/jsdom 测试；总计后端 187 / 前端 53，六场景 29 项。

当前清单为 50 个工具（核心 10 / 场景 26 / 扩展 14）、28 条补偿规格（15 可补偿 / 13 不可逆）、49 个 HTTP 操作。已升级 Vitest 与 certifi，依赖扫描结果见 [修复记录](REMEDIATION-PLAN-2026-10-23.md)。本批次的提交与发布记录以 Git 历史为准。

比赛仍需完成：≤5 分钟演示视频、实际答辩时长核验和截图更新；订阅纯查询的黄/绿口径仍需组委会解释。生产化与待验证风险单列，不以本轮回归代替真实认证、OS 隔离或生产安全验收。
