# 草案计划溯源（Draft Plan Provenance）设计说明

状态：待评审建议稿

日期：2026-10-20

相关文件：`backend/src/parser.ts`、`backend/src/llm.ts`、`backend/src/service.ts`、`packages/shared/src/index.ts`、`docs/ARCHITECTURE.md`、`docs/SECURITY.md`

## 评审摘要

本 PR 只新增设计文档，不修改代码、不修改合约，也不改变当前 native ETH 单动作范围。

要解决的问题：

> 原项目可以证明付款满足链上策略并有匹配的交易事件，但还不能证明这笔任务来自用户刚刚审阅的同一份 draft、parser 结果和 quote。

建议增加：

- 一个版本化对象 `DraftPlanV1`；
- `draftHash`、`quoteHash`、`planHash`；
- preview 返回 `planHash`；
- submit 必须携带 `planHash`，并由服务端重新计算；
- task/evidence 暴露 provenance hashes；
- hash 不一致时 fail closed，不创建 task、不准备交易、不广播。

本次 PR 需要评审决定的内容：

1. 是否接受 `planHash` 这个 provenance 概念；
2. hash 覆盖字段是否合理，尤其是 parser reason 和 quote 观测区块；
3. submit 新增必填字段是否可接受，是否需要先做兼容期；
4. 第一阶段只做 off-chain provenance 是否足够；
5. 未来是否需要把 `planHash` 锚定到链上。

明确不改：

- Wallet、PolicyEngine、Oracle、签名和 Owner 审批；
- 单动作 native ETH 范围；
- LLM draft-only 边界；
- 链上 `requestHash`、事件证据和现有 API 语义。

## 0. 10 分钟评审路径

1. 先读"评审摘要"，确认问题、建议改动和需要决策的事项。
2. 看第 1 节"本 PR 增加了什么"，确认本 PR 的范围。
3. 看第 5 节改造前后示例，判断用户体验和 API 变化是否合理。
4. 看第 7 至 8 节安全不变量和验收标准，确认是否存在未覆盖的篡改路径。
5. 在第 12 节按产品、后端、合约三个维度给出评审意见。
6. 如果认可方向，再讨论第 10 节的实现拆分顺序。

本文件的建议是：先接受或修改协议，再进入实现；不建议把设计讨论和代码实现放在同一个 PR 里。

## 1. 本 PR 增加了什么

| 原项目现状 | 本提案增加的内容 |
|---|---|
| `Intent`、`Quote` 和 `Task` 已有相关字段，但 provenance 分散在多个记录中 | 一个版本化 `DraftPlanV1` 契约，明确绑定对象 |
| task evidence 分别暴露 recipient、amount、requestHash、parser | 在 task/evidence 中增加 `draftHash`、`quoteHash`、`planHash` |
| preview 返回 quote 上下文，但没有单一确认指纹 | preview 返回 `planHash`，用户确认这个精确值 |
| submit 检查 revision 和 quote ID | submit 额外要求 `planHash`，并由服务端重算 |
| 链下 draft 和 parser 被修改时，task evidence 无法检测 | hash 不一致时阻断 task 创建和广播 |
| parser fallback 只是说明性信息 | parser kind、model、reason 进入 hash provenance |
| 没有专门的验证向量 | 后续在 `backend/test/plan.test.ts` 增加 golden vector 和篡改测试 |

本 PR 不修改运行代码。上表描述的是后续实现 PR 应达到的目标状态。

## 2. 范围与非目标

### 范围内

- 增加版本化的 draft、quote、parser provenance 契约；
- preview 返回 `planHash`；
- submit 要求并重新计算 `planHash`；
- task 和 evidence 暴露 provenance hashes；
- 增加确定性测试矩阵，覆盖篡改和版本漂移。

### 范围外

- 不增加多动作 DAG、订阅、swap、ERC-20、跨链或银行工具；
- 不改变 native ETH 单动作范围；
- 不声称 LLM 推理诚实、完整或安全；
- 不改变 Wallet、PolicyEngine、Oracle、签名或审批语义；
- 不证明自然语言本身，只绑定其 digest；
- 不替代 `requestHash`、链上事件或 PolicyEngine 检查。

## 3. 当前状态与缺口

当前流程是刻意收窄且安全的：

