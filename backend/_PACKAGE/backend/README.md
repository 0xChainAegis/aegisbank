# backend 源码包说明

FastAPI 入口、配置、SQLite 与 Mock Bank Core、依赖、运行脚本和后端测试。

六个分类目录保留为团队源码修改入口。它们相互依赖，不能作为六个独立应用分别启动；在仓库根目录运行 `python3 scripts/assemble.py`，即可组装到 `.runtime/` 后按[根 README](../../../README.md)启动和验证。生成目录不是第二份维护源码，不应手工修改或提交。

## 来源和当前状态

原始导出基线为 `654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec`。同目录 `MANIFEST.json` 中的 `source_commit` 仅表示该历史起点，不是整合最终提交，也不表示当前文件全部原样复制。

本次整合恢复或更新必要的验证与说明材料；业务执行链没有新增旁路。

当前运行白名单包含 **51 个文件**，`bytes` 和 `sha256` 记录这些文件的当前字节；`path` 相对本分类目录，`runtime_path` 表示组装后的路径。后端测试、前端测试和验证脚本已经按职责恢复，不再采用最初资料包的“排除全部测试”口径。

根 `docs/` 和 `deliverables/` 是团队阅读、验收及比赛材料入口；包内旧文档保留背景，不单独维护新主线。旧 `plans/README.md` 和 `plans/AGENTS.md` 属历史来源说明，不进入运行组装白名单。`_PACKAGE` 为来源、许可与校验元数据，不复制进 `.runtime/`。

## 更新和核验

在仓库根目录执行 `python3 scripts/update_manifests.py` 更新六包清单，或加 `--check` 仅核验。需要与仓库 LF 规则对齐时，显式加 `--normalize-line-endings`，脚本会记录行尾格式处理；默认更新与检查不会隐式改写源码。

Git checkout 中扫描已跟踪或未被忽略的新文件；没有 `.git` 的源码归档使用同一白名单安全扫描。已有 Git checkout 中的 Git 命令错误会停止处理，不会静默改用归档扫描。真实 `.env`、本地数据、依赖、缓存和构建产物不进入清单。MIT 许可及原作者声明保留在同目录 `LICENSE`。

整合原因、历史与修复映射见[整合记录](../../../docs/INTEGRATION-2026-10-26.md)。根 `文件清单.csv` 和 `排除清单.csv` 是最初导出的历史快照，不是当前文件或测试状态的权威清单。

## 当前运行源文件

- `.env.example`
- `backend/README.md`
- `backend/aegisbank_api/__init__.py`
- `backend/aegisbank_api/banking/__init__.py`
- `backend/aegisbank_api/banking/models.py`
- `backend/aegisbank_api/banking/repository.py`
- `backend/aegisbank_api/config.py`
- `backend/aegisbank_api/db.py`
- `backend/aegisbank_api/demo_seed.py`
- `backend/aegisbank_api/main.py`
- `backend/aegisbank_api/schemas.py`
- `backend/aegisbank_api/services.py`
- `backend/pyproject.toml`
- `backend/tests/conftest.py`
- `backend/tests/test_api.py`
- `backend/tests/test_api_handoff_examples.py`
- `backend/tests/test_authz.py`
- `backend/tests/test_automation.py`
- `backend/tests/test_bill_report_accounting.py`
- `backend/tests/test_bills.py`
- `backend/tests/test_breaker.py`
- `backend/tests/test_breaker_business_effects.py`
- `backend/tests/test_card_reference_conflicts.py`
- `backend/tests/test_cards.py`
- `backend/tests/test_compensation.py`
- `backend/tests/test_im_channel.py`
- `backend/tests/test_internal_transfer_accounting.py`
- `backend/tests/test_mfa.py`
- `backend/tests/test_nlp_safety.py`
- `backend/tests/test_p0_core_feedback.py`
- `backend/tests/test_p0_nlp_feedback.py`
- `backend/tests/test_planner.py`
- `backend/tests/test_sandbox.py`
- `backend/tests/test_scenario_target_assertions.py`
- `backend/tests/test_scheduled_transfer_reauthorization.py`
- `backend/tests/test_security_regressions.py`
- `backend/tests/test_semantics.py`
- `backend/tests/test_subscription_cancel.py`
- `backend/tests/test_transfers.py`
- `backend/tests/test_trust.py`
- `backend/tests/test_wealth.py`
- `backend/uv.lock`
- `docs/DEVELOPMENT-ENVIRONMENT.md`
- `scripts/bootstrap.sh`
- `scripts/build.sh`
- `scripts/dev.sh`
- `scripts/lint.sh`
- `scripts/scenario-check.py`
- `scripts/seed-demo.sh`
- `scripts/smoke.sh`
- `scripts/test.sh`
