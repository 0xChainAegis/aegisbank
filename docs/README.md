# AegisBank 文档索引

- [P1补缺、安全回退与最新验收](NLP-P1-COMPLETION-2026-10-28.md)

- [NLP P1 实现、验收与未完成边界](NLP-P1-2026-10-27.md)

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

各历史记录保留当时的日期与测试数字。当前启动方式以根 README 为准，职责包整合后的验证结果以当前 CI 为准。
