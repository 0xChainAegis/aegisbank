# AegisBank API 交接文档

> 状态：**Stage 1 基线版**。本文档先锁定版本、组装、启动与后端地址；关键接口的完整请求/返回示例在 Stage 2 补齐。
>
> 适用版本：`0xChainAegis/aegisbank` `main` @ `bad8e64`。
> 验证日期：2026-10-26。
> 后端运行环境：Linux / WSL Ubuntu 24.04。

## 1. 版本与源码位置

仓库保留六个职责包作为唯一业务源码入口：

```text
NLP/      金额解析、Planner、语义安全、受限澄清
agent/    网关、调度、执行器、风险、审计、信任层
backend/  FastAPI 入口、数据库、Mock Bank Core、后端测试与脚本
fronted/  React / TypeScript 前端，源码位于 fronted/frontend/
plans/    计划契约与编译器
skills/   工具 SDK、工具注册与银行场景
```

`docs/`、`deliverables/`、根 `scripts/` 和根 `tests/` 是团队阅读、交付与组装入口，不是第二份业务实现。

不要直接修改 `.runtime/`。它是 `scripts/assemble.py` 生成的运行目录，已被 `.gitignore` 忽略。

## 2. 组装

在仓库根目录执行：

```bash
python3 scripts/assemble.py
```

预期输出：

```text
Assembled 140 files into <repo>/.runtime
```

组装规则：

- 只从六个职责包读取白名单源文件；
- `_PACKAGE`、缓存、依赖目录、构建产物、运行数据库不作为输入；
- `backend/.env.example` 是唯一显式隐藏文件特例；
- 生成目录只管理自己清单中的文件，不清理本地数据库、虚拟环境或依赖；
- 重复组装是幂等的；源码变化后重新组装即可。

组装器自身测试：

```bash
python3 -m unittest discover -s tests -q
```

当前基线：**18 项通过**。

## 3. 启动

### 3.1 一键方式（推荐）

根目录脚本会先自动组装，再执行 `.runtime/` 内的对应脚本：

```bash
bash scripts/bootstrap.sh
bash scripts/dev.sh
```

### 3.2 手工方式

```bash
python3 scripts/assemble.py
cd .runtime
bash scripts/bootstrap.sh
bash scripts/dev.sh
```

### 3.3 只启动后端

```bash
cd .runtime/backend
uv sync --frozen
uv run uvicorn aegisbank_api.main:app --host 127.0.0.1 --port 8000
```

### 3.4 只启动前端

```bash
cd .runtime/frontend
pnpm install --frozen-lockfile
pnpm dev
```

前端 Vite 默认将 `/api` 代理到 `http://127.0.0.1:8000`。

### 3.5 环境变量

组装后的示例配置位于：

```text
.runtime/backend/.env.example
```

需要覆盖时复制为同目录 `.env`。默认 `AEGIS_PLANNER_MODE=rule`，无需模型密钥即可离线运行。演示 OTP 为 `246810`，仅用于本地流程展示。

后端必须运行在 Linux / WSL：数据库锁使用 `fcntl`，原生 Windows Python 不能直接运行。

## 4. 后端地址

| 项 | 地址 |
|---|---|
| API Base | `http://127.0.0.1:8000` |
| API 前缀 | `/api` |
| Swagger | `http://127.0.0.1:8000/docs` |
| 健康检查 | `http://127.0.0.1:8000/api/health` |
| 就绪检查 | `http://127.0.0.1:8000/api/health/ready` |
| 前端控制台 | `http://127.0.0.1:5173` |

如果前端运行在另一台机器或容器中，需要调整 Vite 代理或 `VITE_API_BASE_URL`，并把前端 origin 加入 `AEGIS_CORS_ORIGINS`。当前脚本默认只绑定本机 `127.0.0.1`。

## 5. Stage 1 已验证基线

以下结果来自 2026-10-26 在 `/home/lqz5885/work/aegisbank-day1` 的实际运行：

### 5.1 组装

```text
Assembled 140 files into /home/lqz5885/work/aegisbank-day1/.runtime (140 written, 0 removed).
```

### 5.2 组装器测试

```text
Ran 18 tests in 0.378s
OK
```

### 5.3 健康检查

```http
GET /api/health
200 OK
```

```json
{
  "status": "ok",
  "service": "AegisBank Trusted Agent",
  "version": "0.1.0",
  "mode": "local-mvp",
  "planner": {
    "mode": "rule",
    "contract": "ExecutionPlan/v1"
  }
}
```

### 5.4 就绪检查

```http
GET /api/health/ready
200 OK
```

