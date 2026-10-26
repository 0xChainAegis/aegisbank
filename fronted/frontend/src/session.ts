/**
 * 待确认动作的会话快照（UX-17）。
 *
 * 之前 pending / lastRun 只活在 App 的内存 state 里，刷新即丢失，而后端动作仍在
 * AWAITING_CONFIRMATION。这里把「待确认的 RunResponse + 原始指令」写进
 * sessionStorage，刷新后由 App 恢复成一条可继续/可放弃的横幅。
 */

import type { AgentRunInput, RunResponse } from './types';
import type { AegisRole } from './roles';

export const PENDING_STORAGE_KEY = 'aegisbank.pending.v1';
export const SUBMISSION_STORAGE_KEY = 'aegisbank.submission.v1';

export interface SubmissionSnapshot {
  key: string;
  input: AgentRunInput;
  role: AegisRole;
}

export interface PendingSnapshot {
  pending: RunResponse;
  instruction: string;
  savedAt: string;
}

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function defaultStorage(): StorageLike | null {
  try {
    if (typeof window === 'undefined' || !window.sessionStorage) return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function isValidSnapshot(value: unknown): value is PendingSnapshot {
  if (value === null || typeof value !== 'object') return false;
  const record = value as Partial<PendingSnapshot>;
  const pending = record.pending as Partial<RunResponse> | undefined;
  if (!pending || typeof pending !== 'object') return false;
  const confirmation = pending.confirmation;
  if (!confirmation || typeof confirmation.id !== 'string' || !confirmation.id) return false;
  if (typeof pending.status !== 'string') return false;
  return typeof record.instruction === 'string' && typeof record.savedAt === 'string';
}

export function savePendingSnapshot(
  snapshot: PendingSnapshot,
  storage: StorageLike | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    const previous = loadPendingSnapshots(storage).filter(
      (item) => item.pending.confirmation?.id !== snapshot.pending.confirmation?.id,
    );
    storage.setItem(PENDING_STORAGE_KEY, JSON.stringify([...previous, snapshot]));
  } catch {
    // 隐私模式或配额不足：静默降级为不持久化，不影响主流程。
  }
}

export function loadPendingSnapshot(
  storage: StorageLike | null = defaultStorage(),
): PendingSnapshot | null {
  return loadPendingSnapshots(storage)[0] ?? null;
}

export function loadPendingSnapshots(
  storage: StorageLike | null = defaultStorage(),
): PendingSnapshot[] {
  if (!storage) return [];
  try {
    const raw = storage.getItem(PENDING_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return (Array.isArray(parsed) ? parsed : [parsed]).filter(isValidSnapshot);
  } catch {
    return [];
  }
}

export function removePendingSnapshot(actionId: string, storage = defaultStorage()): void {
  if (!storage) return;
  try {
    const remaining = loadPendingSnapshots(storage).filter(
      (item) => item.pending.confirmation?.id !== actionId,
    );
    if (remaining.length) storage.setItem(PENDING_STORAGE_KEY, JSON.stringify(remaining));
    else storage.removeItem(PENDING_STORAGE_KEY);
  } catch { /* storage may be disabled */ }
}

/** Must succeed before sending a write so a reload can recover its original key. */
export function saveSubmission(snapshot: SubmissionSnapshot, storage = defaultStorage()): void {
  if (!storage) throw new Error('会话存储不可用，无法保存请求凭据，已停止提交。');
  storage.setItem(SUBMISSION_STORAGE_KEY, JSON.stringify(snapshot));
}

export function loadSubmission(storage = defaultStorage()): SubmissionSnapshot | null {
  if (!storage) return null;
  try {
    const value = JSON.parse(storage.getItem(SUBMISSION_STORAGE_KEY) ?? 'null');
    return value && typeof value.key === 'string' && value.key.length > 0 &&
      ['user', 'operator', 'auditor'].includes(value.role) &&
      value.input && typeof value.input.instruction === 'string' ? value : null;
  } catch { return null; }
}

export function clearSubmission(storage = defaultStorage()): void {
  storage?.removeItem(SUBMISSION_STORAGE_KEY);
}

export function clearPendingSnapshot(storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(PENDING_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function snapshotExpiryMs(snapshot: PendingSnapshot): number {
  const expiresAt = snapshot.pending.confirmation?.expires_at;
  if (!expiresAt) return 0;
  const parsed = Date.parse(expiresAt);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function remainingSeconds(
  expiresAt: string | undefined,
  now: number = Date.now(),
): number {
  if (!expiresAt) return 0;
  const parsed = Date.parse(expiresAt);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.round((parsed - now) / 1000));
}

/** 倒计时展示：4:32 / 0:09；超过 1 小时显示 1:02:03。 */
export function formatRemaining(totalSeconds: number): string {
  const safe = Math.max(0, Math.trunc(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  const pad = (value: number) => String(value).padStart(2, '0');
  if (hours > 0) return `${hours}:${pad(minutes)}:${pad(seconds)}`;
  return `${minutes}:${pad(seconds)}`;
}

export function isSnapshotExpired(
  snapshot: PendingSnapshot,
  now: number = Date.now(),
): boolean {
  const expiry = snapshotExpiryMs(snapshot);
  return expiry > 0 && expiry <= now;
}
