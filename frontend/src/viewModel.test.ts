import { describe, expect, it } from 'vitest';
import type { RunResponse } from './types';
import {
  collectRiskReasons,
  daysLeft,
  evidenceSourceLabel,
  formatChangePct,
  formatRate,
  formatSignedCny,
  normalizeBankingOverview,
  normalizeEvidence,
  normalizeReadiness,
  paginate,
  prettyEvidence,
  readinessBlockers,
  runRiskLevel,
  severityLabel,
  statusDescription,
  statusLabel,
  wealthRiskLevel,
  wealthRiskLabel,
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

describe('scenario display formatters', () => {
  it('formats annual rates, signed amounts and change percentages', () => {
    expect(formatRate(2.6)).toBe('2.60%');
    expect(formatRate(null)).toBe('—');
    expect(formatSignedCny(1234.5)).toContain('+');
    expect(formatSignedCny(1234.5)).toContain('1,234.50');
    expect(formatSignedCny(-88)).toContain('−');
    expect(formatChangePct(12.34)).toBe('+12.3%');
    expect(formatChangePct(-5)).toBe('−5.0%');
    expect(formatChangePct(null)).toBe('—');
  });

  it('renders friendly renewal countdown labels', () => {
    expect(daysLeft(0)).toBe('今天到期');
    expect(daysLeft(3)).toBe('3 天后');
    expect(daysLeft(-2, true)).toBe('已逾期 2 天');
    expect(daysLeft(null)).toBe('—');
  });

  it('maps task statuses and severities to readable labels', () => {
    expect(statusLabel('unknown')).toBe('结果未知（需对账）');
    expect(statusLabel('reconciled')).toBe('已人工对账');
    expect(statusLabel('rolled_back')).toBe('已人工回滚');
    expect(statusLabel('custom-status')).toBe('custom-status');
    expect(statusDescription('unknown')).toContain('人工对账');
    expect(severityLabel('high')).toBe('高');
    expect(severityLabel('weird')).toBe('weird');
  });

  it('maps wealth R1-R5 levels and evidence sources to display labels', () => {
    expect(wealthRiskLevel('R1')).toBe('green');
    expect(wealthRiskLevel('R3')).toBe('yellow');
    expect(wealthRiskLevel('R5')).toBe('red');
    expect(wealthRiskLabel('R2')).toContain('稳健');
    expect(evidenceSourceLabel('mock_bank')).toBe('Mock 数据');
    expect(evidenceSourceLabel('audit_chain')).toBe('审计哈希链');
  });
});

describe('readiness normalizer', () => {
  const readyComponents = {
    sqlite: { ok: true, detail: 'SQLite 可读写' },
    audit_chain: { ok: true, detail: '哈希链校验通过，共 3 条' },
    mock_bank_seed: { ok: true, detail: '模拟银行种子就绪' },
    planner: { ok: true, detail: 'Planner 可用：rule' },
  };

  it('normalizes ready / degraded / not_ready snapshots and blockers', () => {
    const ready = normalizeReadiness({ status: 'ready', components: readyComponents });
    expect(ready.status).toBe('ready');
    expect(ready.components.sqlite.ok).toBe(true);
    expect(readinessBlockers(ready)).toEqual([]);

    const degraded = normalizeReadiness({
      status: 'degraded',
      components: { ...readyComponents, planner: { ok: false, detail: 'Planner 未初始化' } },
    });
    expect(degraded.status).toBe('degraded');
    expect(readinessBlockers(degraded)).toContain('规划器：Planner 未初始化');

    const broken = normalizeReadiness({
      status: 'not_ready',
      components: { ...readyComponents, sqlite: { ok: false, detail: 'SQLite 不可用' } },
    });
    expect(broken.status).toBe('not_ready');
    expect(readinessBlockers(broken).length).toBeGreaterThan(0);
    expect(readinessBlockers(null)).toContain('尚未获取系统就绪状态');
  });

  it('falls back to not_ready for malformed readiness payloads', () => {
    expect(normalizeReadiness(null).status).toBe('not_ready');
    expect(normalizeReadiness('oops').status).toBe('not_ready');
    expect(normalizeReadiness({ status: 'weird' }).status).toBe('not_ready');
  });
});

describe('evidence normalizer', () => {
  it('keeps valid layered evidence, dedupes and drops invalid items', () => {
    const evidence = normalizeEvidence([
      { source: 'mock_bank', verified: true, verification_kind: 'tool_result', detail: 'simulated' },
      { source: 'mock_bank', verified: true, verification_kind: 'tool_result', detail: 'simulated' },
      { source: 'audit_chain', verified: false, detail: '链校验失败' },
      { source: '', verified: true },
      'not-an-object',
      null,
    ]);
    expect(evidence).toHaveLength(2);
    expect(evidence[0].source).toBe('mock_bank');
    expect(evidence[0].verified).toBe(true);
    expect(evidence[1].source).toBe('audit_chain');
    expect(evidence[1].verified).toBe(false);
  });
});