```json
{
  "status": "ready",
  "components": {
    "sqlite": {"ok": true, "detail": "SQLite 可读写"},
    "audit_chain": {"ok": true, "detail": "哈希链校验通过，共 0 条"},
    "mock_bank_seed": {"ok": true, "detail": "模拟银行种子就绪：2 个账户 / 2 张卡"},
    "planner": {"ok": true, "detail": "Planner 可用：rule"}
  }
}
```

### 5.5 银行概览

```http
GET /api/banking/overview
200 OK
```

关键种子数据：

- 账户：`ACC-1001`（工资卡）、`ACC-2002`（日常储蓄）；
- 卡片：`CARD-8821`、`CARD-9902`；
- 异常订阅：`SUB-3002`；
- 返回字段包括 `accounts`、`cards`、`subscriptions`、`monthly_spend_cny`、`daily_transfer_total_cny`、`suspicious_subscription_id`。

## 6. 通用接口约定

- `Content-Type: application/json`
- `X-Aegis-Role: user | operator | auditor`，仅用于本地演示，不是生产认证。
- `Idempotency-Key: <uuid>`，用于 `POST /api/agent/run` 和 `POST /api/confirmations/{action_id}`。
- 业务状态与 HTTP 状态分离：
  - 200：请求已处理，业务状态可能是 `completed` / `awaiting_confirmation` / `blocked` / `needs_clarification`；
  - 400：参数或意图错误；
  - 403：角色能力不足或 MFA 校验失败；
  - 409：幂等冲突、确认 Envelope 失效或澄清上下文不可用；
  - 413：请求体过大；
  - 422：执行失败或 Pydantic 校验失败；
  - 503：服务未就绪，写操作 fail closed。

## 7. 关键接口示例

以下示例基于当前 `bad8e64` 组装后的 `.runtime`，在 fresh DB 上按顺序执行。示例中的 `run_id`、`confirmation_id`、`plan_hash`、`nonce`、`expires_at`、`transaction_id`、`audit_id`、`checked` 等动态字段使用占位符；实际值以响应为准。

通用请求头：

```http
Content-Type: application/json
X-Aegis-Role: user
Idempotency-Key: <uuid>
```

- `X-Aegis-Role` 仅用于本地演示，不是生产认证。
- `Idempotency-Key` 建议用于 `POST /api/agent/run` 与 `POST /api/confirmations/{action_id}`；同一逻辑请求重试时复用同一个 key。
- 审计接口建议使用最小权限角色 `X-Aegis-Role: auditor`。

| 接口 | 用途 | 典型业务状态 |
|---|---|---|
| `GET /api/health` | 存活检查 | HTTP 200 |
| `GET /api/health/ready` | 就绪检查 | `ready` / 503 |
| `GET /api/banking/overview` | 账户、卡片、订阅概览 | HTTP 200 |
| `POST /api/planner/plan` | 只生成计划，不执行 | `planned` / `needs_clarification` |
| `POST /api/agent/run` | 执行或进入确认 | `completed` / `awaiting_confirmation` / `blocked` / `needs_clarification` |
| `POST /api/confirmations/{action_id}` | 确认黄色/红色操作 | `completed` / `blocked`；错误 OTP 403 |
| `GET /api/audit` | 审计列表 | HTTP 200 |
| `GET /api/audit/verify` | SHA-256 哈希链校验 | `valid=true/false` |
### 7.1 `GET /api/health`

```bash
curl -s http://127.0.0.1:8000/api/health
```

```json
{
  "status": "ok",
  "service": "AegisBank Trusted Agent",
  "version": "0.1.0",
  "mode": "local-mvp",
  "planner": {
    "mode": "rule",
    "contract": "ExecutionPlan/v1"
  }
}
```

### 7.2 `GET /api/health/ready`

```bash
curl -s http://127.0.0.1:8000/api/health/ready
```

```json
{
  "status": "ready",
  "components": {
    "sqlite": {"ok": true, "detail": "SQLite 可读写"},
    "audit_chain": {"ok": true, "detail": "哈希链校验通过，共 0 条"},
    "mock_bank_seed": {"ok": true, "detail": "模拟银行种子就绪：2 个账户 / 2 张卡"},
    "planner": {"ok": true, "detail": "Planner 可用：rule"}
  }
}
```

服务未就绪时，写操作会 fail closed 返回 503，不会伪装成功。

### 7.3 `GET /api/banking/overview`

```bash
curl -s http://127.0.0.1:8000/api/banking/overview
```

响应节选（省略部分账户、卡片和订阅）：

