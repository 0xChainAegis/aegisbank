import type { AegisCapability, AegisRole } from './roles';
import type {
  ActionJournal,
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
  BreakerEventsResponse,
  BreakerPolicy,
  BreakerStatus,
  CardApplicationsResponse,
  ContactsResponse,
  PlanPreviewResponse,
  ImHelp,
  ImMessageInput,
  ImMessageReply,
  MfaProvidersResponse,
  ReadinessSnapshot,
  RenewalReminders,
  RunResponse,
  SandboxDemoKind,
  SandboxDemoResult,
  SandboxPolicyResponse,
  SubscriptionCharges,
  ToolMetadata,
  TrustActionDetail,
  WealthHoldingsResponse,
  WealthOrdersResponse,
  WealthProductsResponse,
} from './types';
import { normalizeBankingOverview, normalizeReadiness } from './viewModel';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

let currentRole: AegisRole = 'user';

/** Every request is role-scoped; call this whenever the top-bar role changes. */
export function setApiRole(role: AegisRole): void {
  currentRole = role;
}

export function getApiRole(): AegisRole {
  return currentRole;
}

/**
 * 生成幂等键（UX-18）。一次逻辑提交生成一次；重试复用同一个 key，
 * 进入终态后清空。浏览器不支持 randomUUID 时退回时间戳 + 随机数。
 */
export function createIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422 的 detail 是数组；直接 JSON.stringify 会把原始结构糊在界面上。
    const parts = detail
      .map((item) => {
        if (!item || typeof item !== 'object') return '';
        const record = item as Record<string, unknown>;
        const location = Array.isArray(record.loc) ? record.loc.map(String).join('.') : '';
        const message = typeof record.msg === 'string' ? record.msg : '';
        return [location, message].filter(Boolean).join('：');
      })
      .filter(Boolean);
    return parts.length > 0 ? `提交内容校验未通过：${parts.join('；')}` : '提交内容校验未通过。';
  }
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === 'string' && record.message.trim()) {
      const code = typeof record.code === 'string' ? record.code : '';
      return code ? `${record.message}（${code}）` : record.message;
    }
    return JSON.stringify(detail);
  }
  return null;
}

export interface RequestOptions extends RequestInit {
  /** 同一逻辑请求重试时复用同一个 key，避免产生第二笔待确认动作。 */
  idempotencyKey?: string;
  timeoutMs?: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { idempotencyKey, timeoutMs = 30_000, headers, signal, ...init } = options;
  const controller = new AbortController();
  const forwardAbort = () => controller.abort();
  signal?.addEventListener('abort', forwardAbort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Aegis-Role': currentRole,
        ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
        ...(headers ?? {}),
      },
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error) {
      // A proxy or server can return an HTML/plain-text error. Preserve its HTTP
      // status so a definite rejection is not treated as a lost write response.
      if (!response.ok && !controller.signal.aborted) {
        throw new ApiError(`请求失败（HTTP ${response.status}），服务未返回有效的 JSON 错误详情。`, response.status);
      }
      throw error;
    }
    if (!response.ok) {
      const detail = payload && typeof payload === 'object' && 'detail' in payload
        ? (payload as { detail: unknown }).detail : null;
      const code = detail && typeof detail === 'object' && 'code' in detail &&
        typeof detail.code === 'string' ? detail.code : undefined;
      throw new ApiError(detailMessage(detail) ?? `请求失败（HTTP ${response.status}）`, response.status, code);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted) throw new ApiError('请求超时或已取消，执行结果需查询原请求。', 0);
    throw new ApiError('连接或响应数据异常，请查询原请求状态。', 0);
  } finally {
    globalThis.clearTimeout(timer);
    signal?.removeEventListener('abort', forwardAbort);
  }
}

export async function fetchAuthzMe(): Promise<{ role: AegisRole; capabilities: AegisCapability[] }> {
  return request('/authz/me');
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
  const payload = await request<TrustActionDetail>(
    `/trust/actions/${encodeURIComponent(actionId)}?user_id=demo-user`,
  );
  if (payload.action_id !== actionId || !payload.plan || !payload.state) {
    throw new ApiError('动作详情不完整，已停止恢复确认。', 0);
  }
  return payload;
}

export async function previewPlan(input: AgentRunInput): Promise<PlanPreviewResponse> {
  return request<PlanPreviewResponse>('/planner/plan', {
    method: 'POST',
    body: JSON.stringify({ user_id: 'demo-user', ...input }),
  });
}

export async function runAgent(
  input: AgentRunInput,
  options: { idempotencyKey?: string } = {},
): Promise<RunResponse> {
  return request<RunResponse>('/agent/run', {
    method: 'POST',
    idempotencyKey: options.idempotencyKey,
    body: JSON.stringify({ user_id: 'demo-user', ...input }),
  });
}

export async function resolveConfirmation(
  actionId: string,
  approved: boolean,
  reauthToken?: string,
  mfaProvider?: string | null,
  options: { idempotencyKey?: string } = {},
): Promise<RunResponse> {
  return request<RunResponse>(`/confirmations/${encodeURIComponent(actionId)}`, {
    method: 'POST',
    idempotencyKey: options.idempotencyKey,
    body: JSON.stringify({
      approved,
      reauth_token: reauthToken || null,
      mfa_provider: mfaProvider || null,
    }),
  });
}

