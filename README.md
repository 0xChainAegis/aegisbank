# AegisBank

**用自然语言办理模拟银行业务，每一步都有计划、确认与审计。**

2026 深圳国际金融科技大赛参赛原型，由 0xChainAegis 团队维护。

[六类场景](#六类场景) · [安全设计](#安全设计) · [快速开始](#快速开始) · [团队协作](#团队协作) · [参赛材料](#参赛材料)

![银行助手：需求输入、业务示例与按需展开的技术信息](docs/screenshots/assistant-workspace-20261027.jpg)

![转账确认：真实账户、金额、剩余时间和待确认状态](docs/screenshots/assistant-confirmation-20261027.jpg)

界面改造、真实联调结果及待后端核实的统计口径见 [10月27日银行助手记录](docs/FRONTEND-PRODUCT-2026-10-27.md)。

> **演示边界**：账户、卡片、账单、理财和交易均来自确定性的 Mock Bank Core，不连接真实银行、不产生真实资金变动。固定 OTP、模拟生物识别和角色请求头用于本地展示；理财数据与收益均为模拟。

## 它如何工作

用户表达需求，Agent 生成结构化计划，系统根据权限与风险决定执行方式。

```text
自然语言 → Planner → Plan Compiler → 动态风险 → 统一权限网关
         → 分级确认 / 演示 MFA → ToolExecutor → Mock Bank Core
         → 执行回执 + 证据分层 + SHA-256 审计哈希链
```

例如“分析我的账单并取消异常订阅”会生成两步 DAG。任务包含状态变更，因此整条任务先等待确认，确认后再依次执行账单查询与订阅取消。后续节点引用前序结果，避免猜测操作对象。

## 六类场景

- **智能转账**：按联系人、别名或手机号转账，支持 AA 拆分、定时与周期任务。
- **账单分析**：月度与年度报告、分类统计、异常交易及订阅涨价识别。
- **理财操作**：模拟产品与持仓查询、风险测评、申购和赎回。
- **卡片管理**：额度、每日交易限额、还款日、挂失/解挂及虚拟卡申请。
- **订阅 / 代扣**：扣费识别、续费提醒，以及确认后取消订阅。
- **跨场景联动**：账单分析后取消异常订阅，或查生日、锁预算、预约鲜花与蛋糕。

支持的示例指令：

```text
分析我的本月账单
向 ACC-2002 转账 880 元
解挂卡片 CARD-8821
买 1000 元稳健短债A
分析我的账单并取消异常订阅
帮我准备下个月妈妈的生日，预算 1000 元
```

六场景指已验证的代表链路，通用指代、自由组合和对话纠错仍有待完善。歧义金额与不支持的条件请求会转为澄清，详见 [NLP 现状](docs/NLP-ASSESSMENT-AND-PLAN-2026-10-25.md) 与 [NLP 待办](docs/NLP-BACKLOG.md)。

## 安全设计

- **绿色自动执行**：余额、账单、持仓等只读查询。
- **黄色明确确认**：小额转账、取消订阅及部分账户设置。
- **红色确认 + 演示 MFA**：累计风险升级的转账、理财申购、挂失/解挂等操作。

风险由确定性规则判断，只能保持或上调。转账日累计包含本次金额，超过 1,000 元会升级为红色。

Planner 只生成候选计划。执行前统一校验 Schema、依赖、工具授权、角色能力与注入风险；确认绑定计划、参数、nonce 和有效期。幂等机制防止重复执行，失败可进入补偿、暂停或 `UNKNOWN` 人工对账流程。服务未就绪时禁用写操作。

![刷新后恢复待确认任务：向服务端核对计划后等待用户决定](docs/screenshots/confirmation-recovery-2026-10-25.jpg)

![操作审计：人工确认、工具执行与证据链记录](docs/screenshots/audit-verified-2026-10-25.jpg)

SHA-256 哈希链用于检测日志改动，不等同于数字签名或独立存证。当前没有生产身份认证、真实 MFA、真实 IM 平台接入或 OS 级沙箱。详见 [安全说明](docs/SECURITY.md) 与 [系统架构](docs/ARCHITECTURE.md)。

## 快速开始

**后端需要 Linux 或 WSL**，数据库锁使用 `fcntl`，原生 Windows Python 不能直接运行。安装 Python 3.11+、`uv`、`pnpm`，Node.js 满足 `^22.22.2 || ^24.15.0 || >=26.0.0`。

本仓库保留六个职责包，通过组装脚本生成可运行目录：

```bash
git clone https://github.com/0xChainAegis/aegisbank.git
cd aegisbank
python3 scripts/assemble.py
cd .runtime
bash scripts/bootstrap.sh
bash scripts/dev.sh
```

打开 [银行助手](http://127.0.0.1:5173/#/console)、[API 文档](http://127.0.0.1:8000/docs) 或 [就绪检查](http://127.0.0.1:8000/api/health/ready)。完整的组装、启动与接口请求/返回示例见 [API 交接文档](docs/API-HANDOFF.md)。默认规则 Planner 无需模型密钥；可选 LLM 配置见组装后的 `.runtime/backend/.env.example`，需要覆盖时复制为同目录 `.env`。演示 OTP 为 `246810`。

首次试用可从首页的账单、880 元转账、卡片挂失三个入口填入指令。入口仅预填，提交和风险确认仍需用户操作；同机演示准备、新模拟库及固定任务卡见 [前端联调与试用交接](docs/DAY1-FRONTEND-HANDOFF-2026-10-26.md)。`localhost` 地址仅用于运行服务的电脑，异地试用由开发者提供可访问环境或共享屏幕。

建议先查询本月账单，再发起 880 元转账并核对确认内容，最后查看审计哈希链。写操作会改变本地模拟状态，重复演示前应核对余额、累计转账和订阅状态。

## 团队协作

**源码在六个职责包中编辑，`.runtime/` 是生成目录，不作为开发主线。** 每次改动后重新组装，再运行测试与演示。

- [`fronted/`](fronted/)：React / TypeScript 前端，原始代码位于 `fronted/frontend/`；目录名沿用团队约定。
- [`backend/`](backend/)：FastAPI 入口、数据库、Mock Bank Core、依赖与运行脚本。
- [`agent/`](agent/)：DAG 调度、权限网关、执行器、风险、审计与信任层。
- [`NLP/`](NLP/)：意图识别、金额解析、规则/LLM Planner 与受限澄清。
- [`skills/`](skills/)：银行工具 SDK、工具注册及业务场景技能。
- [`plans/`](plans/)：计划契约、编译器及规划资料，涉及运行代码，不能作为纯文档删除。

各自开分支，通过 PR 合入 `main`。接口变更先对齐输入/输出，不同时直接改别人负责的文件；原库与组织库只保留一条开发主线。AI 生成的代码与材料同样由对应负责人验证，协作约定见 [贡献指南](CONTRIBUTING.md) 与 [团队工作流](docs/TEAM-WORKFLOW.md)。

## 验证记录

应用验证基线（2026-10-25）：**后端 pytest 252 项、前端 Vitest 73 项、六场景回归 29/29、实际前端入口 15/15**。范围与环境见 [前端修复及验收记录](docs/FRONTEND-REPAIR-2026-10-25.md)。

职责包组装测试单独计数。CI 先组装 `.runtime/`，再验证应用；整合后的结果以 [GitHub Actions](https://github.com/0xChainAegis/aegisbank/actions) 为准。测试覆盖已知用例，不代表生产安全认证或任意自然语言均能成功执行。

## 参赛材料

- [本轮提交材料索引](deliverables/current/README.md)：技术文档、安全自评的 Word / PDF，以及现有 14 页答辩 PPT。
- [文档索引](docs/README.md)：架构、业务场景、安全、NLP、验收与协作说明。
- [真实界面截图](docs/screenshots/README.md)：本轮验证图与历史页面记录。

演示视频成片和正式答辩时长核验仍待完成。提交截止为 **2026-11-02 18:00（中国标准时间）**。

## 来源与许可

原始银行原型来自 [LQZ5885/aegisbank](https://github.com/LQZ5885/aegisbank)，由组织仓库继续协作，保留原作者版权声明。AegisAgent 的设计参考范围见 [来源说明](docs/UPSTREAM-NOTES.md)，第三方资料见 [参考资料索引](docs/reference/README.md)。本项目采用 [MIT License](LICENSE)。

欢迎通过 [Issue](https://github.com/0xChainAegis/aegisbank/issues) 提供复现步骤，或通过 [Pull Request](https://github.com/0xChainAegis/aegisbank/pulls) 改进项目。
