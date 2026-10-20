# AegisAgent 上游项目对齐说明

> 上游仓库：<https://github.com/0xChainAegis/aegis-agent>
> 审阅提交：`71930d6`（main，2026-10-20）

本文用于调整本项目早期银行多工具 Agent 计划，使其与真实上游代码和交付边界一致。

## 1. 上游项目实际是什么

AegisAgent 不是一个银行多工具 DAG 项目，而是一个面向智能体运行钱包的 Gas 储备与受限 native ETH 支付系统。

### 已有组件

| 层 | 实际实现 |
|---|---|
| 前端 | Vite + TypeScript DOM UI，钱包登录、储备卡片、确认抽屉、任务与证据 |
| 后端 | Node.js 24 + TypeScript + viem + Zod + SQLite |
| 合约 | Solidity + Hardhat：Wallet、PolicyEngine、Oracle Adapter、Attestation |
| 行情 | Chainlink ETH/USD Data Feed（本地用 Mock Feed） |
| 鉴权 | Owner 钱包挑战签名；后端只持有受限 executor key |
| 审批 | 低风险自动执行；高风险 Owner approveAndExecute |
| LLM | 默认规则解析；live 模式仅生成草稿，不签名、不授权、不执行 |
| 评测 | 40 条意图样本 + rule / stub / live 三种解析器 |
| 范围 | 单资金池、单运行钱包、native ETH；订阅、CCIP、自动监控不在当前交付 |

### 关键信任边界

1. LLM 只产生 draft，不能决定风险、策略、signer、nonce 或 calldata。
2. 后端持有 executor key，不持有 Owner key。
3. 链上 PolicyEngine 统一判断权限、收款人、USD 限额、预算、deadline、policyVersion。
4. Owner 审批是链上交易，不是后端布尔值。
5. 广播前先持久化 signed bytes、tx hash、nonce、requestHash。
6. 只有匹配的 Wallet 事件才证明执行；receipt status=1 不等于付款成功。
7. 证据来自回执/事件，模型输出和自然语言不是执行证明。

## 2. 我们原计划需要调整的地方

| 原计划 | 需要调整 |
|---|---|
| 银行多工具 Agent | 不适用。上游只做运行钱包 Gas 储备和单一 native ETH 支付 |
| DAG 多工具调度 | 不进入上游 MVP；不为了更 Agent 而扩大动作面 |
| 订阅、卡片、跨场景 | 明确是范围外；不能作为第一阶段贡献 |
| 自建权限网关 | 上游已有链上 PolicyEngine + 后端 authorization + 钱包 approval，不重复造 |
| 暂存确认凭证 | 上游已有 quote/revision/deadline/policyVersion/requestHash，先理解再扩展 |
| 结构化 Planner | 上游已有严格的 draft-only parser/LLM 边界，优先增强 provenance 而非替换 |
| 本地金融数据 | 上游只保留任务/证据所需最小状态，不存全量金融数据 |

## 3. 调整后的贡献路线

### P0：Draft Plan Provenance

当前证据链能证明：

> 付款满足链上策略，且有匹配的交易/事件。

但还不能直接证明：

> 这笔任务来自用户刚刚审阅的那份 draft、解析结果和 quote。

拟新增：

- DraftPlanV1 规范化对象；
- draftHash / quoteHash / planHash；
- preview 返回 planHash；
- submit 必填并服务端重算；
- task/evidence 暴露 provenance hashes；
- 不修改合约、PolicyEngine、签名或 native ETH 范围。

设计文件（含中文评审摘要、10 分钟评审路径、PDF 原则映射和实现拆分）：

```text
upstream-pr/aegis-agent/docs/DRAFT-PLAN-PROVENANCE.md
```

补丁：

```text
upstream-pr/aegis-agent/DRAFT-PLAN-PROVENANCE.patch
```

### P1：实现 Draft Plan Provenance

建议实现顺序：

1. packages/shared/src/index.ts 增加 DraftPlanV1 和 Provenance 类型；
2. 新增 backend/src/plan.ts，实现 canonical JSON 与 keccak256；
3. service.ts 在 intent/preview/submit 计算并校验 hash；
4. server.ts submit schema 增加 planHash；
5. publicTask() / evidence() 增加 provenance；
6. backend/test/plan.test.ts 加 golden vector 和篡改测试；
7. 前端显示 planHash，但明确"确认绑定，不是执行证明"。

### P2：证据增强

- 将 planHash 放入本地 evidence bundle 或 attestation dataUri；
- 增加 CLI verifier；
- 评估报告中引用可重算的 provenance 数据；
- 仍不声称 LLM 推理或自然语言本身被证明。

### P3：必要时做链上锚定

只有在前两步被接受、且业务确实需要时，才讨论：

- 新 policy domain 版本；
- 将 planHash 绑入 requestHash，或新增独立字段/事件；
- 合约重新部署、迁移和新的链/数据库验收。

## 4. 不进入上游计划的内容

- 多工具 DAG；
- 订阅、ERC-20、swap、跨链、CCIP；
- 银行账户/账单/卡片管理；
- P2P、去中心化身份、复杂分布式协议；
- 用 LLM 替代权限引擎；
- 自动监控/自动补款（当前明确不在交付范围）。

## 5. PR 策略

采用"先设计、后实现"的两步 PR：

1. docs PR：docs(plan): specify draft plan provenance binding
   - 只增加设计文档；
   - 明确非目标和信任边界；
   - 收集接口/哈希/存储/迁移意见。
2. feat PR：feat(plan): bind reviewed draft and quote to task evidence
   - 实现 plan.ts、类型、API 字段和测试；
   - 不触碰合约；
   - 保持现有 API 兼容。

这样可以把大而全的银行 Agent 想法收敛成上游可评审、可测试、可合入的小增量。

## 6. 验收标准

- 上游 npm run check、npm run test:e2e 保持通过；
- 设计文档明确 off-chain 与 on-chain 边界；
- 不改动合约、权限、签名路径；
- 不同 draft/quote/parser 产生不同 planHash；
- hash 不一致时 fail closed，不创建 task、不广播；
- 证据响应可重算 provenance；
- PR 不包含本地密钥、数据库、测试运行产物或原始模型输出。
