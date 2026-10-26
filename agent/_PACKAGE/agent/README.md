# agent

DAG 调度、权限网关、动态风险、执行守卫、审计、补偿、信任层、渠道与横切安全扩展。

来源：AegisBank Linux 主线；提交 `654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec`；整理日期：2026-10-26。

包含 30 个原仓库文件，全部原样复制，保留仓库相对路径。源码清单及 SHA-256 见同目录 MANIFEST.json。

这是按职责划分的源码资料包，六个包共同组成应用，不能分别独立运行。运行前将六个包内的原始路径合并到同一个新目录，不要改动源仓库。`_PACKAGE` 仅为打包说明。

测试文件、测试运行脚本、归档与非核心历史资料未包含。为保持源码原样，依赖清单中的测试依赖/命令及文档中的历史记录、测试描述未改写；原文指向被排除附件的链接可能不可用。当前仍在调用链上的兼容代码和演示能力保留。

文件列表：

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
- `backend/aegisbank_api/trust/evidence.py`
- `backend/aegisbank_api/trust/idempotency.py`
- `backend/aegisbank_api/trust/mfa.py`
- `backend/aegisbank_api/trust/pause.py`
- `backend/aegisbank_api/trust/readiness.py`
- `backend/aegisbank_api/trust/sandbox.py`
- `backend/aegisbank_api/trust/state_machine.py`
- `docs/SECURITY.md`
