/** Pure display helpers for the stage-2A capabilities (no API calls here). */
import type {
  ActionJournalEntry,
  BreakerStatus,
  MfaProvider,
  PlanStep,
  RiskLevel,
  SandboxDemoResult,
  ToolMetadata,
} from './types';

export type BadgeTone = 'good' | 'warn' | 'bad' | 'neutral';

export interface CompensationBadgeInfo {
  label: string;
  tone: BadgeTone;
  title: string;
}

/* ------------------------------------------------------------------ */
/* 步骤日志 / 暂停 / 回滚 / 补偿                                        */
/* ------------------------------------------------------------------ */

export const COMPENSATION_STATUS_LABELS: Record<string, string> = {
  paused: '已暂停（可恢复）',
  pending: '等待人工确认（尚未执行）',
  executing: '执行中',
  rolled_back: '已回滚（补偿完成）',
  unknown: '结果未知（需人工对账）',
  rollback_blocked: '回滚被阻止（存在不可撤销步骤）',
  completed: '执行完成',
  failed: '执行失败',
  reconciled: '已人工对账',
};

export const COMPENSATION_STATUS_DESCRIPTIONS: Record<string, string> = {
  paused: '暂停在步骤之间生效；已执行步骤不会重复执行，可调用 resume 继续剩余节点。',
  pending: '动作尚未开始执行，步骤日志为空；确认通过后才会产生执行记录。',
  executing: '动作正在执行中；已执行步骤会实时写入步骤日志。',
  rolled_back: '系统已按相反顺序补偿已执行步骤，补偿工具同样经过权限网关与审计链。',
  unknown: '结果不确定不等于失败：副作用可能已经发生。不得自动重试，需人工对账或回滚。',
  rollback_blocked: '已执行步骤中存在不可撤销操作，自动回滚被阻止；需要人工与银行核实后对账。',
  completed: '全部步骤已执行完成，无待补偿步骤。',
  failed: '执行失败且没有可补偿的已执行步骤，失败原因已写入审计链。',
  reconciled: '人工已给出对账结论，结论写入审计哈希链。',
};

export function compensationStatusLabel(status: string): string {
  return COMPENSATION_STATUS_LABELS[status] ?? status;
}

export function compensationStatusDescription(status: string): string {
  return COMPENSATION_STATUS_DESCRIPTIONS[status] ?? '';
}

export const JOURNAL_PHASE_LABELS: Record<string, string> = {
  executed: '已执行',
  compensated: '已补偿',
  compensation_failed: '补偿失败',
  rollback_blocked: '回滚被阻止',
  paused: '已暂停',
};

export function journalPhaseLabel(phase: string): string {
  return JOURNAL_PHASE_LABELS[phase] ?? phase;
}

export function journalPhaseTone(phase: string): BadgeTone {
  if (phase === 'compensated') return 'good';
  if (phase === 'compensation_failed' || phase === 'rollback_blocked') return 'bad';
  if (phase === 'paused') return 'warn';
  return 'neutral';
}

export interface JournalSummary {
  executed: number;
  compensated: number;
  compensationFailed: number;
  rollbackBlocked: number;
  paused: number;
  headline: string;
}

export function summarizeJournal(entries: ActionJournalEntry[]): JournalSummary {
  const counts = { executed: 0, compensated: 0, compensationFailed: 0, rollbackBlocked: 0, paused: 0 };
  for (const entry of entries) {
    if (entry.phase === 'executed') counts.executed += 1;
    else if (entry.phase === 'compensated') counts.compensated += 1;
    else if (entry.phase === 'compensation_failed') counts.compensationFailed += 1;
    else if (entry.phase === 'rollback_blocked') counts.rollbackBlocked += 1;
    else if (entry.phase === 'paused') counts.paused += 1;
  }
  let headline = '尚无步骤执行记录';
  if (counts.compensationFailed > 0) {
    headline = `补偿失败 ${counts.compensationFailed} 步，需人工对账`;
  } else if (counts.rollbackBlocked > 0) {
    headline = `回滚被阻止：存在 ${counts.rollbackBlocked} 个不可撤销步骤`;
  } else if (counts.compensated > 0) {
    headline = `已按逆序补偿 ${counts.compensated} 个已执行步骤`;
  } else if (counts.paused > 0) {
    headline = `已暂停：剩余步骤未执行，可恢复`;
  } else if (counts.executed > 0) {
    headline = `已执行 ${counts.executed} 个步骤，尚无补偿记录`;
  }
  return { ...counts, headline };
}

export function compensationBadge(
  compensable: boolean | undefined,
  riskLevel: RiskLevel,
  compensationTool?: string | null,
): CompensationBadgeInfo {
  if (compensable) {
    return {
      label: '可撤销',
      tone: 'good',
      title: compensationTool ? `补偿工具：${compensationTool}` : '工具已登记补偿规格。',
    };
  }
  if (riskLevel === 'green') {
    return {
      label: '只读 · 无需补偿',
      tone: 'neutral',
      title: '只读工具没有资金或设置副作用，不需要补偿。',
    };
  }
  return {
    label: '不可撤销',
    tone: 'warn',
    title: '工具未登记补偿工具：失败或回滚时需要人工处理。',
  };
}

