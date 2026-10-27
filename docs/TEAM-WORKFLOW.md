# 团队协作与接口交接

10月27日具体负责人、交接时间及验收范围见 [当日任务安排](PLAN-2026-10-27.md)。

团队集成仓库为 <https://github.com/0xChainAegis/aegisbank>。`main` 保存共同验收版本，原作者仓库作为来源保留，不同时维护两条集成主线。每位成员各自克隆、各自分支，通过 PR 合入。

## 修改边界

- 前端负责人主责 `fronted/frontend/`、界面体验、前后端集成、README 与部署说明。
- 后端与 NLP 负责人按 `backend/`、`agent/`、`NLP/`、`skills/`、`plans/` 的职责维护语义解析、API 契约、安全链和后端回归，并核对技术文档及安全自评事实。
- 体验与材料负责人主责试用安排、复现记录、PPT 和演示脚本；技术事实由对应开发负责人审核。
- 一个文档或共享文件设一个主笔。接口变化先对齐请求、响应和兼容处理，再同步 `fronted/frontend/src/api.ts`、`types.ts` 与相关回归；后端和前端分工不应让接口文件被两人同时覆盖。

## 开发与合入

```bash
git clone https://github.com/0xChainAegis/aegisbank.git
cd aegisbank
git switch -c feat/short-description
# 修改、验证、提交
git push -u origin HEAD
```

从分支向 `main` 提 PR，说明具体问题、改后行为和验证结果。由另一位成员查看改动和 CI 结果后合入。需要协调时，以组织仓库的 PR 和明确约定的文件边界为准；AI 生成修改同样由负责人核查。

已有原作者仓库的成员可额外添加团队 remote；已有未合入工作先在自己的分支保留，再向组织仓库提交 PR，不需要重新初始化 Git 或覆盖整目录。

```bash
git remote add team https://github.com/0xChainAegis/aegisbank.git
git fetch team
# 在自己的功能分支提交后
git push -u team HEAD
```

## 验收与演示版本

后端必须在 Linux / WSL 运行。先在根目录执行 `python3 scripts/assemble.py`，在 `.runtime/` 安装锁定依赖并运行；源目录是六个职责包，生成目录不作为开发入口。仓库 CI 先组装，再验证后端 lint、编译、pytest、六场景脚本，以及前端测试与生产构建。具体版本见 `.github/workflows/ci.yml`；本地常用脚本见 CONTRIBUTING。

功能冻结后只修影响运行、关键流程、安全或材料一致性的问题。每次演示与打包记录提交 SHA，使用同一版前后端和材料；研究性 NLP 任务单独分支推进，未验收不进入交付版本。

本轮 NLP 只整理待办，现状及后续验收标准见 [NLP-BACKLOG.md](NLP-BACKLOG.md)。当前可上传材料见 [deliverables/current](../deliverables/current/README.md)。
