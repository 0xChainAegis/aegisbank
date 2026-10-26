# 核心扩展契约（阶段 2A）

`aegisbank_api/extensions/` 下每个 `.py` 文件（不以 `_` 开头）代表一项横切能力。
`create_app()` 自动发现并按约定调用，**不需要修改 main.py / scheduler.py 的核心装配**。

## 可选导出

| 名称 | 签名 | 说明 |
|---|---|---|
| `NAME` | `str` | 扩展标识（建议必填） |
| `SCHEMA_SQL` | `str` | 幂等建表 SQL；应用启动时执行 |
| `seed(db, user_id)` | 函数 | 幂等写入演示数据 |
| `activate(services)` | 函数 | 运行时接线（此时 scheduler/executor/mfa/authz 均已就绪） |
| `tools(services)` | 函数 | 返回额外 `BaseTool` 列表（会进统一注册表与权限种子） |
| `router(services)` | 函数 | 返回 `APIRouter`（路径自带 `/api/...` 前缀）或 `None` |
| `start_background(services)` / `stop_background()` | 函数 | 可选后台线程，成对出现 |

`CoreServices` 提供：`db / repository / settings / registry / gateway / audit / scheduler / executor / mfa / authz / compensation / extras`。

## 硬性约束

1. 写操作必须走工具节点 + 统一网关 + 审计；扩展路由只做运维/只读/演示触发。
2. 不得在扩展内降低风险等级或跳过确认；补偿/回滚必须写审计。
3. 不修改核心装配文件（`main.py`、`scheduler.py` 的公共契约）；如需新能力先在 `CoreServices` 已有字段上扩展或用 `extras`。
4. 并行开发隔离：`AEGIS_EXTENSION_ALLOW=mfa,breaker`，或 `AEGIS_EXTENSION_ALLOW=none` 只跑核心。
5. 每个扩展至少 3 条测试：正向、拒绝/失败、审计可见。
