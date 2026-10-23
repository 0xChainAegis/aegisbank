export type RiskLevel = 'green' | 'yellow' | 'red';

export interface RiskAssessment {
  level?: RiskLevel;
  risk_level?: RiskLevel;
  reasons?: string[];
  reason?: string;
  matched_rules?: string[];
  risk_reasons?: string[];
  score?: number;
}

export interface ToolMetadata {
  name: string;
  title: string;
  description: string;
  risk_level: RiskLevel;
  permission: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  granted: boolean;
}

export interface ToolResult {
  tool_name: string;
  message: string;
  data: Record<string, unknown>;
  risk?: RiskAssessment | null;
  risk_level?: RiskLevel;
  risk_reasons?: string[];
}

export interface Confirmation {
  id: string;
  requires_reauth: boolean;
  expires_at: string;
  state?: string;
  envelopes?: ActionEnvelopeView[];
}

export interface PlanStep {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  depends_on: string[];
  description?: string | null;
  title?: string;
  risk_level?: RiskLevel;
  permission?: string;
  risk_reasons?: string[];
}

export interface ExecutionPlan {
  intent: string;
  planner: string;
  confidence: number;
  assumptions: string[];
  plan_hash?: string;
  dag_path?: string;
  steps: PlanStep[];
  needs_clarification?: boolean;
  clarification?: string | null;
  risk_level?: RiskLevel;
  risk_reasons?: string[];
}

export type RunStatus =
  | 'completed'
  | 'awaiting_confirmation'
  | 'needs_clarification'
  | 'blocked'
  | 'rejected'
  | 'failed'
  | 'unknown'
  | 'reconciled'
  | 'rolled_back';

/** Layered evidence returned by the trust layer. */
export interface EvidenceItem {
  source: string;
  verified: boolean;
  verification_kind?: string;
  detail?: string;
}

export interface RunResponse {
  status: RunStatus | string;
  run_id: string;
  risk_level?: RiskLevel;
  risk?: RiskAssessment | null;
  risk_reasons?: string[];
  reason: string;
  plan?: ExecutionPlan;
  confirmation?: Confirmation;
  results?: ToolResult[];
  audit_id?: number;
  evidence?: EvidenceItem[];
  evidence_list?: EvidenceItem[];
}

export interface ActionEnvelopeView {
  schema_version?: string;
  user_id?: string;
  plan_hash?: string;
  step_id?: string;
  tool_name?: string;
  arguments_hash?: string;
  risk_level?: RiskLevel;
  risk_reasons?: string[];
  permission?: string;
  nonce?: string;
  issued_at?: string;
  expires_at?: string;
  confirmation_state?: string;
  approval_token?: string | null;
  approval_token_present?: boolean;
}

export interface TrustActionTransition {
  from: string;
  to: string;
  reason?: string;
}

export interface TrustActionDetail {
  action_id: string;
  user_id: string;
  status: string;
  state: string;
  risk_level: RiskLevel;
  requires_reauth: boolean;
  created_at: string;
  expires_at: string;
  resolved_at?: string | null;
  history: TrustActionTransition[];
  envelopes: ActionEnvelopeView[];
  evidence?: EvidenceItem[];
  evidence_list?: EvidenceItem[];
}

export interface ReadinessComponent {
  ok: boolean;
  detail?: string;
}

export type ReadinessStatus = 'ready' | 'degraded' | 'not_ready';

export interface ReadinessSnapshot {
  status: ReadinessStatus;
  components: Record<string, ReadinessComponent>;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  event: string;
  user_id: string;
  instruction: string;
  dag_path: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  confirmation_state: string;
  risk_level: RiskLevel;
  evidence?: EvidenceItem[];
  prev_hash: string;
  entry_hash: string;
}

export interface AuditResponse {
  entries: AuditEntry[];
  count: number;
}

export interface AuditVerification {
  valid: boolean;
  checked: number;
}

export interface AgentRunInput {
  instruction: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  user_id?: string;
}

export interface BankingAccount {
  id: string;
  name: string;
  type: string;
  balanceCny: number;
  availableCny: number | null;
  currency: string;
  maskedNumber: string;
}

export interface BankingCard {
  id: string;
  accountId: string;
  name: string;
  maskedNumber: string;
  status: string;
  creditLimitCny: number | null;
  availableLimitCny: number | null;
  repaymentDay: number | null;
}

export interface Subscription {
  id: string;
  merchant: string;
  amountCny: number;
  cycle: string;
  nextBillingDate: string;
  status: string;
  abnormal: boolean;
  reason: string;
}

export interface BankingOverview {
  accounts: BankingAccount[];
  cards: BankingCard[];
  subscriptions: Subscription[];
  abnormalSubscriptions: Subscription[];
  monthSpendingCny: number;
  todayTransferTotalCny: number;
  asOf: string;
}

/* ------------------------------------------------------------------ */
/* 财富管理（模拟数据）                                                  */
/* ------------------------------------------------------------------ */

export interface WealthProduct {
  product_id: string;
  name: string;
  kind: string;
  risk_level: string;
  min_amount_cny: number;
  expected_annual_rate: number;
  term_days: number;
  status: string;
}

export interface WealthHolding {
  holding_id: string;
  product_id: string;
  product_name: string;
  kind: string;
  risk_level: string;
  shares: number;
  principal_cny: number;
  market_value_cny: number;
  opened_at: string;
  status: string;
}

export interface WealthOrder {
  order_id: string;
  product_id: string;
  product_name: string;
  side: string;
  amount_cny: number;
  shares: number;
  status: string;
  created_at: string;
}

