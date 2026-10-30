import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { formatCny } from '../risk';
import type { AegisRole } from '../roles';
import { roleCan, canExecuteTools, roleTaskBlockReason } from '../roles';
import type {
  ActionJournal,
  AgentRunInput,
  RiskLevel,
  RunResponse,
  ToolMetadata,
  TrustActionDetail,
} from '../types';
import { journalEligibleStatus, planStepCompensation } from '../twoA';
import {
  argumentLabels,
  collectRiskReasons,
  formatDateTime,
  formatDisplayValue,
  receiptHeadline,
  receiptReference,
  resultExecutedAt,
  resultRiskLevel,
  runRiskLevel,
  statusDescription,
  statusLabel,
  stepRiskLevel,
} from '../viewModel';
import StepJournalPanel from './StepJournalPanel';
import BusinessReceipt from './BusinessReceipt';
import { CompensationBadge, EvidenceBadges, PageAlerts, RiskBadge, StatusPill } from './ui';

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
  'wealth-purchase': 'red',
  'birthday-plan': 'yellow',
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
        instruction: '分析我的本月账单',
        toolName: 'query_bill',
        arguments: { account_id: 'ACC-1001', period: 'current_month' },
        requiredTools: ['query_bill'],
        hint: '只读操作，命中绿色规则后直接执行。',
      },
      {
        id: 'bill-annual',
        title: '生成年度账单',
        description: '生成年度账单报告，汇总分类支出、Top 商户与同比。',
        instruction: '生成我的年度账单报告',
        toolName: 'bill_report',
        arguments: { account_id: 'ACC-1001', period: 'year' },
        requiredTools: ['bill_report'],
        hint: '只读年报，不改变账户状态。',
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
        description: '把 CARD-8821 的单日交易限额调整为 8,000 元。',
        instruction: '把 CARD-8821 的单日交易限额调整为 8000 元',
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
        title: '解挂卡片',
        description: '解除 CARD-8821 的挂失状态。',
        instruction: '解挂卡片 CARD-8821',
        requiredTools: ['unlock_card'],
        hint: '解挂属于高风险卡片操作，必须 MFA 二次校验。',
      },
    ],
  },
  {
    id: 'wealth',
    index: '04',
    title: '理财操作',
    caption: '模拟产品 · 申购强验证',
    actions: [
      {
        id: 'wealth-products',
        title: '查看理财产品',
        description: '查看模拟产品的风险等级、期限与起购金额。',
        instruction: '有哪些理财产品',
        requiredTools: ['list_wealth_products'],
        hint: '只读产品查询；产品与收益全部为模拟数据。',
      },
      {
        id: 'wealth-purchase',
        title: '申购稳健短债A ¥1,000',
        description: '演示结构化申购计划与红色 MFA 确认。',
        instruction: '买 1000 元稳健短债A',
        requiredTools: ['purchase_wealth'],
        hint: '申购始终需要强验证，确认前不会变更模拟持仓。',
      },
    ],
  },
  {
    id: 'subscriptions',
    index: '05',
    title: '订阅与代扣',
    caption: '扣费识别 · 续费管理',
    actions: [
      {
        id: 'subscription-list',
        title: '查看我的订阅',
        description: '读取订阅清单、扣费金额、续费日期与异常标记。',
        instruction: '查看我的订阅',
        requiredTools: ['list_subscriptions'],
        hint: '只读查询；取消订阅仍需另行明确确认。',
      },
      {
        id: 'subscription-charges',
        title: '识别订阅扣费',
        description: '从模拟交易中识别订阅扣费与未登记代扣。',
        instruction: '识别我的订阅扣费',
        requiredTools: ['identify_subscription_charges'],
        hint: '基于实际模拟流水分析，不修改订阅状态。',
      },
    ],
  },
  {
    id: 'cross',
    index: '06',
    title: '跨场景分析',
    caption: 'DAG 串联账单与订阅',
    actions: [
      {
        id: 'subscription-rescue',
        title: '分析并取消异常订阅',
        description: '读取账单与订阅，识别异常订阅后由 DAG 串联取消操作。',
        instruction: '分析我的账单并取消异常订阅',
        requiredTools: ['query_bill', 'list_subscriptions', 'cancel_subscription'],
        hint: '跨节点 DAG 会串联查询、识别与取消；取消动作按实际风险进入确认。',
      },
      {
        id: 'birthday-plan',
        title: '安排妈妈生日 ¥1,000',
        description: '查询联系人生日、锁定预算，并预约鲜花和蛋糕。',
        instruction: '帮我准备下个月妈妈的生日，预算 1000 元',
        requiredTools: ['query_contact_birthday', 'lock_budget_funds', 'schedule_flower_order', 'schedule_cake_order'],
        hint: '四步 DAG；确认后锁定模拟预算，礼物在生日前两天下单。',
      },
    ],
  },
];

