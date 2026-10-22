# AegisBank 总规划（Master Plan）

> 版本：v1.0　更新日期：2026-10-23　基线：`main` @ `7639a44`（阶段 0 收尾补充见 §7.0）
> 适用对象：参赛团队、工程实施者、评审与答辩
> 信息来源：《项目总结与规划一》（Word）、上一轮 25 次会话的工作轨迹与结论、三个仓库/分支的实测核对

---

## 1. 一页速览

| 项 | 内容 |
|---|---|
| 一句话 | AegisBank 是一个把「自然语言银行指令」编译成可审核 DAG、并在执行前经过动态风险与统一权限网关、执行后写入 SHA-256 审计链的银行 AI 智能体原型。 |
| 赛题 | 人工智能赛道 · 银行 AI 智能体（至少 3 个核心场景 + 权限分级 + 安全机制 + 意图规划 + 五类交付物） |
| 产品主线 | <https://github.com/LQZ5885/aegisbank>（Public / MIT / `main`） |
| 开发主线 | WSL Ubuntu 24.04 ext4：`/home/lqz5885/aegisbank/dev/aegisbank` |
| 当前阶段 | 阶段 0（仓库定型）已完成 → **阶段 1（信任工程）为下一步** |
| 已完成能力 | 动态风险（含 1000 元日累计阈值）、9 个银行工具、跨场景 DAG、绿/黄/红分级、统一权限网关、确认 + 演示 OTP、SHA-256 审计链、四页 React 控制台 |
| 硬缺口 | 步骤级回退/补偿、异常熔断、工具沙箱、IM 渠道、真实 MFA、readiness/fail closed、幂等与 `UNKNOWN` 状态 |
| 验证基线 | 后端 20 项 pytest、前端 7 项 Vitest、lint/build 通过、门禁五阶段通过（2026-10-23 复验） |

---

## 2. 赛题要求与产品定位

### 2.1 赛题硬要求（摘要）

- **场景**：至少覆盖 3 个核心场景，参考智能转账、账单分析、理财操作、卡片管理、订阅/代扣管理、跨场景联动。
- **权限分级**：绿色自动执行；黄色用户确认（小额转账日累计 ≤ 1000 元等）；红色强验证（大额转账 > 1000 元、挂失/解挂、密码修改、理财申购等，需人脸/短信/U 盾等多因子）。
- **安全机制**：幻觉防护、Prompt 注入防御、完整操作审计、异常熔断、代码/工具运行沙箱。
- **意图规划**：支持模糊表达、省略上下文、隐含意图；复杂任务拆成有序 DAG；执行中支持中断、回退和人工接管。
- **交付物**：200 字作品简介、技术文档（架构图/算法说明/安全设计）、≤10 分钟答辩 PPT、≤5 分钟演示视频、源码 + README + 部署说明 + 测试用例、安全自评报告。

### 2.2 产品定义

AegisBank 不把大模型直接接上几个银行函数，而是给 Agent 增加一层**金融操作控制平面**：

```text
自然语言意图
  → 结构化 Planner（只生成计划，不执行工具）
  → 确定性 Plan Compiler（Schema / DAG / plan_hash 校验）
  → 动态风险引擎（绿 / 黄 / 红 + 可解释原因）
  → 统一权限网关（最小权限 / 越权 / 注入 / 分级决策）
  → 分级确认与演示 MFA
  → Mock Bank Core 工具执行
  → SHA-256 审计哈希链
```

### 2.3 差异化：证明的是「信任链路」，不是工具数量

普通银行 AI 助手也能查账单、转账。本项目要证明的是：