export function planStepCompensation(
  step: PlanStep,
  tools: ToolMetadata[],
): CompensationBadgeInfo {
  if (step.irreversible) {
    return {
      label: '不可撤销',
      tone: 'bad',
      title: step.irreversible_reason || '计划已标注该步骤为不可撤销。',
    };
  }
  const tool = tools.find((item) => item.name === step.tool_name);
  if (!tool) {
    return {
      label: '可撤销性未知',
      tone: 'neutral',
      title: `工具 ${step.tool_name} 不在当前权限列表中，无法判断可撤销性。`,
    };
  }
  return compensationBadge(tool.compensable === true, tool.risk_level, tool.compensation_tool);
}

const JOURNAL_ELIGIBLE_STATUSES = new Set([
  'awaiting_confirmation',
  'completed',
  'failed',
  'unknown',
  'reconciled',
  'rolled_back',
  'paused',
]);

export function journalEligibleStatus(status: string): boolean {
  return JOURNAL_ELIGIBLE_STATUSES.has(status);
}

/* ------------------------------------------------------------------ */
/* MFA                                                                  */
/* ------------------------------------------------------------------ */

export const MFA_DEMO_TOKENS: Record<string, string> = {
  otp: '246810',
  biometric: 'FACE-888888',
};

const MFA_FALLBACK_LABELS: Record<string, string> = {
  otp: '演示动态验证码',
  biometric: '模拟人脸 / 设备确认',
};

const MFA_FALLBACK_HINTS: Record<string, string> = {
  otp: '演示环境固定验证码 246810；生产环境必须接入银行真实 MFA。',
  biometric: '模拟人脸/设备确认，演示 token 为 FACE-888888，不涉及真实生物识别。',
};

export function defaultMfaProvider(providers: MfaProvider[], fallback = 'otp'): string {
  const enabled = providers.filter((provider) => provider.enabled !== false);
  const preferred = enabled.find((provider) => provider.default)?.name;
  if (preferred) return preferred;
  if (enabled.some((provider) => provider.name === fallback)) return fallback;
  return enabled[0]?.name ?? fallback;
}

export function mfaProviderLabel(name: string, providers: MfaProvider[] = []): string {
  const provider = providers.find((item) => item.name === name);
  return provider?.title || MFA_FALLBACK_LABELS[name] || name;
}

export function mfaProviderHint(name: string, providers: MfaProvider[] = []): string {
  const provider = providers.find((item) => item.name === name);
  return provider?.hint || MFA_FALLBACK_HINTS[name] || '演示验证方式，仅用于本地开发。';
}

export function mfaTokenPlaceholder(provider: string): string {
  if (provider === 'biometric') return '输入 FACE-XXXXXX';
  if (provider === 'otp') return '输入 6 位验证码';
  return '输入演示验证 token';
}

export function sanitizeMfaToken(provider: string, raw: string): string {
  if (provider === 'otp') return raw.replace(/\D/g, '').slice(0, 6);
  if (provider === 'biometric') {
    return raw.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 12);
  }
  return raw.trim().slice(0, 32);
}

export function isMfaTokenComplete(provider: string, token: string): boolean {
  if (provider === 'otp') return /^\d{6}$/.test(token);
  if (provider === 'biometric') return /^FACE-[A-Z0-9]{6}$/.test(token);
  return token.trim().length > 0;
}

export function describeMfaFailure(message: string, provider: string): string {
  const label = mfaProviderLabel(provider);
  return `验证方式「${label}」未通过：${message}`;
}

/* ------------------------------------------------------------------ */
/* 沙箱                                                                 */
/* ------------------------------------------------------------------ */

export const SANDBOX_KIND_LABELS: Record<string, string> = {
  network: '网络访问',
  slow: '慢工具超时',
  oversize: '超大输出',
};

export const SANDBOX_EVENT_LABELS: Record<string, string> = {
  sandbox_blocked: '沙箱拦截',
  sandbox_timeout: '沙箱超时',
};

