import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchAudit,
  fetchBankingOverview,
  fetchPermissions,
  fetchReadiness,
  fetchTools,
  fetchTrustAction,
  resolveConfirmation,
  runAgent,
  updatePermission,
  verifyAudit,
} from './api';
import AuditPage from './components/AuditPage';
import BankOverviewPage from './components/BankOverviewPage';
import ConfirmationModal from './components/ConfirmationModal';
import PermissionsPage from './components/PermissionsPage';
import ReadinessBanner from './components/ReadinessBanner';
import ScenariosPage from './components/ScenariosPage';
import TaskConsolePage from './components/TaskConsolePage';
import { readinessBlockers } from './viewModel';
import type {
  AgentRunInput,
  AuditEntry,
  BankingOverview,
  ReadinessSnapshot,
  RunResponse,
  ToolMetadata,
  TrustActionDetail,
} from './types';

type Page = 'overview' | 'scenarios' | 'console' | 'permissions' | 'audit';

const navigation: Array<{ id: Page; index: string; label: string; hint: string }> = [
  { id: 'overview', index: '01', label: '银行概览', hint: '账户与订阅' },
  { id: 'scenarios', index: '02', label: '六场景面板', hint: '理财 / 账单 / 自动化' },
  { id: 'console', index: '03', label: '任务控制台', hint: '三场景任务' },
  { id: 'permissions', index: '04', label: '权限控制台', hint: '工具授权' },
  { id: 'audit', index: '05', label: '操作审计', hint: '哈希链证据' },
];

const CROSS_SCENARIO_INSTRUCTION = '分析我的本月账单和所有订阅，找出异常订阅并取消它';

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function combineErrors(...errors: string[]): string {
  return errors.filter(Boolean).join(' ');
}

export default function App() {
  const [page, setPage] = useState<Page>('overview');
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
  const [instruction, setInstruction] = useState('查询并分析我的本月账单');
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);
  const [pending, setPending] = useState<RunResponse | null>(null);
  const [lastActionId, setLastActionId] = useState<string | null>(null);
  const [trustAction, setTrustAction] = useState<TrustActionDetail | null>(null);
  const [trustActionLoading, setTrustActionLoading] = useState(false);
  const [trustActionError, setTrustActionError] = useState('');
  const [otp, setOtp] = useState('');
  const [busy, setBusy] = useState(false);
  const [busyTool, setBusyTool] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');

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
      } else {
        setAuditValid(null);
        setAuditChecked(0);
        setAuditError(messageOf(verificationResult.reason, '哈希链校验失败'));
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

  useEffect(() => {
    void loadTools(true);
    void loadOverview(true);
    void loadAudit(true);
    void loadReadiness(true);
  }, [loadAudit, loadOverview, loadReadiness, loadTools]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadReadiness();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [loadReadiness]);

  function navigate(next: Page) {
    setPage(next);
    setActionError('');
    setNotice('');
  }

  function openCrossScenario() {
    setInstruction(CROSS_SCENARIO_INSTRUCTION);
    navigate('console');
  }

  async function refreshAfterRun() {
    await Promise.all([loadTools(), loadOverview(), loadAudit(), loadReadiness()]);
  }

  async function execute(input: AgentRunInput) {
    setBusy(true);
    setActionError('');
    setNotice('');
    setTrustAction(null);
    setTrustActionError('');
    try {
      const result = await runAgent(input);
      setLastRun(result);
      setLastActionId(result.confirmation?.id ?? null);
      if (result.status === 'awaiting_confirmation') {
        setOtp('');
        setPending(result);
        setNotice('计划已生成。请核对风险原因并完成人工确认。');
      } else {
        setPending(null);
        setOtp('');
        setNotice(result.reason);
      }
      await refreshAfterRun();
    } catch (error) {
      setActionError(messageOf(error, '任务执行失败'));
    } finally {
      setBusy(false);
    }
  }

  async function decide(approved: boolean) {
    if (!pending?.confirmation) return;
    const actionId = pending.confirmation.id;
    setBusy(true);
    setActionError('');
    try {
      const result = await resolveConfirmation(actionId, approved, otp);
      setLastRun(result);
      setLastActionId(actionId);
      setPending(null);
      setOtp('');
      setNotice(result.reason);
      setTrustAction(null);
      setTrustActionError('');
      await refreshAfterRun();
    } catch (error) {
      setActionError(messageOf(error, approved ? '确认执行失败' : '拒绝操作失败'));
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
        <div className="topbar-status">
          <span
            className={`status-dot ${auditValid === false ? 'status-bad' : auditValid === null ? 'status-pending' : ''}`}
          />
          {auditValid === false ? '审计链异常' : auditValid === null ? '审计链待校验' : '本地 MVP · 审计链在线'}
          <span className="env-pill">DEV</span>
        </div>
      </header>

      <ReadinessBanner
        snapshot={readiness}
        loading={readinessLoading}
        error={readinessError}
        onRefresh={() => void loadReadiness(true)}
      />

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
            <span>用户 · demo-user</span>
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
            <ScenariosPage writesBlocked={writesBlocked} blockReason={blockReason} />
          )}

          {page === 'console' && (
            <TaskConsolePage
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
            />
          )}

          {page === 'permissions' && (
            <PermissionsPage
              tools={tools}
              loading={toolsLoading}
              error={combineErrors(toolsError, overlayError)}
              notice={sharedNotice}
              busyTool={busyTool}
              onToggle={(tool) => void togglePermission(tool)}
              onRefresh={() => void loadTools(true)}
            />
          )}

          {page === 'audit' && (
            <AuditPage
              audit={audit}
              auditValid={auditValid}
              auditChecked={auditChecked}
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
          otp={otp}
          setOtp={setOtp}
          onDecision={(approved) => void decide(approved)}
          error={actionError}
          writesBlocked={writesBlocked}
          blockReason={blockReason}
        />
      )}
    </div>
  );
}
