# 开发工具与技术栈

## 1. 选型原则

AegisBank 的技术栈围绕四个约束选择：

1. **可信执行优先**：LLM 只做规划，权限、DAG、执行和审计必须是确定性的。
2. **可演示、可测试**：本地一条命令启动，绿/黄/红链路可重复验收。
3. **可替换**：模型、工具、策略、存储都通过接口隔离，避免绑定单一供应商。
4. **不过度设计**：MVP 使用中心化权限和单机 SQLite，不引入 P2P、区块链或复杂分布式身份。

## 2. 当前技术栈

| 层 | 技术 | 版本/状态 | 用途 |
|---|---|---|---|
| 操作系统 | WSL2 Ubuntu 24.04（ext4 原生工作区）+ Windows 11 桌面 | 已就绪 | Linux 为开发与执行主线，Windows 仅作展示与备份 |
| 后端语言 | Python | 3.12.3 | Agent 编排、网关、工具和执行器 |
| Web 框架 | FastAPI | 0.148 | REST API、OpenAPI、依赖注入 |
| 数据契约 | Pydantic v2 | 2.14 | Planner、工具参数、API Schema |
| 配置 | pydantic-settings | 2.16 | `.env` / 环境变量配置 |
| HTTP 客户端 | httpx | 0.28 | 调用 OpenAI-compatible LLM |
| ASGI Server | uvicorn | 0.54 | 本地开发与演示服务 |
| 持久化 | SQLite（stdlib） | MVP | 权限、待确认动作、审计哈希链 |
| 前端 | React + TypeScript | React 19 / TS 5.9 | 独立交互层 |
| 前端构建 | Vite | 7.3 | 开发服务器与生产构建 |
| 前端测试 | Vitest | 3.2 | 纯逻辑和组件测试基础 |
| 后端测试 | pytest + httpx | pytest 9.1 | API 闭环与 Planner 契约测试 |
| Python 依赖管理 | uv | 0.12 | lockfile、虚拟环境、可复现安装 |
| Node 依赖管理 | pnpm | 12.10 | lockfile、依赖供应链控制 |
| Lint | ruff + tsc | - | Python 静态检查 + TypeScript 类型检查 |
| 工作流 | DSH Workflow | dsh-v1 | 五阶段门禁、hooks、审计日志 |
| 密钥扫描 | gitleaks / DSH secret-scan | - | 提交前密钥拦截 |
| Shell 检查 | shellcheck | - | `scripts/*.sh` 静态检查 |

## 3. Planner 技术方案

### 3.1 契约

```text
PlanningRequest
  → Planner.plan()
  → ExecutionPlan/v1
  → PlanCompiler
  → CompiledPlan (DAG + plan_hash)
  → Scheduler
```

### 3.2 规划器实现

| 模式 | 实现 | 适用场景 |
|---|---|---|
| `rule` | `RuleBasedPlanner` | 本地默认、离线演示、LLM 兜底 |
| `llm` | `OpenAICompatiblePlanner` | 已配置模型服务时的结构化规划 |
| `auto` | `FallbackPlanner` | 优先 LLM，不可用时自动回退规则 |

### 3.3 模型接入

不绑定单一模型厂商，统一使用 OpenAI-compatible Chat Completions：

```bash
AEGIS_PLANNER_MODE=llm
AEGIS_LLM_BASE_URL=https://your-private-llm.example/v1
AEGIS_LLM_API_KEY=...
AEGIS_LLM_MODEL=aegis-planner
```

建议优先选择支持私有化部署、数据不出行的模型服务。模型只接收：

- 用户指令；
- 显式工具与参数；
- 只读工具目录和 JSON Schema。

模型不接收数据库句柄、密钥、真实账户全量数据，也没有工具执行能力。

### 3.4 为什么不用 LangChain / LlamaIndex 作为核心编排

MVP 的核心链路要求可审计、可验证、可解释。把 Planner、Tool Registry、DAG Scheduler 和 Permission Gateway 保持为轻量自有代码，可以：

- 精确控制 JSON 契约和失败模式；
- 确保模型输出不能绕过权限网关；
- 便于写确定性单元测试；
- 避免框架升级改变安全语义。

