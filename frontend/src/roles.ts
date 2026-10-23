/**
 * Stage 2A demo roles.
 *
 * The matrix mirrors `backend/aegisbank_api/trust/authz.py`: it is only used to
 * decide what the console may offer, never to authorise an API call. The API is
 * still the single source of truth, and every request carries `X-Aegis-Role`.
 */

export type AegisRole = 'user' | 'operator' | 'auditor';

export type AegisCapability =
  | 'tool:execute'
  | 'permission:manage'
  | 'audit:read'
  | 'ops:manage'
  | 'trust:inspect';

export const AEGIS_ROLES: readonly AegisRole[] = ['user', 'operator', 'auditor'];

export const ROLE_LABELS: Record<AegisRole, string> = {
  user: '普通用户',
  operator: '运维操作员',
  auditor: '审计员',
};

export const ROLE_SHORT_LABELS: Record<AegisRole, string> = {
  user: 'USER',
  operator: 'OPERATOR',
  auditor: 'AUDITOR',
};

export const ROLE_DESCRIPTIONS: Record<AegisRole, string> = {
  user: '账户持有人：唯一可发起银行工具执行的角色，可管理本人工具授权。',
  operator: '运维操作员：可查看信任状态、处理熔断与紧急撤权，不能发起银行操作。',
  auditor: '审计员：只读查看审计哈希链、信任状态与步骤日志，不能执行任何写操作。',
};

export const CAPABILITY_LABELS: Record<AegisCapability, string> = {
  'tool:execute': '发起银行工具执行',
  'permission:manage': '管理工具授权（授予 / 撤回）',
  'audit:read': '查看操作审计与哈希链校验',
  'ops:manage': '运维操作（熔断解除 / 重置）',
  'trust:inspect': '查看信任状态与任务对账',
};

export const ROLE_CAPABILITIES: Record<AegisRole, readonly AegisCapability[]> = {
  user: ['audit:read', 'permission:manage', 'tool:execute', 'trust:inspect'],
  operator: ['audit:read', 'ops:manage', 'permission:manage', 'trust:inspect'],
  auditor: ['audit:read', 'trust:inspect'],
};

export const ROLE_STORAGE_KEY = 'aegisbank.role';

export function isAegisRole(value: unknown): value is AegisRole {
  return value === 'user' || value === 'operator' || value === 'auditor';
}

export function roleFromStorage(value: string | null | undefined): AegisRole {
  return isAegisRole(value) ? value : 'user';
}

export function roleCan(role: AegisRole, capability: AegisCapability): boolean {
  return ROLE_CAPABILITIES[role].includes(capability);
}

export function roleCapabilities(role: AegisRole): AegisCapability[] {
  return [...ROLE_CAPABILITIES[role]];
}

export function canExecuteTools(role: AegisRole): boolean {
  return roleCan(role, 'tool:execute');
}

export function canManagePermissions(role: AegisRole): boolean {
  return roleCan(role, 'permission:manage');
}

export function canUnlockBreaker(role: AegisRole): boolean {
  return role === 'operator' && roleCan(role, 'ops:manage');
}

export function canReadAudit(role: AegisRole): boolean {
  return roleCan(role, 'audit:read');
}

/** The auditor is the explicit read-only console role. */
export function isReadOnlyRole(role: AegisRole): boolean {
  return role === 'auditor';
}

/** Sandbox demos run tools through the executor, so they are not audit-only. */
export function canRunSandboxDemo(role: AegisRole): boolean {
  return role !== 'auditor';
}

/** The IM adapter always executes as the customer role. */
export function canSendImMessage(role: AegisRole): boolean {
  return role === 'user';
}

export function roleTaskBlockReason(role: AegisRole): string {
  if (role === 'operator') {
    return '当前角色为运维操作员（operator）：不具备 tool:execute，可查看信任状态与处理熔断，但银行工具执行仅限 user 角色。';
  }
  if (role === 'auditor') {
    return '当前角色为审计员（auditor）：只读审计视角，不能发起任务、确认执行或修改工具授权。';
  }
  return '';
}

export function roleActionBlockReason(role: AegisRole, action = '该写操作'): string {
  if (role === 'user') return '';
  return `当前角色 ${role} 不具备 tool:execute，${action}会被后端以 403 拒绝。`;
}

export function rolePermissionBlockReason(role: AegisRole): string {
  if (role === 'auditor') {
    return '审计员只有 audit:read / trust:inspect，权限开关已按只读视角禁用。';
  }
  return '';
}

export function roleTone(role: AegisRole): 'teal' | 'amber' | 'neutral' {
  if (role === 'operator') return 'amber';
  if (role === 'auditor') return 'teal';
  return 'neutral';
}