import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  fetchAudit,
  fetchTools,
  resolveConfirmation,
  runAgent,
  updatePermission,
  verifyAudit,
} from './api';
import { formatCny, isHighRisk, riskLabels } from './risk';
import type { AuditEntry, RiskLevel, RunResponse, ToolMetadata } from './types';

type Page = 'console' | 'permissions' | 'audit';

const quickActions: Record<string, { instruction: string; arguments: Record<string, unknown> }> = {
  query_bill: {
    instruction: '查询我的本月账单',
    arguments: { account_id: 'ACC-1001', period: 'current_month' },
  },
  adjust_repayment_date: {
    instruction: '把还款日调整到每月 18 日',
    arguments: { card_id: 'CARD-8821', new_day: 18 },
  },
  transfer: {
    instruction: '向 ACC-2002 转账 880 元',
    arguments: {
      from_account: 'ACC-1001',
      to_account: 'ACC-2002',
      amount_cny: 880,
      note: 'Console quick action',
    },
  },
};

function riskBadge(risk: RiskLevel) {
  return <span className={`risk-badge risk-${risk}`}>{risk.toUpperCase()}</span>;
}

function eventLabel(event: string): string {
  return (
    {
      tool_executed: '工具执行',
      confirmation_requested: '等待确认',
      confirmation_approved: '确认通过',
      confirmation_rejected: '用户拒绝',
      gateway_blocked: '网关拦截',
      tool_failed: '执行失败',
    }[event] ?? event
  );
}

