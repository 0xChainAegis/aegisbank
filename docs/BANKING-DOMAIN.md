# 银行领域模型与三场景闭环

## 1. 目标

本阶段在 AegisBank 本地骨架上补齐可演示的银行领域模型、动态风险引擎和三类核心场景：

1. 智能转账
2. 账单分析
3. 卡片管理

同时增加一个跨场景 DAG：

```text
分析账单 -> 识别异常订阅 -> 取消订阅 -> 写入审计
```

所有银行数据都来自确定性的 Mock Bank Core，LLM 和 Planner 不得编造余额、账单、交易结果或订阅状态。

## 2. 银行领域模型

数据表由 `BankingRepository` 自动创建并播种。

| 表 | 说明 |
|---|---|
| `bank_accounts` | 账户余额、可用余额、账户类型 |
| `bank_cards` | 卡号掩码、状态、额度、还款日、交易限额 |
| `bank_transactions` | 交易流水、分类、金额、时间、状态 |
| `bank_subscriptions` | 订阅商户、金额、周期、状态、风险标记 |

种子数据只针对 `demo-user`，包括：

- `ACC-1001` 工资卡
- `ACC-2002` 日常储蓄
- `CARD-8821` / `CARD-9902`
- 工资、餐饮、购物、交通、订阅等本月交易
- `SUB-3001` 云端影音
- `SUB-3002` AI 工具订阅：带异常标记
- `SUB-3003` 健身房月卡

## 3. 工具目录

| 工具 | 权限 | 基线风险 | 说明 |
|---|---|---|---|
| `query_bill` | `billing:read` | 绿色 | 账单分析、分类、异常订阅 |
| `transfer` | `transfer:execute` | 黄色 | 按金额和日累计动态升级 |
| `adjust_repayment_date` | `card:manage` | 黄色 | 修改还款日 |
| `adjust_card_limit` | `card:manage` | 黄色 | 超过 5000 元升级红色 |
| `set_transaction_limit` | `card:manage` | 黄色 | 设置单日交易限额 |
| `report_card_lost` | `card:security` | 红色 | 挂失 |
| `unlock_card` | `card:security` | 红色 | 解挂 |
| `list_subscriptions` | `subscription:read` | 绿色 | 查询订阅 |
| `cancel_subscription` | `subscription:manage` | 黄色 | 取消订阅 |

## 4. 动态风险引擎

`DynamicRiskEngine` 使用确定性数据做风险判断，规则如下：

### 智能转账

```text
单笔金额 > 5000 元             -> 红色
今日累计转账（含本次） > 1000 元 -> 红色
其他转账                       -> 黄色
```

### 卡片管理

```text
额度调整 > 5000 元 -> 红色
挂失 / 解挂        -> 红色
其他卡片设置变更   -> 黄色
```

### 查询

```text
账单分析 / 订阅查询 -> 绿色
```

风险结果会同时写入：

- Agent 响应的 `risk`
- 计划步骤的 `risk_level` / `risk_reasons`
- 工具执行结果
- 审计记录

## 5. 三类场景

### 5.1 智能转账

示例：

```text
向 ACC-2002 转账 880 元
```

- 880 元 -> 黄色确认
- 同一天再转 500 元 -> 累计 1380 元 -> 红色强验证
- 确认后更新账户余额和交易流水

### 5.2 账单分析

示例：

```text
分析我的本月账单
```

返回：

- 本月支出总额
- 消费分类
- 异常交易说明
- 异常订阅 ID
- 最近交易明细

### 5.3 卡片管理

示例：

```text
把还款日调整到每月 18 日
把信用卡额度调整到 8000 元
把 CARD-8821 的单日交易限额设置为 3000 元
挂失卡片 CARD-9902
```

- 还款日调整 -> 黄色
- 8000 元额度调整 -> 红色
- 挂失/解挂 -> 红色

## 6. 跨场景 DAG

示例：

```text
分析我的账单并取消异常订阅
```

生成计划：

```text
step-1: query_bill
   |
   v
step-2: cancel_subscription
```

步骤 2 的参数使用前一步结果：

```json
{
  "subscription_id": "${steps.step-1.data.suspicious_subscription_id}"
}
```

执行器在运行 step-2 前解析引用，确保取消的是账单分析实际发现的订阅。

## 7. API

新增：

```text
GET /api/banking/overview
```

返回：

- 账户列表
- 卡片列表
- 订阅列表
- 本月支出
- 今日累计转账
- 异常订阅 ID 和原因

现有：

```text
GET  /api/tools
GET  /api/permissions
PUT  /api/permissions/{tool}
POST /api/agent/run
POST /api/planner/plan
POST /api/confirmations/{id}
GET  /api/audit
GET  /api/audit/verify
```

## 8. 当前边界

- 银行数据仍为本地模拟数据，不连接真实银行核心；
- 强验证仍使用演示 OTP，不冒充真实短信/人脸/U 盾；
- DAG 当前支持依赖和变量解析，但还没有步骤级回滚和补偿；
- 异常熔断和工具沙箱尚未实现；
- 只支持 Web 控制台，IM 适配器尚未接入；
- 比赛文档、PPT、演示视频和安全自评报告仍需后续补齐。

## 9. 下一步

1. 增加步骤级暂停、回退和补偿；
2. 增加异常熔断器；
3. 增加工具执行沙箱；
4. 增加事实校验和注入攻击测试集；
5. 增加 IM 渠道适配器；
6. 准备比赛材料。
