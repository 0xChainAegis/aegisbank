import { useEffect, useMemo, useRef, useState } from 'react';
import {
  collectRiskReasons,
  confirmationSummary,
  formatDateTime,
  runRiskLevel,
  stepRiskLevel,
} from '../viewModel';
import type { MfaProvider, RunResponse } from '../types';
import { formatRemaining, remainingSeconds } from '../session';
import {
  MFA_DEMO_TOKENS,
  defaultMfaProvider,
  isMfaTokenComplete,
  mfaProviderHint,
  mfaProviderLabel,
  mfaTokenPlaceholder,
  sanitizeMfaToken,
} from '../twoA';
import { EvidenceBadges, ResourceState, RiskBadge } from './ui';

const YELLOW_GATEWAY_REASON = '黄色操作涉及资金变动或账户设置，需要在 5 分钟内完成一次轻量确认。';
const LEGACY_YELLOW_GATEWAY_REASON = '黄色操作会修改账户设置，需要在 5 分钟内完成一次轻量确认。';
const RED_GATEWAY_REASON = '红色操作涉及资金变动，需要二次身份校验并明确确认。';

interface Props {
  pending: RunResponse;
  busy: boolean;
  mfaToken: string;
  setMfaToken: (value: string) => void;
  mfaProvider: string;
  setMfaProvider: (value: string) => void;
  mfaProviders: MfaProvider[];
  mfaProvidersLoading: boolean;
  mfaProvidersError: string;
  onRefreshMfaProviders: () => void;
  onDecision: (approved: boolean, provider?: string) => void;
  /** 稍后处理：关闭弹窗但保留待确认快照（UX-11）。 */
  onClose: () => void;
  error?: string;
  writesBlocked: boolean;
  blockReason: string;
  accountLabels?: Record<string, string>;
}

