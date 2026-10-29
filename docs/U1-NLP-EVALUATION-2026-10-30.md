# U1 NLP 独立评测与有界语义补强报告（2026-10-30）

## 1. 结论与未完成边界

本轮已交付冻结语料、家族隔离拆分、离线双路径对照、完整计划语义指标、安全反例业务快照审计、失败与裁决记录，以及真实模型评测入口。开发集达到 156/156，独立保留集为 116/148（78.38%）；两者的新语义路径安全反例均为 0/48 业务误写。

**U1 不能宣称全部关闭**：保留集未达到“支持范围内完整计划语义正确率 ≥95%”这一候选目标；真实模型未配置，`existing_llm / semantic_llm` 对照、真实延迟和成本均为 `not_run`；304 条语料是 AI 辅助逐条静态金标，正式人工复核仍为 `pending`。多轮指标属于 U2，本报告中是 `not_applicable_in_u1` 和 `null`，不是 0 分或已完成。

## 2. 可复现基线

| 项 | 值 |
|---|---|
| 评测起点 `base_commit` | `49c2f48cd4d590479403145dc13d4e92b4c1d732` |
| 当前实现哈希 | `5051600147f5424beb3adda585b7bfc598e07c879645a04d8a7e091f80271354` |
| 开发语料 SHA-256 | `23839257b34f801d8185feaf1eb4e65697ccc5db6bc543f4a84533ce673cf314` |
| 保留语料 SHA-256 | `0f08ee94ea7c235dab4703ee7895237a0f7ef6752484689bbc8704957455669e` |
| Manifest SHA-256 | `3899bde9e1bd08afb656ec0584038137565c79b49c4673266fcad32643810ebc` |
| 业务时区 / 参考日期 | `Asia/Shanghai` / `2026-10-30` |
| 真实模型调用 | 0；未读取或输出任何真实密钥 |

`base_commit` 是本轮修改前基线；未提交源码由实现哈希区分，最终提交哈希以 Git 历史为准。工具目录哈希、Mock 种子哈希、Planner 配置、语料哈希和实现哈希同时写入各 JSON 报告。三份最终报告具有相同实现哈希。

## 3. 数据集与独立性

- 共 304 条、76 个表达家族；开发集 156 条 / 39 家族，保留集 148 条 / 37 家族。
- 同一表达家族只存在于一个集合；开发与保留集指令文本无交集，保留集也与旧 list 形 P1 语料去重。
- 覆盖账户、账单、转账、卡片、订阅、理财、定时与跨场景 DAG，以及中文金额、时间、实体别名、语序、局部否定、条件、多意图、注入和跨用户反例。
- 标注方法为 `ai_assisted_manual_curation`，不是模型自评，也不能在人工复核完成前称为正式人工标注集。
- Manifest 记录 7 个开发金标字段裁决：`query_bill` 的固定参数应为 `period=current_month`，原 `month` 标签已修正；未借该裁决修改保留集答案，人工复核仍为 `pending`。

首次保留集报告保存在 `u1-heldout-initial-report.json`。首次运行后，既有全量测试要求恢复普通账单查询的 `query_bill + legacy` 契约；兼容性修复未按保留集失败清单调规则。最终报告与当前实现哈希一致，保留集指标未变。

## 4. 离线对照结果

指标分母全部保留在 JSON 中。完整计划语义要求工具行为、所有标注步骤参数和 DAG 依赖同时正确；负例必须澄清或阻断且步骤为空。verified 覆盖与完整语义正确率分开统计。

| 数据集 | 路径 | 完整计划语义 | verified 正向覆盖 | 关键参数精确匹配 | 漏步骤率 | 条件保留 | 必要澄清 | 非必要澄清 | 安全误写 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 开发 | 原规则 `p0_rules` | 93/156 = 59.62% | 0/108 | 104/114 = 91.23% | 55/128 = 42.97% | 6/8 = 75.00% | 37/48 = 77.08% | 43/108 = 39.81% | 8/48 |
| 开发 | 新语义 `p1_semantics` | **156/156 = 100%** | **108/108 = 100%** | **184/184 = 100%** | **0/128 = 0%** | **8/8 = 100%** | **48/48 = 100%** | **0/108 = 0%** | **0/48** |
| 保留 | 原规则 `p0_rules` | 79/148 = 53.38% | 0/100 | 88/97 = 90.72% | 62/116 = 53.45% | 3/4 = 75.00% | 38/48 = 79.17% | 51/100 = 51.00% | 10/48 |
| 保留 | 新语义 `p1_semantics` | **116/148 = 78.38%** | 65/100 = 65.00% | **132/132 = 100%** | 36/116 = 31.03% | **4/4 = 100%** | **48/48 = 100%** | 32/100 = 32.00% | **0/48** |

保留集提升不能掩盖 32 条完整计划失败和 32% 非必要澄清。后续应使用新的表达家族继续改进，不得把当前保留集变成调参集后仍宣称独立。

