## 概述

本 PR 新增一份中文设计说明，讨论草案计划溯源（Draft Plan Provenance）：

- 用一个版本化 `DraftPlanV1` 对象，把用户审阅的 draft、parser 决策和 preview quote 绑定起来；
- preview 返回 `planHash`；
- submit 必须携带 `planHash`，并由服务端重新计算；
- task/evidence 暴露 provenance hash；
- hash 不一致时 fail closed，不创建 task、不准备交易、不广播。

本 PR 仅修改文档，不修改合约、策略、签名或 native ETH 单动作范围。

## 为什么需要

当前证据链可以证明付款满足链上 PolicyEngine 策略，并且有匹配的交易和事件。但它不能直接证明：

> 这笔付款来自用户刚刚审阅的同一份 draft、parser 结果和 quote。

本设计建议增加一个可重算、可测试、可逐步落地的 provenance 契约，让 task evidence 能回答这个问题，同时明确说明它是 off-chain provenance，不是 on-chain proof。

## 文档内容

- 中文评审摘要和 10 分钟评审路径；
- 本 PR 增加了什么的一览表；
- 当前状态和缺口说明；
- 与 AegisBank 参考手册的信任原则映射；
- 改造前后示例；
- `DraftPlanV1`、`draftHash`、`quoteHash`、`planHash` 设计；
- API 变更、代码归属和实现骨架；
- 安全不变量、验收标准和测试矩阵；
- 分阶段实现计划和评审问题。

## 验证

- 补丁基于上游 `main`（`71930d6`）生成；
- `git apply --check` 通过；
- 仅新增 `docs/DRAFT-PLAN-PROVENANCE.md`；
- 不包含合约、密钥、数据库、原始模型输出或本地临时文件。

## 建议的后续实现

1. 先确认本设计中的 hash 契约和 API 变更；
2. 增加 `backend/src/plan.ts` 和 `backend/test/plan.test.ts`，先做纯 hash 模块和 golden vectors；
3. 再接入 preview/submit/task/evidence；
4. 最后讨论是否需要在新的 policy domain 中做链上锚定。

## 需要评审决定的问题

1. 是否接受 `planHash` 这个 provenance 概念？
2. hash 字段是否合理，尤其是 parser reason 和 quote 观测区块？
3. submit 新增 `planHash` 是否立即强制，还是保留一个兼容期？
4. 第一阶段只做 off-chain provenance 是否足够？
5. 未来是否需要把 `planHash` 锚定到链上？
