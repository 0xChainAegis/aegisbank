import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createIdempotencyKey,
  fetchAudit,
  fetchBankingOverview,
  fetchBreakerStatus,
  fetchMfaProviders,
  fetchPermissions,
  fetchReadiness,
  fetchTools,
  fetchTrustAction,
  reconcileAction,
  resolveConfirmation,
  runAgent,
  setApiRole,
  updatePermission,
  verifyAudit,
} from './api';
import AuditPage from './components/AuditPage';
import BankOverviewPage from './components/BankOverviewPage';
import BreakerBanner from './components/BreakerBanner';
import CapabilitiesPage from './components/CapabilitiesPage';
import ConfirmationModal from './components/ConfirmationModal';
import OpsPage from './components/OpsPage';
import PermissionsPage from './components/PermissionsPage';
import ReadinessBanner from './components/ReadinessBanner';
import ScenariosPage from './components/ScenariosPage';
import TaskConsolePage from './components/TaskConsolePage';
import type { AegisRole } from './roles';
import {
  AEGIS_ROLES,
  ROLE_LABELS,
  ROLE_SHORT_LABELS,
  ROLE_STORAGE_KEY,
  roleFromStorage,
  roleTaskBlockReason,
} from './roles';
import { defaultMfaProvider, describeMfaFailure } from './twoA';
import type {
  ActionJournal,
  AgentRunInput,
  AuditEntry,
  BankingOverview,
  BreakerStatus,
  MfaProvidersResponse,
  ReadinessSnapshot,
  RunResponse,
  ToolMetadata,
  TrustActionDetail,
} from './types';
import { describeError } from './errors';
import {
  clearPendingSnapshot,
  formatRemaining,
  isSnapshotExpired,
  loadPendingSnapshot,
  remainingSeconds,
  savePendingSnapshot,
  type PendingSnapshot,
} from './session';
import { useHashRoute, type Page } from './useHashRoute';
import { readinessBlockers } from './viewModel';

const navigation: Array<{ id: Page; index: string; label: string; hint: string }> = [
  { id: 'overview', index: '01', label: '银行概览', hint: '账户与订阅' },
  { id: 'scenarios', index: '02', label: '场景数据', hint: '只读 · 六场景' },
  { id: 'console', index: '03', label: '任务控制台', hint: '发起任务' },
  { id: 'permissions', index: '04', label: '权限控制台', hint: '工具授权' },
  { id: 'capabilities', index: '05', label: '2A 能力', hint: 'MFA / 沙箱 / IM' },
  { id: 'ops', index: '06', label: '运维面板', hint: '熔断与恢复' },
  { id: 'audit', index: '07', label: '操作审计', hint: '哈希链证据' },
];

const CROSS_SCENARIO_INSTRUCTION = '分析我的本月账单和所有订阅，找出异常订阅并取消它';

function initialRole(): AegisRole {
  if (typeof window === 'undefined') return 'user';
  try {
    return roleFromStorage(window.localStorage.getItem(ROLE_STORAGE_KEY));
  } catch {
    return 'user';
  }
}

const INITIAL_ROLE = initialRole();
setApiRole(INITIAL_ROLE);

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function combineErrors(...errors: string[]): string {
  return errors.filter(Boolean).join(' ');
}

