# 开发环境与初始化验收记录

初始化日期：2026-10-19  
项目目录：`D:\开发交流\mia03-ether\aegisbank智能体`  
工作流：`D:\开发交流\mia03-ether\.dsh-workflow`（脚本来源与本机 `D:\电脑软件修改\.dsh-workflow` 一致）

## 1. 主机与引擎

| 项 | 状态 |
|---|---|
| Windows 驾驶舱 | Git 2.55.0、Node.js v24.19.0、Python 3.14.6 |
| WSL 发行版 | Ubuntu 24.04.5 LTS（WSL2，内核 6.18） |
| WSL 工具链 | git、node v22、pnpm 12.10.1、uv 0.12.24、ruff、pytest、jq、gitleaks、shellcheck、make、gcc |
| 工作流体检 | 23 项 OK，3 项 WARN，0 项 FAIL（警告均为预期/误报，见第 6 节） |
| PATH 隔离 | 已剥离所有 `/mnt/*` Windows 路径泄漏 |
| 子工作区 | 已接入 DSH hooks，首次骨架提交 `669c1a6`，完整初始化提交 `29f460c` |

## 2. 已安装的项目依赖

### 后端

```text
Python 3.12.3
FastAPI 0.148.0
Pydantic 2.14.1
pytest 9.1.1
ruff 0.17.1
uv lock: backend/uv.lock
虚拟环境: backend/.venv
```

### 前端

```text
React 19.3.1
TypeScript 5.9.3
Vite 7.3.7
Vitest 3.2.7
pnpm lock: frontend/pnpm-lock.yaml
依赖目录: frontend/node_modules
```

## 3. 已执行的验收

| 命令 | 结果 |
|---|---|
| `bash scripts/bootstrap.sh` 等价步骤 | `uv sync` 成功；`pnpm install` + esbuild 构建批准成功 |
| `bash scripts/lint.sh` | ruff 通过；TypeScript `tsc --noEmit` 通过 |
| `bash scripts/build.sh` | 后端 compileall 通过；Vite 生产包构建成功 |
| `bash scripts/test.sh` | 后端 6 项测试通过；前端 3 项测试通过 |
| `bash scripts/smoke.sh` | `/api/health` 正常；绿色账单工具执行成功；审计链 `valid=true` |
| DSH `gate.ps1` | 五阶段全部 PASS，提交 `29f460c` 带 `Verified-By: dsh-gate` |
| 全量密钥扫描 | 48 个文件，0 findings |

## 4. 本地启动

```bash
bash scripts/dev.sh
```

- UI: <http://127.0.0.1:5173>
- API: <http://127.0.0.1:8000>
- Swagger: <http://127.0.0.1:8000/docs>

红色演示链路使用本地演示验证码 `246810`。该值只用于演示，不得用于任何真实环境。

## 5. 复验方式

```bash
bash scripts/bootstrap.sh
bash scripts/lint.sh
bash scripts/build.sh
bash scripts/test.sh
bash scripts/smoke.sh
```

在 Windows 侧重新运行 DSH 工作流体检：

```powershell
cd D:\开发交流\mia03-ether
.\.dsh-workflow\scripts\doctor.ps1
```


## 6. Doctor 警告说明

- `pytest(win)`：Windows 侧没有 pytest 是预期情况，项目门禁使用 WSL runner，Linux 引擎内 pytest 正常。
- `sync/remotes`：当前工作区使用的是脱敏工作流副本，没有配置同步远端；不影响本地门禁、hooks 与提交。
- `security/credential-file`：`.env.example` 因文件名启发式被标记；该文件只包含本地演示变量和演示 OTP，没有任何真实凭据。DSH 全量密钥扫描为 0 命中。

## 7. 当前提交

```text
29f460c feat: 初始化 AegisBank 可信智能体开发环境与最小闭环
Status: verified
Verified-By: dsh-gate
Stages: encoding=pass lint=pass build=pass test=pass security=pass
```
