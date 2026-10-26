/**
 * Stage 2A demo roles.
 *
 * Capabilities come from /authz/me. Unknown or failed policy loads fail closed.
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

const capabilities = new Map<AegisRole, readonly AegisCapability[]>();

export function setRoleCapabilities(role: AegisRole, values: readonly AegisCapability[]): void {
  capabilities.set(role, [...values]);
}

export function resetRoleCapabilities(role: AegisRole): void {
  capabilities.delete(role);
}

export const ROLE_STORAGE_KEY = 'aegisbank.role';

export function isAegisRole(value: unknown): value is AegisRole {
  return value === 'user' || value === 'operator' || value === 'auditor';
}

export function roleFromStorage(value: string | null | undefined): AegisRole {
  return isAegisRole(value) ? value : 'user';
}

export function roleCan(role: AegisRole, capability: AegisCapability): boolean {
  return capabilities.get(role)?.includes(capability) ?? false;
}

export function roleCapabilities(role: AegisRole): AegisCapability[] {
  return [...(capabilities.get(role) ?? [])];
}

export function canExecuteTools(role: AegisRole): boolean {
  return roleCan(role, 'tool:execute');
}

export function canManagePermissions(role: AegisRole): boolean {
  return roleCan(role, 'permission:manage');
}

export function canUnlockBreaker(role: AegisRole): boolean {
  return roleCan(role, 'ops:manage');
}

export function canReadAudit(role: AegisRole): boolean {
  return roleCan(role, 'audit:read');
}

/** The auditor is the explicit read-only console role. */
export function isReadOnlyRole(role: AegisRole): boolean {
  return !['tool:execute', 'permission:manage', 'ops:manage'].some(
    (capability) => roleCan(role, capability as AegisCapability),
  );
}

/** Sandbox demos run tools through the executor, so they are not audit-only. */
export function canRunSandboxDemo(role: AegisRole): boolean {
  return roleCan(role, 'tool:execute') || roleCan(role, 'ops:manage');
}

/** The IM adapter always executes as the customer role. */
export function canSendImMessage(role: AegisRole): boolean {
  return roleCan(role, 'tool:execute');
}

export function roleTaskBlockReason(role: AegisRole): string {
  if (canExecuteTools(role)) return '';
  if (role === 'operator') {
    return '当前角色为运维操作员（operator）：不具备 tool:execute，可查看信任状态与处理熔断，但银行工具执行仅限 user 角色。';
  }
  if (role === 'auditor') {
    return '当前角色为审计员（auditor）：只读审计视角，不能发起任务、确认执行或修改工具授权。';
  }
  return '尚未取得后端 tool:execute 能力，任务提交已暂停。';
}

export function roleActionBlockReason(role: AegisRole, action = '该写操作'): string {
  if (canExecuteTools(role)) return '';
  return `当前角色 ${role} 不具备 tool:execute，${action}会被后端以 403 拒绝。`;
}

export function rolePermissionBlockReason(role: AegisRole): string {
  if (!canManagePermissions(role)) {
    return '后端未授予 permission:manage，权限开关已禁用。';
  }
  return '';
}

export function roleTone(role: AegisRole): 'teal' | 'amber' | 'neutral' {
  if (role === 'operator') return 'amber';
  if (role === 'auditor') return 'teal';
  return 'neutral';
}