```json
{
  "accounts": [
    {
      "account_id": "ACC-1001",
      "name": "工资卡",
      "kind": "checking",
      "currency": "CNY",
      "balance_cny": 28650.0,
      "available_cny": 28650.0
    },
    {
      "account_id": "ACC-2002",
      "name": "日常储蓄",
      "kind": "savings",
      "currency": "CNY",
      "balance_cny": 12000.0,
      "available_cny": 12000.0
    }
  ],
  "cards": [
    {
      "card_id": "CARD-8821",
      "account_id": "ACC-1001",
      "masked_number": "**** 8821",
      "status": "active",
      "credit_limit_cny": 30000.0,
      "available_limit_cny": 21750.0,
      "repayment_day": 8,
      "transaction_limit_cny": 10000.0
    }
  ],
  "subscriptions": [
    {
      "subscription_id": "SUB-3002",
      "merchant": "AI 工具订阅",
      "amount_cny": 199.0,
      "cycle": "monthly",
      "next_charge_date": "2026-11-01",
      "status": "active",
      "risk_flag": "本月扣费较上月上涨 120%"
    }
  ],
  "monthly_spend_cny": 5497.4,
  "daily_transfer_total_cny": 0.0,
  "suspicious_subscription_id": "SUB-3002",
  "suspicious_reason": "本月扣费较上月上涨 120%"
}
```

### 7.4 `POST /api/planner/plan`

只生成计划，不执行工具。

```bash
curl -s -X POST http://127.0.0.1:8000/api/planner/plan \
  -H 'Content-Type: application/json' \
  -H 'X-Aegis-Role: user' \
  -d '{"instruction":"向 ACC-2002 转账 880 元"}'
```

```json
{
  "status": "planned",
  "plan": {
    "intent": "transfer",
    "planner": "rule",
    "confidence": 0.93,
    "assumptions": [
      "未指定转出账户，默认使用演示账户 ACC-1001。",
      "金额来源：原文[14:17]「880」 = 880.00 CNY。"
    ],
    "plan_hash": "<plan_hash_64_hex>",
    "dag_path": "step-1:transfer",
    "steps": [
      {
        "id": "step-1",
        "tool_name": "transfer",
        "arguments": {
          "from_account": "ACC-1001",
          "to_account": "ACC-2002",
          "amount_cny": 880.0,
          "note": "向 ACC-2002 转账 880 元"
        },
        "depends_on": [],
        "title": "智能转账",
        "risk_level": "yellow",
        "permission": "transfer:execute",
        "description": "按金额和日累计动态评估风险后发起转账。",
        "risk_reasons": [
          "小额转账 880.00 元，今日累计 880.00 元，未超过 1000 元。",
          "需要黄色操作确认。"
        ],
        "requires_reauth": false,
        "risk_score": 40
      }
    ]
  },
  "risk_level": "yellow",
  "risk": {
    "level": "yellow",
    "reasons": [
      "小额转账 880.00 元，今日累计 880.00 元，未超过 1000 元。",
      "需要黄色操作确认。"
    ],
    "requires_reauth": false
  },
  "reason": "计划已通过 Schema、工具注册、DAG 依赖和动态风险校验。",
  "evidence": [
    {
      "source": "policy_engine",
      "verified": true,
      "verification_kind": "policy_decision",
      "detail": "预览计划通过策略校验"
    }
  ]
}
```

### 7.5 条件/组合请求转澄清

当前不支持的条件或自由组合不会降级为部分执行。示例：

```bash
curl -s -X POST http://127.0.0.1:8000/api/planner/plan \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"如果余额超过1000元，就给妈妈转500元"}'
```

```json
{
  "status": "needs_clarification",
  "plan": {
    "intent": "unsupported_condition",
    "steps": [],
    "confidence": 0.0,
    "assumptions": [],
    "needs_clarification": true,
    "clarification": "当前无法完整执行条件任务，不会忽略条件生成操作；请先查询条件，确认满足后再单独发起操作。",
    "planner": "safety"
  },
  "reason": "当前无法完整执行条件任务，不会忽略条件生成操作；请先查询条件，确认满足后再单独发起操作。",
  "evidence": [
    {
      "source": "policy_engine",
      "verified": true,
      "verification_kind": "policy_decision",
      "detail": "Planner 请求澄清"
    }
  ]
}
```

### 7.6 `POST /api/agent/run` — 绿色直接完成

只读查询可以直接执行。

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -H 'X-Aegis-Role: user' \
  -H 'Idempotency-Key: demo-green-1' \
  -d '{
    "instruction":"查询我的本月账单",
    "tool_name":"query_bill",
    "arguments":{"account_id":"ACC-1001"}
  }'