1. `parseDraft()` 或 `parseDraftWithLlm()` 生成 draft-only `Intent`；
2. `preview()` 创建 `Quote`，绑定 `draftId`、`draftVersion`、`policyVersion`、quote 过期时间和 deadline；
3. `submit()` 检查 `expectedRevision`、`quoteId`、quote 是否过期，以及 quote 与 intent 的 recipient、amount 是否一致；
4. Wallet 用链上 `requestHash` 绑定 agent、recipient、amount、USD cap、nonce、deadline 和 policyVersion；
5. 回执和事件用于判断付款是已执行、待审批还是已取消。

这条链路对授权和执行是强的，但它不能证明下面这句话：

> 这笔付款来自用户刚刚审阅的同一份 draft、parser 结果和 quote。

原因如下：

- `Intent.message`、`purpose` 和 `parser` 存在链下，没有被确定性 digest 覆盖；
- `Task` 会复制 `parser`，但 `publicTask()` 和 `evidence()` 没有给出一个能从原始 draft 和 quote 重算的 hash；
- 数据库写入者可以在事后修改 message、purpose 或 parser metadata，而链上 `requestHash` 不会变化，因为这些字段不在链上请求中；
- 审核者无法用单一可验证标识对比用户看到的 preview 和最终 task。

这不是说当前流程有漏洞，而是两个陈述之间存在差距：

> 付款满足链上策略，并且有匹配的交易证据。

和

> 付款来自用户审阅的同一份 draft、parser 决策和 quote。

第二个陈述需要明确的 provenance 契约。

## 4. 与 AegisBank 参考手册的关系

PDF 参考手册描述的是银行 Agent，本提案不把其产品范围复制到 AegisAgent。这里只借鉴其信任与审计原则。

| 参考手册原则 | AegisAgent 当前对应实现 | 本提案增加的改进 |
|---|---|---|
| 身份必须唯一、可验证、可调用、操作不可抵赖 | Owner 钱包挑战签名、executor key、链上地址 | 把已审阅的 draft、parser、quote 绑定为可重算 plan hash |
| 网关是访问数据和工具的唯一路径 | Wallet、PolicyEngine、preview/submit 检查 | submit 时重算 provenance，不一致即 fail closed |
| 工具调用应标准化 | 单一 native ETH 动作和严格 draft schema | 版本化 `DraftPlanV1` 契约 |
| 审计必须属于执行链路，而不是事后附属 | `requestHash`、合约事件、task evidence | 在执行前把 plan hashes 放入 task evidence |
| 绿、黄、红三级交互 | 自动执行、Owner 审批、拒绝 | 保持不变，provenance 不影响策略决策 |
| 操作记录应签名且不可抵赖 | Owner 交易和合约事件 | 增加 draft 到 task 的可验证关联，但不声称它是链上证明 |
| 不采用 P2P，不在本地保存全量金融数据 | 中心化钱包、最小 SQLite 状态 | 只使用链下 hash，不把原始 payload 放进 evidence |

参考手册还要求审计记录回答：触发时间、原始指令、DAG 路径、工具参数、执行结果和确认状态。AegisAgent 已有金融请求和链上事件，缺的是原始指令和 draft/quote 上下文。本提案用 hash 补上这部分。

## 5. 改造前后示例

用户请求：

```text
向 0x1111111111111111111111111111111111111111 转 0.001 ETH，用途是服务器托管。
```

### 当前状态

task/evidence 可以证明：

- 收款人和金额；
- requestHash 和合约事件；
- parser 类型和模型；
- policyVersion 和交易证据。

但这些记录之间没有覆盖 reviewed draft 与 quote 的 digest。如果有人修改 SQLite 中的 message、purpose、parser.reason 或 draft revision，链上 requestHash 不会变化。

### 改造后

preview 返回：

```json
{
  "quoteId": "a3f...",
  "draftVersion": 1,
  "draftHash": "0x...",
  "quoteHash": "0x...",
  "planHash": "0x..."
}
```

submit 请求体变成：

```json
{
  "expectedRevision": 1,
  "quoteId": "a3f...",
  "planHash": "0x..."
}
```

