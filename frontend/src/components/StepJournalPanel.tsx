import { useCallback, useEffect, useMemo, useState } from 'react';
import { pauseAction, resumeAction, rollbackAction, fetchActionJournal } from '../api';
import type { AegisRole } from '../roles';
import type { ActionJournal, RunResponse } from '../types';
import {
  compensationStatusDescription,
  compensationStatusLabel,
  journalPhaseLabel,
  journalPhaseTone,
  summarizeJournal,
} from '../twoA';
import { formatDateTime, prettyEvidence, statusLabel } from '../viewModel';
import { PageAlerts, ResourceState, StatusPill, ToneChip } from './ui';

interface Props {
  actionId: string;
  role: AegisRole;
  run: RunResponse | null;
  writesBlocked: boolean;
  blockReason: string;
  onChanged: (journal: ActionJournal, response: unknown) => void;
}

type JournalAction = 'pause' | 'resume' | 'rollback';

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export default function StepJournalPanel({
  actionId,
  role,
  run,
  writesBlocked,
  blockReason,
  onChanged,
}: Props) {
  const [journal, setJournal] = useState<ActionJournal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyAction, setBusyAction] = useState<JournalAction | ''>('');
  const [actionError, setActionError] = useState('');
  const [actionNotice, setActionNotice] = useState('');

  // Re-read after a confirmation changes the same action from pending to executed.
  const runStatus = run?.status ?? '';

  const loadJournal = useCallback(async (): Promise<ActionJournal | null> => {
    setLoading(true);
    setError('');
    try {
      const next = await fetchActionJournal(actionId);
      setJournal(next);
      return next;
    } catch (caught) {
      setJournal(null);
      setError(messageOf(caught, '无法读取步骤日志'));
      return null;
    } finally {
      setLoading(false);
    }
  }, [actionId, runStatus]);

  useEffect(() => {
    void loadJournal();
  }, [loadJournal]);

  const summary = useMemo(
    () => summarizeJournal(journal?.entries ?? []),
    [journal],
  );

  const controlBlocked = writesBlocked || role !== 'user';
  const controlReason = writesBlocked
    ? blockReason
    : role !== 'user'
      ? `当前角色 ${role} 不具备 tool:execute，暂停 / 恢复 / 回滚会被后端 403 拒绝。`
      : '';

  async function perform(action: JournalAction) {
    if (controlBlocked || busyAction) return;
    setBusyAction(action);
    setActionError('');
    setActionNotice('');
    try {
      let response: unknown = null;
      if (action === 'pause') {
        response = await pauseAction(actionId);
        setActionNotice('暂停请求已生效：剩余节点不会再执行，可稍后恢复或回滚。');
      } else if (action === 'resume') {
        response = await resumeAction(actionId);
        setActionNotice('已恢复执行：只执行剩余节点，已执行步骤不会重复执行。');
      } else {
        response = await rollbackAction(actionId);
        setActionNotice('回滚请求已处理：补偿按相反顺序执行，结论已写入审计链。');
      }
      const next = await loadJournal();
      if (next) onChanged(next, response);
    } catch (caught) {
      setActionError(messageOf(caught, `${action} 操作失败`));
    } finally {
      setBusyAction('');
    }
  }

  const rollback = run?.rollback;
  const journalStatus = journal?.status ?? run?.status ?? 'unknown';

  return (
    <div className="journal-panel">
      <div className="section-head compact-head">
        <div>
          <span className="eyebrow">STEP JOURNAL · RECOVERY</span>
          <h3>步骤日志与暂停 / 回滚</h3>
        </div>
        <div className="journal-head-actions">
          <code className="journal-action-id" title={actionId}>{actionId}</code>
          <button
            className="ghost-button small-button"
            onClick={() => void loadJournal()}
            disabled={loading || Boolean(busyAction)}
          >
            {loading ? '读取中…' : '刷新日志'}
          </button>
        </div>
      </div>

      <p className="panel-note">
        数据来自 <code>GET /api/actions/&#123;id&#125;/journal</code>；暂停、恢复与回滚分别调用
        <code> POST .../pause</code>、<code>.../resume</code>、<code>.../rollback</code>。
        所有补偿工具仍经过权限网关、执行器与审计哈希链。
      </p>

      <PageAlerts error={actionError} notice={actionNotice} />

      {rollback && (
        <div className={`rollback-summary rollback-${rollback.status}`}>
          <div className="rollback-head">
            <span className="eyebrow">COMPENSATION AUDIT</span>
            <ToneChip tone={rollback.status === 'completed' ? 'good' : rollback.status === 'blocked' ? 'bad' : 'warn'}>
              补偿 {rollback.status === 'completed' ? '已完成' : rollback.status === 'blocked' ? '被阻止' : '未全部成功'}
            </ToneChip>
          </div>
          <p>{rollback.reason || '—'}</p>
          <div className="rollback-facts">
            <span>已补偿 {rollback.compensated.length} 步</span>
            <span>补偿失败 {rollback.failed.length} 步</span>
            <span>不可撤销 {rollback.irreversible_steps.length} 步</span>
          </div>
          {rollback.compensated.length > 0 && (
            <ul className="rollback-list">
              {rollback.compensated.map((item) => (
                <li key={`${item.node_id}-${item.tool_name}`}>
                  <code>{item.node_id}</code>
                  <span>{item.tool_name}</span>
                  <span aria-hidden="true">→</span>
                  <code>{item.compensation_tool ?? '—'}</code>
                  {item.gateway_outcome && <span className="chip chip-teal">网关 {item.gateway_outcome}</span>}
                </li>
              ))}
            </ul>
          )}
          {rollback.irreversible_steps.length > 0 && (
            <ul className="rollback-list rollback-blocked-list">
              {rollback.irreversible_steps.map((item) => (
                <li key={`${item.node_id}-${item.tool_name}`}>
                  <code>{item.node_id}</code>
                  <span>{item.tool_name}</span>
                  <span>不可撤销：{item.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <ResourceState
        loading={loading}
        error={error}
        empty={false}
        emptyText=""
        onRetry={() => void loadJournal()}
      >
        {journal && (
          <>
            <dl className="trust-facts journal-facts">
              <div>
                <dt>STATUS</dt>
                <dd><StatusPill status={journalStatus} /> {statusLabel(journalStatus)}</dd>
              </div>
              <div>
                <dt>下一步索引</dt>
                <dd>{journal.next_index} / {journal.nodes.length} 个节点</dd>
              </div>
              <div>
                <dt>暂停状态</dt>
                <dd>{journal.pause.paused ? '已暂停' : '未暂停'}</dd>
              </div>
              <div>
                <dt>读取角色</dt>
                <dd>{journal.role ?? '—'}（请求头 X-Aegis-Role）</dd>
              </div>
              <div>
                <dt>创建时间</dt>
                <dd>{journal.created_at ? formatDateTime(journal.created_at) : '—'}</dd>
              </div>
              <div>
                <dt>更新时间</dt>
                <dd>{journal.updated_at ? formatDateTime(journal.updated_at) : '—'}</dd>
              </div>
            </dl>

            <p className="journal-status-copy">
              <strong>{compensationStatusLabel(journalStatus)}</strong>
              {compensationStatusDescription(journalStatus)}
            </p>
            {journal.reason && <p className="journal-reason">{journal.reason}</p>}
            {journal.pause.reason && journal.pause.paused && (
              <p className="journal-pause-reason">暂停原因：{journal.pause.reason}</p>
            )}
            {journal.not_started && (
              <div className="alert alert-info">
                动作尚未开始执行：步骤日志为空；暂停标记可清除，继续确认流程后才产生执行记录。
              </div>
            )}
            {journal.resume && (
              <div className="journal-resume">
                <span className="eyebrow">RESUME GUIDANCE</span>
                <p>{journal.resume.guidance}</p>
                <span>
                  剩余 {journal.resume.remaining_steps.length} 步：
                  {journal.resume.remaining_steps.map((step) => step.id).join(' → ') || '—'}
                </span>
              </div>
            )}

            <div className="journal-summary">
              <span className="eyebrow">COMPENSATION SUMMARY</span>
              <strong>{summary.headline}</strong>
              <div className="journal-counts">
                <span>已执行 {summary.executed}</span>
                <span>已补偿 {summary.compensated}</span>
                <span>补偿失败 {summary.compensationFailed}</span>
                <span>回滚被阻止 {summary.rollbackBlocked}</span>
              </div>
            </div>

            <div className="journal-actions">
              <button
                className="ghost-button small-button"
                onClick={() => void perform('pause')}
                disabled={Boolean(busyAction) || controlBlocked || journal.pause.paused}
                title={controlReason || '在下一个节点执行前暂停'}
              >
                {busyAction === 'pause' ? '暂停中…' : '暂停执行'}
              </button>
              <button
                className="ghost-button small-button"
                onClick={() => void perform('resume')}
                disabled={Boolean(busyAction) || controlBlocked || !journal.pause.paused}
                title={controlReason || '只执行剩余节点'}
              >
                {busyAction === 'resume' ? '恢复中…' : '恢复执行'}
              </button>
              <button
                className="danger-button small-button"
                onClick={() => void perform('rollback')}
                disabled={Boolean(busyAction) || controlBlocked || Boolean(journal.not_started)}
                title={controlReason || '按相反顺序补偿已执行步骤'}
              >
                {busyAction === 'rollback' ? '回滚中…' : '人工回滚'}
              </button>
            </div>
            {controlBlocked && (
              <div className="alert alert-warn">
                {controlReason} 只读角色仍可查看步骤日志、暂停状态与补偿审计摘要。
              </div>
            )}

            <div className="journal-entries">
              <span className="eyebrow">JOURNAL ENTRIES</span>
              <ResourceState
                loading={false}
                error=""
                empty={journal.entries.length === 0}
                emptyText={journal.not_started ? '动作尚未执行，暂无步骤条目。' : '该动作没有步骤日志条目。'}
              >
                <ol className="journal-entry-list">
                  {journal.entries.map((entry) => {
                    return (
                      <li className={`journal-entry journal-${journalPhaseTone(entry.phase)}`} key={entry.id}>
                        <div className="journal-entry-head">
                          <ToneChip tone={journalPhaseTone(entry.phase)}>
                            {journalPhaseLabel(entry.phase)}
                          </ToneChip>
                          <code>{entry.node_id}</code>
                          <strong>{entry.tool_name}</strong>
                          <span className="journal-entry-time">{formatDateTime(entry.created_at)}</span>
                        </div>
                        <div className="journal-entry-meta">
                          <span>条目状态：{entry.status}</span>
                          <span>风险：{entry.risk_level.toUpperCase()}</span>
                        </div>
                        <details>
                          <summary>查看入参与结果</summary>
                          <div className="journal-entry-detail">
                            <div>
                              <span className="eyebrow">ARGUMENTS</span>
                              <pre>{prettyEvidence(entry.arguments)}</pre>
                            </div>
                            <div>
                              <span className="eyebrow">RESULT</span>
                              <pre>{prettyEvidence(entry.result)}</pre>
                            </div>
                          </div>
                        </details>
                      </li>
                    );
                  })}
                </ol>
              </ResourceState>
            </div>
          </>
        )}
      </ResourceState>
    </div>
  );
}