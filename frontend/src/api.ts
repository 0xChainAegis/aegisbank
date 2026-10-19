import type { AuditResponse, RunResponse, ToolMetadata } from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof payload === 'object' && payload && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `请求失败（HTTP ${response.status}）`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function fetchTools(userId = 'demo-user'): Promise<ToolMetadata[]> {
  const payload = await request<{ tools: ToolMetadata[] }>(
    `/tools?user_id=${encodeURIComponent(userId)}`,
  );
  return payload.tools;
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

export async function runAgent(input: {
  instruction: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  user_id?: string;
}): Promise<RunResponse> {
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

export async function fetchAudit(limit = 50): Promise<AuditResponse> {
  return request<AuditResponse>(`/audit?limit=${limit}`);
}

export async function verifyAudit(): Promise<{ valid: boolean; checked: number }> {
  return request('/audit/verify');
}
