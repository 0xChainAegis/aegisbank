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
  | 'failed';

export interface RunResponse {
  status: RunStatus;
  run_id: string;
  risk_level?: RiskLevel;
  risk?: RiskAssessment | null;
  risk_reasons?: string[];
  reason: string;
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
