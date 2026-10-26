import type { AegisRole } from '../roles';
import {
  CAPABILITY_LABELS,
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  roleCapabilities,
} from '../roles';
import type { BreakerStatus } from '../types';
import BreakerPanel from './BreakerPanel';

interface Props {
  writesBlocked: boolean;
  role: AegisRole;
  breakerStatus: BreakerStatus | null;
  breakerLoading: boolean;
  breakerError: string;
  onRefreshBreaker: () => void;
  onBreakerChanged: () => void;
  onRoleChange: (role: AegisRole) => void;
}

export default function OpsPage({
  writesBlocked,
  role,
  breakerStatus,
  breakerLoading,
  breakerError,
  onRefreshBreaker,
  onBreakerChanged,
  onRoleChange,
}: Props) {
  const capabilities = roleCapabilities(role);

  return (
    <section className="page-stack ops-page">
      <div className="page-heading ops-heading">
        <div>
          <span className="eyebrow">OPERATIONS · TRUST RECOVERY</span>
          <h1>运维面板</h1>
          <p>
            熔断状态、触发原因与恢复路径集中在一个视图。写操作在熔断打开时按 fail-closed
            拒绝；解除熔断只允许 operator，user 的 403 原因会原样展示。
          </p>
        </div>
        <span className="role-pill">当前角色 {ROLE_LABELS[role]}</span>
      </div>

      <div className="role-banner card">
        <div>
          <span className="eyebrow">ROLE CAPABILITIES</span>
          <strong>{ROLE_LABELS[role]}</strong>
          <p>{ROLE_DESCRIPTIONS[role]}</p>
          <div className="capability-chips">
            {capabilities.map((capability) => (
              <span className="chip chip-teal" key={capability}>
                {CAPABILITY_LABELS[capability]}
              </span>
            ))}
          </div>
        </div>
        <div className="role-switch-inline">
          <span>切换角色会立即改变所有 API 的 X-Aegis-Role</span>
          <button
            className="ghost-button small-button"
            onClick={() => onRoleChange('operator')}
            disabled={role === 'operator'}
          >
            切到 operator
          </button>
          <button
            className="ghost-button small-button"
            onClick={() => onRoleChange('user')}
            disabled={role === 'user'}
          >
            切到 user
          </button>
        </div>
      </div>

      <div className="card breaker-card">
        <BreakerPanel
          writesBlocked={writesBlocked}
          role={role}
          status={breakerStatus}
          statusLoading={breakerLoading}
          statusError={breakerError}
          onRefreshStatus={onRefreshBreaker}
          onChanged={onBreakerChanged}
        />
      </div>
    </section>
  );
}