// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App, { initialRole } from './App';
import { useResource } from './components/ScenariosPage';
import { ApiError, runAgent, resolveConfirmation, fetchReadiness, fetchTrustAction, fetchMfaProviders } from './api';
import { loadPendingSnapshots, loadSubmission, savePendingSnapshot, saveSubmission } from './session';
import { ROLE_STORAGE_KEY } from './roles';
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
  vi.mocked(fetchMfaProviders).mockResolvedValue({ providers: [], enabled: [], default: 'otp', kinds: [] });
  container = document.createElement('div'); document.body.append(container);
});
afterEach(async () => { await unmount(); container.remove(); });

describe('submission and confirmation security', () => {
  it('keeps primary examples as editable requests rather than executing them', async () => {
    await mount();
    const example = container.querySelectorAll<HTMLButtonElement>('.demo-path button')[1];
    await act(async () => example.click());
    expect(container.querySelector<HTMLTextAreaElement>('#instruction')?.value)
      .toBe('向 ACC-2002 转账 880 元');
    expect(runAgent).not.toHaveBeenCalled();
  });
  it('keeps the current receipt ahead of the collapsed business examples', async () => {
    await mount(); await submit('分析我的本月账单');
    const result = container.querySelector('.result-card')!;
    const examples = container.querySelector<HTMLDetailsElement>('.scenario-library')!;
    expect(result.compareDocumentPosition(examples) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(examples.open).toBe(false);
    expect(container.querySelector<HTMLDetailsElement>('.system-details')?.open).toBe(false);
  });
  it('ties a displayed receipt to the submitted request while the user edits a new draft', async () => {
    await mount(); await submit('分析我的本月账单');
    const textarea = container.querySelector<HTMLTextAreaElement>('#instruction')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, '挂失我的卡片');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(container.querySelector('.submitted-request')?.textContent).toContain('分析我的本月账单');
    expect(container.querySelector('.submitted-request')?.textContent).not.toContain('挂失我的卡片');
  });
  it('opens the assistant from accounts and prefills a task without sending a banking request', async () => {
    window.location.hash = '#/overview';
    await mount();
    await click('银行助手');
    await act(async () => container.querySelectorAll<HTMLButtonElement>('.demo-path button')[1].click());
    expect(container.querySelector<HTMLTextAreaElement>('#instruction')?.value)
      .toBe('向 ACC-2002 转账 880 元');
    expect(runAgent).not.toHaveBeenCalled();
    expect(container.textContent).toContain('示例已填入');
  });
  it('keeps a green journal without offering a pending-only trust lookup', async () => {
    await mount(); await submit('分析我的本月账单');
    expect(container.textContent).not.toContain('查看信任详情');
    expect(container.textContent).toContain('completed-run');
    expect(fetchTrustAction).not.toHaveBeenCalled();
  });
  it('retains trust inspection after a confirmed action is resolved', async () => {
    vi.mocked(runAgent).mockResolvedValue(pending());
    await mount(); await submit('向 ACC-2002 转账 880 元');
    await click('拒绝执行');
    expect(container.textContent).toContain('查看信任详情');
  });
  it('restores the submission role when another tab has changed the preferred role', () => {
    window.localStorage.setItem(ROLE_STORAGE_KEY, 'auditor');
    saveSubmission({ key: 'original-key', input: { instruction: '向妈妈转账 100 元' }, role: 'user' });
    expect(initialRole()).toBe('user');
  });
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
  it('shows the completed server receipt when a deferred confirmation was resolved elsewhere', async () => {
    savePendingSnapshot({ pending: pending(), instruction: '原始转账指令', savedAt: new Date().toISOString() });
    window.location.hash = '#/overview';
    vi.mocked(fetchTrustAction).mockResolvedValue({
      action_id: 'pending-one', user_id: 'demo-user', status: 'completed', state: 'COMPLETED',
      risk_level: 'yellow', requires_reauth: false, instruction: '原始转账指令',
      created_at: '', expires_at: new Date(Date.now() + 300_000).toISOString(), history: [], envelopes: [],
      result: { ...completed, run_id: 'pending-one', reason: '服务端已完成该笔转账' },
      plan: { intent: 'transfer', planner: 'rule', confidence: 1, assumptions: [], steps: [step] },
    });
    await mount(); await click('继续处理');

    expect(container.querySelector('#instruction')).not.toBeNull();
    expect(container.textContent).toContain('服务端已完成该笔转账');
    expect(container.textContent).toContain('pending-one');
    expect(loadPendingSnapshots()).toHaveLength(0);
    expect(resolveConfirmation).not.toHaveBeenCalled();
    expect(runAgent).not.toHaveBeenCalled();
  });
  it('advances the recovery banner to the next confirmation when its countdown expires', async () => {
    vi.useFakeTimers();
    try {
      const first = pending('expires-first');
      first.confirmation!.expires_at = new Date(Date.now() + 2000).toISOString();
      savePendingSnapshot({ pending: first, instruction: '即将过期的任务', savedAt: new Date().toISOString() });
      savePendingSnapshot({ pending: pending('still-active'), instruction: '后续有效任务', savedAt: new Date().toISOString() });
      await mount();
      expect(container.querySelector('.restore-banner')?.textContent).toContain('剩余 0:02');
      await act(async () => { vi.advanceTimersByTime(1000); });
      expect(container.querySelector('.restore-banner')?.textContent).toContain('剩余 0:01');
      await act(async () => { vi.advanceTimersByTime(1000); });
      expect(container.querySelector('.restore-banner')?.textContent).toContain('后续有效任务');
      expect(loadPendingSnapshots()).toHaveLength(1);
      await unmount();
    } finally {
      vi.useRealTimers();
    }
  });
  it('freezes MFA method and token controls while verification is in flight', async () => {
    const red = pending('red-one');
    red.risk_level = 'red';
    red.confirmation!.requires_reauth = true;
    vi.mocked(runAgent).mockResolvedValue(red);
    vi.mocked(fetchMfaProviders).mockResolvedValue({
      providers: [
        { name: 'otp', kind: 'otp', title: '验证码', enabled: true, default: true },
        { name: 'biometric', kind: 'biometric', title: '模拟人脸', enabled: true },
      ], enabled: ['otp', 'biometric'], default: 'otp', kinds: ['otp', 'biometric'],
    });
    let finish!: (result: RunResponse) => void;
    vi.mocked(resolveConfirmation).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await mount(); await submit('挂失 CARD-9902');
    await click('填入演示令牌'); await click('验证并执行');

    const modal = container.querySelector('[role="dialog"]')!;
    expect(modal.querySelector<HTMLInputElement>('input')!.disabled).toBe(true);
    expect([...modal.querySelectorAll<HTMLButtonElement>('[role="radio"]')].every(button => button.disabled)).toBe(true);
    const fill = [...modal.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === '填入演示令牌')!;
    expect(fill.disabled).toBe(true);
    await act(async () => { finish(completed); });
  });
  it('requires an explicit choice to submit a clarification follow-up', async () => {
    vi.mocked(runAgent).mockResolvedValueOnce({ status: 'needs_clarification', run_id: 'clarify-one', reason: '请提供金额' })
      .mockResolvedValueOnce(pending());
    await mount(); await submit('给张三转账');
    await click('补充上一条任务信息'); await submit('100元');
    expect(vi.mocked(runAgent).mock.calls[1][0]).toEqual({ instruction: '100元', clarification_run_id: 'clarify-one' });
  });
  it('shows an unevaluated risk for clarification instead of the default green execution badge', async () => {
    vi.mocked(runAgent).mockResolvedValueOnce({
      status: 'needs_clarification', run_id: 'clarify-card', reason: '请补充要挂失的卡号',
      risk_reasons: ['缺少卡号，尚不能生成执行计划'],
    });
    await mount(); await submit('挂失我的卡');
    const result = container.querySelector('.result-card')!;
    expect(result.querySelector('.result-tags')?.textContent).toContain('风险待评估');
    expect(result.querySelector('.receipt-facts')?.textContent).toContain('风险待评估');
    expect(result.querySelector('.risk-reason-panel')).toBeNull();
    expect(result.querySelector('.risk-green')).toBeNull();
    expect(result.textContent).not.toContain('GREEN');
    expect([...result.querySelectorAll('[title]')].some(item => /绿色|直接执行/.test(item.getAttribute('title') ?? ''))).toBe(false);
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
