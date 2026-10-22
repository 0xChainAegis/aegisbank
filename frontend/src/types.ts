export type RiskLevel = 'green' | 'yellow' | 'red';

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
}

export interface Confirmation {
  id: string;
  requires_reauth: boolean;
  expires_at: string;
}

export interface RiskAssessment {
  level: RiskLevel;
  score: number;
  reasons: string[];
  base_risk: RiskLevel;
  requires_reauth: boolean;
}

export interface AccountInfo {
  account_id: string;
  name: string;
  kind: string;
  currency: string;
  balance_cny: number;
  available_cny: number;
}

export interface CardInfo {
  card_id: string;
  account_id: string;
  masked_number: string;
  status: string;
  credit_limit_cny: number;
  available_limit_cny: number;
  repayment_day: number;
  transaction_limit_cny: number;
}

export interface SubscriptionInfo {
  subscription_id: string;
  merchant: string;
  amount_cny: number;
  cycle: string;
  next_charge_date: string;
  status: string;
  risk_flag?: string | null;
}

export interface BankingOverview {
  accounts: AccountInfo[];
  cards: CardInfo[];
  subscriptions: SubscriptionInfo[];
  monthly_spend_cny: number;
  daily_transfer_total_cny: number;
  suspicious_subscription_id: string | null;
  suspicious_reason: string | null;
}

export interface PlanStep {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  depends_on: string[];
  description?: string | null;
  title?: string;
  risk_level?: RiskLevel;
  risk_reasons?: string[];
  risk_score?: number;
  requires_reauth?: boolean;
  permission?: string;
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
}

export interface RunResponse {
  status:
    | 'completed'
    | 'awaiting_confirmation'
    | 'needs_clarification'
    | 'blocked'
    | 'rejected'
    | 'failed';
  run_id: string;
  risk_level: RiskLevel;
  reason: string;
  risk?: RiskAssessment;
  plan?: ExecutionPlan;
  confirmation?: Confirmation;
  results?: ToolResult[];
  audit_id?: number;
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
  prev_hash: string;
  entry_hash: string;
}

export interface AuditResponse {
  entries: AuditEntry[];
  count: number;
}
