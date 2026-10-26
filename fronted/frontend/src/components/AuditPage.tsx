import { useEffect, useMemo, useState } from 'react';
import type { AegisRole } from '../roles';
import { isReadOnlyRole, ROLE_LABELS } from '../roles';
import type { AuditEntry } from '../types';
import {
  eventDescription,
  isTwoAEvent,
  TWO_A_EVENT_CODES,
} from '../twoA';
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
  role: AegisRole;
  audit: AuditEntry[];
  auditValid: boolean | null;
  auditChecked: number;
  /** 从回执跳转时携带的筛选词（通常是本次任务的原始指令），用于定位相关记录。 */
  initialQuery?: string;
  /** 校验请求本身失败（无法判断链状态），与「尚未校验」区分开（UX-25）。 */
  verifyError?: string;
  loading: boolean;
  error: string;
  notice: string;
  onRefresh: () => void;
}

export default function AuditPage({
  role,
  audit,
  auditValid,
  auditChecked,
  initialQuery = '',
  verifyError = '',
  loading,
  error,
  notice,
  onRefresh,
}: Props) {
  const [query, setQuery] = useState(initialQuery);

  useEffect(() => {
    if (initialQuery) setQuery(initialQuery);
  }, [initialQuery]);
  const entries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return audit;
    return audit.filter((entry) =>
      [entry.run_id, entry.instruction, entry.tool_name, entry.event, entry.dag_path, entry.entry_hash]
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
          <span className="role-pill">当前角色 {ROLE_LABELS[role]} · audit:read</span>
        </div>
        <div className={`chain-seal ${verifyError || auditValid === false ? 'seal-bad' : auditValid === null ? 'seal-pending' : ''}`}>
          <span>{verifyError || auditValid === false ? '!' : auditValid === null ? '…' : '✓'}</span>
          <div>
            <strong>
              {verifyError
                ? '哈希链校验失败'
                : auditValid === false
                  ? '哈希链异常'
                  : auditValid === null
                    ? '哈希链待校验'
                    : '哈希链完整'}
            </strong>
            <small>
              {verifyError
                ? verifyError
                : auditChecked
                  ? `已校验 ${auditChecked} 条记录`
                  : `${audit.length} 条记录已加载`}
            </small>
          </div>
        </div>
      </div>

      <PageAlerts error={error} notice={notice} />

      {isReadOnlyRole(role) && (
        <div className="alert alert-info auditor-banner" role="status">
          审计员只读视角：审计日志是只追加的 SHA-256 哈希链，任何角色都不能通过 API 修改或删除已有条目；
          本页只展示读取、校验与证据分层结果。
        </div>
      )}

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
                <strong title={eventDescription(entry.event)}>
                  {eventLabels[entry.event] ?? entry.event}
                  {isTwoAEvent(entry.event) && <span className="chip chip-teal two-a-chip">2A</span>}
                </strong>
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
                  {eventDescription(entry.event) && (
                    <div className="detail-wide">
                      <dt>事件说明</dt>
                      <dd>{eventDescription(entry.event)}</dd>
                    </div>
                  )}
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

      <details className="event-legend card">
        <summary className="section-head compact-head">
          <div>
            <span className="eyebrow">EVENT GLOSSARY</span>
            <h2>事件说明（点击展开）</h2>
          </div>
          <span className="muted">补偿 / MFA / 沙箱 / 熔断 / IM / 撤权</span>
        </summary>
        <div className="event-legend-grid">
          {TWO_A_EVENT_CODES.map((code) => (
            <div className="event-legend-item" key={code}>
              <div className="event-legend-head">
                <strong>{eventLabels[code] ?? code}</strong>
                <code>{code}</code>
              </div>
              <p>{eventDescription(code)}</p>
            </div>
          ))}
        </div>
      </details>

      <div className="policy-note card">
        <span className="eyebrow">EVIDENCE READABILITY</span>
        <div>
          审计详情同时保留结构化字段与原始证据；哈希列展示前序哈希与当前条目哈希。
          任意条目内容发生变化，审计链校验都会失败。证据分层徽标复用同一套
          source / verified / verification_kind 语义。
        </div>
      </div>
    </section>
  );
}