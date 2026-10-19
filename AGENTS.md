# aegisbank智能体 —— 项目规则

> 继承工作区宪法（工作区根的 AGENTS.md）。此处只写本项目的特殊约定；冲突时以本文件为准。

## 产品目标

构建银行场景的可信 Agent MVP：意图解析 → DAG 调度 → 统一权限网关 → 绿/黄/红分级确认 → 签名审计。所有金融结果在未接真实银行接口前必须是模拟数据。

## 不可破坏的架构约束

- 所有工具调用必须经过 `backend/aegisbank_api/gateway.py`，禁止在 API 或工具内部绕过权限判断。
- 新工具必须继承 `BaseTool` 并声明：风险等级、最小权限、输入/输出 schema。
- 审计日志必须包含：触发时间、原始指令、DAG 路径、工具入参、执行结果、用户确认状态；并保持 SHA-256 哈希链。
- 禁止提交真实银行凭证、客户数据或 `.env`；演示 OTP 只能用于本地开发。
- 前端只通过 `/api` 调用后端，不内嵌业务权限判断。

## 门禁与提交

- **门禁**：`..\.dsh-workflow\scripts\gate.ps1 -Repo .`
- **提交**：`..\.dsh-workflow\scripts\checkpoint.ps1 -Repo . -Message "..."`
- runner：wsl（依赖安装、lint、build、test 在 Ubuntu 引擎执行）
- 常用：`bash scripts/bootstrap.sh` / `bash scripts/dev.sh` / `bash scripts/test.sh`

## 项目结构

- `backend/aegisbank_api/`：FastAPI、工具 SDK、权限网关、DAG 调度、审计
- `backend/tests/`：API 闭环测试
- `frontend/src/`：React 任务控制台、权限控制台、操作审计
- `scripts/`：依赖安装、开发启动、lint/build/test
- `docs/`：架构、安全边界与用户参考资料

## 当前阶段

第一阶段最小闭环骨架已搭好。下一步优先补充：真实 LLM 规划器、策略引擎、更多工具节点、异常熔断、权限控制台审计联动。
