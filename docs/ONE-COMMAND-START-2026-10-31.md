# 一键启动实现与验证（2026-10-31）

仓库根目录提供三个入口：Linux/WSL 运行 `bash start.sh`；Windows PowerShell 运行 `.\start.ps1`；Windows CMD 运行 `start.cmd`。PowerShell/CMD 入口只负责把当前仓库路径转换为 WSL 路径，再委托同一份 `bash start.sh`，不提供原生 Windows Python 运行路径。macOS 原生入口暂不在本轮验证范围。

三个入口使用同一套前置要求：Python 3.11+（含 venv/pip）和受支持的 Node.js（含 npm）；入口不要求先全局安装 uv/pnpm。

## Windows 命令修复与复验（2026-10-31）

用户反馈：复制 `powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1` 后未能启动服务。该相对路径依赖当前目录含当前版本脚本；作者的 Windows 历史副本实际没有 `start.ps1/start.cmd`，另一旧 Linux 检出也没有这两个文件，因此只提供相对命令不能定位开发主线。本轮没有获得用户原始错误全文，不将路径问题认定为唯一根因。

本轮检查还发现测试进程的 `PATHEXT` 只有 `.CPL`（机器级配置仍含 `.EXE`），PowerShell 的 `& wsl.exe` 会按文件关联启动，提前返回且可能不设置退出码。旧实现因此存在将“发出了调用”误当作“同步执行完成”的问题。本轮没有修改进程、用户或机器的环境配置；产品通过显式进程创建避免文件关联。

README 首选入口改为从任意 Windows 当前目录启动指定发行版、指定 Linux 仓库的 WSL：PowerShell 使用 `Start-Process ... -NoNewWindow -Wait`，CMD 直接调用 `wsl.exe`；作者本机路径与其他电脑的克隆流程分别说明。无需先进入 Windows 仓库，也不依赖默认发行版。Python/Node 的现有要求保持不变，明确要求其安装在所选 WSL 内。

`start.cmd` 改为委托 `start.ps1`，关闭延迟展开，保留 `!` 字符；PowerShell 增加 `-Repo / -Distro`、发行版冲突及 `start.sh` 存在性检查，通过 `ProcessStartInfo` 直接创建 WSL 进程、等待并传递退出码。Windows argv 按需引用，支持中文、空格、`!`、`&` 和含空格的数据库参数。错误不会伪装成成功。不修改金融工具执行、数据库种子、权限或审计逻辑。

本轮实际检查：

| 检查 | 实际结果 |
|---|---|
| README PowerShell 原样一行 | 从 `C:\Windows` 启动真实前后端；Windows 侧确认 8000 ready、5173 代理 ready、页面 HTTP 200、审计 valid |
| README CMD 原样一行 | 从 `C:\Windows` 启动真实前后端；同上四项 Windows HTTP 检查通过 |
| PowerShell / CMD UNC 脚本 | 两项均实际启动服务并通过上述 Windows HTTP 检查；宿主持续等待服务 |
| 退出与隔离 | 四轮分别向本轮 Linux launcher 发送 SIGINT；宿主退出 0，8000/5173 释放；没有终止无关服务 |
| Windows 盘符特殊路径 | 临时目录含中文、空格、`!`、`&`，实际通过 WSL 路径转换并执行标记脚本；含空格的数据库参数完整保留 |
| 显式 Linux 仓库 | 从其他 Windows 当前目录通过 `-Repo` 成功读取启动帮助 |
| 错误仓库 / 发行版 / UNC 冲突 | 均返回非零退出码并打印诊断信息 |

服务实测原始输出与脚本 SHA-256 见[四入口证据](fixtures/windows-start-repair-2026-10-31.json)，路径与失败检查见[路径证据](fixtures/windows-start-paths-2026-10-31.json)。这些是自动启动和 Windows HTTP 验证，不是用户物理键盘的人工体验验收；退出检查使用 SIGINT，不声称已自动验证 Windows 键盘 Ctrl+C 事件。本轮完整门禁状态以修复提交的尾注为准。

## 行为与边界