export async function reconcileAction(
  actionId: string,
  outcome: 'reconciled' | 'rolled_back',
  reason = '',
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/trust/actions/${encodeURIComponent(actionId)}/reconcile`,
    {
      method: 'POST',
      body: JSON.stringify({ outcome, reason }),
    },
  );
}

export async function fetchAudit(limit = 100, runId?: string): Promise<AuditResponse> {
  return request<AuditResponse>(`/audit?limit=${encodeURIComponent(limit)}${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`);
}

export async function verifyAudit(): Promise<AuditVerification> {
  return request<AuditVerification>('/audit/verify');
}

/* ------------------------------------------------------------------ */
/* 阶段 2A：MFA / 步骤日志 / 熔断 / 沙箱 / IM                            */
/* ------------------------------------------------------------------ */

export async function fetchMfaProviders(): Promise<MfaProvidersResponse> {
  const payload = await request<Partial<MfaProvidersResponse>>('/mfa/providers');
  return {
    providers: payload.providers ?? [],
    enabled: payload.enabled ?? [],
    default: payload.default ?? 'otp',
    kinds: payload.kinds ?? [],
    simulated: payload.simulated,
    demo_only: payload.demo_only,
    note: payload.note,
  };
}

export async function fetchActionJournal(actionId: string): Promise<ActionJournal> {
  return request<ActionJournal>(`/actions/${encodeURIComponent(actionId)}/journal`);
}

export async function pauseAction(actionId: string, reason = '用户请求暂停'): Promise<unknown> {
  const params = new URLSearchParams({ reason, user_id: 'demo-user' });
  return request(`/actions/${encodeURIComponent(actionId)}/pause?${params.toString()}`, {
    method: 'POST',
  });
}

export async function resumeAction(actionId: string): Promise<unknown> {
  return request(
    `/actions/${encodeURIComponent(actionId)}/resume?user_id=demo-user`,
    { method: 'POST' },
  );
}

export async function rollbackAction(actionId: string, reason = '用户请求人工回退'): Promise<unknown> {
  const params = new URLSearchParams({ reason, user_id: 'demo-user' });
  return request(`/actions/${encodeURIComponent(actionId)}/rollback?${params.toString()}`, {
    method: 'POST',
  });
}

export async function fetchBreakerStatus(): Promise<BreakerStatus> {
  return request<BreakerStatus>('/trust/circuit-breaker');
}

export async function fetchBreakerPolicy(): Promise<BreakerPolicy> {
  return request<BreakerPolicy>('/trust/breaker/policy');
}

export async function fetchBreakerEvents(limit = 50): Promise<BreakerEventsResponse> {
  return request<BreakerEventsResponse>(
    `/trust/breaker/events?limit=${encodeURIComponent(limit)}`,
  );
}

export async function unlockBreaker(): Promise<BreakerStatus> {
  return request<BreakerStatus>('/trust/breaker/unlock', { method: 'POST' });
}

export async function fetchSandboxPolicy(): Promise<SandboxPolicyResponse> {
  const payload = await request<Partial<SandboxPolicyResponse>>('/sandbox/policy');
  const policy = payload.policy ?? {
    enabled: payload.enabled ?? false,
    timeout_seconds: payload.timeout_seconds ?? 0,
    max_output_bytes: payload.max_output_bytes ?? 0,
    max_argument_bytes: payload.max_argument_bytes ?? 0,
    block_network: payload.block_network ?? false,
    allowed_tools: payload.allowed_tools ?? [],
    tool_whitelist_enforced: payload.tool_whitelist_enforced ?? false,
  };
  return {
    ...policy,
    ...payload,
    policy,
    guards: payload.guards ?? [],
    demo_kinds: payload.demo_kinds ?? ['network', 'slow', 'oversize'],
    network_block_active: payload.network_block_active ?? false,
    executor: payload.executor ?? null,
  };
}

export async function runSandboxDemo(kind: SandboxDemoKind): Promise<SandboxDemoResult> {
  return request<SandboxDemoResult>('/sandbox/demo/run', {
    method: 'POST',
    body: JSON.stringify({ kind }),
  });
}

export async function fetchImHelp(): Promise<ImHelp> {
  return request<ImHelp>('/channels/im/help');
}

export async function sendImMessage(input: ImMessageInput): Promise<ImMessageReply> {
  const payload = await request<Partial<ImMessageReply>>('/channels/im/message', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return {
    channel: payload.channel ?? input.channel,
    sender_id: payload.sender_id ?? input.sender_id,
    message_id: payload.message_id ?? input.message_id ?? null,
    replayed: payload.replayed === true,
    text: payload.text ?? '',
    status: payload.status ?? 'unknown',
    structured: payload.structured ?? {},
    confirmation: payload.confirmation ?? null,
  };
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
    reason: payload.reason,
    now: payload.now ?? null,
    executed: payload.executed ?? [],
    failed: payload.failed ?? [],
    executed_count: payload.executed_count ?? payload.executed?.length ?? 0,
    failed_count: payload.failed_count ?? payload.failed?.length ?? 0,
    simulated: payload.simulated ?? true,
  };
}
