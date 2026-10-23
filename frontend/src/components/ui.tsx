import type { ReactNode } from 'react';
import { riskLabels, riskShortLabels } from '../risk';
import type { EvidenceItem, RiskLevel, RunStatus } from '../types';
import {
  evidenceSourceLabel,
  normalizeEvidence,
  statusLabel,
} from '../viewModel';

export function RiskBadge({ risk, verbose = false }: { risk: RiskLevel; verbose?: boolean }) {
  return (
    <span className={`risk-badge risk-${risk}`} title={riskLabels[risk]}>
      {verbose ? `${risk.toUpperCase()} · ${riskShortLabels[risk]}` : risk.toUpperCase()}
    </span>
  );
}

export function StatusPill({ status }: { status: RunStatus | string }) {
  return (
    <span className={`status-pill status-${status}`}>{statusLabel(status)}</span>
  );
}

/** Layered evidence badges: mock data / human confirmation / policy / audit chain. */
export function EvidenceBadges({
  evidence,
  emptyHint,
}: {
  evidence?: EvidenceItem[] | null;
  emptyHint?: string;
}) {
  const items = normalizeEvidence(evidence ?? []);
  if (items.length === 0) {
    return emptyHint ? <span className="evidence-empty">{emptyHint}</span> : null;
  }
  return (
    <div className="evidence-badges" aria-label="证据分层">
      {items.map((item) => (
        <span
          key={`${item.source}-${item.verified}-${item.detail ?? ''}`}
          className={`evidence-badge evidence-${item.source}`}
          title={item.detail || evidenceSourceLabel(item.source)}
        >
          <span className="evidence-source">{evidenceSourceLabel(item.source)}</span>
          <span
            className={`evidence-verified ${item.verified ? 'is-verified' : 'is-unverified'}`}
          >
            {item.verified ? 'verified' : 'unverified'}
          </span>
        </span>
      ))}
    </div>
  );
}

/** Shared loading / error / empty fallback for a single read-only data area. */
export function ResourceState({
  loading,
  error,
  empty,
  emptyText,
  onRetry,
  children,
}: {
  loading: boolean;
  error: string;
  empty: boolean;
  emptyText: string;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <div className="inline-loading" role="status" aria-live="polite">
        <span className="loading-spinner" aria-hidden="true" />
        <span>正在加载数据…</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="inline-error" role="alert">
        <span>{error}</span>
        {onRetry && (
          <button className="text-button" onClick={onRetry}>
            重试
          </button>
        )}
      </div>
    );
  }
  if (empty) {
    return <div className="inline-empty">{emptyText}</div>;
  }
  return <>{children}</>;
}

export function LoadingState({ label = '正在加载数据…' }: { label?: string }) {
  return (
    <div className="loading-state card" role="status" aria-live="polite">
      <span className="loading-spinner" aria-hidden="true" />
      <div>
        <strong>{label}</strong>
        <small>正在从受控 API 获取最新状态</small>
      </div>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state card">{children}</div>;
}

export function PageAlerts({ error, notice }: { error?: string; notice?: string }) {
  return (
    <>
      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="alert alert-info" role="status">
          {notice}
        </div>
      )}
    </>
  );
}
