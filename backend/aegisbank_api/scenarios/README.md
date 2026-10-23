# 场景模块契约（2B 六场景完整覆盖）

`aegisbank_api/scenarios/` 下每个 `.py` 文件（文件名不以 `_` 开头）即一个业务场景。
`create_app()` 通过 `iter_scenario_modules()` 自动发现并依次调用下表契约，**不需要修改任何核心文件**。

## 必须/可选导出的契约

| 名称 | 类型 | 何时调用 | 说明 |
|---|---|---|---|
| `NAME` | `str` | — | 场景标识，例如 `"wealth"` |
| `SCHEMA_SQL` | `str` | 应用启动 | `CREATE TABLE IF NOT EXISTS ...`；可为空串 |
| `seed(db, user_id)` | 函数 | 应用启动 | 幂等写入模拟数据（`INSERT OR IGNORE` / 先查存在） |
| `tools(services)` | 函数 | 构造注册表时 | 返回 `list[BaseTool]`；工具必须继承 `BaseTool` |
| `intents()` | 函数 | Planner 构造时 | 返回 `list[IntentRule]`；不适用时规则返回 `None` |
| `risk_rules()` | 函数 | 风控引擎构造时 | 返回 `list[RiskRule]`；只允许保持或升级工具基线风险 |
| `router(services)` | 函数 | 应用装配时 | 返回 `APIRouter`（可含前缀 `/api/...`）或 `None` |
| `start_background(services)` | 函数 | 启动钩子 | 可选；时间维度自动化线程，需检查 `settings.automation_enabled` |
| `stop_background()` | 函数 | 关闭钩子 | 与 `start_background` 成对出现 |

## 硬性约束

1. **所有写操作必须走工具节点**：工具由 `ToolRegistry` 注册，最终经 `gateway.evaluate()` 判定；场景模块不得在路由层直接改资金/账户状态。
2. **数据必须确定**：金额、账户、卡片、产品等事实来自 SQLite（本模块 schema + seed），不得由 LLM 或常量直接编造。
3. **风险只升不降**：`RiskRule.assess()` 返回的等级会与工具基线取最大值，不得下调。
4. **路由只读**：`router()` 暴露的 GET 接口用于前端展示；写操作走 `/api/agent/run`。
5. **禁止跨模块私有约定**：需要其它场景数据时，直接读取已存在的表（表结构见各自模块的 `SCHEMA_SQL`），或通过 `services.repository`。
6. **幂等**：同一请求重复提交不得产生第二笔资产变动（阶段一幂等键在 `trust/` 提供）。
7. **模拟数据**：理财等内容必须标注“模拟数据、不构成投资建议”。

## 目录约定

```text
backend/aegisbank_api/scenarios/
├─ __init__.py          # 自动发现与装配（核心，勿改契约）
├─ README.md            # 本文件
├─ wealth.py            # 理财：产品/持仓/申购/赎回
├─ transfers.py         # 联系人簿 + 人名转账 + AA 拆分
├─ bills.py             # 账单月报/年报 + 异常检测 + 订阅扣费识别/续费提醒
├─ cards.py             # 虚拟卡申请/审核/密码修改/限额解锁
├─ automation.py        # 定时转账调度 + 生日跨场景联动 + 时间快进
└─ ...
```

统一测试方式：`cd backend && uv run pytest -q`。每个场景至少 1 条正向链路、1–2 条风险分级、1 条撤权/失败/DAG 用例。
