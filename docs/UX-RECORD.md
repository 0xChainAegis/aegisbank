# AegisBank 前端 UX 问题与修复方案报告

> **阶段**：阶段 2.5（人工体验 / Dogfooding）第一轮
> **版本**：v1.0 · 2026-10-23
> **审计基线**：`702c27f`（2026-10-23，WSL 主线 `/home/lqz5885/aegisbank/dev/aegisbank`）
> **文档性质**：问题记录 + 修复方案；**本报告不含代码改动**
> **关联文档**：[UX-DOGFOODING.md](UX-DOGFOODING.md) · [ROADMAP.md](ROADMAP.md) §2.5 · [MASTER-PLAN.md](MASTER-PLAN.md)

---

## 1. 结论摘要

人工初步测试反馈的“前端交互界面问题很大”，经复现后可以归为三类，而不是视觉风格问题：

1. **任务闭环不可见**：核心路径（发起 → 看风险 → 确认 → 回执 → 审计）被 7 个平级页面切碎，首屏先看到的是营销区而不是输入框；提交后页面不滚动、无提示，回执出现在 1800px 之下。
2. **状态不可恢复**：待确认动作、回执、步骤日志只存在于 `App.tsx` 的 `useState`；刷新即丢失，后端动作仍挂在 `AWAITING_CONFIRMATION`，用户既不能确认也不能拒绝。确认遇到 409/422 后弹窗还关不掉。
3. **界面在说实现语言**：确认弹窗直接渲染 `${steps.step-1...}` 占位符与原始 JSON，出现 `EVIDENCE LAYERS`、`DAG 节点`、`GET /api/mfa/providers`、`plan_hash`；执行回执是 5000+ 字的调试面板。

另有两条会直接影响评委观感的风险：**移动端整页横向溢出**（390px 视口 → 文档 594px），以及**演示数据被消费后无法重跑**（人工测试的 3 次任务中 2 次 `rolled_back`，因为上一轮已取消的订阅导致占位符解析为 null）。

**规模**：共 36 项（P0 × 7、P1 × 17、P2 × 10、P3 × 2），按“止血 → 闭环 → 状态与契约 → 收尾”分四批，预计 **5–7 人日**（不含后端配套项），其中第一批约 **0.5–1 人日**即可明显扭转观感。

---

## 2. 审计范围与方法

### 2.1 审计对象

| 项 | 值 |
|---|---|
| 前端规模 | `frontend/src` 26 个文件 / 8703 行（含 3 个 Vitest 测试文件） |
| 页面 | 7 个：银行概览、六场景面板、任务控制台、权限控制台、2A 能力、运维面板、操作审计 |
| 状态管理 | 全部集中在 `frontend/src/App.tsx`（610 行）的 `useState`；无路由库、无状态库 |
| 样式 | `frontend/src/styles.css` 963 行，三套重复媒体查询（423 / 712 / 937 行） |
| 后端契约 | FastAPI 49 个接口；幂等键、readiness、409 / 422 / 503 语义已在后端实现 |

### 2.2 证据来源

1. **人工测试复盘**：`backend/data/dogfood.db`（2026-10-23 16:23–16:26 的人工操作）——`pending_actions` 3 条（completed ×1、rolled_back ×2），`audit_log` 25 条。
2. **静态审计**：逐文件阅读 `App.tsx`、12 个组件、`api.ts`、`viewModel.ts`、`twoA.ts`、`roles.ts`、`styles.css`，对照 `UX-DOGFOODING.md` 的验收项与后端契约。
3. **运行时量测**：无头 Chromium 经 CDP 驱动真实 dev server（`vite:5173` + `uvicorn:8000`），在 1440×900 / 390×844 / 360×844 三种视口下测量几何、执行真实交互、采集 console 与网络事件。

### 2.3 复现方式

```bash
# 1) 干净数据启动
cd /home/lqz5885/aegisbank/dev/aegisbank
bash scripts/seed-demo.sh /tmp/ux-audit.db
cd backend && AEGIS_DATABASE_PATH=/tmp/ux-audit.db uv run uvicorn aegisbank_api.main:app --host 0.0.0.0 --port 8000
# 2) 另开终端
cd frontend && pnpm dev
# 3) 打开 http://127.0.0.1:5173
```

人工可复现的关键点：控制台首屏滚动位置、提交后是否自动滚动、弹窗内连按两次 Tab、弹窗打开时刷新页面、390px 视口是否横向滚动、第二次执行“分析并取消异常订阅”。

### 2.4 局限

- 运行时只覆盖 Chromium 无头模式；未做 Safari / Firefox，未接屏幕阅读器（对比度为计算值）。
- 未做真实外部用户测试（当前 n=1 开发者），结论偏工程视角；建议按 `UX-DOGFOODING.md` 补一轮外部试用。
- 个别 P1 项需要后端小改（角色复检、readiness 覆盖、演示重置、pending 列表），本报告只给方案，不改代码。

---

## 3. 问题总览

| 类别 | 条数 | P0 | P1 | P2 | P3 |
|---|---:|---:|---:|---:|---:|
| A 信息架构与首屏 | 5 | 1 | 3 | 1 | 0 |
| B 任务闭环与反馈 | 4 | 1 | 2 | 1 | 0 |
| C 确认与回执 | 7 | 3 | 3 | 1 | 0 |
| D 状态与契约 | 10 | 1 | 4 | 4 | 1 |
| E 可用性与无障碍 | 7 | 1 | 3 | 3 | 0 |
| F 演示与文档一致性 | 3 | 0 | 2 | 0 | 1 |
| **合计** | **36** | **7** | **17** | **10** | **2** |

> 严重度定义：**P0** 阻断演示或使用户无法完成任务；**P1** 严重损害理解或效率；**P2** 明显影响体验；**P3** 打磨项。

---

## 4. 缺陷清单

### A. 信息架构与首屏

#### UX-01 [P0] 任务控制台首屏看不到输入框

- **现象**：1440×900 下页面先渲染 360px 高的 hero 与三个工程指标；输入框 `top=823`、提交按钮 `bottom=914`，超出 900px 视口；390×844 下输入框在 `y≈1100`。
- **证据**：`frontend/src/components/TaskConsolePage.tsx:262-279`（hero）、`:281-297`（指标）、`:299-336`（指令卡）；运行时量测（附录 A）。
- **影响**：首次使用者找不到入口，演示开场需要先滚动。
- **修复**：指令卡移到 hero 之前；hero 压缩为一行标题 + 一句副标题（≤120px）；指标与流程条下沉到回执之后。
- **验收**：1440×900 与 390×844 首屏均可直接看到 textarea 与提交按钮。

#### UX-02 [P1] 导航命名、序号与职责互相干扰

- **现象**：7 个平级页面带 `01–07` 序号（暗示固定顺序）；02“六场景面板”标题为只读视图（`SIX SCENARIOS · READ ONLY + TIME TRAVEL`），却与 03 的“三场景快捷操作”（`:341-343`）共用“场景”一词；02、03 的导航副标题只列了 3 项。
- **证据**：`frontend/src/App.tsx:53-61`；`frontend/src/components/TaskConsolePage.tsx:341-343`；`frontend/src/components/ScenariosPage.tsx:272`。
- **影响**：用户不知道“场景”该去 02 还是 03；序号被误读为操作步骤。
- **修复**：去掉序号；02 改名“场景数据（只读）”、03 改名“任务控制台（发起任务）”；导航按“任务 / 治理 / 数据”分组。
- **验收**：新用户在不看文档的情况下能说出每页职责，且能选中正确入口。

#### UX-03 [P1] 无 URL 路由与深链，刷新回到概览

