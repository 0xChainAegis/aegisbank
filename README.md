# AegisBank

2026 深圳国际金融科技大赛参赛项目：覆盖六类银行场景的可信 AI 智能体，支持风险分级、人工确认、演示 MFA 与可追溯审计。全部使用模拟数据。

本仓库按文件职责保留 **fronted、backend、agent、NLP、plans、skills** 六个板块，存放解压后的源码，不上传 ZIP。

| 板块 | 原仓库文件数 | 内容与入口 |
|---|---:|---|
| [fronted](fronted/) | 34 | React/TypeScript 页面、组件、API 客户端与样式；[前端源码](fronted/frontend/src/) |
| [backend](backend/) | 19 | FastAPI 入口、配置、数据库、Mock Bank Core、依赖与启动脚本；[后端基础](backend/backend/aegisbank_api/) |
| [agent](agent/) | 30 | DAG 调度、权限网关、风险、执行守卫、审计、补偿、信任层与渠道；[智能体源码](agent/backend/aegisbank_api/) |
| [NLP](NLP/) | 8 | 规则/LLM Planner、意图识别、金额解析、安全校验和澄清续问；[语言解析](NLP/backend/aegisbank_api/planning/) |
| [plans](plans/) | 9 | 计划契约、确定性编译器、总规划、路线图与架构；[项目规划](plans/docs/) |
| [skills](skills/) | 12 | 工具 SDK、核心银行工具及业务场景；[业务技能](skills/backend/aegisbank_api/) |

共 **112 个原仓库文件**，每个文件只归属一个板块；另附包说明、MIT 许可及哈希清单。`fronted` 按分类要求保留此拼写，内部原始目录仍为 `frontend`。`skills` 指银行业务工具能力，不是独立的 Codex SKILL.md 插件包。

## 目录与依赖

每个板块内部保留原仓库相对路径，例如：

```text
fronted/frontend/src/
backend/backend/aegisbank_api/
agent/backend/aegisbank_api/
NLP/backend/aegisbank_api/planning/
plans/backend/aegisbank_api/planning/
skills/backend/aegisbank_api/scenarios/
```

这是按职责组织的源码分类仓库，六个板块存在依赖，不能单独运行。调用链为：前端 → API → 语言解析/计划生成 → 计划编译 → 风控/网关/调度 → 业务工具 → Mock Bank Core。场景中的意图规则与业务工具保持在同一源文件，2A 横切扩展整体归入 agent。

如需运行，请将六个板块目录中的内容复制、合并到仓库外一个新的空目录，保持 `backend/`、`frontend/`、`scripts/` 等原始路径，再执行：

```bash
bash scripts/bootstrap.sh
bash scripts/dev.sh
```

`_PACKAGE/` 是打包元数据。依赖要求与运行边界见 [原项目说明](plans/README.md)；原文使用原仓库相对链接，合并后使用，部分被排除的附件链接不适用于本分类仓库。

## 来源与范围

- 来源：[LQZ5885/aegisbank](https://github.com/LQZ5885/aegisbank)，提交 [`654c986`](https://github.com/LQZ5885/aegisbank/commit/654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec)，整理日期 2026-10-26。
- 原始源码与配置均原样保留；[文件清单](文件清单.csv) 记录分类、原路径、大小及 SHA-256；各板块 `_PACKAGE/<板块>/MANIFEST.json` 提供对应明细。
- 排除测试用例、夹具、测试脚本、测试复现材料，以及历史记录、归档、参考资料、展示附件等非核心内容；逐文件理由见 [排除清单](排除清单.csv)。不包含依赖目录、缓存、构建产物、运行数据库、实际 `.env` 或凭据。
- 保留仍被生产调用链引用的兼容模块与演示功能；不因名称含 legacy 就将其误判为作废。
- 为保证源码一致，依赖清单中的测试依赖/命令、现行文档中的阶段历史与测试描述未删除；本仓库不包含测试文件。

金融结果均为确定性模拟数据；固定 OTP、模拟生物识别和演示角色头仅用于本地演示。项目采用 [MIT License](LICENSE)。
