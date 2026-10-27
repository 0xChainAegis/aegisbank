# AegisBank 团队工程约定

组织仓库的 main 为共同集成版本，保留原作者和六模块分类的 Git 历史。不要在分类目录与生成目录分别维护两份代码。

## 源码位置与运行工程

- `fronted/frontend/`：前端唯一修改入口，名称沿用队友已提交的 `fronted`。
- `backend/backend/`：FastAPI 装配、数据库和 Mock Bank Core；`backend/scripts/` 为运行与验证脚本。
- `agent/backend/`：网关、调度、信任、MFA、补偿和审计。
- `NLP/backend/`：金额解析、规则/LLM Planner、语义安全与受限澄清。
- `skills/backend/`：银行工具与场景模块。
- `plans/backend/`：计划契约与编译器。
- 根 `docs/` 和 `deliverables/` 是团队阅读、验收和参赛材料入口；六包内的旧文档保留历史背景。

运行 `python3 scripts/assemble.py` 将六个目录组装到 `.runtime/`。该目录不提交；开发只改上述源目录，再重新组装。组装不得覆盖用户运行数据库、依赖环境或未由生成清单管理的文件。

## 不可破坏的约束

所有金融结果来自确定性的 Mock Bank Core，不连接真实银行或支付网络。所有工具和补偿都经统一网关、风险复检、ToolExecutor、SandboxGuard 与审计。模型只生成候选计划，不决定授权、执行工具或编造结果；风险只能保持或上调。

黄色/红色确认绑定计划、参数、风险、权限、nonce 与有效期。执行前必须重新核验；幂等重试保留原键；结果未知不得自动重试或假定资金未变。服务未 ready 时写入 fail closed。角色能力由服务端 AuthzService 给出，前端不维护另一套授权矩阵。

NLP P0 与 P1 有界语义模块已落地；原定开放表达泛化验收仍待完成，具体状态见 `docs/NLP-P1-2026-10-27.md` 与 `docs/NLP-BACKLOG.md`。不把通用上下文、任意组合、真实 MFA、OS 隔离或模型效果目标准确率写成已实现。

## 协作与验证

前端负责人维护 `fronted/`；后端与 NLP 负责人维护其余业务包。改目录、接口与共享类型前先对齐，独立分支经 PR 集成；AI 生成变更同样由负责人验证。图片必须随文档提交并验证实际路径。

组装后在 `.runtime/backend` 使用冻结 uv 锁依赖、ruff、pytest 和场景脚本，在 `.runtime/frontend` 使用冻结 pnpm 锁依赖、Vitest 与生产构建。组装器自身使用根 `tests/` 的独立测试。具体命令由根 README 与 `.github/workflows/ci.yml` 定义。

不提交真实 `.env`、凭证、客户数据、运行数据库或依赖目录。保留 MIT 原作者声明。行为改变同步文档，测试数字必须来自实际输出；历史快照明确标记，未运行的作者机器专用 DSH 门禁不得宣称通过。

## 作者 Linux 检出的 DSH 门禁

本机检出为 `/home/lqz5885/aegisbank/dev/chainaegis`，Windows 历史副本冻结。`bash scripts/check.sh lint|build|test|scenarios` 在统一 `.runtime` 流程中安装冻结依赖并检查；test 同时覆盖根组装器测试，lint 包含 API 契约核验。本机提交继续使用 `/mnt/d/开发交流/mia03-ether/.dsh-workflow/scripts/gate.ps1` 和 `checkpoint.ps1`，`-Repo` 指向该检出。不得在门禁通过后修改源文件而沿用旧结论；Lead 综合自审的提交尾注保留 `Verifier: self`。
