import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  fetchAutomationGoals,
  fetchAutomationOrders,
  fetchAutomationSchedules,
  fetchBillAnomalies,
  fetchBillReport,
  fetchCardApplications,
  fetchContacts,
  fetchRenewalReminders,
  fetchSubscriptionCharges,
  fetchWealthHoldings,
  fetchWealthOrders,
  fetchWealthProducts,
  runAutomationDue,
} from '../api';
import { formatCny } from '../risk';
import type { AutomationRunDueResult } from '../types';
import {
  daysLeft,
  formatChangePct,
  formatDateTime,
  formatRate,
  formatSignedCny,
  prettyEvidence,
  severityLabel,
  statusLabel,
  wealthRiskLabel,
  wealthRiskLevel,
} from '../viewModel';
import { ResourceState, RiskBadge } from './ui';

interface Resource<T> {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => Promise<void>;
}

export function useResource<T>(loader: () => Promise<T>, fallbackError: string): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const sequence = useRef(0);
  const reload = useCallback(async () => {
    const current = ++sequence.current;
    setLoading(true);
    setError('');
    try {
      const next = await loader();
      if (current === sequence.current) setData(next);
    } catch (caught) {
      if (current === sequence.current) setError(caught instanceof Error ? caught.message : fallbackError);
    } finally {
      if (current === sequence.current) setLoading(false);
    }
  }, [loader, fallbackError]);

  useEffect(() => {
    void reload();
    return () => { sequence.current += 1; };
  }, [reload]);

  return { data, loading, error, reload };
}

const BILL_CATEGORY_LABELS: Record<string, string> = {
  food: '餐饮',
  shopping: '购物',
  subscription: '订阅',
  transport: '交通',
  wealth: '理财',
};

const RELATION_LABELS: Record<string, string> = {
  mother: '母亲',
  father: '父亲',
  friend: '好友',
  colleague: '同事',
  spouse: '配偶',
};

const TASK_KIND_LABELS: Record<string, string> = {
  transfer: '定时转账',
  gift: '生日礼物',
};

const TASK_STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  done: '已完成',
  cancelled: '已取消',
  failed: '失败',
};

const GOAL_STATUS_LABELS: Record<string, string> = {
  active: '进行中',
  completed: '已完成',
  cancelled: '已取消',
};

const ORDER_STATUS_LABELS: Record<string, string> = {
  scheduled: '已排期',
  ordered: '已下单',
  cancelled: '已取消',
};

const CARD_APPLICATION_STATUS_LABELS: Record<string, string> = {
  applying: '审核中',
  approved: '已批准',
  issued: '已发卡',
  rejected: '已拒绝',
};

const RECURRENCE_LABELS: Record<string, string> = {
  none: '单次',
  monthly: '每月',
  yearly: '每年',
};

const WEALTH_SIDE_LABELS: Record<string, string> = {
  purchase: '申购',
  redeem: '赎回',
};

function categoryLabel(category: string): string {
  return BILL_CATEGORY_LABELS[category] ?? category;
}

function taskKindLabel(kind: string | undefined): string {
  return kind ? (TASK_KIND_LABELS[kind] ?? kind) : '任务';
}

function taskStatusClass(status: string): string {
  if (status === 'done') return 'chip-good';
  if (status === 'failed') return 'chip-bad';
  if (status === 'pending') return 'chip-warn';
  return '';
}

function goalStatusClass(status: string): string {
  if (status === 'active') return 'chip-teal';
  if (status === 'completed') return 'chip-good';
  return '';
}

function orderStatusClass(status: string): string {
  if (status === 'ordered') return 'chip-good';
  if (status === 'scheduled') return 'chip-warn';
  return '';
}

function cardStatusClass(status: string): string {
  if (status === 'issued') return 'chip-good';
  if (status === 'rejected') return 'chip-bad';
  return 'chip-warn';
}

