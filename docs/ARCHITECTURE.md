# 架构说明

## 1. 设计目标

AegisBank 的第一阶段只验证一件事：**是否能把一笔金融操作从自然语言意图安全地送到工具节点，并完整留存可追溯证据。**

因此架构优先保证：

1. Planner 只产出结构化计划，不能直接访问数据库或执行工具；
2. 计划必须通过确定性的 Schema、工具注册和 DAG 依赖校验；
3. 所有工具调用只有一个入口：统一权限网关；
4. 工具是插件，风险等级和最小权限由工具 Manifest 声明；
5. 用户确认是执行状态机的一部分，并且绑定具体计划；
6. 审计证据在操作链路中同步产生，而不是事后补写。

完整架构图：

![AegisBank 完整架构图](architecture/aegisbank-architecture.png)

可编辑源文件：

- [Mermaid 源文件](architecture/aegisbank-architecture.mmd)
- [SVG 矢量图](architecture/aegisbank-architecture.svg)
- 渲染脚本：`scripts/render_architecture.py`

## 2. 端到端数据流

```text
用户自然语言
  │
  ▼
API Gateway
  │  PlanningRequest
  ▼
Planner Interface
  ├── RuleBasedPlanner        （本地默认 / LLM 兜底）
  └── OpenAI-Compatible Planner（可选，结构化 JSON 输出）
  │  ExecutionPlan/v1
  ▼
Deterministic Plan Compiler
  ├── 检查工具是否已注册
  ├── 检查参数是否符合工具 Schema
  ├── 检查 step id / depends_on
  ├── 拓扑排序并检测环
  └── 生成 plan_hash
  │  CompiledPlan
  ▼
DAG Scheduler
  │  preflight every node
  ▼
Permission Gateway
  ├── Identity / Context
  ├── Permission + Scope
  ├── Risk Engine（GREEN / YELLOW / RED）
  ├── Injection / Overreach Guard
  └── Decision: allow / confirm / reauth / deny
  │
  ├── allow → Tool Runtime → Result → Audit
  ├── confirm → Pending Action → User Confirmation → Recheck → Tool Runtime
  └── deny → Audit Blocked
```

## 3. 结构化计划契约

Planner 的实现可以替换，但输入输出契约固定：

### PlanningRequest

```json
{
  "user_id": "demo-user",
  "instruction": "向 ACC-2002 转账 880 元",
  "tool_name": null,
  "arguments": {}
}
```

### ExecutionPlan

```json
{
  "intent": "transfer",
  "steps": [
    {
      "id": "step-1",
      "tool_name": "transfer",
      "arguments": {
        "from_account": "ACC-1001",
        "to_account": "ACC-2002",
        "amount_cny": 880
      },
      "depends_on": [],
      "description": "向指定账户发起小额转账。"
    }
  ],
  "confidence": 0.93,
  "assumptions": ["未指定转出账户，默认使用演示账户 ACC-1001。"],
  "needs_clarification": false,
  "clarification": null,
  "planner": "rule"
}
```

必填约束：

- `steps` 至少一个，最多 12 个；
- `step.id` 唯一；
- `depends_on` 必须引用已有节点且不能形成环；
- 工具必须已在 `ToolRegistry` 注册；
- 参数必须通过工具自己的 Pydantic Schema；
- 高风险必要参数缺失时必须返回 `needs_clarification=true`，不能由 Planner 擅自编造。

### 编译结果

编译器会输出：

- 拓扑排序后的 `PlanNode` 列表；
- 每个节点的风险等级、权限、标题；
- `plan_hash`：对规范化后的 intent + steps 计算 SHA-256；
- `dag_path`：用于审计的节点路径；
- Planner 来源、置信度和假设。

预览接口不执行任何工具：

```http
POST /api/planner/plan
Content-Type: application/json

{"instruction":"向 ACC-2002 转账 880 元"}
```

## 4. Planner 可插拔机制

