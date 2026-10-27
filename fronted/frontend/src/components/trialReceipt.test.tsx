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

  it('shows actual transfer results rather than values in the candidate plan', async () => {
    const run: RunResponse = {
      status: 'completed', run_id: 'transfer-result', reason: '已执行',
      plan: { intent: 'transfer', planner: 'rules', confidence: 1, assumptions: [], steps: [
        { id: 'step-1', tool_name: 'transfer', depends_on: [], arguments: {
          from_account: 'ACC-PLAN', to_account: 'ACC-PLAN-TO', amount_cny: 999,
        } },
      ] },
      results: [{ tool_name: 'transfer', message: '转账完成', data: {
        from_account: 'ACC-1001', to_account: 'ACC-2002', amount_cny: 880,
        status: 'simulated_success', transaction_id: 'TX-returned', simulated: true,
      } }],
    };
    await act(async () => root.render(<BusinessReceipt run={run} />));
    expect(container.textContent).toContain('¥880.00');
    expect(container.textContent).toContain('ACC-1001');
    expect(container.textContent).toContain('ACC-2002');
    expect(container.textContent).toContain('TX-returned');
    expect(container.textContent).toContain('模拟转账成功');
    expect(container.textContent).not.toContain('ACC-PLAN');
    expect(container.textContent).not.toContain('¥999.00');
    expect(container.textContent).not.toContain('张三');
  });

  it('reports missing transfer facts without guessing an account, amount or success', async () => {
    const run: RunResponse = { status: 'completed', run_id: 'missing-transfer', reason: '已处理',
      results: [{ tool_name: 'transfer', message: '已处理', data: {} }] };
    await act(async () => root.render(<BusinessReceipt run={run} />));
    for (const label of ['金额未返回', '转出账户未返回', '收款账户未返回', '状态未返回', '交易编号未返回']) {
      expect(container.textContent).toContain(label);
    }
    expect(container.textContent).not.toContain('成功');
    expect(container.textContent).not.toContain('ACC-');
    expect(container.textContent).not.toContain('¥0.00');
  });

  it.each([
    ['report_card_lost', 'lost', '卡片挂失回执', '已挂失'],
    ['unlock_card', 'active', '卡片解挂回执', '正常'],
    ['report_card_lost', 'active', '卡片挂失回执', '正常'],
    ['unlock_card', 'lost', '卡片解挂回执', '已挂失'],
  ])('shows the returned card state for %s / %s', async (toolName, status, title, label) => {
    const run: RunResponse = { status: 'completed', run_id: 'card-result', reason: '已处理',
      results: [{ tool_name: toolName, message: '已处理', data: { card_id: 'CARD-9902', status } }] };
    await act(async () => root.render(<BusinessReceipt run={run} />));
    expect(container.querySelector('h3')?.textContent).toBe(title);
    const facts = [...container.querySelectorAll('.receipt-business-facts dd')].map((item) => item.textContent);
    expect(facts).toEqual(['CARD-9902', label]);
    expect(container.textContent).not.toContain('CARD-8821');
  });

  it.each([undefined, 'unknown', 'blocked'])('does not infer a normal card from returned state %s', async (status) => {
    const run: RunResponse = { status: 'completed', run_id: 'missing-card', reason: '已处理',
      results: [{ tool_name: 'unlock_card', message: '已处理', data: { status } }] };
    await act(async () => root.render(<BusinessReceipt run={run} />));
    expect(container.textContent).toContain('卡片编号未返回');
    expect(container.textContent).not.toContain('正常');
    expect(container.textContent).toContain(status === undefined ? '状态未返回' : status === 'unknown' ? '状态未知' : '未识别状态（blocked）');
  });

  it.each(['awaiting_confirmation', 'needs_clarification', 'unknown', 'failed', 'rejected'])
    ('hides all business completion summaries for %s, even with leftover results', async (status) => {
      const run: RunResponse = { ...bill, status,
        results: [...bill.results!, { tool_name: 'transfer', message: '转账完成', data: {
          amount_cny: 880, status: 'simulated_success', from_account: 'ACC-1001', to_account: 'ACC-2002',
        } }, { tool_name: 'report_card_lost', message: '已挂失', data: { card_id: 'CARD-8821', status: 'lost' } }],
      };
      await act(async () => root.render(<BusinessReceipt run={run} />));
      expect(container.textContent).toBe('');
    });

  it('does not manufacture business results when only a completed plan is present', async () => {
    await act(async () => root.render(<BusinessReceipt run={{ ...bill, results: [] }} />));
    expect(container.textContent).toBe('');
  });
});
