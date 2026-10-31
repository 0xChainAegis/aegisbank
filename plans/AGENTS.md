# AegisBank —— 项目规则

> 2026-10-25 NLP P0：金额统一规范化，未支持的条件/组合请求转澄清；rule / llm / auto / 显式工具入口共用检查，详情见 [P0 记录](docs/NLP-ASSESSMENT-AND-PLAN-2026-10-25.md)。

> 2026-10-24 后端补强：补偿设置冲突保护、恢复额度风险复检、事务内 MFA 拒绝、权限与审计原子提交。见 [本轮记录](docs/BACKEND-HARDENING-2026-10-24.md)。

> 2026-10-23 安全复审后更新；本轮修复、反例与验收见 [安全修复记录](docs/REMEDIATION-PLAN-2026-10-23.md)。
> 本文件保留原作者工程约定的历史背景。2026-10-26 起，当前六包源码位置、生成目录和团队命令见根 [`AGENTS.md`](../AGENTS.md)，目录与开发流程不一致时以根文件为准；下文安全架构约束仍适用。
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
  → ToolExecutor + 执行守卫（沙箱/超时/网络/体积）
  → Mock Bank Core 工具执行
  → SHA-256 审计哈希链
```

所有金融结果在接入真实银行接口前，都必须是 Mock Bank Core 的确定性模拟数据，不得编造。

## 当前阶段

- **阶段 0（产品边界与仓库定型）已完成**：上游 PR 材料归档到 `archive/upstream-plan-provenance`，`main` 只保留产品内容。
- **阶段 1（信任工程）已完成**：`backend/aegisbank_api/trust/` 落地 ActionEnvelope/v1、幂等键、状态机（含 `UNKNOWN / RECONCILED / ROLLED_BACK`）、readiness fail-closed、证据分层、注入整条拒绝与模型候选白名单；新增 `GET /api/health/ready`、`/api/trust/*` 接口；`POST /api/agent/run` 与 `POST /api/confirmations/{id}` 支持 `Idempotency-Key`，确认链路区分 409 / 422 / 503 语义；`backend/tests/test_trust.py` 共 17 条用例。
- **阶段 2B（六场景完整覆盖）已完成**：`scenarios/` 下 5 个场景模块（`wealth` / `transfers` / `bills` / `cards` / `automation`）覆盖赛题六个参考场景 6/6，新增 26 个场景工具。
- **阶段 2A（六项硬要求，后端/API）已完成**（基线 `bf36895`）：步骤级暂停/恢复/回退/补偿（28 条补偿规格，15 可补偿 / 13 不可逆）、三类规则可疑行为熔断与 operator 解锁、可插拔 MFA Provider（OTP + 模拟生物识别）、IM/CLI/webhook 渠道适配器、进程内工具沙箱（超时/网络/入参出参/白名单）、多角色与撤权（`user / operator / auditor`）。工具目录共 **50 个**（核心 10 + 场景 26 + 2A 扩展 14）；后端 **252 项** pytest（17 个测试文件，含 52 项 NLP 回归）、前端 53 项 Vitest。
- **阶段 3 交付材料已产出**：`deliverables/`（作品简介、技术文档、答辩 PPT、演示视频分镜脚本、安全自评、部署说明、测试复现）；演示视频待人工录制。
- 下一步：**阶段 2.5（人工体验，推迟，后续重新进行）**；生产化剩余项：幂等/nonce TTL 清理、按用户熔断、OS 级沙箱、真实身份认证与 MFA、真实 IM 平台接入。详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

## 仓库与开发位置

| 项 | 值 |
|---|---|
| 产品主线仓库 | <https://github.com/LQZ5885/aegisbank>（Public / MIT / 默认分支 `main`） |
| 开发主线目录 | WSL Ubuntu 24.04 ext4：`/home/lqz5885/aegisbank/dev/aegisbank` |
| 展示与备份 | Windows `D:\开发交流\mia03-ether\aegisbank智能体`（历史副本，**已冻结，不再开发**） |
| 归档分支 | `archive/upstream-plan-provenance`（历史上游 PR 材料，只读） |

不要在 Windows 历史副本上继续开发；需要展示时从 Linux 主线单向复制。

## 不可破坏的架构约束

- 所有工具调用必须经过 `backend/aegisbank_api/gateway.py`，并统一经 `backend/aegisbank_api/executor.py` 的 `ToolExecutor` 与 `ExecutionGuard` 链执行；禁止在 API 或工具内部绕过权限判断，禁止直接调用 `tool.execute`。
- 新工具必须继承 `BaseTool` 并声明：风险等级、最小权限、输入/输出 schema；有副作用的工具还必须声明 `compensable / compensation_tool` 并登记补偿规格（或明确声明不可逆）。
- **补偿/回滚必须经网关与审计**：反向工具执行前必须重新做权限、角色、注入与动态风险复检；`compensation_executed / compensation_failed / compensation_blocked` 必须写入 SHA-256 审计链，不得直接调用反向工具绕过。
- **角色能力校验必须走 `AuthzService`**：`tool:execute / permission:manage / audit:read / ops:manage / trust:inspect` 是唯一能力口径；禁止在扩展或前端硬编码角色判断；`X-Aegis-Role` 仅用于本地演示，不是认证。
- **沙箱守卫默认开启**：不得移除或绕过 `SandboxGuard`；新增执行路径必须经过 `ToolExecutor`，沙箱拒绝必须先写审计再抛错。
- 动态风险引擎只能保持或上调工具基线风险，**任何模型输出都不得降低风险等级**。
- 审计日志必须包含：触发时间、原始指令、DAG 路径、工具入参、执行结果、用户确认状态，并保持 SHA-256 哈希链；证据以 `source / verified / verification_kind` 分层写入。
- LLM 只生成计划/草稿，不得直接执行工具、决定权限、跳过确认或编造金融结果；模型输出必须通过字段白名单与冲突校验。
- 黄色/红色操作确认后，执行前必须复核 `ActionEnvelope`（`plan_hash`、`arguments_hash`、风险等级、权限、`nonce`、过期时间），不一致返回 `409` 且不得执行。
- 幂等：带同一 `Idempotency-Key` 的重复请求必须返回首次结果，不得产生第二笔待确认动作或第二次扣款。
- 服务未就绪（`GET /api/health/ready` 非 `ready`）时，写操作必须 fail closed 返回 `503`，不得伪装成功。
- 前端只通过 `/api` 调用后端，不内嵌业务权限判断；服务未就绪时必须禁用写操作（fail closed）。
- 新增业务场景必须遵守 `backend/aegisbank_api/scenarios/README.md` 的自动发现契约（`NAME / SCHEMA_SQL / seed / tools / intents / risk_rules / router / start_background / stop_background`），不得修改核心装配文件。
- 新增 2A 横切能力必须遵守 `backend/aegisbank_api/extensions/README.md` 契约（`NAME / SCHEMA_SQL / seed / activate / tools / router / start_background / stop_background`），不得修改核心装配文件；写操作必须走工具节点 + 网关 + 审计。
- 禁止提交真实银行凭证、客户数据或 `.env`；演示 OTP `246810` 与模拟生物识别 token `FACE-888888` 只能用于本地开发。

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
  - `planning/`：Planner 契约、规则/LLM 实现、Plan Compiler 与模型候选校验
  - `trust/`：ActionEnvelope、幂等、状态机、证据、readiness、熔断、角色、MFA、暂停、沙箱
  - `scenarios/`：5 个可自动发现的业务场景模块（26 个场景工具）与模块契约
  - `extensions/`：2A 横切能力自动发现模块（authz / breaker / compensation / im / mfa / sandbox）
  - `channels/`：IM / CLI / webhook 渠道适配层
  - `executor.py` / `compensation.py`：统一执行链与补偿规格注册表
  - `tools/finance.py`：10 个核心银行工具与 Manifest
- `backend/tests/`：API 闭环、Planner、信任层、六场景与 2A 测试（17 个测试文件，252 条）
- `frontend/src/`：银行概览、六场景面板、任务控制台、权限控制台、2A 能力、运维面板、操作审计（7 页）
- `deliverables/`：阶段 3 参赛交付包（简介 / 技术文档 / 答辩 PPT / 演示视频脚本 / 安全自评 / 部署说明 / 测试复现）
- `scripts/`：依赖安装、开发启动、lint/build/test/smoke
- `docs/`：总规划、架构、安全边界、路线图、Dogfooding、参考资料

## 文档纪律

- 行为变更必须同步更新对应文档（README / ROADMAP / SECURITY / MASTER-PLAN / ARCHITECTURE / BANKING-DOMAIN）。
- 阶段性结论写入 `docs/MASTER-PLAN.md` 和 `docs/ROADMAP.md`，不要只留在对话里。
- 对外材料（README、产品介绍页、截图）必须反映当前真实功能，不得把“计划中”写成“已完成”。
- 文档中的工具数、测试数、接口数必须与代码/测试输出一致；不确定时不要写具体数字。