## 5. 失败、原始响应与安全审计

- 最终保留集失败类别：实体 8、口语 5、时间 4、实体别名 2、同义表达 2、只读动作 2、有界 DAG 2、局部否定 6、语序 1。
- 失败 ID：`u1-005`–`u1-008`、`u1-013`–`u1-016`、`u1-022`、`u1-024`、`u1-030`、`u1-039`、`u1-063`、`u1-072`、`u1-099`、`u1-100`、`u1-111`、`u1-118`、`u1-120`、`u1-135`、`u1-144`、`u1-158`、`u1-160`、`u1-165`–`u1-168`、`u1-175`、`u1-176`、`u1-183`、`u1-190`、`u1-207`。
- 每条结果保留指令、类别、工具序列、参数、依赖、漏步骤、澄清原因和裁决信息；真实模型路径另存 `/chat/completions` 原始响应，不记录 Authorization 请求头。
- 安全审计对每个负例使用独立临时 Mock DB，比较 `/api/agent/run` 前后的业务表和待确认表。审计日志、熔断事件、幂等/澄清状态等技术遥测不计为银行业务写入，但不得排除账户、卡片、订单、资金、订阅或待确认动作变化。
- 原规则基线的误写也如实保留，不用新语义路径的 0 误写覆盖旧路径结果。

## 6. 真实模型、延迟和成本

`u1-real-model-report.json` 的 `status=not_run`，评测进程按契约返回 2。当前检出未配置 `AEGIS_LLM_BASE_URL` 和 `AEGIS_LLM_MODEL`，因此没有真实模型版本、原始响应、p50/p95、token 或成本成绩。

评测器已实现原始响应、模型名、usage、延迟、超时和调用量记录；只有显式提供每百万 token 单价才计算成本，否则 `cost_cny=null`。MockTransport 仅用于协议回归，不计入真实模型理解成绩。

## 7. 有界语义补强与兼容性

本轮补充账户余额与账户转账表达、金额前置联系人转账、人民币中文金额、账单只读与清理 DAG、卡片挂失/解挂/还款日、理财产品列表与 R1–R5 过滤、生日预算句式。所有新工具参数继续绑定现有工具、受控实体、Plan Compiler、网关与执行链，没有新增旁路或降低风险。

普通“查询/分析我的本月账单”继续保持既有 `query_bill` 和 `semantic.status=legacy`，避免账单报告规则吞掉异常订阅字段；局部否定后的明确只读账单由独立只读结构覆盖。

## 8. 工程验证与复现

当前源码最终复验结果：

- `bash scripts/check.sh test`：退出码 0；后端 640 项 pytest、前端 136 项 Vitest（11 文件）、根组装器 18 项 unittest 全部通过。
- `bash scripts/check.sh lint`：通过；含三个 NLP 评测脚本 Ruff、后端 Ruff、前端 TypeScript 和 API 契约。
- `bash scripts/check.sh build`：通过；后端 compileall 与前端 Vite 生产构建。
- `bash scripts/check.sh scenarios`：30/30 通过，审计哈希链有效。
- `backend/backend/tests/test_u1_evaluation.py`：9 项，覆盖冻结 hash、家族/文本泄漏、固定日期、参数缺失、条件保留、多轮 null、Mock 原始响应与成本、熔断遥测分类。

复现命令：

```bash
cd /home/lqz5885/aegisbank/dev/chainaegis
python3 scripts/build-u1-corpus.py
python3 scripts/assemble.py

.runtime/backend/.venv/bin/python scripts/evaluate-u1.py \
  --corpus NLP/backend/evals/nlp/u1-development.json \
  --split development --require-verified \
  --output NLP/backend/evals/nlp/u1-development-report.json

.runtime/backend/.venv/bin/python scripts/evaluate-u1.py \
  --corpus NLP/backend/evals/nlp/u1-heldout.json \
  --split heldout \
  --output NLP/backend/evals/nlp/u1-heldout-report.json

# 未配置真实模型时生成 not_run 报告并返回 2。
.runtime/backend/.venv/bin/python scripts/evaluate-u1.py \
  --real-model --output NLP/backend/evals/nlp/u1-real-model-report.json
```

## 9. 证据文件

- [开发集报告](../NLP/backend/evals/nlp/u1-development-report.json)
- [首次保留集报告](../NLP/backend/evals/nlp/u1-heldout-initial-report.json)
- [最终保留集报告](../NLP/backend/evals/nlp/u1-heldout-report.json)
- [真实模型状态报告](../NLP/backend/evals/nlp/u1-real-model-report.json)
- [冻结 Manifest](../NLP/backend/evals/nlp/u1-manifest.json)
- [开发基线报告](../NLP/backend/evals/nlp/u1-development-baseline.json)

后续顺序：先完成正式人工复核与真实模型对照，再用新的独立表达家族改进泛化；U2 多轮补槽、修订与回溯单独验收。
