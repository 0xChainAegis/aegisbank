// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchAutomationSchedules, runAutomationDue } from '../api';
import type { AutomationTask, RunResponse } from '../types';
import BusinessReceipt from './BusinessReceipt';
import ScenariosPage from './ScenariosPage';

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  fetchAutomationSchedules: vi.fn(),
  runAutomationDue: vi.fn(),
  ...Object.fromEntries([
    'fetchWealthProducts', 'fetchWealthHoldings', 'fetchWealthOrders', 'fetchContacts',
    'fetchBillReport', 'fetchBillAnomalies', 'fetchSubscriptionCharges', 'fetchRenewalReminders',
    'fetchCardApplications', 'fetchAutomationGoals', 'fetchAutomationOrders',
  ].map((name) => [name, vi.fn(async () => null)])),
}));

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

function completed(toolName: string, data: Record<string, unknown>): RunResponse {
  return { status: 'completed', run_id: 'returned-run', reason: '已完成',
    results: [{ tool_name: toolName, message: '后端回执', data }] };
}

describe('new NLP business receipts', () => {
  it('renders actual bill-report period, totals, categories and conclusion', async () => {
    const run = completed('bill_report', {
      label: '2025 年度', month: null, year: 2025, period: 'year',
      total_spend_cny: 520.5, categories: { food: 500, transport: 20.5 },
      conclusion: '该账期餐饮支出最多。',
    });
    await act(async () => root.render(<BusinessReceipt run={run} />));
    expect(container.textContent).toContain('账期：2025 年度');
    expect(container.textContent).toContain('¥520.50');
    expect(container.textContent).toContain('餐饮');
    expect(container.textContent).toContain('¥500.00');
    expect(container.textContent).toContain('该账期餐饮支出最多。');
    expect(container.textContent).not.toContain('本月');
    expect(container.querySelector('details')).toBeNull();
  });

  it('renders contact and nested transfer facts from the execution result', async () => {
    const run = completed('transfer_to_contact', {
      contact: { name: '妈妈', account_id: 'ACC-****01' }, amount_cny: 999,
      transfer: { from_account: 'ACC-1001', to_account: 'ACC-9001', amount_cny: 500,
        transaction_id: 'TX-contact-returned', status: 'simulated_success' },
    });
    await act(async () => root.render(<BusinessReceipt run={run} />));
    for (const value of ['妈妈', 'ACC-1001', 'ACC-9001', '¥500.00', 'TX-contact-returned', '模拟转账成功']) {
      expect(container.textContent).toContain(value);
    }
    expect(container.textContent).not.toContain('¥999.00');
    expect(container.textContent).not.toContain('ACC-****01');
  });

  it.each(['bill_report', 'transfer_to_contact'])('does not replace missing %s fields with defaults', async (toolName) => {
    const run = completed(toolName, toolName === 'transfer_to_contact'
      ? { contact: { account_id: 'ACC-not-execution' }, amount_cny: 500 } : {});
    await act(async () => root.render(<BusinessReceipt run={run} />));
    expect(container.textContent).toContain('金额未返回');
    expect(container.textContent).not.toContain('¥0.00');
    expect(container.textContent).not.toContain('¥500.00');
    expect(container.textContent).not.toContain('成功');
    expect(container.textContent).not.toContain('ACC-not-execution');
    expect(container.textContent).toContain(toolName === 'bill_report' ? '账期未返回' : '收款账户未返回');
  });

  it.each(['failed', 'awaiting_confirmation', 'needs_clarification', 'unknown'])
    ('does not display successful new NLP business receipts while %s', async (status) => {
      const run: RunResponse = { ...completed('bill_report', { total_spend_cny: 500 }), status,
        results: [
          ...completed('bill_report', { total_spend_cny: 500 }).results!,
          ...completed('transfer_to_contact', { transfer: { amount_cny: 500, status: 'simulated_success' } }).results!,
        ] };
      await act(async () => root.render(<BusinessReceipt run={run} />));
      expect(container.textContent).toBe('');
    });
});

const pendingTask: AutomationTask = {
  task_id: 'TASK-REAUTH-PERSISTED', kind: 'transfer', status: 'pending',
  run_at: '2026-10-29T09:00:00+00:00', recurrence: 'once', created_at: '2026-10-28T08:00:00+00:00',
  last_run_at: '2026-10-29T10:00:00+00:00', amount_cny: 500, label: '定时转账给张三', payload: {},
  last_result: { execution_status: 'needs_reauth', reauth_required: true,
    reason: '到期复检累计风险升为红色。', action_required: '请取消原任务后重新创建并完成强验证。' },
};

describe('persisted scheduled step-up state', () => {
  it('restores the reason and guidance on remount without running the task', async () => {
    vi.mocked(fetchAutomationSchedules).mockResolvedValue({ tasks: [pendingTask], count: 1 });
    const assertPending = () => {
      const row = [...container.querySelectorAll<HTMLLIElement>('li.list-item')]
        .find((item) => item.textContent?.includes('定时转账给张三'))!;
      expect(row.textContent).toContain('待补验证');
      expect(row.textContent).toContain('上次调度未执行、未扣款');
      expect(row.textContent).toContain('到期复检累计风险升为红色。');
      expect(row.textContent).toContain('请取消原任务后重新创建并完成强验证。');
      expect(row.textContent).toContain('最近调度');
      expect(row.textContent).not.toContain('最近执行');
    };
    await act(async () => root.render(<ScenariosPage writesBlocked={false} blockReason="" />));
    assertPending();
    await act(async () => root.unmount());
    root = createRoot(container);
    await act(async () => root.render(<ScenariosPage writesBlocked={false} blockReason="" />));
    assertPending();
    expect(runAutomationDue).not.toHaveBeenCalled();
  });

  it('does not relabel a cancelled task as awaiting reauth from an old result', async () => {
    vi.mocked(fetchAutomationSchedules).mockResolvedValue({
      tasks: [{ ...pendingTask, status: 'cancelled' }], count: 1,
    });
    await act(async () => root.render(<ScenariosPage writesBlocked={false} blockReason="" />));
    const row = [...container.querySelectorAll<HTMLLIElement>('li.list-item')]
      .find((item) => item.textContent?.includes('定时转账给张三'))!;
    expect(row.textContent).toContain('已取消');
    expect(row.textContent).not.toContain('待补验证');
    expect(runAutomationDue).not.toHaveBeenCalled();
  });
});