```

```json
{
  "status": "completed",
  "run_id": "<run_id>",
  "risk_level": "green",
  "risk": {
    "level": "green",
    "reasons": ["只读查询操作，满足最小权限后自动执行。"],
    "requires_reauth": false
  },
  "reason": "全部节点通过权限网关。",
  "plan": {
    "intent": "query_bill",
    "planner": "rule",
    "confidence": 1.0,
    "assumptions": ["用户显式指定了工具节点，参数由请求提供。"],
    "plan_hash": "<plan_hash_64_hex>",
    "dag_path": "step-1:query_bill",
    "steps": [
      {
        "id": "step-1",
        "tool_name": "query_bill",
        "arguments": {"account_id": "ACC-1001", "period": "current_month"},
        "depends_on": [],
        "title": "分析账单",
        "risk_level": "green",
        "permission": "billing:read",
        "requires_reauth": false,
        "risk_score": 10
      }
    ]
  },
  "results": [
    {
      "tool_name": "query_bill",
      "message": "已完成账单分析（演示银行数据）。",
      "data": {
        "account_id": "ACC-1001",
        "period": "current_month",
        "month": "2026-10",
        "total_spend_cny": 6377.4,
        "categories": {
          "food": 1865.0,
          "transport": 108.0,
          "transfer": 880.0,
          "shopping": 2752.4,
          "subscription": 772.0
        },
        "suspicious_subscription_id": "SUB-3002",
        "suspicious_subscription_name": "AI 工具订阅"
      }
    }
  ]
}
```

`results[0].data.transactions` 等长数组在实际响应中会返回，示例中省略。

### 7.7 `POST /api/agent/run` — 黄色待确认，再确认执行

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -H 'X-Aegis-Role: user' \
  -H 'Idempotency-Key: demo-yellow-1' \
  -d '{"instruction":"向 ACC-2002 转账 880 元"}'
```

```json
{
  "status": "awaiting_confirmation",
  "run_id": "<confirmation_id>",
  "risk_level": "yellow",
  "risk": {
    "level": "yellow",
    "reasons": [
      "小额转账 880.00 元，今日累计 880.00 元，未超过 1000 元。",
      "需要黄色操作确认。"
    ],
    "requires_reauth": false
  },
  "reason": "黄色操作会修改账户设置，需要在 5 分钟内完成一次轻量确认。",
  "plan": {
    "intent": "transfer",
    "planner": "rule",
    "confidence": 0.93,
    "assumptions": [
      "未指定转出账户，默认使用演示账户 ACC-1001。",
      "金额来源：原文[14:17]「880」 = 880.00 CNY。"
    ],
    "plan_hash": "<plan_hash_64_hex>",
    "dag_path": "step-1:transfer",
    "steps": [
      {
        "id": "step-1",
        "tool_name": "transfer",
        "arguments": {
          "from_account": "ACC-1001",
          "to_account": "ACC-2002",
          "amount_cny": 880.0
        },
        "depends_on": [],
        "risk_level": "yellow",
        "permission": "transfer:execute",
        "requires_reauth": false,
        "risk_score": 40
      }
    ]
  },
  "audit_id": "<audit_id>",
  "confirmation": {
    "id": "<confirmation_id>",
    "requires_reauth": false,
    "expires_at": "<expires_at>",
    "state": "AWAITING_CONFIRMATION",
    "envelopes": [
      {
        "schema_version": "action-envelope/v1",
        "user_id": "demo-user",
        "plan_hash": "<plan_hash_64_hex>",
        "step_id": "step-1",
        "tool_name": "transfer",
        "arguments_hash": "<arguments_hash_64_hex>",
        "risk_level": "yellow",
        "permission": "transfer:execute",
        "nonce": "<nonce>",
        "issued_at": "<issued_at>",
        "expires_at": "<expires_at>",
        "confirmation_state": "pending",
        "approval_token": null,
        "approval_token_present": false
      }
    ]
  }
}
```

用上一步返回的 `confirmation.id` 确认：

```bash
curl -s -X POST http://127.0.0.1:8000/api/confirmations/<confirmation_id> \
  -H 'Content-Type: application/json' \
  -H 'X-Aegis-Role: user' \
  -H 'Idempotency-Key: demo-yellow-confirm-1' \
  -d '{"approved":true}'
```

