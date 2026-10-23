import { useEffect, useMemo, useState } from 'react';
import type { AegisRole } from '../roles';
import { canManagePermissions, rolePermissionBlockReason } from '../roles';
import type { ToolMetadata } from '../types';
import { compensationBadge } from '../twoA';
import { paginate } from '../viewModel';
import { CompensationBadge, LoadingState, PageAlerts, RiskBadge } from './ui';

interface Props {
  role: AegisRole;
  tools: ToolMetadata[];
  loading: boolean;
  error: string;
  notice: string;
  busyTool: string;
  onToggle: (tool: ToolMetadata) => void;
  onRefresh: () => void;
}

const PAGE_SIZE = 6;

export default function PermissionsPage({
  role,
  tools,
  loading,
  error,
  notice,
  busyTool,
  onToggle,
  onRefresh,
}: Props) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const canManage = canManagePermissions(role);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return tools;
    return tools.filter((tool) =>
      [tool.name, tool.title, tool.description, tool.permission]
        .join(' ')
        .toLowerCase()
        .includes(keyword),
    );
  }, [tools, query]);

  const view = useMemo(() => paginate(filtered, page, PAGE_SIZE), [filtered, page]);

  useEffect(() => {
    setPage((current) => Math.min(current, view.totalPages));
  }, [view.totalPages]);

  if (loading && tools.length === 0) {
    return (
      <section className="page-stack">
        <div className="page-heading">
          <span className="eyebrow">USER-CONTROLLED AUTHORIZATION</span>
          <h1>权限控制台</h1>
          <p>授权颗粒度精确到工具。撤回后，后续调用会在进入调度器前被统一网关拦截。</p>
        </div>
        <LoadingState label="正在同步工具权限…" />
      </section>
    );
  }

  return (
    <section className="page-stack">
      <div className="page-heading permissions-heading">
        <div>
          <span className="eyebrow">USER-CONTROLLED AUTHORIZATION</span>
          <h1>权限控制台</h1>
          <p>授权颗粒度精确到工具。授权或撤回后会立即通过后端刷新，所有调用继续经过统一权限网关。</p>
        </div>
        <button className="ghost-button" onClick={onRefresh} disabled={loading}>
          {loading ? '刷新中…' : '刷新权限'}
        </button>
      </div>

      <PageAlerts error={error} notice={notice} />

      {!canManage && (
        <div className="alert alert-warn" role="status">
          {rolePermissionBlockReason(role)} 当前角色：{role}。
        </div>
      )}

      <div className="permission-toolbar card">
        <div>
          <span className="eyebrow">TOOL REGISTRY</span>
          <strong>{filtered.length} / {tools.length} 个工具</strong>
        </div>
        <label className="search-field">
          <span className="sr-only">搜索工具</span>
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder="搜索工具名、权限或描述…"
          />
        </label>
        <div className="permission-legend">
          <span><i className="rule-dot dot-green" />GREEN 查询</span>
          <span><i className="rule-dot dot-yellow" />YELLOW 设置</span>
          <span><i className="rule-dot dot-red" />RED 资金/卡风险</span>
        </div>
      </div>

      <div className="card table-card">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>工具节点</th>
                <th>动态风险</th>
                <th>最小权限</th>
                <th>可撤销性</th>
                <th>当前状态</th>
                <th aria-label="操作" />
              </tr>
            </thead>
            <tbody>
              {view.items.map((tool) => (
                <tr key={tool.name}>
                  <td>
                    <strong>{tool.title}</strong>
                    <small>{tool.description}</small>
                    <code className="tool-name-code">{tool.name}</code>
                  </td>
                  <td><RiskBadge risk={tool.risk_level} verbose /></td>
                  <td><code>{tool.permission}</code></td>
                  <td>
                    <CompensationBadge
                      info={compensationBadge(
                        tool.compensable === true,
                        tool.risk_level,
                        tool.compensation_tool,
                      )}
                    />
                  </td>
                  <td>
                    <span className={tool.granted ? 'grant-on' : 'grant-off'}>
                      {tool.granted ? '已授权' : '已撤回'}
                    </span>
                  </td>
                  <td className="table-action">
                    <button
                      className={tool.granted ? 'danger-button' : 'primary-button small-button'}
                      onClick={() => onToggle(tool)}
                      disabled={Boolean(busyTool) || !canManage}
                      title={canManage ? undefined : '审计员只读：不能修改工具授权'}
                    >
                      {busyTool === tool.name ? '处理中…' : tool.granted ? '撤回' : '授予'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {view.total === 0 && <div className="inline-empty">没有匹配的工具。</div>}
      </div>

      <div className="pagination card">
        <span>
          显示 {view.start}–{view.end} 项 · 共 {view.total} 项
        </span>
        <div className="pagination-controls">
          <button
            className="ghost-button small-button"
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            disabled={view.page <= 1}
          >
            上一页
          </button>
          <span>第 {view.page} / {view.totalPages} 页</span>
          <button
            className="ghost-button small-button"
            onClick={() => setPage((current) => Math.min(view.totalPages, current + 1))}
            disabled={view.page >= view.totalPages}
          >
            下一页
          </button>
        </div>
      </div>

      <div className="policy-note card">
        <span className="eyebrow">DEFAULT POLICY</span>
        <div>
          <strong>绿色操作</strong> 仅需最小权限即可静默执行；<strong>黄色操作</strong>
          需要 5 分钟内确认；<strong>红色操作</strong>必须 MFA/OTP 二次校验。单笔转账 &gt; ¥5,000
          或今日累计 &gt; ¥1,000、交易额度 &gt; ¥5,000、挂失/解挂均按红色处理。高风险工具的授权撤回立即生效。
        </div>
      </div>
    </section>
  );
}
