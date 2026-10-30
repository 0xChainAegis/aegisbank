# AegisBank 文档索引

- [U1 独立评测、有界语义补强与未完成边界](U1-NLP-EVALUATION-2026-10-30.md)

- [U2 最小多轮闭环验收（联系人转账）](U2-CONVERSATION-2026-10-30.md)
- [U4 交付回归、真实浏览器联调与文档收尾](U4-DELIVERY-2026-10-30.md)
- [下一步问题修复与升级计划](next-steps/AegisBank-问题修复与升级计划.md)

- [P1补缺、安全回退与最新验收](NLP-P1-COMPLETION-2026-10-28.md)

- [NLP P1 实现、验收与未完成边界](NLP-P1-2026-10-27.md)

当前验证基线（2026-10-30 U4 收尾）：后端 652 项 pytest、前端 144 项 Vitest、组装器 18 项、六场景 30/30、工具 51 个、HTTP `/api` 路径 49 个；前端 39 个 `/api` 路径契约全部匹配。真实浏览器联调、API 冻结和未完成边界见 [U4 报告](U4-DELIVERY-2026-10-30.md)。U1 正式人工复核/真实模型对照、U3/U5 仍未完成。

运行与修改项目先阅读[根目录 README](../README.md)。源码保留在 `fronted/`、`backend/`、`agent/`、`NLP/`、`skills/`、`plans/` 六个职责包中，运行前执行 `python3 scripts/assemble.py` 生成 `.runtime/`。

旧文档中的 `frontend/`、`backend/aegisbank_api/` 等单体路径对应组装后的目录结构；修改源码时回到所属职责包，不直接编辑 `.runtime/`。

## 产品与架构

- [系统架构](ARCHITECTURE.md)
- [银行业务与六场景](BANKING-DOMAIN.md)
- [技术栈](TECH-STACK.md)
- [项目路线图](ROADMAP.md)

## 安全与 NLP

- [安全机制与边界](SECURITY.md)
- [后端安全补强记录](BACKEND-HARDENING-2026-10-24.md)
- [安全修复记录](REMEDIATION-PLAN-2026-10-23.md)
- [NLP 现状与 P0 修复](NLP-ASSESSMENT-AND-PLAN-2026-10-25.md)
- [NLP 后续待办](NLP-BACKLOG.md)

## 体验与验证

- [前端修复与 2026-10-25 验收记录](FRONTEND-REPAIR-2026-10-25.md)
- [真实截图与图片路径](screenshots/README.md)
- [体验问题记录](UX-RECORD.md)
- [体验测试计划](UX-DOGFOODING.md)

## 协作与交付

- [API 交接文档](API-HANDOFF.md)
- [团队工作流](TEAM-WORKFLOW.md)
- [本轮可提交材料](../deliverables/current/README.md)
- [来源与参考边界](UPSTREAM-NOTES.md)
- [第三方参考资料](reference/README.md)

各历史记录保留当时的日期与测试数字；187/53/29、252/73、646 等旧数字只代表对应历史快照，当前口径以 U4 报告和根 README 为准。当前启动方式以根 README 为准，职责包整合后的验证结果以当前 CI 为准。