- **现象**：7 个页面都挂在 `/`；地址栏始终是 `http://127.0.0.1:5173/`；刷新后回到 01 银行概览，且弹窗消失；浏览器后退无效。
- **证据**：`frontend/src/App.tsx:51`、`:86`（`useState<Page>('overview')`）；运行时实测 URL 恒为 `/`。
- **影响**：无法把某一页发给评委；刷新即丢掉当前上下文；演示路径不可编排。
- **修复**：约 30 行的 hash 路由（`#/console`、`#/audit`），导航改用 `<a href>`；页面标题同步更新，深链依赖（UX-17）一并解决。
- **验收**：任意页可复制 URL 直达；刷新后停留原页；后退/前进可用。

#### UX-04 [P1] 首次使用与演示路径缺失

- **现象**：全站唯一“下一步”钩子是概览页的异常订阅 callout；没有演示路径条、没有空态引导；README 的演示步骤是唯一导航。
- **证据**：`frontend/src/App.tsx:86`（默认页即概览，无引导层）；`frontend/src/components/BankOverviewPage.tsx:76-92`（唯一入口按钮）。
- **影响**：评委 3 分钟内难以走到确认与审计；用户不知道可以做什么。
- **修复**：顶部加三步演示路径 chip（分析账单 → 小额转账 → 查看审计与哈希链），点击即填指令并跳转；空态提供同款入口。
- **验收**：不读 README 的试用者能在 3 分钟内完成一次黄色确认并找到审计记录。

#### UX-05 [P2] 页面数据重复、02 页过长

- **现象**：银行概览与 02 都展示订阅/卡片；02 桌面端文档高 4027px，首屏是理财表格，账单与自动化在很下方。
- **证据**：运行时时量测 `scrollHeight=4027`；`frontend/src/components/ScenariosPage.tsx`（6 个 Panel）。
- **影响**：信息重复造成“哪个才是准的”疑问；长页难以定位。
- **修复**：概览只保留摘要并给“查看全部”深链；02 分组锚点导航；重复区块标注数据来源。
- **验收**：两类页面无重复展示冲突；02 可在 2 次点击内到达账单与自动化分组。

### B. 任务闭环与反馈

#### UX-06 [P0] 提交后没有任何可见反馈

- **现象**：提交绿色查询后，回执卡 `top=1822`、`scrollY=0`，页面不滚动、无 toast、无 aria-live；唯一变化是按钮文案从“处理中…”变回“交给 Agent”。
- **证据**：`frontend/src/components/TaskConsolePage.tsx:406`（回执卡在表单之后）；`frontend/src/App.tsx:306-332`（无滚动/提示逻辑）；运行时量测（附录 A）。
- **影响**：用户认为“点了没反应”，重复提交（叠加 UX-18 会真的产生两个待确认动作）。
- **修复**：提交后 `resultRef.scrollIntoView({block:'start'})` + 顶部 toast；失败在同一位置提示；回执加 `aria-live="polite"`。
- **验收**：提交后 1 秒内，视口内出现结果或明确的进行中状态。

#### UX-07 [P1] 长任务无进度与阶段提示

- **现象**：规划、权限校验、风险判定、等待确认全部只用一个按钮文案“处理中…”表达；无可访问的进度语义。
- **证据**：`frontend/src/App.tsx:307`（`busy`）；`frontend/src/components/TaskConsolePage.tsx:328-335`。
- **影响**：慢请求（LLM 模式或冷启动）时用户不知道系统在做什么，容易重复点击或刷新。
- **修复**：指令区下方加 `role="status"` 的阶段行（解析意图 → 校验权限 → 风险判定 → 等待确认），完成后折叠为一条记录。
- **验收**：任一任务耗时超过 2 秒时，用户能看到当前阶段。

#### UX-08 [P1] 快捷动作静默覆盖已输入文本并立即执行

- **现象**：在指令框输入“查询我的账户余额”后点击“分析本月账单”，输入被替换为新指令并直接执行，没有确认或撤销。
- **证据**：`frontend/src/components/TaskConsolePage.tsx:250-258`（`trigger()` 先 `setInstruction`，再 `onExecute`）；运行时实测复现。
- **影响**：用户输入被丢弃，执行了非预期操作；与“我不小心点错”的直觉冲突。
- **修复**：快捷动作改为“填入指令、不自动执行”（二次点击提交），或执行前检测未提交文本并提示覆盖。
- **验收**：点击快捷动作不会静默丢弃用户已输入内容。

#### UX-09 [P2] 失败后保留上一轮回执

- **现象**：新任务在 503/网络/400 失败时，页面仍显示上一次的“执行回执”和“查看信任详情”，看起来像本轮结果。
- **证据**：`frontend/src/App.tsx:306-331`（开始时只清 `trustAction`，不清 `lastRun` / `lastActionId`）；`frontend/src/components/TaskConsolePage.tsx:406-435`。
- **影响**：用户误判本轮结果，演示时尤其危险。
- **修复**：提交开始时清空或标记旧回执；失败时显示“本次提交失败”，并明确列出上一次结果的时间戳。
- **验收**：任何失败后，回执区域不会把上一轮结果显示为本轮结果。

### C. 确认与回执

#### UX-10 [P0] 确认弹窗泄露未解析占位符与原始 JSON

- **现象**：“即将执行的 DAG 节点”直接渲染 `{"subscription_id":"${steps.step-1.data.suspicious_subscription_id}"}`；转账弹窗渲染 `{"from_account":"ACC-1001","to_account":"ACC-2002","amount_cny":6800,...}`；用户看不出“取消哪个订阅、扣多少钱”。
- **证据**：`frontend/src/components/ConfirmationModal.tsx:96-113`（`JSON.stringify(step.arguments)`）；运行时 dialogText 实测。
- **影响**：确认动作失去意义，风险提示无法被非开发者理解。
- **修复**：按工具类型生成人话摘要（如“取消「AI 工具订阅」（SUB-3002），每月 ¥199，下次扣款 10-29”）；原始参数收进“技术详情”折叠；无法解析的占位符必须显式标注“执行时确定”。
- **验收**：非开发者能用自己的话复述“将要发生什么”。

#### UX-11 [P0] 弹窗不可退出、焦点逃逸、未就绪时“拒绝”也被禁用

- **现象**：无 ESC、无关闭按钮、遮罩不可点；实测 Tab 第 2 次焦点即跳到顶栏 `USER`；`writesBlocked` 时“拒绝执行”与“确认执行”都被禁用，应用被锁死，只能刷新（而刷新会丢状态，见 UX-17）。
- **证据**：`frontend/src/components/ConfirmationModal.tsx:62-63`（无关闭/Esc）、`:197-212`（两个按钮均受 `writesBlocked` 约束）；运行时 Tab 序列实测。
- **影响**：用户无法脱身；键盘用户可能误操作背景按钮。
- **修复**：补 ESC、右上角关闭与“稍后处理”；实现 focus trap（首尾循环）并在关闭后还原焦点；未就绪时至少保留“取消/稍后处理”，确认按钮禁用并说明原因；打开时锁定背景滚动。
- **验收**：仅用键盘可完整确认或退出；弹窗打开时 Tab 不会离开弹窗。

#### UX-12 [P0] 409 / 422 终态错误后弹窗死锁，回执仍显示“等待确认”

- **现象**：确认过期或计划变更时后端返回 409（并已把动作置为 `blocked`），前端只在弹窗里显示一条红字；重试得到 400“确认请求已处理”；弹窗关不掉，`RUN RESULT` 仍是“等待人工确认”。
- **证据**：`frontend/src/App.tsx:334-363`（仅成功分支 `setPending(null)`）；后端 `backend/aegisbank_api/scheduler.py:941-962`（409 前 `resolve_pending(...,"blocked")`）、`:1260-1261`（422 前置 `failed`）、`:900-901`（重复确认 400）；运行时与 TestClient 复现。
- **影响**：演示中一旦确认超时，页面进入不可恢复状态，只能刷新并丢失全部上下文。
- **修复**：按 `ApiError.status` / `code` 分支（详见 §6.4.3）：409 → 关闭弹窗 + 提示“需重新发起” + 刷新 trust/audit；422 → 失败回执；503/网络 → 保留弹窗可重试。
- **验收**：构造过期确认后，用户能在一个可见步骤内回到可继续状态。