```json
{
  "status": "completed",
  "run_id": "<confirmation_id>",
  "risk_level": "yellow",
  "reason": "确认通过，任务已执行。",
  "plan": {
    "intent": "transfer",
    "plan_hash": "<plan_hash_64_hex>",
    "authorization": {
      "risk_level": "yellow",
      "mfa_verified": false,
      "user_id": "demo-user",
      "expires_at": "<expires_at>"
    }
  },
  "results": [
    {
      "tool_name": "transfer",
      "message": "转账指令已通过风险校验并完成模拟执行。",
      "data": {
        "transaction_id": "<transaction_id>",
        "from_account": "ACC-1001",
        "to_account": "ACC-2002",
        "amount_cny": 880.0,
        "daily_transfer_total_cny": 880.0,
        "status": "simulated_success",
        "executed_at": "<executed_at>",
        "simulated": true
      }
    }
  ],
  "audit_id": "<audit_id>"
}
```

### 7.8 `POST /api/agent/run` — 红色 + 演示 MFA

在 7.7 的 880 元之后继续转账 1200 元，日累计达到 2080 元，升级为红色：

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -H 'X-Aegis-Role: user' \
  -H 'Idempotency-Key: demo-red-1' \
  -d '{"instruction":"向 ACC-2002 转账 1200 元"}'
```

```json
{
  "status": "awaiting_confirmation",
  "run_id": "<red_confirmation_id>",
  "risk_level": "red",
  "risk": {
    "level": "red",
    "reasons": [
      "今日累计转账将达到 2080.00 元，超过 1000 元上限。",
      "需要红色强验证和明确确认。",
      "整条计划累计转账将超过 1000 元，需要强验证。"
    ],
    "requires_reauth": true
  },
  "reason": "红色操作涉及资金变动，需要二次身份校验并明确确认。",
  "plan": {
    "intent": "transfer",
    "plan_hash": "<red_plan_hash_64_hex>",
    "steps": [
      {
        "id": "step-1",
        "tool_name": "transfer",
        "arguments": {
          "from_account": "ACC-1001",
          "to_account": "ACC-2002",
          "amount_cny": 1200.0
        },
        "risk_level": "red",
        "permission": "transfer:execute",
        "requires_reauth": true,
        "risk_score": 80
      }
    ]
  },
  "audit_id": "<audit_id>",
  "confirmation": {
    "id": "<red_confirmation_id>",
    "requires_reauth": true,
    "expires_at": "<expires_at>",
    "state": "AWAITING_REAUTH",
    "envelopes": [
      {
        "schema_version": "action-envelope/v1",
        "user_id": "demo-user",
        "plan_hash": "<red_plan_hash_64_hex>",
        "step_id": "step-1",
        "tool_name": "transfer",
        "arguments_hash": "<arguments_hash_64_hex>",
        "risk_level": "red",
        "permission": "transfer:execute",
        "nonce": "<nonce>",
        "issued_at": "<issued_at>",
        "expires_at": "<expires_at>",
        "confirmation_state": "pending",
        "approval_token": null,
        "approval_token_present": false
      }
    ]
  }
}
```

错误 OTP 返回 403：

```bash
curl -s -o /tmp/otp-error.json -w '%{http_code}\n' \
  -X POST http://127.0.0.1:8000/api/confirmations/<red_confirmation_id> \
  -H 'Content-Type: application/json' \
  -H 'X-Aegis-Role: user' \
  -d '{"approved":true,"reauth_token":"000000"}'
```

```json
{
  "detail": "二次身份校验失败：OTP 校验失败，请检查演示验证码。"
}
```

正确 OTP：

```bash
curl -s -X POST http://127.0.0.1:8000/api/confirmations/<red_confirmation_id> \
  -H 'Content-Type: application/json' \
  -H 'X-Aegis-Role: user' \
  -H 'Idempotency-Key: demo-red-confirm-1' \
  -d '{"approved":true,"reauth_token":"246810"}'
```

```json
{
  "status": "completed",
  "run_id": "<red_confirmation_id>",
  "risk_level": "red",
  "reason": "确认通过，任务已执行。",
  "plan": {
    "intent": "transfer",
    "plan_hash": "<red_plan_hash_64_hex>",
    "authorization": {
      "risk_level": "red",
      "mfa_verified": true,
      "user_id": "demo-user",
      "expires_at": "<expires_at>"
    }
  },
  "results": [
    {
      "tool_name": "transfer",
      "message": "转账指令已通过风险校验并完成模拟执行。",
      "data": {
        "transaction_id": "<red_transaction_id>",
        "from_account": "ACC-1001",
        "to_account": "ACC-2002",
        "amount_cny": 1200.0,
        "daily_transfer_total_cny": 2080.0,
        "status": "simulated_success",
        "executed_at": "<executed_at>",
        "simulated": true
      }
    }
  ],
  "audit_id": "<audit_id>"
}
```

### 7.9 `GET /api/audit` 与 `GET /api/audit/verify`

审计读取建议使用只读角色：

```bash
curl -s 'http://127.0.0.1:8000/api/audit?limit=3' \
  -H 'X-Aegis-Role: auditor'