export const SANDBOX_VIOLATION_LABELS: Record<string, string> = {
  network: '网络访问被阻断',
  timeout: '执行超时',
  output_too_large: '输出超过上限',
  arguments_too_large: '入参超过上限',
  tool_whitelist: '工具不在白名单',
  error: '演示异常',
};

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value < 1024) return `${Math.trunc(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function sandboxKindLabel(kind: string): string {
  return SANDBOX_KIND_LABELS[kind] ?? kind;
}

export function sandboxEventLabel(event: string | null | undefined): string {
  if (!event) return '无事件';
  return SANDBOX_EVENT_LABELS[event] ?? event;
}

export function sandboxViolationLabel(violation: string | null | undefined): string {
  if (!violation) return '无越界类型';
  return SANDBOX_VIOLATION_LABELS[violation] ?? violation;
}

export function sandboxDemoSummary(result: SandboxDemoResult): string {
  const kind = sandboxKindLabel(result.kind);
  if (result.blocked) {
    return `${kind}：已被沙箱拦截（${sandboxEventLabel(result.event)}，${sandboxViolationLabel(result.violation)}）——${result.reason}`;
  }
  return `${kind}：本次未被沙箱拦截——${result.reason}`;
}

/* ------------------------------------------------------------------ */
/* 熔断                                                                 */
/* ------------------------------------------------------------------ */

export const BREAKER_TRIGGER_LABELS: Record<string, string> = {
  consecutive_failures: '连续失败',
  suspicious_red: '短时多次红色操作',
  suspicious_injection: '注入命中累计',
};

export const BREAKER_EVENT_LABELS: Record<string, string> = {
  circuit_open: '熔断打开',
  reset: '熔断重置',
  lock_expired: '冷却到期',
  consecutive_failure: '连续失败计数',
  red_operation: '红色操作计数',
  red_cleared: '红色计数清零',
  injection_hit: '注入命中计数',
  circuit_breaker_unlock: '运维解除熔断',
};

export function breakerEventLabel(kind: string): string {
  return BREAKER_EVENT_LABELS[kind] ?? kind;
}

export function breakerStateLabel(status: BreakerStatus | null | undefined): string {
  if (!status) return '状态未知';
  return status.open ? '熔断打开 · fail-closed' : '熔断关闭';
}

export function breakerTriggerLabel(status: BreakerStatus | null | undefined): string {
  if (!status?.trigger) return '—';
  return status.trigger_label || BREAKER_TRIGGER_LABELS[status.trigger] || status.trigger;
}

export function breakerReason(
  status: BreakerStatus | null | undefined,
  error = '',
): string {
  if (error) return error;
  if (status?.reason) return status.reason;
  if (status?.open) {
    return '执行熔断已触发：写操作按 fail-closed 拒绝，请等待冷却或由 operator 解除。';
  }
  return '熔断器关闭：最近没有触发写操作锁定。';
}

export function breakerTone(status: BreakerStatus | null | undefined, error = ''): BadgeTone {
  if (error) return 'bad';
  if (!status) return 'neutral';
  if (status.open) return 'bad';
  if ((status.suspicious?.red_events ?? 0) > 0 || (status.suspicious?.injection_events ?? 0) > 0) {
    return 'warn';
  }
  return 'good';
}

/* ------------------------------------------------------------------ */
/* 2A 审计事件                                                          */
/* ------------------------------------------------------------------ */

export const TWO_A_EVENT_CODES: readonly string[] = [
  'compensation_executed',
  'compensation_failed',
  'compensation_blocked',
  'rollback_blocked',
  'mfa_failed',
  'mfa_challenge_issued',
  'sandbox_blocked',
  'sandbox_timeout',
  'action_paused',
  'circuit_breaker_open',
  'circuit_breaker_reset',
  'circuit_breaker_unlock',
  'im_message_executed',
  'im_message_rejected',
  'role_revocation',
];

export const TWO_A_EVENT_DESCRIPTIONS: Record<string, string> = {
  compensation_executed: '失败或人工回退时，系统按相反顺序调用补偿工具撤销已执行步骤，补偿同样经过权限网关。',
  compensation_failed: '补偿工具执行失败：系统不会自动重试，任务转入 UNKNOWN，需要人工对账。',
  compensation_blocked: '已执行步骤中存在不可撤销操作，自动补偿被阻止；需人工与银行核实后处理。',
  rollback_blocked: '人工回滚被不可撤销步骤阻止，回滚结论写入审计链。',
  mfa_failed: '红色操作的 MFA 验证失败（OTP 或模拟生物识别），未执行任何工具。',
  mfa_challenge_issued: '签发了演示 MFA 挑战提示，不返回真实凭据。',
  sandbox_blocked: '工具调用越过沙箱策略（网络、入参或输出上限），结果被拒绝并写入审计链。',
  sandbox_timeout: '工具执行超过沙箱超时上限，已中止并写入审计链。',
  action_paused: '用户在步骤之间暂停执行；剩余节点保留，可恢复或回滚。',
  circuit_breaker_open: '熔断器打开：后续写操作统一 fail-closed 拒绝。',
  circuit_breaker_reset: '熔断器被重置，连续失败与可疑行为计数清零。',
  circuit_breaker_unlock: 'operator 解除熔断，操作写入审计链。',
  im_message_executed: 'IM 渠道消息复用 Planner / 网关 / 确认 / 审计链路并产生回执。',
  im_message_rejected: 'IM 渠道消息被拒绝或确认失败，原因写入审计链。',
  role_revocation: '角色撤权：工具授权立即失效，后续计划在进入调度器前被网关拦截。',
};

export function isTwoAEvent(event: string): boolean {
  return TWO_A_EVENT_CODES.includes(event);
}

export function eventDescription(event: string): string {
  return TWO_A_EVENT_DESCRIPTIONS[event] ?? '';
}