# 开发环境与验收记录

更新日期：2026-10-23（阶段 1 信任工程 + 阶段 2B 六场景覆盖完成后）
适用仓库：<https://github.com/LQZ5885/aegisbank>
总规划：[MASTER-PLAN.md](MASTER-PLAN.md)

## 1. 目录与角色

| 位置 | 角色 | 状态 |
|---|---|---|
| `/home/lqz5885/aegisbank/dev/aegisbank`（WSL2 ext4） | **开发主线**，所有开发、测试与提交在此完成 | 活跃 |
| `D:\开发交流\mia03-ether\aegisbank智能体`（Windows 11） | 最初原型 / 历史副本 | **已冻结**，不再开发，仅作展示与单向备份 |
| `/home/lqz5885/aegisbank/backup/` | Windows 文档备份与 SHA-256 校验清单 | 2026-10-22 建立 |
| `/home/lqz5885/aegisbank/upstream/aegis-agent/` | 上游参考仓库（只读） | 参考 |

迁移说明：2026-10-22 起项目从「Windows 目录 + `/mnt/d`」迁到 WSL 原生 ext4 分区，原因是 `/mnt` 挂载 I/O 较慢、Windows 与 Linux 在换行符与权限上存在差异、两套环境容易漂移。Windows 侧现在只保留展示与推送用途。

## 2. 主机与引擎

| 项 | 值 |
|---|---|
| Windows 驾驶舱 | Git、Node.js v24、Python 3.14（用于驱动 WSL、运行工作流脚本与 GitHub 推送） |
| WSL 发行版 | Ubuntu 24.04（WSL2） |
| Linux 工具链 | git、Node v22.23.3、pnpm 12.10.1、Python 3.12.3、uv 0.12.24、ruff 0.16.10、pytest 9.1.1、jq、gitleaks、shellcheck |
| 工作流目录（WSL 可见） | `/mnt/d/开发交流/mia03-ether/.dsh-workflow` |
| 分区挂载 | ext4 loop 镜像 `~/aegisbank.ext4` → `/home/lqz5885/aegisbank`（20 GB，已写入 `/etc/fstab`） |

## 3. 项目依赖（锁定）

后端：

```text
Python 3.12.3
FastAPI / Pydantic v2 / uvicorn / httpx
pytest 9.1.1 · ruff 0.16.10
uv lock: backend/uv.lock
虚拟环境: backend/.venv
```

前端：

```text
React 19 · TypeScript 5.9 · Vite 7.3.7 · Vitest 3.2.7
pnpm lock: frontend/pnpm-lock.yaml
依赖目录: frontend/node_modules
```

## 4. 验收记录（2026-10-23，阶段 1 + 2B 实现后）

| 命令 | 结果 |
|---|---|
| `cd backend && uv run pytest` | 后端 **85 项** pytest 全部通过（8 个测试文件；其中 `test_trust.py` 17 条） |
| `cd frontend && pnpm test` | 前端 **14 个** Vitest 用例通过（2 个测试文件） |
| HTTP 接口枚举 | **29 个** `/api` 接口（核心 16 + 场景 13） |
| 工具目录 | **34 个**（核心 9 + 场景 25） |
| `bash scripts/lint.sh` / `build.sh` / `smoke.sh` | 本轮文档同步未重跑；交付前需补跑完整门禁 |
| `gate.ps1`（WSL 内调用） | 纯文档改动走 docs 快速通道（encoding / lint / build / test skip / security），提交会带「纯文档改动」标记 |
| 依赖安装 | 依赖来自此前 `bash scripts/bootstrap.sh` 的锁定安装，`uv.lock` 与 `pnpm-lock.yaml` 未变 |

补充说明：本轮改动为阶段 1 信任工程、2B 六场景模块（后端/前端）与文档同步；测试数字来自实际 `pytest` / `vitest` 输出，实现变更后必须重新核对。纯文档同步提交按约定走门禁 docs 快速通道，交付前需补跑一次 lint / build / smoke。

## 5. 本地启动

```bash
cd /home/lqz5885/aegisbank/dev/aegisbank
bash scripts/bootstrap.sh   # 首次安装依赖
bash scripts/dev.sh         # 同时启动后端与前端
```

- UI：<http://127.0.0.1:5173>
- API：<http://127.0.0.1:8000>
- 健康检查：<http://127.0.0.1:8000/api/health>
- 就绪检查：<http://127.0.0.1:8000/api/health/ready>
- Swagger：<http://127.0.0.1:8000/docs>

红色演示链路使用本地演示验证码 `246810`，只用于演示，不得用于任何真实环境。时间维度演示可使用 `POST /api/automation/run-due`（可传 `now` 做时间快进）；如需后台轮询，设置 `AEGIS_AUTOMATION_ENABLED=true`。

## 6. 复验方式

```bash
bash scripts/lint.sh
bash scripts/build.sh
bash scripts/test.sh
bash scripts/smoke.sh
```

门禁（在 WSL Ubuntu 中执行）：

```bash
cd /home/lqz5885/aegisbank/dev/aegisbank
pwsh -NoProfile -File /mnt/d/开发交流/mia03-ether/.dsh-workflow/scripts/gate.ps1 \
  -Repo /home/lqz5885/aegisbank/dev/aegisbank -Verbose
```

提交：

```bash
pwsh -NoProfile -File /mnt/d/开发交流/mia03-ether/.dsh-workflow/scripts/checkpoint.ps1 \
  -Repo /home/lqz5885/aegisbank/dev/aegisbank -Message "docs: ..."
```

推送（WSL 内没有配置凭据，使用 Windows 侧 git 访问同一目录）：

```powershell
$unc = '\\wsl.localhost\Ubuntu-24.04\home\lqz5885\aegisbank\dev\aegisbank'
git -C $unc push origin main
```

## 7. 已知限制与警告

- `pytest(win)`：Windows 侧没有 pytest 属于预期，项目门禁使用 WSL runner；
- `security/credential-file`：`.env.example` 因文件名启发式被标记，只包含本地演示变量，无真实凭据；
- 纯文档改动时门禁 test 阶段会走快速通道并给出 `unverified` 结论，提交会带 `Note: 纯文档改动`，需在交付前补跑一次完整测试；
- WSL 分区为 loop 镜像，宿主机异常关机后如未自动挂载，需执行 `sudo mount /home/lqz5885/aegisbank`；
- 演示数据固定在 SQLite 中，重复演示前建议删除 `backend/data/aegisbank.db` 后重启以恢复种子数据（六场景种子均幂等）。
