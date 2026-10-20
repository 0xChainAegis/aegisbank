## 概述

本 PR 增加草案计划溯源（Draft Plan Provenance）的设计说明和第一阶段实现。

目标是让 task/evidence 能够回答：

> 这笔付款是否来自用户刚刚审阅的同一份 draft、parser 决策和 preview quote？

当前链上证据可以证明付款满足 PolicyEngine 策略并有匹配事件，但不能直接证明上述关联。本 PR 用可重算的 hash 补上这一层链下 provenance。

## 主要改动

### 1. 设计说明

新增/更新：

- `docs/DRAFT-PLAN-PROVENANCE.md`
- 中文评审摘要和评审路径
- 与 AegisBank 参考手册的信任原则映射
- 安全不变量、测试矩阵和后续拆分

### 2. 纯 hash 模块

新增：

- `backend/src/plan.ts`
- `backend/test/plan.test.ts`

包括：

- canonical JSON
- domain-separated `keccak256`
- `computeDraftHash`
- `computeQuoteHash`
- `computePlanHash`
- `computePlanProvenance`
- `verifyPlanHash`
- golden vector 和篡改测试

### 3. 数据契约

更新：

- `packages/shared/src/index.ts`
- `backend/src/chain.ts`

增加：

- `DraftPlanV1`
- `PlanProvenance`
- `Intent.draftHash`
- `Task.provenance`
- `Quote.draftHash / quoteHash / planHash`

### 4. API 与执行链路

更新：

- `backend/src/service.ts`
- `backend/src/server.ts`
- `frontend/src/main.ts`

行为变化：

- intent create/patch 返回 `draftHash`
- preview 返回 `draftHash`、`quoteHash`、`planHash`
- submit 必须携带 `planHash`
- 服务端根据已存储的 intent 和 quote 重新计算
- 不一致返回 `409 PLAN_HASH_MISMATCH`
- 不创建 task、不准备交易、不广播
- task 和 evidence 暴露同一份 provenance
- `/api/v1/config` 公布 `planProvenance: aegis.draft-plan.v1`

### 5. 测试

更新：

- `backend/test/api.test.ts`
- `e2e/wallet.topup.spec.ts`

新增测试覆盖：

- preview 返回计划 hash
- submit 缺少/错误 hash 被拒绝
- task/evidence 保留同一 planHash
- 错误 hash 不创建 task、不准备交易、不广播
- E2E 中检查 preview、submit、evidence 的 hash 一致性

## 本地验证

已执行：

```bash
npm run check
```

结果：

- typecheck 通过
- backend build 通过
- frontend production build 通过
- 34 项合约测试通过
- 51 项后端测试通过
- Playwright 16 个用例可被正确发现

未在本地启动完整浏览器 E2E 环境；CI 会在批准 workflow 后执行 Playwright。

## 明确不改

- 不修改 Wallet、PolicyEngine、Oracle 或部署脚本
- 不修改 Owner 签名和审批语义
- 不扩展 native ETH 单动作范围
- 不声称 LLM 推理或原始自然语言本身被证明
- 不把 off-chain provenance 描述成 on-chain proof

## 需要评审关注

1. `planHash` 覆盖字段是否合适？
2. submit 新增必填字段是否需要兼容期？
3. parser reason 和 quote 观测区块是否应进入 hash？
4. 第一阶段只做 off-chain provenance 是否足够？
5. 后续是否需要 CLI verifier 或链上锚定？
