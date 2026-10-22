# AegisBank —— 项目规则

> 本文件是产品主线仓库的工程约定。上级工作区规则见 `../AGENTS.md`；两者冲突时以本文件为准。
> 总规划：[`docs/MASTER-PLAN.md`](docs/MASTER-PLAN.md)｜路线图：[`docs/ROADMAP.md`](docs/ROADMAP.md)

## 产品目标

构建银行场景的可信 AI 智能体（AI Banking Agent）：

```text
自然语言意图
  → 结构化 Planner（只生成计划，不执行工具）
  → 确定性 Plan Compiler（Schema / DAG / plan_hash）
  → 动态风险引擎（绿 / 黄 / 红 + 可解释原因）
  → 统一权限网关（最小权限 / 注入拦截 / 分级决策）
  → 分级确认与演示 MFA
  → Mock Bank Core 工具执行
  → SHA-256 审计哈希链
```

所有金融结果在接入真实银行接口前，都必须是 Mock Bank Core 的确定性模拟数据，不得编造。

## 当前阶段

- **阶段 0（产品边界与仓库定型）已完成**：上游 PR 材料归档到 `archive/upstream-plan-provenance`，`main` 只保留产品内容。
- **当前进入阶段 1：吸收 AegisAgent 的信任工程**——Action Envelope、幂等键、状态机（`UNKNOWN/RECONCILED/ROLLED_BACK`）、readiness 与 fail closed、证据分层、注入整条拒绝、模型候选白名单。
- 阶段 2（回退补偿、熔断、沙箱、MFA、IM）、阶段 2.5（人工用户体验 Dogfooding）、阶段 3（比赛材料）见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

## 仓库与开发位置

| 项 | 值 |
|---|---|
| 产品主线仓库 | <https://github.com/LQZ5885/aegisbank>（Public / MIT / 默认分支 `main`） |
| 开发主线目录 | WSL Ubuntu 24.04 ext4：`/home/lqz5885/aegisbank/dev/aegisbank` |
| 展示与备份 | Windows `D:\开发交流\mia03-ether\aegisbank智能体`（历史副本，**已冻结，不再开发**） |
| 归档分支 | `archive/upstream-plan-provenance`（历史上游 PR 材料，只读） |

不要在 Windows 历史副本上继续开发；需要展示时从 Linux 主线单向复制。

## 不可破坏的架构约束

- 所有工具调用必须经过 `backend/aegisbank_api/gateway.py`，禁止在 API 或工具内部绕过权限判断。
- 新工具必须继承 `BaseTool` 并声明：风险等级、最小权限、输入/输出 schema。
- 动态风险引擎只能保持或上调工具基线风险，**任何模型输出都不得降低风险等级**。
- 审计日志必须包含：触发时间、原始指令、DAG 路径、工具入参、执行结果、用户确认状态，并保持 SHA-256 哈希链。
- LLM 只生成计划/草稿，不得直接执行工具、决定权限、跳过确认或编造金融结果。
- 前端只通过 `/api` 调用后端，不内嵌业务权限判断；服务未就绪时必须禁用写操作（fail closed）。
- 禁止提交真实银行凭证、客户数据或 `.env`；演示 OTP `246810` 只能用于本地开发。

## 门禁与提交

开发主线在 WSL 内，脚本来自工作流目录 `/mnt/d/开发交流/mia03-ether/.dsh-workflow`。

```bash
# 门禁（在 WSL Ubuntu 中执行）
cd /home/lqz5885/aegisbank/dev/aegisbank
pwsh -NoProfile -File /mnt/d/开发交流/mia03-ether/.dsh-workflow/scripts/gate.ps1 \
  -Repo /home/lqz5885/aegisbank/dev/aegisbank

# 提交
pwsh -NoProfile -File /mnt/d/开发交流/mia03-ether/.dsh-workflow/scripts/checkpoint.ps1 \
  -Repo /home/lqz5885/aegisbank/dev/aegisbank -Message "feat: ..."
```

推送使用 Windows 侧 git（WSL 内没有配置凭据）：

```powershell
$unc = '\\wsl.localhost\Ubuntu-24.04\home\lqz5885\aegisbank\dev\aegisbank'
git -C $unc push origin main
```

常用项目脚本（WSL 内）：`bash scripts/bootstrap.sh` / `dev.sh` / `lint.sh` / `build.sh` / `test.sh` / `smoke.sh`。

## 项目结构

- `backend/aegisbank_api/`：FastAPI、工具 SDK、权限网关、动态风险、DAG 调度、审计
  - `banking/`：Mock Bank Core 领域模型与 SQLite 仓库
  - `planning/`：Planner 契约、规则/LLM 实现、Plan Compiler
  - `tools/finance.py`：9 个银行工具与 Manifest
- `backend/tests/`：API 闭环与 Planner 契约测试
- `frontend/src/`：银行概览、任务控制台、权限控制台、操作审计
- `scripts/`：依赖安装、开发启动、lint/build/test/smoke
- `docs/`：总规划、架构、安全边界、路线图、Dogfooding、参考资料

## 文档纪律

- 行为变更必须同步更新对应文档（README / ROADMAP / SECURITY / MASTER-PLAN）。
- 阶段性结论写入 `docs/MASTER-PLAN.md` 和 `docs/ROADMAP.md`，不要只留在对话里。
- 对外材料（README、产品介绍页、截图）必须反映当前真实功能，不得把“计划中”写成“已完成”。
