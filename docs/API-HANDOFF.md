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
## 8. 演示数据与排障

- 首次启动会自动建库并写入确定性 Mock Bank Core 种子。
- `seed-demo.sh` 默认重置 `.runtime/backend/data/dogfood.db`，而 `dev.sh` 默认使用 `.runtime/backend/data/aegisbank.db`；需要 3000 元虚拟卡时，必须让后端指向同一个数据库。
- 建议使用绝对路径：
  ```bash
  bash scripts/seed-demo.sh "$PWD/.runtime/backend/data/aegisbank.db"
  bash scripts/dev.sh
  ```
- 重置数据库前先停止后端，避免 SQLite 文件锁。
- 端口冲突时检查 8000 / 5173：
  ```bash
  ss -ltnp | grep -E ':8000|:5173'
  ```

## 9. 已知边界

- 全部账户、卡片、账单、理财和交易均为 Mock Bank Core 模拟数据，不连接真实银行。
- `X-Aegis-Role` 只是演示请求头，不是身份认证。
- 固定 OTP `246810` 和模拟生物识别不是生产 MFA。
- 当前 NLP 只完成 P0；P1–P4 的通用上下文、对话纠错、任意条件与组合规划仍未实现。
- 进程内工具沙箱不是 OS 级隔离；没有真实 IM 平台接入。
- 测试通过只代表已知用例可复现，不代表生产安全认证。

## 10. 参考资料

- [根 README](../README.md)
- [贡献指南](../CONTRIBUTING.md)
- [六模块整合记录](INTEGRATION-2026-10-26.md)
- [系统架构](ARCHITECTURE.md)
- [安全设计](SECURITY.md)
- [部署说明](../deliverables/06-部署说明.md)
- [测试与复现](../deliverables/07-测试与复现.md)