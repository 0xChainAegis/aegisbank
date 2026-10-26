# AegisBank 完整架构图

本目录包含三份等价表达：

| 文件 | 用途 |
|---|---|
| `aegisbank-architecture.png` | 演示、文档嵌入和高清预览 |
| `aegisbank-architecture.svg` | 可缩放矢量图，适合汇报和二次编辑 |
| `aegisbank-architecture.mmd` | Mermaid 源文件，适合在 Markdown / 代码评审中维护 |

重新生成 SVG 与 PNG：

```bash
python scripts/render_architecture.py
# 可选：使用 Edge headless 将 SVG 转为 PNG
```

## 图例

- **绿色边框**：当前已经落地的核心组件
- **黄色虚线**：第二阶段或生产化规划组件
- **灰色**：数据与证据存储
- **外部系统列**：通过适配器接入；MVP 全部为 Mock 或可选配置

## 关键数据流

1. 用户在 React 控制台输入自然语言。
2. FastAPI 创建 `PlanningRequest`，交给可插拔 Planner。
3. Planner 返回 `ExecutionPlan`，不能直接调用工具。
4. Plan Compiler 做 Schema、工具注册、DAG 环检测和 `plan_hash`。
5. DAG Scheduler 对全部节点做 preflight。
6. Permission Gateway 统一完成权限、风险、注入和越权检查。
7. 绿色直接执行；黄色/红色进入确认状态机，确认后复检权限再执行。
8. Tool Runtime 执行标准工具节点。
9. Audit Emitter 将计划哈希、参数、结果和确认状态写入哈希链。

## 信任不变量

1. LLM 不直接调用工具；
2. 所有工具调用经过权限网关；
3. 用户确认必须绑定精确动作（plan hash / nonce / expiry）；
4. 执行后必须产生可验证审计证据；
5. 高风险默认暂停；
6. 计划必须通过确定性编译；
7. 生产环境不存储全量金融数据，不引入 P2P 或去中心化身份。
