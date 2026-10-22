import { formatCny } from '../risk';
import type { BankingOverview } from '../types';
import { formatDateTime } from '../viewModel';
import { LoadingState, PageAlerts } from './ui';

interface Props {
  overview: BankingOverview | null;
  loading: boolean;
  error: string;
  notice: string;
  onRefresh: () => void;
  onNavigateConsole: () => void;
}

export default function BankOverviewPage({
  overview,
  loading,
  error,
  notice,
  onRefresh,
  onNavigateConsole,
}: Props) {
  if (loading && !overview) {
    return (
      <section className="page-stack">
        <div className="page-heading">
          <span className="eyebrow">BANKING SNAPSHOT · READ ONLY</span>
          <h1>银行概览</h1>
          <p>汇总展示账户、卡片、订阅与今日风险相关的资金变化。</p>
        </div>
        <LoadingState label="正在汇总银行概览…" />
      </section>
    );
  }

  if (error && !overview) {
    return (
      <section className="page-stack">
        <div className="page-heading">
          <span className="eyebrow">BANKING SNAPSHOT · READ ONLY</span>
          <h1>银行概览</h1>
          <p>汇总展示账户、卡片、订阅与今日风险相关的资金变化。</p>
        </div>
        <PageAlerts error={error} notice={notice} />
        <button className="primary-button fit-button" onClick={onRefresh}>
          重新加载概览
        </button>
      </section>
    );
  }

  if (!overview) return null;

  const totalBalance = overview.accounts.reduce((sum, account) => sum + account.balanceCny, 0);
  const abnormalCount = overview.abnormalSubscriptions.length;
  const todayTransferRisk = overview.todayTransferTotalCny > 1_000 ? 'red' : 'yellow';

  return (
    <section className="page-stack overview-page">
      <div className="page-heading overview-heading">
        <div>
          <span className="eyebrow">BANKING SNAPSHOT · READ ONLY</span>
          <h1>银行概览</h1>
          <p>账户、卡片与订阅的统一只读视图。今日累计转账会参与动态风险判定。</p>
          <small className="page-meta">
            快照时间：{overview.asOf ? formatDateTime(overview.asOf) : '本次加载'}
          </small>
        </div>
        <button className="ghost-button" onClick={onRefresh} disabled={loading}>
          {loading ? '刷新中…' : '刷新数据'}
        </button>
      </div>

      <PageAlerts error={error} notice={notice} />

      {abnormalCount > 0 && (
        <div className="risk-callout" role="alert">
          <span className="callout-symbol">!</span>
          <div>
            <span className="eyebrow">ABNORMAL SUBSCRIPTION DETECTED</span>
            <strong>发现 {abnormalCount} 项异常订阅，建议尽快核查并处理。</strong>
            <p>
              {overview.abnormalSubscriptions
                .map((item) => `${item.merchant}${item.reason ? `（${item.reason}）` : ''}`)
                .join('；')}
            </p>
          </div>
          <button className="ghost-button callout-action" onClick={onNavigateConsole}>
            前往任务控制台
          </button>
        </div>
      )}

      <div className="summary-grid">
        <article className="card summary-card accent-teal">
          <span>账户总余额</span>
          <strong>{formatCny(totalBalance)}</strong>
          <small>{overview.accounts.length} 个账户 · 人民币</small>
        </article>
        <article className="card summary-card">
          <span>本月支出</span>
          <strong>{formatCny(overview.monthSpendingCny)}</strong>
          <small>基于本月交易汇总</small>
        </article>
        <article className={`card summary-card ${overview.todayTransferTotalCny > 1_000 ? 'accent-red' : ''}`}>
          <span>今日累计转账</span>
          <strong>{formatCny(overview.todayTransferTotalCny)}</strong>
          <small>
            动态阈值 {formatCny(1_000)}
            <span className={`inline-risk-dot risk-dot-${todayTransferRisk}`} />
            {overview.todayTransferTotalCny > 1_000 ? ' 已触发红色累计规则' : ' 当前低于红色阈值'}
          </small>
        </article>
        <article className={`card summary-card ${abnormalCount ? 'accent-amber' : ''}`}>
          <span>异常订阅</span>
          <strong>{abnormalCount} 项</strong>
          <small>{abnormalCount ? '需要人工核查' : '未发现异常扣款模式'}</small>
        </article>
      </div>

      <div className="overview-columns">
        <section className="card overview-panel">
          <div className="section-head compact-head">
            <div>
              <span className="eyebrow">ACCOUNTS</span>
              <h2>银行账户</h2>
            </div>
            <span className="muted">{overview.accounts.length} 个账户</span>
          </div>
          <div className="account-list">
            {overview.accounts.map((account) => (
              <article className="account-item" key={account.id}>
                <div className="account-item-top">
                  <div>
                    <strong>{account.name}</strong>
                    <small>
                      {account.type} · {account.maskedNumber}
                    </small>
                  </div>
                  <span className="currency-pill">{account.currency}</span>
                </div>
                <div className="account-balance">{formatCny(account.balanceCny)}</div>
                <small>
                  可用余额：{account.availableCny === null ? '—' : formatCny(account.availableCny)}
                </small>
              </article>
            ))}
            {overview.accounts.length === 0 && (
              <div className="inline-empty">暂无账户数据。</div>
            )}
          </div>
        </section>

        <section className="card overview-panel">
          <div className="section-head compact-head">
            <div>
              <span className="eyebrow">CARDS</span>
              <h2>卡片状态</h2>
            </div>
            <span className="muted">{overview.cards.length} 张卡片</span>
          </div>
          <div className="card-list">
            {overview.cards.map((card) => (
              <article className="bank-card-item" key={card.id}>
                <div className="bank-card-top">
                  <div>
                    <strong>{card.name}</strong>
                    <small>{card.maskedNumber}</small>
                  </div>
                  <span className={card.status.includes('正常') ? 'grant-on' : 'grant-off'}>
                    {card.status}
                  </span>
                </div>
                <dl className="mini-facts">
                  <div>
                    <dt>信用额度</dt>
                    <dd>{card.creditLimitCny === null ? '—' : formatCny(card.creditLimitCny)}</dd>
                  </div>
                  <div>
                    <dt>可用额度</dt>
                    <dd>{card.availableLimitCny === null ? '—' : formatCny(card.availableLimitCny)}</dd>
                  </div>
                  <div>
                    <dt>还款日</dt>
                    <dd>{card.repaymentDay === null ? '—' : `每月 ${card.repaymentDay} 日`}</dd>
                  </div>
                </dl>
              </article>
            ))}
            {overview.cards.length === 0 && <div className="inline-empty">暂无卡片数据。</div>}
          </div>
        </section>
      </div>

      <section className="card overview-panel">
        <div className="section-head compact-head">
          <div>
            <span className="eyebrow">SUBSCRIPTIONS</span>
            <h2>订阅与自动扣款</h2>
          </div>
          <span className="muted">
            {overview.subscriptions.length} 项订阅 · {abnormalCount} 项异常
          </span>
        </div>
        <div className="table-scroll">
          <table className="overview-table">
            <thead>
              <tr>
                <th>商户 / 订阅</th>
                <th>扣款金额</th>
                <th>周期</th>
                <th>下次扣款</th>
                <th>状态</th>
                <th>异常提示</th>
              </tr>
            </thead>
            <tbody>
              {overview.subscriptions.map((item) => (
                <tr key={item.id} className={item.abnormal ? 'row-abnormal' : ''}>
                  <td>
                    <strong>{item.merchant}</strong>
                    <small>{item.id}</small>
                  </td>
                  <td>{formatCny(item.amountCny)}</td>
                  <td>{item.cycle}</td>
                  <td>{item.nextBillingDate || '—'}</td>
                  <td>
                    <span className={item.abnormal ? 'grant-off' : 'grant-on'}>{item.status}</span>
                  </td>
                  <td>
                    {item.abnormal ? <span className="risk-badge risk-red">需处理</span> : '—'}
                    {item.reason && <small>{item.reason}</small>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {overview.subscriptions.length === 0 && <div className="inline-empty">暂无订阅数据。</div>}
      </section>
    </section>
  );
}
