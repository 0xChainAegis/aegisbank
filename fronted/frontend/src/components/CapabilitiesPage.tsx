import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchImHelp,
  fetchSandboxPolicy,
  runSandboxDemo,
  sendImMessage,
} from '../api';
import type { AegisRole } from '../roles';
import {
  canRunSandboxDemo,
  canSendImMessage,
  isReadOnlyRole,
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
} from '../roles';
import type {
  ImChannelName,
  ImHelp,
  ImMessageReply,
  MfaProvider,
  MfaProvidersResponse,
  SandboxDemoKind,
  SandboxDemoResult,
  SandboxPolicyResponse,
} from '../types';
import {
  MFA_DEMO_TOKENS,
  formatBytes,
  sandboxDemoSummary,
  sandboxEventLabel,
  sandboxKindLabel,
  sandboxViolationLabel,
} from '../twoA';
import { ResourceState, StatusPill, ToneChip } from './ui';

interface Props {
  writesBlocked: boolean;
  role: AegisRole;
  mfa: MfaProvidersResponse | null;
  mfaLoading: boolean;
  mfaError: string;
  onRefreshMfa: () => void;
}

const SANDBOX_KINDS: SandboxDemoKind[] = ['network', 'slow', 'oversize'];

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function newMessageId(): string {
  return `ui-im-${Date.now().toString(36)}`;
}