```

```json
{
  "entries": [
    {
      "id": "<audit_id>",
      "created_at": "<timestamp>",
      "event": "state_transition",
      "user_id": "demo-user",
      "instruction": "向 ACC-2002 转账 1200 元",
      "dag_path": "step-1:transfer",
      "tool_name": "transfer",
      "confirmation_state": "COMPLETED",
      "risk_level": "red",
      "prev_hash": "<prev_hash_64_hex>",
      "entry_hash": "<entry_hash_64_hex>",
      "arguments": {
        "amount_cny": 1200.0,
        "from_account": "ACC-1001",
        "to_account": "ACC-2002"
      },
      "result": {
        "action_id": "<red_confirmation_id>",
        "from": "EXECUTING",
        "to": "COMPLETED",
        "reason": "全部节点执行完成"
      },
      "run_id": "<red_confirmation_id>",
      "step_id": null
    }
  ],
  "count": 1
}
```

哈希链校验：

```bash
curl -s http://127.0.0.1:8000/api/audit/verify \
  -H 'X-Aegis-Role: auditor'
```

```json
{
  "valid": true,
  "checked": 16
}
```

`checked` 随操作数量变化；示例中为上述完整流程后的条数。
## 8. 错误码与典型响应

### 8.1 状态码总表

| HTTP | 典型场景 | 说明 |
|---|---|---|
| 200 | 业务请求已处理 | 业务状态可能是 `completed` / `awaiting_confirmation` / `blocked` / `needs_clarification` |
| 400 | 确认请求不存在、意图错误 | 请求语义或目标不合法 |
| 403 | 直接能力端点缺少角色能力 | 例如普通用户重置熔断器 |
| 404 | 工具不存在 | 权限接口中的未知工具名 |
| 409 | 幂等键冲突、确认 Envelope 失效、澄清上下文不可用 | 需要更换请求或重新发起操作 |
| 413 | 请求体超过 128 KB | 中间件在解析前拒绝 |
| 422 | Pydantic 校验失败或执行失败 | 字段缺失/类型错误，或确认执行阶段失败 |
| 503 | 服务未就绪 | 写操作 fail closed，不会伪装成功 |

注意：`POST /api/agent/run` 遇到角色无 `tool:execute` 时，可能返回 **HTTP 200 + `status=blocked`**，而不是 403；这是业务状态层的拒绝。直接检查能力的端点（如熔断重置）才会返回 403。

### 8.2 400 — 确认请求不存在

```bash
curl -s -X POST http://127.0.0.1:8000/api/confirmations/does-not-exist \
  -H 'Content-Type: application/json' \
  -d '{"approved":true}'
```

```json
{
  "detail": "确认请求不存在。"
}
```

### 8.3 403 — 角色能力不足

`user` 角色不能重置熔断器：

```bash
curl -s -X POST http://127.0.0.1:8000/api/trust/circuit-breaker/reset \
  -H 'X-Aegis-Role: user'
```

```json
{
  "detail": "角色 user 不具备能力 ops:manage 的执行权限。"
}
```

### 8.4 409 — 幂等键复用但请求内容不同

```bash
# 第一次请求
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: same-key' \
  -d '{"instruction":"查询我的本月账单","tool_name":"query_bill","arguments":{"account_id":"ACC-1001"}}'

# 相同 key，不同 body
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: same-key' \
  -d '{"instruction":"查询我的本月账单","tool_name":"query_bill","arguments":{"account_id":"ACC-2002"}}'
```

```json
{
  "detail": {
    "code": "IDEMPOTENCY_KEY_REUSED",
    "message": "同一个 Idempotency-Key 携带了不同的请求内容，拒绝处理。"
  }
}
```

确认 Envelope 过期、plan/arguments 哈希不一致等也会返回 409；响应中的 `code` 用于区分具体原因。

### 8.5 413 — 请求体过大

```bash
python3 - <<'PY'
import json, urllib.request
body = json.dumps({"instruction": "x" * 130000}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/agent/run",
    data=body,
    headers={"Content-Type": "application/json", "X-Aegis-Role": "user"},
    method="POST",
)
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as exc:
    print(exc.code, exc.read().decode())
