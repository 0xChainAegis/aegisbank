// @vitest-environment jsdom
import { act, type ComponentProps } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchActionJournal, pauseAction, runAutomationDue } from '../api';
import { resetRoleCapabilities, setRoleCapabilities } from '../roles';
import type { ActionJournal, BankingOverview, RunResponse, ToolMetadata } from '../types';
import BankOverviewPage from './BankOverviewPage';
import PermissionsPage from './PermissionsPage';
import StepJournalPanel from './StepJournalPanel';
import TaskConsolePage from './TaskConsolePage';
import ScenariosPage from './ScenariosPage';

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  fetchActionJournal: vi.fn(),
  pauseAction: vi.fn(),
  runAutomationDue: vi.fn(),
  ...Object.fromEntries([
    'fetchWealthProducts', 'fetchWealthHoldings', 'fetchWealthOrders', 'fetchContacts',
    'fetchBillReport', 'fetchBillAnomalies', 'fetchSubscriptionCharges', 'fetchRenewalReminders',
    'fetchCardApplications', 'fetchAutomationSchedules', 'fetchAutomationGoals', 'fetchAutomationOrders',
  ].map((name) => [name, vi.fn(async () => null)])),
}));

const tool: ToolMetadata = {
  name: 'set_transaction_limit', title: '设置交易限额', description: '设置单日限额',
  risk_level: 'yellow', permission: 'card:manage', granted: true, input_schema: {}, output_schema: {},
};

const taskProps = (): ComponentProps<typeof TaskConsolePage> => ({
  role: 'user', tools: [tool], toolsLoading: false, instruction: '',
  setInstruction: vi.fn(), lastRun: null, busy: false, error: '', notice: '',
  writesBlocked: false, blockReason: '', lastActionId: null,
  trustAction: null, trustActionLoading: false, trustActionError: '',
  onInspectTrustAction: vi.fn(), onExecute: vi.fn(), onRefresh: vi.fn(),
  onRecoveryChanged: vi.fn(), onNavigateAudit: vi.fn(), onReconcile: vi.fn(),
  reconciling: false,
});

const journal = (status: string): ActionJournal => ({
  status, pause: { paused: false }, entries: [], results: [], nodes: [],
  irreversible_steps: [],
} as unknown as ActionJournal);

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  vi.clearAllMocks();
  setRoleCapabilities('user', ['tool:execute', 'permission:manage']);
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLElement.prototype.scrollIntoView = vi.fn();
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  resetRoleCapabilities('user');
  container.remove();
});

