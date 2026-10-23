import type {
  AgentRunInput,
  AuditResponse,
  AuditVerification,
  AutomationGoals,
  AutomationOrders,
  AutomationRunDueResult,
  AutomationSchedules,
  BankingOverview,
  BillAnomalies,
  BillReport,
  CardApplicationsResponse,
  ContactsResponse,
  ExecutionPlan,
  ReadinessSnapshot,
  RenewalReminders,
  RunResponse,
  SubscriptionCharges,
  ToolMetadata,
  TrustActionDetail,
  WealthHoldingsResponse,
  WealthOrdersResponse,
  WealthProductsResponse,
} from './types';
import { normalizeBankingOverview, normalizeReadiness } from './viewModel';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new Error('无法连接后端服务，请确认 AegisBank API 已启动。');
  }

  const payload: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      payload !== null && typeof payload === 'object' && 'detail' in payload
        ? (payload as { detail: unknown }).detail
        : null;
    const message =
      typeof detail === 'string'
        ? detail
        : detail
          ? JSON.stringify(detail)
          : `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return payload as T;
}

export async function fetchTools(userId = 'demo-user'): Promise<ToolMetadata[]> {
  const payload = await request<{ tools: ToolMetadata[] }>(
    `/tools?user_id=${encodeURIComponent(userId)}`,
  );
  return payload.tools ?? [];
}

export async function fetchPermissions(userId = 'demo-user'): Promise<ToolMetadata[]> {
  const payload = await request<{ permissions: ToolMetadata[] }>(
    `/permissions?user_id=${encodeURIComponent(userId)}`,
  );
  return payload.permissions ?? [];
}

export async function updatePermission(
  toolName: string,
  granted: boolean,
  userId = 'demo-user',
): Promise<void> {
  await request(`/permissions/${encodeURIComponent(toolName)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body: JSON.stringify({ granted }),
  });
}

export async function fetchBankingOverview(): Promise<BankingOverview> {
  const payload = await request<unknown>('/banking/overview?user_id=demo-user');
  return normalizeBankingOverview(payload);
}

export async function fetchReadiness(): Promise<ReadinessSnapshot> {
  const payload = await request<unknown>('/health/ready');
  return normalizeReadiness(payload);
}

export async function fetchTrustAction(actionId: string): Promise<TrustActionDetail> {
  const payload = await request<Partial<TrustActionDetail>>(
    `/trust/actions/${encodeURIComponent(actionId)}?user_id=demo-user`,
  );
  return {
    action_id: payload.action_id ?? actionId,
    user_id: payload.user_id ?? 'demo-user',
    status: payload.status ?? 'unknown',
    state: payload.state ?? 'UNKNOWN',
    risk_level: payload.risk_level ?? 'green',
    requires_reauth: payload.requires_reauth === true,
    created_at: payload.created_at ?? '',
    expires_at: payload.expires_at ?? '',
    resolved_at: payload.resolved_at ?? null,
    history: payload.history ?? [],
    envelopes: payload.envelopes ?? [],
    evidence: payload.evidence ?? [],
    evidence_list: payload.evidence_list ?? [],
  };
}

export async function previewPlan(input: AgentRunInput): Promise<ExecutionPlan> {
  return request<ExecutionPlan>('/planner/plan', {
    method: 'POST',
    body: JSON.stringify({ user_id: 'demo-user', ...input }),
  });
}

export async function runAgent(input: AgentRunInput): Promise<RunResponse> {
  return request<RunResponse>('/agent/run', {
    method: 'POST',
    body: JSON.stringify({ user_id: 'demo-user', ...input }),
  });
}

export async function resolveConfirmation(
  actionId: string,
  approved: boolean,
  reauthToken?: string,
): Promise<RunResponse> {
  return request<RunResponse>(`/confirmations/${encodeURIComponent(actionId)}`, {
    method: 'POST',
    body: JSON.stringify({ approved, reauth_token: reauthToken || null }),
  });
}