后续如需 RAG、文档解析或复杂 Agent 记忆，可在非信任边界内引入这些库，而不替换执行核心。

## 4. 安全与信任组件

| 能力 | MVP 方案 | 生产建议 |
|---|---|---|
| 身份认证 | `demo-user` | OIDC / OAuth2 + 设备绑定 |
| 二次校验 | 演示 OTP | 银行真实 MFA / 生物识别 |
| 权限模型 | 工具级 capability + user grant | ABAC / ReBAC + 短期 scope |
| 策略引擎 | Python 统一网关 | OPA / Cedar，策略与代码分离 |
| Prompt 注入 | 正则基线 + 统一网关 | 分类器 + 策略规则 + 红队评测 |
| 事实校验 | Phase 2 | 规则校验 + 第二模型审查 + 人工复核 |
| 熔断 | Phase 2 | 金额/频次/设备/收款方异常检测 |
| 工具隔离 | 同进程 + 超时/幂等设计 | 独立沙箱、最小网络出口 |
| 审计完整性 | SHA-256 哈希链 | Ed25519 签名 + WORM / KMS |
| 数据存储 | SQLite | PostgreSQL / 银行合规数据库 |
| 密钥管理 | `.env` 本地配置 | Vault / KMS / HSM |

## 5. 前端技术方案

- **React 19 + TypeScript**：保持独立交互层，不把 Agent 能力锁在第三方聊天窗口。
- **Vite**：本地启动快，构建产物可直接由银行内网静态服务器托管。
- **无重型 UI 框架**：MVP 使用自有 CSS，避免引入不必要依赖；后续可替换为银行设计系统。
- **页面结构**：
  - 任务控制台：自然语言输入、快捷工具、结构化计划、执行回执；
  - 权限控制台：按工具授权/撤回；
  - 操作审计：完整字段、哈希链状态、计划与参数证据。
- **安全注意**：正式接入时增加 CSP、内网字体、CSRF 防护和统一登录。

## 6. 开发工具链

| 工具 | 用途 |
|---|---|
| `uv` | Python 依赖锁定、虚拟环境、脚本执行 |
| `pnpm` | 前端依赖锁定与脚本执行 |
| `ruff` | Python lint / import 排序 / 代码质量 |
| `tsc` | TypeScript 静态类型检查 |
| `pytest` | 后端单元与 API 集成测试 |
| `Vitest` | 前端逻辑测试 |
| `httpx.MockTransport` | LLM Planner 网络层测试，避免真实模型依赖 |
| DSH `gate.ps1` | encoding / lint / build / test / security 五阶段门禁 |
| DSH `checkpoint.ps1` | 自动写 Verified-By 尾注并提交 |
| gitleaks / secret-scan | 凭据扫描 |
| `scripts/render_architecture.py` | 生成架构图 SVG |
| Edge headless | 将 SVG 导出为 PNG 预览 |

## 7. 环境变量

```bash
AEGIS_DATABASE_PATH=data/aegisbank.db
AEGIS_DEMO_OTP=246810
AEGIS_CONFIRMATION_TTL_SECONDS=300
AEGIS_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AEGIS_PLANNER_MODE=rule
AEGIS_LLM_BASE_URL=
AEGIS_LLM_API_KEY=
AEGIS_LLM_MODEL=
AEGIS_LLM_TIMEOUT_SECONDS=20
```

所有演示值都只用于本地开发，不能进入生产环境。

## 8. 推荐后续技术演进

1. **Planner 评测集**：覆盖意图识别、参数抽取、缺失字段、恶意指令和歧义澄清。
2. **Action Envelope**：为每个待执行动作生成 `plan_hash + args_hash + nonce + expiry`。
3. **策略引擎**：将风险规则迁移到 OPA/Cedar，支持策略版本和审计。
4. **持久化升级**：SQLite → PostgreSQL；待确认动作和审计事件独立存储。
5. **工具插件协议**：工具 Manifest + entry-point 加载 + 独立版本管理。
6. **可观测性**：OpenTelemetry trace、运行指标、熔断告警和审计看板。
7. **多银行适配**：通过统一 `BankAdapter` 接口隔离不同银行开放平台。
