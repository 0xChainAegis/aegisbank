# 上游设计参考说明

AegisBank 是独立产品仓库，不是上游 AegisAgent 的 PR 或附属项目。

团队协作仓库为 [0xChainAegis/aegisbank](https://github.com/0xChainAegis/aegisbank)，从 [LQZ5885/aegisbank](https://github.com/LQZ5885/aegisbank) 延续原提交历史。原 `LICENSE` 中的作者版权声明保持不变。

项目既有记录将 [0xChainAegis/aegis-agent](https://github.com/0xChainAegis/aegis-agent) 列为钱包、策略、证据和状态恢复设计的参考，记录的参考方向包括：

- Agent 身份与审批身份分离；
- 所有工具调用经过统一权限/策略网关；
- LLM 只生成 draft/plan，不直接执行；
- Action Envelope 绑定 plan hash、参数、nonce 和过期时间；
- 幂等、执行前持久化和 UNKNOWN 状态恢复；
- 证据分层和 fail closed；
- 严格 Schema、注入整条拒绝和自动 fallback。

上游业务范围（Gas 储备、native ETH、Chainlink、Owner 钱包审批）不进入银行比赛产品主流程。

历史上游 PR 材料保留在[原作者的归档分支](https://github.com/LQZ5885/aegisbank/tree/archive/upstream-plan-provenance)：

```text
archive/upstream-plan-provenance
```

产品 `main` 不包含 `upstream-pr/` 目录。

上述说明记录参考边界，不是逐文件代码来源鉴定，也不表示已核验所有第三方附件的许可。涉及实际复用的代码或素材时，应保留对应来源和许可声明；参考资料的已知和未知来源见 [reference/README.md](reference/README.md)。
