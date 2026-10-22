# 上游设计参考说明

AegisBank 是独立产品仓库，不是上游 AegisAgent 的 PR 或附属项目。

上游 AegisAgent 的价值在于成熟的钱包、策略、证据和状态恢复设计。我们只借鉴以下工程理念：

- Agent 身份与审批身份分离；
- 所有工具调用经过统一权限/策略网关；
- LLM 只生成 draft/plan，不直接执行；
- Action Envelope 绑定 plan hash、参数、nonce 和过期时间；
- 幂等、执行前持久化和 UNKNOWN 状态恢复；
- 证据分层和 fail closed；
- 严格 Schema、注入整条拒绝和自动 fallback。

上游业务范围（Gas 储备、native ETH、Chainlink、Owner 钱包审批）不进入银行比赛产品主流程。

历史上游 PR 材料归档在独立 branch：

```text
archive/upstream-plan-provenance
```

产品 `main` 不包含 `upstream-pr/` 目录。
