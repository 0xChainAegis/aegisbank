import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchBreakerEvents,
  fetchBreakerPolicy,
  unlockBreaker,
} from '../api';
import type { AegisRole } from '../roles';
import { canUnlockBreaker } from '../roles';
import type { BreakerEvent, BreakerEventsResponse, BreakerPolicy, BreakerStatus } from '../types';
import {
  breakerEventLabel,
  breakerReason,
  breakerStateLabel,
  breakerTone,
  breakerTriggerLabel,
} from '../twoA';
import { formatDateTime, prettyEvidence } from '../viewModel';
import { PageAlerts, ResourceState, ToneChip } from './ui';

interface Props {
  writesBlocked: boolean;
  role: AegisRole;
  status: BreakerStatus | null;
  statusLoading: boolean;
  statusError: string;
  onRefreshStatus: () => void;
  onChanged: () => void;
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function eventCounts(events: BreakerEvent[]): Array<{ kind: string; count: number }> {
  const counts = new Map<string, number>();
  for (const event of events) {
    counts.set(event.kind, (counts.get(event.kind) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([kind, count]) => ({ kind, count }))
    .sort((left, right) => right.count - left.count || left.kind.localeCompare(right.kind));
}

export default function BreakerPanel({
  writesBlocked,
  role,
  status,
  statusLoading,
  statusError,
  onRefreshStatus,
  onChanged,
}: Props) {
  const [policy, setPolicy] = useState<BreakerPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [policyError, setPolicyError] = useState('');
  const [events, setEvents] = useState<BreakerEventsResponse | null>(null);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState('');
  const [unlockBusy, setUnlockBusy] = useState(false);
  const [unlockError, setUnlockError] = useState('');
  const [unlockNotice, setUnlockNotice] = useState('');

  const loadPolicy = useCallback(async () => {
    setPolicyLoading(true);
    setPolicyError('');
    try {
      setPolicy(await fetchBreakerPolicy());
    } catch (caught) {
      setPolicy(null);
      setPolicyError(messageOf(caught, '无法读取熔断策略'));
    } finally {
      setPolicyLoading(false);
    }
  }, []);

  const loadEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError('');
    try {
      setEvents(await fetchBreakerEvents(30));
    } catch (caught) {
      setEvents(null);
      setEventsError(messageOf(caught, '无法读取熔断事件'));
    } finally {
      setEventsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPolicy();
    void loadEvents();
  }, [loadEvents, loadPolicy, role]);

  const tone = breakerTone(status, statusError);
  const graph = useMemo(() => eventCounts(events?.events ?? []), [events]);
  const maxCount = Math.max(1, ...graph.map((item) => item.count));

  async function unlock() {
    if (unlockBusy || writesBlocked || !canUnlockBreaker(role)) return;
    setUnlockBusy(true);
    setUnlockError('');
    setUnlockNotice('');
    try {
      const result = await unlockBreaker();
      setUnlockNotice(result.reason || '熔断已解除。');
      await Promise.all([loadPolicy(), loadEvents()]);
      onRefreshStatus();
      onChanged();
    } catch (caught) {
      // Never hide a 403: the exact backend reason is the demo evidence.
      setUnlockError(messageOf(caught, '解除熔断失败'));
    } finally {
      setUnlockBusy(false);
    }
  }

  const unlockHint = writesBlocked ? '系统尚未就绪，写操作已暂停。' : canUnlockBreaker(role)
    ? '后端授予 ops:manage，解除结果会写入审计链。'
    : '后端未授予 ops:manage，解除操作已禁用。';

  return (
    <div className="breaker-panel">
      <div className="section-head compact-head">
        <div>
          <span className="eyebrow">CIRCUIT BREAKER · FAIL-CLOSED</span>
          <h2>异常熔断</h2>
        </div>
        <div className="panel-head-meta">
          <ToneChip tone={tone}>{breakerStateLabel(status)}</ToneChip>
          <button className="ghost-button small-button" onClick={onRefreshStatus} disabled={statusLoading}>
            {statusLoading ? '刷新中…' : '刷新状态'}
          </button>
        </div>
      </div>

      <p className="panel-note">
        状态来自 <code>GET /api/trust/circuit-breaker</code>；策略与事件来自
        <code> /api/trust/breaker/policy</code>、<code>/api/trust/breaker/events</code>。
        熔断打开时，写操作统一返回 blocked，不会伪装成功。
      </p>

      <PageAlerts error={unlockError} notice={unlockNotice} />

      <ResourceState
        loading={statusLoading}
        error={statusError}
        empty={!status}
        emptyText="尚未返回熔断状态。"
        onRetry={onRefreshStatus}
      >
        {status && (
          <>
            <div className={`breaker-state-banner ${status.open ? 'is-open' : 'is-closed'}`}>
              <ToneChip tone={tone}>{status.open ? 'OPEN' : 'CLOSED'}</ToneChip>
              <div>
                <strong>{breakerReason(status)}</strong>
                <small>
                  触发规则：{breakerTriggerLabel(status)}
                  {status.opened_at ? ` · 打开于 ${formatDateTime(status.opened_at)}` : ''}
                  {status.retry_after_seconds > 0 ? ` · ${status.retry_after_seconds} 秒后自动冷却` : ''}
                </small>
              </div>
            </div>
            <dl className="trust-facts breaker-facts">
              <div>
                <dt>连续失败</dt>
                <dd>{status.failures} / {status.threshold}</dd>
              </div>
              <div>
                <dt>红色操作（窗口内）</dt>
                <dd>
                  {status.suspicious?.red_events ?? 0} / {status.suspicious?.red_threshold ?? '—'}
                </dd>
              </div>
              <div>
                <dt>注入命中（窗口内）</dt>
                <dd>
                  {status.suspicious?.injection_events ?? 0} / {status.suspicious?.injection_threshold ?? '—'}
                </dd>
              </div>
              <div>
                <dt>失败窗口</dt>
                <dd>{status.window_seconds} 秒</dd>
              </div>
              <div>
                <dt>锁定冷却</dt>
                <dd>{status.lock_seconds} 秒</dd>
              </div>
              <div>
                <dt>自动冷却</dt>
                <dd>{status.cooled_down ? '刚刚冷却' : status.retry_after_seconds > 0 ? `${status.retry_after_seconds} 秒` : '—'}</dd>
              </div>
            </dl>
          </>
        )}
      </ResourceState>

      <div className="breaker-actions card-inset">
        <div>
          <strong>解除熔断</strong>
          <small>{unlockHint}</small>
        </div>
        <button
          className="danger-button small-button"
          onClick={() => void unlock()}
          disabled={unlockBusy || writesBlocked || !canUnlockBreaker(role)}
          title={role === 'auditor' ? '审计员只读，不能解除熔断' : 'POST /api/trust/breaker/unlock'}
        >
          {unlockBusy ? '解除中…' : '解除熔断'}
        </button>
      </div>

      <div className="breaker-columns">
        <section className="breaker-section">
          <div className="section-head compact-head">
            <div>
              <span className="eyebrow">POLICY</span>
              <h3>熔断策略</h3>
            </div>
            <button className="text-button" onClick={() => void loadPolicy()} disabled={policyLoading}>
              {policyLoading ? '同步中…' : '刷新'}
            </button>
          </div>
          <ResourceState
            loading={policyLoading}
            error={policyError}
            empty={!policy}
            emptyText="尚未返回熔断策略。"
            onRetry={() => void loadPolicy()}
          >
            {policy && (
              <>
                <ul className="policy-rules">
                  {Object.entries(policy.thresholds).map(([key, item]) => (
                    <li key={key}>
                      <span>{item.label}</span>
                      <strong>{item.threshold} 次</strong>
                      <small>{item.window_seconds} 秒窗口</small>
                    </li>
                  ))}
                </ul>
                <ul className="breaker-rule-list">
                  {policy.rules.map((rule) => <li key={rule}>{rule}</li>)}
                </ul>
                <div className="breaker-recovery">
                  <span>自动：{policy.recovery.auto}</span>
                  <span>人工：{policy.recovery.manual}</span>
                </div>
              </>
            )}
          </ResourceState>
        </section>

        <section className="breaker-section">
          <div className="section-head compact-head">
            <div>
              <span className="eyebrow">EVENTS</span>
              <h3>最近熔断事件</h3>
            </div>
            <button className="text-button" onClick={() => void loadEvents()} disabled={eventsLoading}>
              {eventsLoading ? '同步中…' : '刷新'}
            </button>
          </div>
          <ResourceState
            loading={eventsLoading}
            error={eventsError}
            empty={!events || events.events.length === 0}
            emptyText="暂无熔断事件：尚未发生连续失败、可疑红色操作或注入命中。"
            onRetry={() => void loadEvents()}
          >
            {events && events.events.length > 0 && (
              <>
                <div className="breaker-graph" aria-label="熔断事件类型分布">
                  {graph.map((item) => (
                    <div className="breaker-bar" key={item.kind}>
                      <span>{breakerEventLabel(item.kind)}</span>
                      <div className="bar-track">
                        <span className="bar-fill" style={{ width: `${(item.count / maxCount) * 100}%` }} />
                      </div>
                      <strong>{item.count}</strong>
                    </div>
                  ))}
                </div>
                <ul className="breaker-events">
                  {events.events.map((event, index) => (
                    <li key={event.id ?? `${event.created_at}-${index}`}>
                      <div className="breaker-event-head">
                        <ToneChip tone={event.kind === 'circuit_open' ? 'bad' : event.kind === 'reset' ? 'good' : 'neutral'}>
                          {breakerEventLabel(event.kind)}
                        </ToneChip>
                        <span>{formatDateTime(event.created_at)}</span>
                        <code>{event.user_id}</code>
                      </div>
                      <pre>{prettyEvidence(event.detail)}</pre>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </ResourceState>
        </section>
      </div>
    </div>
  );
}