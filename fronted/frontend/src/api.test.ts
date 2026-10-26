import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchBankingOverview, runAgent } from './api';

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
});
