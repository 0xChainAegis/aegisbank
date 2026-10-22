import { describe, expect, it } from 'vitest';
import type { RunResponse } from './types';
import {
  collectRiskReasons,
  normalizeBankingOverview,
  paginate,
  prettyEvidence,
  runRiskLevel,
} from './viewModel';

describe('banking overview normalizer', () => {
  it('normalizes nested overview payloads and flags abnormal subscriptions', () => {
    const overview = normalizeBankingOverview({
      data: {
        overview: {
          accounts: [
            { account_id: 'ACC-1001', account_name: '工资卡', balance_cny: 18500 },
            { account_id: 'ACC-2002', name: '备用金', balance_cny: 1200.5 },
          ],
          cards: [
            {
              card_id: 'CARD-8821',
              card_name: '白金卡',
              credit_limit_cny: 50000,
              available_limit_cny: 32000,
              repayment_day: 8,
            },
          ],
          subscriptions: [
            { subscription_id: 'SUB-1', merchant: '云存储', amount_cny: 30, status: '正常' },
            {
              subscription_id: 'SUB-2',
              merchant: '未知扣款',
              amount_cny: 199,
              status: '异常',
              abnormal_reason: '三个月未使用仍持续扣费',
            },
          ],
          summary: { month_spending_cny: 3280.5, today_transfer_total_cny: 1280 },
        },
      },
    });

    expect(overview.accounts).toHaveLength(2);
    expect(overview.accounts[0].balanceCny).toBe(18500);
    expect(overview.cards[0].repaymentDay).toBe(8);
    expect(overview.abnormalSubscriptions).toHaveLength(1);
    expect(overview.abnormalSubscriptions[0].merchant).toBe('未知扣款');
    expect(overview.monthSpendingCny).toBe(3280.5);
    expect(overview.todayTransferTotalCny).toBe(1280);
  });
});

describe('risk response helpers', () => {
  it('collects unique risk reasons from assessment, steps and results', () => {
    const run: RunResponse = {
      status: 'awaiting_confirmation',
      run_id: 'run-1',
      risk_level: 'red',
      risk: {
        level: 'red',
        reasons: ['单笔转账金额 6800 元超过 5000 元阈值', '今日累计转账超过 1000 元'],
      },
      reason: '需要二次确认',
      plan: {
        intent: 'transfer',
        planner: 'rule',
        confidence: 0.95,
        assumptions: [],
        steps: [
          {
            id: 'step-1',
            tool_name: 'transfer',
            arguments: { amount_cny: 6800 },
            depends_on: [],
            risk_level: 'red',
            risk_reasons: ['单笔转账金额 6800 元超过 5000 元阈值'],
          },
        ],
      },
      results: [
        {
          tool_name: 'transfer',
          message: 'ok',
          data: {},
          risk: { level: 'red', reasons: ['MFA 二次校验'] },
        },
      ],
    };

    expect(runRiskLevel(run)).toBe('red');
    expect(collectRiskReasons(run)).toEqual([
      '单笔转账金额 6800 元超过 5000 元阈值',
      '今日累计转账超过 1000 元',
      'MFA 二次校验',
    ]);
  });
});

describe('pagination helper', () => {
  it('clamps pages and returns display bounds', () => {
    const result = paginate([1, 2, 3, 4, 5, 6, 7], 99, 3);
    expect(result.page).toBe(3);
    expect(result.totalPages).toBe(3);
    expect(result.items).toEqual([7]);
    expect(result.start).toBe(7);
    expect(result.end).toBe(7);
  });
});

describe('evidence formatter', () => {
  it('pretty prints JSON strings and keeps plain text readable', () => {
    expect(prettyEvidence('{"ok":true}')).toContain('"ok": true');
    expect(prettyEvidence('bank declined')).toBe('bank declined');
  });
});
