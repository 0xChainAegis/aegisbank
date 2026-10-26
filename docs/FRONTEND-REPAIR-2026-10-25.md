# 前端修复与本轮验收记录

> 2026-10-26 六模块整合：下文代码路径描述修复时的运行工程布局；当前源文件在 `fronted/frontend/`，后端按六包职责保留。运行前在根目录执行 `python3 scripts/assemble.py`，然后进入 `.runtime/`，再使用下文的后端/前端命令。详见 [整合记录](INTEGRATION-2026-10-26.md)。

验收日期：2026-10-25（中国标准时间）。代码基线：`654c986` 加本轮前端补丁。后端代码未修改，全部业务仍使用 Mock Bank Core。

## 修复内容

- 待确认队列会跳过过期项，倒计时实时刷新，到期后显示下一笔；恢复前向服务端重新核对计划、风险与状态。已完成的操作展示关联回执，不再次提交。
- 未决提交在刷新时保留原角色与幂等键，避免另一标签页切换角色后无法查询原请求。MFA 提交期间锁住验证方式与输入。
- 修正月账单、跨场景取消订阅、卡片解挂和单日限额快捷指令，使其与当前 Planner 契约一致；补齐六场景快捷入口。默认规则 Planner 不需要模型密钥。
- 日期与金额分开格式化；每日限额确认摘要读取实际 `daily_limit_cny`。取消的订阅保留历史记录，但不再列为当前异常提醒。
- 非 JSON 错误仍保留 HTTP 状态；明确拒绝与网络结果未知分别处理。失败回执不再推断“资金没有变化”。
- 步骤日志和恢复请求隔离旧任务响应，避免切换任务后旧响应覆盖当前内容。
- 时间快进可指定模拟截止时间，并把后端拒绝原因显示给用户，拒绝时不报成功。权限页面在未就绪与刷新时说明禁用原因。

## 自动验证

- 前端 Vitest：73 项通过，8 个测试文件；TypeScript 检查和 Vite 生产构建通过。
- 后端 pytest：252 项通过，无跳过；在 WSL Ubuntu、Linux Python 3.14.4 下使用 `backend/uv.lock --frozen` 安装依赖。
- 六场景端到端脚本：`scripts/scenario-check.py` 29/29 通过。
- 从实际 TypeScript 源码 AST 提取 14 个快捷入口和概览跨场景入口的完整请求，15/15 通过真实 API；每例独立数据库，5 个绿色直接完成、5 个黄色待确认、5 个红色待确认。该项写操作停在确认前。
- `git diff --check` 通过。此次未运行仓库作者机器专用的外部 WSL 工作流 `gate.ps1`，不宣称该门禁已通过。

## 浏览器验证

通过本机 Vite 与 WSL FastAPI 联调，检查绿色月账单、黄色转账确认、稍后处理和刷新恢复、红色 MFA、审计与哈希链。手机宽度检查未发现页面横向溢出。实际截图与完整日志随交付包提供。

## 复现

后端使用 Linux 或 WSL。`db.py` 依赖 `fcntl` 文件锁，原生 Windows Python 会导入失败，不应删除文件锁或用无操作替身绕过。

```bash
# 终端一，先从仓库根目录生成运行工程
python3 scripts/assemble.py
cd .runtime
cd backend
uv sync --frozen --group dev
uv run uvicorn aegisbank_api.main:app --host 127.0.0.1 --port 8000

# 终端二，从仓库根目录
cd .runtime/frontend
pnpm install --frozen-lockfile
pnpm dev

# 测试，从对应目录执行
# backend: uv run pytest
# frontend: pnpm test && pnpm build
# backend: uv run python ../scripts/scenario-check.py
```

访问 `http://127.0.0.1:5173`。首次初始化使用模拟种子；不要删除正在运行的数据库。Windows 可在 WSL 启动后端、Windows 启动前端，通过本机端口转发联调。

本机前端验证使用 Node 24.19.0 与 npm 安装依赖，未改动 `pnpm-lock.yaml`。Windows 沙箱限制了 pnpm 符号链接；测试将 TEMP/TMP 指向工作目录后通过。源码交付仍保留原 pnpm 锁文件。

## 本轮结论的范围

自动化测试和有限浏览器回归通过，不代表所有交互、自由自然语言或生产安全已经验证。真实认证、真实 MFA、真实 IM 平台接入、OS 级沙箱、通用指代与自由组合仍有待实现。原 `deliverables/` 为历史材料快照；组织仓库的 `deliverables/current/` 包含更新后的技术文档、安全自评和答辩 PPT。PPT 已同步本轮数字与演示指令，正式答辩前仍需试讲，演示视频尚待录制。