#### UX-13 [P1] 术语与接口路径外泄

- **现象**：用户界面出现 `EVIDENCE LAYERS`、`即将执行的 DAG 节点`、`验证方式 · GET /api/mfa/providers`、`ActionEnvelope`、`plan_hash`、`幂等键`、`fail-closed`、`GET /api/trust/actions/{id}`、`POST /api/automation/run-due`、`/api/audit/verify`。
- **证据**：`frontend/src/components/ConfirmationModal.tsx:126`；`frontend/src/components/TaskConsolePage.tsx:617-618`；`frontend/src/components/StepJournalPanel.tsx:129`；`frontend/src/components/CapabilitiesPage.tsx:200`、`:249-250`；`frontend/src/components/ScenariosPage.tsx:850`、`:857`；`frontend/src/components/AuditPage.tsx:228`。
- **影响**：评委看到的是 API 文档；信任能力被表述为实现细节而非用户价值。
- **修复**：业务语言在外、技术证据在内；所有路径/哈希/状态码收进“技术详情”折叠（默认收起），保留可展开审计入口。
- **验收**：默认视图中不再出现英文事件码、接口路径与原始 JSON。

#### UX-14 [P1] 执行回执是调试面板

- **现象**：一次 6800 元转账后，回执包含 `RUN ID`、`plan_hash` 截断值、`simulated_success`、`daily_transfer_total_cny`、ISO 时间、原始入参 JSON、状态机/步骤日志/信任视图说明，正文 5000+ 字。
- **证据**：`frontend/src/components/TaskConsolePage.tsx:406-708`；运行时 afterApprove 文本实测。
- **影响**：用户找不到“转成功没有、余额变成多少、下一步做什么”。
- **修复**：三层信息结构（结论 / 关键事实 / 技术详情折叠），见 §6.4.4。
- **验收**：回执首屏（900px 内）能回答“是否成功、金额、对象、当前余额、去哪看审计”。

#### UX-15 [P1] 回执与审计、证据链断裂

- **现象**：回执只有“查看信任详情”和步骤日志，没有“查看本次审计记录”；审计页无法按 run/action 过滤；用户需自己记住 run id。
- **证据**：`frontend/src/components/TaskConsolePage.tsx:406-708`（无审计入口）；`frontend/src/App.tsx:575-586`（审计页无过滤参数）。
- **影响**：“执行 → 审计”这条信任链路在 UI 上是断的，正好削弱产品核心卖点。
- **修复**：回执加“在审计页查看本次记录”，跳转 07 并按 run_id / action_id 预过滤并高亮。
- **验收**：从回执一次点击到达对应审计条目。

#### UX-16 [P2] 过期无倒计时，演示 token 重复展示

- **现象**：只显示“有效期至 16:48:03”，无剩余时间；过期后点击才报错。MFA 演示 token 在同一区块出现两次（provider 卡片与输入框下方说明），且可直接读取。
- **证据**：`frontend/src/components/ConfirmationModal.tsx:69-71`、`:156-158`、`:170-185`。
- **影响**：用户不知道还剩多少时间；演示 token 反复出现削弱“二次校验”的可信感。
- **修复**：显示“剩余 mm:ss”，≤0 时禁用并给“重新发起”；token 改为“填入演示 token”按钮 + 一行说明。
- **验收**：过期前 30 秒有可见提示；token 只出现一次。

### D. 状态与契约

#### UX-17 [P0] 刷新 / 断线后待确认动作与回执全部丢失

- **现象**：刷新页面后回到概览，待确认弹窗、MFA token、回执、步骤日志全部消失；后端动作仍为 `AWAITING_CONFIRMATION`（5 分钟后过期）；重新发起会再建一笔待确认动作。
- **证据**：`frontend/src/App.tsx:108-120`（全部为内存 state）、`:221-228`（mount 只拉取只读数据）；后端 `backend/aegisbank_api/main.py` 无 pending 列表接口；运行时实测“弹窗中刷新 → 弹窗消失”。
- **影响**：任务无法续接；与“刷新不会重复执行”的承诺只对了一半（不重复但也不可恢复）。
- **修复**：前端 `sessionStorage` 存待确认快照 + `GET /api/trust/actions/{id}` + `GET /api/actions/{id}/journal` 恢复（详见 §6.4.2）；可选后端补 pending 列表接口。
- **验收**：弹窗打开时刷新，页面出现“你有一笔待确认操作”横幅，可继续确认或明确放弃。

#### UX-18 [P1] 幂等键完全未实现

- **现象**：`/api/agent/run` 与 `/api/confirmations/{id}` 均未带 `Idempotency-Key`；重复提交或超时重试会创建第二笔待确认动作（实测同一 body 连发两次 → 两个 action id）。
- **证据**：`frontend/src/api.ts:77-107`（request 无该 header）、`:172-193`；后端 `backend/aegisbank_api/main.py:285`、`:320` 已支持；`backend/aegisbank_api/trust/idempotency.py`。
- **影响**：与 `AGENTS.md` 的幂等约束不一致；演示中双击可能产生两个待确认任务。
- **修复**：`request()` 支持 `idempotencyKey`；每次逻辑提交生成 `crypto.randomUUID()` 并存入 ref，重试复用，终态清空。
- **验收**：双击提交仅产生一个待确认动作；重试复用同一 key。

#### UX-19 [P1] 错误码没有驱动状态机

- **现象**：`ApiError.status` / `code` 已解析但无消费者；所有错误都显示为一行红字，页面状态不迁移；503 后最多等 30 秒 readiness 轮询；FastAPI 422 的 detail 数组被 `JSON.stringify` 直出（如输入超 2000 字）。
- **证据**：`frontend/src/api.ts:52-107`（`detailMessage` 对数组直出）；`frontend/src/App.tsx:77-79`（只用 `message`）、`:356-359`（仅用正则猜 MFA）。
- **影响**：用户不知道错误能否重试、是否需要重新发起。
- **修复**：统一 `describeError()` 映射表（§6.4.3）；503/网络失败立即 `loadReadiness()`；422 数组转“字段 + 原因”。
- **验收**：409 / 422 / 503 / 403-MFA 分别触发不同的 UI 动作，且文案可被非开发者理解。

#### UX-20 [P1] 角色切换竞态；后端“拒绝”分支缺角色复检

- **现象**：红色转账规划中切到 operator/auditor，响应返回后弹窗以新角色出现；点击“拒绝执行”后端返回 200 `rejected`（实测），把一条用户动作标记为由非属主角色拒绝。
- **证据**：`frontend/src/App.tsx:259-274`（切换角色不清 pending）、`:406-419`（角色按钮不受 busy 约束）；后端 `backend/aegisbank_api/scheduler.py:964-1005`（拒绝分支）先于 `:1038-1050` 的权限/风险复检。
- **影响**：违反“auditor 只读、operator 不能操作银行动作”的角色语义；审计写入误导性记录。
- **修复**：前端切角色时若 pending 非空则只读化或先处理；后端拒绝分支补 `require_capability(role, 'tool:execute')` 并加测试。
- **验收**：非 user 角色无法以任何路径确认或拒绝他人动作。

#### UX-21 [P1] fail-closed 覆盖不全

