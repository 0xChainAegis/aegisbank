# AegisBank · 可信银行智能体 MVP

AegisBank 是一个面向银行场景的安全自治智能体原型。项目把「结构化规划 → Plan 编译 → DAG 调度 → 统一权限网关 → 分级确认 → 签名审计」串成一条可运行的闭环，避免把工具逻辑硬编码进 Agent 主流程。

当前仓库完成的是**可开发的银行 Agent 最小闭环**：可插拔结构化 Planner、确定性 Plan Compiler、银行账户/卡片/订阅领域模型、动态风险引擎、账单分析/智能转账/卡片管理三场景、跨场景 DAG、SQLite 哈希链审计、React 控制台和自动化测试都已就位。

> 所有账户、账单、转账结果均为本地模拟数据，不连接任何真实银行系统。

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.12 + FastAPI + Pydantic | 统一 API、工具 SDK、权限网关与 DAG 调度 |
| Planner | Rule + OpenAI-compatible LLM | 结构化 ExecutionPlan，可插拔、可回退、可校验 |
| 持久化 | SQLite（stdlib） | 本地零依赖，保存授权、待确认动作与审计哈希链 |
| 前端 | React 19 + TypeScript + Vite | 任务控制台、权限控制台、操作审计 |
| 测试 | pytest + httpx / Vitest | 后端 API 闭环 + 前端纯逻辑测试 |
| 工程门禁 | DSH Workflow | encoding / lint / build / test / security 五阶段门禁 |
| 运行位置 | Windows 驾驶舱 + WSL Ubuntu 引擎 | 依赖安装、测试、构建均在 Linux 引擎执行 |

## 结构化 Planner

Planner 不直接调用工具，只输出 `ExecutionPlan/v1`：

```json
{
  "intent": "transfer",
  "steps": [
    {
      "id": "step-1",
      "tool_name": "transfer",
      "arguments": {"from_account": "ACC-1001", "to_account": "ACC-2002", "amount_cny": 880},
      "depends_on": []
    }
  ],
  "needs_clarification": false,
  "planner": "rule"
}
```

计划随后经过确定性编译器：工具注册检查、参数 Schema 校验、DAG 拓扑排序、环检测和 `plan_hash` 计算。任何模型输出都不能绕过权限网关。

- 预览计划（不执行）：`POST /api/planner/plan`
- Planner 信息：`GET /api/planner/info`
- 配置：`AEGIS_PLANNER_MODE=rule|llm|auto`

`auto` 模式优先使用 LLM，不可用时自动回退到规则 Planner。

## 快速开始

前置：WSL Ubuntu 24.04 中已有 `uv`、`pnpm`、`python3`（本机 `doctor.ps1` 已确认齐全）。

```bash
# 在仓库根目录执行
bash scripts/bootstrap.sh
bash scripts/dev.sh
```

打开：

- 前端控制台：<http://127.0.0.1:5173>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

也可以分开启动：

```bash
cd backend && uv run uvicorn aegisbank_api.main:app --reload --port 8000
cd frontend && pnpm dev
```

## 三条演示链路

| 场景 | 示例指令 | 动态风险 | 预期行为 |
|---|---|---|---|
| 账单分析 | 分析我的本月账单 | 绿色 | 直接执行，返回分类、异常交易和异常订阅 |
| 智能转账 | 向 ACC-2002 转账 880 元 | 黄色 | 日累计 ≤ 1000 元，确认后执行 |
| 智能转账 | 向 ACC-2002 转账 1200 元 | 红色 | 需演示 OTP `246810` 后执行 |
| 卡片管理 | 把信用卡额度调整到 8000 元 | 红色 | 额度 > 5000 元，强验证后执行 |
| 卡片管理 | 把还款日调整到每月 18 日 | 黄色 | 确认后执行 |
| 跨场景 DAG | 分析我的账单并取消异常订阅 | 黄色 | `query_bill` → 变量解析 → `cancel_subscription` |

在「权限控制台」撤回任一工具权限后，再次调用会在进入调度器之前被统一网关拦截。所有结果都会写入「操作审计」，并可校验 SHA-256 哈希链。

银行演示数据通过 `GET /api/banking/overview` 查看，所有账户、卡片、交易和订阅都来自后端 Mock Bank Core，不由 LLM 编造。


## 工程命令

```bash
bash scripts/bootstrap.sh   # 安装 Python / Node 依赖
bash scripts/dev.sh         # 同时启动前后端
bash scripts/lint.sh        # ruff + tsc
bash scripts/build.sh       # compileall + vite build
bash scripts/test.sh        # pytest + vitest
bash scripts/smoke.sh       # 启动 API 并跑一条绿色链路 + 校验审计链
```

DSH 工作流门禁与提交：

```powershell
# 在 D:\开发交流\mia03-ether 下执行
.\.dsh-workflow\scripts\gate.ps1 -Repo "aegisbank智能体"
.\.dsh-workflow\scripts\checkpoint.ps1 -Repo "aegisbank智能体" -Message "feat: ..."
```

## 目录结构

```text
aegisbank智能体/
├─ backend/
│  ├─ aegisbank_api/
│  │  ├─ banking/         # 账户、卡片、交易、订阅 Mock Bank Core
│  │  ├─ planning/        # 结构化 Planner、Compiler、LLM 适配器
│  │  ├─ risk.py          # 动态金额/日累计/操作风险引擎
│  │  ├─ gateway.py       # 统一权限网关：注入/越权/风险分级
│  │  ├─ scheduler.py     # DAG 调度、变量解析与确认恢复
│  │  ├─ audit.py         # SHA-256 审计哈希链
│  │  ├─ registry.py      # 可插拔工具 SDK
│  │  └─ tools/finance.py # 银行标准工具节点
│  └─ tests/              # API 闭环 + Planner 契约测试
├─ frontend/
│  └─ src/                # 控制台 UI、API 客户端、风险展示
├─ docs/
│  ├─ architecture/       # 完整架构图（PNG / SVG / Mermaid）
│  ├─ ARCHITECTURE.md     # 模块边界与数据流
│  ├─ TECH-STACK.md       # 开发工具与技术栈
│  ├─ SECURITY.md         # 安全边界与生产化清单
│  └─ reference/          # 用户提供的参考手册与界面截图
└─ scripts/               # bootstrap / dev / lint / build / test / render
```

## 文档

- [架构说明](docs/ARCHITECTURE.md)
- [银行领域模型与三场景闭环](docs/BANKING-DOMAIN.md)
- [完整架构图 PNG](docs/architecture/aegisbank-architecture.png)
- [开发工具与技术栈](docs/TECH-STACK.md)
- [AegisAgent 上游项目对齐说明](docs/UPSTREAM-ALIGNMENT.md)
- [上游 PR 设计文件与补丁](upstream-pr/aegis-agent/README.md)
- [开发环境与验收记录](docs/DEVELOPMENT-ENVIRONMENT.md)
- [安全边界与生产化待办](docs/SECURITY.md)
- [参考手册](docs/reference/aegisbank-reference.pdf)

## 已知边界（MVP 刻意不做）

- 单用户 `demo-user`，未接入真实身份认证；
- 工具结果为模拟数据，未接银行核心系统；
- Planner 默认规则驱动；LLM 模式需配置 OpenAI-compatible 模型服务；
- SQLite 适合本地原型，生产需迁移到合规数据库与密钥管理；
- 二次校验只是演示 OTP，生产必须接银行真实 MFA。

这些边界都封装在独立模块中，后续替换不会侵入工具注册与调度核心。
