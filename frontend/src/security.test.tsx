// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { useResource } from './components/ScenariosPage';
import { ApiError, runAgent, resolveConfirmation, fetchReadiness, fetchTrustAction } from './api';
import { loadPendingSnapshots, loadSubmission } from './session';
import type { RunResponse } from './types';

vi.mock('./api', async (importOriginal) => {
  const original = await importOriginal<typeof import('./api')>();
  return {
    ...original,
    fetchAuthzMe: vi.fn(async () => ({ role: 'user', capabilities: ['tool:execute', 'permission:manage', 'audit:read', 'trust:inspect'] })),
    fetchTools: vi.fn(async () => []),
    fetchPermissions: vi.fn(async () => [{ name: 'transfer', title: '转账', description: 'mock', permission: 'transfer:execute', risk_level: 'yellow', granted: true }]),
    fetchBankingOverview: vi.fn(async () => ({ accounts: [], cards: [], subscriptions: [], abnormalSubscriptions: [], monthSpendingCny: 0, todayTransferTotalCny: 0, asOf: '' })),
    fetchAudit: vi.fn(async () => ({ entries: [] })),
    verifyAudit: vi.fn(async () => ({ valid: true, checked: 0 })),
    fetchReadiness: vi.fn(async () => ({ status: 'ready', components: {} })),
    fetchBreakerStatus: vi.fn(async () => ({ open: false, suspicious: {}, failures: 0, threshold: 3 })),
    fetchMfaProviders: vi.fn(async () => ({ providers: [], enabled: [], default: 'otp', kinds: [] })),
    fetchTrustAction: vi.fn(),
    fetchActionJournal: vi.fn(async () => ({ status: 'pending', pause: {}, entries: [], results: [], nodes: [], irreversible_steps: [] })),
    runAgent: vi.fn(), resolveConfirmation: vi.fn(),
  };
});

const step = { id: 'one', tool_name: 'transfer', arguments: { to_account: 'ACC-2002', amount_cny: 100 }, depends_on: [], risk_level: 'yellow' as const };
const completed: RunResponse = { status: 'completed', run_id: 'completed-run', reason: '完成', results: [] };
function pending(id = 'pending-one'): RunResponse {
  return { status: 'awaiting_confirmation', run_id: id, reason: '等待确认', risk_level: 'yellow',
    plan: { intent: 'transfer', planner: 'rule', confidence: 1, assumptions: [], steps: [step] },
    confirmation: { id, requires_reauth: false, expires_at: new Date(Date.now() + 300_000).toISOString() } };
}
let root: Root | null;
let container: HTMLDivElement;
async function mount() {
  root = createRoot(container);
  await act(async () => { root!.render(<App />); });
}
async function unmount() {
  if (root) await act(async () => root!.unmount());
  root = null;
}
async function click(text: string) {
  const button = [...container.querySelectorAll('button')].find((item) => item.textContent?.trim() === text || item.querySelector('strong')?.textContent === text);
  if (!button) throw new Error(`Missing button ${text}`);
  await act(async () => { button.click(); });
}
async function submit(text: string) {
  const textarea = container.querySelector<HTMLTextAreaElement>('#instruction')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, text);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => { textarea.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
}
beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear(); window.localStorage.clear(); window.location.hash = '#/console';
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLElement.prototype.scrollIntoView = vi.fn();
  window.scrollTo = vi.fn();
  vi.mocked(runAgent).mockResolvedValue(completed);
  vi.mocked(resolveConfirmation).mockResolvedValue(completed);
  vi.mocked(fetchReadiness).mockResolvedValue({ status: 'ready', components: {} });
  container = document.createElement('div'); document.body.append(container);
});
afterEach(async () => { await unmount(); container.remove(); });

