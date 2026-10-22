import type {
  BankingAccount,
  BankingCard,
  BankingOverview,
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
};

export const confirmationLabels: Record<string, string> = {
  not_required: '无需确认',
  pending: '等待用户确认',
  approved: '已确认',
  rejected: '已拒绝',
  blocked: '已拦截',
  expired: '已过期',
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

function firstNumber(records: UnknownRecord[], keys: string[], fallback = 0): number {
  const value = findValue(records, keys);
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function optionalNumber(records: UnknownRecord[], keys: string[]): number | null {
  const value = findValue(records, keys);
  if (value === undefined || value === null || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
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

function mapAccount(value: unknown, index: number): BankingAccount {
  const records = flattenRecords(value);
  const id = firstString(records, ['account_id', 'id', 'account_no', 'number'], `ACC-${index + 1}`);
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

function mapCard(value: unknown, index: number): BankingCard {
  const records = flattenRecords(value);
  const id = firstString(records, ['card_id', 'id', 'card_no'], `CARD-${index + 1}`);
  return {
    id,
    accountId: firstString(records, ['account_id', 'linked_account_id', 'primary_account_id']),
    name: firstString(records, ['card_name', 'name', 'title', 'card_type', 'type'], '银行卡'),
    maskedNumber: firstString(records, ['masked_number', 'masked_card', 'card_number_masked', 'last4'], id),
    status: firstString(records, ['status', 'card_status'], '正常'),
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

function mapSubscription(value: unknown, index: number): Subscription {
  const records = flattenRecords(value);
  const merchant = firstString(records, ['merchant', 'merchant_name', 'name', 'title'], '未知订阅');
  const status = firstString(records, ['status', 'subscription_status'], '正常');
  const riskFlag = firstString(records, ['risk_flag', 'abnormal_reason'], '');
  const abnormalFlag =
    firstBoolean(
      records,
      ['abnormal', 'is_abnormal', 'flagged', 'is_suspicious', 'anomaly'],
      /异常|风险|异常订阅|suspicious|abnormal/i.test(status),
    ) || Boolean(riskFlag);
  return {
    id: firstString(records, ['subscription_id', 'id', 'merchant_id'], `SUB-${index + 1}`),
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
  for (const item of abnormal) abnormalById.set(item.id, item);
  for (const item of subscriptions) {
    if (item.abnormal || abnormalIds.has(item.id)) {
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

export function riskLevelOfRisk(risk?: RiskAssessment | null, fallback: RiskLevel = 'green'): RiskLevel {
  return risk?.level ?? risk?.risk_level ?? fallback;
}

export function runRiskLevel(run: RunResponse): RiskLevel {
  return run.risk_level ?? riskLevelOfRisk(run.risk);
}

export function stepRiskLevel(stepRisk: RiskLevel | undefined, run: RunResponse): RiskLevel {
  return stepRisk ?? runRiskLevel(run);
}

export function resultRiskLevel(result: ToolResult, run: RunResponse): RiskLevel {
  return result.risk_level ?? riskLevelOfRisk(result.risk, runRiskLevel(run));
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