1. 用户能看见 Agent 准备做什么（结构化计划 + 参数 + 风险原因）；
2. 高风险操作能被准确拦住（动态风险只能升不能降）；
3. 用户能随时撤回授权（撤权后立即阻断，待确认动作执行前复检）；
4. 每次操作为什么被放行/拒绝都有可解释原因；
5. 确认之后执行的就是用户刚刚确认的那一笔（计划哈希 + 参数绑定）；
6. 日志可验证未被篡改（SHA-256 哈希链）。

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
| 新库 AegisBank | **比赛产品主线**，9 工具 + 动态风险 + 跨场景 DAG + 完整前端 | <https://github.com/LQZ5885/aegisbank> | 活跃开发 |
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
| 基线提交 | `7639a44 chore: complete phase 0 product boundary` |
| 归档分支 | `archive/upstream-plan-provenance`（含 `upstream-pr/` 4 个文件） |
| 许可证 | MIT（Copyright (c) 2026 LQZ5885） |
| 代码规模 | 后端 22 个 Python 文件 / 约 3054 行；前端 16 个文件 / 约 2913 行 |
| 技术栈 | FastAPI + Pydantic v2 + SQLite｜React 19 + TypeScript 5.9 + Vite 7｜pytest + Vitest |

### 4.2 已落地能力

| 能力 | 实现位置 | 说明 |
|---|---|---|
| Mock Bank Core | `backend/aegisbank_api/banking/` | SQLite 确定性数据：`bank_accounts` / `bank_cards` / `bank_transactions` / `bank_subscriptions` |
| 可插拔 Planner | `backend/aegisbank_api/planning/` | `rule`（默认与兜底）/ `llm`（OpenAI-compatible）/ `auto`（自动回退），统一输出 `ExecutionPlan/v1` |
| Plan Compiler | `planning/compiler.py` | 工具注册、参数 Schema、步骤 ID、依赖与环检测、拓扑排序、`plan_hash` |
| 动态风险引擎 | `backend/aegisbank_api/risk.py` | 单笔金额 / 当日累计 / 操作类型；只升不降；输出 `level/score/reasons/requires_reauth` |
| 统一权限网关 | `backend/aegisbank_api/gateway.py` | 最小权限、注入拦截、分级决策；任一节点拒绝则整条 DAG 阻断 |
| DAG 调度 | `backend/aegisbank_api/scheduler.py` | 依赖排序、前序结果变量解析、待确认动作、确认后权限复检 |
| 审计哈希链 | `backend/aegisbank_api/audit.py` | 六字段审计 + SHA-256 链 + 完整性校验接口 |
| 银行工具 | `backend/aegisbank_api/tools/finance.py` | 9 个工具（见下） |
| React 控制台 | `frontend/src/` | 银行概览、任务控制台、权限控制台、操作审计、确认/MFA 弹窗 |

9 个银行工具：`query_bill`、`transfer`、`adjust_repayment_date`、`adjust_card_limit`、`set_transaction_limit`、`report_card_lost`、`unlock_card`、`list_subscriptions`、`cancel_subscription`。

### 4.3 三条演示链路（评审现场可直接复现）

```text
分析我的本月账单                      → 绿色，直接执行，返回分类与异常订阅
向 ACC-2002 转账 880 元               → 黄色，确认后执行
分析我的账单并取消异常订阅            → 两步 DAG：query_bill → cancel_subscription（变量解析）
同日再转 500 元（累计 > 1000 元）      → 红色，确认 + 演示 OTP 246810
挂失卡片 CARD-9902                    → 红色，确认 + 演示 OTP
```

### 4.4 验证结果（2026-10-23 复验）

| 命令 | 结果 |
|---|---|
| `bash scripts/lint.sh` | ruff 通过；TypeScript `tsc --noEmit` 通过 |
| `bash scripts/build.sh` | 后端 compileall 通过；Vite 生产构建成功 |
| `bash scripts/test.sh` | 后端 **20 项** pytest 通过；前端 **7 项** Vitest 通过 |
| `bash scripts/smoke.sh` | API 健康、绿色工具执行成功、审计链 `valid=true` |
| DSH `gate.ps1` | encoding / lint / build / test / security 五阶段通过 |

### 4.5 刻意保留的边界（不得在对外材料中夸大）

