import { formatCny } from '../risk';
import type { RunResponse } from '../types';

const categoryLabels: Record<string, string> = {
  food: '餐饮', shopping: '购物', subscription: '订阅', transport: '交通',
};

export default function BusinessReceipt({ run }: { run: RunResponse }) {
  if (run.status !== 'completed') return null;
  const bill = run.results?.find((item) => item.tool_name === 'query_bill');
  if (!bill) return null;
  const { total_spend_cny: total, categories, anomalies, month } = bill.data;
  const entries = categories && typeof categories === 'object' && !Array.isArray(categories)
    ? Object.entries(categories) : [];
  const notes = Array.isArray(anomalies) ? anomalies.filter((item): item is string => typeof item === 'string') : [];
  return (
    <section className="business-receipt" aria-label="账单查询结果">
      <h3>账单查询结果</h3>
      {typeof month === 'string' && month && <p>账期：{month}</p>}
      <p>支出合计 <strong>{typeof total === 'number' && Number.isFinite(total) ? formatCny(total) : '金额未返回'}</strong></p>
      {entries.length > 0 && (
        <dl className="bill-categories">
          {entries.map(([category, amount]) => (
            <div key={category}><dt>{categoryLabels[category] ?? category}</dt>
              <dd>{typeof amount === 'number' && Number.isFinite(amount) ? formatCny(amount) : '金额未返回'}</dd></div>
          ))}
        </dl>
      )}
      {notes.length > 0 && <ul>{notes.map((note, index) => <li key={index}>{note}</li>)}</ul>}
      <small>来源：本次模拟银行查询回执</small>
    </section>
  );
}
