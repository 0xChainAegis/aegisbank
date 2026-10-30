# agent 源码包说明

权限网关、动态风险、调度、执行守卫、MFA、补偿、熔断和审计。

六个分类目录保留为团队源码修改入口。它们相互依赖，不能作为六个独立应用分别启动；在仓库根目录运行 `python3 scripts/assemble.py`，即可组装到 `.runtime/` 后按[根 README](../../../README.md)启动和验证。生成目录不是第二份维护源码，不应手工修改或提交。

## 来源和当前状态

原始导出基线为 `654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec`。同目录 `MANIFEST.json` 中的 `source_commit` 仅表示该历史起点，不是整合最终提交，也不表示当前文件全部原样复制。

本次整合恢复或更新必要的验证与说明材料；业务执行链没有新增旁路。

当前运行白名单包含 **31 个文件**，`bytes` 和 `sha256` 记录这些文件的当前字节；`path` 相对本分类目录，`runtime_path` 表示组装后的路径。后端测试、前端测试和验证脚本已经按职责恢复，不再采用最初资料包的“排除全部测试”口径。

根 `docs/` 和 `deliverables/` 是团队阅读、验收及比赛材料入口；包内旧文档保留背景，不单独维护新主线。旧 `plans/README.md` 和 `plans/AGENTS.md` 属历史来源说明，不进入运行组装白名单。`_PACKAGE` 为来源、许可与校验元数据，不复制进 `.runtime/`。

## 更新和核验

在仓库根目录执行 `python3 scripts/update_manifests.py` 更新六包清单，或加 `--check` 仅核验。需要与仓库 LF 规则对齐时，显式加 `--normalize-line-endings`，脚本会记录行尾格式处理；默认更新与检查不会隐式改写源码。

Git checkout 中扫描已跟踪或未被忽略的新文件；没有 `.git` 的源码归档使用同一白名单安全扫描。已有 Git checkout 中的 Git 命令错误会停止处理，不会静默改用归档扫描。真实 `.env`、本地数据、依赖、缓存和构建产物不进入清单。MIT 许可及原作者声明保留在同目录 `LICENSE`。

整合原因、历史与修复映射见[整合记录](../../../docs/INTEGRATION-2026-10-26.md)。根 `文件清单.csv` 和 `排除清单.csv` 是最初导出的历史快照，不是当前文件或测试状态的权威清单。

## 当前运行源文件

- `backend/aegisbank_api/audit.py`
- `backend/aegisbank_api/channels/__init__.py`
- `backend/aegisbank_api/channels/im.py`
- `backend/aegisbank_api/compensation.py`
- `backend/aegisbank_api/domain.py`
- `backend/aegisbank_api/executor.py`
- `backend/aegisbank_api/extensions/README.md`
- `backend/aegisbank_api/extensions/__init__.py`
- `backend/aegisbank_api/extensions/authz.py`
- `backend/aegisbank_api/extensions/breaker.py`
- `backend/aegisbank_api/extensions/compensation.py`
- `backend/aegisbank_api/extensions/im.py`
- `backend/aegisbank_api/extensions/mfa.py`
- `backend/aegisbank_api/extensions/sandbox.py`
- `backend/aegisbank_api/gateway.py`
- `backend/aegisbank_api/risk.py`
- `backend/aegisbank_api/risk_rules.py`
- `backend/aegisbank_api/scheduler.py`
- `backend/aegisbank_api/trust/__init__.py`
- `backend/aegisbank_api/trust/action_envelope.py`
- `backend/aegisbank_api/trust/authz.py`
- `backend/aegisbank_api/trust/circuit_breaker.py`
- `backend/aegisbank_api/trust/drafts.py`
- `backend/aegisbank_api/trust/evidence.py`
- `backend/aegisbank_api/trust/idempotency.py`
- `backend/aegisbank_api/trust/mfa.py`
- `backend/aegisbank_api/trust/pause.py`
- `backend/aegisbank_api/trust/readiness.py`
- `backend/aegisbank_api/trust/sandbox.py`
- `backend/aegisbank_api/trust/state_machine.py`
- `docs/SECURITY.md`