export default function App() {
  const { page, navigate: setRoute } = useHashRoute('overview');
  const [role, setRole] = useState<AegisRole>(INITIAL_ROLE);
  const [tools, setTools] = useState<ToolMetadata[]>([]);
  const [toolsLoading, setToolsLoading] = useState(true);
  const [toolsError, setToolsError] = useState('');
  const [overview, setOverview] = useState<BankingOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState('');
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(true);
  const [auditError, setAuditError] = useState('');
  const [auditValid, setAuditValid] = useState<boolean | null>(null);
  const [auditChecked, setAuditChecked] = useState(0);
  const [readiness, setReadiness] = useState<ReadinessSnapshot | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(true);
  const [readinessError, setReadinessError] = useState('');
  const [breakerStatus, setBreakerStatus] = useState<BreakerStatus | null>(null);
  const [breakerLoading, setBreakerLoading] = useState(true);
  const [breakerError, setBreakerError] = useState('');
  const [mfaProviders, setMfaProviders] = useState<MfaProvidersResponse | null>(null);
  const [mfaProvidersLoading, setMfaProvidersLoading] = useState(true);
  const [mfaProvidersError, setMfaProvidersError] = useState('');
  const [instruction, setInstruction] = useState('');
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);
  const [pending, setPending] = useState<RunResponse | null>(null);
  const [lastActionId, setLastActionId] = useState<string | null>(null);
  const [trustAction, setTrustAction] = useState<TrustActionDetail | null>(null);
  const [trustActionLoading, setTrustActionLoading] = useState(false);
  const [trustActionError, setTrustActionError] = useState('');
  const [mfaToken, setMfaToken] = useState('');
  const [mfaProvider, setMfaProvider] = useState('otp');
  const [busy, setBusy] = useState(false);
  const [busyTool, setBusyTool] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [auditVerifyError, setAuditVerifyError] = useState('');
  const [restoredPending, setRestoredPending] = useState<PendingSnapshot | null>(null);
  const [reconciling, setReconciling] = useState(false);
  const [auditFilter, setAuditFilter] = useState('');
  const [lastRunInstruction, setLastRunInstruction] = useState('');
  const runKeyRef = useRef<string | null>(null);
  const confirmKeyRef = useRef<{ actionId: string; key: string } | null>(null);

  const grantedCount = useMemo(() => tools.filter((tool) => tool.granted).length, [tools]);

  const writesBlocked = Boolean(readinessError) || readiness?.status !== 'ready';
  const blockReason = readinessError
    ? readinessError
    : readinessBlockers(readiness).join('；') || '系统尚未就绪';

  const loadTools = useCallback(async (showLoading = false) => {
    if (showLoading) setToolsLoading(true);
    setToolsError('');
    try {
      let nextTools: ToolMetadata[];
      try {
        nextTools = await fetchPermissions();
      } catch {
        nextTools = await fetchTools();
      }
      setTools(nextTools);
    } catch (error) {
      setToolsError(messageOf(error, '无法加载工具权限'));
    } finally {
      setToolsLoading(false);
    }
  }, []);

  const loadOverview = useCallback(async (showLoading = false) => {
    if (showLoading) setOverviewLoading(true);
    setOverviewError('');
    try {
      setOverview(await fetchBankingOverview());
    } catch (error) {
      setOverviewError(messageOf(error, '无法加载银行概览'));
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const loadAudit = useCallback(async (showLoading = false) => {
    if (showLoading) setAuditLoading(true);
    setAuditError('');
    try {
      const [entriesResult, verificationResult] = await Promise.allSettled([
        fetchAudit(100),
        verifyAudit(),
      ]);
      if (entriesResult.status === 'rejected') throw entriesResult.reason;
      setAudit(entriesResult.value.entries ?? []);
      if (verificationResult.status === 'fulfilled') {
        setAuditValid(verificationResult.value.valid);
        setAuditChecked(verificationResult.value.checked);
        setAuditVerifyError('');
      } else {
        setAuditValid(null);
        setAuditChecked(0);
        setAuditVerifyError(messageOf(verificationResult.reason, '哈希链校验失败'));
      }
    } catch (error) {
      setAuditError(messageOf(error, '无法加载操作审计'));
    } finally {
      setAuditLoading(false);
    }
  }, []);

  const loadReadiness = useCallback(async (showLoading = false) => {
    if (showLoading) setReadinessLoading(true);
    try {
      setReadiness(await fetchReadiness());
      setReadinessError('');
    } catch (error) {
      // 无法确认就绪状态时保持 fail-closed：写操作继续被禁用。
      setReadinessError(messageOf(error, '无法获取系统就绪状态'));
    } finally {
      setReadinessLoading(false);
    }
  }, []);

  const loadBreaker = useCallback(async (showLoading = false) => {
    if (showLoading) setBreakerLoading(true);
    try {
      setBreakerStatus(await fetchBreakerStatus());
      setBreakerError('');
    } catch (error) {
      setBreakerError(messageOf(error, '无法获取熔断状态'));
    } finally {
      setBreakerLoading(false);
    }
  }, []);

  const loadMfaProviders = useCallback(async () => {
    setMfaProvidersLoading(true);
    setMfaProvidersError('');
    try {
      setMfaProviders(await fetchMfaProviders());
    } catch (error) {
      setMfaProvidersError(messageOf(error, '无法加载 MFA 验证方式'));
    } finally {
      setMfaProvidersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTools(true);
    void loadOverview(true);
    void loadAudit(true);
    void loadReadiness(true);
    void loadBreaker(true);
    void loadMfaProviders();
  }, [loadAudit, loadBreaker, loadMfaProviders, loadOverview, loadReadiness, loadTools]);

  // 刷新/断线后恢复待确认动作（UX-17）：只恢复本地快照，状态仍以后端为准。
  useEffect(() => {
    const snapshot = loadPendingSnapshot();
    if (!snapshot) return;
    if (isSnapshotExpired(snapshot)) {
      clearPendingSnapshot();
      setNotice('之前有一笔待确认操作已过期，已自动清理。');
      return;
    }
    setRestoredPending(snapshot);
    setNotice('检测到一笔未完成的确认，可在顶部继续处理或放弃。');
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadReadiness();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [loadReadiness]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadBreaker();
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [loadBreaker]);

  useEffect(() => {
    setApiRole(role);
    try {
      window.localStorage.setItem(ROLE_STORAGE_KEY, role);
    } catch {
      // localStorage may be unavailable in a hardened browser profile.
    }
  }, [role]);

  function navigate(next: Page) {
    setRoute(next);
    setActionError('');
    setNotice('');
  }

  function switchRole(next: AegisRole) {
    if (next === role) return;
    if (pending) {
      setNotice('请先确认或拒绝当前待操作，再切换角色。');
      return;
    }
    setApiRole(next);
    setRole(next);
    setActionError('');
    if (next === 'operator') setRoute('ops');
    if (next === 'auditor') setRoute('audit');
    setNotice(`角色已切换为 ${ROLE_LABELS[next]}；所有 API 请求自动携带 X-Aegis-Role: ${next}。`);
    void Promise.all([
      loadTools(true),
      loadAudit(true),
      loadReadiness(true),
      loadBreaker(true),
      loadMfaProviders(),
    ]);
  }

  function openCrossScenario() {
    setInstruction(CROSS_SCENARIO_INSTRUCTION);
    navigate('console');
  }

  const refreshAll = useCallback(async () => {
    await Promise.all([loadTools(), loadOverview(), loadAudit(), loadReadiness(), loadBreaker()]);
  }, [loadAudit, loadBreaker, loadOverview, loadReadiness, loadTools]);

  function handleRecoveryChanged(journal: ActionJournal, response: unknown) {
    const payload =
      response !== null && typeof response === 'object'
        ? (response as Partial<RunResponse>)
        : {};
    setLastRun((previous) =>
      previous
        ? {
            ...previous,
            status: journal.status,
            reason: journal.reason || previous.reason,
            rollback: payload.rollback ?? previous.rollback,
            rolled_back: payload.rolled_back ?? previous.rolled_back,
            paused: payload.paused ?? previous.paused,
            results: payload.results ?? previous.results,
          }
        : previous,
    );
    void refreshAll();
  }

  function continueRestoredPending() {
    if (!restoredPending) return;
    setPending(restoredPending.pending);
    setLastRun(restoredPending.pending);
    setLastActionId(restoredPending.pending.confirmation?.id ?? null);
    setInstruction(restoredPending.instruction);
    setRestoredPending(null);
    navigate('console');
    setNotice('已恢复待确认操作，请核对风险原因后确认或拒绝。');
  }

  function discardRestoredPending() {
    clearPendingSnapshot();
    setRestoredPending(null);
    setNotice('已放弃恢复该待确认操作；后端动作会在有效期内自动过期。');
    void refreshAll();
  }

  function laterConfirmation() {
    if (!pending?.confirmation) return;
    const snapshot: PendingSnapshot = {
      pending,
      instruction,
      savedAt: new Date().toISOString(),
    };
    savePendingSnapshot(snapshot);
    setRestoredPending(snapshot);
    setPending(null);
    setActionError('');
    setNotice('已稍后处理，可在页面顶部继续这笔确认。');
  }

  async function handleReconcile(outcome: 'reconciled' | 'rolled_back') {
    if (!lastActionId || reconciling) return;
    setReconciling(true);
    setActionError('');
    try {
      await reconcileAction(
        lastActionId,
        outcome,
        outcome === 'reconciled' ? '用户在控制台人工对账' : '用户在控制台申请人工回滚',
      );
      setNotice(
        outcome === 'reconciled'
          ? '已对账，结论已写入审计哈希链。'
          : '已提交人工回滚，结论已写入审计哈希链。',
      );
      setTrustAction(await fetchTrustAction(lastActionId));
      await refreshAll();
    } catch (error) {
      setActionError(describeError(error, 'run').message);
    } finally {
      setReconciling(false);
    }
  }

  async function execute(input: AgentRunInput) {
    setBusy(true);
    setActionError('');
    setNotice('');
    setTrustAction(null);
    setTrustActionError('');
    // 新一轮提交不再展示上一轮回执（UX-09）；失败也不会伪装成上一次的结果。
    setLastRun(null);
    setLastActionId(null);
    const idempotencyKey = runKeyRef.current ?? createIdempotencyKey();
    runKeyRef.current = idempotencyKey;
    try {
      const result = await runAgent(input, { idempotencyKey });
      runKeyRef.current = null;
      setLastRun(result);
      setLastActionId(result.confirmation?.id ?? null);
      setLastRunInstruction(input.instruction);
      if (result.status === 'awaiting_confirmation' && result.confirmation) {
        setMfaToken('');
        setMfaProvider(defaultMfaProvider(mfaProviders?.providers ?? [], 'otp'));
        setPending(result);
        savePendingSnapshot({
          pending: result,
          instruction: input.instruction,
          savedAt: new Date().toISOString(),
        });
        setNotice('计划已生成。请核对风险原因并完成人工确认。');
      } else {
        setPending(null);
        setMfaToken('');
        clearPendingSnapshot();
        setNotice(result.reason);
      }
      await refreshAll();
    } catch (error) {
      const explanation = describeError(error, 'run');
      if (explanation.action !== 'retry') runKeyRef.current = null;
      setActionError(explanation.message);
    } finally {
      setBusy(false);
    }
  }

  async function decide(approved: boolean, providerOverride?: string) {
    if (!pending?.confirmation) return;
    const actionId = pending.confirmation.id;
    const needsMfa = pending.confirmation.requires_reauth || pending.risk_level === 'red';
    const provider = providerOverride ?? mfaProvider;
    const idempotencyKey =
      confirmKeyRef.current?.actionId === actionId
        ? confirmKeyRef.current.key
        : createIdempotencyKey();
    confirmKeyRef.current = { actionId, key: idempotencyKey };
    setBusy(true);
    setActionError('');
    try {
      const result = await resolveConfirmation(
        actionId,
        approved,
        needsMfa ? mfaToken : undefined,
        needsMfa ? provider : null,
        { idempotencyKey },
      );
      confirmKeyRef.current = null;
      runKeyRef.current = null;
      clearPendingSnapshot();
      setRestoredPending(null);
      setLastRun(result);
      setLastActionId(actionId);
      setPending(null);
      setMfaToken('');
      setNotice(result.reason);
      setTrustAction(null);
      setTrustActionError('');
      await refreshAll();
    } catch (error) {
      const explanation = describeError(error, 'confirmation');
      if (explanation.action === 'retry') {
        // 可重试：保留弹窗，让用户改 OTP 或稍后重试。
        const raw = messageOf(error, approved ? '确认执行失败' : '拒绝操作失败');
        const lookLikeMfaFailure = /二次身份校验|OTP|token|验证/i.test(raw);
        setActionError(
          needsMfa && lookLikeMfaFailure ? describeMfaFailure(raw, provider) : explanation.message,
        );
      } else {
        // 终态错误（409 / 400 / 422）：关闭弹窗，不再让用户对着永远失败的重试按钮。
        confirmKeyRef.current = null;
        clearPendingSnapshot();
        setRestoredPending(null);
        setPending(null);
        setMfaToken('');
        setLastRun(null);
        setLastActionId(null);
        setActionError('');
        setNotice(
          explanation.action === 'reconfirm'
            ? `${explanation.message} 请重新发起任务。`
            : explanation.message,
        );
        await refreshAll();
      }
    } finally {
      setBusy(false);
    }
  }

  async function inspectTrustAction() {
    if (!lastActionId || trustActionLoading) return;
    setTrustActionLoading(true);
    setTrustActionError('');
    try {
      setTrustAction(await fetchTrustAction(lastActionId));
    } catch (error) {
      setTrustActionError(messageOf(error, '无法读取信任详情'));
    } finally {
      setTrustActionLoading(false);
    }
  }

  async function togglePermission(tool: ToolMetadata) {
    setBusyTool(tool.name);
    setActionError('');
    setNotice('');
    try {
      await updatePermission(tool.name, !tool.granted);
      setNotice(`${tool.title} 权限已${tool.granted ? '撤回' : '授予'}，列表已刷新。`);
      await loadTools();
    } catch (error) {
      setActionError(messageOf(error, '权限更新失败'));
    } finally {
      setBusyTool('');
    }
  }

  const sharedNotice = notice;
  const overlayError = actionError;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">A</div>
          <div>
            <strong>AegisBank</strong>
            <span>Trusted Agent Console</span>
          </div>
        </div>
        <div className="topbar-tools">
          <div className="role-switch" role="group" aria-label="角色切换">
            {AEGIS_ROLES.map((item) => (
              <button
                key={item}
                className={role === item ? 'active' : ''}
                onClick={() => switchRole(item)}
                aria-pressed={role === item}
                title={`${ROLE_LABELS[item]}：所有请求自动携带 X-Aegis-Role: ${item}`}
              >
                {ROLE_SHORT_LABELS[item]}
              </button>
            ))}
          </div>
          <button
            className={`breaker-pill ${breakerStatus?.open ? 'is-open' : breakerError ? 'is-unknown' : ''}`}
            onClick={() => navigate('ops')}
            title={breakerError || (breakerStatus?.open ? breakerStatus.reason : '熔断器关闭')}
          >
            <i aria-hidden="true" />
            {breakerError
              ? '熔断状态未知'
              : breakerLoading && !breakerStatus
                ? '熔断检查中'
                : breakerStatus?.open
                  ? '熔断打开'
                  : '熔断关闭'}
          </button>
          <div className="topbar-status">
            <span
              className={`status-dot ${auditVerifyError || auditValid === false ? 'status-bad' : auditValid === null ? 'status-pending' : ''}`}
            />
            {auditVerifyError
              ? '审计链校验失败'
              : auditValid === false
                ? '审计链异常'
                : auditValid === null
                  ? '审计链待校验'
                  : '本地 MVP · 审计链在线'}
            <span className="env-pill">DEV</span>
          </div>
        </div>
      </header>

      <ReadinessBanner
        snapshot={readiness}
        loading={readinessLoading}
        error={readinessError}
        onRefresh={() => void loadReadiness(true)}
      />

      <BreakerBanner
        status={breakerStatus}
        loading={breakerLoading}
        error={breakerError}
        onOpenOps={() => navigate('ops')}
        onRetry={() => void loadBreaker(true)}
      />

      {restoredPending && (
        <div className="restore-banner" role="status">
          <div className="restore-copy">
            <span className="eyebrow">UNFINISHED CONFIRMATION</span>
            <strong>有一笔待确认的操作：{restoredPending.instruction}</strong>
            <small>
              剩余{' '}
              {formatRemaining(
                remainingSeconds(restoredPending.pending.confirmation?.expires_at),
              )}{' '}
              · 刷新不会自动执行，需要你明确确认或拒绝
            </small>
          </div>
          <div className="restore-actions">
            <button className="ghost-button small-button" onClick={discardRestoredPending}>
              放弃恢复
            </button>
            <button className="primary-button small-button" onClick={continueRestoredPending}>
              继续处理
            </button>
          </div>
        </div>
      )}

      <div className="layout">
        <aside className="sidebar">
          <nav aria-label="主导航">
            {navigation.map((item) => (
              <button
                key={item.id}
                className={page === item.id ? 'active' : ''}
                onClick={() => navigate(item.id)}
                aria-current={page === item.id ? 'page' : undefined}
              >
                <span className="nav-index">{item.index}</span>
                <span className="nav-copy">
                  <strong>{item.label}</strong>
                  <small>{item.hint}</small>
                </span>
              </button>
            ))}
          </nav>

          <div className="sidebar-note">
            <span className="eyebrow">TRUST POSTURE</span>
            <strong>{grantedCount} / {tools.length || '—'}</strong>
            <p>工具权限已授权</p>
            <div className="meter">
              <span style={{ width: `${tools.length ? (grantedCount / tools.length) * 100 : 0}%` }} />
            </div>
          </div>

          <div className="sidebar-footer">
            <span>角色 · {ROLE_LABELS[role]}</span>
            <span>数据 · SQLite / Local</span>
            <span>策略 · Dynamic Risk v2</span>
          </div>
        </aside>

        <main>
          {page === 'overview' && (
            <BankOverviewPage
              overview={overview}
              loading={overviewLoading}
              error={combineErrors(overviewError, overlayError)}
              notice={sharedNotice}
              onRefresh={() => void loadOverview(true)}
              onNavigateConsole={openCrossScenario}
            />
          )}

          {page === 'scenarios' && (
            <ScenariosPage
              writesBlocked={writesBlocked || role !== 'user'}
              blockReason={role !== 'user' ? roleTaskBlockReason(role) : blockReason}
              onDataChanged={() => void refreshAll()}
            />
          )}

          {page === 'console' && (
            <TaskConsolePage
              role={role}
              tools={tools}
              toolsLoading={toolsLoading}
              instruction={instruction}
              setInstruction={setInstruction}
              lastRun={lastRun}
              busy={busy}
              error={combineErrors(toolsError, overlayError)}
              notice={sharedNotice}
              writesBlocked={writesBlocked}
              blockReason={blockReason}
              lastActionId={lastActionId}
              trustAction={trustAction}
              trustActionLoading={trustActionLoading}
              trustActionError={trustActionError}
              onInspectTrustAction={() => void inspectTrustAction()}
              onExecute={(input) => void execute(input)}
              onRefresh={() => void loadTools(true)}
              onRecoveryChanged={handleRecoveryChanged}
              onNavigateAudit={() => {
                setAuditFilter(lastRunInstruction);
                navigate('audit');
              }}
              onReconcile={(outcome) => void handleReconcile(outcome)}
              reconciling={reconciling}
            />
          )}

          {page === 'permissions' && (
            <PermissionsPage
              role={role}
              tools={tools}
              loading={toolsLoading}
              error={combineErrors(toolsError, overlayError)}
              notice={sharedNotice}
              busyTool={busyTool}
              onToggle={(tool) => void togglePermission(tool)}
              onRefresh={() => void loadTools(true)}
            />
          )}

          {page === 'capabilities' && (
            <CapabilitiesPage
              role={role}
              mfa={mfaProviders}
              mfaLoading={mfaProvidersLoading}
              mfaError={mfaProvidersError}
              onRefreshMfa={() => void loadMfaProviders()}
            />
          )}

          {page === 'ops' && (
            <OpsPage
              role={role}
              breakerStatus={breakerStatus}
              breakerLoading={breakerLoading}
              breakerError={breakerError}
              onRefreshBreaker={() => void loadBreaker(true)}
              onBreakerChanged={() => {
                void loadBreaker();
                void loadAudit();
              }}
              onRoleChange={switchRole}
            />
          )}

          {page === 'audit' && (
            <AuditPage
              role={role}
              audit={audit}
              auditValid={auditValid}
              auditChecked={auditChecked}
              initialQuery={auditFilter}
              verifyError={auditVerifyError}
              loading={auditLoading}
              error={combineErrors(auditError, overlayError)}
              notice={sharedNotice}
              onRefresh={() => void loadAudit(true)}
            />
          )}
        </main>
      </div>

      {pending?.confirmation && (
        <ConfirmationModal
          pending={pending}
          busy={busy}
          mfaToken={mfaToken}
          setMfaToken={setMfaToken}
          mfaProvider={mfaProvider}
          setMfaProvider={setMfaProvider}
          mfaProviders={mfaProviders?.providers ?? []}
          mfaProvidersLoading={mfaProvidersLoading}
          mfaProvidersError={mfaProvidersError}
          onRefreshMfaProviders={() => void loadMfaProviders()}
          onDecision={(approved, provider) => void decide(approved, provider)}
          onClose={laterConfirmation}
          error={actionError}
          writesBlocked={writesBlocked}
          blockReason={blockReason}
        />
      )}
    </div>
  );
}