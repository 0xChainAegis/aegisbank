# U2：最小多轮闭环验收报告（联系人转账）

> 日期：2026-10-30
> 需求依据：[问题修复与升级计划 §5](next-steps/AegisBank-问题修复与升级计划.md#5-u2最小多轮闭环)
> 范围：只交付「联系人转账」的一条最小多轮主链路；U3、U5 不进入本轮。
> 结论：U2 最小闭环已实现并通过专项验收；U1 正式人工金标与真实模型对照仍未完成，不能据此宣称 NLP 泛化验收完成。

## 1. 实际支持范围

仅支持以下主链路：

```text
给妈妈转钱
  → 五百（补齐当前草稿缺失金额）
  → 不是500，改成300（只修改未执行草稿金额）
  → 旧确认失效
  → 重新确认
  → 我刚才转了多少 / 我刚才转给谁
```

历史查询回答的是**当前用户最近一次已完成的 Mock Bank Core 转账流水**，不是模型生成的摘要，也不是全局审计查询。

明确不支持：

- 任意旧轮次指代、通用「那个/刚才」解析、跨轮订阅目标选择；
- 长期记忆摘要、已执行历史编辑、个性化推荐；
- 多意图 DAG、条件表达式、任意组合规划；
- 真实银行、真实资金、生产 MFA、OS 级沙箱或真实 IM 接入。
## 2. 会话与草稿

### 2.1 数据模型

新增 SQLite 表 `agent_drafts`，源码位于 `agent/backend/aegisbank_api/trust/drafts.py`：

| 字段 | 说明 |
|---|---|
| `session_id` | 客户端可复用；未提供时服务端生成 `sess_*` |
| `draft_id` | 服务端生成 `drf_*`，客户端不得自行构造语义 |
| `user_id` | 草稿所有者；所有读取、补充、修订、确认按当前用户过滤 |
| `version` | 乐观并发版本；每次状态变更递增 |
| `semantic_json` | 最近一次已验证/澄清的 SemanticAnalysis |
| `plan_json` / `plan_hash` | 最近一次编译计划与哈希；旧确认不会复用旧哈希 |
| `status` | `awaiting_amount / awaiting_confirmation / processing / completed / rejected / blocked / failed / unknown / expired / superseded` |
| `pending_action_id` | 当前有效确认动作 ID |
| `missing_slots_json` | 草稿声明的缺失槽位，U2 只允许 `amount` |
| `context_json` | 服务端从当前用户联系人事实解析出的收款人和当前金额 |
| `run_ids_json` | 原始轮次关联的现有 `run_id` / 确认动作 ID，最多保留最近 10 个 |
| `expires_at` | 固定 TTL，默认 900 秒 |

约束：

- 同一 `user_id + session_id` 同时最多一个活动草稿（SQLite 部分唯一索引）；
- TTL 默认 900 秒，配置项 `AEGIS_CONVERSATION_DRAFT_TTL_SECONDS`；
- 读取时发现过期立即失效；新建草稿时清理过期行；
- 每个用户最多保留 20 个终态草稿，超出后按更新时间清理最旧记录；
- 补充文本最大 2,000 字（沿用 `/api/agent/run` 的请求上限）；`session_id / draft_id` 最大 64 字。
### 2.2 补槽与修订边界

- 补槽只接受**一个金额**，例如 `五百`、`500元`；金额经过既有确定性金额解析器和原文整串校验。
- 含新增收款人、第二个金额、额外动作或条件的回复一律拒绝，返回稳定原因码 `unsupported_amendment`。
- 金额修订只接受「不是500，改成300」或「改成300」这类仅含金额的变更；若用户陈述的原金额与草稿当前金额不一致，不修改任何状态。
- 修订后重新走 Planner / Plan Compiler / 动态风险 / 权限网关，生成新的 `plan_hash` 和新的确认动作；旧授权、旧 MFA、旧 nonce、旧确认均不复用。
- 旧确认被替代时，服务端将其状态置为 `superseded`，不写入可重放的 `result_json`；再次确认返回 `409 draft_version_conflict`，不执行任何工具。

## 3. API 契约

### 3.1 `POST /api/agent/run`

新增可选请求字段：

```json
{
  "instruction": "五百",
  "user_id": "demo-user",
  "session_id": "sess_xxx",
  "draft_id": "drf_xxx",
  "draft_version": 1
}
```

兼容字段：`instruction / user_id / tool_name / arguments / clarification_run_id`。`draft_id` 与 `draft_version` 必须成对出现。

响应在原有 `status / run_id / plan / confirmation / results / evidence` 基础上增加：

```json
{
  "session_id": "sess_xxx",
  "reason_code": "missing_amount",
  "draft": {
    "draft_id": "drf_xxx",
    "session_id": "sess_xxx",
    "version": 1,
    "status": "awaiting_amount",
    "reason_code": "missing_amount",
    "missing_slots": ["amount"],
    "plan_hash": "",
    "pending_action_id": null,
    "expires_at": "2026-10-30T02:45:00+00:00",
    "last_run_id": "run_xxx"
  }
}
```
### 3.2 `POST /api/confirmations/{action_id}`

新增可选字段：`user_id / session_id / draft_id / draft_version`。前端核对当前草稿后应原样回传；服务端校验：

- `draft_version` 必须等于当前草稿版本；
- 草稿的 `pending_action_id` 必须等于 URL 中的 `action_id`；
- 草稿用户与会话必须匹配；
- 旧确认或版本不一致返回 `409 draft_version_conflict`；
- 已结束/过期草稿返回 `409 context_expired`。

### 3.3 稳定原因码

| 原因码 | 场景 | HTTP |
|---|---|---|
| `missing_amount` | 首轮联系人转账缺金额；或补充金额无法识别/超出范围 | 200（首轮澄清） / 422（金额无效） |
| `context_expired` | 草稿不存在、不属于当前用户、会话不匹配、已过期或已结束 | 409 |
| `unsupported_amendment` | 补充/修订包含金额以外的收款人、动作、条件或多金额 | 409 |
| `draft_version_conflict` | 草稿版本过旧、并发更新、旧确认执行新草稿、确认 ID 与草稿不匹配 | 409 |

前端不应把上述任一错误显示为成功或 `completed`。

### 3.4 最近转账查询

新增只读工具 `query_recent_transfer`：

- 权限 `transfer:read`，风险 `green`，`read_only=true`，输入为空；
- 只按 `context.user_id` 查询 `bank_transactions` 中 `category='transfer' AND amount_cents < 0 AND status='posted'` 的最近一条；
- 返回 `found / transaction_id / amount_cny（正数）/ executed_at / contact_name / contact_phone（脱敏）/ to_account_masked / source / simulated=true`；
- 无记录时 `found=false`，前端明确显示「无记录」，不补造金额或联系人；
- 查询不创建草稿、不创建待确认动作、不执行任何写工具。

可直接用于前端联调的 Mock 样例见 [`docs/fixtures/u2-conversation.json`](fixtures/u2-conversation.json)。
## 4. 安全不变量

1. **用户隔离**：草稿、确认、历史查询均按 `user_id` 过滤；使用他人 session/draft 返回 `context_expired`，不泄露对象是否存在。
2. **不继承旧授权**：补槽/修订生成新确认；旧确认、旧 MFA、旧 nonce 不复用。
3. **版本并发控制**：草稿变更使用 `WHERE version = ?` 条件更新；重复回复使用 `Idempotency-Key` 返回首次结果。
4. **不新增写旁路**：补槽和修订只生成新的 Planner 请求，仍经过 Plan Compiler、动态风险、权限网关、ActionEnvelope、ToolExecutor、SandboxGuard 和审计。
5. **历史不可编造**：最近转账来自当前用户的 Mock Bank Core 实际流水；无记录时返回空结果。
6. **已完成不可编辑**：草稿确认成功后状态为 `completed`，后续修订返回 409，不产生第二笔转账。
7. **失败安全**：补充/修订失败时不返回可执行计划，不产生待确认动作或扣款；旧确认如已被替代则保持不可执行。

## 5. 验收证据

### 5.1 专项测试

`backend/backend/tests/test_u2_lead_integration.py` 共 6 条集成测试，覆盖：

1. 完整主链路：缺金额 → 补 500 → 修订 300 → 旧确认 409 → 新确认完成 → Mock 流水仅一笔 -300 元 → 历史回读金额/联系人/交易号来自真实 Mock 记录；
2. 非法补充与非法修订、旧版本、零待确认动作、零银行写入；
3. 跨用户草稿、过期草稿、零待确认动作；
4. 补槽与修订幂等键重复、只有一个 pending、确认重复不产生第二笔扣款；
5. 历史查询按用户隔离：另一用户无记录；
6. 确认接口拒绝旧 draft_version 且不产生银行流水。

既有 U1/NLP、信任层、六场景回归全部保持通过。
### 5.2 本轮实测输出

```text
后端 pytest            646 passed（35 个测试文件）
前端 Vitest            144 passed（12 个测试文件）
根组装器 unittest       18 passed
六场景场景检查          30/30 passed
工具目录                51 个
HTTP 路径               49 个
```

运行命令：

```bash
python3 scripts/assemble.py
cd .runtime/backend && uv run pytest -q
cd .runtime/frontend && pnpm test -- --run
cd .runtime/backend && uv run python ../scripts/scenario-check.py
```

### 5.3 前端支持

- 首轮 `needs_clarification` 显示草稿版本、缺失金额和有效期；
- 「补充上一条任务信息」携带 `session_id / draft_id / draft_version`，不再拼接旧文本；
- 确认弹窗对 `awaiting_confirmation` 草稿提供「修改金额」，只生成「不是X，改成Y」的新 Agent run，不直接确认旧动作；
- 确认请求回传草稿三元组；`409 draft_version_conflict` 映射为「需重新确认/重新发起」，不伪装成功；
- `query_recent_transfer` 回执展示联系人、金额、执行时间、交易号和模拟来源；无记录时明确显示无记录。

前端测试为契约级 Mock 联调；本轮未在浏览器中连接真实运行后端做人工点击联调，U4 交付回归时应补一次真实前后端联调。

## 6. 已知限制

- 只支持联系人转账的金额补槽与金额修订；其他字段、动作、条件必须重新发起；
- 只保留一个活动草稿；新任务会使用同一会话时旧草稿/旧确认失效；
- 草稿仅保存在本机 SQLite，不跨设备同步；不实现通用会话平台或时间线；
- 历史查询只覆盖最近一条已完成转账，不支持分页、全局审计或任意条件筛选；
- `user_id` 仍是本地演示身份，不是生产认证；
- 金额应答为整串解析，暂不支持「大约五百」「五百左右」等模糊金额；
- 真实 MFA、真实银行、OS 级沙箱、分布式幂等等生产化事项不在本轮完成范围。