export default function CapabilitiesPage({
  writesBlocked,
  role,
  mfa,
  mfaLoading,
  mfaError,
  onRefreshMfa,
}: Props) {
  const [sandbox, setSandbox] = useState<SandboxPolicyResponse | null>(null);
  const [sandboxLoading, setSandboxLoading] = useState(true);
  const [sandboxError, setSandboxError] = useState('');
  const [demoResult, setDemoResult] = useState<SandboxDemoResult | null>(null);
  const [demoRunning, setDemoRunning] = useState<SandboxDemoKind | ''>('');
  const [demoError, setDemoError] = useState('');

  const [help, setHelp] = useState<ImHelp | null>(null);
  const [helpLoading, setHelpLoading] = useState(true);
  const [helpError, setHelpError] = useState('');
  const [channel, setChannel] = useState<ImChannelName>('im');
  const [senderId, setSenderId] = useState('alice');
  const [messageId, setMessageId] = useState(newMessageId);
  const [text, setText] = useState('查询我的本月账单');
  const [reply, setReply] = useState<ImMessageReply | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');

  const loadSandbox = useCallback(async () => {
    setSandboxLoading(true);
    setSandboxError('');
    try {
      setSandbox(await fetchSandboxPolicy());
    } catch (caught) {
      setSandbox(null);
      setSandboxError(messageOf(caught, '无法读取沙箱策略'));
    } finally {
      setSandboxLoading(false);
    }
  }, []);

  const loadHelp = useCallback(async () => {
    setHelpLoading(true);
    setHelpError('');
    try {
      setHelp(await fetchImHelp());
    } catch (caught) {
      setHelp(null);
      setHelpError(messageOf(caught, '无法读取 IM 渠道帮助'));
    } finally {
      setHelpLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSandbox();
    void loadHelp();
  }, [loadHelp, loadSandbox]);

  const sandboxAllowed = !writesBlocked && canRunSandboxDemo(role);
  const imAllowed = !writesBlocked && canSendImMessage(role);
  const providerCards = useMemo(() => mfa?.providers ?? [], [mfa]);

  async function runDemo(kind: SandboxDemoKind) {
    if (!sandboxAllowed || demoRunning) return;
    setDemoRunning(kind);
    setDemoError('');
    try {
      setDemoResult(await runSandboxDemo(kind));
    } catch (caught) {
      setDemoResult(null);
      setDemoError(messageOf(caught, '沙箱演示失败'));
    } finally {
      setDemoRunning('');
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!imAllowed || sending || !text.trim() || !senderId.trim()) return;
    setSending(true);
    setSendError('');
    setReply(null);
    try {
      setReply(
        await sendImMessage({
          channel,
          sender_id: senderId.trim(),
          message_id: messageId.trim() || null,
          text: text.trim(),
        }),
      );
      setMessageId(newMessageId());
    } catch (caught) {
      setSendError(messageOf(caught, 'IM 消息发送失败'));
    } finally {
      setSending(false);
    }
  }

  function fillExample(payload: Record<string, unknown>) {
    const nextChannel = payload.channel;
    if (nextChannel === 'im' || nextChannel === 'cli' || nextChannel === 'webhook') {
      setChannel(nextChannel);
    }
    if (typeof payload.sender_id === 'string') setSenderId(payload.sender_id);
    if (typeof payload.message_id === 'string') setMessageId(payload.message_id);
    if (typeof payload.text === 'string') setText(payload.text);
  }

  return (
    <section className="page-stack capabilities-page">
      <div className="page-heading capabilities-heading">
        <div>
          <span className="eyebrow">STAGE 2A CAPABILITIES</span>
          <h1>2A 能力面板</h1>
          <p>
            演示 MFA Provider、工具沙箱与 IM 渠道适配器。所有演示仍复用统一
            Planner、动态风险、权限网关、确认流程与 SHA-256 审计链；不改变核心执行路径。
          </p>
        </div>
        <span className="role-pill">当前角色 {ROLE_LABELS[role]}</span>
      </div>

      <div className="role-banner card capability-role-card">
        <div>
          <span className="eyebrow">ROLE NOTE</span>
          <strong>{ROLE_LABELS[role]}</strong>
          <p>{ROLE_DESCRIPTIONS[role]}</p>
          {isReadOnlyRole(role) && (
            <span className="chip chip-warn">审计员只读：沙箱演示与 IM 写入已禁用，可读取策略与帮助。</span>
          )}
        </div>
      </div>

      <div className="card capability-card">
        <div className="section-head compact-head">
          <div>
            <span className="eyebrow">MFA PROVIDERS</span>
            <h2>演示 MFA Provider</h2>
          </div>
          <div className="panel-head-meta">
            {mfa?.default && <span className="chip chip-teal">默认 {mfa.default}</span>}
            <button className="text-button" onClick={onRefreshMfa} disabled={mfaLoading}>
              {mfaLoading ? '同步中…' : '刷新 provider'}
            </button>
          </div>
        </div>
        <p className="panel-note">
          数据来自 <code>GET /api/mfa/providers</code>。红色操作确认弹窗会在 OTP 与模拟生物识别之间选择，
          并把 <code>mfa_provider</code> 随确认请求提交给后端。
        </p>
        <ResourceState
          loading={mfaLoading}
          error={mfaError}
          empty={providerCards.length === 0}
          emptyText="后端尚未注册任何 MFA provider。"
          onRetry={onRefreshMfa}
        >
          <div className="mfa-provider-grid">
            {providerCards.map((provider: MfaProvider) => (
              <article className={`mfa-provider-card ${provider.default ? 'is-default' : ''}`} key={provider.name}>
                <div className="mfa-provider-top">
                  <strong>{provider.title}</strong>
                  <ToneChip tone={provider.name === 'biometric' ? 'warn' : 'good'}>
                    {provider.kind}
                  </ToneChip>
                  {provider.default && <span className="chip chip-teal">默认</span>}
                </div>
                <code>{provider.name}</code>
                <p>{provider.hint}</p>
                <div className="mfa-provider-token">
                  演示 token：<code>{MFA_DEMO_TOKENS[provider.name] ?? '—'}</code>
                  {provider.demo_token_format && <span>格式 {provider.demo_token_format}</span>}
                </div>
              </article>
            ))}
          </div>
          {mfa?.note && <p className="panel-note">{mfa.note}</p>}
        </ResourceState>
      </div>

      <div className="card capability-card">
        <div className="section-head compact-head">
          <div>
            <span className="eyebrow">TOOL SANDBOX</span>
            <h2>工具执行沙箱</h2>
          </div>
          <div className="panel-head-meta">
            <ToneChip tone={sandbox?.enabled ? 'good' : 'warn'}>
              {sandbox?.enabled ? '沙箱已启用' : '沙箱未启用'}
            </ToneChip>
            <button className="text-button" onClick={() => void loadSandbox()} disabled={sandboxLoading}>
              {sandboxLoading ? '同步中…' : '刷新策略'}
            </button>
          </div>
        </div>
        <p className="panel-note">
          策略来自 <code>GET /api/sandbox/policy</code>；三个按钮会调用
          <code> POST /api/sandbox/demo/run</code>，在真实执行器上验证网络阻断、超时与输出上限，
          拦截事件写入审计链。
        </p>
        <ResourceState
          loading={sandboxLoading}
          error={sandboxError}
          empty={!sandbox}
          emptyText="后端尚未返回沙箱策略。"
          onRetry={() => void loadSandbox()}
        >
          {sandbox && (
            <>
              <dl className="trust-facts sandbox-facts">
                <div><dt>执行器</dt><dd><code>{sandbox.executor ?? '—'}</code></dd></div>
                <div><dt>超时上限</dt><dd>{sandbox.timeout_seconds} 秒</dd></div>
                <div><dt>输出上限</dt><dd>{formatBytes(sandbox.max_output_bytes)}</dd></div>
                <div><dt>入参上限</dt><dd>{formatBytes(sandbox.max_argument_bytes)}</dd></div>
                <div><dt>网络阻断</dt><dd>{sandbox.block_network ? '开启' : '关闭'}</dd></div>
                <div><dt>工具白名单</dt><dd>{sandbox.tool_whitelist_enforced ? sandbox.allowed_tools.join(', ') || '空' : '未启用'}</dd></div>
              </dl>
              <div className="sandbox-demo-buttons">
                {SANDBOX_KINDS.map((kind) => (
                  <button
                    className="scenario-action"
                    key={kind}
                    onClick={() => void runDemo(kind)}
                    disabled={!sandboxAllowed || Boolean(demoRunning)}
                    title={
                      sandboxAllowed
                        ? `执行 ${sandboxKindLabel(kind)} 演示`
                        : '审计员只读：不能触发工具执行演示'
                    }
                  >
                    <span className="scenario-action-head">
                      <strong>{sandboxKindLabel(kind)}</strong>
                      <ToneChip tone={kind === 'slow' ? 'warn' : 'bad'}>DEMO</ToneChip>
                    </span>
                    <small>
                      {demoRunning === kind
                        ? '演示执行中…'
                        : kind === 'network'
                          ? '尝试 socket 连接 → 期望被网络盾拦截'
                          : kind === 'slow'
                            ? '休眠超过超时上限 → 期望超时中止'
                            : '返回超过输出上限 → 期望结果被拒绝'}
                    </small>
                  </button>
                ))}
              </div>
              {!sandboxAllowed && (
                <div className="alert alert-warn">
                  当前角色 {role} 为只读审计视角，沙箱演示按钮已禁用；策略仍可查看。
                </div>
              )}
              <div className="sandbox-result-area">
                {demoRunning && (
                  <div className="inline-loading" role="status">
                    <span className="loading-spinner" aria-hidden="true" />
                    <span>正在通过真实执行器运行沙箱演示…</span>
                  </div>
                )}
                {demoError && <div className="inline-error" role="alert">{demoError}</div>}
                {!demoRunning && !demoError && !demoResult && (
                  <div className="inline-empty">选择上方任一演示，查看 blocked / reason / 审计事件。</div>
                )}
                {demoResult && (
                  <div className={`sandbox-result ${demoResult.blocked ? 'is-blocked' : 'is-allowed'}`}>
                    <div className="sandbox-result-head">
                      <ToneChip tone={demoResult.blocked ? 'good' : 'bad'}>
                        {demoResult.blocked ? 'BLOCKED' : 'NOT BLOCKED'}
                      </ToneChip>
                      <strong>{sandboxKindLabel(demoResult.kind)}</strong>
                      {demoResult.event && <span className="chip chip-teal">审计事件 {sandboxEventLabel(demoResult.event)}</span>}
                      {demoResult.violation && <span className="chip chip-warn">{sandboxViolationLabel(demoResult.violation)}</span>}
                    </div>
                    <p>{sandboxDemoSummary(demoResult)}</p>
                    <dl className="sandbox-result-facts">
                      <div><dt>工具</dt><dd><code>{demoResult.tool_name ?? '—'}</code></dd></div>
                      <div><dt>沙箱</dt><dd>{demoResult.sandbox_enabled ? '启用' : '未启用'}</dd></div>
                      <div><dt>审计事件</dt><dd><code>{demoResult.event ?? '无'}</code></dd></div>
                    </dl>
                  </div>
                )}
              </div>
            </>
          )}
        </ResourceState>
      </div>

      <div className="card capability-card">
        <div className="section-head compact-head">
          <div>
            <span className="eyebrow">IM CHANNEL ADAPTER</span>
            <h2>IM 渠道适配器</h2>
          </div>
          <button className="text-button" onClick={() => void loadHelp()} disabled={helpLoading}>
            {helpLoading ? '同步中…' : '刷新帮助'}
          </button>
        </div>
        <p className="panel-note">
          IM 只是入口：消息会复用同一 Planner / 风险引擎 / 权限网关 / 确认流程 / 审计链。
          <code> message_id</code> 作为幂等键，重复提交返回首次回执，不会二次执行。
        </p>
        <ResourceState
          loading={helpLoading}
          error={helpError}
          empty={!help}
          emptyText="后端尚未返回 IM 渠道帮助。"
          onRetry={() => void loadHelp()}
        >
          {help && (
            <>
              <div className="im-help">
                <div>
                  <span className="eyebrow">CONFIRMATION SYNTAX</span>
                  <ul>
                    {help.confirmation_syntax.map((item) => <li key={item}><code>{item}</code></li>)}
                  </ul>
                </div>
                <div>
                  <span className="eyebrow">DEMO OTP</span>
                  <strong><code>{help.demo_otp}</code></strong>
                  <span className="muted">仅本地演示；生产环境必须接入真实 MFA。</span>
                </div>
              </div>

              <form className="im-form" onSubmit={submit}>
                <div className="im-form-row">
                  <label>
                    <span>渠道</span>
                    <select value={channel} onChange={(event) => setChannel(event.target.value as ImChannelName)}>
                      {help.channels.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>发送者</span>
                    <input
                      value={senderId}
                      onChange={(event) => setSenderId(event.target.value)}
                      maxLength={64}
                      placeholder="alice"
                    />
                  </label>
                  <label>
                    <span>message_id（幂等键）</span>
                    <input
                      value={messageId}
                      onChange={(event) => setMessageId(event.target.value)}
                      maxLength={96}
                      placeholder="可选"
                    />
                  </label>
                </div>
                <label className="im-message-field">
                  <span>消息正文</span>
                  <textarea
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    rows={3}
                    maxLength={2000}
                    placeholder="例如：挂失 CARD-9902"
                  />
                </label>
                {!imAllowed && (
                  <div className="alert alert-warn">
                    当前角色 {role} 不能发送 IM 指令：适配器始终以 user 身份执行银行操作，非 user 角色仅可查看帮助。
                  </div>
                )}
                <div className="im-form-actions">
                  <span className="muted">message_id 相同即回放首次回执；重试失败确认请换新 id。</span>
                  <button
                    className="primary-button"
                    type="submit"
                    disabled={!imAllowed || sending || !text.trim() || !senderId.trim()}
                  >
                    {sending ? '发送中…' : '发送 IM 消息'}
                  </button>
                </div>
              </form>

              <div className="sandbox-result-area">
                {sending && (
                  <div className="inline-loading" role="status">
                    <span className="loading-spinner" aria-hidden="true" />
                    <span>IM 消息正在经过统一执行链路…</span>
                  </div>
                )}
                {sendError && <div className="inline-error" role="alert">{sendError}</div>}
                {!sending && !sendError && !reply && (
                  <div className="inline-empty">发送一条 IM 消息，查看回执、状态与确认话术。</div>
                )}
                {reply && (
                  <div className="im-receipt">
                    <div className="im-receipt-head">
                      <StatusPill status={reply.status} />
                      <span className="chip chip-teal">{reply.channel}</span>
                      <span className="chip">sender {reply.sender_id}</span>
                      {reply.message_id && <span className="chip">id {reply.message_id}</span>}
                      {reply.replayed && <span className="chip chip-warn">幂等回放</span>}
                    </div>
                    <pre className="im-receipt-text">{reply.text}</pre>
                    {reply.confirmation?.id && (
                      <div className="im-confirmation-command">
                        <span className="eyebrow">CONFIRMATION COMMAND</span>
                        <code>确认 {reply.confirmation.id} 验证码 {help.demo_otp}</code>
                        <small>实际发送时把 &lt;6 位动态验证码&gt; 替换为演示 OTP；确认成功后会执行原计划。</small>
                      </div>
                    )}
                    <details>
                      <summary>查看结构化回执</summary>
                      <pre>{JSON.stringify(reply.structured, null, 2)}</pre>
                    </details>
                  </div>
                )}
              </div>

              <div className="im-examples">
                <span className="eyebrow">HELP EXAMPLES</span>
                <div className="im-example-list">
                  {help.examples.map((example) => (
                    <button
                      className="im-example"
                      key={example.label}
                      onClick={() => fillExample(example.payload)}
                      type="button"
                    >
                      <strong>{example.label}</strong>
                      <small>{String(example.payload.text ?? '')}</small>
                      <code>{String(example.payload.channel ?? 'im')}</code>
                    </button>
                  ))}
                </div>
              </div>
              <p className="panel-note">{help.policy}</p>
            </>
          )}
        </ResourceState>
      </div>
    </section>
  );
}