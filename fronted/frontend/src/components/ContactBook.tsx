import { fetchContacts } from '../api';
import { useResource } from './ScenariosPage';
import { ResourceState } from './ui';

const RELATION_LABELS: Record<string, string> = {
  mother: '母亲', father: '父亲', friend: '好友', colleague: '同事',
  spouse: '配偶', family: '家人', other: '其他关系',
};

function relationLabel(value: string | null): string {
  const relation = value?.trim();
  if (!relation) return '联系人';
  return RELATION_LABELS[relation.toLowerCase()]
    ?? (/[\u3400-\u9fff]/.test(relation) ? relation : '关系未分类');
}

export default function ContactBook() {
  const resource = useResource(fetchContacts, '无法加载联系人');
  const contacts = resource.data?.contacts ?? [];

  return (
    <section className="card contact-book" id="contact-book" aria-labelledby="contact-book-title">
      <div className="section-head">
        <div>
          <h2 id="contact-book-title" data-care-reading="true">联系人</h2>
          <p className="panel-note">转账前请先核对姓名或别名，手机号和收款账户按后端脱敏结果显示。</p>
        </div>
        <button type="button" className="ghost-button small-button" disabled={resource.loading}
          onClick={() => void resource.reload()}>刷新联系人</button>
      </div>
      <ResourceState loading={resource.loading} error={resource.error}
        empty={contacts.length === 0} emptyText="暂无联系人。"
        onRetry={() => void resource.reload()}>
        <div className="contact-grid">
          {contacts.map((contact) => (
            <article className="contact-card" key={contact.contact_id}>
              <div className="contact-top" data-care-reading="true">
                <strong>{contact.name?.trim() || '姓名未返回'}</strong>
                <span className="chip chip-teal">{relationLabel(contact.relation)}</span>
              </div>
              <dl className="mini-facts">
                <div data-care-reading="true">
                  <dt>别名</dt><dd>{contact.alias?.trim() || '未设置'}</dd>
                </div>
                <div data-care-private="true">
                  <dt>手机号</dt><dd>{contact.phone?.trim() || '未返回'}</dd>
                </div>
                <div data-care-private="true">
                  <dt>收款账户</dt><dd>{contact.account_id?.trim() || '未返回'}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </ResourceState>
    </section>
  );
}
