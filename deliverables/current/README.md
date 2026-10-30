# 当前参赛提交材料

本目录保存 2026-10-25 完成并经本机 Office 渲染检查的 Word / PDF / PPT 快照，2026-10-26 随修复版导入团队组织仓库。这些二进制材料中的测试数字和界面描述是当时口径，**未随 2026-10-30 U4 收尾重新渲染**；提交或答辩前若引用当前数字，应以仓库根 README、[U4 交付报告](../../docs/U4-DELIVERY-2026-10-30.md) 和 [API 交接文档](../../docs/API-HANDOFF.md) 为准，并重新导出对应文件。

## 当前验证基线（2026-10-30 U4 收尾）

- 后端：652 passed / 36 个测试文件（0 failed / 0 skipped / 0 xfail；唯一 warning 为 Starlette/httpx 弃用警告）。
- U4 独立回归：6 passed（`backend/backend/tests/test_u4_delivery_regression.py`）。
- 前端：144 passed / 12 个测试文件（jsdom/契约级，不是浏览器 E2E）。
- 根组装器：18 passed；六场景：30/30 passed。
- 工具：51 个；HTTP `/api` 路径：49 个；前端 39 个 `/api` 路径契约全部存在。
- 真实浏览器联调：Edge 156 headless CDP + Vite 代理 + FastAPI + 全新 SQLite，最终仅一笔 -30000 分转账；旧确认 409 `draft_version_conflict`，历史回执妈妈 / 300.00 元。证据见 [U4 报告](../../docs/U4-DELIVERY-2026-10-30.md)。

## 材料索引

- 技术文档（2026-10-25 快照，未随 U4 重渲染）：[Word](02-AegisBank-技术文档.docx) / [PDF](02-AegisBank-技术文档.pdf)。
- 答辩材料（2026-10-25 快照，14 页，未随 U4 重渲染）：[PPTX](03-AegisBank-答辩材料.pptx)。
- 安全自评（2026-10-25 快照，未随 U4 重渲染）：[Word](04-AegisBank-安全自评报告.docx) / [PDF](04-AegisBank-安全自评报告.pdf)。
- 作品简介：[01-作品简介.md](../01-作品简介.md)。
- 演示视频：目前只有[脚本](../04-演示视频脚本.md)，成片尚未录制。
- 源码与部署：先执行 `python3 scripts/assemble.py`，再在生成的 `.runtime/` 中安装依赖和运行；源码包应排除 `.git`、依赖目录、运行数据库和真实配置。当前验证细节见 [README](../../README.md) 与 [07-测试与复现](../07-测试与复现.md)。

报名系统需分别上传四项必交材料；仓库链接不能替代源代码压缩包。根据团队提供的报名页，截止时间为 2026 年 11 月 2 日 18:00（中国标准时间）。

## 边界

U1 正式人工复核仍为 `pending`、真实模型对照仍为 `not_run`；U3 习惯学习/推荐、U5 组合与条件规划未实施。所有金融数据来自 Mock Bank Core，不连接真实银行；没有生产身份认证、真实 MFA、OS 级沙箱或真实 IM 接入。测试通过不等于生产安全认证。
