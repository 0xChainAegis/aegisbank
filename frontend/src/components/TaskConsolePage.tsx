import { FormEvent, useMemo } from 'react';
import { formatCny, riskDescriptions } from '../risk';
import type { AgentRunInput, RiskLevel, RunResponse, ToolMetadata } from '../types';
import {
  argumentLabels,
  collectRiskReasons,
  formatDisplayValue,
  resultRiskLevel,
  runRiskLevel,
  stepRiskLevel,
  statusLabels,
} from '../viewModel';
import { PageAlerts, RiskBadge, StatusPill } from './ui';

interface ScenarioAction {
  id: string;
  title: string;
  description: string;
  instruction: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  requiredTools: string[];
  hint: string;
}

interface ScenarioGroup {
  id: string;
  index: string;
  title: string;
  caption: string;
  actions: ScenarioAction[];
}

const actionRiskMap: Record<string, RiskLevel> = {
  'transfer-large': 'red',
  'transfer-small': 'yellow',
  'card-repayment': 'yellow',
  'card-limit': 'red',
  'card-lost': 'red',
  'card-unlock': 'red',
  'subscription-rescue': 'yellow',
};

const scenarioGroups: ScenarioGroup[] = [
  {
    id: 'bill',
    index: '01',
    title: '账单分析',
    caption: '只读查询 · GREEN',
    actions: [
      {
        id: 'bill-analyze',
        title: '分析本月账单',
        description: '查询 ACC-1001 本月账单与近期交易，快速了解消费结构。',
        instruction: '查询并分析我的本月账单',
        toolName: 'query_bill',
        arguments: { account_id: 'ACC-1001', period: 'current_month' },
        requiredTools: ['query_bill'],
        hint: '只读操作，命中绿色规则后直接执行。',
      },
    ],
  },
  {
    id: 'transfer',
    index: '02',
    title: '转账指令',
    caption: '动态金额分级',
    actions: [
      {
        id: 'transfer-small',
        title: '小额转账 ¥880',
        description: '向 ACC-2002 转账 880 元，预计进入黄色确认。',
        instruction: '向 ACC-2002 转账 880 元',
        toolName: 'transfer',
        arguments: {
          from_account: 'ACC-1001',
          to_account: 'ACC-2002',
          amount_cny: 880,
          note: '任务控制台 · 小额转账快捷操作',
        },
        requiredTools: ['transfer'],
        hint: '单笔不超过 ¥5,000，且今日累计不超过 ¥1,000 时为黄色。',
      },
      {
        id: 'transfer-large',
        title: '大额转账 ¥6,800',
        description: '向 ACC-2002 转账 6,800 元，演示红色 MFA 二次校验。',
        instruction: '向 ACC-2002 转账 6800 元',
        toolName: 'transfer',
        arguments: {
          from_account: 'ACC-1001',
          to_account: 'ACC-2002',
          amount_cny: 6800,
          note: '任务控制台 · 大额转账快捷操作',
        },
        requiredTools: ['transfer'],
        hint: '单笔金额 > ¥5,000，触发红色规则并要求 MFA/OTP。',
      },
    ],
  },
  {
    id: 'card',
    index: '03',
    title: '卡片管理',
    caption: '账户设置与卡状态',
    actions: [
      {
        id: 'card-repayment',
        title: '调整还款日',
        description: '把 CARD-8821 的还款日调整到每月 18 日。',
        instruction: '把 CARD-8821 的还款日调整到每月 18 日',
        toolName: 'adjust_repayment_date',
        arguments: { card_id: 'CARD-8821', new_day: 18 },
        requiredTools: ['adjust_repayment_date'],
        hint: '账户设置变更，至少需要黄色轻量确认。',
      },
      {
        id: 'card-limit',
        title: '调整交易限额',
        description: '把 CARD-8821 的单笔交易限额调整为 8,000 元。',
        instruction: '把 CARD-8821 的单笔交易限额调整为 8000 元',
        requiredTools: ['set_transaction_limit'],
        hint: '额度超过 ¥5,000 时触发红色规则。',
      },
      {
        id: 'card-lost',
        title: '挂失卡片',
        description: '立即挂失 CARD-8821，阻断后续交易。',
        instruction: '挂失我的卡片 CARD-8821',
        requiredTools: ['report_card_lost'],
        hint: '挂失属于高风险卡片操作，必须 MFA 二次校验。',
      },
      {
        id: 'card-unlock',
        title: '解锁卡片',
        description: '解除 CARD-8821 的锁定状态。',
        instruction: '解锁我的卡片 CARD-8821',
        requiredTools: ['unlock_card'],
        hint: '解挂属于高风险卡片操作，必须 MFA 二次校验。',
      },
    ],
  },
  {
    id: 'cross',
    index: '04',
    title: '跨场景分析',
    caption: 'DAG 串联账单与订阅',
    actions: [
      {
        id: 'subscription-rescue',
        title: '分析并取消异常订阅',
        description: '读取账单与订阅，识别异常订阅后由 DAG 串联取消操作。',
        instruction: '分析我的本月账单和所有订阅，找出异常订阅并取消它',
        requiredTools: ['list_subscriptions', 'cancel_subscription'],
        hint: '跨节点 DAG 会串联查询、识别与取消；取消动作按实际风险进入确认。',
      },
    ],
  },
];

