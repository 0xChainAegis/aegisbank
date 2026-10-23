import { describe, expect, it } from 'vitest';
import {
  canExecuteTools,
  canRunSandboxDemo,
  canSendImMessage,
  canUnlockBreaker,
  roleCan,
  roleFromStorage,
  roleTaskBlockReason,
} from './roles';
import {
  breakerEventLabel,
  breakerReason,
  breakerStateLabel,
  breakerTriggerLabel,
  compensationBadge,
  compensationStatusDescription,
  compensationStatusLabel,
  defaultMfaProvider,
  describeMfaFailure,
  eventDescription,
  formatBytes,
  isMfaTokenComplete,
  isTwoAEvent,
  journalEligibleStatus,
  mfaProviderLabel,
  planStepCompensation,
  sandboxDemoSummary,
  sandboxEventLabel,
  sandboxViolationLabel,
  sanitizeMfaToken,
  summarizeJournal,
} from './twoA';
import type {
  ActionJournalEntry,
  BreakerStatus,
  MfaProvider,
  PlanStep,
} from './types';

const providers: MfaProvider[] = [
  { name: 'biometric', kind: 'biometric', title: '模拟人脸 / 设备确认', enabled: true },
  { name: 'otp', kind: 'otp', title: '演示动态验证码', enabled: true, default: true },
];

function journalEntry(phase: string, id: number): ActionJournalEntry {
  return {
    id,
    action_id: 'dag_test',
    node_id: `step-${id}`,
    tool_name: 'demo_tool',
    phase,
    status: phase === 'compensated' ? 'succeeded' : phase,
    risk_level: 'green',
    created_at: '2026-10-23T05:00:00+00:00',
    arguments: {},
    result: {},
  };
}

function breaker(overrides: Partial<BreakerStatus> = {}): BreakerStatus {
  return {
    name: 'tool_execution',
    open: true,
    trigger: 'suspicious_red',
    trigger_label: '短时多次红色操作',
    failures: 0,
    threshold: 3,
    window_seconds: 60,
    lock_seconds: 60,
    opened_at: '2026-10-23T05:00:00+00:00',
    retry_after_seconds: 42,
    reason: '执行熔断已触发：短时多次红色操作。',
    suspicious: {
      red_events: 3,
      red_threshold: 3,
      injection_events: 0,
      injection_threshold: 3,
      window_seconds: 300,
    },
    ...overrides,
  };
}

describe('stage 2A role capability helpers', () => {
  it('mirrors the backend role matrix and explains blocked tasks', () => {
    expect(roleCan('user', 'tool:execute')).toBe(true);
    expect(roleCan('operator', 'tool:execute')).toBe(false);
    expect(roleCan('auditor', 'audit:read')).toBe(true);
    expect(canExecuteTools('user')).toBe(true);
    expect(canExecuteTools('auditor')).toBe(false);
    expect(canUnlockBreaker('operator')).toBe(true);
    expect(canUnlockBreaker('user')).toBe(false);
    expect(canRunSandboxDemo('auditor')).toBe(false);
    expect(canSendImMessage('user')).toBe(true);
    expect(canSendImMessage('operator')).toBe(false);
    expect(roleTaskBlockReason('auditor')).toContain('只读');
    expect(roleTaskBlockReason('operator')).toContain('tool:execute');
    expect(roleFromStorage('nope')).toBe('user');
    expect(roleFromStorage('operator')).toBe('operator');
  });
});

describe('stage 2A MFA helpers', () => {
  it('selects default providers, sanitizes tokens and explains failures', () => {
    expect(defaultMfaProvider(providers)).toBe('otp');
    expect(defaultMfaProvider([], 'otp')).toBe('otp');
    expect(mfaProviderLabel('biometric', providers)).toContain('人脸');
    expect(sanitizeMfaToken('biometric', 'face-888888')).toBe('FACE-888888');
    expect(sanitizeMfaToken('otp', '12a34b567')).toBe('123456');
    expect(isMfaTokenComplete('otp', '246810')).toBe(true);
    expect(isMfaTokenComplete('otp', '24681')).toBe(false);
    expect(isMfaTokenComplete('biometric', 'FACE-888888')).toBe(true);
    expect(describeMfaFailure('二次身份校验失败：token 不匹配', 'biometric')).toContain(
      '模拟人脸 / 设备确认',
    );
  });
});