task/evidence 返回相同 hash 和 provenance 对象。如果 draft、parser reason、quote policyVersion 或观测区块上下文发生变化，服务端重算结果会不同，submit 返回 `409 PLAN_HASH_MISMATCH`。

## 6. 方案设计

### 6.1 版本化规范对象

在 shared types 中增加一个小型、带 domain separation 的契约：

```ts
export interface DraftPlanV1 {
  schemaVersion: 'aegis.draft-plan.v1';
  draftId: string;
  revision: number;
  action: 'transfer';
  messageHash: Hex;
  purposeHash: Hex;
  recipient: Hex;
  amountWei: string;
  parser: ParserInfo;
  quote: {
    quoteId: string;
    draftVersion: number;
    policyVersion: string;
    quoteExpiresAtSeconds: number;
    requestDeadlineSeconds: number;
    observedBlockNumber: string;
    observedBlockHash: Hex;
  };
}
```

hash 规则：

```text
canonicalJson = 按 key 排序、字符串转义稳定、不包含 undefined 字段的 JSON
draftHash    = keccak256(utf8("aegis.draft-plan.v1\ndraft\n" + canonicalJson(draft)))
quoteHash    = keccak256(utf8("aegis.draft-plan.v1\nquote\n" + canonicalJson(quote)))
planHash     = keccak256(utf8("aegis.draft-plan.v1\nplan\n" + draftHash + quoteHash))
```

`messageHash` 和 `purposeHash` 必须从原始字段重新计算，再参与 draft digest。使用 `keccak256` 而不是 SHA-256，是为了未来可以把同一个构造直接变成链上 `bytes32` commitment，而不需要重新设计。版本字符串属于 domain separator；字段集合变化时必须升级版本。

### 6.2 生命周期

```text
create/patch intent
  -> 根据规范化 Intent 计算 draftHash
  -> preview(quote)
  -> 计算 quoteHash 和 planHash
  -> 把 planHash 返回给客户端
  -> 用户审阅并确认这个精确的 planHash
  -> submit(expectedRevision, quoteId, planHash)
  -> 服务端根据已存储的 intent 和 quote 重新计算
  -> 不一致则返回 409 PLAN_HASH_MISMATCH，不创建 task
  -> task 保存 draftHash、quoteHash、planHash
  -> task/evidence 暴露 hashes 和重算说明
```

客户端传来的 `planHash` 只是确认绑定，不是授权凭证。服务端必须从存储的 intent 和 quote 重新计算，不能信任客户端值。

### 6.3 API 变更

采用增量字段，避免破坏现有客户端：

| 接口 | 变更 |
|---|---|
| `GET /api/v1/intents/:id` | 增加 `draftHash` |
| `POST /api/v1/intents` 和 `PATCH /api/v1/intents/:id` | 增加 `draftHash` |
| `POST /api/v1/intents/:id/preview` | 返回 `draftHash`、`quoteHash`、`planHash` |
| `POST /api/v1/intents/:id/submit` | 要求 `planHash` |
| `GET /api/v1/tasks/:id` | 暴露 `draftHash`、`quoteHash`、`planHash` |
| `GET /api/v1/tasks/:id/evidence` | 增加 `provenance` 对象 |
| `GET /api/v1/config` | 公布 `planProvenance: "aegis.draft-plan.v1"` |

evidence 增加示例：

```json
{
  "provenance": {
    "schemaVersion": "aegis.draft-plan.v1",
    "draftHash": "0x...",
    "quoteHash": "0x...",
    "planHash": "0x...",
    "hashAlgorithm": "keccak256",
    "recompute": "docs/DRAFT-PLAN-PROVENANCE.md"
  }
}
```

submit 缺少 `planHash` 时返回 400 级请求错误，不能静默默认。上线过渡期可以先让 backend 在 `/config` 公布字段，再由前端开始发送。

### 6.4 代码归属

| 文件 | 职责 |
|---|---|
| `packages/shared/src/index.ts` | `DraftPlanV1`、`PlanProvenance`、domain 常量 |
| `backend/src/plan.ts`（新增） | canonical JSON 和 domain-separated keccak256 函数 |
| `backend/src/service.ts` | 计算、重算、校验 hash，并保存到 task |
| `backend/src/server.ts` | submit 的严格 Zod schema，加入 `planHash` |
| `frontend/src/main.ts` | 展示短 hash 和复制按钮，用清晰文案解释其含义 |
| `backend/test/plan.test.ts`（新增） | golden vectors 和篡改测试 |
| E2E 测试 | 验证 preview hash 经过确认、提交、刷新后保持一致 |