interface Props {
  tools: ToolMetadata[];
  toolsLoading: boolean;
  instruction: string;
  setInstruction: (value: string) => void;
  lastRun: RunResponse | null;
  busy: boolean;
  error: string;
  notice: string;
  onExecute: (input: AgentRunInput) => void;
  onRefresh: () => void;
}

export default function TaskConsolePage({
  tools,
  toolsLoading,
  instruction,
  setInstruction,
  lastRun,
  busy,
  error,
  notice,
  onExecute,
  onRefresh,
}: Props) {
  const toolNames = useMemo(() => new Set(tools.map((tool) => tool.name)), [tools]);
  const riskReasons = useMemo(() => (lastRun ? collectRiskReasons(lastRun) : []), [lastRun]);
  const overallRisk = lastRun ? runRiskLevel(lastRun) : 'green';

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = instruction.trim();
    if (!value || busy) return;
    onExecute({ instruction: value });
  }

  function trigger(action: ScenarioAction) {
    if (busy) return;
    setInstruction(action.instruction);
    onExecute({
      instruction: action.instruction,
      tool_name: action.toolName,
      arguments: action.arguments,
    });
  }

  return (
    <section className="page-grid console-grid">
      <div className="hero card">
        <div>
          <span className="eyebrow">AGENTIC BANKING · CONTROL PLANE</span>
          <h1>让每一次金融操作，都经过信任闸门。</h1>
          <p>
            AegisBank 将意图规划、权限校验、动态风险分级与操作审计串成一条可追溯链路。
            绿色直接执行，黄色轻量确认，红色执行 MFA/OTP 二次校验。
          </p>
        </div>
        <div className="hero-orbit" aria-hidden="true">
          <span className="orbit-ring ring-one" />
          <span className="orbit-ring ring-two" />
          <span className="orbit-core">A</span>
          <span className="orbit-label orbit-top">IDENTITY</span>
          <span className="orbit-label orbit-right">POLICY</span>
          <span className="orbit-label orbit-bottom">AUDIT</span>
        </div>
      </div>

      <div className="metrics-row">
        <div className="metric card">
          <span>动态风险策略</span>
          <strong>3 级</strong>
          <small>GREEN / YELLOW / RED</small>
        </div>
        <div className="metric card">
          <span>已注册工具</span>
          <strong>{tools.length}</strong>
          <small>{toolsLoading ? '正在同步权限' : `${tools.filter((tool) => tool.granted).length} 项已授权`}</small>
        </div>
        <div className="metric card">
          <span>跨场景编排</span>
          <strong>DAG</strong>
          <small>依赖 / 风险 / 审计统一编排</small>
        </div>
      </div>

      <div className="card command-card">
        <div className="section-head">
          <div>
            <span className="eyebrow">INTENT CONSOLE</span>
            <h2>发起一项任务</h2>
          </div>
          <button className="text-button" onClick={onRefresh} disabled={busy || toolsLoading}>
            {toolsLoading ? '同步中…' : '刷新工具状态'}
          </button>
        </div>

        <form className="command-form" onSubmit={submit}>
          <label className="sr-only" htmlFor="instruction">
            输入任务指令
          </label>
          <textarea
            id="instruction"
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            rows={3}
            placeholder="例如：分析我的本月账单和所有订阅，找出异常订阅并取消它"
          />
          <button className="primary-button" type="submit" disabled={busy || !instruction.trim()}>
            {busy ? '处理中…' : '交给 Agent'}
            <span aria-hidden="true">↗</span>
          </button>
        </form>

        <div className="scenario-heading">
          <div>
            <span className="eyebrow">SCENARIO LAUNCHPAD</span>
            <h3>三场景快捷操作 + 跨场景编排</h3>
          </div>
          <span className="muted">快捷入口会携带演示参数，仍全部经过权限网关与风险引擎</span>
        </div>

        <div className="scenario-grid">
          {scenarioGroups.map((group) => (
            <article className="scenario-card" key={group.id}>
              <div className="scenario-title">
                <span>{group.index}</span>
                <div>
                  <strong>{group.title}</strong>
                  <small>{group.caption}</small>
                </div>
              </div>
              <div className="scenario-actions">
                {group.actions.map((action) => {
                  const available = action.requiredTools.every((name) => toolNames.has(name));
                  const actionRisk: RiskLevel = actionRiskMap[action.id] ?? 'green';
                  return (
                    <button
                      className="scenario-action"
                      key={action.id}
                      onClick={() => trigger(action)}
                      disabled={busy || !available}
                      title={available ? action.hint : `缺少工具：${action.requiredTools.join(', ')}`}
                    >
                      <span className="scenario-action-head">
                        <strong>{action.title}</strong>
                        <RiskBadge risk={actionRisk} />
                      </span>
                      <small>{available ? action.description : '后端尚未注册该工具'}</small>
                      <span className="scenario-hint">{action.hint}</span>
                    </button>
                  );
                })}
              </div>
            </article>
          ))}
        </div>

        <div className="rule-strip">
          <span><i className="rule-dot dot-green" />查询：GREEN</span>
          <span><i className="rule-dot dot-yellow" />转账 ≤ ¥5,000 且今日累计 ≤ ¥1,000：YELLOW</span>
          <span><i className="rule-dot dot-red" />转账 &gt; ¥5,000 或今日累计 &gt; ¥1,000：RED</span>
          <span><i className="rule-dot dot-red" />额度 &gt; ¥5,000 / 挂失 / 解挂：RED</span>
        </div>
      </div>

      <PageAlerts error={error} notice={notice} />

      {lastRun && (
        <div className="card result-card">
          <div className="section-head">
            <div>
              <span className="eyebrow">RUN RESULT</span>
              <h2>执行回执</h2>
            </div>
            <div className="result-tags">
              <RiskBadge risk={overallRisk} verbose />
              <StatusPill status={lastRun.status} />
            </div>
          </div>

          <div className="result-summary-grid">
            <div>
              <span className="eyebrow">RUN ID</span>
              <code>{lastRun.run_id}</code>
            </div>
            <div>
              <span className="eyebrow">STATUS</span>
              <strong>{statusLabels[lastRun.status] ?? lastRun.status}</strong>
            </div>
            <div>
              <span className="eyebrow">RISK</span>
              <strong>{riskDescriptions[overallRisk]}</strong>
            </div>
          </div>

          <p className="result-reason">{lastRun.reason}</p>

          {riskReasons.length > 0 && (
            <div className={`risk-reason-panel risk-panel-${overallRisk}`}>
              <div className="risk-reason-head">
                <span className="eyebrow">RISK ENGINE FINDINGS</span>
                <RiskBadge risk={overallRisk} verbose />
              </div>
              <ul>
                {riskReasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}

          {lastRun.status === 'needs_clarification' && (
            <div className="clarification-panel">
              {lastRun.plan?.clarification || lastRun.reason || '请补充更多任务信息。'}
            </div>
          )}

          {lastRun.plan && (
            <div className="plan-block">
              <div className="plan-meta">
                <span className="eyebrow">STRUCTURED EXECUTION PLAN</span>
                <span className="plan-planner">{lastRun.plan.planner}</span>
                <span className="plan-confidence">
                  置信度 {Math.round(lastRun.plan.confidence * 100)}%
                </span>
                {lastRun.plan.plan_hash && (
                  <code className="plan-hash" title={lastRun.plan.plan_hash}>
                    {lastRun.plan.plan_hash.slice(0, 16)}…
                  </code>
                )}
              </div>
              {lastRun.plan.dag_path && (
                <p className="dag-path">
                  <span>DAG 路径</span>
                  <code>{lastRun.plan.dag_path}</code>
                </p>
              )}
              {lastRun.plan.steps.length > 0 && (
                <ol className="plan-steps">
                  {lastRun.plan.steps.map((step) => {
                    const stepRisk = stepRiskLevel(step.risk_level, lastRun);
                    return (
                      <li key={step.id}>
                        <div className="plan-step-head">
                          <span className="plan-step-id">{step.id}</span>
                          <strong>{step.title || step.tool_name}</strong>
                          <RiskBadge risk={stepRisk} />
                          {step.depends_on.length > 0 && (
                            <span className="depends-pill">依赖 {step.depends_on.join(', ')}</span>
                          )}
                        </div>
                        <div className="plan-step-tool">
                          <code>{step.tool_name}</code>
                          {step.permission && <span>权限 {step.permission}</span>}
                        </div>
                        {step.description && <p className="plan-step-description">{step.description}</p>}
                        <pre>{JSON.stringify(step.arguments, null, 2)}</pre>
                        {step.risk_reasons && step.risk_reasons.length > 0 && (
                          <ul className="step-risk-reasons">
                            {step.risk_reasons.map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
              {lastRun.plan.assumptions.length > 0 && (
                <div className="plan-assumptions">
                  {lastRun.plan.assumptions.map((item) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
              )}
            </div>
          )}

          {lastRun.results && lastRun.results.length > 0 && (
            <div className="results-section">
              <span className="eyebrow">TOOL RESULTS</span>
              {lastRun.results.map((result, index) => (
                <div className="result-block" key={`${result.tool_name}-${index}`}>
                  <div className="result-tool">
                    <div>
                      <span>{result.message}</span>
                      <code>{result.tool_name}</code>
                    </div>
                    <RiskBadge risk={resultRiskLevel(result, lastRun)} verbose />
                  </div>
                  <dl className="data-grid">
                    {Object.entries(result.data).map(([key, value]) => (
                      <div key={key}>
                        <dt>{argumentLabels[key] ?? key}</dt>
                        <dd>
                          {key.includes('amount') || key.includes('balance') || key.includes('limit') || key.includes('due')
                            ? formatCny(value)
                            : typeof value === 'object'
                              ? <pre>{formatDisplayValue(value)}</pre>
                              : formatDisplayValue(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  {result.risk && (result.risk.reasons?.length ?? 0) > 0 && (
                    <ul className="result-risk-reasons">
                      {result.risk.reasons?.map((reason) => <li key={reason}>{reason}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="card flow-card">
        <div className="section-head">
          <div>
            <span className="eyebrow">GOVERNED PIPELINE</span>
            <h2>每个节点都经过同一条路径</h2>
          </div>
        </div>
        <ol className="pipeline">
          <li><span>01</span><strong>意图解析</strong><small>规则规划器生成 DAG</small></li>
          <li><span>02</span><strong>权限网关</strong><small>授权 / 注入 / 越权 / 风险</small></li>
          <li><span>03</span><strong>分级确认</strong><small>绿放行 · 黄确认 · 红 MFA</small></li>
          <li><span>04</span><strong>签名审计</strong><small>SHA-256 哈希链留痕</small></li>
        </ol>
      </div>
    </section>
  );
}
