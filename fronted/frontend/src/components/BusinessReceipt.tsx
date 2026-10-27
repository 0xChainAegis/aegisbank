import { formatCny } from '../risk';
import type { RunResponse } from '../types';

const categoryLabels: Record<string, string> = {
  food: '餐饮', shopping: '购物', subscription: '订阅', transport: '交通',
};

function text(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function money(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? formatCny(value) : '金额未返回';
}

function cardStatus(value: unknown): string {
  const status = text(value, '').toLowerCase();
  if (status === 'active' || status === '正常') return '正常';
  if (status === 'lost' || status === '已挂失') return '已挂失';
  if (!status) return '状态未返回';
  if (status === 'unknown') return '状态未知';
  return `未识别状态（${text(value, '')}）`;
}

export default function BusinessReceipt({ run }: { run: RunResponse }) {
  if (run.status !== 'completed') return null;
  const results = run.results?.filter((item) =>
    ['query_bill', 'transfer', 'report_card_lost', 'unlock_card'].includes(item.tool_name));
  if (!results?.length) return null;
  return (
    <div className="business-receipts">
      {results.map((result, index) => {
        const data = result.data ?? {};
        if (result.tool_name === 'query_bill') {
          const { total_spend_cny: total, categories, anomalies, month } = data;
          const hasCategories = categories !== null && typeof categories === 'object' && !Array.isArray(categories);
          const entries = hasCategories ? Object.entries(categories) : [];
          const notes = Array.isArray(anomalies)
            ? anomalies.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())) : [];
          return (
            <section className="business-receipt business-receipt-bill" aria-label="账单查询结果" key={index}>
              <h3>账单查询结果</h3>
              <p>账期：{text(month, '账期未返回')}</p>
              <p>支出合计 <strong className="receipt-business-amount">{money(total)}</strong></p>
              {entries.length > 0 ? (
                <dl className="bill-categories">
                  {entries.map(([category, amount]) => (
                    <div key={category}><dt>{categoryLabels[category] ?? category}</dt><dd>{money(amount)}</dd></div>
                  ))}
                </dl>
              ) : <p className="receipt-business-notice">{hasCategories ? '该账期暂无分类支出。' : '分类明细未返回。'}</p>}
              {notes.length > 0 ? <ul>{notes.map((note, noteIndex) => <li key={noteIndex}>{note}</li>)}</ul>
                : <p className="receipt-business-notice">{Array.isArray(anomalies) && anomalies.length === 0
                  ? '本次查询未返回异常提示。' : '异常分析未返回。'}</p>}
              <small>来源：本次模拟银行查询回执</small>
            </section>
          );
        }
        if (result.tool_name === 'transfer') {
          const status = text(data.status, '状态未返回');
          return (
            <section className="business-receipt business-receipt-transfer" aria-label="转账回执" key={index}>
              <h3>转账回执</h3>
              <p>转账金额 <strong className="receipt-business-amount">{money(data.amount_cny)}</strong></p>
              <dl className="receipt-business-facts">
                <div><dt>转出账户</dt><dd>{text(data.from_account, '转出账户未返回')}</dd></div>
                <div><dt>收款账户</dt><dd>{text(data.to_account, '收款账户未返回')}</dd></div>
                <div><dt>交易状态</dt><dd>{status === 'simulated_success' ? '模拟转账成功' : status}</dd></div>
                <div><dt>交易编号</dt><dd>{text(data.transaction_id, '交易编号未返回')}</dd></div>
              </dl>
              <small>来源：本次模拟银行执行回执；不涉及真实资金。</small>
            </section>
          );
        }
        const title = result.tool_name === 'report_card_lost' ? '卡片挂失回执' : '卡片解挂回执';
        return (
          <section className="business-receipt business-receipt-card" aria-label={title} key={index}>
            <h3>{title}</h3>
            <dl className="receipt-business-facts">
              <div><dt>操作卡片</dt><dd>{text(data.card_id, '卡片编号未返回')}</dd></div>
              <div><dt>返回状态</dt><dd>{cardStatus(data.status)}</dd></div>
            </dl>
            <small>来源：本次模拟银行执行回执。</small>
          </section>
        );
      })}
    </div>
  );
}