PY
```

```json
{
  "detail": "请求体超出上限。"
}
```

### 8.6 422 — 请求字段校验失败

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"instruction":""}'
```

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "instruction"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": {"min_length": 1}
    }
  ]
}
```

### 8.7 503 — 服务未就绪

就绪检查本身返回 200，但 `status=not_ready`：

```json
{
  "status": "not_ready",
  "components": {
    "sqlite": {"ok": false, "detail": "模拟 SQLite 未就绪"},
    "audit_chain": {"ok": true, "detail": "哈希链校验通过，共 0 条"},
    "mock_bank_seed": {"ok": true, "detail": "模拟银行种子就绪：2 个账户 / 2 张卡"},
    "planner": {"ok": true, "detail": "Planner 可用：rule"}
  }
}
```

此时写操作返回 503：

```json
{
  "detail": "系统未就绪，写操作已按 fail closed 拒绝（sqlite: 模拟 SQLite 未就绪）。"
}
```
## 9. 演示数据与排障

- 首次启动会自动建库并写入确定性 Mock Bank Core 种子，不需要手工迁移。
- `seed-demo.sh` 默认重置 `.runtime/backend/data/dogfood.db`，而 `dev.sh` 默认使用 `.runtime/backend/data/aegisbank.db`。需要 3000 元虚拟卡时，必须让后端指向同一个数据库。
- 推荐用绝对路径重置默认库：

```bash
# 先停止后端
pkill -f '[u]vicorn aegisbank_api.main:app' || true

# 重置并使用 dev.sh 默认的数据库
bash scripts/seed-demo.sh "$PWD/.runtime/backend/data/aegisbank.db"
bash scripts/dev.sh
```

- 也可以让 `dev.sh` 指向 `dogfood.db`：

```bash
bash scripts/seed-demo.sh
AEGIS_DATABASE_PATH="$PWD/.runtime/backend/data/dogfood.db" bash scripts/dev.sh
```

- 重置数据库前先停止后端，避免 SQLite 文件锁。
- 端口冲突时检查 8000 / 5173：

```bash
ss -ltnp | grep -E ':8000|:5173'
```

- 复现第 7 节示例时，建议按以下顺序执行，以保证风险分级与审计条数一致：
  1. `GET /api/health`、`GET /api/health/ready`、`GET /api/banking/overview`
  2. `POST /api/planner/plan`（880 元）
  3. `POST /api/agent/run`（880 元黄色）
  4. `POST /api/confirmations/{id}`（黄色确认）
  5. `POST /api/agent/run`（绿色账单查询）
  6. `POST /api/agent/run`（1200 元红色，日累计升级）
  7. 错误 OTP → 正确 OTP
  8. `GET /api/audit`、`GET /api/audit/verify`
## 10. 前端契约核对与已知边界

### 10.1 前端契约核对

已核对以下前端调用与后端路由/字段一致：

| 前端函数 | 后端接口 | 关键字段 |
|---|---|---|
| `fetchBankingOverview()` | `GET /api/banking/overview?user_id=demo-user` | `accounts`、`cards`、`subscriptions`、`monthly_spend_cny` |
| `previewPlan(input)` | `POST /api/planner/plan` | `plan`、`steps`、`risk` |
| `runAgent(input)` | `POST /api/agent/run` | `status`、`run_id`、`plan`、`confirmation`、`results` |
| `resolveConfirmation(id, approved, reauthToken, mfaProvider)` | `POST /api/confirmations/{id}` | `approved`、`reauth_token`、`mfa_provider` |
| `fetchReadiness()` | `GET /api/health/ready` | `status`、`components` |
| `fetchAudit(limit, runId)` | `GET /api/audit` | `entries`、`count` |
| `verifyAudit()` | `GET /api/audit/verify` | `valid`、`checked` |

前端 `RunResponse` 类型已覆盖 `completed`、`awaiting_confirmation`、`needs_clarification`、`blocked` 等业务状态。接口字段变更时，必须同步 `fronted/frontend/src/api.ts` 与 `types.ts`。
### 10.2 NLP 能力边界

- P0 已落地：完整金额词元规范化、Decimal 分位校验、金额原文与位置记录；已识别的条件、组合和参数冲突转澄清；rule / llm / auto / 显式工具入口共用安全检查。
- P1-P4 未实现：没有通用 SemanticFrame、会话记忆与纠错、任意条件与组合规划，也没有正式 NLP 保留集评测。
- 当前可表述为支持限定表达、部分口语、受限续问和预置跨场景 DAG 的可信银行智能体原型，不能表述为通用自然语言理解或任意复杂任务规划。
- 详见 [NLP 现状与 P0 修复](NLP-ASSESSMENT-AND-PLAN-2026-10-25.md) 与 [NLP 后续待办](NLP-BACKLOG.md)。
### 10.3 安全与演示边界

- 全部账户、卡片、账单、理财和交易均为 Mock Bank Core 模拟数据，不连接真实银行或支付网络。
- X-Aegis-Role 只是演示请求头，不是身份认证。
- 固定 OTP 246810 和模拟生物识别不是生产 MFA。
- 进程内工具沙箱不是 OS 级隔离；没有真实 IM 平台接入。
- SHA-256 哈希链用于检测日志改动，不等同于数字签名或独立存证。
- 测试通过只代表已知用例可复现，不代表生产安全认证。

### 10.4 验证数字口径

- 应用验证基线（2026-10-25）：后端 pytest 252 项、前端 Vitest 73 项、六场景回归 29/29、实际前端入口 15/15。
- 职责包组装器测试：18 项通过。
- 以上数字来自对应版本的历史记录；当前变更后应重新运行并引用实际输出，不能用旧数字代替新验证。

## 11. Stage 4 验证记录

验证日期：2026-10-26。验证对象：分支 `docs/day1-api-handoff`，文档提交 `4ae990a`，干净 clone 到 `/tmp/aegisbank-stage4-check`。

### 11.1 组装与组装器测试

```text
python3 scripts/assemble.py
Assembled 140 files into /tmp/aegisbank-stage4-check/.runtime (140 written, 0 removed).

