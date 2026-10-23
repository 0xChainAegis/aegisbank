import { describe, expect, it } from 'vitest';
import type { RunResponse } from './types';
import {
  PENDING_STORAGE_KEY,
  clearPendingSnapshot,
  formatRemaining,
  isSnapshotExpired,
  loadPendingSnapshot,
  remainingSeconds,
  savePendingSnapshot,
  type PendingSnapshot,
  type StorageLike,
} from './session';

function memoryStorage(initial: Record<string, string> = {}): StorageLike {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => map.set(key, value),
    removeItem: (key) => map.delete(key),
  };
}

function snapshot(expiresAt: string): PendingSnapshot {
  const pending: RunResponse = {
    status: 'awaiting_confirmation',
    run_id: 'run-1',
    reason: '等待人工确认',
    confirmation: {
      id: 'cfm_123',
      requires_reauth: false,
      expires_at: expiresAt,
    },
  };
  return { pending, instruction: '取消异常订阅', savedAt: new Date().toISOString() };
}

describe('pending snapshot (UX-17)', () => {
  it('round-trips a pending confirmation through sessionStorage-like storage', () => {
    const storage = memoryStorage();
    const saved = snapshot(new Date(Date.now() + 300_000).toISOString());
    savePendingSnapshot(saved, storage);
    expect(storage.getItem(PENDING_STORAGE_KEY)).toBeTruthy();

    const restored = loadPendingSnapshot(storage);
    expect(restored?.pending.confirmation?.id).toBe('cfm_123');
    expect(restored?.instruction).toBe('取消异常订阅');
  });

  it('drops malformed or incomplete snapshots instead of crashing', () => {
    const broken = memoryStorage({ [PENDING_STORAGE_KEY]: '{not-json' });
    expect(loadPendingSnapshot(broken)).toBeNull();

    const missingConfirmation = memoryStorage({
      [PENDING_STORAGE_KEY]: JSON.stringify({ pending: { status: 'x' }, instruction: 'i', savedAt: 's' }),
    });
    expect(loadPendingSnapshot(missingConfirmation)).toBeNull();
  });

  it('clears the snapshot after a decision', () => {
    const storage = memoryStorage();
    savePendingSnapshot(snapshot(new Date(Date.now() + 300_000).toISOString()), storage);
    clearPendingSnapshot(storage);
    expect(loadPendingSnapshot(storage)).toBeNull();
  });
});

describe('confirmation countdown (UX-16)', () => {
  it('formats the remaining time as mm:ss and clamps at zero', () => {
    expect(formatRemaining(272)).toBe('4:32');
    expect(formatRemaining(9)).toBe('0:09');
    expect(formatRemaining(-5)).toBe('0:00');
    expect(formatRemaining(3723)).toBe('1:02:03');
  });

  it('computes remaining seconds against a fixed clock', () => {
    const now = Date.parse('2026-10-23T08:00:00+00:00');
    const expires = '2026-10-23T08:05:00+00:00';
    expect(remainingSeconds(expires, now)).toBe(300);
    expect(remainingSeconds(expires, now + 300_000)).toBe(0);
  });

  it('marks expired snapshots so the UI can stop accepting decisions', () => {
    const expired = snapshot('2026-10-23T08:05:00+00:00');
    expect(isSnapshotExpired(expired, Date.parse('2026-10-23T08:06:00+00:00'))).toBe(true);
    expect(isSnapshotExpired(expired, Date.parse('2026-10-23T08:04:00+00:00'))).toBe(false);
  });
});