- 银行数据全部为 Mock Bank Core 模拟数据，**不连接真实银行系统**，不产生真实资金变动；
- 固定演示用户 `demo-user`，未接入登录、会话、设备指纹或真实身份认证；
- 演示 OTP `246810` 不是生产 MFA；
- 动态风险是确定性演示规则，不是生产反欺诈/信用决策模型；
- SQLite 单机持久化，不满足银行级高可用、隔离、容灾与 WORM 审计；
- 尚未实现步骤级回滚/补偿、异常熔断、工具沙箱、IM 渠道；
- LLM 为可选依赖，规则 Planner 完全离线可用。

---

## 5. 架构与信任不变量

### 5.1 端到端数据流

```text
┌──────────────────────────────────────────────────────────────┐
│ React 19 + TypeScript + Vite 控制台                           │
│ 银行概览 │ 任务控制台 │ 权限控制台 │ 操作审计                   │
└─────────────────────────────┬────────────────────────────────┘
                              │ /api
┌─────────────────────────────▼────────────────────────────────┐
│ FastAPI + Pydantic                                           │
│  Planner ──► Plan Compiler ──► DagScheduler                  │
│                                   │                          │
│                    ┌──────────────┼───────────────┐          │
│                    ▼              ▼               ▼          │
│            DynamicRiskEngine  PermissionGateway  Confirmation │
│                    └──────────────┼───────────────┘          │
│                                   ▼                          │
│                        银行工具（9 个）                        │
│                                   ▼                          │
│                    BankingRepository（SQLite Mock Bank Core） │
│                                   ▼                          │
│                    AuditService（SHA-256 哈希链）             │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 模块边界

| 目录 | 职责 | 禁止 |
|---|---|---|
| `planning/` | 意图 → 结构化计划；Compiler 校验 | 直接执行工具、决定权限 |
| `risk.py` | 确定性风险判定与原因 | 接受模型输出降级风险 |
| `gateway.py` | 唯一工具调用入口；权限/注入/分级 | 被绕过；在工具内部做权限判断 |
| `scheduler.py` | DAG 顺序、变量解析、确认恢复、复检 | 跳过确认直接执行高风险节点 |
| `tools/` | 银行操作 + Manifest 声明 | 读写权限表、写审计链之外的旁路状态 |
| `audit.py` | 六字段审计、哈希链、校验 | 被业务代码裁剪字段 |
| `banking/` | Mock 数据与仓储 | 编造数据 / 连接真实银行 |

### 5.3 八条信任不变量（任何改动不得破坏）

1. **LLM 只产出计划**：不签名、不授权、不执行、不解释审计结果。
2. **统一网关**：所有工具调用只有一条入口，权限判断不散落在工具内部。
3. **确认绑定动作**：确认凭证必须绑定用户、计划哈希、参数、风险等级、一次性 nonce 与过期时间；执行前重算校验。
4. **风险只升不降**：工具基线风险 + 动态规则决定等级，模型输出不得降低。
5. **审计不可裁剪**：触发时间、原始指令、DAG 路径、工具入参、执行结果、确认状态 + 哈希链。
6. **失败不伪装成功**：服务未就绪、依赖失败、结果未知都必须显式暴露（fail closed / `UNKNOWN`）。
7. **数据来源可分层**：Mock 数据、人工确认、策略判断、审计链必须可区分。
8. **最小数据**：不存真实凭证与客户数据；证据优先存哈希而非原文。

### 5.4 不变量与当前实现的差距（诚实标注）

| 不变量 | 当前状态 | 归属阶段 |
|---|---|---|
| 1 LLM 只产出计划 | 已实现（Planner 不执行） | ✅ |
| 2 统一网关 | 已实现 | ✅ |
| 3 确认绑定动作 | 部分：已有 `plan_hash` 与参数，缺 nonce/expiry/审批令牌与执行前重算 | 阶段 1 |
| 4 风险只升不降 | 已实现 | ✅ |
| 5 审计不可裁剪 | 已实现哈希链，缺证据来源分层 | 阶段 1 |
| 6 失败不伪装成功 | 部分：缺 `/api/health/ready` 与前端 fail closed、缺 `UNKNOWN` 状态 | 阶段 1 |
| 7 数据来源可分层 | 未实现（`source/verified/verification_kind`） | 阶段 1 |
| 8 最小数据 | 已实现（哈希链 + 库内状态） | ✅ |

---

## 6. 赛题差距矩阵

| 赛题要求 | 当前状态 | 差距 | 归属 |
|---|---|---|---|
| 至少 3 个核心场景 | 转账 / 账单分析 / 卡片管理 / 订阅取消 / 跨场景 DAG | 场景深度可加强（定时转账、理财申购） | 阶段 2 |
| 绿色自动执行 | 已实现 | — | ✅ |
| 黄色用户确认 | 已实现（≤1000 元日累计小额转账、卡片设置、订阅取消） | — | ✅ |
| 红色强验证（>1000 元） | 已实现分级 + 演示 OTP | 缺人脸/短信/U 盾级多因子演示 | 阶段 2 |
| 幻觉防护 | 数据来自 Mock 仓库 + Schema 校验 | 缺独立事实校验与自述拦截 | 阶段 1 |
| Prompt 注入防御 | 网关正则拦截 | 升级为「命中整条请求拒绝」+ 候选白名单 | 阶段 1 |
| 完整操作审计 | 六字段 + 哈希链 | 证据来源分层 | 阶段 1 |
| 异常熔断 | 未实现 | 连续失败/可疑行为锁定 | 阶段 2 |
| 工具沙箱 | 未实现 | 受限、可监控的执行环境 | 阶段 2 |
| 模糊/省略/隐含意图 | 规则 Planner 有澄清字段 | 多轮上下文与指代消解不足 | 阶段 2 |
| 复杂任务 DAG | 已实现两步跨场景 DAG | 缺步骤级中断、回退、人工接管 | 阶段 2 |
| APP / IM 入口 | 仅 Web | 缺 IM 适配器 | 阶段 2 |
| 五类交付物 | 源码 / README / 部署 / 测试较完整 | 缺简介、PPT、视频、安全自评 | 阶段 3 |

---

## 7. 路线图：阶段 0 → 1 → 2 → 2.5 → 3

### 7.0 阶段 0：产品边界与仓库定型（已完成，本次收尾）

已完成的清理：

- 上游 PR 材料从产品 `main` 移出，归档到 `archive/upstream-plan-provenance`；
- README 只保留银行 Agent 产品叙事，新增 `docs/UPSTREAM-NOTES.md` 说明参考边界；
- 新增 `docs/ROADMAP.md`、`docs/UX-DOGFOODING.md`、产品介绍页与真实截图；
- MIT License、GitHub Public 仓库、默认分支 `main`。

本次收尾补充（补齐「未完成」项）：

- 重写 `AGENTS.md`：反映当前产品范围、阶段状态、Linux 主线目录与可用门禁命令；
- 新增 `CONTRIBUTING.md`：贡献流程、分支模型、代码与安全约定；
- 重写 `docs/DEVELOPMENT-ENVIRONMENT.md`：记录 Linux ext4 主线、冻结 Windows 副本、2026-10-23 复验数据；
- 更新 `docs/TECH-STACK.md` 运行环境说明；
- 更新 `docs/ROADMAP.md` 的阶段 0 完成清单与验收；
- 新增本总规划文档 `docs/MASTER-PLAN.md`，并加入 README 文档索引。

**阶段 0 退出标准**：`main` 无上游材料、文档与实现一致、根目录工程文件齐全（README / LICENSE / CONTRIBUTING / AGENTS / docs）、门禁与测试全绿、环境记录可复现。→ **满足**。

### 7.1 阶段 1：吸收 AegisAgent 的信任工程（下一步）

目标：把上游可借鉴的身份、策略、证据与状态恢复设计，移植成 Python 侧的小模块，不改变产品主流程与技术栈。

计划任务与产出：

| # | 任务 | 产出文件/接口 | 验收 |
|---|---|---|---|
| 1 | Action Envelope | `backend/aegisbank_api/trust/action_envelope.py` | 确认与执行绑定同一 envelope；篡改参数/过期/nonce 复用均被拒 |
| 2 | 幂等键与执行前持久化 | `trust/idempotency.py` | 重复提交不产生第二笔任务；结果未知可查询原任务 |
| 3 | 状态机扩展 | `trust/state_machine.py` | 增加 `UNKNOWN` / `RECONCILED` / `ROLLED_BACK`，非法迁移被拒 |
| 4 | readiness 与 fail closed | `trust/readiness.py` + `GET /api/health/ready` + 前端禁用写操作 | 服务未就绪时明确原因，不显示“成功” |
| 5 | 证据来源分层 | `trust/evidence.py` | 审计与 API 返回 `source / verified / verification_kind` |
| 6 | 注入整条拒绝 | `gateway.py` 升级 | 命中注入时整条请求拒绝，不生成可执行计划 |
| 7 | 模型候选白名单与冲突校验 | `planning/llm.py` | 模型不能覆盖用户给定的账户/金额；冲突转澄清 |

### 7.2 阶段 2：比赛硬要求补齐

| # | 任务 | 关键点 | 验收 |
|---|---|---|---|
| 1 | 步骤级暂停、回退、补偿 | 每个工具声明可补偿性与补偿动作；DAG 支持中途暂停与人工接管 | 跨场景 DAG 任一步失败可回退，且审计记录回退路径 |
| 2 | 异常熔断 | 连续失败 / 可疑行为计数 → 临时锁定，UI 显示锁定原因与恢复方式 | 触发锁定后写操作被拒且可审计 |
| 3 | 工具执行沙箱 | 工具运行在受限、可监控环境（超时/资源限制/无外网/结构化输入输出） | 越界调用被限制并有日志 |
| 4 | 演示 MFA Provider | OTP + 模拟人脸/设备确认；Provider 可插拔 | 红色操作可选择验证方式，审计记录验证方式与结果 |
| 5 | IM 渠道适配器 | 至少一个 IM 通道（webhook/CLI/HTTP 适配层）复用同一网关 | 通过 IM 完成一次绿色 + 一次红色流程 |
| 6 | 多角色与撤权 | 用户 / 运营 / 审计角色；权限撤回后立即生效 | 撤权后待确认动作被阻断并留痕 |

### 7.3 阶段 2.5：人工用户体验（开发者 Dogfooding）

目的：在制作比赛材料前，开发者暂时忘掉实现细节，按真实用户路径连续使用产品，找出「代码能跑但人不会用」的问题。

三轮计划：

1. **第一轮 · 无脚本首次使用**：只读 README 启动，不看 API 文档，完成银行概览 / 账单分析 / 转账 / 卡片管理 / 权限与审计；记录所有卡点。
2. **第二轮 · 安全与异常路径**：撤权后重试、OTP 错误、重复确认与刷新、服务离线、空数据、注入请求。
3. **第三轮 · 修复后回归**：连续完成三场景，更新真实截图，形成 UX 验收记录。

退出标准：

- 3 个核心场景从首次打开到完成均不超过 10 分钟；
- 无 P0/P1 可用性阻塞；
- 关键页面均有 loading / empty / error 状态；
- 确认、MFA、撤权、审计证据能被非开发者理解；
- 截图与当前界面一致，README 与产品介绍页同步更新。

详细执行清单见 [`docs/UX-DOGFOODING.md`](UX-DOGFOODING.md)；执行记录落到 `docs/UX-RECORD.md`（阶段 2.5 创建）。

### 7.4 阶段 3：比赛交付

| 交付物 | 要求 | 状态 |
|---|---|---|
| 作品简介 | ≤200 字，含创作理念与所用 AI 技术 | 待产出 |
| 技术文档 | 系统架构图、核心算法说明、安全设计文档 | 已有部分（ARCHITECTURE / BANKING-DOMAIN / SECURITY），需整理成参赛版 |
| 答辩 PPT | 汇报 ≤10 分钟 | 待产出 |
| 演示视频 | ≤5 分钟 | 待产出 |
| 作品信息 | 源码、README、GitHub 地址、部署说明、测试用例 | 基本具备 |
| 安全自评报告 | 权限分级实现说明 + 已知风险清单 | 待产出（SECURITY.md 可作为底稿） |

---

## 8. 阶段 1 详细设计（信任层）

### 8.1 目录

```text
backend/aegisbank_api/trust/
├─ __init__.py
├─ action_envelope.py   # 计划/参数/风险/身份的一次性绑定
├─ idempotency.py       # 幂等键与执行前持久化
├─ state_machine.py     # 任务状态迁移与 UNKNOWN/恢复
├─ evidence.py          # 证据来源分层
├─ readiness.py         # 就绪检查
└─ circuit_breaker.py   # 异常熔断（阶段 2 完成主体，阶段 1 先落骨架）
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
  - nonce: str                   # 一次性随机串
  - issued_at / expires_at: ISO8601
  - confirmation_state: pending|approved|rejected|expired
  - approval_token: str | null   # 演示审批令牌，不写入审计明文