python3 -m unittest discover -s tests -q
Ran 18 tests in 0.452s
OK
```

### 11.2 后端 API 验证

在 fresh DB 上启动 `.runtime/backend`，逐项执行文档中的方法、路径、请求体与请求头。共 **20 项检查通过**：

- health 200 / ok
- ready 200 / ready
- overview 200 / accounts
- planner planned
- planner clarification 且 steps 为空
- agent run green completed
- agent run yellow awaiting_confirmation
- yellow confirmation completed
- agent run red awaiting_confirmation / requires_reauth
- wrong OTP 403
- correct OTP 246810 completed / mfa_verified
- audit list entries
- audit verify valid=true
- 400 confirm nonexistent
- 403 user reset breaker
- 409 idempotency key reused
- 413 body too large
- 422 validation
- 503 readiness not_ready
- 503 write blocked

### 11.3 curl 可复制性抽查

在 fresh DB 上直接执行文档中的 curl 命令，以下链路通过：

```text
GET  /api/health                 200
GET  /api/health/ready           200 / ready
GET  /api/banking/overview       200
POST /api/planner/plan           200 / planned / yellow / transfer
POST /api/agent/run green        200 / completed / green
POST /api/agent/run yellow       200 / awaiting_confirmation
POST /api/confirmations/{id}     200 / completed / simulated=true
GET  /api/audit/verify           200 / valid=true / checked=8
```

注意：如果同一个数据库已经执行过 880 元与 1200 元转账，再次执行 880 元可能因日累计升级为红色；复现示例前应使用 fresh DB。

### 11.4 门禁结果

```text
gate.ps1 -Repo /tmp/aegisbank-stage4-check -DocsOnly
encoding  pass
lint      pass
build     skip
test      skip（docs fast path）
security  pass（扫描 209 个文件，HIGH=0 MEDIUM=0）
GATE 结果: UNVERIFIED
```

docs-only 变更按快速通道跳过测试，因此标记 unverified；提交时已在 checkpoint 中写明原因。

### 11.5 本次未覆盖

- 未重新运行浏览器 E2E、前端 Vitest 和真实 LLM 测评；
- 前端契约通过阅读 `fronted/frontend/src/api.ts` 与 `types.ts` 核对，未做浏览器联调；
- 应用 252/73/29/15 等数字来自 2026-10-25 历史验证记录，不是本次 docs-only 变更的新输出；
- 本次不宣称生产认证、真实 MFA、OS 级沙箱或通用 NLP 已完成。
## 12. 参考资料

- [根 README](../README.md)
- [贡献指南](../CONTRIBUTING.md)
- [六模块整合记录](INTEGRATION-2026-10-26.md)
- [系统架构](ARCHITECTURE.md)
- [安全设计](SECURITY.md)
- [NLP 现状](NLP-ASSESSMENT-AND-PLAN-2026-10-25.md)
- [NLP 待办](NLP-BACKLOG.md)
- [部署说明](../deliverables/06-部署说明.md)
- [测试与复现](../deliverables/07-测试与复现.md)