// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import BusinessReceipt from './BusinessReceipt';
import type { RunResponse } from '../types';

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement('div'); document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

const bill: RunResponse = {
  status: 'completed', run_id: 'bill-result', reason: '查询完成',
  results: [{ tool_name: 'query_bill', message: '账单',
    data: { month: '2026-09', total_spend_cny: 120.5, categories: { food: 100, transport: 20.5 },
      anomalies: ['请核对订阅项目'], simulated: true } }],
};

describe('business receipt facts', () => {
  it('shows returned spending, categories and anomaly text outside technical details', async () => {
    await act(async () => root.render(<BusinessReceipt run={bill} />));
    expect(container.textContent).toContain('¥120.50');
    expect(container.textContent).toContain('餐饮');
    expect(container.textContent).toContain('¥100.00');
    expect(container.textContent).toContain('请核对订阅项目');
    expect(container.textContent).toContain('账期：2026-09');
    expect(container.textContent).not.toContain('本月');
    expect(container.querySelector('details')).toBeNull();
  });
  it('does not turn missing financial facts into a zero spending claim', async () => {
    const missing = { ...bill, results: [{ ...bill.results![0], data: {} }] };
    await act(async () => root.render(<BusinessReceipt run={missing} />));
    expect(container.textContent).toContain('金额未返回');
    expect(container.textContent).not.toContain('¥0.00');
  });
  it('does not show a completion summary for a failed task with leftover results', async () => {
    await act(async () => root.render(<BusinessReceipt run={{ ...bill, status: 'failed' }} />));
    expect(container.textContent).toBe('');
  });
});
