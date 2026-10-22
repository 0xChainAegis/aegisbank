import type { ReactNode } from 'react';
import { riskLabels, riskShortLabels } from '../risk';
import type { RiskLevel, RunStatus } from '../types';
import { statusLabels } from '../viewModel';

export function RiskBadge({ risk, verbose = false }: { risk: RiskLevel; verbose?: boolean }) {
  return (
    <span className={`risk-badge risk-${risk}`} title={riskLabels[risk]}>
      {verbose ? `${risk.toUpperCase()} · ${riskShortLabels[risk]}` : risk.toUpperCase()}
    </span>
  );
}

export function StatusPill({ status }: { status: RunStatus | string }) {
  return (
    <span className={`status-pill status-${status}`}>{statusLabels[status] ?? status}</span>
  );
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