hash 函数必须是纯函数，可以不依赖 RPC、LLM 或 SQLite 单独测试。

### 6.5 建议实现骨架

```ts
// backend/src/plan.ts
export function canonicalJson(value: unknown): string { /* key 排序、类型稳定 */ }

export function hashDomain(domain: string, value: unknown): Hex {
  return keccak256(toUtf8Bytes(`aegis.draft-plan.v1\n${domain}\n${canonicalJson(value)}`));
}

export function computeDraftHash(intent: Intent): Hex { /* messageHash + purposeHash + 字段 */ }
export function computeQuoteHash(quote: Quote): Hex { /* quote + policy/block context */ }
export function computePlanHash(draftHash: Hex, quoteHash: Hex): Hex { /* domain-separated */ }
```

实现 PR 至少应包含一个 golden vector，使其他进程或其他语言可以复现 digest。

## 7. 安全不变量

1. `planHash` 必须由服务端根据已存储的 draft 和 quote 重新计算；`messageHash` 和 `purposeHash` 必须从原始字段重算后再参与 hash。
2. draft 一旦被编辑，之前的 preview、quote 和 plan hash 全部失效。
3. Parser metadata（`kind`、`model`、`configuredModel`、`fallback`、`reason`）必须纳入 digest，防止模型回退被事后改写。
4. 来自其他 draft、revision 或 policyVersion 的 quote 不能产生相同的 `planHash`，因为相关字段都进入规范对象。
5. `planHash` 不是授权 token，不能绕过 PolicyEngine、Owner 审批、nonce、deadline 或链上检查。
6. 本变更不把原始 message、purpose 或 API key 放进 task evidence 或日志。
7. 不一致时必须 fail closed：不创建 task、不准备交易、不广播。

## 8. 验收标准

- [ ] 相同 intent 和 quote 在不同进程中产生相同 `planHash`。
- [ ] message、purpose、recipient、amount、revision、parser model、parser reason、quote id、policyVersion 或 quote 过期时间任一变化，hash 必须变化。
- [ ] preview 返回 `planHash`；submit 缺少该字段时被拒绝。
- [ ] 携带正确 `planHash` 的 submit 成功，task/evidence 返回相同值。
- [ ] draft 编辑后提交旧 hash，或使用其他 quote 的 hash，返回 `409 PLAN_HASH_MISMATCH`，不创建 task。
- [ ] 相同 idempotency key 和相同请求体重放时返回原 task，不创建第二笔付款。
- [ ] 现有流程、typecheck、build、backend tests 和 E2E tests 保持通过。
- [ ] evidence 包含 provenance hashes，并明确说明这是 off-chain provenance，不是 on-chain proof。
- [ ] UI 文案明确说明 hash 是"确认绑定"，不是"执行证明"。

## 9. 测试矩阵

| 场景 | 预期 |
|---|---|
| 创建 draft -> preview -> 用返回的 planHash submit | 202，task 中 hash 一致 |
| preview 后编辑 draft，再用旧 planHash submit | 409 `PLAN_HASH_MISMATCH` |
| 使用其他 draft/quote 的 planHash | 409 `PLAN_HASH_MISMATCH` |
| 修改存储记录中的 parser fallback reason | 重算 hash 不同，submit 被拒绝 |
| 修改 quote 的 policyVersion | hash 不一致 |
| 缺少 planHash | 400 `INVALID_REQUEST` |
| 相同 idempotency key 和相同请求体 | 返回原 task |
| 相同 idempotency key 和不同 planHash | 409 `IDEMPOTENCY_CONFLICT` |
| 按 evidence 重算 provenance | `draftHash`、`quoteHash`、`planHash` 全部匹配 |
| 篡改链下 message 或 purpose | digest 不一致，task 不被接受 |
| 现有 mock chain 流程 | 行为不变 |

## 10. 评审后的实现拆分

为了保持实现可评审，本设计 PR 之后建议拆成以下步骤：

