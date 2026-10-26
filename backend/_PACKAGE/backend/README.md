# backend

FastAPI 入口、配置、数据库、Mock Bank Core、服务装配、依赖锁文件和安装/启动/构建脚本。

来源：AegisBank Linux 主线；提交 `654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec`；整理日期：2026-10-26。

包含 19 个原仓库文件，全部原样复制，保留仓库相对路径。源码清单及 SHA-256 见同目录 MANIFEST.json。

这是按职责划分的源码资料包，六个包共同组成应用，不能分别独立运行。运行前将六个包内的原始路径合并到同一个新目录，不要改动源仓库。`_PACKAGE` 仅为打包说明。

测试文件、测试运行脚本、归档与非核心历史资料未包含。为保持源码原样，依赖清单中的测试依赖/命令及文档中的历史记录、测试描述未改写；原文指向被排除附件的链接可能不可用。当前仍在调用链上的兼容代码和演示能力保留。

文件列表：

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
- `backend/uv.lock`
- `docs/DEVELOPMENT-ENVIRONMENT.md`
- `scripts/bootstrap.sh`
- `scripts/build.sh`
- `scripts/dev.sh`
- `scripts/seed-demo.sh`
