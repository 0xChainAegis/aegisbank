# 上游 PR 交付包：AegisAgent

本目录包含提交到以下仓库的评审材料和补丁：

<https://github.com/0xChainAegis/aegis-agent>

## 已提交 PR

- 地址：<https://github.com/0xChainAegis/aegis-agent/pull/11>
- 标题：`docs(plan): 说明草案计划溯源绑定`
- 来源分支：`LQZ5885:docs/draft-plan-provenance`
- 目标分支：`0xChainAegis:main`
- 状态：Open，等待上游评审

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
git add docs/DRAFT-PLAN-PROVENANCE.md
git commit -m "docs(plan): 说明草案计划溯源绑定"
git push -u origin docs/draft-plan-provenance
```

然后在 GitHub 上创建 PR，并把 `PR_BODY.md` 的内容作为 PR 描述。

## 范围

仅新增设计文档。方案保持当前单动作 native ETH 范围，并明确区分链下 provenance 与链上 proof。