export interface WealthProductsResponse {
  products: WealthProduct[];
  count: number;
  simulated?: boolean;
  disclaimer?: string;
}

export interface WealthHoldingsResponse {
  holdings: WealthHolding[];
  count: number;
  total_market_value_cny: number;
  total_principal_cny: number;
  simulated?: boolean;
  disclaimer?: string;
}

export interface WealthOrdersResponse {
  orders: WealthOrder[];
  count: number;
  simulated?: boolean;
  disclaimer?: string;
}

/* ------------------------------------------------------------------ */
/* 联系人                                                               */
/* ------------------------------------------------------------------ */

export interface Contact {
  contact_id: string;
  name: string;
  alias: string | null;
  phone: string | null;
  account_id: string;
  birthday: string | null;
  relation: string | null;
  status: string;
}

export interface ContactsResponse {
  contacts: Contact[];
  count: number;
  simulated?: boolean;
}

/* ------------------------------------------------------------------ */
/* 账单与订阅                                                           */
/* ------------------------------------------------------------------ */

export interface BillTopMerchant {
  merchant: string;
  category: string;
  amount_cny: number;
  count: number;
}

export interface BillComparison {
  baseline: string;
  previous_total_cny: number;
  change_cny: number;
  change_pct: number | null;
  direction: string;
  comparable: boolean;
}

export interface BudgetUsage {
  category: string;
  budget_cny: number;
  spent_cny: number;
  usage_pct: number | null;
  over_budget: boolean;
}

export interface BillReport {
  account_id: string;
  period: string;
  label: string;
  month: string | null;
  year: number;
  total_spend_cny: number;
  categories: Record<string, number>;
  top_merchants: BillTopMerchant[];
  transaction_count: number;
  all_transaction_count: number;
  comparison: BillComparison;
  budget_usage: BudgetUsage[];
  conclusion: string;
  simulated?: boolean;
}

export interface BillAnomaly {
  kind: string;
  severity: string;
  message: string;
  evidence: Record<string, unknown>;
}

export interface BillAnomalyRule {
  kind: string;
  description: string;
  severity: string;
}

export interface BillAnomalies {
  account_id: string;
  period: string;
  month: string;
  anomalies: BillAnomaly[];
  counts_by_kind: Record<string, number>;
  total: number;
  high_severity_count: number;
  rules: BillAnomalyRule[];
  conclusion: string;
  simulated?: boolean;
}

export interface SubscriptionCharge {
  merchant: string;
  charge_count: number;
  total_spend_cny: number;
  average_amount_cny: number;
  latest_charge_date: string;
  latest_charge_cny: number;
  latest_transaction_id: string;
  registered: boolean;
  unregistered_debit: boolean;
  subscription_id: string | null;
  cycle: string | null;
  status: string | null;
  risk_flag: string | null;
  advice: string;
}

export interface SubscriptionCharges {
  account_id: string | null;
  subscriptions: SubscriptionCharge[];
  total: number;
  registered_count: number;
  unregistered_count: number;
  window: string;
  conclusion: string;
  simulated?: boolean;
}

export interface RenewalReminder {
  subscription_id: string;
  merchant: string;
  amount_cny: number;
  cycle: string;
  next_charge_date: string;
  days_left: number;
  overdue: boolean;
  risk_flag: string | null;
  advice: string;
}

export interface RenewalReminders {
  reminders: RenewalReminder[];
  count: number;
  cycle: string;
  days_ahead: number;
  as_of: string;
  channel: string;
  note: string;
  simulated?: boolean;
}

/* ------------------------------------------------------------------ */
/* 卡片申请                                                             */
/* ------------------------------------------------------------------ */

export interface CardApplication {
  application_id: string;
  kind: string;
  status: string;
  requested_limit_cny: number;
  card_id: string | null;
  masked_number: string | null;
  created_at: string;
  updated_at: string;
}

export interface CardApplicationsResponse {
  applications: CardApplication[];
  count: number;
  simulated?: boolean;
}

/* ------------------------------------------------------------------ */
/* 自动化（定时任务 / 预算目标 / 礼物订单）                              */
/* ------------------------------------------------------------------ */

export interface AutomationTask {
  task_id: string;
  kind: string;
  status: string;
  run_at: string;
  recurrence: string;
  created_at: string;
  last_run_at: string | null;
  last_result: Record<string, unknown> | null;
  payload: Record<string, unknown>;
  amount_cny?: number | null;
  label?: string | null;
  simulated?: boolean;
}

export interface AutomationSchedules {
  tasks: AutomationTask[];
  count: number;
  simulated?: boolean;
}

export interface BudgetGoal {
  goal_id: string;
  name: string;
  target_cny: number;
  locked_cny: number;
  status: string;
  deadline: string | null;
  created_at: string;
  simulated?: boolean;
}

export interface AutomationGoals {
  goals: BudgetGoal[];
  count: number;
  simulated?: boolean;
}

export interface GiftOrder {
  order_id: string;
  goal_id: string | null;
  gift_kind: string;
  amount_cny: number;
  due_at: string;
  status: string;
  simulated?: boolean;
}

export interface AutomationOrders {
  orders: GiftOrder[];
  count: number;
  simulated?: boolean;
}

export interface AutomationRunDueItem {
  task_id?: string;
  kind?: string;
  status?: string;
  reason?: string;
  amount_cny?: number | null;
  [key: string]: unknown;
}

export interface AutomationRunDueResult {
  status: string;
  risk_level?: RiskLevel;
  now?: string | null;
  executed: AutomationRunDueItem[];
  failed: AutomationRunDueItem[];
  executed_count: number;
  failed_count: number;
  simulated?: boolean;
}
