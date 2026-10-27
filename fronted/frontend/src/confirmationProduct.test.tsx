// @vitest-environment jsdom
import { act, type ComponentProps } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ConfirmationModal from './components/ConfirmationModal';
import type { PlanStep, RunResponse } from './types';
import { confirmationSummary } from './viewModel';

let root: Root;
let container: HTMLDivElement;
const currentTime = new Date('2026-10-27T10:00:00Z');
const yellowReason = '黄色操作会修改账户设置，需要在 5 分钟内完成一次轻量确认。';
const redReason = '红色操作涉及资金变动，需要二次身份校验并明确确认。';
const transfer: PlanStep = {
  id: 'transfer-1', tool_name: 'transfer', depends_on: [], risk_level: 'yellow',
  arguments: { from_account: 'ACC-1001', to_account: 'ACC-2002', amount_cny: 880 },
};

function pending(step = transfer): RunResponse {
  return {
    status: 'awaiting_confirmation', run_id: 'confirmation-product',
    reason: yellowReason, risk_level: 'yellow',
    risk: { level: 'yellow', reasons: ['本次转账 880.00 元，需要明确确认。'] },
    plan: { intent: step.tool_name, planner: 'rule', confidence: 1, assumptions: [], steps: [step] },
    confirmation: { id: 'confirmation-product', requires_reauth: false,
      expires_at: new Date(currentTime.getTime() + 97_000).toISOString() },
  };
}

function props(run = pending()): ComponentProps<typeof ConfirmationModal> {
  return {
    pending: run, busy: false, mfaToken: '', setMfaToken: vi.fn(),
    mfaProvider: 'otp', setMfaProvider: vi.fn(),
    mfaProviders: [{ name: 'otp', kind: 'otp', title: '演示验证码', enabled: true, default: true }],
    mfaProvidersLoading: false, mfaProvidersError: '', onRefreshMfaProviders: vi.fn(),
    onDecision: vi.fn(), onClose: vi.fn(), writesBlocked: false, blockReason: '',
  };
}

function frontText(): string {
  const copy = container.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('details').forEach((element) => element.remove());
  return copy.textContent ?? '';
}

function decisionButton(): HTMLButtonElement {
  return [...container.querySelectorAll<HTMLButtonElement>('button')]
    .find((button) => button.textContent === '确认执行' || button.textContent === '验证并执行')!;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(currentTime);
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe('confirmation product facts', () => {
  it('puts the real amount and account names with their IDs before technical details', async () => {
    const input = props();
    input.accountLabels = { 'ACC-1001': '我的日常账户', 'ACC-2002': '我的储蓄账户' };
    await act(async () => root.render(<ConfirmationModal {...input} />));

    expect(container.querySelector('h2')?.textContent).toBe('确认转账 ¥880.00');
    expect(frontText()).toContain('转出账户：我的日常账户（ACC-1001）');
    expect(frontText()).toContain('收款账户：我的储蓄账户（ACC-2002）');
    expect(frontText()).toContain('待确认 · 尚未执行');
    expect(frontText()).not.toContain('修改账户设置');
    expect(frontText()).not.toContain('5 分钟');
    expect(container.querySelector('details')?.textContent).toContain(yellowReason);
    expect(input.onDecision).not.toHaveBeenCalled();

    await act(async () => decisionButton().click());
    expect(input.onDecision).toHaveBeenCalledWith(true, 'otp');
  });

  it('keeps IDs without inventing account names and updates labels when overview arrives', async () => {
    const input = props();
    await act(async () => root.render(<ConfirmationModal {...input} />));
    const summary = container.querySelector('.confirm-summary')?.textContent;
    expect(summary).toContain('转出账户：ACC-1001');
    expect(summary).toContain('收款账户：ACC-2002');
    expect(summary).not.toContain('储蓄账户');

    await act(async () => root.render(<ConfirmationModal {...input}
      accountLabels={{ 'ACC-2002': '储蓄账户' }} />));
    expect(container.querySelector('.confirm-summary')?.textContent)
      .toContain('收款账户：储蓄账户（ACC-2002）');
  });

  it('explains card loss as a separate verified recovery and retains its actual risk reason', async () => {
    const run = pending({ id: 'lost-1', tool_name: 'report_card_lost', depends_on: [],
      risk_level: 'red', irreversible: true, arguments: { card_id: 'CARD-9902' } });
    run.risk_level = 'red';
    run.reason = redReason;
    run.risk = { level: 'red', reasons: ['卡片安全操作需要二次身份校验。'] };
    run.confirmation!.requires_reauth = true;
    await act(async () => root.render(<ConfirmationModal {...props(run)} />));

    expect(container.querySelector('h2')?.textContent).toBe('确认挂失银行卡');
    expect(frontText()).toContain('卡片：CARD-9902');
    expect(frontText()).toContain('不支持自动回滚，恢复需另发起解挂并验证。');
    expect(frontText()).toContain('卡片安全操作需要二次身份校验。');
    expect(frontText()).not.toContain('不可撤销');
    expect(frontText()).not.toContain('涉及资金变动');
    expect(decisionButton().disabled).toBe(true);
    expect(container.querySelector('details')?.textContent).toContain(redReason);
  });

  it('counts down from the returned expiry and stops confirmation at that instant', async () => {
    const input = props();
    await act(async () => root.render(<ConfirmationModal {...input} />));
    expect(container.querySelector('.modal-expiry')?.textContent).toBe('剩余 1:37');
    await act(async () => { vi.advanceTimersByTime(96_000); });
    expect(container.querySelector('.modal-expiry')?.textContent).toBe('剩余 0:01');
    expect(decisionButton().disabled).toBe(false);
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(container.querySelector('.modal-expiry')?.textContent).toBe('已过期');
    expect(decisionButton().disabled).toBe(true);
    await act(async () => decisionButton().click());
    expect(input.onDecision).not.toHaveBeenCalled();
  });

  it('keeps nonstandard server warnings and supplied risk findings visible', async () => {
    const run = pending();
    run.reason = '权限已变更，请重新核对本次操作。';
    run.risk = { level: 'yellow', reasons: ['今日累计金额接近强验证阈值。'] };
    await act(async () => root.render(<ConfirmationModal {...props(run)} />));
    expect(frontText()).toContain(run.reason);
    expect(frontText()).toContain('今日累计金额接近强验证阈值。');
  });

  it('preserves the later action and Escape without approving the task', async () => {
    const input = props();
    await act(async () => root.render(<ConfirmationModal {...input} />));
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
    expect(input.onClose).toHaveBeenCalledOnce();
    expect(input.onDecision).not.toHaveBeenCalled();
  });

  it('shows scheduled transfer amount and distinguishes creation from later execution', () => {
    const summary = confirmationSummary({ id: 'scheduled-1', tool_name: 'schedule_transfer',
      depends_on: [], arguments: { from_account: 'ACC-1001', to_name: '张三',
        amount_cny: 500, run_at: '2026-10-28T01:00:00Z' } });
    expect(summary.headline).toBe('定时转账 ¥500.00');
    expect(summary.details.join(' ')).toContain('收款联系人：张三');
    expect(summary.details.join(' ')).toContain('创建任务不立即扣款');
    expect(summary.details.join(' ')).toContain('到期仍会复检权限和风险');
  });
});