1. **PR A（本 PR）：** 确认契约和范围。
2. **PR B：** 增加 `backend/src/plan.ts`、`backend/test/plan.test.ts` 和 shared types。此阶段只做纯 hash 模块和 golden vectors，不接 service/API。
3. **PR C：** 接入 preview、submit、task、evidence，补充 API 兼容和前端文案。
4. **PR D（可选）：** 增加 CLI verifier，并将 `planHash` 放入 evidence bundle 或 attestation data URI。
5. **PR E（仅在必要时）：** 在新 policy domain 版本中做链上锚定。

这个顺序可以让第一个实现 PR 足够小，避免把 hash 契约讨论和合约、部署风险混在一起。

## 11. 风险与边界

| 风险 | 缓解措施 |
|---|---|
| 链下 hash 可被完全被攻陷的后端重算 | 明确信任边界；如确有需要，再规划链上锚定 |
| 不同 Node 版本的 canonical JSON 实现不一致 | 使用纯 canonical JSON 实现，并加入 golden vector 测试 |
| schema 变化破坏旧客户端 | 只做增量字段，并引入版本化 domain string |
| 用户误以为 planHash 是付款证明 | UI 和文档明确写"确认绑定，不是执行证明" |
| 额外 hash 影响 demo 速度 | hash 只在本地 CPU 计算，不增加链上调用 |
| 原始 message 含敏感信息 | 默认只导出 hash，原始数据继续留在现有本地 DB |

第一阶段可以检测意外漂移和链下记录替换，但它不能防止完全被攻陷的后端或数据库管理员。因此文档必须保持诚实，并把链上锚定作为后续明确决策，而不是隐含承诺。

## 12. 评审问题

### 产品与交互

1. `planHash` 是展示给所有用户，还是只放在高级 evidence 页面？
2. 文案用"审阅指纹"还是"plan hash"？
3. 对低风险自动执行，增加确认 payload 是否值得？当前提案把 hash 放在 preview/submit 边界，不影响 PolicyEngine 的自动执行决策。

### 后端与 API

4. `draftHash` 在创建时暴露，还是等 preview 再暴露？
5. submit 是否立即强制要求 `planHash`，还是先提供一个版本的兼容期，缺失时记录日志，之后强制？
6. `quoteHash` 是否包含 observed block hash 和 block number？建议包含。
7. parser `reason` 是否进入 hash？建议进入，因为它已经是 `ParserInfo` 的一部分，是重要的 provenance 信息。

### 合约与安全

8. 当前阶段只做链下 provenance 是否足够？
9. 如果未来做链上锚定，`planHash` 应该进入 `requestHash`，还是单独字段或事件？单独字段更清楚，但占存储；进入 requestHash 更省，但需要升级 domain version。
10. 第一阶段是否需要 CLI verifier，还是只提供文档化的重算步骤？

## 13. 为什么适合当前仓库

- 保留单动作 native ETH 范围；
- 扩展现有 `Intent`、`Quote`、`Task` 和 evidence 模型，不引入并行 Agent 框架；
- 强化项目"可执行、可验证、可追溯"的定位，但不假装 LLM 或链下数据库可信；
- 为未来是否做链上 commitment 留出清晰接口，同时保持第一个 PR 小而可测。

最小且诚实的版本是：一个纯 hash 模块、一个 submit 字段、一个 task provenance 对象和一组以篡改为核心的测试。

## 附录 A：开发讨论检查清单

评审时可以直接逐项确认：

- [ ] 问题陈述是否成立？
- [ ] 是否保持单动作范围？
- [ ] hash 字段是否充分且不过度？
- [ ] 失败模式是否 fail closed 且可观测？
- [ ] 现有 API 客户端是否保持兼容？
- [ ] evidence 的声明是否明确限制为 off-chain provenance？
- [ ] 是否存在不依赖链即可测试的第一个实现 PR？
- [ ] 链上锚定是否被明确推迟，而不是被暗示为已完成？

## 附录 B：非声明

本设计不声称：

- LLM 产生的计划正确或诚实；
- 原始自然语言本身被证明；
- 链下数据库不可篡改；
- `planHash` 可以替代 `requestHash` 或合约事件；
- 本提案改变策略决策或审批流程；
- 多动作规划属于当前项目范围。
