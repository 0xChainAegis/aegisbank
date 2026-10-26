# 比赛对照、安全复审与修复记录（2026-10-23）

审查基线：[GitHub main 82c5d75](https://github.com/LQZ5885/aegisbank/tree/82c5d75a19c52594792726a1d85548482edb85bf)。审查时 Linux 主线 HEAD 与远端一致；Windows 历史副本的 MASTER-PLAN 较旧。本轮先审查，后按用户要求实施修复。只使用临时 Mock 数据库，不访问真实银行或客户数据。

原基线验证：后端 144 项 pytest、前端 38 项 Vitest、lint、构建、六场景脚本 29/29 均通过。这些用例没有覆盖下列安全反例。隔离复现包含 29 组后端探针和 7 组 React/jsdom 交互探针；探针包含并发同步和故障注入，不等同于已在公网完成利用。严重等级按模拟账本完整性与控制面影响评定，P0 最高。

## 比赛对照

| 要求 | 审查结论 | 必须补齐的证据或实现 |
|---|---|---|
| 至少三个参考场景 | 六个方向均有实现，原场景回归通过 | 场景存在不代表每个参考示例完整实现；AA 收款、推荐对比等应准确描述 |
| 日累计 >1000 元强验证 | 存在绕过 | DAG 多笔累计、定时转账必须覆盖同一确定性风险链 |
| 完整审计、幻觉防护 | 存在账本与审计不一致 | 并发链写入、账本/审计/journal 原子性、礼物流水、模型语义与前端缺失值 |
| 注入防御、异常熔断 | 部分实现 | 正则不是完整安全边界；MFA 失败必须计数，角色和授权必须逐步骤复核 |
| 受限运行环境 | 演示级，存在实现缺陷 | 超时后的持久化副作用、进程全局网络拦截、资源上限；不得宣称任意代码的 OS 隔离 |
| 模糊表达、省略上下文 | 审查时单轮澄清可用、多轮上下文缺失；本轮新增受限续问 | 已补限时单次缺参续问与否定/多意图冲突；通用指代与长会话仍待完善 |
| 中断、回退、人工接管 | 有接口，存在恢复/补偿漏洞 | 撤权后恢复、并发恢复/回滚、只读角色写状态、对账证据与真实补偿分离 |
| APP / IM 等入口 | Web 与通道模拟可用 | 真实 IM 签名、账户映射属于外部集成；不能把模拟适配器写成真实平台接入 |
| 简介、技术文档、PPT、源码与测试、安全自评 | 文件存在 | 简介正文实测 199 字符；PPT 14 页且有备注，实际汇报时长仍需排练 |
| 演示视频 ≤5 分钟 | 未交付视频文件 | 只有脚本，需录制并核验时长；不能标为完整交付 |

赛题黄色示例同时列出“订阅查询/取消”，而绿色原则为纯查询。当前订阅查询为绿色，需保守对齐或取得组委会口径；此项单列为要求解释差异，不伪称已判定违规。参考示例不全部等同于硬性必做项。

## 已确认问题与修复验收

下表记录修复前事实。修复状态与最终命令结果在文末更新；没有回归证据的条目不标为完成。

| ID / 级别 | 代码位置（修复前） | 复现与影响 | 修复方案 | 验收标准 |
|---|---|---|---|---|
| B01 P0 | `extensions/compensation.py:288,627` | 显式调用 reverse_transfer，伪造不存在的原交易，黄色确认后余额增加 100 万 | 反向工具仅内部补偿可达；由持久化 journal 获取原参数/结果，并原子防重复 | 伪造、改金额、重复冲正均无余额变化；合法补偿一次成功 |
| B02 P0 | `scenarios/automation.py:1178,1249,1518,2007` | 1500 元定时转账黄色确认；撤回 transfer 后，以 auditor 调 run-due 仍扣款；子操作没经过 executor | 绑定持久化任务授权，实际转账逐次复核权限、动态风险和授权上限，经统一执行器 | 超日累计无 MFA 不执行；撤权与非执行角色不能触发扣款 |
| B03 P0 | `scheduler.py:144,1378` | 两个 600 元节点整体黄色确认，第二步风险变红仍执行 | 计划预估累计暴露；逐节点复核授权风险上限、网关与已确认参数 | 超累计必须红色确认；运行时风险变化先阻断 |
| B04 P0 | `scheduler.py:1677,2542` | 并发两次回滚同一 100 元转账，最终余额比最初多 100 | 动作串行占有、补偿事务与去重 | 并发回滚最多一次冲正，其他请求回放或 409 |
| B05 P0 | `scheduler.py:1386,1422,1437` | 扣款后注入审计失败，返回 422/FAILED，但实际扣 100，journal 没有执行记录 | 工具副作用、成功审计与 journal 统一事务；不确定结果保留 UNKNOWN | 任一提交点故障不得出现“扣款但失败且无证据” |
| B06 P0 | `banking/repository.py:373,380` | 余额 1000，并发转两笔 800，余额为 -600 | 事务内条件扣款与受影响行校验；同类财富读改写收口 | 并发金额超过可用余额时最多成功一笔，不出现负余额 |
| B07 P1 | `scheduler.py:2281,2354` | 暂停后撤回下一工具权限，resume 仍执行 | 恢复时使用当前角色与授权、逐步网关复检 | 撤权、熔断、失效确认均阻止剩余写入 |
| B08 P0 | `scheduler.py:2303,2343` | 两个 resume 同时读取 paused，剩余步骤执行两次 | 动作操作互斥与状态重读 | 并发 resume 只执行一次剩余节点 |
| B09 P1 | `scheduler.py:964` | auditor 可拒绝他人待确认动作，写 REJECTED | 拒绝与批准统一能力/归属校验，先校验再回放 | 只读角色对确认写端点一律 403，无状态变化 |
| B10 P1 | `main.py:404; scheduler.py:2671` | auditor 可把 UNKNOWN 标为 ROLLED_BACK，未冲正；后续还回放旧 UNKNOWN | 对账写入使用管理能力；对账结论与执行补偿分离，更新统一回执 | 只读不能写；未执行补偿不能显示“资金已退回” |
| B11 P1 | `scheduler.py:895` | 已完成结果在归属校验前回放，其他 user_id 可取得结果 | 归属与能力先于缓存 | 跨用户、角色越权不能读回执 |
| B12 P1 | `main.py:251; extensions/{compensation,sandbox,authz,breaker}.py` | not_ready 下辅助写路由仍可更新授权、执行 demo；IM 使用另一个 readiness 实例 | 全写入口共享 fail-closed；恢复和后台路径同样复检 | 依赖故障逐个写路由均 503 且无副作用 |
| B13 P1 | `scheduler.py:1004` | 连续五次错误 OTP 均 403，熔断仍关闭 | MFA 失败计数与审计，达到阈值锁定 | 错误强验证达到阈值后即使正确令牌也不能直接执行 |
| B14 P1 | `trust/mfa.py:143; scheduler.py:1006` | transfer 策略仅允许 OTP，但 biometric 也可执行 | 策略与实际允许 provider 一致，整条 DAG 取交集 | 策略外 provider 被拒，API/UI 展示与执行一致 |
| B15 P1 | `channels/im.py:186,197` | bob 可确认 alice 动作，auditor 头被忽略并作为 user 执行 | 绑定通道/发送者/动作/角色；校验签名属于真实接入前置 | 跨发送者确认与非执行角色均拒绝 |
| B16 P1 | `channels/im.py:143,168,407` | 相同 message_id 跨 sender/channel 返回另一人的回执 | 按发送者/通道命名空间，内容哈希，原子占有 | 跨发送者不串回执；并发重复投递不创建第二动作 |
| B17 P0 | `trust/sandbox.py:378` | 超时抛错后工具线程继续，稍后余额仍增加 123.45 | 可取消的持久化边界、事务提交截止、未知结果不重试、资源上限 | 超时后不产生新的持久化副作用 |
| B18 P1 | `trust/sandbox.py:99` | 工具运行时，无关线程 DNS 也被 SandboxViolation 拒绝 | 网络约束限于工具执行上下文，避免进程全局污染 | 并发 Planner/普通线程不受工具沙箱影响 |
| B19 P1 | `scheduler.py:856` | 故障注入清空 envelopes_json，确认仍执行；需数据库/迁移故障前提，非远程接口利用 | 验证 envelope 与步骤完整一一对应，缺失 fail closed | 空、少、重复 envelope 均 409，零执行 |
| B20 P1 | `trust/idempotency.py:49` | 并发同键抢占产生 IntegrityError 而非稳定冲突 | 原子插入占有，重复读取返回回放/处理中；限制键长度 | 同键并发无 500、最多一个动作 |
| B21 P1 | `planning/llm.py:93` | 联系人收款人/金额可改；100 的子串 10 被视为已提及；显式查询可增加写步骤 | 结构化参数逐类核对，数值边界匹配，限制显式工具计划 | 错收款人、错产品、错金额、额外副作用转澄清 |
| B22 P1 | `tools/finance.py:62; planning/rule.py:92` | transfer 空参数默认转 880；模糊调限额默认 2000 | 金融写参数必须显式提供，未知则澄清 | 缺金额/收款人/限额不产生可执行写计划；自然语言转澄清，缺参显式 API 返回 400 |
| B23 P1 | `banking/repository.py:28,370` | 0.001 元通过输入，最终完成一笔 0 元转账 | 有限数与分精度校验，金额转换后必须 >0 | 次分、NaN、Infinity、负数、零均拒绝 |
| B24 P2 | `executor.py:72; domain.py:37` | 33/48 工具输出 schema 为空；执行器未校验输出 | 输出公共契约与声明 schema 校验，异常不能标 verified | 破坏输出/模拟标记的工具拒绝提交 |
| B25 P1 | `scenarios/cards.py:527` | 不传限额默认恢复 10000，但风险是黄，无 MFA | 对实际解析后的默认值评估风险 | 默认与显式 10000 均红色 |
| B26 P1 | `banking/repository.py:443` | 改额度把已用额度 8250 清零 | 保留已用金额与业务约束 | 调整前后已用额度不凭空变化 |
| B27 P1 | `scenarios/automation.py:825,1271` | 预算 100 却花 358，可用余额大于余额 | 预约总额不能超预算；事务内消费锁定金额与可用金额 | 超预算不预约/扣款；保持账户不变量 |
| B28 P1 | `scenarios/automation.py:1312` | 礼物扣款 358，交易流水与月支出增量为 0 | 同事务写确定性消费流水与订单完成结果 | 余额、流水、月报、预算与订单一致 |
| B29 P1 | `scenarios/wealth.py:689,712` | 赎回全部 3000 份后仍 active，份额 0、市值 60 | 统一用持仓净值换算份额/市值，事务内校验 | 全部份额赎回关闭持仓，金额与份额守恒 |
| B30 P1 | `scenarios/bills.py:1241,1257,1270,1282` | 撤权后工具入口 blocked，REST 仍 200，未过 executor、无审计 | REST 查询复用同一网关/执行链，禁止 tool.execute | 撤权一致生效；静态检查无直接调用 |
| B31 P1 | `planning/rule.py:88` | “不要挂失 CARD-9902”生成挂失计划 | 否定/冲突命令转澄清，不静默截取多意图 | 否定不生成写计划，多意图明确拆解或澄清 |
| B32 P2 | `planning/rule.py:119,193` | 查询余额得到的是账单，不含余额 | 余额意图返回真实 Mock 账户快照 | 指定账户余额与仓库一致 |
| B33 P1 | `gateway.py:42; db.py:134` | 新用户/新工具自动全授权，GET 权限也可写入默认授权 | Demo 预置授权范围明确；新增工具默认拒绝，未知用户不自动建权限 | 新增工具/未知用户不能自动获得资金权限 |
| B34 P1 | `scenarios/automation.py:1132` | 领取任务即写 done；故障后无扣款却永久完成且不会重跑 | 领取与副作用/结果统一提交，不能提前标成功 | 领取后故障不呈现 done；重启不重扣或丢任务 |
| B35 P2 | `audit.py:35; frontend/src/App.tsx:705` | 同指令多次执行无统一 run_id，前端按指令匹配最近日志 | 新审计持久化 run_id/step_id 并精确查询，旧链不改写 | 同文本的并发任务可分别还原决策链 |

| B36 P0 | `extensions/compensation.py:609` | 申购 1000 → 全额赎回合并持仓 → 回滚原申购，修复前又返 1000 并标记 rolled_back | 核验原申购订单、份额/本金/市值与持仓 active 状态；原交易只能登记一次冲正，持仓不足转 UNKNOWN | 已赎回不能再返款；失败补偿不改变余额，不伪装已退款 |
| B37 P1 | `extensions/compensation.py:270` | 本人账户 A→B 转 100；B 将款转出；回滚第一笔，修复前 B=-100、A 获退款 | 在同一事务验证原流水及唯一冲正，收款账户条件扣款成功后才退回付款方 | 收款余额/可用金额不足时零变更、补偿失败转 UNKNOWN |

上述路径均以 `backend/aegisbank_api/` 为后端相对根。并发用例用 Barrier 固定交错，故障用例显式注入，不声称自然运行必然每次触发。B36/B37 是修复分支最终复核追加的正常用户流程反例；先运行新回归确认两项均失败，修复后再通过。

## 前端已确认问题

| ID / 级别 | 位置 | 复现 | 修复方案 | 验收标准 |
|---|---|---|---|---|
| F01 P1 | `App.tsx:407` | 网络错误后把 100 改为 200，复用原键 | 逻辑提交按请求内容绑定键；结果未知时先查询 | 相同内容重试同键；未知结果先查询并阻止改正文，原任务解决后新提交使用新键 |
| F02 P1 | `App.tsx:137; session.ts` | 服务端收请求但响应丢失，刷新生成新键 | 发请求前持久化提交记录，刷新后查询/回放 | 丢响应并刷新仍只有一个动作 |
| F03 P1 | `errors.ts:75; App.tsx:483` | IDEMPOTENCY_IN_PROGRESS 的 409 关闭弹窗并清快照 | 按业务 code 区分暂态/终态 | 处理中保留任务与键，禁止建议重新下单 |
| F04 P1 | `App.tsx:425` | 稍后处理一笔转账后发起查询，旧快照被清除 | 待处理动作与当前回执分开管理 | 新查询/失败/刷新不丢旧确认 |
| F05 P1 | `App.tsx:342` | 恢复直接信任本地计划，未取服务端状态；可稍后后换角色再开确认 | 恢复先核对服务端归属、状态、计划与当前能力 | 失效/已完成/角色不符不允许确认旧快照 |
| F06 P1 | `PermissionsPage.tsx:151; CapabilitiesPage.tsx:110` | not_ready 时授权、IM、沙箱按钮可点 | 统一向所有写页面传就绪状态 | 未就绪所有写按钮禁用，服务端仍独立拒绝 |
| F07 P2 | `roles.ts:46,78,97` | 客户端复制角色矩阵，与 AuthzService 存在两个口径 | 从 authz/me 获取 capability，用能力控制展示 | 前端无角色名硬编码授权判断 |
| F08 P1 | `errors.ts:84; viewModel.ts:49` | 422 文案称未执行；rolled_back 文案称已撤销，和故障事实不符 | 以服务端证据/未知状态描述，区分对账标记与真实补偿 | 结果未知不引导重复扣款、不宣称无副作用 |
| F09 P2 | `ScenariosPage.tsx:41` | 月报慢响应晚于年报响应，覆盖新账期 | 请求序号/取消与卸载保护 | 乱序响应只能展示当前筛选账期 |
| F10 P1 | `viewModel.ts:268,290,427` | 缺失账户字段被补成 ACC-1、余额 0、卡片正常；未知风险变绿色 | 明确响应契约，缺失事实报错或未知 | 不凭空构造金融数值、身份、正常状态 |
| F11 P2 | `api.ts:107` | 只在获取 headers 阶段保留超时，body 卡住可永久 busy | 超时覆盖 body 读取，合并外部取消信号 | 慢 body、断流、非法 JSON 可恢复且不伪造结果 |

前端位置以 `frontend/src/` 为根。F01–F04、F06、F10 有 React/jsdom 或纯函数复现；F05、F07、F09、F11 为代码确认，浏览器网络/多窗口回归必须另做。

## 待验证风险与已知边界（不得标为已利用漏洞）

| 风险 | 证据 / 前提 | 后续验证与验收 |
|---|---|---|
| 真实身份认证与租户隔离 | X-Aegis-Role 自报、固定 demo-user；仓库已声明原型边界 | 默认只监听回环地址；真实对外部署必须从认证会话导出主体/角色，不能信任请求头 |
| 真实 MFA / 真实 IM 平台 | 固定 OTP/模拟人脸、无平台签名；不是银行 MFA | 外部服务配置、签名重放、挑战过期、主体与动作绑定测试后才能声称接入 |
| 任意生成代码的强隔离 | 当前只执行注册 Python 工具，没有任意生成代码入口 | 仍不得把进程内守卫称为 OS 沙箱；容器/进程权限、文件和资源配额另验收 |
| 注入分类覆盖 | 五条正则无法覆盖全部语义攻击；未进行真实外部模型红队 | 绕写、跨语言、工具结果注入用例；确定性权限边界独立生效 |
| 崩溃后幂等/nonce 清理与恢复 | running 记录、确认 nonce、任务状态存在长期保留 | kill -9 / 多 worker / 重启故障矩阵；未知结果先对账，不能超时删除后直接重扣 |
| 哈希链尾部裁剪与整体重算 | 攻击者需直接写 SQLite；本地链无外部锚点 | 外部可信锚点/WORM 才能检出尾裁剪；哈希链有效不等于完整历史可信 |
| 依赖公告版本冲突（已升级消除扫描命中） | 原 pip-audit 命中 certifi 2026.10.18，建议 .19；官方公告列 .18 已修复，描述也指向 .18 | 核对证书包与公告范围，已升级 certifi 2026.10.23 并重扫无命中；不能直接宣称原版本已发生 TLS 劫持 |
| Dev 依赖可利用性（已升级消除扫描命中） | 原 pnpm 命中 Vitest/mocker 3.2.7、tinypool 1.1.1；均为 devDependencies | 已升级 Vitest 4.1.12，当前依赖树不再含受影响 Tinypool，重扫零命中；Tinypool 需原型污染前提，mocker 需插件暴露 WebSocket，本项目未证实远程 RCE |
| 规模与线程资源 | 未做压力测试；原实现每次调用创建线程池、readiness 全链扫描 | 有界执行队列、背压、最大请求体、持续运行与大日志性能验证 |

依赖原始公告：[Vitest 目录穿越](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9)、[mocker 注入](https://github.com/vitest-dev/vitest/security/advisories/GHSA-qxg6-89mg-rqv8)、[Tinypool worker options](https://github.com/tinylibs/tinypool/security/advisories/GHSA-5gmw-xhrv-c9v3)、[Tinypool run options](https://github.com/tinylibs/tinypool/security/advisories/GHSA-85c8-ppgw-ccpr)、[certifi 公告](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)。这里记录版本命中与攻击前提，不把开发依赖风险算作已确认网站 RCE。

## 实施顺序与退出条件

1. 账本、审计与动作执行事务；补偿内部化和防重；并发操作占有。
2. 定时授权、累计风险、角色与 readiness 统一；MFA 与通道隔离。
3. 金额、卡片、预算、理财与 Planner 数据正确性；统一工具契约。
4. 前端提交恢复、错误语义、能力与 fail-closed；依赖、文档与安全回归。

每批必须先通过针对上述反例的回归，再跑现有 lint/build/test、六场景与统一 gate。只修前端禁用不算修复服务端漏洞；只把异常改成 200 不算修复；无证据不标记完成。不承诺有限审查能证明不存在其他漏洞。

## 修复状态与最终验证

本轮确认 37 项后端问题与 11 项前端问题（包含漏洞、数据正确性与体验缺陷）。下表记录代码修复及对应验证；“通过”仅覆盖列出的本地 Mock 反例，不表示真实银行接入或生产安全验收。

| 问题 | 已实施的修复位置（当前文件/函数） | 回归证据 |
|---|---|---|
| B01、B04、B08、B11、B36、B37 | `registry.py:24` 内部工具；`executor.py:69` 执行目的复核；`db.py:190` 动作文件锁；`scheduler.py:910,2411,2630`；`extensions/compensation.py` 的 ReverseTransferTool / ReversePurchaseWealthTool 与 `compensation_reversals` | 伪造反向调用被拒；并发回滚与恢复最多一次；跨用户回放拒绝；已用资金/已赎回持仓禁止重复返款 |
| B03、B05、B06、B07、B19、B20 | `db.py:146` 统一事务；`scheduler.py:166,871,1337` 累计预评估、完整 envelope 与执行前复核；`audit.py:24` 事务内链追加；`trust/idempotency.py` | 600+600 必须 MFA；审计故障余额不变、journal 无假执行；并发 800+800/余额1000 只成功一次；缺 envelope 409；撤权恢复不执行；同键并发稳定冲突 |
| B02、B12、B27、B28、B34 | `main.py:225` 共享 readiness；`scenarios/automation.py:502,1346,1446,1660` 授权记录、子工具链与原子任务完成 | auditor 触发到期 403；1500 预约红色；撤权/到期风险上升拒绝；预算100不预约358；礼物流水与扣款一致；领取后故障不留假 done |
| B09、B10、B13、B14 | `main.py` 确认/对账能力检查；`scheduler.py:910,2790`；`trust/mfa.py` | auditor 拒绝/对账 403；对账不能写 rolled_back；回执更新为 reconciled 且 funds_reversed=false；MFA 错误触发熔断；provider 必须在允许交集中 |
| B15、B16 | `channels/im.py`、`extensions/im.py` 的角色、sender/channel/action 绑定与正文哈希 | 跨发送者确认失败；不同 sender/channel 不串缓存；同消息不同正文 409；OTP 不写明文日志 |
| B17、B18 | `trust/sandbox.py:362,444` 有界池、提交时截止、取消排队 Future、网络 ContextVar；`db.py:146` 提交前后截止检查 | 超时后的迟到写入拒绝；已超时排队任务不启动；无关线程 localhost DNS 仍可用；数据库外副作用仍属 OS 隔离边界 |
| B21、B22、B23、B24、B25、B31、B32、B33 | `planning/llm.py:98` 关键参数/笔数；`planning/rule.py:38` 否定/混合写澄清与真实余额；`registry.py:35,53` 金额及结果校验；`tool_outputs.py` 旧工具业务 Schema；`gateway.py` 显式 Demo 授权；`scenarios/cards.py` 默认实际限额风险 | 错收款人/10冒充100/额外转账被拒；缺参不补金额；次分与非有限数拒绝；坏输出不提交；默认10000红色；否定不挂失；新用户/工具无默认资金权限 |
| B26、B29 | `banking/repository.py:482` 保留已用额度；`scenarios/wealth.py:647` 按市值/实际份额换算与并发条件更新 | 已用8250不清零，额度不能低于已用；全部3000份赎回后份额/市值归零、持仓关闭；成交份额与订单一致 |
| B30、B35 | `scenarios/bills.py` REST 查询复用 scheduler；`audit.py:75` / `main.py` run_id 查询；`scheduler.py` 新确认全流程统一 action/run_id | bill_report 撤权后 REST 403；并发同指令任务的审计链可按 run_id 分开；执行记录包含 step_id，历史日志不改写 |
| F01–F05 | `frontend/src/App.tsx` 的 execute / decide / continueRestoredPending；`session.ts` 提交凭据与待确认队列；`errors.ts` 暂态冲突 | React/jsdom 验证：修改未知提交被阻止；丢响应刷新复用原键；IN_PROGRESS 保留弹窗与键；新查询不清旧确认；恢复采用服务端计划 |
| F06–F11 | `roles.ts` `/authz/me` 能力；各写页面 readiness；`api.ts` body 超时/非法 JSON；`viewModel.ts` 金融事实缺失报错；`ScenariosPage.tsx` 请求序号 | 不就绪授权按钮禁用；能力未知默认拒绝；乱序月报不覆盖当前期；缺账户/余额不造0；未知风险按红色；慢 body 与坏 JSON 可退出等待 |
| 比赛上下文缺口 | `trust/clarification.py:20`、`schemas.py`、`main.py`、`TaskConsolePage.tsx` | 明确选择补充后，缺金额任务可接续“100元”；绑定用户/角色、10分钟、单次消费；同幂等键回放；通用指代与长会话仍待扩展 |

主要新增回归：`backend/tests/test_security_regressions.py` 共 43 项；`frontend/src/security.test.tsx` 8 项 React/jsdom；`api.test.ts` 3 项。现有用例已同步新的安全语义，包括已用额度约束、默认限额红色验证、明确授予测试工具权限与 provider 策略一致性。

### 可复现的验证命令

在 Linux 主线执行，测试只使用隔离的 Mock 库；可以给进程设置临时 AEGIS_DATABASE_PATH，避免模块导入初始化开发用演示库。

```bash
cd /home/lqz5885/aegisbank/dev/aegisbank
export AEGIS_DATABASE_PATH=/tmp/aegisbank-review-import.db
(cd backend && uv run pytest -q)
(cd frontend && pnpm test)
bash scripts/lint.sh
bash scripts/build.sh
(cd backend && uv run python ../scripts/scenario-check.py)
bash scripts/smoke.sh
(cd frontend && pnpm audit)
(cd backend && uv export --no-dev --no-hashes --format requirements-txt > /tmp/aegis-req.txt)
uvx pip-audit -r /tmp/aegis-req.txt
pwsh -NoProfile -File /mnt/d/开发交流/mia03-ether/.dsh-workflow/scripts/gate.ps1 \
  -Repo /home/lqz5885/aegisbank/dev/aegisbank
```

验证记录：

| 检查 | 结果 |
|---|---|
| 完整后端 pytest | 187 项 / 16 文件，通过（含新增 43 项安全回归） |
| 完整前端 Vitest | 53 项 / 7 文件，通过（含 8 项 React/jsdom） |
| lint / build | Ruff、TypeScript、compileall、Vite 构建通过 |
| 六场景脚本 | 29/29，通过 |
| 真实 HTTP smoke | health、planner info、只预览转账、绿色查询与审计链校验通过；审计 valid=true |
| 正常理财申购撤销 | 独立 Mock HTTP 流程余额还原，审计链有效 |
| 输出契约与清单 | 50 个工具均有业务字段输出 Schema；空 Schema / 仅模拟标记 Schema 均为 0；28 条补偿规格，49 个 HTTP 操作 |
| 依赖扫描 | pnpm audit 全部依赖 0 项已知漏洞；pip-audit 生产依赖 0 项，certifi 已升级 2026.10.23 |
| PPT / 简介文件 | PPT ZIP 与 XML 完整，14 页 / 14 备注，统计已同步；简介正文 199 字符（不含空白190），仍无视频文件 |
| 完整 DSH gate | encoding / lint / build / test / security 五阶段 PASS，静态扫描 HIGH=0 / MEDIUM=0 |

交互测试采用 jsdom 30.1.3，已明确 package.json engines 与部署文档：Node 22.x ≥22.22.2 或 24.x ≥24.15.0（另支持 ≥26）；本轮实际 Node v22.23.3。依赖扫描的零命中表示扫描当时未报告已知条目，不证明不存在未知漏洞。

### 迁移、限制与后续工作

- 旧定时任务没有 `scheduled_authorizations` 时拒绝执行，需取消后重新确认创建；不自动给旧任务补造授权。旧审计记录缺 run_id/step_id 时不重写哈希链。
- 未能自动完成的外部交付：真实认证/租户绑定、真实 MFA、真实 IM 签名与主体映射、演示视频录制、实际答辩计时。默认 dev 监听已改为回环地址。
- 仍待验证/生产化：OS 级沙箱、任意数据库外副作用隔离、kill -9 与多 worker 故障矩阵、TTL 清理、按用户熔断、外部审计锚点、长时间压力、真实浏览器多窗口/网络回归。进程内线程超时不能代表任意代码可安全执行。
- 订阅纯查询目前仍按绿色，赛题表中的黄色口径差异未取得组委会解释；一般指代消解和长会话未宣称完成。
- 修复源分支为 `codex/audit-remediation-20261023`；提交与发布记录以 Git 历史为准；Windows 历史副本保持冻结。

