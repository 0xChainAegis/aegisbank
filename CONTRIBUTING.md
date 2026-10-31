# 贡献指南

AegisBank 是面向「银行 AI 智能体」赛题的**可运行原型**。我们欢迎评审、复现和问题反馈；在提交任何改动前，请先阅读本文件与 [`docs/MASTER-PLAN.md`](docs/MASTER-PLAN.md)。

## 1. 项目边界

- 所有银行数据来自 Mock Bank Core 的确定性模拟数据，**本项目不连接真实银行系统、支付网络或客户数据**。
- 演示 OTP `246810` 仅用于本地流程展示，不是生产 MFA。
- 上游 `0xChainAegis/aegis-agent` 只作为信任工程的设计参考，其 Gas 钱包业务不进入本项目主流程。

提交内容不得包含真实凭证、客户数据、`.env` 文件或任何可用于真实业务的密钥。

## 2. 开发环境

后端需要 Linux 或 WSL，因为数据库锁依赖 fcntl。预装 Python 3.11+（含 venv/pip）和 Node.js（含 npm，版本 `^22.22.2 || ^24.15.0 || >=26.0.0`）后，仓库根目录运行：

```bash
bash start.sh
```

入口自动准备缺失的项目内 uv/pnpm、组装并安装冻结依赖，首次初始化独立模拟库；重复启动保留数据，Ctrl+C 关闭本次启动的前后端。该入口固定离线规则 Planner、关闭后台自动任务并开启沙箱。`--no-browser` 仅输出地址，`--database /绝对路径/demo.db` 选择已有或新的模拟库，不会重置。

开发热重载或使用 .env 中的可选模型配置时，保留手动流程（需要已安装的 uv/pnpm）。每人使用独立检出目录，作者机器上的绝对路径不是前置条件。

```bash
python3 scripts/assemble.py # 从六个源码包生成 .runtime
cd .runtime
bash scripts/bootstrap.sh   # 安装后端与前端依赖
bash scripts/dev.sh         # 同时启动 API(8000) 与前端(5173)
```

前端修改 `fronted/frontend/`，后端按 `backend/`、`agent/`、`NLP/`、`skills/`、`plans/` 的职责修改；改完重新组装。`.runtime/` 不提交，也不在其中维护另一份源码。根 `AGENTS.md` 列出具体映射。

## 3. 分支与提交

- 组织仓库 `0xChainAegis/aegisbank` 的 `main` 是团队集成主线，始终保持可构建、可测试；不在原作者仓库与组织仓库同时维护两条集成主线。
- 历史上游 PR 材料保留在[原作者归档分支](https://github.com/LQZ5885/aegisbank/tree/archive/upstream-plan-provenance)，本轮不复制或修改该归档。
- 功能开发使用独立分支（如 `feat/trust-action-envelope`），完成后合入 `main`。
- 前端、后端各自分支提交，经 PR 对齐后合入；修改接口、共享类型或同一文件前先沟通。AI 生成的修改也需要负责人阅读并复现。
- 提交信息使用 Conventional Commits 前缀：`feat:` / `fix:` / `docs:` / `chore:` / `test:`。
- 提交前必须通过门禁（见下节）。

具体文件边界、已有原仓库如何接入团队 remote，以及接口交接方式见 [团队协作说明](docs/TEAM-WORKFLOW.md)。

## 4. 门禁与验证

```bash
# 在仓库根目录；这些入口先组装，再执行运行工程里的对应脚本
bash scripts/lint.sh    # ruff + TypeScript 类型检查
bash scripts/build.sh   # 后端 compileall + Vite 生产构建
bash scripts/test.sh    # pytest + Vitest
bash scripts/smoke.sh   # 启动 API，跑绿色链路并校验审计哈希链
bash scripts/check-api-contract.sh  # 前端调用路径 vs 后端 OpenAPI
```

推送或 PR 后，GitHub CI 在 Linux 中分别验证后端和前端，使用冻结锁文件安装依赖。必须查看实际通过结果，不把新增工作流等同于验证通过。若在原作者机器使用 DSH 工作流，仍按其 `gate.ps1` / `checkpoint.ps1` 约定执行；该外部工作流不是其他成员的必需安装项。

## 5. 代码约定

- 新增工具必须继承 `BaseTool`，声明风险等级、最小权限和输入/输出 schema，并且只能通过统一网关调用；源文件为 `agent/backend/aegisbank_api/gateway.py`，组装后位于 `.runtime/backend/aegisbank_api/gateway.py`。
- 风险等级只能保持或上调，不允许任何模型输出降低风险。
- 审计记录字段不得裁剪：触发时间、原始指令、DAG 路径、工具入参、执行结果、用户确认状态。
- 前端不内嵌业务权限判断，只消费 `/api` 返回的结果。
- 新增依赖需更新源锁文件（`backend/backend/uv.lock` / `fronted/frontend/pnpm-lock.yaml`），不只更新生成目录中的锁文件。

## 6. 文档要求

- 行为变更同步更新相关文档：`README.md`、`docs/ROADMAP.md`、`docs/SECURITY.md`、`docs/MASTER-PLAN.md`。
- 对外表述必须与真实实现一致，未实现的能力要标注为「计划中」，不得写成已落地。

## 7. 反馈

- 可通过 GitHub Issue 描述复现步骤、期望行为与实际行为。
- 安全相关问题请不要公开细节，先与维护者私下沟通。

## 8. 许可证

贡献即表示同意以 [MIT License](LICENSE) 授权，Copyright (c) 2026 LQZ5885。
