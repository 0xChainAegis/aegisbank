import { formatDateTime, collectRiskReasons, runRiskLevel, stepRiskLevel } from '../viewModel';
import type { MfaProvider, RunResponse } from '../types';
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
  error?: string;
  writesBlocked: boolean;
  blockReason: string;
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
  error,
  writesBlocked,
  blockReason,
}: Props) {
  const risk = runRiskLevel(pending);
  const needsOtp = Boolean(pending.confirmation?.requires_reauth) || risk === 'red';
  const reasons = collectRiskReasons(pending);
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

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal card" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <div className="modal-top">
          <div className="modal-top-tags">
            <RiskBadge risk={risk} verbose />
            <span className="eyebrow">HUMAN-IN-THE-LOOP</span>
          </div>
          {pending.confirmation?.expires_at && (
            <span className="modal-expiry">有效期至 {formatDateTime(pending.confirmation.expires_at)}</span>
          )}
        </div>

        <h2 id="confirm-title">
          {risk === 'red' ? '红色操作 · MFA 二次校验' : '黄色操作 · 快速确认'}
        </h2>
        <p>{pending.reason}</p>

        <div className={`mfa-banner mfa-${risk}`}>
          <strong>{needsOtp ? 'MFA / 二次身份校验必需' : '仅需一次明确确认'}</strong>
          <span>
            {needsOtp
              ? '该操作命中红色风险规则。请选择验证方式并输入演示 token；验证失败不会执行任何工具。'
              : '该操作会修改账户设置，请在 5 分钟有效期内确认。'}
          </span>
        </div>

        <div className="result-evidence modal-evidence">
          <span className="eyebrow">EVIDENCE LAYERS</span>
          <EvidenceBadges
            evidence={pending.evidence ?? pending.evidence_list}
            emptyHint="本次确认尚未返回分层证据。"
          />
        </div>

        {pending.plan && pending.plan.steps.length > 0 && (
          <div className="confirm-plan">
            <span className="eyebrow">即将执行的 DAG 节点</span>
            <ol>
              {pending.plan.steps.map((step) => (
                <li key={step.id}>
                  <div>
                    <strong>{step.title || step.tool_name}</strong>
                    <code>{step.tool_name}</code>
                    <RiskBadge risk={stepRiskLevel(step.risk_level, pending)} />
                    {step.irreversible && <span className="comp-badge comp-bad">不可撤销</span>}
                  </div>
                  <small>{JSON.stringify(step.arguments)}</small>
                </li>
              ))}
            </ol>
          </div>
        )}

        {reasons.length > 0 && (
          <div className="confirm-reasons">
            <span className="eyebrow">触发规则</span>
            <ul>
              {reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          </div>
        )}

        {needsOtp && (
          <div className="mfa-method">
            <span className="eyebrow">验证方式 · GET /api/mfa/providers</span>
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
                      disabled={writesBlocked}
                    >
                      <span className="mfa-provider-option-top">
                        <strong>{provider.title}</strong>
                        <code>{provider.name}</code>
                        {provider.default && <span className="chip chip-teal">默认</span>}
                      </span>
                      <small>{provider.hint || mfaProviderHint(provider.name, providerOptions)}</small>
                      <span className="mfa-provider-demo-token">
                        演示 token <code>{MFA_DEMO_TOKENS[provider.name] ?? '—'}</code>
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
                disabled={writesBlocked}
                autoFocus
              />
              <small>
                演示 token：{MFA_DEMO_TOKENS[selectedProvider] ?? '—'}。{mfaProviderHint(selectedProvider, providerOptions)}
                生产环境须接入银行真实 MFA，演示 token 不得用于真实业务。
              </small>
            </label>
          </div>
        )}

        {writesBlocked && (
          <div className="alert alert-warn modal-alert" role="alert">
            写操作已按 fail-closed 禁用：{blockReason}。系统恢复 ready 后才能确认或拒绝该操作。
          </div>
        )}

        {error && <div className="alert alert-error modal-alert" role="alert">{error}</div>}

        <div className="modal-actions">
          <button
            className="ghost-button"
            onClick={() => onDecision(false)}
            disabled={busy || writesBlocked}
          >
            拒绝执行
          </button>
          <button
            className="primary-button"
            onClick={() => onDecision(true, selectedProvider)}
            disabled={busy || writesBlocked || (needsOtp && !tokenComplete)}
          >
            {busy ? '校验中…' : needsOtp ? '验证并执行' : '确认执行'}
          </button>
        </div>
      </section>
    </div>
  );
}