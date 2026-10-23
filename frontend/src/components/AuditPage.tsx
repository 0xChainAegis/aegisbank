import { useMemo, useState } from 'react';
import type { AuditEntry } from '../types';
import {
  argumentLabels,
  confirmationLabels,
  eventLabels,
  formatDateTime,
  formatDisplayValue,
  prettyEvidence,
} from '../viewModel';
import { EmptyState, EvidenceBadges, LoadingState, PageAlerts, RiskBadge } from './ui';

interface Props {
  audit: AuditEntry[];
  auditValid: boolean | null;
  auditChecked: number;
  loading: boolean;
  error: string;
  notice: string;
  onRefresh: () => void;
}

export default function AuditPage({
  audit,
  auditValid,
  auditChecked,
  loading,
  error,
  notice,
  onRefresh,
}: Props) {
  const [query, setQuery] = useState('');
  const entries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return audit;
    return audit.filter((entry) =>
      [entry.instruction, entry.tool_name, entry.event, entry.dag_path, entry.entry_hash]
        .join(' ')
        .toLowerCase()
        .includes(keyword),
    );
  }, [audit, query]);

  if (loading && audit.length === 0) {
    return (
      <section className="page-stack">
        <div className="page-heading">
          <span className="eyebrow">TAMPER-EVIDENT ACTIVITY LOG</span>
          <h1>操作审计</h1>
          <p>每一条记录都包含触发时间、原始指令、DAG 路径、工具入参、执行结果和确认状态。</p>
        </div>
        <LoadingState label="正在校验审计哈希链…" />
      </section>
    );
  }

  return (
    <section className="page-stack audit-page">
      <div className="page-heading audit-heading">
        <div>
          <span className="eyebrow">TAMPER-EVIDENT ACTIVITY LOG</span>
          <h1>操作审计</h1>
          <p>时间线记录每一次计划、确认、执行与拦截。原始证据保留在可展开的详情中，便于逐项复核。</p>
        </div>
        <div className={`chain-seal ${auditValid === false ? 'seal-bad' : auditValid === null ? 'seal-pending' : ''}`}>
          <span>{auditValid === false ? '!' : auditValid === null ? '…' : '✓'}</span>
          <div>
            <strong>
              {auditValid === false ? '哈希链异常' : auditValid === null ? '哈希链待校验' : '哈希链完整'}
            </strong>
            <small>{auditChecked ? `已校验 ${auditChecked} 条记录` : `${audit.length} 条记录已加载`}</small>
          </div>
        </div>
      </div>

      <PageAlerts error={error} notice={notice} />

      <div className="audit-toolbar card">
        <label className="search-field">
          <span className="sr-only">搜索审计记录</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索指令、工具、DAG 路径或哈希…"
          />
        </label>
        <div className="audit-toolbar-meta">
          <span>{entries.length} / {audit.length} 条记录</span>
          <button className="ghost-button" onClick={onRefresh} disabled={loading}>
            {loading ? '校验中…' : '刷新并重新校验'}
          </button>
        </div>
      </div>

      {entries.length === 0 ? (
        <EmptyState>{audit.length === 0 ? '还没有审计记录，先发起一项任务。' : '没有匹配的审计记录。'}</EmptyState>
      ) : (
        <div className="audit-list">
          {entries.map((entry) => (
            <details className="audit-entry card" key={entry.id}>
              <summary>
                <span className="timeline-dot" aria-hidden="true" />
                <span className="audit-id">#{String(entry.id).padStart(3, '0')}</span>
                <RiskBadge risk={entry.risk_level} />
                <strong>{eventLabels[entry.event] ?? entry.event}</strong>
                <span className="audit-tool">{entry.tool_name}</span>
                <span className="audit-instruction-preview">{entry.instruction}</span>
                <span className="audit-time">{formatDateTime(entry.created_at)}</span>
                <span className="audit-chevron">⌄</span>
              </summary>
              <div className="audit-body">
                <dl>
                  <div>
                    <dt>触发时间</dt>
                    <dd>{formatDateTime(entry.created_at)}</dd>
                  </div>
                  <div>
                    <dt>用户</dt>
                    <dd>{entry.user_id}</dd>
                  </div>
                  <div className="detail-wide">
                    <dt>用户原始指令</dt>
                    <dd>{entry.instruction}</dd>
                  </div>
                  <div className="detail-wide">
                    <dt>DAG 路径</dt>
                    <dd><code>{entry.dag_path || '—'}</code></dd>
                  </div>
                  <div>
                    <dt>工具</dt>
                    <dd><code>{entry.tool_name}</code></dd>
                  </div>
                  <div>
                    <dt>确认状态</dt>
                    <dd>{confirmationLabels[entry.confirmation_state] ?? entry.confirmation_state}</dd>
                  </div>
                  <div className="detail-wide">
                    <dt>工具入参</dt>
                    <dd>
                      <div className="argument-pills">
                        {Object.entries(entry.arguments).map(([key, value]) => (
                          <span key={key}>
                            {argumentLabels[key] ?? key}: {formatDisplayValue(value)}
                          </span>
                        ))}
                        {Object.keys(entry.arguments).length === 0 && <span>无入参</span>}
                      </div>
                    </dd>
                  </div>
                  <div className="detail-wide">
                    <dt>证据分层</dt>
                    <dd>
                      <EvidenceBadges evidence={entry.evidence} emptyHint="该记录没有分层证据。" />
                    </dd>
                  </div>
                  <div className="detail-wide">
                    <dt>执行结果 / 原始证据</dt>
                    <dd><pre className="evidence-block">{prettyEvidence(entry.result)}</pre></dd>
                  </div>
                  <div className="detail-wide hash-chain-row">
                    <div>
                      <dt>Prev hash</dt>
                      <dd><code className="hash">{entry.prev_hash || 'GENESIS'}</code></dd>
                    </div>
                    <div>
                      <dt>Entry hash</dt>
                      <dd><code className="hash">{entry.entry_hash}</code></dd>
                    </div>
                  </div>
                </dl>
              </div>
            </details>
          ))}
        </div>
      )}

      <div className="policy-note card">
        <span className="eyebrow">EVIDENCE READABILITY</span>
        <div>
          审计详情同时保留结构化字段与 raw evidence。哈希列展示前序哈希与当前条目哈希，任意条目内容变化都会导致
          <code>/api/audit/verify</code> 校验失败。
        </div>
      </div>
    </section>
  );
}