- **现象**：readiness 非 ready 时任务/确认/时间快进已禁用，但权限开关（`PUT /api/permissions`）、沙箱演示、IM 发送、熔断解除仍可点击；后端 `PUT /api/permissions` 与 `POST /api/sandbox/demo/run` 未做 readiness 门禁。
- **证据**：`frontend/src/components/PermissionsPage.tsx:148-155`；`frontend/src/components/CapabilitiesPage.tsx:36-42`；后端 `backend/aegisbank_api/main.py:251-280`（无 `ensure_ready`）、`backend/aegisbank_api/extensions/sandbox.py:186-193`、`backend/aegisbank_api/extensions/im.py:169-174`（IM 有 readiness、无角色校验）。
- **影响**：与 `AGENTS.md` “未就绪写操作必须 fail closed”不一致；演示时可能出现“半禁用”状态。
- **修复**：抽 `useWriteGuard()` 统一组合 readiness / breaker / capabilities；后端补 readiness 与能力校验。
- **验收**：readiness 异常时所有写入口要么禁用，要么被后端 503 拒绝并给出原因。

#### UX-22 [P2] 数据新鲜度无统一策略

- **现象**：撤权、时间快进、沙箱/IM 写操作后，概览余额、今日累计转账、审计列表不刷新；断线恢复后 tools 为空导致快捷动作一直禁用，直到逐页手动刷新。
- **证据**：`frontend/src/App.tsx:221-228`（只 mount 拉取）、`:378-391`（撤权只刷新 tools）；`frontend/src/components/ScenariosPage.tsx:249-267`（时间快进只刷新本页）。
- **影响**：界面显示旧数据，风险判断与余额展示可能不一致。
- **修复**：App 暴露 `refreshAll()`，通过 `onDataChanged` 传给各页；readiness 从非 ready→ready 时自动触发一次全量刷新。
- **验收**：任一写操作完成后 1 秒内，概览、审计、熔断状态同步更新。

#### UX-23 [P2] UNKNOWN 状态没有对账入口

- **现象**：回执提示“请人工对账（reconciled）或回滚”，但前端没有 `reconcile` 调用，信任视图只读；UNKNOWN 永远停在 UNKNOWN。
- **证据**：`frontend/src/components/TaskConsolePage.tsx:437-457`；`frontend/src/api.ts` 无 reconcile 函数；后端已有 `POST /api/trust/actions/{id}/reconcile`（`backend/aegisbank_api/main.py:404`）。
- **影响**：README 承诺的对账能力在 UI 上不可达。
- **修复**：`api.ts` 增 `reconcileAction()`；按状态显示“对账为已解决 / 已回滚”按钮，成功后刷新 trust + audit。
- **验收**：UNKNOWN 任务可在 UI 内完成对账并写审计。

#### UX-24 [P2] 前端硬编码角色能力矩阵

- **现象**：`roles.ts` 自维护 `ROLE_CAPABILITIES`（与后端矩阵手抄同步），后端已有 `GET /api/authz/me` 却未使用。
- **证据**：`frontend/src/roles.ts:46-50`（能力矩阵）、`:63-99`（派生的角色判断）；`backend/aegisbank_api/extensions/authz.py:51`。
- **影响**：与 `AGENTS.md` “能力口径唯一走 AuthzService / 前端不内嵌业务权限判断”存在偏差；后端调整能力时前端会漂移。
- **修复**：切换角色时请求 `GET /api/authz/me` 缓存 capabilities；`roles.ts` 只保留展示文案。
- **验收**：前端不再有独立的能力常量；能力变化只需改后端。

#### UX-25 [P2] 审计链校验失败被显示成“待校验”

- **现象**：`/api/audit/verify` 请求本身失败（网络/500/403）时 `auditValid=null`，顶栏显示“审计链待校验”，与“尚未校验”同义；只有 `valid:false` 才显示异常。
- **证据**：`frontend/src/App.tsx:169-176`、`:436-438`；`frontend/src/components/AuditPage.tsx:79`。
- **影响**：用户会低估安全状态，演示时也无法解释“校验失败”。
- **修复**：三态 `unknown | valid | invalid`；请求失败归入异常并保留原始错误。
- **验收**：校验失败与未校验在视觉与文案上可区分。

#### UX-26 [P3] 月报/年报快速切换存在响应竞态

- **现象**：快速点“月报→年报”，先发的月报响应晚到会覆盖当前 tab 的数据。
- **证据**：`frontend/src/components/ScenariosPage.tsx:41-63`（`useResource` 无请求序号/取消）。
- **影响**：数据显示与所选周期不一致。
- **修复**：`useResource` 加请求序号（`id !== seq.current` 则丢弃），或 AbortController。
- **验收**：任意快速切换后，展示数据与当前选项一致。

### E. 可用性与无障碍

#### UX-27 [P0] 移动端整页横向溢出

- **现象**：390px / 360px 视口下文档宽度为 594px，整页左右滚动；侧栏与正文错位。根因是 1024 断点把 `.layout` 从 `minmax(0,1fr)` 退回 `1fr`，且 `.sidebar` / `nav` 未设 `min-width:0`，导航按钮 `white-space:nowrap` 把父级撑到 594px。
- **证据**：`frontend/src/styles.css:424`（`grid-template-columns: 1fr`）、`:425-427`；运行时实测（390 → 594，注入修复后 → 390）。
- **影响**：手机演示不可用；截图与对外材料受影响。
- **修复**：1024 断点改为 `grid-template-columns: minmax(0, 1fr)`，`.sidebar`、`.sidebar nav` 加 `min-width:0`（约 2 行）。
- **验收**：360 / 390 / 768 视口下 `document.documentElement.scrollWidth === innerWidth`。

#### UX-28 [P1] 字号过小、对比度不足

- **现象**：`styles.css` 中 7–10px 字号共 140 处（7px×2、8px×21、9px×70、10px×47）；表头 9px `#87928c`、辅助文字 10px `#8d9691`，计算对比度约 2.7–2.9:1；琥珀色文字约 3.8:1；均低于 WCAG AA 4.5:1。
- **证据**：`frontend/src/styles.css:231`（风险徽标 8px）、`:335`（表头 9px）、`:338`（`td small` 10px）。
- **影响**：投影与移动端读不清，是“界面很差”的第一来源。
- **修复**：正文/说明下限 12px、徽标下限 11px，先改风险徽标/表头/说明三档；灰阶统一到 `#6b7671` 以上，amber 加深。
- **验收**：桌面与移动端的正文、表头、风险徽标均可读；关键文字对比度 ≥ 4.5:1。

#### UX-29 [P1] 按钮字号层级反转

- **现象**：`button.primary-button` 的 `font: inherit`（特异性更高）覆盖了 `.primary-button` 的 12px/700，实测按钮为 16px/400，比 9px 正文更“大而不重”。
- **证据**：`frontend/src/styles.css:126` 与 `:187-194`。
- **影响**：视觉层级与可读性同时受损。
- **修复**：改为 `font-family: inherit`，让 12px/700 生效（或统一到 13–14px/600）。
- **验收**：按钮字号与字重符合设计层级，且不随浏览器默认样式漂移。

#### UX-30 [P1] 无可见焦点样式

- **现象**：全文件仅 2 处 `:focus`（输入框与 `:focus-visible` 局部），按钮、导航、链接 Tab 时无可见指示。
- **证据**：`frontend/src/styles.css:186`（仅 textarea/input）；全局无 `:focus-visible` 规则。
- **影响**：键盘用户无法定位；与 UX-11 的焦点逃逸叠加。
- **修复**：加全局 `:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }`。
- **验收**：仅用 Tab 浏览全站时，焦点位置始终可见。

#### UX-31 [P2] 移动端触控目标过小

- **现象**：角色按钮 `padding:5px 9px; font-size:9px`（实测约 36×19）、熔断 pill 约 64×23；620 断点进一步降到 8px。
- **证据**：`frontend/src/styles.css:742-746`、`:749-756`、`:958-959`。
- **影响**：手机上点不准，误触角色切换。
- **修复**：触控目标 ≥ 44×44px；移动端把角色切换收进菜单。
- **验收**：390px 下主要可点元素满足 44×44。

