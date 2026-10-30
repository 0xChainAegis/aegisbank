// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resolveConfirmation, runAgent, ApiError } from './api';
import { describeError, isTerminalConfirmationError } from './errors';
import BusinessReceipt from './components/BusinessReceipt';
import ConfirmationModal from './components/ConfirmationModal';
import TaskConsolePage from './components/TaskConsolePage';
import type { RunResponse } from './types';
import { resetRoleCapabilities, setRoleCapabilities } from './roles';

let root: Root;
let container: HTMLDivElement;

function buttonByText(text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>('button')]
    .find((item) => item.textContent?.trim() === text);
  if (!button) throw new Error(`Missing button ${text}`);
  return button;
}

function setInputValue(input: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const prototype = input instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

const clarification: RunResponse = {
  status: 'needs_clarification',
  run_id: 'run-draft-1',
  session_id: 'session-1',
  reason: '还需要转账金额。',
  reason_code: 'missing_amount',
  draft: {
    draft_id: 'draft-1',
    session_id: 'session-1',
    version: 3,
    status: 'awaiting_amount',
    reason_code: 'missing_amount',
    missing_slots: ['amount'],
    plan_hash: 'plan-hash',
    pending_action_id: 'pending-1',
    expires_at: '2026-11-01T12:30:00+08:00',
    changed_fields: ['amount'],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  resetRoleCapabilities('user');
  setRoleCapabilities('user', ['tool:execute', 'permission:manage', 'audit:read', 'trust:inspect']);
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLElement.prototype.scrollIntoView = vi.fn();
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe('U2 conversation requests', () => {
  it('sends the draft triple when supplementing a clarification and shows draft facts', async () => {
    const onExecute = vi.fn();
    function Harness() {
      const [value, setValue] = useState('');
      return (
        <TaskConsolePage
          role={'user'}
          tools={[]}
          toolsLoading={false}
          instruction={value}
          setInstruction={setValue}
          lastRun={clarification}
          busy={false}
          error={''}
          notice={''}
          writesBlocked={false}
          blockReason={''}
          lastActionId={null}
          trustAction={null}
          trustActionLoading={false}
          trustActionError={''}
          onInspectTrustAction={vi.fn()}
          onExecute={onExecute}
          onRefresh={vi.fn()}
          onRecoveryChanged={vi.fn()}
          onNavigateAudit={vi.fn()}
          onReconcile={vi.fn()}
          reconciling={false}
        />
      );
    }
    await act(async () => root.render(<Harness />));

    expect(container.textContent).toContain('草稿版本');
    expect(container.textContent).toContain('v3');
    expect(container.textContent).toContain('amount');
    expect(container.textContent).toContain('有效期');

    await act(async () => buttonByText('补充上一条任务信息').click());
    const textarea = container.querySelector<HTMLTextAreaElement>('#instruction')!;
    await act(async () => setInputValue(textarea, '五百'));
    await act(async () => {
      textarea.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(onExecute).toHaveBeenCalledWith({
      instruction: '五百',
      session_id: 'session-1',
      draft_id: 'draft-1',
      draft_version: 3,
    });
  });

  it('posts the draft triple unchanged to the agent run endpoint', async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      json: async () => ({ status: 'completed', run_id: 'run-2', reason: '完成' }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    await runAgent({
      instruction: '五百',
      session_id: 'session-1',
      draft_id: 'draft-1',
      draft_version: 3,
    });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      user_id: 'demo-user',
      instruction: '五百',
      session_id: 'session-1',
      draft_id: 'draft-1',
      draft_version: 3,
    });
  });

  it('posts the current session and draft when resolving a confirmation', async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      json: async () => ({ status: 'completed', run_id: 'run-3', reason: '完成' }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    await resolveConfirmation('confirmation-1', true, undefined, null, {
      idempotencyKey: 'confirm-key',
      session_id: 'session-1',
      draft_id: 'draft-1',
      draft_version: 3,
    });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      user_id: 'demo-user',
      approved: true,
      reauth_token: null,
      mfa_provider: null,
      session_id: 'session-1',
      draft_id: 'draft-1',
      draft_version: 3,
    });
  });
});

describe('U2 amount amendment', () => {
  it('turns a new amount into the amendment instruction without executing the old confirmation', async () => {
    const onAmend = vi.fn();
    const onDecision = vi.fn();
    const pending: RunResponse = {
      status: 'awaiting_confirmation',
      run_id: 'run-confirm-1',
      session_id: 'session-1',
      reason: '请确认转账。',
      risk_level: 'yellow',
      draft: {
        draft_id: 'draft-1',
        session_id: 'session-1',
        version: 2,
        status: 'awaiting_confirmation',
        pending_action_id: 'confirmation-1',
        expires_at: '2026-11-01T12:30:00+08:00',
      },
      plan: {
        intent: 'transfer_to_contact',
        planner: 'rule',
        confidence: 1,
        assumptions: [],
        steps: [{
          id: 'step-1',
          tool_name: 'transfer_to_contact',
          depends_on: [],
          arguments: { to_name: '妈妈', amount_cny: 500 },
        }],
      },
      confirmation: {
        id: 'confirmation-1',
        requires_reauth: false,
        expires_at: '2026-11-01T12:30:00+08:00',
      },
    };
    await act(async () => root.render(
      <ConfirmationModal
        pending={pending}
        busy={false}
        mfaToken={''}
        setMfaToken={vi.fn()}
        mfaProvider={'otp'}
        setMfaProvider={vi.fn()}
        mfaProviders={[]}
        mfaProvidersLoading={false}
        mfaProvidersError={''}
        onRefreshMfaProviders={vi.fn()}
        onDecision={onDecision}
        onClose={vi.fn()}
        onAmend={onAmend}
        writesBlocked={false}
        blockReason={''}
      />,
    ));

    await act(async () => buttonByText('修改金额').click());
    expect(container.textContent).toContain('当前这笔旧确认不会执行');
    const input = container.querySelector<HTMLInputElement>('input')!;
    await act(async () => setInputValue(input, '300'));
    await act(async () => buttonByText('提交修改').click());

    expect(onAmend).toHaveBeenCalledWith('不是500，改成300');
    expect(onDecision).not.toHaveBeenCalled();
  });
});

describe('U2 recent transfer receipt', () => {
  it('renders the actual recent-transfer readback and simulated source', async () => {
    const run: RunResponse = {
      status: 'completed',
      run_id: 'recent-run',
      reason: '查询完成',
      results: [{
        tool_name: 'query_recent_transfer',
        message: '最近一笔转账',
        data: {
          found: true,
          contact_name: '妈妈',
          amount_cny: 500,
          executed_at: '2026-10-30T03:20:00+00:00',
          transaction_id: 'TX-RECENT-1',
          simulated: true,
        },
      }],
    };
    await act(async () => root.render(<BusinessReceipt run={run} />));
    for (const expected of [
      '妈妈', '¥500.00', '2026', 'TX-RECENT-1', 'simulated=true', '模拟银行回读',
    ]) {
      expect(container.textContent).toContain(expected);
    }
  });

  it('states that no record exists instead of inventing a transfer', async () => {
    const run: RunResponse = {
      status: 'completed',
      run_id: 'recent-missing',
      reason: '查询完成',
      results: [{
        tool_name: 'query_recent_transfer',
        message: '最近一笔转账',
        data: { found: false, simulated: true },
      }],
    };
    await act(async () => root.render(<BusinessReceipt run={run} />));
    expect(container.textContent).toContain('无记录');
    expect(container.textContent).not.toContain('¥0.00');
    expect(container.textContent).not.toContain('妈妈');
  });
});

describe('U2 stale confirmation conflict', () => {
  it('preserves and shows draft_version_conflict while refusing to pretend success', async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          code: 'draft_version_conflict',
          message: '旧确认已被新草稿替代。',
        },
      }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    const error = await resolveConfirmation('old-confirmation', true).catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'draft_version_conflict' });
    expect(isTerminalConfirmationError(error)).toBe(true);
    const explanation = describeError(error, 'confirmation');
    expect(explanation.action).toBe('reconfirm');
    expect(explanation.message).toContain('draft_version_conflict');
    expect(explanation.message).toContain('最新确认');
    expect(explanation.message).toContain('重新发起');
    expect(explanation.message).not.toContain('成功');
  });
});