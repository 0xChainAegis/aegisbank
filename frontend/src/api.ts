import type {
  AgentRunInput,
  AuditResponse,
  AuditVerification,
  BankingOverview,
  ExecutionPlan,
  RunResponse,
  ToolMetadata,
} from './types';
import { normalizeBankingOverview } from './viewModel';

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
