import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchBankingOverview, previewPlan, runAgent } from './api';
import type { PlanPreviewResponse } from './types';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('API response boundaries', () => {
  it('keeps its timeout active while waiting for the response body', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(async (_url, init: RequestInit) => ({
      ok: true,
      json: () => new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      }),
    })));
    const result = runAgent({ instruction: '查询余额' }).catch(error => error);
    await vi.advanceTimersByTimeAsync(30_001);
    expect(await result).toMatchObject({ status: 0 });
  });
  it('rejects malformed JSON rather than constructing an empty success response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => { throw new SyntaxError('bad JSON'); } })));
    await expect(runAgent({ instruction: '查询余额' })).rejects.toMatchObject({ status: 0 });
  });
  it.each([403, 422, 503])('preserves HTTP %s when an error response is not JSON', async (status) => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status,
      json: async () => { throw new SyntaxError('HTML error page'); },
    })));
    await expect(runAgent({ instruction: '查询余额' })).rejects.toMatchObject({ status });
  });
  it('rejects missing financial facts instead of displaying a made-up zero balance', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ accounts: [{}] }) })));
    await expect(fetchBankingOverview()).rejects.toThrow('账户标识缺失');
  });

  it('preserves structured 409 idempotency errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          code: 'IDEMPOTENCY_KEY_REUSED',
          message: '同一个 Idempotency-Key 携带了不同的请求内容，拒绝处理。',
        },
      }),
    })));
    await expect(runAgent({ instruction: '查询余额' })).rejects.toMatchObject({
      status: 409,
      code: 'IDEMPOTENCY_KEY_REUSED',
    });
  });
  it('preserves structured 503 readiness errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({
        detail: '系统未就绪，写操作已按 fail closed 拒绝（sqlite: 模拟 SQLite 未就绪）。',
      }),
    })));
    await expect(runAgent({ instruction: '查询余额' })).rejects.toMatchObject({
      status: 503,
      message: '系统未就绪，写操作已按 fail closed 拒绝（sqlite: 模拟 SQLite 未就绪）。',
    });
  });

  it('returns the planner preview envelope with its nested plan and risk', async () => {
    const payload: PlanPreviewResponse = {
      status: 'planned',
      reason: '计划已通过校验，尚未执行。',
      risk_level: 'yellow',
      risk: { level: 'yellow', reasons: ['需要黄色操作确认。'] },
      plan: {
        intent: 'transfer', planner: 'rule', confidence: 0.93, assumptions: [],
        plan_hash: 'preview-hash',
        steps: [{
          id: 'step-1', tool_name: 'transfer', depends_on: [],
          arguments: { from_account: 'ACC-1001', to_account: 'ACC-2002', amount_cny: 880 },
        }],
      },
    };
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true, json: async () => payload,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await previewPlan({ instruction: '向 ACC-2002 转账 880 元' });
    expect(result.status).toBe('planned');
    if (result.status !== 'planned') throw new Error('Expected a planned preview');
    expect(result.plan.steps[0].arguments.amount_cny).toBe(880);
    expect(result.risk_level).toBe('yellow');
    expect(result.risk?.reasons).toEqual(['需要黄色操作确认。']);
    expect(result).not.toHaveProperty('run_id');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/planner/plan', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ user_id: 'demo-user', instruction: '向 ACC-2002 转账 880 元' }),
    }));
  });

  it('preserves a clarification preview with empty steps instead of treating it as execution', async () => {
    const clarification = '当前无法完整执行条件任务，请明确后再执行。';
    const payload: PlanPreviewResponse = {
      status: 'needs_clarification', reason: clarification,
      plan: {
        intent: 'unsupported_condition', planner: 'safety', confidence: 0,
        assumptions: [], steps: [], needs_clarification: true, clarification,
      },
    };
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true, json: async () => payload,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await previewPlan({ instruction: '如果余额超过1000元，就给妈妈转500元' });
    expect(result.status).toBe('needs_clarification');
    if (result.status !== 'needs_clarification') throw new Error('Expected clarification');
    expect(result.plan.steps).toEqual([]);
    expect(result.plan.clarification).toBe(clarification);
    expect(result.reason).toBe(clarification);
    expect(result).not.toHaveProperty('run_id');
    expect(result).not.toHaveProperty('confirmation');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/planner/plan');
  });
});