export default function ConfirmationModal({
  pending,
  busy,
  mfaToken,
  setMfaToken,
  mfaProvider,
  setMfaProvider,
  mfaProviders,
  mfaProvidersLoading,
  mfaProvidersError,
  onRefreshMfaProviders,
  onDecision,
  onClose,
  error,
  writesBlocked,
  blockReason,
  accountLabels,
}: Props) {
  const risk = runRiskLevel(pending);
  const needsOtp = Boolean(pending.confirmation?.requires_reauth) || risk === 'red';
  const reasons = collectRiskReasons(pending);
  const fixedGatewayReason = pending.reason === YELLOW_GATEWAY_REASON
    || pending.reason === LEGACY_YELLOW_GATEWAY_REASON
    || pending.reason === RED_GATEWAY_REASON;
  const reason = fixedGatewayReason
    ? needsOtp ? '本次操作需要身份验证和你的确认。' : '本次操作需要你的确认。'
    : pending.reason;
  const enabledProviders = mfaProviders.filter((provider) => provider.enabled !== false);
  const fallbackProvider: MfaProvider[] = [
    { name: 'otp', kind: 'otp', title: '演示动态验证码', enabled: true, default: true },
  ];
  const providerOptions = enabledProviders.length > 0 ? enabledProviders : fallbackProvider;
  const selectedProvider = providerOptions.some((provider) => provider.name === mfaProvider)
    ? mfaProvider
    : defaultMfaProvider(providerOptions);
  const tokenComplete = isMfaTokenComplete(selectedProvider, mfaToken);
  const providerEmpty = !mfaProvidersLoading && !mfaProvidersError && enabledProviders.length === 0;

  const steps = useMemo(() => (pending.plan?.steps ?? []).map((step) => ({
    step,
    summary: confirmationSummary(step, accountLabels),
    risk: stepRiskLevel(step.risk_level, pending),
  })), [pending, accountLabels]);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = remainingSeconds(pending.confirmation?.expires_at, now);
  const expired = Boolean(pending.confirmation?.expires_at) && remaining <= 0;

  const dialogRef = useRef<HTMLElement | null>(null);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // 焦点管理（UX-11）：打开时移入弹窗、Tab 首尾循环、ESC 关闭、关闭后焦点还原。
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialogRef.current;
    const focusables = (): HTMLElement[] => {
      if (!node) return [];
      return Array.from(
        node.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null || element === document.activeElement);
    };
    focusables()[0]?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busyRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      // 触发按钮在 busy 期间可能已被禁用，导致 previous 退化为 body；退回指令输入区。
      const target =
        previous && previous !== document.body
          ? previous
          : document.getElementById('instruction');
      target?.focus?.();
    };
    // 只挂载一次：onClose 用 ref 读取最新值，避免倒计时每秒重挂载。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const decisionDisabled = busy || writesBlocked || expired;

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="modal card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        ref={(node) => {
          dialogRef.current = node;
        }}
      >
        <div className="modal-top">
          <div className="modal-top-tags">
            <RiskBadge risk={risk} verbose />
            <span className="eyebrow">需要你确认</span>
          </div>
          <div className="modal-top-actions">
            {pending.confirmation?.expires_at && (
              <span className={`modal-expiry ${expired ? 'is-expired' : ''}`}>
                {expired ? '已过期' : `剩余 ${formatRemaining(remaining)}`}
              </span>
            )}
            <button
              className="icon-button"
              type="button"
              aria-label="稍后处理并关闭"
              title="稍后处理（保留待确认操作）"
              onClick={() => { if (!busy) onCloseRef.current(); }}
              disabled={busy}
            >
              ×
            </button>
          </div>
        </div>

        <h2 id="confirm-title" className="confirmation-product-title">
          {steps.length === 1 ? `确认${steps[0].summary.headline}`
            : steps.length > 1 ? `确认这 ${steps.length} 项操作` : '确认操作'}
        </h2>
        <p className="confirmation-status"><strong>待确认 · 尚未执行</strong></p>
        <p className="modal-reason">{reason}</p>

        {steps.length > 0 && (
          <div className="confirm-summary">
            <span className="eyebrow">将要发生什么</span>
            <ul>
              {steps.map(({ step, summary, risk: stepRisk }) => (
                <li key={step.id}>
                  <div className="confirm-summary-head">
                    <strong>{summary.headline}</strong>
                    <RiskBadge risk={stepRisk} />
                    {summary.unresolved && (
                      <span className="chip chip-amber" title="参数由执行时结果决定">
                        部分参数执行时确定
                      </span>
                    )}
                  </div>
                  {summary.details.length > 0 && (
                    <ul className="confirm-summary-details">
                      {summary.details.map((detail) => (
                        <li key={detail}>{detail}</li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className={`mfa-banner mfa-${risk}`}>
          <strong>{needsOtp ? '需要二次身份验证' : '一次明确确认即可'}</strong>
          <span>
            {needsOtp
              ? '请先核对操作对象和内容；身份验证未通过时，本次操作不会执行。'
              : '请核对操作对象和内容，在上方显示的剩余时间内确认。'}
          </span>
        </div>

        {reasons.length > 0 && (
          <div className="confirm-reasons">
            <span className="eyebrow">为什么需要确认</span>
            <ul>
              {reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          </div>
        )}

        {needsOtp && (
          <div className="mfa-method">
            <span className="eyebrow">选择验证方式</span>
            <ResourceState
              loading={mfaProvidersLoading}
              error={mfaProvidersError}
              empty={providerEmpty}
              emptyText="后端未注册 MFA provider，已回退到演示 OTP。"
              onRetry={onRefreshMfaProviders}
            >
              <div className="mfa-provider-options" role="radiogroup" aria-label="MFA 验证方式">
                {providerOptions.map((provider) => {
                  const active = provider.name === selectedProvider;
                  return (
                    <button
                      className={`mfa-provider-option ${active ? 'active' : ''}`}
                      key={provider.name}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      onClick={() => {
                        setMfaProvider(provider.name);
                        setMfaToken('');
                      }}
                      disabled={busy || writesBlocked || expired}
                    >
                      <span className="mfa-provider-option-top">
                        <strong>{provider.title}</strong>
                        {provider.default && <span className="chip chip-teal">默认</span>}
                      </span>
                      <small>{provider.hint || mfaProviderHint(provider.name, providerOptions)}</small>
                      <span className="mfa-provider-demo-token">
                        演示令牌 <code>{MFA_DEMO_TOKENS[provider.name] ?? '—'}</code>
                      </span>
                    </button>
                  );
                })}
              </div>
            </ResourceState>
            {providerEmpty && (
              <div className="alert alert-warn modal-alert">
                provider 列表为空，已回退到演示 OTP；确认时仍会提交 mfa_provider=otp。
              </div>
            )}

            <label className="otp-field">
              <span>{mfaProviderLabel(selectedProvider, providerOptions)} 验证令牌</span>
              <input
                inputMode={selectedProvider === 'otp' ? 'numeric' : 'text'}
                autoComplete={selectedProvider === 'otp' ? 'one-time-code' : 'off'}
                placeholder={mfaTokenPlaceholder(selectedProvider)}
                value={mfaToken}
                onChange={(event) => setMfaToken(sanitizeMfaToken(selectedProvider, event.target.value))}
                disabled={busy || writesBlocked || expired}
              />
              <span className="otp-help">
                演示环境使用固定令牌；生产环境必须接入银行真实 MFA。
                <button
                  type="button"
                  className="text-button otp-fill"
                  onClick={() => setMfaToken(MFA_DEMO_TOKENS[selectedProvider] ?? '')}
                  disabled={busy || writesBlocked || expired}
                >
                  填入演示令牌
                </button>
              </span>
            </label>
          </div>
        )}

        {writesBlocked && (
          <div className="alert alert-warn modal-alert" role="alert">
            写操作已按 fail-closed 禁用：{blockReason}。恢复就绪后可继续确认；现在可以先「稍后处理」。
          </div>
        )}

        {expired && (
          <div className="alert alert-warn modal-alert" role="alert">
            这次确认已过期，不能继续执行。请关闭后重新发起任务。
          </div>
        )}

        {error && <div className="alert alert-error modal-alert" role="alert">{error}</div>}

        <details className="tech-details">
          <summary>技术详情（计划哈希 / 原始参数 / 证据分层）</summary>
          <p>服务端原始说明：{pending.reason}</p>
          {pending.plan?.plan_hash && (
            <p>
              <span className="eyebrow">PLAN HASH</span>
              <code>{pending.plan.plan_hash}</code>
            </p>
          )}
          {pending.plan?.dag_path && (
            <p>
              <span className="eyebrow">DAG 路径</span>
              <code>{pending.plan.dag_path}</code>
            </p>
          )}
          <ol className="tech-steps">
            {steps.map(({ step }) => (
              <li key={step.id}>
                <div>
                  <strong>{step.title || step.tool_name}</strong>
                  <code>{step.tool_name}</code>
                  {step.permission && <span>权限 {step.permission}</span>}
                </div>
                <pre>{JSON.stringify(step.arguments, null, 2)}</pre>
              </li>
            ))}
          </ol>
          <div className="result-evidence">
            <span className="eyebrow">证据分层</span>
            <EvidenceBadges
              evidence={pending.evidence ?? pending.evidence_list}
              emptyHint="本次确认尚未返回分层证据。"
            />
          </div>
          {pending.confirmation?.expires_at && (
            <p className="tech-expiry">
              确认有效期至 {formatDateTime(pending.confirmation.expires_at)}
            </p>
          )}
        </details>

        <div className="modal-actions">
          <button
            className="ghost-button"
            type="button"
            onClick={() => { if (!busy) onCloseRef.current(); }}
            disabled={busy}
          >
            稍后处理
          </button>
          <button
            className="ghost-button"
            type="button"
            onClick={() => onDecision(false)}
            disabled={decisionDisabled}
          >
            拒绝执行
          </button>
          <button
            className="primary-button"
            type="button"
            onClick={() => onDecision(true, selectedProvider)}
            disabled={decisionDisabled || (needsOtp && !tokenComplete)}
          >
            {busy ? '校验中…' : needsOtp ? '验证并执行' : '确认执行'}
          </button>
        </div>
      </section>
    </div>
  );
}