describe('stage 2A compensation helpers', () => {
  it('maps paused / rolled_back / unknown to readable recovery copy', () => {
    expect(compensationStatusLabel('paused')).toContain('已暂停');
    expect(compensationStatusLabel('rolled_back')).toContain('补偿完成');
    expect(compensationStatusLabel('unknown')).toContain('对账');
    expect(compensationStatusDescription('rollback_blocked')).toContain('不可撤销');
  });

  it('summarizes journal entries and picks the most important headline', () => {
    const entries = [
      journalEntry('executed', 1),
      journalEntry('executed', 2),
      journalEntry('compensated', 3),
      journalEntry('compensation_failed', 4),
    ];
    const summary = summarizeJournal(entries);
    expect(summary.executed).toBe(2);
    expect(summary.compensated).toBe(1);
    expect(summary.compensationFailed).toBe(1);
    expect(summary.headline).toContain('补偿失败 1 步');
    expect(summarizeJournal([journalEntry('paused', 5)]).headline).toContain('已暂停');
    expect(summarizeJournal([]).headline).toContain('尚无步骤');
  });

  it('renders 可撤销 / 不可撤销 badges for tools and annotated plan steps', () => {
    expect(compensationBadge(true, 'yellow', 'reverse_transfer').label).toBe('可撤销');
    expect(compensationBadge(false, 'red').label).toBe('不可撤销');
    expect(compensationBadge(false, 'green').label).toContain('只读');
    expect(compensationBadge(true, 'yellow', 'reverse_transfer').title).toContain(
      'reverse_transfer',
    );

    const irreversibleStep: PlanStep = {
      id: 'step-3',
      tool_name: 'demo_irreversible_marker',
      arguments: {},
      depends_on: [],
      irreversible: true,
      irreversible_reason: '该步骤声明为不可撤销',
    };
    expect(planStepCompensation(irreversibleStep, []).label).toBe('不可撤销');
    expect(planStepCompensation(irreversibleStep, []).tone).toBe('bad');

    const unknownStep: PlanStep = {
      id: 'step-4',
      tool_name: 'not_in_registry',
      arguments: {},
      depends_on: [],
    };
    expect(planStepCompensation(unknownStep, []).label).toContain('未知');
  });
});

describe('stage 2A sandbox and breaker helpers', () => {
  it('formats sandbox events, violations and demo summaries', () => {
    expect(sandboxEventLabel('sandbox_timeout')).toBe('沙箱超时');
    expect(sandboxViolationLabel('output_too_large')).toBe('输出超过上限');
    expect(formatBytes(8192)).toBe('8.0 KB');
    expect(formatBytes(64000)).toBe('62.5 KB');
    const summary = sandboxDemoSummary({
      kind: 'network',
      sandbox_enabled: true,
      blocked: true,
      event: 'sandbox_blocked',
      violation: 'network',
      reason: '沙箱禁止工具访问网络',
    });
    expect(summary).toContain('已被沙箱拦截');
    expect(summary).toContain('网络访问被阻断');
  });

  it('labels breaker state, trigger and event kinds', () => {
    expect(breakerStateLabel(breaker())).toContain('熔断打开');
    expect(breakerStateLabel(breaker({ open: false }))).toContain('熔断关闭');
    expect(breakerTriggerLabel(breaker())).toBe('短时多次红色操作');
    expect(breakerReason(breaker())).toContain('执行熔断已触发');
    expect(breakerReason(breaker({ open: false, reason: '' }))).toContain('最近没有触发');
    expect(breakerEventLabel('circuit_open')).toBe('熔断打开');
  });

  it('identifies 2A audit events and journal-eligible statuses', () => {
    expect(isTwoAEvent('mfa_failed')).toBe(true);
    expect(isTwoAEvent('tool_executed')).toBe(false);
    expect(eventDescription('sandbox_blocked')).toContain('沙箱');
    expect(journalEligibleStatus('paused')).toBe(true);
    expect(journalEligibleStatus('awaiting_confirmation')).toBe(true);
    expect(journalEligibleStatus('blocked')).toBe(false);
  });
});