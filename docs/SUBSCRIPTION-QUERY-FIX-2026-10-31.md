# 场景五订阅查询修复（2026-10-31）

人工反馈：在银行助手输入页面示例「查看我的订阅」，任务显示「需要补充信息」。使用全新 SQLite 和默认离线规则模式可复现，返回 `needs_clarification`，原因是「尚不能完整验证这条指令」。

## 原因与修复

`RuleBasedPlanner` 已能生成 `list_subscriptions` 候选计划，但 `SemanticPlanner` 还会调用 `semantic_legacy.allow_legacy` 验证完整原文。原白名单仅接受「我的订阅有哪些」「查询订阅列表」「看看订阅」等表达，遗漏页面场景五实际提供的「查看我的订阅」。因此查询没有缺失业务参数，却被完整句校验拒绝。

修复订阅查询的有限语法：接受查/查询/查看/看看/看下/列出，可带「一下」「我的」及「列表/清单」。仍使用整句匹配；未知尾任务、未支持的时间筛选及其他用户对象继续要求澄清。前端示例保持原文，金融数据仍由当前用户的 Mock Bank Core 返回，经权限网关、执行守卫和审计链执行。

预期结果：输入「查看我的订阅」直接完成绿色只读查询，返回订阅列表，无需补充信息或确认；取消订阅仍走原有确认流程。

## 回归与复现

- 修复前，新增查询回归中的六种表达失败，原先三种表达通过，定位到完整句白名单缺口。
- API 回归验证九种查询表达、实际模拟库数据一致性、查询前后业务状态不变、审计链有效，以及未知尾句不被忽略。
- 六场景脚本加入页面原文「查看我的订阅」，防止只验证另一种说法而遗漏展示入口。
- 完整门禁结果以本次提交的 `Gate` / `Stages` 尾注为准。

```bash
python3 scripts/assemble.py
.runtime/backend/.venv/bin/pytest -o addopts= -q \
  .runtime/backend/tests/test_subscription_cancel.py \
  .runtime/backend/tests/test_semantic_legacy.py \
  .runtime/backend/tests/test_semantics.py
bash scripts/check.sh scenarios
```

已启动的一键演示进程不会自动重载后端。先在原启动终端按 Ctrl+C，再于同一 Linux 检出运行 `bash start.sh`；原模拟数据会保留，重新提交查询即可。
