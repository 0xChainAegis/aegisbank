import { formatDateTime, collectRiskReasons, runRiskLevel, stepRiskLevel } from '../viewModel';
import type { RunResponse } from '../types';
import { RiskBadge } from './ui';

interface Props {
  pending: RunResponse;
  busy: boolean;
  otp: string;
  setOtp: (value: string) => void;
  onDecision: (approved: boolean) => void;
  error?: string;
}

export default function ConfirmationModal({
  pending,
  busy,
  otp,
  setOtp,
  onDecision,
  error,
}: Props) {
  const risk = runRiskLevel(pending);
  const needsOtp = Boolean(pending.confirmation?.requires_reauth) || risk === 'red';
  const reasons = collectRiskReasons(pending);

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
          <strong>{needsOtp ? 'MFA / OTP 必需' : '仅需一次明确确认'}</strong>
          <span>
            {needsOtp
              ? '该操作命中红色风险规则，必须输入动态验证码后才能执行。'
              : '该操作会修改账户设置，请在 5 分钟有效期内确认。'}
          </span>
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
          <label className="otp-field">
            <span>动态验证码</span>
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="输入 6 位验证码"
              value={otp}
              onChange={(event) => setOtp(event.target.value.replace(/\D/g, '').slice(0, 6))}
              autoFocus
            />
            <small>本地演示验证码：246810。生产环境须接入银行真实 MFA，演示 OTP 不得用于真实业务。</small>
          </label>
        )}

        {error && <div className="alert alert-error modal-alert" role="alert">{error}</div>}

        <div className="modal-actions">
          <button className="ghost-button" onClick={() => onDecision(false)} disabled={busy}>
            拒绝执行
          </button>
          <button
            className="primary-button"
            onClick={() => onDecision(true)}
            disabled={busy || (needsOtp && otp.length !== 6)}
          >
            {busy ? '校验中…' : needsOtp ? '验证并执行' : '确认执行'}
          </button>
        </div>
      </section>
    </div>
  );
}
