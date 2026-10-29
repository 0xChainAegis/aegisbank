import { describe, expect, it } from 'vitest';
import type { RunResponse } from './types';
import {
  collectRiskReasons,
  confirmationSummary,
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
  receiptHeadline,
  receiptReference,
  resultExecutedAt,
  runRiskLevel,
  severityLabel,
  statusDescription,
  statusLabel,
  wealthRiskLevel,
  wealthRiskLabel,
} from './viewModel';

describe('banking overview normalizer', () => {
  it('keeps cancelled subscriptions in history without repeating an active anomaly alert', () => {
    const overview = normalizeBankingOverview({
      accounts: [], cards: [], monthly_spend_cny: 0, daily_transfer_total_cny: 0,
      subscriptions: [
        { subscription_id: 'SUB-cancelled', merchant: 'AI 工具', amount_cny: 99, status: 'cancelled', risk_flag: '上涨 120%' },
        { subscription_id: 'SUB-active', merchant: '云存储', amount_cny: 30, status: 'active', risk_flag: '重复扣费' },
      ],
      abnormal_subscriptions: ['SUB-cancelled'],
    });
    expect(overview.subscriptions).toHaveLength(2);
    expect(overview.abnormalSubscriptions.map((item) => item.id)).toEqual(['SUB-active']);
  });
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
    expect(wealthRiskLevel('unknown')).toBe('red');
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

describe('confirmation summary (UX-10)', () => {
  it('shows the daily card limit from the actual tool argument', () => {
    const summary = confirmationSummary({
      id: 'limit-1', tool_name: 'set_transaction_limit', depends_on: [],
      arguments: { card_id: 'CARD-8821', daily_limit_cny: 3000 },
    });
    expect(summary.headline).toContain('每日');
    expect(summary.details.join(' ')).toContain('3,000');
  });
  it('turns raw transfer arguments into a human readable sentence', () => {
    const summary = confirmationSummary({
      id: 'step-1',
      tool_name: 'transfer',
      arguments: {
        from_account: 'ACC-1001',
        to_account: 'ACC-2002',
        amount_cny: 6800,
        note: '任务控制台 · 大额转账',
      },
      depends_on: [],
    });
    expect(summary.headline).toContain('6,800');
    expect(summary.details.join(' ')).toContain('ACC-2002');
    expect(summary.details.join(' ')).toContain('任务控制台');
    expect(summary.unresolved).toBe(false);
  });

  it('flags runtime-resolved placeholders instead of showing raw template text', () => {
    const summary = confirmationSummary({
      id: 'step-2',
      tool_name: 'cancel_subscription',
      arguments: { subscription_id: '${steps.step-1.data.suspicious_subscription_id}' },
      depends_on: ['step-1'],
    });
    expect(summary.unresolved).toBe(true);
    expect(summary.details.join(' ')).toContain('执行时确定');
    expect(summary.details.join(' ')).not.toContain('${steps');
  });

  it('keeps irreversible steps explicit', () => {
    const summary = confirmationSummary({
      id: 'step-3',
      tool_name: 'report_card_lost',
      arguments: { card_id: 'CARD-8821' },
      depends_on: [],
      irreversible: true,
    });
    expect(summary.details.join(' ')).toContain('不支持自动回滚');
    expect(summary.details.join(' ')).toContain('恢复需另发起解挂并验证');
  });
});

describe('receipt headline (UX-14)', () => {
  it('prefers the tool result message and exposes execution time', () => {
    const run: RunResponse = {
      status: 'completed',
      run_id: 'run-1',
      reason: '确认通过，任务已执行。',
      results: [
        {
          tool_name: 'transfer',
          message: '转账指令已通过风险校验并完成模拟执行。',
          data: { executed_at: '2026-10-23T08:42:57+00:00' },
        },
      ],
    };
    expect(receiptHeadline(run)).toContain('转账指令');
    expect(resultExecutedAt(run)).toBe('2026-10-23T08:42:57+00:00');
  });

  it('prefers audit_id and falls back to the stable run_id for the receipt reference', () => {
    expect(receiptReference({
      status: 'completed', run_id: 'run-audit', reason: '', audit_id: 42,
    })).toEqual({ label: '审计编号', value: '#42' });
    expect(receiptReference({
      status: 'completed', run_id: 'run-bill-1', reason: '',
    })).toEqual({ label: '运行编号', value: 'run-bill-1' });
    expect(receiptReference({
      status: 'completed', run_id: '', reason: '',
    })).toEqual({ label: '审计编号', value: '—' });
    expect(resultExecutedAt({
      status: 'completed', run_id: 'run-bill-1', reason: '',
      results: [{ tool_name: 'query_bill', message: '账单查询完成', data: { total_spend_cny: 100 } }],
    })).toBe('');
  });

  it('maps terminal states to plain language without leaking status codes', () => {
    const rejected: RunResponse = { status: 'rejected', run_id: 'run-2', reason: '用户拒绝' };
    const unknown: RunResponse = { status: 'unknown', run_id: 'run-3', reason: '超时' };
    expect(receiptHeadline(rejected)).toContain('拒绝');
    expect(receiptHeadline(unknown)).toContain('人工对账');
    expect(resultExecutedAt(rejected)).toBe('');
  });
  it('does not infer an unchanged balance from a failed status alone', () => {
    const failed: RunResponse = { status: 'failed', run_id: 'run-failed', reason: '工具执行失败' };
    expect(receiptHeadline(failed)).toContain('核对');
    expect(receiptHeadline(failed)).not.toContain('未产生资金变动');
  });
});

describe('financial facts fail closed', () => {
  it('does not invent identifiers, numeric values or safe risk levels', () => {
    expect(() => normalizeBankingOverview({ accounts: [{}] })).toThrow();
    expect(() => normalizeBankingOverview({ accounts: [{ account_id: 'real' }] })).toThrow();
    expect(runRiskLevel({ status: 'completed', run_id: 'unknown-risk', reason: '' })).toBe('red');
  });
});
