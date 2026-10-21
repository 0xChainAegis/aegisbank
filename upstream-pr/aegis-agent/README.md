# 上游 PR 交付包：AegisAgent

本目录包含提交到以下仓库的评审材料和补丁：

<https://github.com/0xChainAegis/aegis-agent>

## 已提交 PR

- 地址：<https://github.com/0xChainAegis/aegis-agent/pull/11>
- 标题：`feat(plan): 实现草案计划溯源绑定`
- 来源分支：`LQZ5885:docs/draft-plan-provenance`
- 目标分支：`0xChainAegis:main`
- 状态：Open，已 rebase 到最新 upstream/main，等待上游维护者批准 workflow 和评审

## 上游 PR 实际变更

```text
docs/DRAFT-PLAN-PROVENANCE.md
backend/src/plan.ts
backend/test/plan.test.ts
backend/src/chain.ts
backend/src/server.ts
backend/src/service.ts
backend/test/api.test.ts
frontend/src/main.ts
e2e/wallet.topup.spec.ts
packages/shared/src/index.ts
```

## 文件说明

| 文件 | 用途 |
|---|---|
| `docs/DRAFT-PLAN-PROVENANCE.md` | 准备提交到上游仓库的中文设计说明 |
| `DRAFT-PLAN-PROVENANCE.patch` | 可直接用 `git apply` 应用的补丁 |
| `PR_BODY.md` | PR 描述草稿 |

## 本地应用方式

```bash
git clone https://github.com/0xChainAegis/aegis-agent.git
cd aegis-agent
git checkout -b docs/draft-plan-provenance
git apply /path/to/DRAFT-PLAN-PROVENANCE.patch
git add -A
git commit -m "feat(plan): 实现草案计划溯源绑定"
git push -u origin docs/draft-plan-provenance
```

然后在 GitHub 上创建 PR，并把 `PR_BODY.md` 的内容作为 PR 描述。

## 范围

本次 PR 包含中文设计说明、纯 hash 模块、API 绑定、task/evidence provenance 和测试。保持不变的是当前单动作 native ETH 范围、PolicyEngine、签名和审批语义；方案明确区分链下 provenance 与链上 proof。