export async function fetchAudit(limit = 100): Promise<AuditResponse> {
  return request<AuditResponse>(`/audit?limit=${encodeURIComponent(limit)}`);
}

export async function verifyAudit(): Promise<AuditVerification> {
  return request<AuditVerification>('/audit/verify');
}

/* ------------------------------------------------------------------ */
/* 六场景只读接口                                                       */
/* ------------------------------------------------------------------ */

export async function fetchWealthProducts(riskLevel?: string): Promise<WealthProductsResponse> {
  const query = riskLevel ? `?risk_level=${encodeURIComponent(riskLevel)}` : '';
  const payload = await request<Partial<WealthProductsResponse>>(`/wealth/products${query}`);
  return {
    products: payload.products ?? [],
    count: payload.count ?? payload.products?.length ?? 0,
    simulated: payload.simulated,
    disclaimer: payload.disclaimer,
  };
}

export async function fetchWealthHoldings(): Promise<WealthHoldingsResponse> {
  const payload = await request<Partial<WealthHoldingsResponse>>(
    '/wealth/holdings?user_id=demo-user',
  );
  return {
    holdings: payload.holdings ?? [],
    count: payload.count ?? payload.holdings?.length ?? 0,
    total_market_value_cny: payload.total_market_value_cny ?? 0,
    total_principal_cny: payload.total_principal_cny ?? 0,
    simulated: payload.simulated,
    disclaimer: payload.disclaimer,
  };
}

export async function fetchWealthOrders(): Promise<WealthOrdersResponse> {
  const payload = await request<Partial<WealthOrdersResponse>>(
    '/wealth/orders?user_id=demo-user',
  );
  return {
    orders: payload.orders ?? [],
    count: payload.count ?? payload.orders?.length ?? 0,
    simulated: payload.simulated,
    disclaimer: payload.disclaimer,
  };
}

export async function fetchContacts(): Promise<ContactsResponse> {
  const payload = await request<Partial<ContactsResponse>>('/contacts?user_id=demo-user');
  return {
    contacts: payload.contacts ?? [],
    count: payload.count ?? payload.contacts?.length ?? 0,
    simulated: payload.simulated,
  };
}

export async function fetchBillReport(
  period: 'month' | 'year' = 'month',
  month?: string,
): Promise<BillReport> {
  const params = new URLSearchParams({
    account_id: 'ACC-1001',
    period,
    user_id: 'demo-user',
  });
  if (month) params.set('month', month);
  const payload = await request<Partial<BillReport>>(`/bills/report?${params.toString()}`);
  return {
    account_id: payload.account_id ?? 'ACC-1001',
    period: payload.period ?? period,
    label: payload.label ?? (period === 'year' ? '年度账单' : '本月账单'),
    month: payload.month ?? null,
    year: payload.year ?? new Date().getFullYear(),
    total_spend_cny: payload.total_spend_cny ?? 0,
    categories: payload.categories ?? {},
    top_merchants: payload.top_merchants ?? [],
    transaction_count: payload.transaction_count ?? 0,
    all_transaction_count: payload.all_transaction_count ?? 0,
    comparison: payload.comparison ?? {
      baseline: period === 'year' ? '去年' : '上月',
      previous_total_cny: 0,
      change_cny: 0,
      change_pct: null,
      direction: '缺少可比基线',
      comparable: false,
    },
    budget_usage: payload.budget_usage ?? [],
    conclusion: payload.conclusion ?? '暂无账单结论。',
    simulated: payload.simulated ?? true,
  };
}

