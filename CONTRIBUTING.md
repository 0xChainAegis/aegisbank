# 贡献指南

AegisBank 是面向「银行 AI 智能体」赛题的**可运行原型**。我们欢迎评审、复现和问题反馈；在提交任何改动前，请先阅读本文件与 [`docs/MASTER-PLAN.md`](docs/MASTER-PLAN.md)。

## 1. 项目边界

- 所有银行数据来自 Mock Bank Core 的确定性模拟数据，**本项目不连接真实银行系统、支付网络或客户数据**。
- 演示 OTP `246810` 仅用于本地流程展示，不是生产 MFA。
- 上游 `0xChainAegis/aegis-agent` 只作为信任工程的设计参考，其 Gas 钱包业务不进入本项目主流程。

提交内容不得包含真实凭证、客户数据、`.env` 文件或任何可用于真实业务的密钥。

## 2. 开发环境

推荐 WSL2 Ubuntu 24.04（项目主线开发目录在其中），需要 Python 3.11+ / `uv`、Node.js 20.19+ 或 22.12+ / `pnpm`。

```bash
bash scripts/bootstrap.sh   # 安装后端与前端依赖
bash scripts/dev.sh         # 同时启动 API(8000) 与前端(5173)
```

## 3. 分支与提交

- `main` 是唯一产品主线，始终保持可构建、可测试。
- `archive/upstream-plan-provenance` 是历史上游 PR 材料的只读归档分支，不再修改。
- 功能开发使用独立分支（如 `feat/trust-action-envelope`），完成后合入 `main`。
- 提交信息使用 Conventional Commits 前缀：`feat:` / `fix:` / `docs:` / `chore:` / `test:`。
- 提交前必须通过门禁（见下节）。

## 4. 门禁与验证

```bash
bash scripts/lint.sh    # ruff + TypeScript 类型检查
bash scripts/build.sh   # 后端 compileall + Vite 生产构建
bash scripts/test.sh    # pytest + Vitest
bash scripts/smoke.sh   # 启动 API，跑绿色链路并校验审计哈希链
```

如使用 DSH 工作流，提交必须经 `gate.ps1` 五阶段（encoding / lint / build / test / security）通过后由 `checkpoint.ps1` 生成提交。命令见仓库根 [`AGENTS.md`](AGENTS.md)。

## 5. 代码约定

- 新增工具必须继承 `BaseTool`，声明风险等级、最小权限和输入/输出 schema，并且只能通过 `backend/aegisbank_api/gateway.py` 被调用。
- 风险等级只能保持或上调，不允许任何模型输出降低风险。
- 审计记录字段不得裁剪：触发时间、原始指令、DAG 路径、工具入参、执行结果、用户确认状态。
- 前端不内嵌业务权限判断，只消费 `/api` 返回的结果。
- 新增依赖需更新锁文件（`backend/uv.lock` / `frontend/pnpm-lock.yaml`）。

## 6. 文档要求

- 行为变更同步更新相关文档：`README.md`、`docs/ROADMAP.md`、`docs/SECURITY.md`、`docs/MASTER-PLAN.md`。
- 对外表述必须与真实实现一致，未实现的能力要标注为「计划中」，不得写成已落地。

## 7. 反馈

- 可通过 GitHub Issue 描述复现步骤、期望行为与实际行为。
- 安全相关问题请不要公开细节，先与维护者私下沟通。

## 8. 许可证

贡献即表示同意以 [MIT License](LICENSE) 授权，Copyright (c) 2026 LQZ5885。
