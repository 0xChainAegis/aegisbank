# AegisBank 参赛交付包（阶段 3）

> 交付版本说明：本目录材料（含 PPT）保留 2026-10-23 验收快照。2026-10-24 后端补强增加 13 项回归，当前后端 200 项；最新功能和测试基线见 [补强记录](../docs/BACKEND-HARDENING-2026-10-24.md) 及根 README。

> 2026-10-23 安全复审后更新；本轮修复、反例与验收见 [安全修复记录](../docs/REMEDIATION-PLAN-2026-10-23.md)。
> 赛题：人工智能赛道 · 银行 AI 智能体
> 版本：阶段 3 交付版　基线：`main` @ `75df12b`
> 仓库：<https://github.com/LQZ5885/aegisbank>（Public / MIT）
> 说明：本目录是比赛**提交/答辩用**的整合材料；实现细节与长期文档见仓库 `docs/`。

---

## 1. 交付清单

| 编号 | 文件 | 对应赛题交付物 | 状态 |
|---|---|---|---|
| 01 | [01-作品简介.md](01-作品简介.md) | 作品简介（≤200 字） | ✅ 已完成（含 200 字压缩版） |
| 02 | [02-技术文档.md](02-技术文档.md) | 技术文档（架构图 / 核心算法 / 安全设计） | ✅ 已完成（含 Mermaid 架构图） |
| 03 | [03-AegisBank-答辩PPT.pptx](03-AegisBank-答辩PPT.pptx) | 答辩 PPT（≤10 分钟，14 页） | ✅ 已生成（含逐页备注/时间控制） |
| 04 | [04-演示视频脚本.md](04-演示视频脚本.md) | 演示视频（≤5 分钟）分镜与口播稿 | ✅ 脚本完成；**视频待人工录制** |
| 05 | [05-安全自评报告.md](05-安全自评报告.md) | 安全自评报告（权限分级 + 已知风险） | ✅ 已完成 |
| 06 | [06-部署说明.md](06-部署说明.md) | 部署说明 / 环境与复现 | ✅ 已完成 |
| 07 | [07-测试与复现.md](07-测试与复现.md) | 源码测试用例与复现步骤 | ✅ 已完成 |
| — | [架构图源文件（Mermaid）](../docs/architecture/aegisbank-architecture-v2.mmd) | 技术文档配图 | ✅ 已完成 |

> 视频文件（`.mp4`）与最新界面截图不在本目录内：按 `04-演示视频脚本.md` 录制后放入本目录；截图在阶段 2.5（人工体验回归）时统一更新。**未完成项不要对外宣称已完成。**

---

## 2. 30 秒上手（评审现场）

```powershell
# 0) 先停掉正在运行的后端（重置数据库前必须停）
#    pkill -f "uvicorn aegisbank_api.main"

# 1) 重置演示数据（含 3000 元虚拟卡 ACC-3003 / CARD-9001）
cd /home/lqz5885/aegisbank/dev/aegisbank
bash scripts/seed-demo.sh

# 2) 启动后端：必须显式指向 dogfood.db
#    （scripts/dev.sh 默认使用 backend/data/aegisbank.db，看不到 3000 元虚拟卡）
cd backend
AEGIS_DATABASE_PATH=/home/lqz5885/aegisbank/dev/aegisbank/backend/data/dogfood.db \
  uv run uvicorn aegisbank_api.main:app --host 127.0.0.1 --port 8000

# 3) 另开一个终端启动前端
cd /home/lqz5885/aegisbank/dev/aegisbank/frontend && pnpm dev
# UI: http://127.0.0.1:5173   API: http://127.0.0.1:8000/docs
```

演示账号与凭据：用户 `demo-user`；红色操作 OTP `246810`；模拟生物识别 `FACE-888888`；
角色 `USER / OPERATOR / AUDITOR`（演示用 `X-Aegis-Role` 请求头，不是真实认证）。

---

## 3. 评审可验证的数字

| 指标 | 数值 | 验证方式 |
|---|---|---|
| 后端测试 | **187 passed**（16 个测试文件） | `cd backend && uv run pytest -p no:warnings` |
| 前端测试 | **53 passed**（7 个文件） | `cd frontend && pnpm test` |
| 六场景端到端回归 | **29/29 PASS** | `cd backend && uv run python ../scripts/scenario-check.py` |
| 工具 / 接口 | **50 个工具 / 49 个 HTTP 接口** | `GET /api/tools`、`GET /api/planner/info`、`/docs` |
| 审计链 | `{"valid": true, "checked": N}` | `GET /api/audit/verify` |
| 门禁 | encoding / lint / build / test / security **五阶段 PASS** | `gate.ps1 -Repo <repo>` |

---

## 4. 与赛题要求对照

| 赛题要求 | 对应交付内容 |
|---|---|
| 至少 3 个场景（鼓励全覆盖） | 六场景 6/6：见 `02-技术文档.md` §5、`07-测试与复现.md` |
| 权限分级（绿/黄/红 + 强验证） | `02` §4.3–4.5、`05` §2；演示：转账累计超 1000 → 红 + OTP |
| 幻觉 / 注入 / 审计 / 熔断 / 沙箱 | `05-安全自评报告.md` §3（逐项机制 → 实现 → 证据） |
| 意图规划（模糊表达、DAG、中断/回退/接管） | `02` §4.1–4.7；演示：两步账单 DAG、生日 4 步 DAG、暂停/回滚 |
| 五类交付物 | 本目录 01–07（视频待录制） |

---

## 5. 目录说明

```text
deliverables/
├─ README.md                  # 本文件：交付索引与 30 秒上手
├─ 01-作品简介.md             # ≤200 字 + 压缩版
├─ 02-技术文档.md             # 参赛版技术文档（架构/算法/安全/场景/验证）
├─ 03-AegisBank-答辩PPT.pptx  # 14 页答辩 PPT（含演讲备注与时间控制）
├─ 04-演示视频脚本.md         # 5 分钟逐秒分镜 + 口播稿 + 录制说明
├─ 05-安全自评报告.md         # 权限分级实现 + 已知风险清单
├─ 06-部署说明.md             # 环境、启动、数据、配置、排障
└─ 07-测试与复现.md           # 测试矩阵、命令、预期输出、复现排查
```

长期维护文档（不随比赛提交）：`docs/MASTER-PLAN.md`（总规划）、`docs/ROADMAP.md`、`docs/ARCHITECTURE.md`、`docs/SECURITY.md`、`docs/BANKING-DOMAIN.md`、`docs/NEWBIE-TUTORIAL.md`。

---

## 6. 诚实边界（答辩必须同时说明）

- 全部为 Mock Bank Core 模拟数据，不连接真实银行、不产生真实资金；理财不构成投资建议。
- 无真实登录/身份认证；`X-Aegis-Role` 为演示请求头；OTP 与生物识别为演示实现。
- 工具沙箱为进程内守卫（超时/网络/体积/白名单），不是 OS 级隔离。
- SQLite 单机；幂等键与 nonce 无 TTL；熔断计数为系统级。
- 六场景为「典型能力完整覆盖」，不等于生产业务完整性；已支持限时单次澄清续问；通用指代消解仍未实现。
- 阶段 2.5 人工体验测试已推迟；界面截图与演示视频需在 2.5 / 录制阶段更新。
