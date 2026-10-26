import { formatCny } from './risk';
import type {
  BankingAccount,
  BankingCard,
  BankingOverview,
  EvidenceItem,
  PlanStep,
  ReadinessComponent,
  ReadinessSnapshot,
  ReadinessStatus,
  RiskAssessment,
  RiskLevel,
  RunResponse,
  Subscription,
  ToolResult,
} from './types';

type UnknownRecord = Record<string, unknown>;

export const statusLabels: Record<string, string> = {
  completed: '执行完成',
  awaiting_confirmation: '等待人工确认',
  needs_clarification: '需要补充信息',
  blocked: '被权限网关拦截',
  rejected: '用户已拒绝',
  failed: '执行失败',
  unknown: '结果未知（需对账）',
  reconciled: '已人工对账',
  rolled_back: '已人工回滚',
  paused: '已暂停（可恢复）',
  pending: '等待人工确认（尚未执行）',
  executing: '执行中',
  rollback_blocked: '回滚被阻止（存在不可撤销步骤）',
  planned: '计划已生成',
  awaiting_reauth: '等待二次验证',
  action_failed: '动作执行失败',
  completed_with_warnings: '执行完成（有告警）',
};

export const statusDescriptions: Record<string, string> = {
  completed: '全部节点已通过统一权限网关执行完成，结果已写入审计哈希链。',
  awaiting_confirmation: '计划已生成，正在等待用户在有效期内完成人工确认。',
  needs_clarification: 'Planner 判断信息不足，需要补充任务信息后重新发起。',
  blocked: '统一权限网关或风险策略拦截请求，未执行任何工具。',
  rejected: '用户明确拒绝，未执行任何资金或账户变更。',
  failed: '执行过程中失败，失败原因已写入审计链，系统不会自动重试。',
  unknown: '执行结果不确定：副作用可能已经发生。请勿重复提交，需要人工对账或回滚。',
  reconciled: 'UNKNOWN 状态已由人工对账处理，结论已写入审计链。',
  rolled_back: '补偿链已完成；请结合逐步补偿记录核对资金与业务状态。',
  paused: '执行在步骤之间暂停；已执行步骤不会重复执行，可恢复剩余节点或人工回退。',
  pending: '动作尚未开始执行，步骤日志为空；完成人工确认后才会产生执行记录。',
  executing: '动作正在执行中，步骤日志会随节点推进持续更新。',
  rollback_blocked: '回滚被不可撤销步骤阻止：已执行步骤无法自动补偿，需要人工与银行核实后对账。',
  planned: '只生成了执行计划预览，尚未执行任何工具。',
};

export const eventLabels: Record<string, string> = {
  tool_executed: '工具执行',
  confirmation_requested: '等待确认',
  confirmation_approved: '确认通过',
  confirmation_rejected: '用户拒绝',
  confirmation_expired: '确认过期',
  gateway_blocked: '网关拦截',
  tool_failed: '执行失败',
  permission_denied: '权限不足',
  plan_created: '计划生成',
  state_transition: '状态迁移',
  state_transition_rejected: '非法迁移被拒',
  action_reconciled: '人工对账',
  action_rolled_back: '人工回滚',
  scheduled_task_executed: '定时任务执行',
  scheduled_task_failed: '定时任务失败',
  tool_outcome_unknown: '执行结果未知',
  compensation_executed: '补偿已执行',
  compensation_failed: '补偿失败',
  compensation_blocked: '补偿被阻止',
  rollback_blocked: '回滚被阻止',
  action_paused: '执行已暂停',
  mfa_failed: 'MFA 验证失败',
  mfa_challenge_issued: 'MFA 挑战签发',
  sandbox_blocked: '沙箱拦截',
  sandbox_timeout: '沙箱超时',
  circuit_breaker_open: '熔断打开',
  circuit_breaker_reset: '熔断重置',
  circuit_breaker_unlock: '运维解除熔断',
  im_message_executed: 'IM 消息执行',
  im_message_rejected: 'IM 消息拒绝',
  role_revocation: '角色撤权',
  permission_updated: '权限变更',
  injection_blocked: '注入拦截',
  planning_clarification: '规划澄清',
  action_failed: '动作执行失败',
  mfa_succeeded: 'MFA 验证通过',
  action_executed: '动作执行',
  action_rejected: '动作拒绝',
  action_expired: '动作过期',
};