#### UX-32 [P2] 表格窄屏信息丢失

- **现象**：`th` 无 `scope`；620 断点直接 `display:none` 隐藏审计的工具/时间列，信息不可恢复。
- **证据**：`frontend/src/components/BankOverviewPage.tsx:206-215`；`frontend/src/styles.css:469`。
- **影响**：窄屏看不到关键列；屏幕阅读器无法关联表头。
- **修复**：补 `scope="col"`；窄屏改为两行卡片式行，而不是隐藏列。
- **验收**：窄屏与读屏场景下不丢关键字段。

#### UX-33 [P2] 无 ErrorBoundary

- **现象**：任一子组件抛错整页白屏（如 `StepJournalPanel` 对缺失字段 `toUpperCase()`）。
- **证据**：`frontend/src/main.tsx:6-10`（仅 StrictMode）；`frontend/src/components/StepJournalPanel.tsx:302`。
- **影响**：演示中一个异常字段就白屏，且无法恢复。
- **修复**：`<main>` 与确认弹窗外包 ErrorBoundary，fallback 提供“刷新 / 重试”；防御式访问 risk_level。
- **验收**：注入异常字段时不白屏，可继续操作。

### F. 演示与文档一致性

#### UX-34 [P1] 演示数据被消费后不可重跑

- **现象**：人工测试的 3 次任务中 2 次 `rolled_back`：第一次已取消 SUB-3002，第二次账单的 `suspicious_subscription_id` 变为 null，占位符解析失败 → 工具失败 → 自动补偿。界面显示“执行失败后已自动回滚：已按相反顺序成功补偿 0 个已执行步骤”，用户既看不懂也演示不下去。
- **证据**：`backend/data/dogfood.db` 的 `pending_actions` / `audit_log`（25 条，`tool_failed cancel_subscription`）；占位符来自 `frontend/src/components/ConfirmationModal.tsx:108` 的原始参数展示。
- **影响**：同一段演示无法重放，评委现场重试即翻车。
- **修复**：加“重置演示数据”入口（dev-only，调 `POST /api/demo/reset` 或提示 `scripts/seed-demo.sh`）；失败文案改为“演示数据已被上一轮消费，请重置后重试”；占位符在预览阶段标注“执行时确定”。
- **验收**：演示脚本可连续完整执行 3 次以上。

#### UX-35 [P1] README 演示路径与实现不符

- **现象**：README 第 5 步要求“六场景面板：执行「买 1000 元稳健短债A」；执行「给妈妈转 500 元」”，但 02 页是只读视图（仅有刷新与时间快进）；README 第 67 行仍写“七个页面”，实际 7 个。
- **证据**：`README.md:506` 与 `frontend/src/components/ScenariosPage.tsx:272`（`READ ONLY + TIME TRAVEL`）；`README.md:67`。
- **影响**：评委照文档操作会卡住，暴露文档与实现漂移。
- **修复**：把第 5 步动作改到任务控制台；或给 02 加动作入口（成本高，建议改文档）；同步页面数量。
- **验收**：按 README 从零走一遍不出现“页面不支持该操作”。

#### UX-36 [P3] 审计页首屏是事件码说明

- **现象**：审计页首屏是 12 个 2A 事件码的开发说明卡片，最近审计记录被挤到下方；首屏看不到“当前有多少条、链是否完整”。
- **证据**：`frontend/src/components/AuditPage.tsx:95-114`。
- **影响**：评委第一眼看到的不是审计结果，而是实现说明。
- **修复**：事件说明折叠或移到页尾；首屏放校验状态 + 最近记录。
- **验收**：审计页首屏即可回答“链是否完整、最近发生了什么”。

---

## 5. 根因分析

| # | 根因 | 表现 | 对应缺陷 |
|---|---|---|---|
| R1 | **组织维度错位**：界面按后端能力清单组织，而非按用户任务组织 | 7 个平级页面、序号误导、场景入口分散 | UX-01/02/04/05 |
| R2 | **语言层级错位**：实现细节进入用户界面 | DAG / 哈希 / JSON / 接口路径 / 英文枚举 | UX-10/13/14/36 |
| R3 | **状态归属错位**：任务状态在页面内存，而非 URL、持久层或可查询的后端资源 | 刷新即失忆、无法深链、无法续接 | UX-03/17/12 |
| R4 | **反馈缺失**：没有“提交后必须可见”的约束 | 不滚动、无 toast、无进度、旧回执残留 | UX-06/07/09 |
| R5 | **可用性基线缺失**：字号/对比/焦点/移动端没有门槛与检查 | 8–10px 字号 140 处、焦点逃逸、594px 溢出 | UX-27/28/29/30/31 |

> 补充：UX-18/19/20/21/22/23/24/25 属于“契约已存在但前端未接线”，根因是前后端联调只覆盖了正常路径，异常路径与恢复路径没有验收项。

---

## 6. 修复方案

### 6.1 原则

1. **任务可见**：任一时刻，用户能在首屏看到“我在做什么、下一步是什么”。
2. **状态可恢复**：刷新、断线、错误之后，都能回到一个可继续的状态。
3. **语言分层**：业务结论在外，技术证据在内（可展开，不消失）。
4. **增量不重写**：不引入 UI 库/状态库；不改后端契约的前提下先做前端，后端配套项单独小 PR。
5. **演示优先**：以“3 分钟评委演示脚本”为验收主线，其次才是完整功能。

### 6.2 目标信息架构

```text
导航（去序号、分组）
├─ 任务
│  ├─ 银行概览        ← 状态摘要 + “发起任务”主按钮 + 演示路径条
│  ├─ 任务控制台      ← 首屏即输入框；回执紧随其后
│  └─ 操作审计        ← 首屏：链状态 + 最近记录；按 run 过滤
├─ 治理
│  ├─ 权限控制台
│  ├─ 2A 能力
│  └─ 运维面板
└─ 数据
   └─ 场景数据（只读） ← 原“六场景面板”，标注只读 + 时间快进
```

页面数量本轮不变（7 页）；`#/console` 等 hash 深链先行，页面合并留到赛后。

### 6.3 分批计划

| 批次 | 目标 | 包含缺陷 | 预估 | 依赖 |
|---|---|---|---:|---|
| **批 1 · 止血** | 让首屏可用、手机可用、提交有反馈 | UX-01、06、27、28、29、30 | 0.5–1 人日 | 无（纯前端） |
| **批 2 · 闭环** | 确认弹窗可理解、可退出、可恢复；回执说人话；演示可重放 | UX-10、11、12、13、14、15、16、09、04、34、35 | 1.5–2 人日 | 批 1；UX-34 需后端 demo reset 接口 |
| **批 3 · 状态与契约** | 刷新可恢复、幂等、错误码驱动、写守卫统一 | UX-17、03、18、19、20、21、22、23、24、25 | 2–3 人日 | 批 2；UX-20/21/17 含后端小改 |
| **批 4 · 收尾** | 命名、演示细节与健壮性 | UX-02、05、07、08、26、31、32、33、36 | 1 人日 | 批 3 |

**建议排期**：若交付日期临近，只做批 1 + 批 2（约 2–3 人日）即可覆盖 7 个 P0 与主要 P1；批 3 放在演示脚本冻结前完成；批 4 可赛后。

### 6.4 关键设计

#### 6.4.1 确认弹窗（UX-10 / 11 / 12 / 16）