```

规则：

- 用户在黄/红确认时确认的是**这份 envelope**；
- 执行前由服务端重新计算 `plan_hash`、`arguments_hash`、风险等级与权限；
- 任一不一致 → `409 ENVELOPE_MISMATCH`，不执行、不创建任务、不写业务审计；
- `nonce` 只能使用一次，过期或复用一律拒绝。

### 8.3 状态机

```text
DRAFT
 → AWAITING_CONFIRMATION → AWAITING_REAUTH → APPROVED → EXECUTING → COMPLETED
        │                        │                          ├→ FAILED
        ├→ REJECTED              └→ EXPIRED                 └→ UNKNOWN → RECONCILED
        └→ EXPIRED                                                └→ ROLLED_BACK
```

- `UNKNOWN`：执行已发出但结果不确定，**不得自动重复下单**，先核对原操作再决定 `RECONCILED` 或 `ROLLED_BACK`；
- 所有迁移写入审计，非法迁移直接拒绝。

### 8.4 证据分层

```text
source:            mock_bank | human_confirmation | policy_engine | audit_chain
verified:          true | false
verification_kind: tool_result | approval | policy_decision | hash_chain
```

前端据此展示「哪些是 Mock 数据、哪些有人工确认、哪些是策略判断、哪些只是业务状态」。

### 8.5 readiness 与 fail closed

`GET /api/health/ready` 返回各组件状态：

```json
{
  "status": "ready|degraded|not_ready",
  "components": {
    "sqlite": {"ok": true},
    "audit_chain": {"ok": true},
    "mock_bank_seed": {"ok": true},
    "planner": {"mode": "rule", "ok": true}
  }
}
```

- 任一组件的关键项失败 → `not_ready`，前端禁用写操作并显示原因；
- 不允许把“服务离线”显示成“执行成功”。

### 8.6 注入与候选校验

- 注入命中：整条请求拒绝（不进入 Planner，不产生可执行计划），审计记录拒绝原因与命中规则；
- 严格字段白名单：Planner 输出只接受契约内字段；
- 模型不得补全用户未提供的信息，不得覆盖用户新输入的账户/金额，冲突时转澄清；
- fallback 到规则 Planner 时必须显式标记 `planner: rule`。

### 8.7 阶段 1 测试矩阵（至少覆盖）

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

### 8.8 阶段 1 退出标准

- 上述 12 类测试全部纳入自动化测试并通过；
- `docs/SECURITY.md`、`docs/ARCHITECTURE.md`、`docs/ROADMAP.md` 同步更新；
- 门禁五阶段通过，`main` 保持可运行、可演示；
- 前端能展示 readiness 状态、证据来源与 `UNKNOWN` 任务状态。

---

## 9. 阶段 2 详细要点

1. **步骤级暂停 / 回退 / 补偿**：工具 Manifest 增加 `compensable` 与 `compensate` 声明；调度器在步骤间检查暂停信号；失败时按相反顺序执行可补偿步骤；不可补偿步骤必须在确认页面提示「不可撤销」。
2. **异常熔断**：失败计数（滑动窗口）、可疑行为规则（如短时间内多次红色操作、注入命中累计）；触发后进入 `LOCKED`，写操作统一拒绝并在 UI 展示原因与解除方式。
3. **工具沙箱**：工具执行与 API 进程隔离，限制超时、内存、网络与文件访问，只允许结构化输入输出；沙箱拒绝要写入审计。
4. **演示 MFA Provider**：`MfaProvider` 接口 + `OtpProvider` + `SimulatedBiometricProvider`（模拟人脸/设备确认），红色操作按策略选择 Provider，审计记录 `provider` 与 `result`。
5. **IM 渠道适配器**：以适配层形式复用同一 Planner/网关/确认流程，示例可用 Webhook 或 CLI，不另起业务逻辑。
6. **多角色与撤权**：角色与权限矩阵显式化；权限撤回后立即生效；演示「撤权 → 待确认动作被阻断 → 审计可见」。

退出标准：赛题四项硬要求（熔断、沙箱、MFA、IM）均可在演示中一次走通，并有自动化测试或可重复脚本。

---

## 10. 阶段 3 详细要点

- **作品简介**：≤200 字，突出「可信执行控制平面」而非「聊天机器人」；
- **技术文档**：以 `docs/ARCHITECTURE.md`、`docs/BANKING-DOMAIN.md`、`docs/SECURITY.md` 为底稿整理参赛版，附带架构图与风险规则表；
- **答辩 PPT**：10 分钟内讲清「问题 → 方案 → 演示 → 安全边界 → 工程实现」；
- **演示视频**：5 分钟内完成「账单分析 → 跨场景取消订阅 → 880 元黄色确认 → 累计超限红色 OTP → 撤权与审计校验」；
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

- 行为变更同步更新 README / ROADMAP / SECURITY / MASTER-PLAN；
- 阶段结论进入本文档与 `docs/ROADMAP.md`，不留在对话里；
- 对外材料必须与实现一致，未实现的能力标注「计划中」。

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

---

## 13. 风险登记册

| 风险 | 影响 | 应对 |
|---|---|---|
| 赛程时间紧、阶段 1/2 任务多 | 交付材料被压缩 | 阶段 1 先做 6 项核心（envelope/idempotency/state/readiness/evidence/注入），阶段 2 按赛题优先级排序 |
| 沙箱与回退实现成本高 | 阶段 2 延期 | 先做「受限子进程 + 补偿声明」的最小实现，不追求生产级隔离 |
| 前端与后端字段漂移 | 演示失败 | 接口契约集中在 `docs/ARCHITECTURE.md`，前端以类型测试兜底 |
| 对话上下文丢失 | 决策与结论散失 | 结论强制写入 MASTER-PLAN / ROADMAP，不依赖会话记忆 |
| 评审质疑 Mock 数据 | 被误判为「假系统」 | README/PPT 明确边界与可替换性，强调「可信控制平面」而非真实资金 |
| WSL ext4 分区异常 | 开发环境不可用 | 保留备份目录与 GitHub 远端；关键提交及时推送 |
| 上游参考被过度借鉴 | 范围蔓延 | 遵守 D2 与 `docs/UPSTREAM-NOTES.md`，不引入链上组件 |

---

## 14. 里程碑（建议，按相对时间）

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M1（T+0，已完成） | 阶段 0 收尾 + 总规划 | 本文档 + 门禁全绿 |
| M2（T+3 天） | 阶段 1 信任层 | 12 类测试通过，前端展示 readiness/证据/UNKNOWN |
| M3（T+8 天） | 阶段 2 硬要求 | 熔断、沙箱、MFA、IM 四件套可演示 |
| M4（T+11 天） | 阶段 2.5 Dogfooding | 三轮完成，无 P0/P1，截图更新 |
| M5（T+14 天） | 阶段 3 交付 | 简介 / PPT / 视频 / 安全自评齐备，仓库打 tag |

---

## 附录 A：术语表

| 术语 | 含义 |
|---|---|
| Mock Bank Core | 确定性的本地银行数据层，所有金融事实的来源 |
| Planner | 把自然语言编译成结构化计划的组件，只产出计划 |
| Plan Compiler | 校验计划并生成规范化 `plan_hash` 的确定性组件 |
| Action Envelope | 绑定身份、计划、参数、风险、nonce 与过期时间的一次性确认凭证 |
| 绿/黄/红 | 自动执行 / 用户确认 / 强验证三级执行策略 |
| UNKNOWN | 执行结果不确定的中间态，防止重复下单 |
| Fail closed | 依赖不可用或状态不明时默认拒绝，而非放行 |
| Dogfooding | 开发者以真实用户身份使用自家产品并记录摩擦 |

## 附录 B：关键文件索引

| 文件 | 内容 |
|---|---|
| `README.md` | 产品介绍、场景、架构、快速开始、已知边界 |
| `docs/MASTER-PLAN.md` | 本文档：总规划与阶段设计 |
| `docs/ROADMAP.md` | 路线图与阶段任务 |
| `docs/UX-DOGFOODING.md` | 阶段 2.5 执行清单 |
| `docs/ARCHITECTURE.md` | 模块边界与端到端数据流 |
| `docs/BANKING-DOMAIN.md` | 银行领域模型、三场景与跨场景 DAG |
| `docs/SECURITY.md` | 安全边界与生产化清单 |
| `docs/TECH-STACK.md` | 技术选型与环境 |
| `docs/DEVELOPMENT-ENVIRONMENT.md` | 开发环境、复验记录与目录说明 |
| `docs/UPSTREAM-NOTES.md` | 上游参考边界与归档分支说明 |
| `AGENTS.md` / `CONTRIBUTING.md` | 工程约定与贡献指南 |

## 附录 C：评审现场演示脚本（5 分钟）

1. 打开银行概览：账户、卡片、订阅、异常订阅 `SUB-3002`；
2. 任务控制台输入「分析我的本月账单」→ 绿色自动执行，展示分类与异常；
3. 输入「分析我的账单并取消异常订阅」→ 展示两步 DAG 与前序变量解析；
4. 输入「向 ACC-2002 转账 880 元」→ 黄色确认弹窗，展示计划与风险原因；
5. 同日再转 500 元 → 累计超 1000 元升级红色，输入演示 OTP `246810`；
6. 权限控制台撤回 `transfer` 权限 → 再次执行被网关阻断并显示原因；
7. 操作审计页校验 SHA-256 哈希链，展开一条记录查看完整证据。

## 附录 D：上游 AegisAgent 能力映射

| 上游能力 | 本项目处理方式 |
|---|---|
| LLM draft-only、严格 schema | 吸收（Planner 契约 + Compiler） |
| 统一 PolicyEngine | 吸收（统一权限网关） |
| preview/submit 绑定哈希 | 吸收（Action Envelope，阶段 1） |
| 幂等、执行前持久化、UNKNOWN | 吸收（阶段 1） |
| readiness / fail closed | 吸收（阶段 1） |
| 证据与事件绑定 | 吸收（证据来源分层） |
| 注入整条拒绝 | 吸收（阶段 1） |
| Gas 储备、native ETH 业务 | 不搬（与银行场景无关） |
| Chainlink ETH/USD 定价 | 不搬（银行风险不用链上价格） |
| Owner 钱包审批替代 MFA | 不搬（改用演示 MFA Provider） |
| 链上 PolicyEngine 替代业务策略 | 不搬（保留 Python 策略层） |