export const confirmationLabels: Record<string, string> = {
  not_required: '无需确认',
  pending: '等待用户确认',
  approved: '已确认',
  rejected: '已拒绝',
  blocked: '已拦截',
  expired: '已过期',
  executing: '执行中',
  failed: '执行失败',
  DRAFT: '草稿',
  AWAITING_CONFIRMATION: '等待确认',
  AWAITING_REAUTH: '等待二次验证',
  APPROVED: '已批准',
  EXECUTING: '执行中',
  COMPLETED: '已完成',
  FAILED: '已失败',
  REJECTED: '已拒绝',
  EXPIRED: '已过期',
  UNKNOWN: '结果未知',
  RECONCILED: '已对账',
  ROLLED_BACK: '已回滚',
  unknown: '结果未知',
  reconciled: '已对账',
  rolled_back: '已回滚',
  permission_change: '权限变更',
  reauth_failed: '二次验证失败',
  ops: '运维操作',
  demo: '演示数据',
  scheduled: '定时任务',
};

export const argumentLabels: Record<string, string> = {
  account_id: '账户',
  from_account: '转出账户',
  to_account: '转入账户',
  amount_cny: '金额（元）',
  card_id: '卡片',
  new_day: '还款日',
  period: '账期',
  note: '备注',
  merchant: '商户',
  subscription_id: '订阅',
  limit_cny: '限额（元）',
  daily_limit_cny: '每日交易限额（元）',
  transaction_limit_cny: '交易限额（元）',
  status: '状态',
  total_due_cny: '应还金额',
  minimum_due_cny: '最低还款',
  due_date: '到期日',
  available_balance_cny: '可用余额',
  balance_cny: '余额',
  credit_limit_cny: '信用额度',
  next_billing_date: '下次扣款',
  billing_cycle: '扣款周期',
  transaction_id: '交易编号',
  simulated: '模拟数据',
  reason: '原因',
  risk_level: '风险等级',
  product_id: '产品',
  holding_id: '持仓',
  shares: '份额',
  risk_preference: '风险偏好',
  requested_limit_cny: '申请额度（元）',
  to_name: '收款人',
  to_phone: '收款手机号',
  goal_id: '预算目标',
  run_at: '执行时间',
  recurrence: '重复周期',
  now: '快照时间',
  days_ahead: '提醒窗口（天）',
  cycle: '周期',
};

export const evidenceSourceLabels: Record<string, string> = {
  mock_bank: 'Mock 数据',
  human_confirmation: '人工确认',
  policy_engine: '策略判断',
  audit_chain: '审计哈希链',
};

export const severityLabels: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

export const readinessStatusLabels: Record<string, string> = {
  ready: '系统就绪',
  degraded: '降级运行',
  not_ready: '系统未就绪',
};

export const readinessComponentLabels: Record<string, string> = {
  sqlite: 'SQLite 数据库',
  audit_chain: '审计哈希链',
  mock_bank_seed: '模拟银行种子',
  planner: '规划器',
};

export const readinessComponentOrder = ['sqlite', 'audit_chain', 'mock_bank_seed', 'planner'] as const;

export const wealthRiskLabels: Record<string, string> = {
  R1: 'R1 保守型',
  R2: 'R2 稳健型',
  R3: 'R3 平衡型',
  R4: 'R4 成长型',
  R5: 'R5 进取型',
};