interface Props {
  role: AegisRole;
  tools: ToolMetadata[];
  toolsLoading: boolean;
  instruction: string;
  lastInstruction?: string;
  setInstruction: (value: string) => void;
  lastRun: RunResponse | null;
  busy: boolean;
  error: string;
  notice: string;
  writesBlocked: boolean;
  blockReason: string;
  lastActionId: string | null;
  hasTrustAction?: boolean;
  trustAction: TrustActionDetail | null;
  trustActionLoading: boolean;
  trustActionError: string;
  onInspectTrustAction: () => void;
  onExecute: (input: AgentRunInput) => void;
  onRefresh: () => void;
  onRecoveryChanged: (journal: ActionJournal, response: unknown) => void;
  onNavigateAudit: () => void;
  onReconcile: (outcome: 'reconciled' | 'rolled_back') => void;
  reconciling: boolean;
}

export default function TaskConsolePage({
  role,
  tools,
  toolsLoading,
  instruction,
  lastInstruction = '',
  setInstruction,
  lastRun,
  busy,
  error,
  notice,
  writesBlocked,
  blockReason,
  lastActionId,
  hasTrustAction = false,
  trustAction,
  trustActionLoading,
  trustActionError,
  onInspectTrustAction,
  onExecute,
  onRefresh,
  onRecoveryChanged,
  onNavigateAudit,
  onReconcile,
  reconciling,
}: Props) {
  const toolNames = useMemo(() => new Set(tools.map((tool) => tool.name)), [tools]);
  const riskReasons = useMemo(() => (lastRun ? collectRiskReasons(lastRun) : []), [lastRun]);
  const overallRisk = lastRun ? runRiskLevel(lastRun) : 'green';
  const riskPending = lastRun?.status === 'needs_clarification';
  const reference = lastRun ? receiptReference(lastRun) : { label: '审计编号' as const, value: '—' };
  const draft = lastRun?.draft;
  const missingSlots = draft?.missing_slots ?? [];
  const missingSlotText = missingSlots.length > 0
    ? missingSlots.map((slot) => {
        const label = argumentLabels[slot] ?? slot;
        return label === slot ? slot : `${label}（${slot}）`;
      }).join('、')
    : '未返回';
  const draftExpiry = draft?.expires_at ? formatDateTime(draft.expires_at) : '未返回';
  const canExecute = canExecuteTools(role);
  const roleBlockReason = roleTaskBlockReason(role);
  const taskBlocked = !canExecute || writesBlocked;
  const taskBlockText = !canExecute
    ? roleBlockReason
    : writesBlocked
      ? `写操作已按 fail-closed 禁用：${blockReason}`
      : '';

  const demoActions = useMemo(() => {
    const all = scenarioGroups.flatMap((group) => group.actions);
    return [
      all.find((action) => action.id === 'bill-analyze'),
      all.find((action) => action.id === 'transfer-small'),
      all.find((action) => action.id === 'card-lost'),
    ].filter((action): action is ScenarioAction => Boolean(action));
  }, []);
  const resultRef = useRef<HTMLDivElement | null>(null);
  const wasBusyRef = useRef(false);
  const lastQuickInstructionRef = useRef('');
  const [quickNotice, setQuickNotice] = useState('');
  const [followUp, setFollowUp] = useState(false);
  useEffect(() => { setFollowUp(false); }, [lastRun?.run_id]);

  // 提交完成后把回执滚进视口（UX-06）：否则用户会以为「点了没反应」。
  useEffect(() => {
    if (wasBusyRef.current && !busy && lastRun) {
      resultRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
    wasBusyRef.current = busy;
  }, [busy, lastRun]);
  const journalActionId =
    lastRun && journalEligibleStatus(lastRun.status)
      ? lastActionId ?? lastRun.run_id
      : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = instruction.trim();
    if (!value || busy || taskBlocked) return;
    const followUpContext: Partial<AgentRunInput> =
      followUp && lastRun?.status === 'needs_clarification'
        ? lastRun.draft
          ? {
              session_id: lastRun.session_id ?? lastRun.draft.session_id,
              draft_id: lastRun.draft.draft_id,
              draft_version: lastRun.draft.version,
            }
          : { clarification_run_id: lastRun.run_id }
        : {};
    onExecute({ instruction: value, ...followUpContext });
  }

  function prepare(action: ScenarioAction) {
    if (busy || taskBlocked) return;
    setFollowUp(false);
    setInstruction(action.instruction);
    setQuickNotice('示例已填入，请检查内容后提交。');
    document.getElementById('instruction')?.focus();
  }

  function trigger(action: ScenarioAction) {
    setFollowUp(false);
    if (busy || taskBlocked) return;
    const current = instruction.trim();
    // 内置演示指令（快捷动作/演示路径填入过）视为"已知来源"，返回页面后再点仍可一键执行；
    // 只有用户自己手写的文本才只填入、不自动执行（UX-08）。
    const builtInInstructions = new Set(
      scenarioGroups.flatMap((group) => group.actions.map((item) => item.instruction)),
    );
    const canAutoRun =
      !current ||
      current === action.instruction ||
      current === lastQuickInstructionRef.current ||
      builtInInstructions.has(current);
    setInstruction(action.instruction);
    lastQuickInstructionRef.current = action.instruction;
    if (!canAutoRun) {
      // 不静默覆盖用户已输入的内容（UX-08）：只填入，等用户自己提交。
      setQuickNotice(`已填入「${action.title}」指令。确认内容后点击「提交任务」执行。`);
      return;
    }
    setQuickNotice('');
    onExecute({
      instruction: action.instruction,
      tool_name: action.toolName,
      arguments: action.arguments,
    });
  }

  return (
    <section className="page-grid console-grid assistant-workspace">
      <header className="assistant-intro">
        <span className="eyebrow">银行助手</span>
        <h1>今天想办理什么？</h1>
        <p>查账单、准备转账或管理卡片。涉及资金与账户变更时，请核对后确认。</p>
      </header>

      <div className="card command-card">
        <div className="section-head">
          <div>
            <span className="eyebrow">描述你的需求</span>
            <h2>输入需求</h2>
          </div>
          <button className="text-button" onClick={onRefresh} disabled={busy || toolsLoading}>
            {toolsLoading ? '同步中…' : '刷新工具状态'}
          </button>
        </div>

        <div className="demo-path" aria-label="演示路径">
          <span className="eyebrow">试一个例子</span>
          {demoActions.map((action, index) => (
            <button
              key={action.id}
              className="demo-step"
              onClick={() => prepare(action)}
              disabled={busy || taskBlocked}
              title={action.hint}
            >
              <span>{index + 1}</span>
              {action.id === 'transfer-small' ? '小额转账 ¥880' : action.title}
            </button>
          ))}
        </div>

        {taskBlocked && (
          <div className="alert alert-warn command-blocked" role="alert">
            {taskBlockText}
            {writesBlocked ? ' 服务就绪后才能提交任务或执行确认。' : ' 请切换到普通用户演示角色后重试。'}
          </div>
        )}

        <form className="command-form" onSubmit={submit}>
          <label className="sr-only" htmlFor="instruction">
            输入任务指令
          </label>
          <textarea
            id="instruction"
            value={instruction}
            onChange={(event) => {
              setInstruction(event.target.value);
              setQuickNotice('');
            }}
            rows={3}
            placeholder="例如：分析我的本月账单"
          />
          <button
            className="primary-button"
            type="submit"
            disabled={busy || taskBlocked || !instruction.trim()}
          >
            {busy ? '处理中…' : '提交任务'}
            <span aria-hidden="true">↗</span>
          </button>
        </form>

        {lastRun?.status === 'needs_clarification' && (
          <div className="alert alert-info" role="status">
            <span>{followUp ? '当前输入将补充上一条任务（10 分钟内有效，提交后重新核对全部风险）。' : '上一条任务需要补充信息。'}</span>
            <button type="button" className="ghost-button small-button" disabled={busy || taskBlocked}
              onClick={() => { setFollowUp(!followUp); setInstruction(''); document.getElementById('instruction')?.focus(); }}>
              {followUp ? '改为新任务' : '补充上一条任务信息'}
            </button>
          </div>
        )}

        {busy && (
          <div className="progress-line" role="status" aria-live="polite">
            <span className="loading-spinner" aria-hidden="true" />
            <span>正在解析意图、校验权限与风险，请稍候…</span>
          </div>
        )}
        {quickNotice && (
          <div className="alert alert-info" role="status">
            {quickNotice}
          </div>
        )}

      </div>

      <PageAlerts error={error} notice={notice} />

      {lastRun && (
        <div className="card result-card" ref={resultRef}>
          {lastInstruction && <div className="submitted-request"><span>你的请求</span><p>{lastInstruction}</p></div>}
          <div className="section-head">
            <div>
              <span className="eyebrow">本次处理</span>
              <h2>处理结果</h2>
            </div>
            <div className="result-tags">
              {riskPending ? <span className="chip">风险待评估</span> : <RiskBadge risk={overallRisk} verbose />}
              <StatusPill status={lastRun.status} />
            </div>
          </div>

          <div className="receipt-headline">
            <strong>{receiptHeadline(lastRun)}</strong>
            <span className="muted">{lastRun.reason}</span>
          </div>

          <div className="receipt-facts">
            <div>
              <span>状态</span>
              <strong>{statusLabel(lastRun.status)}</strong>
            </div>
            <div>
              <span>风险等级</span>
              <strong>{riskPending ? '风险待评估' : <RiskBadge risk={overallRisk} verbose />}</strong>
            </div>
            <div>
              <span>执行时间</span>
              <strong>
                {resultExecutedAt(lastRun) ? formatDateTime(resultExecutedAt(lastRun)) : '—'}
              </strong>
            </div>
            <div>
              <span>{reference.label}</span>
              <strong>{reference.value}</strong>
            </div>
          </div>

          <p className="status-description">{statusDescription(lastRun.status)}</p>

          <div className="receipt-actions">
            <button className="primary-button small-button" onClick={onNavigateAudit}>
              查看本次审计记录 →
            </button>
            {lastRun.status === 'unknown' && (
              <>
                <button
                  className="ghost-button small-button"
                  onClick={() => onReconcile('reconciled')}
                  disabled={reconciling || writesBlocked || !roleCan(role, 'ops:manage')}
                >
                  {reconciling ? '处理中…' : '人工对账为已解决'}
                </button>
                <button
                  className="ghost-button small-button"
                  onClick={() => onReconcile('rolled_back')}
                  disabled={reconciling || writesBlocked || !canExecute}
                >
                  申请人工回滚
                </button>
              </>
            )}
          </div>

          {(lastRun.status === 'unknown' ||
            lastRun.status === 'reconciled' ||
            lastRun.status === 'rolled_back' ||
            lastRun.status === 'paused' ||
            lastRun.status === 'rollback_blocked') && (
            <div
              className={`alert ${
                lastRun.status === 'unknown' || lastRun.status === 'rollback_blocked'
                  ? 'alert-warn'
                  : 'alert-info'
              }`}
              role="status"
            >
              {lastRun.status === 'unknown'
                ? '结果未知不等于失败：副作用可能已发生，系统不会自动重试。请人工对账（reconciled）或回滚（rolled_back）。'
                : lastRun.status === 'paused'
                  ? '执行已在步骤之间暂停：剩余节点未执行，已执行步骤不会重复执行；可在步骤日志中恢复或回滚。'
                  : lastRun.status === 'rollback_blocked'
                    ? '回滚被阻止：已执行步骤中存在不可撤销操作，需要人工与银行核实后对账。'
                    : '任务状态已由人工处理，结论已写入审计哈希链。'}
            </div>
          )}

          {!riskPending && riskReasons.length > 0 && (
            <div className={`risk-reason-panel risk-panel-${overallRisk}`}>
              <div className="risk-reason-head">
                <span className="eyebrow">风险引擎判定</span>
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
            <div className={'clarification-panel'}>
              <p>{lastRun.plan?.clarification || lastRun.reason || '请补充更多任务信息。'}</p>
              {lastRun.draft && (
                <dl className={'clarification-draft-facts'}>
                  <div>
                    <dt>草稿版本</dt>
                    <dd>v{lastRun.draft.version}</dd>
                  </div>
                  <div>
                    <dt>缺失金额</dt>
                    <dd>{missingSlotText}</dd>
                  </div>
                  <div>
                    <dt>有效期</dt>
                    <dd title={lastRun.draft.expires_at ?? undefined}>{draftExpiry}</dd>
                  </div>
                </dl>
              )}
              {lastRun.reason_code && (
                <p>原因代码：<code>{lastRun.reason_code}</code></p>
              )}
            </div>
          )}

          <BusinessReceipt run={lastRun} />

          <details className="tech-details">
            <summary>技术详情与证据链（计划 / 入参 / 证据 / 状态机 / 步骤日志）</summary>
            <div className="result-evidence">
              <span className="eyebrow">证据分层</span>
              <EvidenceBadges
                evidence={lastRun.evidence ?? lastRun.evidence_list}
                emptyHint="本次回执未返回分层证据。"
              />
            </div>
            <p className="tech-run-id">
              <span className="eyebrow">RUN ID</span>
              <code>{lastRun.run_id}</code>
            </p>

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
                {lastRun.plan.irreversible && (
                  <span className="comp-badge comp-bad">计划含不可撤销步骤</span>
                )}
              </div>
              {lastRun.plan.dag_path && (
                <p className="dag-path">
                  <span>DAG 路径</span>
                  <code>{lastRun.plan.dag_path}</code>
                </p>
              )}
              {lastRun.plan.rollback_blocked_reason && (
                <p className="plan-rollback-note">{lastRun.plan.rollback_blocked_reason}</p>
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
                          <CompensationBadge info={planStepCompensation(step, tools)} />
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
                          {key.endsWith('_cny')
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

          {hasTrustAction && lastActionId && (
            <div className="trust-panel">
              <div className="section-head compact-head">
                <div>
                  <span className="eyebrow">TRUST ACTION VIEW</span>
                  <h3>任务状态机与 ActionEnvelope</h3>
                </div>
                <button
                  className="ghost-button small-button"
                  onClick={onInspectTrustAction}
                  disabled={trustActionLoading}
                >
                  {trustActionLoading ? '读取中…' : trustAction ? '重新读取' : '查看信任详情'}
                </button>
              </div>

              {trustActionError && (
                <div className="alert alert-error" role="alert">
                  {trustActionError}
                </div>
              )}

              {!trustAction && !trustActionError && (
                <p className="panel-note">
                  读取任务状态机（UNKNOWN / RECONCILED / ROLLED_BACK）、ActionEnvelope 与分层证据；
                  数据来自 <code>GET /api/trust/actions/&#123;id&#125;</code>。
                </p>
              )}

              {trustAction && (
                <>
                  <dl className="trust-facts">
                    <div>
                      <dt>ACTION ID</dt>
                      <dd><code>{trustAction.action_id}</code></dd>
                    </div>
                    <div>
                      <dt>STATE</dt>
                      <dd>
                        {trustAction.state} · {statusLabel(trustAction.state.toLowerCase())}
                      </dd>
                    </div>
                    <div>
                      <dt>RISK</dt>
                      <dd><RiskBadge risk={trustAction.risk_level} verbose /></dd>
                    </div>
                    <div>
                      <dt>REAUTH</dt>
                      <dd>{trustAction.requires_reauth ? '需要 MFA/OTP' : '无需二次校验'}</dd>
                    </div>
                    <div>
                      <dt>创建时间</dt>
                      <dd>{trustAction.created_at ? formatDateTime(trustAction.created_at) : '—'}</dd>
                    </div>
                    <div>
                      <dt>过期时间</dt>
                      <dd>{trustAction.expires_at ? formatDateTime(trustAction.expires_at) : '—'}</dd>
                    </div>
                  </dl>

                  {trustAction.history.length > 0 && (
                    <ul className="trust-history">
                      {trustAction.history.map((transition, index) => (
                        <li key={`${transition.from}-${transition.to}-${index}`}>
                          <code>{transition.from}</code>
                          <span aria-hidden="true">→</span>
                          <code>{transition.to}</code>
                          {transition.reason && <span>{transition.reason}</span>}
                        </li>
                      ))}
                    </ul>
                  )}

                  {trustAction.envelopes.length > 0 && (
                    <div className="trust-envelopes">
                      {trustAction.envelopes.map((envelope, index) => (
                        <div
                          className="trust-envelope"
                          key={envelope.nonce ?? envelope.step_id ?? `envelope-${index}`}
                        >
                          <strong>{envelope.step_id ?? `step-${index + 1}`}</strong>
                          <code>{envelope.tool_name ?? '—'}</code>
                          {envelope.risk_level && <RiskBadge risk={envelope.risk_level} />}
                          <span>{envelope.confirmation_state ?? '—'}</span>
                          <span>
                            {envelope.approval_token_present
                              ? 'approval token 已存在（不回传）'
                              : 'approval token 未生成'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="result-evidence">
                    <EvidenceBadges
                      evidence={trustAction.evidence ?? trustAction.evidence_list}
                      emptyHint="状态视图未返回分层证据。"
                    />
                  </div>
                </>
              )}
            </div>
          )}

          {journalActionId && (
            <StepJournalPanel
              actionId={journalActionId}
              role={role}
              run={lastRun}
              writesBlocked={writesBlocked}
              blockReason={blockReason}
              onChanged={onRecoveryChanged}
            />
          )}
          </details>
        </div>
      )}

      <details className="card scenario-library">
        <summary>更多业务示例 <span>六类场景，展开选择</span></summary>
        <p className="muted">这些入口使用固定演示参数。修改类操作仍由服务端评估并要求确认。</p>
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
                      disabled={busy || taskBlocked || !available}
                      title={
                        taskBlocked
                          ? taskBlockText
                          : available
                            ? action.hint
                            : `缺少工具：${action.requiredTools.join(', ')}`
                      }
                    >
                      <span className="scenario-action-head">
                        <strong>{action.title}</strong>
                        <RiskBadge risk={actionRisk} />
                      </span>
                      <small>
                        {taskBlocked
                          ? !canExecute
                            ? roleBlockReason
                            : '系统未就绪，写操作已禁用'
                          : available
                            ? action.description
                            : '后端尚未注册该工具'}
                      </small>
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
      </details>

      <details className="card system-details">
        <summary>处理方式与技术信息</summary>
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
          <li><span>04</span><strong>哈希审计</strong><small>SHA-256 哈希链留痕</small></li>
        </ol>
      </div>
      </details>
    </section>
  );
}
