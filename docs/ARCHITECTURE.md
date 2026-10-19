# 架构说明

## 1. 设计目标

AegisBank 的第一阶段只验证一件事：**是否能把一笔金融操作从自然语言意图安全地送到工具节点，并完整留存可追溯证据。**

因此架构优先保证：

1. 所有工具调用只有一个入口：统一权限网关；
2. 工具是插件，不是主流程里的 `if/else`；
3. 风险等级由工具自身声明，调度器不写死业务规则；
4. 用户确认是执行状态机的一部分，不是前端装饰；
5. 审计日志在操作链路中同步产生，而不是事后补写。

## 2. 分层

```text
React Console
    │  POST /api/agent/run
    ▼
FastAPI API ──────────────► Intent Resolver
    │                            │
    │                            ▼
    │                      DagScheduler
    │                            │
    │                   preflight every node
    │                            ▼
    │                    PermissionGateway
    │                  ┌─────────┼──────────┐
    │                  ▼         ▼          ▼
    │                allow     confirm      deny
    │                  │         │            │
    │                  │    pending_action    └── audit blocked
    │                  │         │
    │                  ▼         ▼
    │             Tool Registry (SDK)
    │             ├─ query_bill             green
    │             ├─ adjust_repayment_date  yellow
    │             └─ transfer               red
    │                  │
    │                  ▼
    └──────────────► AuditService (SHA-256 chain) ──► SQLite
```

## 3. 核心模块

### 3.1 Tool SDK

`backend/aegisbank_api/registry.py` 定义 `BaseTool` 与 `ToolRegistry`。每个工具必须声明：

- `name` / `title` / `description`
- `risk_level`：green / yellow / red
- `permission`：最小权限字符串
- `input_schema` / `output_schema`：Pydantic 生成

调度器只依赖 `ToolMetadata` 和 `execute(arguments, context)`，新增工具只需要注册实例，不需要修改核心调度逻辑。

### 3.2 权限网关

`gateway.py` 在 DAG 执行前做统一校验：

1. **Prompt 注入 / 越权识别**：命中已知注入模式直接拒绝；
2. **权限判断**：按用户与工具查询 SQLite 授权表；
3. **风险分流**：
   - green → 立即放行；
   - yellow → 生成待确认动作；
   - red → 生成待确认动作且要求二次校验。

所有三态结果都会先记录审计，再决定是否执行。

### 3.3 DAG 调度与确认状态机

当前 MVP 的规划器是确定性规则，输出一个 `PlanNode` 列表。调度器会先对**全部节点**做 preflight：任一节点被拒绝则整个任务阻断；任一节点需要确认则整个任务进入 `pending_actions` 表，避免只执行一半再弹窗。

确认流程：

```text
pending ──approve──► approved ──execute──► completed
   │
   ├──reject──► rejected
   └──timeout─► expired
```

确认 ID 使用随机 token，默认 5 分钟过期；红色操作额外校验演示 OTP。

### 3.4 签名审计

每条审计记录包含产品要求的六个核心字段：

1. 触发时间；
2. 用户原始指令；
3. DAG 节点路径；
4. 工具调用入参；
5. 执行结果；
6. 用户确认状态。

记录以 SHA-256 链式串联：`entry_hash = SHA256(prev_hash + canonical(entry))`。`GET /api/audit/verify` 可校验整条链。

### 3.5 前端

React 控制台只通过 API 与后端交互，包含三个页面：

- **任务控制台**：输入指令、快捷工具、执行回执、确认弹窗；
- **权限控制台**：查看/授予/撤回每个工具的最小权限；
- **操作审计**：查看完整审计字段与哈希链状态。

## 4. 数据模型

| 表 | 用途 |
|---|---|
| `permissions` | 用户对每个工具的授权状态 |
| `pending_actions` | 等待确认的 DAG 计划、风险级别、过期时间与状态 |
| `audit_log` | 追加式审计记录与哈希链字段 |

## 5. 下一阶段扩展点

- 用 LLM 规划器替换 `infer_tool`，但保持输出仍为 `PlanNode` 列表；
- 把 `ToolRegistry` 扩展为 entry-point 插件加载；
- 将确认状态机迁移到持久化工作流引擎；
- 把 SQLite 审计迁移到 WORM 存储或银行合规审计平台；
- 在网关增加策略引擎（OPA/Cedar）与更完整的注入检测。
