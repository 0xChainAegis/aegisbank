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

## 7. 关键接口示例（Stage 2 待补）

以下接口将在 Stage 2 写入真实请求/返回：

- [ ] `GET /api/health`
- [ ] `GET /api/health/ready`
- [ ] `GET /api/banking/overview`
- [ ] `POST /api/planner/plan`
- [ ] `POST /api/agent/run`（绿色 / 黄色 / 红色）
- [ ] `POST /api/confirmations/{action_id}`
- [ ] `GET /api/audit`
- [ ] `GET /api/audit/verify`

示例中会使用以下占位符：

- `<run_id>`
- `<confirmation_id>`
- `<nonce>`
- `<expires_at>`
- `<transaction_id>`
- `<checked>`

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