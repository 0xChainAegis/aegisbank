# aegisbank智能体

## 开发流程

```powershell
# 1. 跑门禁
..\.dsh-workflow\scripts\gate.ps1 -Repo .

# 2. 提交（自动写 Verified-By 尾注）
..\.dsh-workflow\scripts\checkpoint.ps1 -Repo . -Message "..."
```

门禁细节见工作流 docs/WORKFLOW.md。