import type { BreakerStatus } from '../types';
import { breakerReason } from '../twoA';
import { formatDateTime } from '../viewModel';

interface Props {
  status: BreakerStatus | null;
  loading: boolean;
  error: string;
  onOpenOps: () => void;
  onRetry: () => void;
}

export default function BreakerBanner({
  status,
  loading,
  error,
  onOpenOps,
  onRetry,
}: Props) {
  if (!status?.open && !error) return null;

  const open = Boolean(status?.open);
  return (
    <section
      className={`breaker-banner ${open ? 'is-open' : 'is-error'}`}
      role="alert"
      aria-live="polite"
      aria-label="执行熔断状态"
    >
      <span className="breaker-banner-dot" aria-hidden="true" />
      <div className="breaker-banner-copy">
        <strong>{open ? '执行熔断已触发 · 写操作 fail-closed' : '无法确认熔断状态'}</strong>
        <span>{breakerReason(status, error)}</span>
        {open && status && (
          <small>
            触发规则：{status.trigger_label ?? status.trigger ?? '—'}
            {status.retry_after_seconds > 0 ? ` · ${status.retry_after_seconds} 秒后自动冷却` : ''}
            {status.opened_at ? ` · 打开于 ${formatDateTime(status.opened_at)}` : ''}
          </small>
        )}
      </div>
      <div className="breaker-banner-actions">
        <button className="ghost-button small-button" onClick={onOpenOps}>
          前往运维面板
        </button>
        <button className="text-button" onClick={onRetry} disabled={loading}>
          {loading ? '检查中…' : '重新检查'}
        </button>
      </div>
    </section>
  );
}