```text
┌──────────────────────────────────────────────┐
│ [YELLOW · 需要确认]              剩余 04:12   │
│ 取消「AI 工具订阅」（SUB-3002）                 │
│ 每月 ¥199 · 下次扣款 2026-10-29                │
│ 影响：取消后本次不再扣费；该操作不可撤销          │
│ 为什么需要确认：该操作会修改订阅状态（规则）       │
│                                              │
│ ▸ 技术详情（计划哈希 / 原始参数 / 证据分层）      │
│                                              │
│            [稍后处理]  [拒绝]  [确认取消订阅]    │
└──────────────────────────────────────────────┘
```

- 三个信息层：**这是什么**（自然语言摘要）→ **会发生什么**（金额/对象/可逆性）→ **为什么需要我确认**（触发规则）。
- 技术详情默认折叠，保留 `plan_hash`、`ActionEnvelope`、原始参数，满足审计诉求但不干扰阅读。
- 退出策略：ESC / 关闭 / “稍后处理”保留待确认快照（配合 §6.4.2）；focus trap + 关闭后焦点还原；打开时锁定背景滚动。
- 红色操作沿用同一结构，MFA 区显示“验证方式 + 剩余时间 + 失败原因”，演示 token 用“填入”按钮。

#### 6.4.2 任务可恢复（UX-17 / 03）

最小实现（纯前端，约 60–80 行）：

```ts
// sessionStorage key: aegisbank.pending.v1
type PendingSnapshot = {
  actionId: string;
  runId: string;
  instruction: string;
  riskLevel: 'yellow' | 'red';
  summary: string;      // 人话摘要，用于横幅
  savedAt: string;      // ISO
  expiresAt: string;    // ISO
};
```

- 生成待确认动作时写入快照；确认/拒绝/过期后清除。
- 挂载时读取快照 → `GET /api/trust/actions/{id}` 校验状态仍为 `AWAITING_*` → 顶部横幅“你有一笔待确认的操作：取消订阅”＋[继续确认] [放弃]。
- 继续确认时用 `GET /api/actions/{id}/journal` 恢复计划节点与风险原因（pending journal 已包含 plan）。
- 放弃只清理本地快照并提示“动作将在 5 分钟后自动过期”，不伪造后端状态。
- 可选增强（后端小改）：`GET /api/confirmations?status=pending`，支持多标签页与换设备恢复。

#### 6.4.3 错误码 → UI 动作映射（UX-12 / 19）

| HTTP / code | 语义 | 用户文案 | UI 动作 |
|---|---|---|---|
| 409 `ENVELOPE_*` | 计划/额度/确认已变化，或确认前复检未通过 | “这次确认已失效（计划或额度已变化），需要重新发起。” | 关闭弹窗；保留指令；刷新 trust + audit；给“重新发起” |
| 422 | 执行失败或参数校验失败 | “操作未执行：{原因}” | 关闭弹窗；渲染失败回执；给重试/回滚入口 |
| 400 | 重复确认或意图不明确 | “该确认已处理过，或指令需要补充。” | 关闭弹窗；刷新任务状态 |
| 403 + MFA | OTP / 生物识别失败 | “验证未通过：{原因}” | 保留弹窗；清空 token；聚焦输入 |
| 503 | 服务未就绪 | “系统未就绪，写操作已暂停。” | 保留弹窗但禁用确认；立即重拉 readiness；可“稍后处理” |
| 网络 / 超时 | 无法连接 | “无法连接服务，请稍后重试。” | 可重试；复用幂等键；显示离线状态 |

实现形态：`api.ts` 暴露 `describeError(err, context)` 与 `classifyConfirmationError(err) → 'retry' | 'reconfirm' | 'refresh'`，`decide()` 消费分类结果。

#### 6.4.4 回执信息分层（UX-14 / 15）

```text
✅ 已取消「AI 工具订阅」，本次不再扣费
   金额 ¥199/月 · 对象 SUB-3002 · 2026-10-23 16:42
   下一步：查看本次审计记录 →
▸ 技术详情：RUN ID / plan_hash / 节点入参与出参 / 证据分层
```

- 第一屏只回答：成功还是失败、关键数字、下一步。
- 审计入口放在结论旁，一键跳转并按 `run_id` 过滤。
- 状态机、步骤日志、补偿详情收进折叠区；`UNKNOWN` 时在折叠区外显示对账按钮（UX-23）。

#### 6.4.5 演示数据治理（UX-34）

- **推荐**：新增 dev-only `POST /api/demo/reset`（仅 `AEGIS_DEMO_MODE=1` 启用），内部复用 `aegisbank_api.demo_seed`；前端在顶栏“DEV”旁提供“重置演示数据”，二次确认后调用并刷新全站。
- **兜底**：不新增接口时，UI 检测到“可重复演示资源已消费”（如 `suspicious_subscription_id === null`）时提示运行 `bash scripts/seed-demo.sh`，并把失败文案从“自动回滚”改为“演示数据已被上一轮消费”。
- **演示模式**（可选）：一键进入“干净演示”：重置数据 + 预置指令 + 隐藏开发者面板。

#### 6.4.6 提交与幂等（UX-18）

- 每次逻辑提交生成 `idempotencyKey = crypto.randomUUID()`，存 `useRef`；
- 网络失败/超时重试复用同一 key；进入终态（确认/拒绝/失败）后清空；
- 后端若返回 `IDEMPOTENCY_KEY_REUSED`，提示“内容已变化，请重新发起”，不复用旧 key。

### 6.5 工作量与依赖

| 项 | 前端 | 后端配套 | 说明 |
|---|---|---|---|
| 批 1 | 0.5–1 人日 | 无 | 纯 CSS + 少量组件结构调整 |
| 批 2 | 1.5–2 人日 | demo reset 接口（0.5 人日） | 弹窗与回执是主要工作量 |
| 批 3 | 2–2.5 人日 | reject 角色复检、permissions/sandbox readiness（0.5–1 人日） | 状态机与路由 |
| 批 4 | 1 人日 | 无 | 收尾 |
| **合计** | **5–6.5 人日** | **1–1.5 人日** | 不含真实用户测试与截图更新 |

### 6.6 风险与回退

- **App.tsx 状态集中**：批 3 改动前先抽 `usePendingAction()` / `useRefreshAll()` 两个 hook，避免 610 行组件内继续膨胀。
- **文案与测试**：前端已有 38 项 Vitest 覆盖 `viewModel` / `risk` / `twoA`，改状态映射与文案时同步更新夹具，避免“文案单测”变成空转。
- **演示冻结窗口**：批 2 完成后冻结 UI，仅修 bug；截图与视频按 `docs/screenshots/README.md` 重新生成。
- **后端小改单独 PR**：reject 角色复检、readiness 覆盖、demo reset、pending 列表分别提交，避免与前端混在一个变更里；每项补一条 pytest。

---

## 7. 验收与回归

### 7.1 批次验收

| 批次 | 可执行验收 |
|---|---|
| 批 1 | 1440×900 首屏可见输入框；提交后 1 秒内视口出现结果；360/390/768 无横向滚动；正文 ≥12px；Tab 焦点可见 |
| 批 2 | 弹窗仅用键盘可确认/退出；409 后一个步骤内回到可继续状态；回执首屏回答 5 个问题；同一演示连续跑 3 次不失败 |
| 批 3 | 弹窗中刷新可恢复；双击提交只产生一个待确认动作；409/422/503 分别触发正确动作；readiness 异常时所有写入口禁用或 503 |
| 批 4 | 每页职责可从导航读出；桌面/移动端主要可点元素 ≥44×44；注入异常字段不白屏 |

### 7.2 自动化用例建议

- `api.test.ts`：`describeError` 对 409/422/503/403/网络输入的映射；`422` detail 数组转文案。
- `pending.test.ts`：快照写入/恢复/过期清理；`classifyConfirmationError` 三种分类。
- `ConfirmationModal.test.tsx`：ESC 退出、focus trap 首尾循环、未就绪时“稍后处理”可用。
- `TaskConsolePage.test.tsx`：提交后调用 `scrollIntoView`；快捷动作不覆盖未提交文本。
- `viewModel.test.ts` 扩展：状态/事件/确认态枚举全部有中文文案（用后端枚举做 fixture，防止漂移）。
- 布局回归：无头浏览器脚本断言 `scrollWidth === innerWidth`（360/390/768/1440）与“首屏含 textarea”。

