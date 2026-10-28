# fronted 源码包说明

React 控制台、API 类型与请求、确认和恢复交互、样式与前端回归测试。

六个分类目录保留为团队源码修改入口。它们相互依赖，不能作为六个独立应用分别启动；在仓库根目录运行 `python3 scripts/assemble.py`，即可组装到 `.runtime/` 后按[根 README](../../../README.md)启动和验证。生成目录不是第二份维护源码，不应手工修改或提交。

## 来源和当前状态

原始导出基线为 `654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec`。同目录 `MANIFEST.json` 中的 `source_commit` 仅表示该历史起点，不是整合最终提交，也不表示当前文件全部原样复制。

前端修复来自 `49201c2846a114f32ec458b295a788548be1c0ee`，组织协作与可复现性评审版本为 `e2fd54424e07d8a2e45f352509f7f306b879f27c`。

当前运行白名单包含 **48 个文件**，`bytes` 和 `sha256` 记录这些文件的当前字节；`path` 相对本分类目录，`runtime_path` 表示组装后的路径。后端测试、前端测试和验证脚本已经按职责恢复，不再采用最初资料包的“排除全部测试”口径。

根 `docs/` 和 `deliverables/` 是团队阅读、验收及比赛材料入口；包内旧文档保留背景，不单独维护新主线。旧 `plans/README.md` 和 `plans/AGENTS.md` 属历史来源说明，不进入运行组装白名单。`_PACKAGE` 为来源、许可与校验元数据，不复制进 `.runtime/`。

## 更新和核验

在仓库根目录执行 `python3 scripts/update_manifests.py` 更新六包清单，或加 `--check` 仅核验。需要与仓库 LF 规则对齐时，显式加 `--normalize-line-endings`，脚本会记录行尾格式处理；默认更新与检查不会隐式改写源码。

Git checkout 中扫描已跟踪或未被忽略的新文件；没有 `.git` 的源码归档使用同一白名单安全扫描。已有 Git checkout 中的 Git 命令错误会停止处理，不会静默改用归档扫描。真实 `.env`、本地数据、依赖、缓存和构建产物不进入清单。MIT 许可及原作者声明保留在同目录 `LICENSE`。

整合原因、历史与修复映射见[整合记录](../../../docs/INTEGRATION-2026-10-26.md)。根 `文件清单.csv` 和 `排除清单.csv` 是最初导出的历史快照，不是当前文件或测试状态的权威清单。

## 当前运行源文件

- `frontend/index.html`
- `frontend/package.json`
- `frontend/pnpm-lock.yaml`
- `frontend/pnpm-workspace.yaml`
- `frontend/src/App.tsx`
- `frontend/src/api.test.ts`
- `frontend/src/api.ts`
- `frontend/src/components/AuditPage.tsx`
- `frontend/src/components/BankOverviewPage.tsx`
- `frontend/src/components/BreakerBanner.tsx`
- `frontend/src/components/BreakerPanel.tsx`
- `frontend/src/components/BusinessReceipt.tsx`
- `frontend/src/components/CapabilitiesPage.tsx`
- `frontend/src/components/ConfirmationModal.tsx`
- `frontend/src/components/ErrorBoundary.tsx`
- `frontend/src/components/OpsPage.tsx`
- `frontend/src/components/PermissionsPage.tsx`
- `frontend/src/components/ReadinessBanner.tsx`
- `frontend/src/components/ScenariosPage.tsx`
- `frontend/src/components/StepJournalPanel.tsx`
- `frontend/src/components/TaskConsolePage.tsx`
- `frontend/src/components/TrialGuide.tsx`
- `frontend/src/components/businessPages.test.tsx`
- `frontend/src/components/nlpScheduleReceipts.test.tsx`
- `frontend/src/components/trialReceipt.test.tsx`
- `frontend/src/components/ui.tsx`
- `frontend/src/confirmationProduct.test.tsx`
- `frontend/src/errors.test.ts`
- `frontend/src/errors.ts`
- `frontend/src/main.tsx`
- `frontend/src/risk.test.ts`
- `frontend/src/risk.ts`
- `frontend/src/roles.ts`
- `frontend/src/security.test.tsx`
- `frontend/src/session.test.ts`
- `frontend/src/session.ts`
- `frontend/src/styles-product.css`
- `frontend/src/styles-ux.css`
- `frontend/src/styles.css`
- `frontend/src/twoA.test.ts`
- `frontend/src/twoA.ts`
- `frontend/src/types.ts`
- `frontend/src/useHashRoute.ts`
- `frontend/src/viewModel.test.ts`
- `frontend/src/viewModel.ts`
- `frontend/src/vite-env.d.ts`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