export async function fetchBillAnomalies(
  period: 'month' | 'year' = 'month',
  month?: string,
): Promise<BillAnomalies> {
  const params = new URLSearchParams({
    account_id: 'ACC-1001',
    period,
    user_id: 'demo-user',
  });
  if (month) params.set('month', month);
  const payload = await request<Partial<BillAnomalies>>(`/bills/anomalies?${params.toString()}`);
  return {
    account_id: payload.account_id ?? 'ACC-1001',
    period: payload.period ?? period,
    month: payload.month ?? '',
    anomalies: payload.anomalies ?? [],
    counts_by_kind: payload.counts_by_kind ?? {},
    total: payload.total ?? payload.anomalies?.length ?? 0,
    high_severity_count: payload.high_severity_count ?? 0,
    rules: payload.rules ?? [],
    conclusion: payload.conclusion ?? '暂无异常检测结论。',
    simulated: payload.simulated ?? true,
  };
}

export async function fetchSubscriptionCharges(): Promise<SubscriptionCharges> {
  const payload = await request<Partial<SubscriptionCharges>>(
    '/subscriptions/charges?user_id=demo-user',
  );
  return {
    account_id: payload.account_id ?? null,
    subscriptions: payload.subscriptions ?? [],
    total: payload.total ?? payload.subscriptions?.length ?? 0,
    registered_count: payload.registered_count ?? 0,
    unregistered_count: payload.unregistered_count ?? 0,
    window: payload.window ?? '',
    conclusion: payload.conclusion ?? '暂无订阅扣费结论。',
    simulated: payload.simulated ?? true,
  };
}

export async function fetchRenewalReminders(daysAhead = 30): Promise<RenewalReminders> {
  const payload = await request<Partial<RenewalReminders>>(
    `/subscriptions/reminders?days_ahead=${encodeURIComponent(daysAhead)}&user_id=demo-user`,
  );
  return {
    reminders: payload.reminders ?? [],
    count: payload.count ?? payload.reminders?.length ?? 0,
    cycle: payload.cycle ?? 'all',
    days_ahead: payload.days_ahead ?? daysAhead,
    as_of: payload.as_of ?? '',
    channel: payload.channel ?? 'in_app_only',
    note: payload.note ?? '',
    simulated: payload.simulated ?? true,
  };
}

export async function fetchCardApplications(): Promise<CardApplicationsResponse> {
  const payload = await request<Partial<CardApplicationsResponse>>(
    '/cards/applications?user_id=demo-user',
  );
  return {
    applications: payload.applications ?? [],
    count: payload.count ?? payload.applications?.length ?? 0,
    simulated: payload.simulated,
  };
}

export async function fetchAutomationSchedules(): Promise<AutomationSchedules> {
  const payload = await request<Partial<AutomationSchedules>>(
    '/automation/schedules?user_id=demo-user',
  );
  return {
    tasks: payload.tasks ?? [],
    count: payload.count ?? payload.tasks?.length ?? 0,
    simulated: payload.simulated,
  };
}

export async function fetchAutomationGoals(): Promise<AutomationGoals> {
  const payload = await request<Partial<AutomationGoals>>(
    '/automation/goals?user_id=demo-user',
  );
  return {
    goals: payload.goals ?? [],
    count: payload.count ?? payload.goals?.length ?? 0,
    simulated: payload.simulated,
  };
}

export async function fetchAutomationOrders(): Promise<AutomationOrders> {
  const payload = await request<Partial<AutomationOrders>>(
    '/automation/orders?user_id=demo-user',
  );
  return {
    orders: payload.orders ?? [],
    count: payload.count ?? payload.orders?.length ?? 0,
    simulated: payload.simulated,
  };
}

export async function runAutomationDue(now?: string): Promise<AutomationRunDueResult> {
  const query = now ? `?now=${encodeURIComponent(now)}` : '';
  const payload = await request<Partial<AutomationRunDueResult>>(
    `/automation/run-due${query}`,
    { method: 'POST' },
  );
  return {
    status: payload.status ?? 'unknown',
    risk_level: payload.risk_level,
    now: payload.now ?? null,
    executed: payload.executed ?? [],
    failed: payload.failed ?? [],
    executed_count: payload.executed_count ?? payload.executed?.length ?? 0,
    failed_count: payload.failed_count ?? payload.failed?.length ?? 0,
    simulated: payload.simulated ?? true,
  };
}