function asRecord(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function flattenRecords(value: unknown, depth = 0, output: UnknownRecord[] = []): UnknownRecord[] {
  const record = asRecord(value);
  if (!record || depth > 3) return output;
  output.push(record);
  for (const child of Object.values(record)) {
    if (asRecord(child)) flattenRecords(child, depth + 1, output);
  }
  return output;
}

function findValue(records: UnknownRecord[], keys: string[]): unknown {
  for (const record of records) {
    for (const key of keys) {
      if (record[key] !== undefined && record[key] !== null) return record[key];
    }
  }
  return undefined;
}

function firstString(records: UnknownRecord[], keys: string[], fallback = ''): string {
  const value = findValue(records, keys);
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

function firstNumber(records: UnknownRecord[], keys: string[]): number {
  const value = findValue(records, keys);
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') throw new Error('金融数据缺少有效数值');
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN;
  if (!Number.isFinite(parsed)) throw new Error('金融数据包含非法数值');
  return parsed;
}

function optionalNumber(records: UnknownRecord[], keys: string[]): number | null {
  const value = findValue(records, keys);
  if (value === undefined || value === null || value === '') return null;
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

function firstArray(records: UnknownRecord[], keys: string[]): unknown[] {
  const value = findValue(records, keys);
  return Array.isArray(value) ? value : [];
}

function firstBoolean(records: UnknownRecord[], keys: string[], fallback = false): boolean {
  const value = findValue(records, keys);
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    if (['true', '1', 'yes', 'abnormal', '异常'].includes(value.toLowerCase())) return true;
    if (['false', '0', 'no', 'normal', '正常'].includes(value.toLowerCase())) return false;
  }
  return fallback;
}

function mapAccount(value: unknown): BankingAccount {
  const records = flattenRecords(value);
  const id = firstString(records, ['account_id', 'id', 'account_no', 'number']);
  if (!id) throw new Error('账户标识缺失，无法展示余额');
  const type = firstString(records, ['account_type', 'type', 'kind'], '活期账户');
  return {
    id,
    name: firstString(records, ['account_name', 'name', 'nickname', 'label'], type),
    type,
    balanceCny: firstNumber(records, ['balance_cny', 'balance', 'current_balance_cny', 'available_balance_cny', 'account_balance_cny', 'amount_cny']),
    availableCny: optionalNumber(records, [
      'available_balance_cny',
      'available_balance',
      'available_cny',
      'available_amount_cny',
      'available_amount',
      'available',
    ]),
    currency: firstString(records, ['currency', 'currency_code'], 'CNY'),
    maskedNumber: firstString(records, ['masked_number', 'masked_account', 'mask', 'account_no_masked'], id),
  };
}

function mapCard(value: unknown): BankingCard {
  const records = flattenRecords(value);
  const id = firstString(records, ['card_id', 'id', 'card_no']);
  if (!id) throw new Error('卡片标识缺失，无法展示卡片');
  return {
    id,
    accountId: firstString(records, ['account_id', 'linked_account_id', 'primary_account_id']),
    name: firstString(records, ['card_name', 'name', 'title', 'card_type', 'type'], '银行卡'),
    maskedNumber: firstString(records, ['masked_number', 'masked_card', 'card_number_masked', 'last4'], id),
    status: firstString(records, ['status', 'card_status'], '未知'),
    creditLimitCny: optionalNumber(records, ['credit_limit_cny', 'credit_limit', 'limit_cny', 'limit']),
    availableLimitCny: optionalNumber(records, [
      'available_limit_cny',
      'available_credit_cny',
      'available_credit',
      'available_limit',
    ]),
    repaymentDay: optionalNumber(records, ['repayment_day', 'billing_day', 'new_day']),
  };
}

function mapSubscription(value: unknown): Subscription {
  const records = flattenRecords(value);
  const merchant = firstString(records, ['merchant', 'merchant_name', 'name', 'title'], '未知订阅');
  const status = firstString(records, ['status', 'subscription_status'], '未知');
  const subscriptionId = firstString(records, ['subscription_id', 'id', 'merchant_id']);
  if (!subscriptionId) throw new Error('订阅标识缺失');
  const riskFlag = firstString(records, ['risk_flag', 'abnormal_reason'], '');
  const abnormalFlag =
    firstBoolean(
      records,
      ['abnormal', 'is_abnormal', 'flagged', 'is_suspicious', 'anomaly'],
      /异常|风险|异常订阅|suspicious|abnormal/i.test(status),
    ) || Boolean(riskFlag);
  return {
    id: subscriptionId,
    merchant,
    amountCny: firstNumber(records, ['amount_cny', 'amount', 'monthly_amount_cny', 'monthly_cost_cny', 'price_cny', 'price']),
    cycle: firstString(records, ['billing_cycle', 'cycle', 'frequency', 'period'], '每月'),
    nextBillingDate: firstString(records, [
      'next_billing_date',
      'next_charge_date',
      'renewal_date',
      'next_billing_at',
    ]),
    status,
    abnormal: abnormalFlag,
    reason: firstString(records, [
      'abnormal_reason',
      'risk_flag',
      'reason',
      'risk_reason',
      'risk_reasons',
      'note',
      'description',
    ], abnormalFlag ? '订阅行为与日常消费模式不一致' : ''),
  };
}

export function normalizeBankingOverview(payload: unknown): BankingOverview {
  const records = flattenRecords(payload);
  const rawAccounts = firstArray(records, ['accounts', 'bank_accounts', 'account_list']);
  const rawCards = firstArray(records, ['cards', 'bank_cards', 'card_list']);
  const rawSubscriptions = firstArray(records, [
    'subscriptions',
    'recurring_subscriptions',
    'subscription_list',
  ]);
  const rawAbnormal = firstArray(records, [
    'abnormal_subscriptions',
    'suspicious_subscriptions',
    'flagged_subscriptions',
  ]);

  const accounts = rawAccounts.map(mapAccount);
  const cards = rawCards.map(mapCard);
  const subscriptions = rawSubscriptions.map(mapSubscription);
  const abnormalIds = new Set(
    rawAbnormal.filter((item): item is string => typeof item === 'string'),
  );
  const abnormal = rawAbnormal
    .filter((item) => asRecord(item) !== null)
    .map(mapSubscription);
  const abnormalById = new Map<string, Subscription>();
  const inactiveStatuses = new Set(['cancelled', 'canceled', 'inactive', 'expired', 'terminated', '已取消', '已终止', '已过期']);
  const inactiveIds = new Set(subscriptions
    .filter((item) => inactiveStatuses.has(item.status.trim().toLowerCase()))
    .map((item) => item.id));
  for (const item of abnormal) {
    if (!inactiveIds.has(item.id) && !inactiveStatuses.has(item.status.trim().toLowerCase())) {
      abnormalById.set(item.id, item);
    }
  }
  for (const item of subscriptions) {
    if (!inactiveIds.has(item.id) && (item.abnormal || abnormalIds.has(item.id))) {
      abnormalById.set(item.id, item.abnormal ? item : { ...item, abnormal: true });
    }
  }

  return {
    accounts,
    cards,
    subscriptions,
    abnormalSubscriptions: [...abnormalById.values()],
    monthSpendingCny: firstNumber(records, [
      'month_spending_cny',
      'monthly_spend_cny',
      'monthly_spending_cny',
      'month_spending',
      'monthly_spending',
      'monthly_spent',
      'monthly_expense',
      'month_spent_cny',
      'month_expense_cny',
      'month_expense',
      'this_month_spending_cny',
      'month_total_spending_cny',
    ]),
    todayTransferTotalCny: firstNumber(records, [
      'today_transfer_total_cny',
      'daily_transfer_total_cny',
      'today_transfer_total',
      'today_transferred_cny',
      'today_transferred',
      'today_transfer_cny',
      'today_transfer_amount_cny',
      'today_transfer_amount',
      'today_accumulated_transfer_cny',
      'today_accumulated_transfer',
      'transfer_total_today_cny',
      'today_transfer_sum_cny',
    ]),
    asOf: firstString(records, ['as_of', 'updated_at', 'generated_at', 'snapshot_at']),
  };
}

function addUnique(target: string[], values: unknown): void {
  if (!Array.isArray(values)) {
    if (typeof values === 'string' && values.trim()) target.push(values.trim());
    return;
  }
  for (const value of values) {
    if (typeof value === 'string' && value.trim() && !target.includes(value.trim())) {
      target.push(value.trim());
    }
  }
}

export function riskLevelOfRisk(risk?: RiskAssessment | null, fallback: RiskLevel = 'red'): RiskLevel {
  const level = risk?.level ?? risk?.risk_level;
  return level === 'green' || level === 'yellow' || level === 'red' ? level : fallback;
}

export function runRiskLevel(run: RunResponse): RiskLevel {
  return riskLevelOfRisk({ level: run.risk_level ?? run.risk?.level ?? run.risk?.risk_level });
}

export function stepRiskLevel(stepRisk: RiskLevel | undefined, run: RunResponse): RiskLevel {
  return riskLevelOfRisk({ level: stepRisk }, runRiskLevel(run));
}

export function resultRiskLevel(result: ToolResult, run: RunResponse): RiskLevel {
  return riskLevelOfRisk({ level: result.risk_level ?? result.risk?.level ?? result.risk?.risk_level }, runRiskLevel(run));
}

export function collectRiskReasons(run: RunResponse): string[] {
  const reasons: string[] = [];
  const risk = asRecord(run.risk);
  if (risk) {
    addUnique(reasons, risk.reasons);
    addUnique(reasons, risk.reason);
    addUnique(reasons, risk.matched_rules);
    addUnique(reasons, risk.risk_reasons);
  }
  addUnique(reasons, run.risk_reasons);
  addUnique(reasons, run.plan?.risk_reasons);
  for (const step of run.plan?.steps ?? []) {
    addUnique(reasons, step.risk_reasons);
  }
  for (const result of run.results ?? []) {
    addUnique(reasons, result.risk_reasons);
    const resultRisk = asRecord(result.risk);
    if (resultRisk) {
      addUnique(reasons, resultRisk.reasons);
      addUnique(reasons, resultRisk.reason);
      addUnique(reasons, resultRisk.matched_rules);
    }
  }
  return reasons;
}

export function prettyEvidence(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return '—';
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function formatDisplayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value);
  if (typeof value === 'object') return prettyEvidence(value);
  return String(value);
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || '—';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

export function paginate<T>(items: T[], page: number, pageSize: number) {
  const safePageSize = Math.max(1, pageSize);
  const totalPages = Math.max(1, Math.ceil(items.length / safePageSize));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const start = (safePage - 1) * safePageSize;
  return {
    items: items.slice(start, start + safePageSize),
    page: safePage,
    totalPages,
    total: items.length,
    start: items.length === 0 ? 0 : start + 1,
    end: Math.min(start + safePageSize, items.length),
  };
}

/* ------------------------------------------------------------------ */
/* 信任层与六场景展示用纯函数                                            */
/* ------------------------------------------------------------------ */

export function statusLabel(status: string): string {
  return statusLabels[status] ?? status;
}

export function statusDescription(status: string): string {
  return statusDescriptions[status] ?? '';
}

export function severityLabel(severity: string): string {
  return severityLabels[severity] ?? severity;
}

export function evidenceSourceLabel(source: string): string {
  return evidenceSourceLabels[source] ?? source;
}

export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value.toFixed(2)}%`;
}

export function formatSignedCny(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value === 0) return formatCny(0);
  return `${value > 0 ? '+' : '−'}${formatCny(Math.abs(value))}`;
}

export function formatChangePct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${Math.abs(value).toFixed(1)}%`;
}

