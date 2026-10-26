# fronted

React/TypeScript 页面、组件、API 客户端、样式及前端构建配置。按用户要求命名 fronted，包内原始目录仍为 frontend。

来源：AegisBank Linux 主线；提交 `654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec`；整理日期：2026-10-26。

包含 34 个原仓库文件，全部原样复制，保留仓库相对路径。源码清单及 SHA-256 见同目录 MANIFEST.json。

这是按职责划分的源码资料包，六个包共同组成应用，不能分别独立运行。运行前将六个包内的原始路径合并到同一个新目录，不要改动源仓库。`_PACKAGE` 仅为打包说明。

测试文件、测试运行脚本、归档与非核心历史资料未包含。为保持源码原样，依赖清单中的测试依赖/命令及文档中的历史记录、测试描述未改写；原文指向被排除附件的链接可能不可用。当前仍在调用链上的兼容代码和演示能力保留。

文件列表：

- `frontend/index.html`
- `frontend/package.json`
- `frontend/pnpm-lock.yaml`
- `frontend/pnpm-workspace.yaml`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/components/AuditPage.tsx`
- `frontend/src/components/BankOverviewPage.tsx`
- `frontend/src/components/BreakerBanner.tsx`
- `frontend/src/components/BreakerPanel.tsx`
- `frontend/src/components/CapabilitiesPage.tsx`
- `frontend/src/components/ConfirmationModal.tsx`
- `frontend/src/components/ErrorBoundary.tsx`
- `frontend/src/components/OpsPage.tsx`
- `frontend/src/components/PermissionsPage.tsx`
- `frontend/src/components/ReadinessBanner.tsx`
- `frontend/src/components/ScenariosPage.tsx`
- `frontend/src/components/StepJournalPanel.tsx`
- `frontend/src/components/TaskConsolePage.tsx`
- `frontend/src/components/ui.tsx`
- `frontend/src/errors.ts`
- `frontend/src/main.tsx`
- `frontend/src/risk.ts`
- `frontend/src/roles.ts`
- `frontend/src/session.ts`
- `frontend/src/styles-ux.css`
- `frontend/src/styles.css`
- `frontend/src/twoA.ts`
- `frontend/src/types.ts`
- `frontend/src/useHashRoute.ts`
- `frontend/src/viewModel.ts`
- `frontend/src/vite-env.d.ts`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