1. 检查 Node 版本、同仓库启动锁及8000/5173端口，未知服务或重复启动直接拒绝。
2. 调用现有组装器生成 .runtime，不在生成目录维护另一份源码。
3. 使用已有 uv/pnpm；缺少时分别在 .runtime/.launcher-tools/ 中准备固定版本 uv 0.13.5、pnpm 10.11.0，不修改全局工具；Python工具虚拟环境采用标准的 .runtime/.launcher-tools/.venv 目录。
4. 使用冻结锁文件安装应用依赖。pnpm安装步骤单独使用非交互环境，避免旧版本在日志中等待隐藏确认；不改变服务进程的CI环境。依据见[pnpm版本10设置](https://github.com/pnpm/pnpm.io/blob/main/versioned_docs/version-10.x/settings.md)。
5. 首次创建独立模拟库 .runtime/backend/data/quickstart.db，使用现有确定性种子且不传 --reset；已有库直接复用。--database 可显式选择其他模拟库。
6. 一键入口固定离线规则 Planner、关闭后台自动任务、开启沙箱。API与前端只监听127.0.0.1；必须通过后端ready、前端代理ready及审计valid检查，才输出“已就绪”并尝试打开浏览器。
7. Ctrl+C、终止信号、未就绪或服务提前退出时，清理本次启动的进程组；不会终止其他服务。日志保存在 .runtime/launcher-logs/ 的独立运行目录。

开发热重载或可选模型配置继续使用 CONTRIBUTING 中的手动流程。此入口不是生产部署、银行认证或自动授权路径，所有金融操作仍走原有网关、确认/MFA、执行守卫和审计。

## 首轮自动验证（历史记录）

| 检查 | 实际结果 |
|---|---|
| 根目录原样命令 bash start.sh | 首次初始化默认独立库；前端HTTP200、代理ready，Ctrl+C退出0，双端口释放 |
| 首次指定新模拟库 | 服务ready；重复命令拒绝且不停止原服务；通过原有API确认一笔300元Mock转账 |
| 重复启动已有库 | 转账流水仍只有一笔-30000分，未重置或重复扣款；审计检查通过 |
| 缺少全局uv/pnpm | 实际安装项目内uv0.13.5/pnpm10.11.0，冻结安装依赖，启动成功；仍保留同一笔流水 |
| Windows PowerShell | `start.ps1 -NoBrowser` 从 `\\wsl.localhost` 路径启动；路径转换为 `/home/.../aegisbank`，API ready、前端 HTTP 200；停止后端口释放 |
| Windows CMD | `start.cmd --no-browser` 从 WSL UNC 路径启动；路径转换为 `/home/.../aegisbank`，API ready、前端 HTTP 200；停止后端口释放 |
| 进程与端口 | 各轮Ctrl+C后8000/5173可重新绑定；已有开发库未被改动 |
| 根单元测试 | 28项通过，其中新增启动测试10项；覆盖端口、锁、数据保留、非交互安装、未就绪/审计失败及进程归属 |

首次测试发现pnpm10与已有依赖布局不兼容时会等待隐藏确认，已修复并重跑三轮实际链路。原始启动/复用/工具安装结果见[JSON证据](fixtures/one-command-start-2026-10-31.json)，根单元测试输出见[文本](fixtures/one-command-start-2026-10-31-unittest.txt)。本机使用Node22.23.3；正常工具为uv0.12.24/pnpm12.10.1。

初次完整门禁发现非标准命名工具缓存中的自动生成Activate.ps1含CRLF；已将工具环境统一到标准.venv目录，保留原源码编码检查，并重新验证冷准备、重复启动与默认入口。该次失败门禁已中止，最终完整门禁重新执行，其状态以本次提交尾注为准。自动启动检查不替代非实现者人工体验、物理手机/键盘/读屏或正式视频验收；历史交付压缩包不自动重新打包。

Windows PowerShell/CMD 验证使用本机已安装的 WSL 发行版（WSL UNC 路径会从路径解析发行版，Windows 盘符路径使用默认发行版）；macOS 没有在本轮实机验证，因此不宣称 macOS 原生支持。