### 7.3 与 UX-DOGFOODING 退出标准的映射

| 退出标准 | 当前 | 修复批次 |
|---|---|---|
| 无 P0/P1 可用性阻塞 | ✗（7 个 P0） | 批 1–2 |
| 三个代表场景从首次打开到完成 ≤10 分钟 | ✗（入口不可见、刷新丢状态） | 批 1–2 |
| 风险等级、确认原因、结果、审计状态可被非开发者理解 | ✗（JSON/术语/回执过载） | 批 2 |
| 桌面与移动端关键路径可用 | ✗（594px 溢出） | 批 1 |
| 不再有只有开发者知道的隐性操作 | ✗（深链缺失、快捷动作覆盖输入） | 批 2–3 |

---

## 8. 不在本次范围

- 页面合并（7 → 5）与“任务详情页 `#/runs/:id`”重构：建议赛后进行，收益大但改动面大。
- 真实身份认证 / 真实 MFA / 真实 IM 平台接入：属于生产化剩余项（见 `ROADMAP.md`）。
- 视觉重设计（换配色/换设计语言）：本轮只做可用性基线，不做品牌层重做。
- 多标签页同步、离线缓存、国际化。

---

## 9. 附录

### A. 运行时证据（原始值，2026-10-23）

**1440×900（桌面）**

| 指标 | 值 |
|---|---|
| hero 区域 | `top=193`、`bottom=553`、高度 `360px` |
| 指令卡 | `top=722` |
| textarea | `top=823`、`bottom=914`（视口高 900） |
| 提交按钮 | `top=823`、`bottom=914`（部分在视口外） |
| 提交后回执卡 | `top=1822`、`scrollY=0`、`inViewport=false` |
| 提交后文档高 | `3993px` |

**390×844 / 360×844（移动端）**

| 指标 | 值 |
|---|---|
| `innerWidth` | 390 / 360 |
| `document.documentElement.scrollWidth` | **594**（横向溢出 204 / 234px） |
| 根因 | `styles.css:424` `.layout { grid-template-columns: 1fr }` + `.sidebar nav` 无 `min-width:0` |
| 验证性注入 | 改回 `minmax(0,1fr)` 并加 `min-width:0` 后 `scrollWidth=390`（仅注入验证，未改文件） |

**键盘与焦点**

- 弹窗内 Tab 序列：`拒绝执行 → BODY → USER → OPERATOR → AUDITOR → 熔断关闭`（第 2 次 Tab 即离开弹窗）。
- 弹窗打开时 `document.body.style.overflow` 为空（背景可滚动）。
- ESC 无法关闭弹窗。

**字号与对比度**

- `styles.css` 字号分布：7px×2、8px×21、9px×70、10px×47、11px×29、12px×21。
- 关键对比度（计算值）：表头 `#87928c` ≈ 2.9:1；辅助文字 `#8d9691` ≈ 2.8:1；琥珀文字 ≈ 3.8:1。

**人工测试复盘（`backend/data/dogfood.db`）**

- `pending_actions`：3 条（completed ×1、rolled_back ×2）。
- `audit_log`：25 条；2 次 `tool_failed cancel_subscription` → `ROLLED_BACK`，原因均为订阅已被上一轮取消、占位符解析为 null。
- 结论：演示数据有状态且不可重放（UX-34）。

**离线表现**

- 停止后端后，Vite 代理返回 500，界面显示“请求失败（HTTP 500）”，而非“服务离线”；fail-closed 骨架有效（写按钮禁用），但错误文案不可读。

### B. dsh-workflow 分诊与执行记录

```text
triage.ps1 -Repo . -Task "产出 AegisBank 前端 UX 问题与修复方案报告：..." -NoWrite
  → 档位：solo（子代理上限 0）
  → 技能：[必用] diagnosing-bugs
  → 写域：be-docs = **/*.md, **/*.txt
  → 计划：.dsh-workflow/.state/team/t-20261023-1653-e6ec45/plan.json

team-plan.ps1 -Repo . -Brief   → 无子代理角色，Lead 兼 scout / be-docs / ver / commit
team-plan.ps1 -Repo . -Tasks   → 4 个任务键（scout → be-docs → ver → commit）
```

执行映射：`scout`（triage）→ `be-docs`（本报告）→ `ver`（引用与数字自检）→ `commit`（按用户要求**未执行提交**）。
技能 `diagnosing-bugs` 的应用方式：每条 P0/P1 均给出可复现命令与运行时证据（相当于 feedback loop），修复方案要求先补回归用例再改实现。

### C. 缺陷索引（按文件）

| 文件 | 相关缺陷 |
|---|---|
| `frontend/src/App.tsx` | UX-02、03、04、09、12、17、19、20、22、25 |
| `frontend/src/api.ts` | UX-18、19、23 |
| `frontend/src/roles.ts` | UX-24 |
| `frontend/src/main.tsx` | UX-33 |
| `frontend/src/styles.css` | UX-27、28、29、30、31、32 |
| `frontend/src/components/TaskConsolePage.tsx` | UX-01、06、07、08、09、14、15、23 |
| `frontend/src/components/ConfirmationModal.tsx` | UX-10、11、12、13、16 |
| `frontend/src/components/ScenariosPage.tsx` | UX-02、05、13、22、26、35 |
| `frontend/src/components/CapabilitiesPage.tsx` | UX-13、21 |
| `frontend/src/components/PermissionsPage.tsx` | UX-21 |
| `frontend/src/components/StepJournalPanel.tsx` | UX-13、33 |
| `frontend/src/components/AuditPage.tsx` | UX-13、25、36 |
| `frontend/src/components/BankOverviewPage.tsx` | UX-04、05、32 |
| `backend/aegisbank_api/scheduler.py` | UX-12、20 |
| `backend/aegisbank_api/main.py` | UX-17、21、23 |
| `backend/aegisbank_api/extensions/sandbox.py` | UX-21 |
| `backend/aegisbank_api/extensions/im.py` | UX-21 |
| `README.md` | UX-35 |

### D. 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-23 | 首版：36 项缺陷、5 条根因、4 批修复计划、验收与回归清单 |
| v1.1 | 2026-10-23 | 批 1 / 批 2 与批 3 前端项实施完成；补充 §10 实施记录与验证证据 |

---

## 10. 修复实施记录（v1.1，2026-10-23）

> 本轮只改前端（`frontend/src/**`）与 README；后端安全整改（认证、多租户、确认原子化等）不在本轮范围。
> 所有条目均为增量改动，未引入新框架；新增 `errors.ts` / `session.ts` / `useHashRoute.ts` / `ErrorBoundary.tsx` / `styles-ux.css`。

### 10.1 已修复