export function daysLeft(days: number | null | undefined, overdue = false): string {
  if (days === null || days === undefined || !Number.isFinite(days)) return '—';
  if (overdue || days < 0) return `已逾期 ${Math.abs(Math.trunc(days))} 天`;
  if (days === 0) return '今天到期';
  return `${Math.trunc(days)} 天后`;
}

export function wealthRiskLevel(riskLevel: string): RiskLevel {
  switch (riskLevel.trim().toUpperCase()) {
    case 'R1':
    case 'R2':
      return 'green';
    case 'R3':
      return 'yellow';
    case 'R4':
    case 'R5':
      return 'red';
    default:
      return 'red';
  }
}

export function wealthRiskLabel(riskLevel: string): string {
  const key = riskLevel.trim().toUpperCase();
  return wealthRiskLabels[key] ?? riskLevel;
}

export function normalizeEvidence(value: unknown): EvidenceItem[] {
  const items = Array.isArray(value) ? value : [];
  const output: EvidenceItem[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    const record = asRecord(item);
    if (!record) continue;
    const source = typeof record.source === 'string' ? record.source.trim() : '';
    if (!source) continue;
    const verified = record.verified === true;
    const verificationKind =
      typeof record.verification_kind === 'string' ? record.verification_kind : '';
    const detail = typeof record.detail === 'string' ? record.detail : '';
    const key = `${source}|${verified}|${detail}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push({
      source,
      verified,
      verification_kind: verificationKind,
      detail,
    });
  }
  return output;
}

export function normalizeReadiness(payload: unknown): ReadinessSnapshot {
  const record = asRecord(payload) ?? {};
  const rawComponents = asRecord(record.components) ?? {};
  const components: Record<string, ReadinessComponent> = {};
  for (const [name, value] of Object.entries(rawComponents)) {
    const item = asRecord(value);
    components[name] = {
      ok: item?.ok === true,
      detail: typeof item?.detail === 'string' ? item.detail : '',
    };
  }
  const rawStatus = typeof record.status === 'string' ? record.status : '';
  const status: ReadinessStatus =
    rawStatus === 'ready' || rawStatus === 'degraded' ? rawStatus : 'not_ready';
  return { status, components };
}

export function readinessStatusLabel(status: ReadinessStatus | string): string {
  return readinessStatusLabels[status] ?? String(status);
}

export function readinessComponentLabel(name: string): string {
  return readinessComponentLabels[name] ?? name;
}

export function readinessBlockers(snapshot: ReadinessSnapshot | null): string[] {
  if (!snapshot) return ['尚未获取系统就绪状态'];
  const reasons = Object.entries(snapshot.components)
    .filter(([, component]) => !component.ok)
    .map(([name, component]) => {
      const detail = component.detail?.trim() || '不可用';
      return `${readinessComponentLabel(name)}：${detail}`;
    });
  if (snapshot.status === 'ready') return [];
  if (reasons.length === 0) {
    reasons.push(
      snapshot.status === 'degraded' ? '系统处于降级运行状态' : '关键依赖不可用',
    );
  }
  return reasons;
}

/* ------------------------------------------------------------------ */
/* 确认弹窗与执行回执的「人话」层（UX-10 / UX-14）                        */
/* ------------------------------------------------------------------ */

export interface StepSummary {
  /** 一句话说明这笔操作是什么。 */
  headline: string;
  /** 补充说明：对象、金额、可逆性、备注。 */
  details: string[];
  /** 是否包含运行期才能确定的占位符（如 ${steps.step-1...}）。 */
  unresolved: boolean;
}

function hasUnresolved(value: unknown, depth = 0): boolean {
  if (depth > 4) return false;
  if (typeof value === 'string') return /\$\{[^}]+\}/.test(value);
  if (Array.isArray(value)) return value.some((item) => hasUnresolved(item, depth + 1));
  if (value !== null && typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).some((item) =>
      hasUnresolved(item, depth + 1),
    );
  }
  return false;
}

function argumentValue(value: unknown, key: string): string {
  if (typeof value === 'string') {
    return /\$\{[^}]+\}/.test(value) ? '执行时确定' : value;
  }
  if (typeof value === 'number') {
    const moneyLike = /(amount|balance|limit|due|cny)/.test(key);
    return moneyLike ? formatCny(value) : String(value);
  }
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (value === null || value === undefined) return '—';
  return formatDisplayValue(value);
}

export function confirmationSummary(step: PlanStep): StepSummary {
  const args = (step.arguments ?? {}) as Record<string, unknown>;
  const unresolved = hasUnresolved(args);
  const text = (key: string): string =>
    typeof args[key] === 'string' && !/\$\{/.test(String(args[key]))
      ? String(args[key])
      : '';
  const amount = typeof args.amount_cny === 'number' ? args.amount_cny : null;
  const reversibleNote = step.irreversible
    ? step.irreversible_reason || '该步骤执行后不可撤销'
    : '如执行后需要撤销，可在步骤日志中申请人工回退';

  switch (step.tool_name) {
    case 'transfer': {
      const from = text('from_account');
      const to = text('to_account');
      return {
        headline: amount !== null ? `转账 ${formatCny(amount)}` : '发起一笔转账',
        details: [
          from && to ? `从 ${from} 转到 ${to}` : '转出与转入账户将在执行时确定',
          to ? `收款账户 ${to}` : '',
          text('note') ? `备注：${text('note')}` : '',
          reversibleNote,
        ].filter(Boolean),
        unresolved,
      };
    }
    case 'cancel_subscription': {
      const subscription = text('subscription_id');
      return {
        headline: '取消一个订阅',
        details: [
          subscription ? `订阅：${subscription}` : '具体订阅由账单分析结果执行时确定',
          '取消后本周期不再自动扣费',
          reversibleNote,
        ].filter(Boolean),
        unresolved,
      };
    }
    case 'adjust_repayment_date': {
      const card = text('card_id');
      const day = args.new_day;
      return {
        headline: '调整信用卡还款日',
        details: [
          card ? `卡片：${card}` : '卡片在执行时确定',
          day !== undefined ? `新的还款日：每月 ${argumentValue(day, 'new_day')} 日` : '',
          reversibleNote,
        ].filter(Boolean),
        unresolved,
      };
    }
    case 'set_transaction_limit': {
      const card = text('card_id');
      return {
        headline: '调整每日交易限额',
        details: [
          card ? `卡片：${card}` : '卡片在执行时确定',
          args.daily_limit_cny !== undefined
            ? `新限额：${argumentValue(args.daily_limit_cny, 'daily_limit_cny')}`
            : '',
          reversibleNote,
        ].filter(Boolean),
        unresolved,
      };
    }
    case 'report_card_lost':
      return {
        headline: '挂失银行卡',
        details: [
          text('card_id') ? `卡片：${text('card_id')}` : '卡片在执行时确定',
          '挂失后该卡将立即停止交易，属于不可撤销操作',
        ],
        unresolved,
      };
    case 'unlock_card':
      return {
        headline: '解锁银行卡',
        details: [
          text('card_id') ? `卡片：${text('card_id')}` : '卡片在执行时确定',
          reversibleNote,
        ],
        unresolved,
      };
    default: {
      const detailKeys = Object.keys(args).slice(0, 4);
      return {
        headline: step.title || step.tool_name,
        details: detailKeys.map(
          (key) => `${argumentLabels[key] ?? key}：${argumentValue(args[key], key)}`,
        ),
        unresolved,
      };
    }
  }
}

/** 回执首屏的一句话结论（优先使用工具返回的业务消息）。 */
export function receiptHeadline(run: RunResponse): string {
  const firstMessage = run.results?.[0]?.message?.trim();
  if (run.status === 'completed') return firstMessage || '操作已完成';
  if (run.status === 'rejected') return '操作已拒绝，未执行任何工具';
  if (run.status === 'failed') return '执行失败，请核对步骤记录和账户结果';
  if (run.status === 'unknown') return '结果未知：需要人工对账';
  if (run.status === 'rolled_back') return '补偿链已完成，请核对逐步结果';
  if (run.status === 'rollback_blocked') return '回滚被阻止：存在不可撤销步骤';
  if (run.status === 'paused') return '执行已暂停，剩余步骤未执行';
  if (run.status === 'awaiting_confirmation') return '等待你确认后才会执行';
  if (run.status === 'needs_clarification') return '需要补充信息后才能继续';
  if (run.status === 'reconciled') return '已人工对账';
  return statusLabel(run.status);
}

/** 从工具结果里取执行时间；没有就退回空串（由调用方展示占位）。 */
export function resultExecutedAt(run: RunResponse): string {
  for (const result of run.results ?? []) {
    const data = result.data as Record<string, unknown> | undefined;
    const value = data?.executed_at;
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}