describe('business page interactions', () => {
  it('shows active cards as normal and updates the status after loss and recovery', async () => {
    const overview = (status: string): BankingOverview => ({
      accounts: [], subscriptions: [], abnormalSubscriptions: [],
      monthSpendingCny: 0, todayTransferTotalCny: 0, asOf: '',
      cards: [{ id: 'CARD-8821', accountId: 'ACC-1001', name: '模拟银行卡',
        maskedNumber: '**** 8821', status, creditLimitCny: 30000,
        availableLimitCny: 21750, repaymentDay: 8 }],
    });
    const renderStatus = async (status: string) => {
      await act(async () => root.render(<BankOverviewPage overview={overview(status)}
        loading={false} error="" notice="" onRefresh={vi.fn()} onNavigateConsole={vi.fn()} />));
      return container.querySelector('.bank-card-top > span')!;
    };
    let status = await renderStatus('active');
    expect(status.textContent).toBe('正常');
    expect(status.className).toBe('grant-on');
    status = await renderStatus('lost');
    expect(status.textContent).toBe('已挂失');
    expect(status.className).toBe('grant-off');
    status = await renderStatus('active');
    expect(status.textContent).toBe('正常');
    expect(status.className).toBe('grant-on');
  });

  it.each(['unknown', '', 'inactive'])('does not display an unrecognized card state %j as normal', async (cardStatus) => {
    const overview: BankingOverview = {
      accounts: [], subscriptions: [], abnormalSubscriptions: [],
      monthSpendingCny: 0, todayTransferTotalCny: 0, asOf: '',
      cards: [{ id: 'CARD-8821', accountId: 'ACC-1001', name: '模拟银行卡',
        maskedNumber: '**** 8821', status: cardStatus, creditLimitCny: 30000,
        availableLimitCny: 21750, repaymentDay: 8 }],
    };
    await act(async () => root.render(<BankOverviewPage overview={overview}
      loading={false} error="" notice="" onRefresh={vi.fn()} onNavigateConsole={vi.fn()} />));
    const status = container.querySelector('.bank-card-top > span')!;
    expect(status.textContent).not.toBe('正常');
    expect(status.className).toBe('grant-off');
    if (!cardStatus || cardStatus === 'unknown') expect(status.textContent).toBe('状态未知');
  });

  it.each([
    ['active', 'monthly', '生效中', '每月', 'grant-on'],
    ['cancelled', 'yearly', '已取消', '每年', 'subscription-status'],
    ['canceled', 'annual', '已取消', '每年', 'subscription-status'],
    ['expired', 'weekly', '已过期', '每周', 'subscription-status'],
    ['paused', 'quarterly', '已暂停', '每季度', 'subscription-status'],
    ['unknown', '', '状态未知', '周期未知', 'subscription-status'],
    ['future_state', 'custom_cycle', 'future_state', 'custom_cycle', 'subscription-status'],
  ])('localizes subscription %s / %s without treating unknown states as active',
    async (status, cycle, statusLabel, cycleLabel, statusClass) => {
      const overview: BankingOverview = {
        accounts: [], cards: [], abnormalSubscriptions: [],
        monthSpendingCny: 0, todayTransferTotalCny: 0, asOf: '',
        subscriptions: [{ id: 'SUB-test', merchant: '测试订阅', amountCny: 30,
          cycle, status, nextBillingDate: '2026-11-01', abnormal: false, reason: '' }],
      };
      await act(async () => root.render(<BankOverviewPage overview={overview}
        loading={false} error="" notice="" onRefresh={vi.fn()} onNavigateConsole={vi.fn()} />));
      const cells = container.querySelectorAll('tbody tr td');
      expect(cells[2]?.textContent).toBe(cycleLabel);
      expect(cells[4]?.textContent).toBe(statusLabel);
      expect(cells[4]?.querySelector('span')?.className).toBe(statusClass);
    });

  it('shows a cancelled subscription risk as history instead of an upcoming debit to resolve', async () => {
    const overview: BankingOverview = {
      accounts: [], cards: [], abnormalSubscriptions: [],
      monthSpendingCny: 0, todayTransferTotalCny: 0, asOf: '',
      subscriptions: [{ id: 'SUB-cancelled', merchant: '已取消项目', amountCny: 199,
        cycle: 'monthly', status: 'cancelled', nextBillingDate: '2026-11-01',
        abnormal: true, reason: '价格上涨' }],
    };
    await act(async () => root.render(<BankOverviewPage overview={overview}
      loading={false} error="" notice="" onRefresh={vi.fn()} onNavigateConsole={vi.fn()} />));
    const row = container.querySelector('tbody tr')!;
    expect(row.className).not.toContain('row-abnormal');
    expect(row.querySelectorAll('td')[3]?.textContent).toBe('—');
    expect(row.textContent).not.toContain('需处理');
    expect(row.textContent).toContain('历史提示：价格上涨');
  });

  it('shows the birthday execution date and formats only currency fields as money', async () => {
    const props = taskProps();
    props.lastRun = {
      status: 'completed', run_id: 'birthday', reason: '已排期',
      results: [{ tool_name: 'schedule_flower_order', message: '已排期',
        data: { due_at: '2026-11-04T08:00:00+08:00', amount_cny: 200, amount_unit: 'CNY' } }],
    } as RunResponse;
    await act(async () => root.render(<TaskConsolePage {...props} />));
    expect(container.querySelector('.data-grid')?.textContent).toContain('2026-11-04T08:00:00+08:00');
    expect(container.querySelector('.data-grid')?.textContent).toContain('¥200.00');
    expect(container.querySelector('.data-grid')?.textContent).toContain('CNY');
  });

  it('renders the risk engine label in Chinese and the audit reference when present', async () => {
    const props = taskProps();
    props.lastRun = {
      status: 'completed', run_id: 'run-risk-label', reason: '已完成',
      audit_id: 42, risk_level: 'yellow',
      risk: { level: 'yellow', reasons: ['本次操作需要明确确认。'] },
      results: [{ tool_name: 'query_bill', message: '账单查询完成',
        data: { total_spend_cny: 100 } }],
    } as RunResponse;
    await act(async () => root.render(<TaskConsolePage {...props} />));
    expect(container.querySelector('.risk-reason-panel .eyebrow')?.textContent).toBe('风险引擎判定');
    expect(container.textContent).not.toContain('RISK ENGINE FINDINGS');
    const facts = [...container.querySelectorAll('.receipt-facts > div')].map((row) => ({
      label: row.querySelector('span')?.textContent,
      value: row.querySelector('strong')?.textContent,
    }));
    expect(facts).toContainEqual({ label: '审计编号', value: '#42' });
    expect(facts.find((fact) => fact.label === '运行编号')).toBeUndefined();
  });

  it('labels a completed bill receipt reference with run_id when audit_id is absent', async () => {
    const props = taskProps();
    props.lastRun = {
      status: 'completed', run_id: 'run-bill-1', reason: '账单查询完成',
      risk_level: 'green', risk: { level: 'green', reasons: ['仅执行只读查询。'] },
      results: [{ tool_name: 'query_bill', message: '账单查询完成',
        data: { total_spend_cny: 100, month: '2026-10', categories: { food: 100 }, anomalies: [] } }],
    } as RunResponse;
    await act(async () => root.render(<TaskConsolePage {...props} />));
    const facts = [...container.querySelectorAll('.receipt-facts > div')].map((row) => ({
      label: row.querySelector('span')?.textContent,
      value: row.querySelector('strong')?.textContent,
    }));
    expect(facts).toContainEqual({ label: '运行编号', value: 'run-bill-1' });
    expect(facts.find((fact) => fact.label === '审计编号')).toBeUndefined();
    expect(facts.find((fact) => fact.label === '执行时间')?.value).toBe('—');
    expect(container.querySelector('.business-receipt-bill')).not.toBeNull();
  });

  it('sends the actual daily-limit instruction from the card shortcut', async () => {
    const props = taskProps();
    await act(async () => root.render(<TaskConsolePage {...props} />));
    const shortcut = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.querySelector('strong')?.textContent === '调整交易限额')!;
    await act(async () => shortcut.click());
    expect(props.onExecute).toHaveBeenCalledWith(expect.objectContaining({
      instruction: '把 CARD-8821 的单日交易限额调整为 8000 元',
    }));
  });

  it('uses supported single-query and full DAG instructions in the demo shortcuts', async () => {
    const props = taskProps();
    props.tools = ['query_bill', 'list_subscriptions', 'cancel_subscription', 'unlock_card']
      .map((name) => ({ ...tool, name }));
    await act(async () => root.render(<TaskConsolePage {...props} />));
    const clickTitle = async (title: string) => {
      const button = [...container.querySelectorAll<HTMLButtonElement>('button')]
        .find((item) => item.querySelector('strong')?.textContent === title)!;
      await act(async () => button.click());
    };
    await clickTitle('分析本月账单');
    expect(props.onExecute).toHaveBeenLastCalledWith(expect.objectContaining({ instruction: '分析我的本月账单' }));
    await clickTitle('分析并取消异常订阅');
    expect(props.onExecute).toHaveBeenLastCalledWith(expect.objectContaining({ instruction: '分析我的账单并取消异常订阅' }));
    await clickTitle('解挂卡片');
    expect(props.onExecute).toHaveBeenLastCalledWith(expect.objectContaining({ instruction: '解挂卡片 CARD-8821' }));
  });

  it('explains readiness restrictions and disables permission changes during refresh', async () => {
    const props: ComponentProps<typeof PermissionsPage> = {
      role: 'user', writesBlocked: true, tools: [tool], loading: false,
      error: '', notice: '', busyTool: '', onToggle: vi.fn(), onRefresh: vi.fn(),
    };
    await act(async () => root.render(<PermissionsPage {...props} />));
    expect(container.querySelector('[role="status"]')?.textContent).toContain('系统尚未就绪');
    const toggle = () => container.querySelector<HTMLButtonElement>('.table-action button')!;
    expect(toggle().title).toContain('系统尚未就绪');
    await act(async () => root.render(<PermissionsPage {...props} writesBlocked={false} loading />));
    expect(toggle().disabled).toBe(true);
    expect(toggle().title).toContain('同步最新权限');
  });

  it('ignores a previous action journal that finishes after switching actions', async () => {
    let finishOld!: (value: ActionJournal) => void;
    vi.mocked(fetchActionJournal).mockImplementation((actionId) => actionId === 'old-action'
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.resolve(journal('completed')));
    const props: ComponentProps<typeof StepJournalPanel> = {
      actionId: 'old-action', role: 'user', run: null,
      writesBlocked: false, blockReason: '', onChanged: vi.fn(),
    };
    await act(async () => root.render(<StepJournalPanel {...props} />));
    await act(async () => root.render(<StepJournalPanel {...props} actionId="new-action" />));
    await act(async () => finishOld(journal('unknown')));
    expect(container.querySelector('.journal-facts .status-pill')?.className).toContain('status-completed');
    expect(container.querySelector('.journal-action-id')?.textContent).toBe('new-action');
  });

  it('does not apply a late recovery result to another action', async () => {
    let finishPause!: (value: unknown) => void;
    vi.mocked(fetchActionJournal).mockResolvedValue(journal('completed'));
    vi.mocked(pauseAction).mockImplementation(() => new Promise((resolve) => { finishPause = resolve; }));
    const props: ComponentProps<typeof StepJournalPanel> = {
      actionId: 'old-action', role: 'user', run: null,
      writesBlocked: false, blockReason: '', onChanged: vi.fn(),
    };
    await act(async () => root.render(<StepJournalPanel {...props} />));
    const pause = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '暂停执行')!;
    await act(async () => pause.click());
    await act(async () => root.render(<StepJournalPanel {...props} actionId="new-action" />));
    await act(async () => finishPause({ status: 'paused' }));
    expect(props.onChanged).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain('暂停请求已生效');
    expect(fetchActionJournal).toHaveBeenCalledTimes(2);
  });

  it('shows a blocked scheduler result without claiming that no tasks were due', async () => {
    vi.mocked(runAutomationDue).mockResolvedValue({
      status: 'blocked', reason: '安全熔断已打开', now: null,
      executed: [], failed: [], executed_count: 0, failed_count: 0, simulated: true,
    });
    await act(async () => root.render(<ScenariosPage writesBlocked={false} blockReason="" />));
    const run = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '执行当前到期任务')!;
    await act(async () => run.click());
    expect(container.querySelector('.run-due-result')?.textContent).toContain('安全熔断已打开');
    expect(container.querySelector('.run-due-result')?.textContent).not.toContain('调度器已正常返回');
  });

  it('surfaces pending re-authentication from run-due instead of claiming completion', async () => {
    vi.mocked(runAutomationDue).mockResolvedValue({
      status: 'completed',
      reason: '到期任务已处理',
      now: '2027-01-01T12:00:00+00:00',
      executed: [],
      failed: [],
      executed_count: 0,
      failed_count: 0,
      pending_reauth: [{
        task_id: 'TASK-REAUTH-1',
        kind: 'transfer',
        status: 'pending',
        execution_status: 'needs_reauth',
        reason: '到期复检时风险升为 red',
        action_required: '取消该定时任务后重新创建，并完成 OTP 强验证。',
        amount_cny: 3000,
        reauth_required: true,
      }],
      pending_reauth_count: 1,
      action_required: true,
      simulated: true,
    });
    await act(async () => root.render(<ScenariosPage writesBlocked={false} blockReason="" />));
    const run = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '执行当前到期任务')!;
    await act(async () => run.click());

    const result = container.querySelector('.run-due-result')!;
    const warning = result.querySelector('.run-due-reauth')!;
    expect(warning.getAttribute('role')).toBe('alert');
    expect(warning.textContent).toContain('未执行、未扣款');
    expect(warning.textContent).toContain('TASK-REAUTH-1');
    expect(warning.textContent).toContain('到期复检时风险升为 red');
    expect(warning.textContent).toContain('OTP');
    expect(warning.textContent).toContain('取消');
    expect(warning.textContent).toContain('重新创建');
    expect(result.querySelector('.eyebrow')?.textContent).toContain('需要重新认证');
    expect(result.querySelector('.eyebrow')?.textContent).not.toContain('已完成');
    expect(result.textContent).not.toContain('调度器已正常返回');
  });

  it('passes the selected simulation time to the scheduler', async () => {
    vi.mocked(runAutomationDue).mockResolvedValue({
      status: 'completed', now: null,
      executed: [], failed: [], executed_count: 0, failed_count: 0, simulated: true,
    });
    await act(async () => root.render(<ScenariosPage writesBlocked={false} blockReason="" />));
    const time = container.querySelector<HTMLInputElement>('[aria-label="模拟调度截止时间"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(time, '2027-01-01T12:00');
      time.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const run = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '时间快进 · 执行到期任务')!;
    expect(run).toBeTruthy();
    await act(async () => run.click());
    expect(runAutomationDue).toHaveBeenCalledWith(new Date('2027-01-01T12:00').toISOString());
  });
});