| 缺陷 | 实施方式 | 主要文件 |
|---|---|---|
| UX-01 | 控制台 order 调整为「指令卡 → 回执 → hero → 指标」；hero 压缩为 138px | `styles-ux.css`、`TaskConsolePage.tsx` |
| UX-03 | 30 行 hash 路由（`#/console` 等）+ 每页 `document.title` | `useHashRoute.ts`、`App.tsx` |
| UX-04 | 控制台加「演示路径」三步 chip（分析账单 / 小额转账 / 查看审计） | `TaskConsolePage.tsx` |
| UX-06 | 提交完成检测 busy→false 后 `scrollIntoView` 回执；运行中显示阶段行 | `TaskConsolePage.tsx` |
| UX-07 | `role="status"` 的阶段行「正在解析意图、校验权限与风险」 | `TaskConsolePage.tsx` |
| UX-08 | 快捷动作检测未提交文本：有自定义内容时只填入、不自动执行 | `TaskConsolePage.tsx` |
| UX-09 | 新提交开始时清空上一轮回执 | `App.tsx` |
| UX-10 | 确认弹窗改为「将要发生什么」人话摘要；占位符标注「执行时确定」；原始参数收进折叠 | `ConfirmationModal.tsx`、`viewModel.ts` |
| UX-11 | ESC / 关闭按钮 / 稍后处理；focus trap；body 滚动锁定；关闭后焦点还原 | `ConfirmationModal.tsx` |
| UX-12 | 按 409/400/422 关闭弹窗并提示重新发起，503/403 保留可重试 | `App.tsx`、`errors.ts` |
| UX-13 | 弹窗与回执中的接口路径、plan_hash、JSON 收进「技术详情」折叠；审计页去掉 `/api/audit/verify` 文案 | `ConfirmationModal.tsx`、`TaskConsolePage.tsx`、`AuditPage.tsx` |
| UX-14 | 回执改为结论 / 关键事实 / 技术详情三层；执行时间与审计编号前置 | `TaskConsolePage.tsx`、`viewModel.ts` |
| UX-15 | 回执增加「查看本次审计记录 →」，跳转审计页并预填本次指令作为搜索词（审计条目未存 run_id，暂不能精确过滤） | `TaskConsolePage.tsx`、`App.tsx`、`AuditPage.tsx` |
| UX-16 | 确认弹窗显示「剩余 mm:ss」，过期禁用决策；演示 token 改为「填入演示令牌」 | `ConfirmationModal.tsx`、`session.ts` |
| UX-17 | sessionStorage 快照 + 顶部恢复横幅（继续处理 / 放弃恢复）；刷新不再丢待确认动作 | `session.ts`、`App.tsx` |
| UX-18 | `/agent/run` 与确认请求生成并复用 `Idempotency-Key`；终态清空 | `api.ts`、`App.tsx` |
| UX-19 | `describeError` 统一错误码 → 文案 + 动作；422 detail 数组转可读文案；请求超时 | `errors.ts`、`api.ts` |
| UX-20（前端） | 有待确认动作时拒绝切换角色，避免跨角色确认/拒绝 | `App.tsx` |
| UX-22 | `refreshAll` 统一刷新；场景时间快进成功后通知 App 刷新概览/审计 | `App.tsx`、`ScenariosPage.tsx` |
| UX-23 | UNKNOWN 回执提供「人工对账为已解决 / 申请人工回滚」，调用后端 reconcile | `api.ts`、`TaskConsolePage.tsx`、`App.tsx` |
| UX-25 | 审计校验失败与「尚未校验」区分：顶栏显示「审计链校验失败」 | `App.tsx`、`AuditPage.tsx` |
| UX-27 | 1024 断点 `minmax(0,1fr)` + `.sidebar`/`nav` `min-width:0` | `styles-ux.css` |
| UX-28 | 风险徽标 11px、表头 11px、主要辅助文字 12px（`.eyebrow` 与指标小字仍为 10px，留待下一轮打磨） | `styles-ux.css` |
| UX-29 | 修正 `font: inherit` 覆盖，按钮恢复 13px/700 层级 | `styles-ux.css` |
| UX-30 | 全局 `:focus-visible` 焦点环 | `styles-ux.css` |
| UX-31 | 移动端按钮最小高度 44px、角色/熔断控件增大 | `styles-ux.css` |
| UX-33 | ErrorBoundary 包裹 App，提供重试/刷新 | `ErrorBoundary.tsx`、`main.tsx` |
| UX-35 | README 演示步骤改为在任务控制台执行；页面数量更正为 7 | `README.md` |
| UX-36 | 审计页事件说明改为页尾可折叠 | `AuditPage.tsx` |

### 10.2 部分修复 / 推迟

| 缺陷 | 状态 | 说明 |
|---|---|---|
| UX-02 | 部分 | 02 改名「场景数据（只读）」、03 hint 改「发起任务」；页面合并与导航分组留待赛后 |
| UX-05 | 推迟 | 概览与场景数据的内容重叠未做合并 |
| UX-13 | 部分 | 2A 能力页、步骤日志页仍有少量接口路径文案，未全量收口 |
| UX-20 | 部分 | 后端「拒绝」分支缺角色复检属于安全整改范围，前端已阻止跨角色操作 |
| UX-21 | 推迟 | 权限/沙箱/IM/熔断的 readiness 守卫需后端配合，本轮未改 |
| UX-24 | 推迟 | 前端能力矩阵改为 `GET /api/authz/me` 留待与后端认证改造一起做 |
| UX-26 | 推迟 | 月报/年报请求序号属低风险打磨项 |
| UX-32 | 推迟 | 表格窄屏卡片化未实施 |
| UX-34 | 推迟 | 演示数据重置需要后端 dev-only 接口，留待安全整改批 |

> 集成验收（integrator 只读复验）结论：**ACCEPT WITH NOTES**（无阻断）。其中 3 条建议已在本版处理：
> 演示路径 chip 跨页返回后一键执行、审计跳转预填本次指令、弹窗关闭后焦点回退到指令框；
> 其余为文案精度与后端字段缺失（绿色直通回执无 `audit_id` / `executed_at`），已在下方验证证据中如实标注。

### 10.3 验证证据

| 检查 | 结果 |
|---|---|
| `pnpm typecheck`（tsc --noEmit） | 通过（0 error） |
| `pnpm test`（Vitest） | **38 passed**（新增 `errors.test.ts` 5 条、`session.test.ts` 6 条、`viewModel.test.ts` 新增 5 条） |
| `pnpm build`（Vite production） | 通过（52 modules，CSS 59.24 kB / JS 376.61 kB） |
| 1440×900 首屏 | 指令卡 top=194，textarea top=344（修复前 823），提交后回执滚入视口（result top=96） |
| 390×844 移动端 | `innerWidth=390`、`documentElement.scrollWidth=375`，无横向滚动（修复前 594） |
| 确认弹窗 | 人话摘要 + 剩余 4:55 倒计时；无 `${steps...}` 泄漏；Tab 循环停留在弹窗内；ESC 关闭后出现恢复横幅 |
| 刷新恢复 | 弹窗中刷新 → 顶部恢复横幅（剩余 4:53）→「继续处理」恢复同一确认 |
| 错误路径 | 409/400/422 关闭弹窗并提示重新发起；403 MFA 保留弹窗；503/网络可重试（由 `errors.test.ts` 覆盖分类） |
| 回执与审计 | 回执显示结论/状态；「查看本次审计记录」跳转 `#/audit` 并预填本次指令作为搜索词。执行时间与审计编号在后端返回时显示（绿色直通路径当前不返回，显示「—」） |

### 10.4 集成验收记录

| 项 | 结论 |
|---|---|
| 范围合规 | `git status` 恰好 18 个文件，全部落在 `frontend/**`、`README.md`、`docs/UX-RECORD.md`；无临时脚本/产物 |
| 独立复跑 | `tsc --noEmit` = 0；`vitest run` = 5 文件 / 38 passed |
| 真实浏览器 | 1440×900 textarea top=344；演示路径 1→2 通过；弹窗可见层无 `${steps...}`；Tab 15 次不逃窗；ESC→恢复横幅；刷新后恢复；390/360/768 七页无横向滚动；console error = 0 |
| 结论 | ACCEPT WITH NOTES（无阻断）；已处理 3 条建议，其余为文案精度与后端字段缺失 |
| 环境说明 | 验收使用 `/tmp/ux-audit.db` 测试库，同日已有 ¥880 完成转账，故小额转账按规则升级为 RED；测试库可通过 `scripts/seed-demo.sh` 重置 |
