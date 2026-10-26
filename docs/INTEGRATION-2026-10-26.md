# 六模块源码与组织主线整合记录

日期：2026-10-26。团队集成仓库为 [0xChainAegis/aegisbank](https://github.com/0xChainAegis/aegisbank)。本次整合保留六个职责包作为唯一业务源码入口，同时恢复可运行工程、测试、文档与展示资产之间的联系。

## 整合原因与历史

组织 `main` 已有六包分类提交，原作者主线则包含完整应用路径、测试与后续前端修复。六包各自只持有同一 Python 或前端工程的一部分；原资料导出又排除了测试，直接进入某一包启动不能得到完整系统。

本次将组织主线与原作者开发历史合流，保留两边已有提交，而不是覆盖其中一方目录或重新初始化 Git。重要来源为：

- 原作者 P0 基线 `654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec`：金额规范化与不支持语义的澄清防线。
- 前端修复 `49201c2846a114f32ec458b295a788548be1c0ee`：任务与确认恢复、MFA 输入锁定、快捷指令和日期金额显示等。
- 协作与复现评审 `e2fd54424e07d8a2e45f352509f7f306b879f27c`：在前述修复之上整理组织协作、CI、当前材料及来源边界。
- 组织原有 `ef8ebca` 六包分类与 `82536d2` 产品介绍提交继续保留。整合采用正常合并，不以强制推送抹去它们。

这些 SHA 是来源定位，不是本次尚待生成的最终整合提交。最终版本由实际合并提交、CI 与相应验收结果确定。

## 源码位置与生成工程

- `fronted/frontend/` 为前端唯一修改入口，沿用队友已提交的 `fronted` 名称。
- `backend/backend/` 为 API 装配、数据库、Mock Bank Core、依赖与后端测试；`backend/scripts/` 保留安装、运行和验证脚本。
- `agent/backend/` 为网关、调度、执行器、信任、MFA、熔断、补偿和审计。
- `NLP/backend/` 为金额解析、Planner、语义安全和受限澄清。
- `plans/backend/` 为计划契约与编译器；`skills/backend/` 为工具和银行场景。

根目录 `docs/`、`deliverables/` 和 README 是团队阅读、验收及比赛材料入口；它们不是另一份业务实现。包内旧文档保留历史或内部源码说明，不分别发展新的团队主线。旧 `plans/README.md`、`plans/AGENTS.md` 不进入运行组装白名单；当前工程协作以根 `AGENTS.md` 为准。

运行 `python3 scripts/assemble.py`，按六包白名单将原工程路径组合到 `.runtime/`，然后在该目录安装依赖、测试和启动。`.runtime/` 是生成目录，不提交、不手工修改。源文件变化后重新组装；不得通过修改生成副本来“修复”运行问题而遗漏源码。

Git checkout 中组装读取已跟踪或未被忽略的新源文件；没有 `.git` 的源码归档使用同一白名单安全扫描，仍可组装。已有 Git checkout 中的 Git 命令失败会直接报错，不静默转为归档扫描。`_PACKAGE`、隐藏文件、本地依赖、缓存、构建产物和运行数据库均不作为输入；`backend/.env.example` 是唯一显式隐藏文件特例。不同源映射到同一目标且内容冲突时，组装在写入前失败；符号链接和路径越界同样拒绝。生成器只管理其清单记录的源文件，不清理用户数据库、虚拟环境或依赖目录。

## 恢复与修复映射

后端业务文件沿用 P0 基线，未新增执行旁路。恢复的后端测试位于 `backend/backend/tests/`，测试与复现脚本位于 `backend/scripts/`。前端测试和修复映射回 `fronted/frontend/src/`，不再维护一个与六包并行的根 `frontend/`。

修复详情和既有验证证据见[前端修复记录](FRONTEND-REPAIR-2026-10-25.md)。该记录中的前端 73 项、后端 252 项和场景 29/29 是相应修复版的已记录结果；本次目录整合仍须在组装工程重新验证，不能把历史通过数字当作本次实际输出。当前 CI 和本地命令见根 README 与 `.github/workflows/ci.yml`。

README 图片使用仓库内实际存在的相对路径；截图和当前参赛材料恢复到根文档及交付入口。旧材料中的历史基线明确保留为快照，不能将未录制的视频、未完成的 NLP 阶段或未核验能力写成完成。

## 清单来源和行尾处理

每包的 `_PACKAGE/<包名>/MANIFEST.json` 重新记录当前运行白名单的 `path`、`runtime_path`、`bytes` 和 `sha256`。脚本复用组装器的只读源计划，使路径、安全过滤和冲突检查保持一致。

`source_commit` 保留为原始导出的 P0 基线；它不表示所有文件仍是该提交的原样副本，也不表示最终整合提交。`current_hashes` 说明当前哈希范围；前端清单另列实际修复与评审提交，区分源码变化和历史来源。MIT 许可证作为元数据保留，不混入运行源文件数量。

更新命令为：

```bash
python3 scripts/update_manifests.py
python3 scripts/update_manifests.py --check
```

首次 Windows 检出使部分旧包为 CRLF，恢复文件和根 `.gitattributes` 使用 LF。本次显式执行 `--normalize-line-endings`，仅将白名单内 UTF-8 文本的 CRLF 规范化为 LF，记录处理日志后再计算哈希；不改变业务语义、二进制或许可声明。默认更新和 `--check` 不隐式重写源码。提交前核对清单与 Git 规范化后的实际内容，避免新克隆出现行尾导致的哈希不一致。

根 `文件清单.csv` 与 `排除清单.csv` 是最初导出的历史快照，不再代表当前文件状态。尤其原“测试被排除”记录不能解读为整合后没有测试；当前源码由六包文件和新 MANIFEST 确定。

## 不变的执行边界

全部银行事实仍来自 Mock Bank Core，不连接真实银行或支付网络。Planner 只生成候选；工具及补偿继续经过统一网关、风险复检、分级确认与演示 MFA、ActionEnvelope、ToolExecutor、SandboxGuard 和审计。风险只能保持或上调，服务未就绪时写入关闭，结果未知时不得自动重试或假设未产生变化。

P0 已落地；P1–P4 为[后续待办](NLP-BACKLOG.md)，本次没有实现通用上下文、对话纠错或任意条件与组合规划。真实认证、真实 MFA、真实 IM 平台和 OS 级隔离的边界同样保持不变。

## 本轮实际验证

在当前六包组装的 `.runtime/` 上重新运行后：

- 后端 pytest **252 项通过**；六场景脚本 **29/29 通过**。后端在 Linux / WSL 环境运行。
- 前端 Vitest **73 项通过**，TypeScript 检查和 Vite 生产构建通过。
- 根组装器边界测试 **18 项通过**，包含无 `.git` 源码归档、安全过滤及失败路径。
- 六包 MANIFEST 的 **140 条**当前源记录均与实际字节长度和 SHA-256 一致；Git clean 过滤后的 canonical blob 与这些源字节一致，未发现行尾差异。
- 六包映射的 **60 个** `backend/aegisbank_api/` 业务文件与 `654c986` 的原始 Git 内容逐一相同，后端业务语义未因整合改变。

上述是本轮本地与 WSL 验证结果。远端 GitHub Actions 仍须在实际推送后运行；本记录不宣称远端 CI 已通过，也不宣称运行了原作者机器专用的 DSH 门禁。

## AegisAgent 参考与许可

本次只读核对了 [AegisAgent README](https://github.com/0xChainAegis/aegis-agent/blob/082ad51845030ff52e652dab099dccc1f1c06d93/README.md) 和 [LICENSE](https://github.com/0xChainAegis/aegis-agent/blob/082ad51845030ff52e652dab099dccc1f1c06d93/LICENSE)，参考快照为 `082ad51845030ff52e652dab099dccc1f1c06d93`。其 MIT 许可保留 `Copyright (c) 2026 0xChainAegis`；AegisBank 自身现有 MIT 声明 `Copyright (c) 2026 LQZ5885` 保持不变。实际复制代码或素材时应一并保留对应许可与来源。

可以借鉴其产品介绍、证据链接、独立快速开始和功能边界的组织方式，以及“模型只整理草稿、策略决定执行”的原则。其链上钱包、Gas 储备、Owner 签名、Chainlink 与跨链功能不进入 AegisBank 银行原型主流程；本次没有复制其业务模块或素材，也不能把其测试网或真实模型证据用作 AegisBank 的验证成绩。进一步来源说明见[上游参考记录](UPSTREAM-NOTES.md)。