function App() {
  const [page, setPage] = useState<Page>('console');
  const [tools, setTools] = useState<ToolMetadata[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditValid, setAuditValid] = useState<boolean | null>(null);
  const [instruction, setInstruction] = useState('查询我的本月账单');
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);
  const [pending, setPending] = useState<RunResponse | null>(null);
  const [otp, setOtp] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const grantedCount = useMemo(() => tools.filter((tool) => tool.granted).length, [tools]);

  async function refresh() {
    try {
      const [nextTools, nextAudit, chain] = await Promise.all([
        fetchTools(),
        fetchAudit(),
        verifyAudit(),
      ]);
      setTools(nextTools);
      setAudit(nextAudit.entries);
      setAuditValid(chain.valid);
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法连接后端服务');
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function execute(input: Parameters<typeof runAgent>[0]) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await runAgent(input);
      setLastRun(result);
      if (result.status === 'awaiting_confirmation') {
        setOtp('');
        setPending(result);
      } else {
        setPending(null);
        setNotice(result.reason);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    } finally {
      setBusy(false);
    }
  }

  function submitInstruction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!instruction.trim()) return;
    void execute({ instruction: instruction.trim() });
  }

  function triggerQuick(tool: ToolMetadata) {
    const action = quickActions[tool.name];
    if (!action) return;
    setInstruction(action.instruction);
    void execute({ instruction: action.instruction, tool_name: tool.name, arguments: action.arguments });
  }

  async function decision(approved: boolean) {
    if (!pending?.confirmation) return;
    setBusy(true);
    setError('');
    try {
      const result = await resolveConfirmation(pending.confirmation.id, approved, otp);
      setLastRun(result);
      setPending(null);
      setOtp('');
      setNotice(result.reason);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败');
    } finally {
      setBusy(false);
    }
  }

  async function togglePermission(tool: ToolMetadata) {
    setBusy(true);
    setError('');
    try {
      await updatePermission(tool.name, !tool.granted);
      await refresh();
      setNotice(`${tool.title} 权限已${tool.granted ? '撤回' : '授予'}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '权限更新失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            A
          </div>
          <div>
            <strong>AegisBank</strong>
            <span>Trusted Agent Console</span>
          </div>
        </div>
        <div className="topbar-status">
          <span className={`status-dot ${auditValid === false ? 'status-bad' : ''}`} />
          {auditValid === false ? '审计链异常' : '本地 MVP · 审计链在线'}
          <span className="env-pill">DEV</span>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <nav aria-label="主导航">
            <button className={page === 'console' ? 'active' : ''} onClick={() => setPage('console')}>
              <span className="nav-index">01</span>
              任务控制台
            </button>
            <button
              className={page === 'permissions' ? 'active' : ''}
              onClick={() => setPage('permissions')}
            >
              <span className="nav-index">02</span>
              权限控制台
            </button>
            <button className={page === 'audit' ? 'active' : ''} onClick={() => setPage('audit')}>
              <span className="nav-index">03</span>
              操作审计
            </button>
          </nav>

          <div className="sidebar-note">
            <span className="eyebrow">TRUST POSTURE</span>
            <strong>{grantedCount} / {tools.length || 3}</strong>
            <p>工具权限已授权</p>
            <div className="meter">
              <span style={{ width: `${tools.length ? (grantedCount / tools.length) * 100 : 0}%` }} />
            </div>
          </div>

          <div className="sidebar-footer">
            <span>用户 · demo-user</span>
            <span>数据 · SQLite / Local</span>
          </div>
        </aside>

        <main>
          {page === 'console' && (
            <section className="page-grid console-grid">
              <div className="hero card">
                <div>
                  <span className="eyebrow">AGENTIC BANKING · CONTROL PLANE</span>
                  <h1>让每一次金融操作，都经过信任闸门。</h1>
                  <p>
                    AegisBank 将意图规划、权限校验、风险分级与操作审计串成一条可追溯链路。
                    绿色直接执行，黄色轻量确认，红色二次校验。
                  </p>
                </div>
                <div className="hero-orbit" aria-hidden="true">
                  <span className="orbit-ring ring-one" />
                  <span className="orbit-ring ring-two" />
                  <span className="orbit-core">A</span>
                  <span className="orbit-label orbit-top">IDENTITY</span>
                  <span className="orbit-label orbit-right">POLICY</span>
                  <span className="orbit-label orbit-bottom">AUDIT</span>
                </div>
              </div>

              <div className="metrics-row">
                <div className="metric card">
                  <span>风险策略</span>
                  <strong>3 级</strong>
                  <small>GREEN / YELLOW / RED</small>
                </div>
                <div className="metric card">
                  <span>已注册工具</span>
                  <strong>{tools.length}</strong>
                  <small>插件化节点 SDK</small>
                </div>
                <div className="metric card">
                  <span>审计完整性</span>
                  <strong className={auditValid === false ? 'text-danger' : 'text-good'}>
                    {auditValid === false ? '异常' : '通过'}
                  </strong>
                  <small>SHA-256 哈希链</small>
                </div>
              </div>

              <div className="card command-card">
                <div className="section-head">
                  <div>
                    <span className="eyebrow">INTENT CONSOLE</span>
                    <h2>发起一项任务</h2>
                  </div>
                  <span className="muted">所有结果均为演示数据</span>
                </div>
                <form className="command-form" onSubmit={submitInstruction}>
                  <label className="sr-only" htmlFor="instruction">
                    输入任务指令
                  </label>
                  <textarea
                    id="instruction"
                    value={instruction}
                    onChange={(event) => setInstruction(event.target.value)}
                    rows={3}
                    placeholder="例如：向 ACC-2002 转账 880 元"
                  />
                  <button className="primary-button" type="submit" disabled={busy}>
                    {busy ? '处理中…' : '交给 Agent'}
                    <span aria-hidden="true">↗</span>
                  </button>
                </form>

                <div className="quick-actions">
                  {tools.map((tool) => (
                    <button
                      key={tool.name}
                      className="tool-chip"
                      onClick={() => triggerQuick(tool)}
                      disabled={busy || !tool.granted}
                      title={tool.granted ? tool.description : '该工具权限已撤回'}
                    >
                      {riskBadge(tool.risk_level)}
                      <span>{tool.title}</span>
                      <small>{tool.permission}</small>
                    </button>
                  ))}
                </div>
              </div>

              {error && <div className="alert alert-error">{error}</div>}
              {notice && <div className="alert alert-info">{notice}</div>}

              {lastRun && (
                <div className="card result-card">
                  <div className="section-head">
                    <div>
                      <span className="eyebrow">RUN RESULT</span>
                      <h2>执行回执</h2>
                    </div>
                    <div className="result-tags">
                      {riskBadge(lastRun.risk_level)}
                      <span className={`status-pill status-${lastRun.status}`}>{lastRun.status}</span>
                    </div>
                  </div>
                  <p className="result-reason">{lastRun.reason}</p>
                  {lastRun.plan && (
                    <div className="plan-block">
                      <div className="plan-meta">
                        <span className="eyebrow">STRUCTURED EXECUTION PLAN</span>
                        <span className="plan-planner">{lastRun.plan.planner}</span>
                        <span className="plan-confidence">
                          置信度 {Math.round(lastRun.plan.confidence * 100)}%
                        </span>
                        {lastRun.plan.plan_hash && (
                          <code className="plan-hash" title={lastRun.plan.plan_hash}>
                            {lastRun.plan.plan_hash.slice(0, 12)}…
                          </code>
                        )}
                      </div>
                      {lastRun.plan.steps.length > 0 && (
                        <ol className="plan-steps">
                          {lastRun.plan.steps.map((step) => (
                            <li key={step.id}>
                              <div className="plan-step-head">
                                <span className="plan-step-id">{step.id}</span>
                                <strong>{step.title || step.tool_name}</strong>
                                {step.risk_level && riskBadge(step.risk_level)}
                              </div>
                              <div className="plan-step-tool">
                                <code>{step.tool_name}</code>
                                {step.depends_on.length > 0 && (
                                  <span>依赖 {step.depends_on.join(', ')}</span>
                                )}
                              </div>
                              <pre>{JSON.stringify(step.arguments, null, 2)}</pre>
                            </li>
                          ))}
                        </ol>
                      )}
                      {lastRun.plan.assumptions.length > 0 && (
                        <div className="plan-assumptions">
                          {lastRun.plan.assumptions.map((item) => (
                            <span key={item}>{item}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {lastRun.results?.map((result) => (
                    <div className="result-block" key={result.tool_name}>
                      <div className="result-tool">
                        <span>{result.message}</span>
                        <code>{result.tool_name}</code>
                      </div>
                      <dl className="data-grid">
                        {Object.entries(result.data).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>
                              {key.includes('amount')
                                ? formatCny(value)
                                : typeof value === 'object'
                                  ? JSON.stringify(value, null, 2)
                                  : String(value)}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  ))}
                </div>
              )}

              <div className="card flow-card">
                <div className="section-head">
                  <div>
                    <span className="eyebrow">GOVERNED PIPELINE</span>
                    <h2>每个节点都经过同一条路径</h2>
                  </div>
                </div>
                <ol className="pipeline">
                  <li><span>01</span><strong>意图解析</strong><small>规则规划器生成 DAG</small></li>
                  <li><span>02</span><strong>权限网关</strong><small>注入 / 越权 / 风险</small></li>
                  <li><span>03</span><strong>分级确认</strong><small>绿放行 · 黄确认 · 红校验</small></li>
                  <li><span>04</span><strong>签名审计</strong><small>哈希链留痕</small></li>
                </ol>
              </div>
            </section>
          )}

          {page === 'permissions' && (
            <section className="page-stack">
              <div className="page-heading">
                <span className="eyebrow">USER-CONTROLLED AUTHORIZATION</span>
                <h1>权限控制台</h1>
                <p>授权颗粒度精确到工具。撤回后，后续调用会在进入调度器前被统一网关拦截。</p>
              </div>
              {error && <div className="alert alert-error">{error}</div>}
              {notice && <div className="alert alert-info">{notice}</div>}
              <div className="card table-card">
                <table>
                  <thead>
                    <tr>
                      <th>工具节点</th>
                      <th>风险等级</th>
                      <th>最小权限</th>
                      <th>当前状态</th>
                      <th aria-label="操作" />
                    </tr>
                  </thead>
                  <tbody>
                    {tools.map((tool) => (
                      <tr key={tool.name}>
                        <td>
                          <strong>{tool.title}</strong>
                          <small>{tool.description}</small>
                        </td>
                        <td>{riskBadge(tool.risk_level)}</td>
                        <td><code>{tool.permission}</code></td>
                        <td>
                          <span className={tool.granted ? 'grant-on' : 'grant-off'}>
                            {tool.granted ? '已授权' : '已撤回'}
                          </span>
                        </td>
                        <td className="table-action">
                          <button className="ghost-button" onClick={() => void togglePermission(tool)}>
                            {tool.granted ? '撤回' : '授予'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="policy-note card">
                <span className="eyebrow">DEFAULT POLICY</span>
                <div>
                  <strong>绿色操作</strong> 仅需最小权限即可静默执行；<strong>黄色操作</strong>
                  需要 5 分钟内确认；<strong>红色操作</strong>必须二次校验。高风险工具的授权撤回立即生效。
                </div>
              </div>
            </section>
          )}

          {page === 'audit' && (
            <section className="page-stack">
              <div className="page-heading audit-heading">
                <div>
                  <span className="eyebrow">TAMPER-EVIDENT ACTIVITY LOG</span>
                  <h1>操作审计</h1>
                  <p>每一条记录都包含触发时间、原始指令、DAG 路径、工具入参、执行结果和确认状态。</p>
                </div>
                <div className={`chain-seal ${auditValid === false ? 'seal-bad' : ''}`}>
                  <span>{auditValid === false ? '!' : '✓'}</span>
                  <div>
                    <strong>{auditValid === false ? '哈希链异常' : '哈希链完整'}</strong>
                    <small>{audit.length} 条记录已加载</small>
                  </div>
                </div>
              </div>
              {error && <div className="alert alert-error">{error}</div>}
              <div className="audit-list">
                {audit.map((entry) => (
                  <details className="audit-entry card" key={entry.id}>
                    <summary>
                      <span className="audit-id">#{String(entry.id).padStart(3, '0')}</span>
                      {riskBadge(entry.risk_level)}
                      <strong>{eventLabel(entry.event)}</strong>
                      <span className="audit-tool">{entry.tool_name}</span>
                      <span className="audit-time">
                        {new Date(entry.created_at).toLocaleString('zh-CN')}
                      </span>
                      <span className="audit-chevron">⌄</span>
                    </summary>
                    <div className="audit-body">
                      <dl>
                        <div><dt>用户原始指令</dt><dd>{entry.instruction}</dd></div>
                        <div><dt>DAG 路径</dt><dd><code>{entry.dag_path}</code></dd></div>
                        <div><dt>工具入参</dt><dd><pre>{JSON.stringify(entry.arguments, null, 2)}</pre></dd></div>
                        <div><dt>执行结果</dt><dd><pre>{JSON.stringify(entry.result, null, 2)}</pre></dd></div>
                        <div><dt>确认状态</dt><dd>{entry.confirmation_state}</dd></div>
                        <div><dt>Entry hash</dt><dd><code className="hash">{entry.entry_hash}</code></dd></div>
                      </dl>
                    </div>
                  </details>
                ))}
                {audit.length === 0 && <div className="empty-state card">还没有审计记录，先发起一项任务。</div>}
              </div>
            </section>
          )}
        </main>
      </div>

      {pending?.confirmation && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <div className="modal-top">
              {riskBadge(pending.risk_level)}
              <span className="eyebrow">HUMAN-IN-THE-LOOP</span>
            </div>
            <h2 id="confirm-title">
              {isHighRisk(pending.risk_level) ? '高风险操作需要二次确认' : '确认这项账户变更'}
            </h2>
            <p>{pending.reason}</p>
            {isHighRisk(pending.risk_level) && (
              <label className="otp-field">
                <span>演示验证码</span>
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="输入 6 位验证码"
                  value={otp}
                  onChange={(event) => setOtp(event.target.value.replace(/\D/g, '').slice(0, 6))}
                />
                <small>本地开发默认值见 README，生产环境须接入银行真实二次认证。</small>
              </label>
            )}
            <div className="modal-actions">
              <button className="ghost-button" onClick={() => void decision(false)} disabled={busy}>
                拒绝
              </button>
              <button
                className="primary-button"
                onClick={() => void decision(true)}
                disabled={busy || (isHighRisk(pending.risk_level) && otp.length !== 6)}
              >
                {busy ? '校验中…' : '确认执行'}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