function Panel({
  eyebrow,
  title,
  meta,
  actions,
  children,
}: {
  eyebrow: string;
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card scenario-panel">
      <div className="section-head compact-head">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <div className="panel-head-meta">
          {meta && <span className="muted">{meta}</span>}
          {actions}
        </div>
      </div>
      {children}
    </section>
  );
}

function RefreshButton({
  loading,
  onClick,
  label = '刷新',
}: {
  loading: boolean;
  onClick: () => void;
  label?: string;
}) {
  return (
    <button className="ghost-button small-button" onClick={onClick} disabled={loading}>
      {loading ? '刷新中…' : label}
    </button>
  );
}

interface Props {
  writesBlocked: boolean;
  blockReason: string;
  /** 时间快进会真实执行到期任务，成功后通知 App 刷新概览 / 审计 / 熔断（UX-22）。 */
  onDataChanged?: () => void;
}

export default function ScenariosPage({ writesBlocked, blockReason, onDataChanged }: Props) {
  /* 理财 */
  const products = useResource(fetchWealthProducts, '无法加载模拟理财产品');
  const holdings = useResource(fetchWealthHoldings, '无法加载模拟理财持仓');
  const orders = useResource(fetchWealthOrders, '无法加载模拟理财订单');
  const productList = products.data?.products ?? [];
  const holdingList = holdings.data?.holdings ?? [];
  const orderList = orders.data?.orders ?? [];
  const wealthLoading = products.loading || holdings.loading || orders.loading;

  /* 联系人 */
  const contacts = useResource(fetchContacts, '无法加载联系人簿');
  const contactList = contacts.data?.contacts ?? [];

  /* 账单与订阅 */
  const [period, setPeriod] = useState<'month' | 'year'>('month');
  const loadReport = useCallback(() => fetchBillReport(period), [period]);
  const loadAnomalies = useCallback(() => fetchBillAnomalies(period), [period]);
  const report = useResource(loadReport, '无法加载账单报告');
  const anomalies = useResource(loadAnomalies, '无法加载账单异常检测');
  const reportData = report.data;
  const anomalyData = anomalies.data;
  const categories = Object.entries(reportData?.categories ?? {});
  const maxCategory = Math.max(1, ...categories.map(([, amount]) => amount));

  const charges = useResource(fetchSubscriptionCharges, '无法加载订阅扣费');
  const reminders = useResource(fetchRenewalReminders, '无法加载续费提醒');
  const chargeList = charges.data?.subscriptions ?? [];
  const reminderList = reminders.data?.reminders ?? [];

  /* 卡片 */
  const applications = useResource(fetchCardApplications, '无法加载卡片申请');
  const applicationList = applications.data?.applications ?? [];

  /* 自动化 */
  const schedules = useResource(fetchAutomationSchedules, '无法加载定时任务');
  const goals = useResource(fetchAutomationGoals, '无法加载预算目标');
  const gifts = useResource(fetchAutomationOrders, '无法加载礼物订单');
  const taskList = schedules.data?.tasks ?? [];
  const goalList = goals.data?.goals ?? [];
  const giftList = gifts.data?.orders ?? [];

  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState('');
  const [runResult, setRunResult] = useState<AutomationRunDueResult | null>(null);

  async function handleRunDue() {
    if (runBusy || writesBlocked) return;
    setRunBusy(true);
    setRunError('');
    try {
      const result = await runAutomationDue();
      setRunResult(result);
      await Promise.all([schedules.reload(), goals.reload(), gifts.reload()]);
      onDataChanged?.();
    } catch (caught) {
      setRunResult(null);
      setRunError(caught instanceof Error ? caught.message : '时间快进失败');
    } finally {
      setRunBusy(false);
    }
  }

  return (
    <section className="scenarios-page">
      <div className="page-heading">
        <span className="eyebrow">SIX SCENARIOS · READ ONLY + TIME TRAVEL</span>
        <h1>场景数据（只读）</h1>
        <p>
          理财、联系人、账单、订阅、卡片与自动化的统一只读视图：这里只展示数据与时间快进，
          发起业务请到「任务控制台」。金融数字全部来自后端模拟数据（simulated=True），不接线真实银行。
        </p>
        <small className="page-meta">
          每个数据区独立加载：某个新增接口未就绪时只在该区显示错误/空态，不会影响其它面板。
        </small>
      </div>

      <Panel
        eyebrow="WEALTH · SIMULATED"
        title="理财"
        meta={
          products.data
            ? `${products.data.count} 只产品 · ${holdingList.length} 笔持仓 · ${orderList.length} 笔订单`
            : '读取产品、持仓与订单'
        }
        actions={
          <RefreshButton
            loading={wealthLoading}
            onClick={() => {
              void products.reload();
              void holdings.reload();
              void orders.reload();
            }}
          />
        }
      >
        <div className="wealth-disclaimer" role="note">
          ⚠ 模拟数据，不构成投资建议，不产生任何真实资金变动。
        </div>

        <h3 className="sub-head">产品列表（R1–R5 风险等级）</h3>
        <ResourceState
          loading={products.loading}
          error={products.error}
          empty={productList.length === 0}
          emptyText="暂无模拟理财产品数据；后端数据源可能尚未初始化。"
          onRetry={() => void products.reload()}
        >
          <div className="table-scroll">
            <table className="compact-table">
              <thead>
                <tr>
                  <th>产品</th>
                  <th>风险等级</th>
                  <th>起购金额</th>
                  <th>预期年化</th>
                  <th>期限</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {productList.map((product) => (
                  <tr key={product.product_id}>
                    <td>
                      <strong>{product.name}</strong>
                      <small>
                        {product.kind} · {product.product_id}
                      </small>
                    </td>
                    <td>
                      <div className="wealth-risk-cell">
                        <RiskBadge risk={wealthRiskLevel(product.risk_level)} />
                        <small>{wealthRiskLabel(product.risk_level)}</small>
                      </div>
                    </td>
                    <td>{formatCny(product.min_amount_cny)}</td>
                    <td>{formatRate(product.expected_annual_rate)}</td>
                    <td>{product.term_days > 0 ? `${product.term_days} 天` : '活期'}</td>
                    <td>
                      <span className="chip chip-good">
                        {product.status === 'active' ? '在售' : product.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ResourceState>

        <div className="panel-columns">
          <div>
            <div className="panel-sub">
              <h3>我的持仓</h3>
              <span className="muted">
                市值合计 {formatCny(holdings.data?.total_market_value_cny ?? 0)}
              </span>
            </div>
            <ResourceState
              loading={holdings.loading}
              error={holdings.error}
              empty={holdingList.length === 0}
              emptyText="暂无模拟理财持仓；可在任务控制台发起一次模拟申购。"
              onRetry={() => void holdings.reload()}
            >
              <ul className="list-stack">
                {holdingList.map((holding) => (
                  <li className="list-item" key={holding.holding_id}>
                    <div className="item-main">
                      <strong>{holding.product_name || holding.product_id}</strong>
                      <small>
                        <RiskBadge risk={wealthRiskLevel(holding.risk_level)} />
                        <span> {wealthRiskLabel(holding.risk_level)} · {holding.kind}</span>
                      </small>
                      <small>
                        本金 {formatCny(holding.principal_cny)} · 份额 {holding.shares} · 建仓{' '}
                        {formatDateTime(holding.opened_at)}
                      </small>
                    </div>
                    <div className="item-end">
                      <strong>{formatCny(holding.market_value_cny)}</strong>
                      <small>{holding.status === 'active' ? '持有中' : holding.status}</small>
                    </div>
                  </li>
                ))}
              </ul>
            </ResourceState>
          </div>

          <div>
            <div className="panel-sub">
              <h3>理财订单</h3>
              <span className="muted">{orderList.length} 笔</span>
            </div>
            <ResourceState
              loading={orders.loading}
              error={orders.error}
              empty={orderList.length === 0}
              emptyText="暂无模拟理财订单；申购或赎回后会在这里出现。"
              onRetry={() => void orders.reload()}
            >
              <ul className="list-stack">
                {orderList.map((order) => (
                  <li className="list-item" key={order.order_id}>
                    <div className="item-main">
                      <strong>{order.product_name || order.product_id}</strong>
                      <small>
                        {WEALTH_SIDE_LABELS[order.side] ?? order.side} · {order.order_id}
                      </small>
                      <small>{formatDateTime(order.created_at)}</small>
                    </div>
                    <div className="item-end">
                      <strong>{formatCny(order.amount_cny)}</strong>
                      <span className="chip">{order.status}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </ResourceState>
          </div>
        </div>
      </Panel>

      <Panel
        eyebrow="CONTACTS · MASKED"
        title="联系人"
        meta={contacts.data ? `${contacts.data.count} 位联系人` : '账户与手机号脱敏'}
        actions={
          <RefreshButton loading={contacts.loading} onClick={() => void contacts.reload()} />
        }
      >
        <p className="panel-note">
          手机号与收款账户由后端脱敏后返回，前端不展示明文；联系人簿可用于转账与 AA 拆分。
        </p>
        <ResourceState
          loading={contacts.loading}
          error={contacts.error}
          empty={contactList.length === 0}
          emptyText="联系人簿为空；可在任务控制台通过「新增联系人」创建（模拟数据）。"
          onRetry={() => void contacts.reload()}
        >
          <div className="contact-grid">
            {contactList.map((contact) => (
              <article className="contact-card" key={contact.contact_id}>
                <div className="contact-top">
                  <strong>{contact.name}</strong>
                  <span className="chip chip-teal">
                    {contact.relation ? (RELATION_LABELS[contact.relation] ?? contact.relation) : '联系人'}
                  </span>
                </div>
                <dl className="mini-facts">
                  <div>
                    <dt>手机号</dt>
                    <dd>{contact.phone ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>收款账户</dt>
                    <dd>{contact.account_id}</dd>
                  </div>
                  <div>
                    <dt>生日</dt>
                    <dd>{contact.birthday ?? '—'}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </ResourceState>
      </Panel>

      <Panel
        eyebrow="BILLS · REPORT + ANOMALIES"
        title="账单报告与异常检测"
        meta={reportData ? reportData.label : '月报 / 年报'}
        actions={
          <>
            <div className="period-toggle" role="group" aria-label="账期切换">
              <button
                className={period === 'month' ? 'active' : ''}
                onClick={() => setPeriod('month')}
                aria-pressed={period === 'month'}
              >
                月报
              </button>
              <button
                className={period === 'year' ? 'active' : ''}
                onClick={() => setPeriod('year')}
                aria-pressed={period === 'year'}
              >
                年报
              </button>
            </div>
            <RefreshButton
              loading={report.loading || anomalies.loading}
              onClick={() => {
                void report.reload();
                void anomalies.reload();
              }}
            />
          </>
        }
      >
        <ResourceState
          loading={report.loading}
          error={report.error}
          empty={!reportData || (reportData.total_spend_cny === 0 && reportData.all_transaction_count === 0)}
          emptyText="该账期暂无账单流水；请确认演示数据是否已初始化。"
          onRetry={() => void report.reload()}
        >
          {reportData && (
            <>
              <div className="stat-row">
                <div className="stat">
                  <span>账期</span>
                  <strong>{reportData.label}</strong>
                  <small>
                    {reportData.transaction_count} / {reportData.all_transaction_count} 笔交易
                  </small>
                </div>
                <div className="stat">
                  <span>总支出</span>
                  <strong>{formatCny(reportData.total_spend_cny)}</strong>
                  <small>{reportData.simulated ? '模拟数据' : '真实数据'}</small>
                </div>
                <div className="stat">
                  <span>环比（{reportData.comparison.baseline || '基线'}）</span>
                  <strong>{formatChangePct(reportData.comparison.change_pct)}</strong>
                  <small>{formatSignedCny(reportData.comparison.change_cny)}</small>
                </div>
                <div className="stat">
                  <span>Top 商户</span>
                  <strong>{reportData.top_merchants[0]?.merchant ?? '—'}</strong>
                  <small>
                    {reportData.top_merchants[0]
                      ? formatCny(reportData.top_merchants[0].amount_cny)
                      : '暂无'}
                  </small>
                </div>
              </div>

              <div className="panel-columns">
                <div>
                  <h3 className="sub-head">分类支出</h3>
                  {categories.length > 0 ? (
                    <div className="category-bars">
                      {categories.map(([category, amount]) => {
                        const usage = reportData.budget_usage.find((item) => item.category === category);
                        return (
                          <div
                            className={`category-bar ${usage?.over_budget ? 'is-over' : ''}`}
                            key={category}
                          >
                            <span>{categoryLabel(category)}</span>
                            <span className="bar-track">
                              <span
                                className="bar-fill"
                                style={{ width: `${Math.min(100, Math.round((amount / maxCategory) * 100))}%` }}
                              />
                            </span>
                            <span>{formatCny(amount)}</span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="inline-empty">该账期没有分类支出数据。</div>
                  )}

                  <h3 className="sub-head">预算使用</h3>
                  {reportData.budget_usage.length > 0 ? (
                    <div className="budget-list">
                      {reportData.budget_usage.map((budget) => (
                        <div
                          className={`budget-row ${budget.over_budget ? 'is-over' : ''}`}
                          key={budget.category}
                        >
                          <span>{categoryLabel(budget.category)}</span>
                          <span>
                            {formatCny(budget.spent_cny)} / {formatCny(budget.budget_cny)}
                            {budget.usage_pct === null ? '' : ` · ${formatRate(budget.usage_pct)}`}
                            {budget.over_budget ? ' · 超预算' : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="inline-empty">该账期没有预算配置。</div>
                  )}
                </div>

                <div>
                  <h3 className="sub-head">Top 商户</h3>
                  {reportData.top_merchants.length > 0 ? (
                    <ul className="list-stack">
                      {reportData.top_merchants.map((merchant) => (
                        <li className="list-item" key={`${merchant.merchant}-${merchant.category}`}>
                          <div className="item-main">
                            <strong>{merchant.merchant}</strong>
                            <small>
                              {categoryLabel(merchant.category)} · {merchant.count} 笔
                            </small>
                          </div>
                          <div className="item-end">{formatCny(merchant.amount_cny)}</div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="inline-empty">该账期没有商户支出数据。</div>
                  )}
                </div>
              </div>

              <p className="conclusion-note">{reportData.conclusion}</p>
            </>
          )}
        </ResourceState>

        <div className="panel-sub">
          <h3>异常检测（4 条确定性规则）</h3>
          <span className="muted">
            {anomalyData
              ? `${anomalyData.total} 条 · 高严重度 ${anomalyData.high_severity_count} 条`
              : '重复扣费 / 超预算 / 订阅涨价 / 凌晨交易'}
          </span>
        </div>
        <ResourceState
          loading={anomalies.loading}
          error={anomalies.error}
          empty={!anomalyData || anomalyData.anomalies.length === 0}
          emptyText="未发现异常扣费模式（按 4 条确定性规则检测后为空）。"
          onRetry={() => void anomalies.reload()}
        >
          {anomalyData && (
            <>
              <div className="anomaly-list">
                {anomalyData.anomalies.map((anomaly, index) => (
                  <article
                    className={`anomaly-item severity-${anomaly.severity}`}
                    key={`${anomaly.kind}-${index}`}
                  >
                    <div className="anomaly-head">
                      <span className={`chip ${anomaly.severity === 'high' ? 'chip-bad' : 'chip-warn'}`}>
                        {severityLabel(anomaly.severity)}严重度
                      </span>
                      <span className="chip">{anomaly.kind}</span>
                    </div>
                    <p>{anomaly.message}</p>
                    <details>
                      <summary>查看证据</summary>
                      <pre>{prettyEvidence(anomaly.evidence)}</pre>
                    </details>
                  </article>
                ))}
              </div>
              <p className="conclusion-note">{anomalyData.conclusion}</p>
            </>
          )}
        </ResourceState>
      </Panel>

      <Panel
        eyebrow="SUBSCRIPTIONS · CHARGES + REMINDERS"
        title="订阅扣费与续费提醒"
        meta={
          charges.data
            ? `${charges.data.total} 个扣费实体 · ${charges.data.unregistered_count} 个未登记`
            : '识别代扣与站内提醒'
        }
        actions={
          <RefreshButton
            loading={charges.loading || reminders.loading}
            onClick={() => {
              void charges.reload();
              void reminders.reload();
            }}
          />
        }
      >
        <div className="panel-columns">
          <div>
            <div className="panel-sub">
              <h3>订阅扣费识别</h3>
              <span className="muted">{charges.data?.window ?? '全部历史账单流水'}</span>
            </div>
            <ResourceState
              loading={charges.loading}
              error={charges.error}
              empty={chargeList.length === 0}
              emptyText="暂无订阅扣费记录；后端尚未返回订阅类目流水。"
              onRetry={() => void charges.reload()}
            >
              <ul className="list-stack">
                {chargeList.map((charge) => (
                  <li className="list-item" key={charge.merchant}>
                    <div className="item-main">
                      <strong>{charge.merchant}</strong>
                      <small>
                        累计 {formatCny(charge.total_spend_cny)} · 平均{' '}
                        {formatCny(charge.average_amount_cny)} · {charge.charge_count} 笔
                      </small>
                      <small>
                        最近扣费 {charge.latest_charge_date}（{formatCny(charge.latest_charge_cny)}）
                      </small>
                      <small>{charge.advice}</small>
                    </div>
                    <div className="item-end">
                      <span className={`chip ${charge.unregistered_debit ? 'chip-bad' : 'chip-good'}`}>
                        {charge.unregistered_debit ? '未登记代扣' : '已登记'}
                      </span>
                      <small>{charge.cycle ?? '未登记周期'}</small>
                    </div>
                  </li>
                ))}
              </ul>
              {charges.data?.conclusion && <p className="conclusion-note">{charges.data.conclusion}</p>}
            </ResourceState>
          </div>

          <div>
            <div className="panel-sub">
              <h3>续费提醒</h3>
              <span className="muted">
                窗口 {reminders.data?.days_ahead ?? 30} 天 · 仅站内提醒
              </span>
            </div>
            <ResourceState
              loading={reminders.loading}
              error={reminders.error}
              empty={reminderList.length === 0}
              emptyText="未来窗口内没有需要续费的订阅。"
              onRetry={() => void reminders.reload()}
            >
              <ul className="list-stack">
                {reminderList.map((reminder) => (
                  <li className="list-item" key={reminder.subscription_id}>
                    <div className="item-main">
                      <strong>{reminder.merchant}</strong>
                      <small>
                        {formatCny(reminder.amount_cny)} · {reminder.cycle} · 下次扣费{' '}
                        {reminder.next_charge_date}
                      </small>
                      <small>{reminder.advice}</small>
                    </div>
                    <div className="item-end">
                      <span
                        className={`chip ${
                          reminder.overdue
                            ? 'chip-bad'
                            : reminder.days_left <= 3
                              ? 'chip-warn'
                              : 'chip-teal'
                        }`}
                      >
                        {daysLeft(reminder.days_left, reminder.overdue)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              {reminders.data?.note && <p className="panel-note">{reminders.data.note}</p>}
            </ResourceState>
          </div>
        </div>
      </Panel>

      <Panel
        eyebrow="CARDS · APPLICATIONS"
        title="卡片申请状态"
        meta={applications.data ? `${applications.data.count} 条申请` : '虚拟卡 / 实体卡'}
        actions={
          <RefreshButton
            loading={applications.loading}
            onClick={() => void applications.reload()}
          />
        }
      >
        <ResourceState
          loading={applications.loading}
          error={applications.error}
          empty={applicationList.length === 0}
          emptyText="暂无卡片申请记录；可在任务控制台申请一张虚拟卡（模拟数据）。"
          onRetry={() => void applications.reload()}
        >
          <div className="table-scroll">
            <table className="compact-table">
              <thead>
                <tr>
                  <th>申请编号</th>
                  <th>状态</th>
                  <th>申请额度</th>
                  <th>卡片</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {applicationList.map((application) => (
                  <tr key={application.application_id}>
                    <td>
                      <strong>{application.application_id}</strong>
                      <small>{application.kind === 'virtual' ? '虚拟卡' : '实体卡'}</small>
                    </td>
                    <td>
                      <span className={`chip ${cardStatusClass(application.status)}`}>
                        {CARD_APPLICATION_STATUS_LABELS[application.status] ?? application.status}
                      </span>
                    </td>
                    <td>{formatCny(application.requested_limit_cny)}</td>
                    <td>
                      {application.card_id ?? '—'}
                      {application.masked_number && <small>{application.masked_number}</small>}
                    </td>
                    <td>{formatDateTime(application.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ResourceState>
      </Panel>

      <Panel
        eyebrow="AUTOMATION · TIME TRAVEL"
        title="自动化（时间维度）"
        meta={
          schedules.data
            ? `${taskList.length} 个定时任务 · ${goalList.length} 个预算目标 · ${giftList.length} 笔礼物订单`
            : '定时任务 / 预算目标 / 生日礼物'
        }
        actions={
          <RefreshButton
            loading={schedules.loading || goals.loading || gifts.loading}
            onClick={() => {
              void schedules.reload();
              void goals.reload();
              void gifts.reload();
            }}
          />
        }
      >
        <div className="automation-toolbar">
          <button
            className="primary-button small-button"
            onClick={() => void handleRunDue()}
            disabled={runBusy || writesBlocked}
            title={writesBlocked ? blockReason : 'POST /api/automation/run-due'}
          >
            {runBusy ? '时间快进中…' : '时间快进 · 执行到期任务'}
          </button>
          <small>
            {writesBlocked
              ? `写操作已禁用：${blockReason}`
              : '调用 POST /api/automation/run-due；只执行 run_at 已到期的模拟任务，失败会如实返回，不会假装成功。'}
          </small>
        </div>

        {runError && (
          <div className="alert alert-error" role="alert">
            时间快进失败：{runError}
          </div>
        )}

        {runResult && (
          <div className={`run-due-result ${runResult.failed_count > 0 ? 'has-failures' : ''}`}>
            <span className="eyebrow">RUN-DUE RESULT · {statusLabel(runResult.status)}</span>
            <p>
              {runResult.executed_count + runResult.failed_count === 0
                ? '本次没有到期的定时任务，调度器已正常返回。'
                : `已执行 ${runResult.executed_count} 项，失败 ${runResult.failed_count} 项。`}
              {runResult.now ? ` 模拟时间：${formatDateTime(runResult.now)}。` : ''}
            </p>
            {runResult.executed.length > 0 && (
              <ul>
                {runResult.executed.map((item, index) => (
                  <li key={`executed-${index}`}>
                    已执行 {taskKindLabel(item.kind)} {item.task_id ?? ''}
                    {typeof item.amount_cny === 'number' ? ` · ${formatCny(item.amount_cny)}` : ''}
                  </li>
                ))}
              </ul>
            )}
            {runResult.failed.length > 0 && (
              <ul className="run-due-failures">
                {runResult.failed.map((item, index) => (
                  <li key={`failed-${index}`}>
                    失败 {item.task_id ?? ''}：{item.reason ?? '未知原因'}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="panel-columns">
          <div>
            <div className="panel-sub">
              <h3>定时任务（schedules）</h3>
              <span className="muted">{taskList.length} 项</span>
            </div>
            <ResourceState
              loading={schedules.loading}
              error={schedules.error}
              empty={taskList.length === 0}
              emptyText="暂无定时任务。可在任务控制台输入「明天给妈妈转账 200 元」创建（模拟数据）。"
              onRetry={() => void schedules.reload()}
            >
              <ul className="list-stack">
                {taskList.map((task) => (
                  <li className="list-item" key={task.task_id}>
                    <div className="item-main">
                      <strong>{task.label || taskKindLabel(task.kind)}</strong>
                      <small>
                        {taskKindLabel(task.kind)} ·{' '}
                        {RECURRENCE_LABELS[task.recurrence] ?? task.recurrence} · 计划{' '}
                        {formatDateTime(task.run_at)}
                      </small>
                      <small>
                        最近执行 {task.last_run_at ? formatDateTime(task.last_run_at) : '未执行'}
                      </small>
                    </div>
                    <div className="item-end">
                      {typeof task.amount_cny === 'number' && (
                        <strong>{formatCny(task.amount_cny)}</strong>
                      )}
                      <span className={`chip ${taskStatusClass(task.status)}`}>
                        {TASK_STATUS_LABELS[task.status] ?? task.status}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </ResourceState>

            <div className="panel-sub">
              <h3>预算目标（goals）</h3>
              <span className="muted">{goalList.length} 项</span>
            </div>
            <ResourceState
              loading={goals.loading}
              error={goals.error}
              empty={goalList.length === 0}
              emptyText="暂无预算目标。可在任务控制台输入「为生日预算锁定 500 元」。"
              onRetry={() => void goals.reload()}
            >
              <ul className="list-stack">
                {goalList.map((goal) => (
                  <li className="list-item" key={goal.goal_id}>
                    <div className="item-main">
                      <strong>{goal.name}</strong>
                      <small>
                        已锁定 {formatCny(goal.locked_cny)} / 目标 {formatCny(goal.target_cny)}
                      </small>
                      <small>
                        截止 {goal.deadline ?? '未设置'} · 创建 {formatDateTime(goal.created_at)}
                      </small>
                    </div>
                    <div className="item-end">
                      <span className={`chip ${goalStatusClass(goal.status)}`}>
                        {GOAL_STATUS_LABELS[goal.status] ?? goal.status}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </ResourceState>
          </div>

          <div>
            <div className="panel-sub">
              <h3>生日礼物订单（orders）</h3>
              <span className="muted">{giftList.length} 笔</span>
            </div>
            <ResourceState
              loading={gifts.loading}
              error={gifts.error}
              empty={giftList.length === 0}
              emptyText="暂无生日礼物订单。创建生日预算后可预约鲜花或蛋糕（模拟数据）。"
              onRetry={() => void gifts.reload()}
            >
              <ul className="list-stack">
                {giftList.map((order) => (
                  <li className="list-item" key={order.order_id}>
                    <div className="item-main">
                      <strong>{order.gift_kind === 'flowers' ? '鲜花' : order.gift_kind === 'cake' ? '蛋糕' : order.gift_kind}</strong>
                      <small>
                        {order.order_id} · 送达 {formatDateTime(order.due_at)}
                      </small>
                      <small>{order.goal_id ? `关联预算 ${order.goal_id}` : '未关联预算目标'}</small>
                    </div>
                    <div className="item-end">
                      <strong>{formatCny(order.amount_cny)}</strong>
                      <span className={`chip ${orderStatusClass(order.status)}`}>
                        {ORDER_STATUS_LABELS[order.status] ?? order.status}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </ResourceState>

            <p className="panel-note">
              自动化场景只执行已到期的模拟任务；时间快进是显式调用，不会隐式触发真实资金动作。
            </p>
          </div>
        </div>
      </Panel>
    </section>
  );
}
