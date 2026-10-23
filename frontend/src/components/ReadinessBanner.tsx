import type { ReadinessSnapshot } from '../types';
import {
  readinessBlockers,
  readinessComponentLabel,
  readinessComponentOrder,
  readinessStatusLabel,
} from '../viewModel';

interface Props {
  snapshot: ReadinessSnapshot | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
}

type Tone = 'ok' | 'warn' | 'bad' | 'pending';

export default function ReadinessBanner({ snapshot, loading, error, onRefresh }: Props) {
  const status = snapshot?.status ?? null;
  const tone: Tone = error
    ? 'bad'
    : status === 'ready'
      ? 'ok'
      : status === 'degraded'
        ? 'warn'
        : status === 'not_ready'
          ? 'bad'
          : 'pending';

  const reasons = error ? [error] : readinessBlockers(snapshot);
  const blocked = tone !== 'ok';
  const title = error
    ? '无法确认系统就绪状态'
    : status
      ? readinessStatusLabel(status)
      : '正在检查系统就绪状态';

  const summary = error
    ? '就绪检查请求失败，已按 fail-closed 处理。'
    : status === 'ready'
      ? '关键依赖全部通过检查，写操作可用。'
      : status === 'degraded'
        ? '部分非关键依赖不可用，写操作按 fail-closed 拒绝。'
        : status === 'not_ready'
          ? '存在不可用的关键依赖，写操作已按 fail-closed 拒绝。'
          : '首次加载中…';

  return (
    <section
      className={`readiness-banner readiness-${tone}`}
      aria-live="polite"
      aria-label="系统就绪状态"
    >
      <div className="readiness-head">
        <span className="readiness-dot" aria-hidden="true" />
        <strong>{title}</strong>
        <span className="readiness-code">{error ? 'error' : status ?? 'checking'}</span>
        <span className="readiness-summary">{summary}</span>
        <button className="text-button readiness-refresh" onClick={onRefresh} disabled={loading}>
          {loading ? '检查中…' : '重新检查'}
        </button>
      </div>

      <div className="readiness-components">
        {readinessComponentOrder.map((name) => {
          const component = snapshot?.components[name];
          const ok = component?.ok === true;
          return (
            <span
              key={name}
              className={`readiness-chip ${ok ? 'is-ok' : component ? 'is-bad' : 'is-missing'}`}
              title={component?.detail || (component ? '检查未通过' : '尚未返回该组件状态')}
            >
              <i aria-hidden="true" />
              {readinessComponentLabel(name)}
              <span className="readiness-chip-state">
                {ok ? 'OK' : component ? 'FAIL' : '—'}
              </span>
            </span>
          );
        })}
      </div>

      {reasons.length > 0 && (
        <p className="readiness-reasons">{reasons.join('；')}</p>
      )}
      {blocked && (
        <p className="readiness-blocked">
          写操作已按 fail-closed 禁用：任务提交、人工确认、时间快进在系统就绪前不可用。
        </p>
      )}
    </section>
  );
}