`backend/aegisbank_api/planning/` 是独立规划包：

| 文件 | 职责 |
|---|---|
| `contracts.py` | `PlanningRequest` / `ExecutionPlan` / `PlanStep` / `Planner` 协议 |
| `rule.py` | 确定性规则 Planner，作为默认实现与安全兜底 |
| `llm.py` | OpenAI-compatible 模型 Planner，只接收工具目录并返回 JSON |
| `compiler.py` | Schema、工具、参数、DAG、环检测、plan hash |
| `factory.py` | 根据环境变量选择 `rule` / `llm` / `auto` |

配置：

```bash
AEGIS_PLANNER_MODE=rule          # rule | llm | auto
AEGIS_LLM_BASE_URL=
AEGIS_LLM_API_KEY=
AEGIS_LLM_MODEL=
AEGIS_LLM_TIMEOUT_SECONDS=20
```

`auto` 模式会优先使用 LLM Planner；模型不可用、超时或输出无法解析时，安全回退到规则 Planner。无论哪种模式，模型输出都必须经过同一个 Plan Compiler 和权限网关。

## 5. 核心模块

### 5.1 Tool SDK

`registry.py` 定义 `BaseTool` 与 `ToolRegistry`。每个工具必须声明：

- `name` / `title` / `description`
- `risk_level`：green / yellow / red
- `permission`：最小权限字符串
- `input_schema` / `output_schema`：Pydantic 生成
- `arguments_model`：供 Plan Compiler 做执行前参数校验

### 5.2 权限网关

`gateway.py` 在 DAG 执行前做统一校验：

1. Prompt 注入 / 越权识别；
2. 用户与工具权限判断；
3. 绿色直接放行；
4. 黄色生成待确认动作；
5. 红色生成待确认动作并要求二次校验。

确认动作执行前会重新检查权限，防止等待期间权限被撤回。

### 5.3 DAG 调度与确认状态机

调度器先对全部节点做 preflight：任一节点被拒绝则整个任务阻断；任一节点需要确认则整个任务进入 `pending_actions`，避免只执行一半再弹窗。

```text
pending ──approve──► approved ──execute──► completed
   │
   ├──reject──► rejected
   ├──timeout─► expired
   └──recheck fail─► blocked
```

待确认记录同时保存 `dag_json` 和 `plan_json`，保证确认页面、执行器和审计看到的是同一份结构化计划。

### 5.4 签名审计

每条审计记录包含：

1. 触发时间；
2. 用户原始指令；
3. DAG 节点路径；
4. 工具调用入参；
5. 执行结果；
6. 用户确认状态。

记录以 SHA-256 链式串联：`entry_hash = SHA256(prev_hash + canonical(entry))`。`GET /api/audit/verify` 校验整条链。

### 5.5 前端

React 控制台包含：

- **任务控制台**：输入指令、快捷工具、结构化计划预览、执行回执、确认弹窗；
- **权限控制台**：查看/授予/撤回每个工具的最小权限；
- **操作审计**：查看完整审计字段与哈希链状态。

## 6. 数据模型

| 表 | 用途 |
|---|---|
| `permissions` | 用户对每个工具的授权状态 |
| `pending_actions` | DAG、计划快照、风险级别、过期时间与确认状态 |
| `audit_log` | 追加式审计记录与哈希链字段 |

## 7. 当前落地范围

- ✅ 可插拔 Planner 接口
- ✅ 规则 Planner
- ✅ OpenAI-compatible Planner 适配器
- ✅ 自动安全回退
- ✅ 结构化 ExecutionPlan 契约
- ✅ 确定性 Plan Compiler 与 DAG 环检测
- ✅ `plan_hash`
- ✅ Planner 预览 API
- ✅ 前端计划可视化
- ⏳ LLM 真实联调与提示词评测
- ⏳ Action Envelope 签名与 nonce
- ⏳ 事实校验、异常熔断、沙箱与 WORM 审计
