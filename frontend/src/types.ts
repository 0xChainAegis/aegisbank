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

export interface PlanStep {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  depends_on: string[];
  description?: string | null;
  title?: string;
  risk_level?: RiskLevel;
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
