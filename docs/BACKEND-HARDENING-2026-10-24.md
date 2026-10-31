# 后端安全补强记录（2026-10-24）

审查对象为当前工作区对应的 AegisBank 产品主线，起点 `9291a5c`；开发位置为 Linux ext4，Windows 历史副本保持冻结。本轮继续检查 2026-10-23 修复后的权限网关、执行器、确认/恢复、补偿、定时执行、Planner 与数据库访问路径，重点验证补偿授权和审计原子性。所有复现只使用隔离的 Mock Bank Core。

## 确认并修复的问题

| 编号 / 级别 | 复现与影响 | 修复 |
|---|---|---|
| H01 / P1 | 同一卡先解锁限额为 3000 元，再显式限制为 100 元；回滚第一次操作，修复前限额被旧快照覆盖为 5000 元。还款日和风险偏好也能被旧回滚覆盖；值改回相同值仍属于新的用户意图。 | 恢复还款日、信用额度、交易限额、风险偏好、订阅前，在执行器事务内核对原执行 journal、当前状态与后续未补偿的同资源写操作。冲突不写入，返回 UNKNOWN 并留下失败审计。 |
| H02 / P1 | 原交易限额 10000 元，黄色确认降低到 1000 元后回滚，修复前无需 MFA 即恢复 10000 元；信用额度恢复也仅采用黄色基线。 | 对 restore_card_limit / restore_transaction_limit 按原回执中的实际恢复目标重新评估风险；超过 5000 元升级红色，自动补偿拒绝执行。 |
| H03 / P1 | 故障注入让补偿预评估为黄、事务内复检为红，修复前只检查 denied，忽略 requires_reauth，仍执行退款。该反例证明复检策略缺口，不声称现有风险规则自然产生该交错。 | 事务内复检同时检查网关拒绝和 MFA 要求；成功/拒绝审计使用最终复检结果，策略拒绝记录 compensation_blocked。 |
| H04 / P1 | 在权限更新或撤权的审计追加处注入存储异常，修复前 API 报错但权限已经改变，可留下无审计的授权。 | PUT /api/permissions/{tool_name} 和 POST /api/authz/revoke/{tool_name} 的权限写入与审计追加处于同一数据库事务；审计失败回滚变更。 |

H01、H02 的业务流程反例和 H03、H04 的故障注入反例均在修复前运行，确认违反断言后再修复。新增回归位于 `backend/tests/test_security_regressions.py`；原撤权补偿测试同步区分策略拒绝和执行失败的审计事件。

## 行为与兼容性

- 不增加工具、接口或数据库列；沿用现有 action_journal_entries 的递增 ID 判断提交顺序，不依赖秒级时间戳。
- 同资源后续写操作即使写入相同值，也会阻止旧快照覆盖；后续操作已成功补偿时允许逆序恢复，不同卡片互不阻断。当前状态也必须与原执行回执一致。
- 恢复设置必须有可信执行日志；缺日志的旧动作失败关闭。新增能修改这些设置的工具时，必须同步对应恢复工具的 writers 集合和冲突回归。
- 恢复超过 5000 元额度会被拒绝并保持当前值；本轮没有新增补偿 MFA 接口。需核查后通过已有显式调额流程重新确认并完成 MFA，不能把 UNKNOWN 当成已回滚。
- 权限事务失败不会留下一条声称变更成功的审计，也不会留下未记录的权限变更；异常仍按存储故障返回，不伪装成功。
- 无前端实现、身份体系或金融模拟算法变更；没有接入真实银行。

## 验证

新增 13 项回归：后续设置覆盖及同值变更、交易限额与风险偏好冲突、信用额度冲突、两类恢复风险、红色恢复阻断、复检 MFA、授权/撤权审计故障，以及正常逆序回滚和不同资源隔离。当前后端统计与最终门禁记录见 README 和提交中的 Verified-By / Gate 信息。

```bash
cd ~/aegisbank
export AEGIS_DATABASE_PATH=/tmp/aegisbank-hardening-import.db
(cd backend && uv run pytest -q)
(cd backend && uv run python ../scripts/scenario-check.py)
bash scripts/smoke.sh
(cd backend && uv export --no-dev --no-hashes --format requirements-txt \
  --output-file /tmp/aegisbank-hardening-requirements.txt)
uvx pip-audit -r /tmp/aegisbank-hardening-requirements.txt
pwsh -NoProfile -File <workspace>/.dsh-workflow/scripts/gate.ps1 \
  -Repo ~/aegisbank
```

本轮完整后端 200 项通过（16 个测试文件，其中安全回归 56 项）；六场景检查 29/29 通过；真实 HTTP smoke 通过且审计链 valid=true；生产依赖 pip-audit 未发现已知漏洞。门禁包含 Ruff、TypeScript、Python/Vite 构建、后端/前端全量测试和静态安全扫描。依赖零命中只表示扫描时未报告公告，不证明不存在未知漏洞。

## 剩余边界

真实认证与主体绑定、真实 MFA、IM 平台验签、OS 级沙箱、按用户熔断、幂等/nonce 保留与崩溃恢复、外部审计锚点仍未完成。`X-Aegis-Role` 和固定演示验证码不能作为生产认证。此次不声称覆盖所有漏洞、完成渗透测试或通过生产安全验收。

设置冲突检查依赖正常工具执行产生的持久化 journal；直接篡改数据库或同时伪造日志不属于这一保护的攻击模型。日志损坏/缺失需人工核查，不能靠补造日志允许旧回滚。