describe('submission and confirmation security', () => {
  it('persists the original key before sending, and blocks editing an unresolved submission', async () => {
    vi.mocked(runAgent).mockImplementation(async () => {
      expect(loadSubmission()?.key).toBeTruthy();
      throw new ApiError('lost response', 0);
    });
    await mount(); await submit('向 ACC-2002 转账 100 元');
    await submit('向 ACC-2002 转账 200 元');
    expect(runAgent).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain('先查询原请求结果');
  });
  it('replays the same key after a lost response and reload', async () => {
    vi.mocked(runAgent).mockRejectedValueOnce(new ApiError('lost response', 0)).mockResolvedValue(pending());
    await mount(); await submit('向 ACC-2002 转账 100 元');
    const key = vi.mocked(runAgent).mock.calls[0][1]?.idempotencyKey;
    await unmount(); await mount(); await click('查询原请求结果');
    expect(vi.mocked(runAgent).mock.calls[1][1]?.idempotencyKey).toBe(key);
    expect(loadSubmission()).toBeNull();
    expect(loadPendingSnapshots()).toHaveLength(1);
  });
  it('keeps a confirmation and its key on an in-progress conflict', async () => {
    vi.mocked(runAgent).mockResolvedValue(pending());
    vi.mocked(resolveConfirmation).mockRejectedValue(new ApiError('processing', 409, 'IDEMPOTENCY_IN_PROGRESS'));
    await mount(); await submit('向 ACC-2002 转账 100 元');
    const approve = () => [...container.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(b => /确认.*执行/.test(b.textContent ?? ''))!;
    await act(async () => { approve().click(); });
    await act(async () => { approve().click(); });
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(loadPendingSnapshots()).toHaveLength(1);
    const calls = vi.mocked(resolveConfirmation).mock.calls;
    expect(calls[0][4]?.idempotencyKey).toBe(calls[1][4]?.idempotencyKey);
  });
  it('does not erase a deferred confirmation when an unrelated query completes', async () => {
    vi.mocked(runAgent).mockResolvedValueOnce(pending()).mockResolvedValueOnce(completed);
    await mount(); await submit('向 ACC-2002 转账 100 元');
    await act(async () => { container.querySelector<HTMLButtonElement>('[aria-label="稍后处理并关闭"]')!.click(); });
    await submit('查询本月账单');
    expect(loadPendingSnapshots()[0].pending.confirmation?.id).toBe('pending-one');
    await unmount(); await mount();
    expect(container.textContent).toContain('有一笔待确认的操作');
  });
  it('restores a server plan rather than trusting the session plan', async () => {
    vi.mocked(runAgent).mockResolvedValue(pending());
    await mount(); await submit('向 ACC-2002 转账 100 元');
    await unmount();
    vi.mocked(fetchTrustAction).mockResolvedValue({
      action_id: 'pending-one', user_id: 'demo-user', status: 'pending', state: 'AWAITING_CONFIRMATION',
      risk_level: 'yellow', requires_reauth: false, instruction: '服务端原指令',
      created_at: '', expires_at: new Date(Date.now() + 300_000).toISOString(), history: [], envelopes: [], result: null,
      plan: { intent: 'transfer', planner: 'rule', confidence: 1, assumptions: [], steps: [{ ...step, arguments: { to_account: 'ACC-9003', amount_cny: 320 } }] },
    });
    await mount(); await click('继续处理');
    expect(fetchTrustAction).toHaveBeenCalledWith('pending-one');
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain('ACC-9003');
  });
  it('requires an explicit choice to submit a clarification follow-up', async () => {
    vi.mocked(runAgent).mockResolvedValueOnce({ status: 'needs_clarification', run_id: 'clarify-one', reason: '请提供金额' })
      .mockResolvedValueOnce(pending());
    await mount(); await submit('给张三转账');
    await click('补充上一条任务信息'); await submit('100元');
    expect(vi.mocked(runAgent).mock.calls[1][0]).toEqual({ instruction: '100元', clarification_run_id: 'clarify-one' });
  });
  it('ignores stale resource responses after a filter changes', async () => {
    let resolveOld!: (value: string) => void;
    let resolveNew!: (value: string) => void;
    const oldLoader = () => new Promise<string>(resolve => { resolveOld = resolve; });
    const newLoader = () => new Promise<string>(resolve => { resolveNew = resolve; });
    function Probe({ loader }: { loader: () => Promise<string> }) {
      const resource = useResource(loader, 'failed');
      return <span>{resource.data}</span>;
    }
    root = createRoot(container);
    await act(async () => { root!.render(<Probe loader={oldLoader} />); });
    await act(async () => { root!.render(<Probe loader={newLoader} />); });
    await act(async () => { resolveNew('current-period'); });
    await act(async () => { resolveOld('old-period'); });
    expect(container.textContent).toBe('current-period');
  });
  it('disables permission changes while readiness is unknown or not ready', async () => {
    vi.mocked(fetchReadiness).mockResolvedValue({ status: 'not_ready', components: {} });
    await mount(); await click('权限控制台');
    const revoke = [...container.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === '撤回')!;
    expect(revoke.disabled).toBe(true);
  });
});
