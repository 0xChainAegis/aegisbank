"""Structured planning and a confirmation-aware DAG scheduler.

Phase 1 adds the trust layer: pre-planner injection rejection, ActionEnvelope
binding, idempotent confirmations, audited state transitions, layered evidence,
readiness fail-closed gating, and a persisted circuit breaker.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any
from uuid import uuid4

from .audit import AuditService, audit_run_id
from .compensation import CompensationRegistry
from .db import Database
from .domain import ExecutionContext, ExecutionStatus, PlanNode, RiskLevel
from .executor import SandboxViolation, ToolExecutor
from .gateway import PermissionGateway, scan_injection
from .planning.compiler import CompiledPlan, PlanCompilationError, PlanCompiler
from .planning.contracts import ExecutionPlan, Planner, PlanningRequest, PlanStep
from .registry import ToolRegistry
from .risk import DynamicRiskEngine, RiskAssessment
from .trust.action_envelope import (
    ActionEnvelope,
    EnvelopeError,
    EnvelopeExpired,
    EnvelopeMismatch,
    EnvelopeService,
    build_envelopes,
)
from .trust.circuit_breaker import CircuitBreaker
from .trust.evidence import (
    approval_evidence,
    evidence_payload,
    hash_chain_evidence,
    merge_evidence,
    policy_decision_evidence,
    tool_result_evidence,
)
from .trust.mfa import MfaError, MfaResult, MfaService, OtpProvider
from .trust.pause import ActionJournal, PauseRegistry
from .trust.state_machine import (
    ActionState,
    ExecutionOutcomeUnknown,
    IllegalTransition,
    StateMachine,
)


class IntentError(ValueError):
    pass


class ReauthError(ValueError):
    pass


class ExecutionFailedError(ValueError):
    """A predictable execution-time business failure (HTTP 422, not 500)."""


class ExecutionPaused(RuntimeError):
    """Raised between DAG nodes when the action has a pending pause flag."""

    def __init__(
        self,
        *,
        results: list[dict[str, Any]],
        next_index: int,
        pause: dict[str, Any],
        nodes: list[PlanNode],
    ) -> None:
        super().__init__(f"执行已暂停：下一个待执行节点索引 {next_index}")
        self.results = results
        self.next_index = next_index
        self.pause = pause
        self.nodes = nodes


def audit_scope(method):
    @wraps(method)
    def scoped(self, *args, **kwargs):
        token = audit_run_id.set(kwargs.get("action_id"))
        try:
            return method(self, *args, **kwargs)
        finally:
            audit_run_id.reset(token)

    return scoped


def serialized_action(method):
    """Confirm, resume and rollback share one cross-process action owner."""

    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.db.action_lock(str(kwargs["action_id"])):
            return method(self, *args, **kwargs)

    return locked


class DagScheduler:
    def __init__(
        self,
        *,
        planner: Planner,
        registry: ToolRegistry,
        gateway: PermissionGateway,
        risk_engine: DynamicRiskEngine,
        db: Database,
        audit: AuditService,
        confirmation_ttl_seconds: int,
        demo_otp: str,
        mfa: MfaService | None = None,
        executor: ToolExecutor | None = None,
        compensation: CompensationRegistry | None = None,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_window_seconds: int = 60,
        circuit_breaker_lock_seconds: int = 60,
    ) -> None:
        self.planner = planner
        self.registry = registry
        self.gateway = gateway
        self.risk_engine = risk_engine
        self.db = db
        self.audit = audit
        self.compiler = PlanCompiler(registry)
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.demo_otp = demo_otp
        self.mfa = mfa or MfaService([OtpProvider(demo_otp)])
        self.executor = executor or ToolExecutor()
        # ``CompensationRegistry`` defines ``__len__``; an empty registry is
        # falsy, so never use ``or`` here or specs registered later by the
        # compensation extension would land on a different object.
        self.compensation = compensation if compensation is not None else CompensationRegistry()
        self.envelopes = EnvelopeService(db)
        self.breaker = CircuitBreaker(
            db,
            threshold=circuit_breaker_threshold,
            window_seconds=circuit_breaker_window_seconds,
            lock_seconds=circuit_breaker_lock_seconds,
        )
        # Stage 2A: step-level pause flags and the per-action execution journal.
        self.pause = PauseRegistry(db)
        self.journal = ActionJournal(db)

    # ---------- shared helpers ----------
    def _propose(self, request: PlanningRequest) -> ExecutionPlan:
        try:
            return self.planner.plan(request)
        except Exception as exc:
            raise IntentError(f"Planner 生成计划失败：{exc}") from exc

    def _compile(self, plan: ExecutionPlan) -> CompiledPlan:
        try:
            return self.compiler.compile(plan)
        except PlanCompilationError as exc:
            raise IntentError(f"计划校验失败：{exc}") from exc

    def _assess_nodes(
        self, nodes: list[PlanNode], user_id: str, instruction: str
    ) -> dict[str, RiskAssessment]:
        assessments: dict[str, RiskAssessment] = {}
        projected_transfers = 0.0
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            assessments[node.id] = self.risk_engine.assess(
                user_id=user_id,
                tool_name=tool.metadata.name,
                arguments=node.arguments,
                base_risk=tool.metadata.risk_level,
                instruction=instruction,
            )
            if node.tool_name in {"transfer", "transfer_to_contact"}:
                projected_transfers += float(node.arguments.get("amount_cny") or 0)
        if (
            projected_transfers + self.risk_engine.repository.daily_transfer_total_cny(user_id)
            > 1000
        ):
            for node in nodes:
                if node.tool_name in {"transfer", "transfer_to_contact"}:
                    previous = assessments[node.id]
                    assessments[node.id] = RiskAssessment(
                        level=RiskLevel.RED,
                        score=max(previous.score, 80),
                        reasons=[*previous.reasons, "整条计划累计转账将超过 1000 元，需要强验证。"],
                        base_risk=previous.base_risk,
                        requires_reauth=True,
                    )
        return assessments

    @staticmethod
    def _decorate_plan(
        plan_payload: dict[str, Any], assessments: dict[str, RiskAssessment]
    ) -> dict[str, Any]:
        for step in plan_payload.get("steps", []):
            assessment = assessments.get(str(step.get("id")))
            if assessment:
                step["risk_level"] = assessment.level.value
                step["risk_reasons"] = assessment.reasons
                step["requires_reauth"] = assessment.requires_reauth
                step["risk_score"] = assessment.score
        return plan_payload

    @staticmethod
    def _max_assessed_risk(assessments: dict[str, RiskAssessment]) -> RiskLevel:
        order = {RiskLevel.GREEN: 0, RiskLevel.YELLOW: 1, RiskLevel.RED: 2}
        return max(
            (assessment.level for assessment in assessments.values()),
            key=lambda item: order[item],
        )

    @classmethod
    def _resolve_arguments(cls, value: Any, results: dict[str, dict[str, Any]]) -> Any:
        if isinstance(value, dict):
            return {key: cls._resolve_arguments(item, results) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._resolve_arguments(item, results) for item in value]
        if isinstance(value, str):
            match = re.fullmatch(r"\$\{steps\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_.-]+)\}", value)
            if match:
                step_id, path = match.groups()
                current: Any = results.get(step_id)
                if current is None:
                    raise ValueError(f"步骤结果不存在：{step_id}")
                for part in path.split("."):
                    if not isinstance(current, dict) or part not in current:
                        raise ValueError(f"步骤 {step_id} 缺少结果字段：{path}")
                    current = current[part]
                if current is None:
                    raise ValueError(f"步骤 {step_id} 的字段为空：{path}")
                return current
        return value

    def _chain_evidence(self) -> list[dict[str, Any]]:
        try:
            result = self.audit.verify()
        except Exception as exc:  # noqa: BLE001 - evidence must never break a response
            return evidence_payload(hash_chain_evidence(False, f"审计链校验异常：{exc}"))
        if result.get("valid"):
            return evidence_payload(
                hash_chain_evidence(True, f"哈希链校验通过，共 {result.get('checked', 0)} 条")
            )
        return evidence_payload(
            hash_chain_evidence(
                False,
                f"审计链断裂于第 {result.get('broken_at')} 条：{result.get('reason')}",
            )
        )

    def _execution_evidence(self, *, confirmation_state: str) -> list[dict[str, Any]]:
        items = evidence_payload(
            tool_result_evidence(True, "Mock 银行工具返回模拟数据（simulated=True）"),
            policy_decision_evidence(True, "请求已通过统一权限网关"),
        )
        if confirmation_state == "approved":
            items = evidence_payload(approval_evidence(True, "用户明确批准并完成确认复检")) + items
        return items

    @staticmethod
    def _failure_evidence(error: Exception) -> list[dict[str, Any]]:
        return evidence_payload(
            tool_result_evidence(False, f"工具执行失败：{error}"),
            policy_decision_evidence(True, "失败已记录，未自动重试"),
        )

    @staticmethod
    def _blocked_response(
        *,
        run_id: str,
        reason: str,
        audit_entry: dict[str, Any],
        chain_evidence: list[dict[str, Any]],
        risk_level: str = "red",
        plan: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence = merge_evidence(
            evidence_payload(policy_decision_evidence(True, reason)), chain_evidence
        )
        response: dict[str, Any] = {
            "status": ExecutionStatus.BLOCKED.value,
            "run_id": run_id,
            "risk_level": risk_level,
            "reason": reason,
            "audit_id": audit_entry["id"],
            "evidence": evidence,
            "evidence_list": evidence,
        }
        if plan is not None:
            response["plan"] = plan
        if extra:
            response.update(extra)
        return response

    def _load_machine(
        self,
        pending: dict[str, Any],
        *,
        dag_path: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> StateMachine:
        record = dict(pending)
        record["dag_path"] = dag_path
        record["tool_name"] = tool_name
        machine = StateMachine.load(db=self.db, audit=self.audit, record=record)
        machine.arguments = arguments
        machine.dag_path = dag_path
        machine.tool_name = tool_name
        return machine

    @staticmethod
    def _stored_result(pending: dict[str, Any]) -> dict[str, Any] | None:
        raw = pending.get("result_json") or ""
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _finish(self, action_id: str, status: str, response: dict[str, Any]) -> None:
        self.db.set_pending_result(
            action_id, json.dumps(response, ensure_ascii=False, sort_keys=True)
        )
        self.db.resolve_pending(action_id, status)

    # ---------- preview ----------
    def preview(
        self,
        *,
        user_id: str,
        instruction: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        arguments = arguments or {}
        matched = scan_injection(instruction, arguments)
        if matched:
            evidence = evidence_payload(
                policy_decision_evidence(True, "注入规则命中，预览阶段整条拒绝")
            )
            return {
                "status": ExecutionStatus.BLOCKED.value,
                "risk_level": RiskLevel.RED.value,
                "reason": "检测到疑似 Prompt 注入或越权指令，请求在进入 Planner 之前被拒绝。",
                "matched_rules": matched,
                "evidence": evidence,
                "evidence_list": evidence,
            }
        request = PlanningRequest(
            user_id=user_id,
            instruction=instruction,
            tool_name=tool_name,
            arguments=arguments,
        )
        plan = self._propose(request)
        if plan.needs_clarification:
            evidence = evidence_payload(policy_decision_evidence(True, "Planner 请求澄清"))
            return {
                "status": ExecutionStatus.NEEDS_CLARIFICATION.value,
                "plan": plan.model_dump(),
                "reason": plan.clarification,
                "evidence": evidence,
                "evidence_list": evidence,
            }
        compiled = self._compile(plan)
        assessments = self._assess_nodes(compiled.nodes, user_id, instruction)
        risk_level = self._max_assessed_risk(assessments)
        plan_payload = self._decorate_plan(compiled.as_dict(), assessments)
        evidence = merge_evidence(
            evidence_payload(policy_decision_evidence(True, "预览计划通过策略校验")),
            self._chain_evidence(),
        )
        return {
            "status": "planned",
            "plan": plan_payload,
            "risk_level": risk_level.value,
            "risk": {
                "level": risk_level.value,
                "reasons": [
                    reason for assessment in assessments.values() for reason in assessment.reasons
                ],
                "requires_reauth": any(item.requires_reauth for item in assessments.values()),
            },
            "reason": "计划已通过 Schema、工具注册、DAG 依赖和动态风险校验。",
            "evidence": evidence,
            "evidence_list": evidence,
        }

    @staticmethod
    def _dag_path(nodes: list[PlanNode]) -> str:
        return " -> ".join(f"{node.id}:{node.tool_name}" for node in nodes)

    @staticmethod
    def _max_risk(nodes: list[PlanNode], registry: ToolRegistry) -> RiskLevel:
        order = {RiskLevel.GREEN: 0, RiskLevel.YELLOW: 1, RiskLevel.RED: 2}
        return max(
            (registry.get(node.tool_name).metadata.risk_level for node in nodes),
            key=lambda item: order[item],
        )

    @staticmethod
    def _tool_is_read_only(tool) -> bool:
        """A read-only tool is green and uses a read capability, never *:manage."""
        metadata = tool.metadata
        return (
            metadata.risk_level is RiskLevel.GREEN
            and metadata.permission.endswith(":read")
        )

    def _plan_is_read_only(self, nodes: list[PlanNode]) -> bool:
        return bool(nodes) and all(
            self._tool_is_read_only(self.registry.get(node.tool_name)) for node in nodes
        )

    def _restore_plan(self, nodes: list[PlanNode], pending: dict[str, Any]) -> dict[str, Any]:
        stored = json.loads(pending.get("plan_json") or "{}")
        if stored:
            return stored
        restored = ExecutionPlan(
            intent="confirmed_action",
            planner="stored",
            steps=[
                PlanStep(
                    id=node.id,
                    tool_name=node.tool_name,
                    arguments=node.arguments,
                    depends_on=node.depends_on,
                )
                for node in nodes
            ],
        )
        return self.compiler.compile(restored).as_dict()

    # ---------- run ----------
    @audit_scope
    def run(
        self,
        *,
        user_id: str,
        instruction: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
        role: str = "user",
    ) -> dict[str, Any]:
        arguments = arguments or {}
        run_id = uuid4().hex
        audit_run_id.set(run_id)

        matched = scan_injection(instruction, arguments)
        if matched:
            self.breaker.record_injection(user_id=user_id)
            audit_entry = self.audit.record(
                event="injection_blocked",
                user_id=user_id,
                instruction=instruction,
                dag_path="pre-planner",
                tool_name=tool_name or "planner",
                arguments=arguments,
                result={
                    "stage": "pre_planner",
                    "matched_patterns": matched,
                    "note": "整条请求拒绝，未进入 Planner，未生成可执行计划",
                },
                confirmation_state="blocked",
                risk_level=RiskLevel.RED.value,
                evidence=evidence_payload(
                    policy_decision_evidence(True, "注入规则命中，请求在 Planner 之前拒绝")
                ),
            )
            return self._blocked_response(
                run_id=run_id,
                reason=(
                    "检测到疑似 Prompt 注入或越权指令，整条请求已在进入 Planner 之前拒绝，"
                    "未生成任何可执行计划。"
                ),
                audit_entry=audit_entry,
                chain_evidence=self._chain_evidence(),
                extra={"matched_rules": matched},
            )

        request = PlanningRequest(
            user_id=user_id,
            instruction=instruction,
            tool_name=tool_name,
            arguments=arguments,
        )
        plan = self._propose(request)
        if plan.needs_clarification:
            evidence = evidence_payload(
                policy_decision_evidence(True, "Planner 判定信息不足，转为澄清")
            )
            audit_entry = self.audit.record(
                event="planning_clarification",
                user_id=user_id,
                instruction=instruction,
                dag_path="planner",
                tool_name="planner",
                arguments={"tool_name": tool_name, "arguments": arguments, "role": role},
                result={"clarification": plan.clarification, "semantic": (
                    plan.semantic.model_dump(mode="json") if plan.semantic else None
                )},
                confirmation_state="clarification",
                risk_level=RiskLevel.GREEN.value,
                evidence=evidence,
            )
            return {
                "status": ExecutionStatus.NEEDS_CLARIFICATION.value,
                "run_id": run_id,
                "risk_level": RiskLevel.GREEN.value,
                "reason": plan.clarification,
                "plan": plan.model_dump(),
                "audit_id": audit_entry["id"],
                "evidence": evidence,
                "evidence_list": evidence,
            }

        compiled = self._compile(plan)
        nodes = compiled.nodes
        assessments = self._assess_nodes(nodes, user_id, instruction)
        risk_level = self._max_assessed_risk(assessments)
        plan_payload = self._decorate_plan(compiled.as_dict(), assessments)
        read_only_plan = self._plan_is_read_only(nodes)
        breaker = self.breaker.status(user_id=user_id)
        if breaker["open"] and not read_only_plan:
            reason = CircuitBreaker.reason(breaker)
            audit_entry = self.audit.record(
                event="circuit_breaker_open",
                user_id=user_id,
                instruction=instruction,
                dag_path="circuit-breaker",
                tool_name=tool_name or "planner",
                arguments=arguments,
                result={
                    "reason": reason,
                    "breaker": breaker,
                    "blocked_scope": "write",
                    "read_only_bypass": read_only_plan,
                },
                confirmation_state="blocked",
                risk_level=risk_level.value,
                evidence=evidence_payload(
                    policy_decision_evidence(True, "熔断器打开，仅写操作被拒绝；只读查询放行")
                ),
            )
            return self._blocked_response(
                run_id=run_id,
                reason=reason,
                audit_entry=audit_entry,
                chain_evidence=self._chain_evidence(),
                risk_level=risk_level.value,
                plan=plan_payload,
                extra={"breaker": breaker, "blocked_scope": "write"},
            )
        if not read_only_plan:
            self.breaker.record_risk_level(user_id=user_id, level=risk_level.value)
        dag_path = compiled.dag_path
        decisions: list[tuple[PlanNode, Any, RiskAssessment]] = []
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            assessment = assessments[node.id]
            decision = self.gateway.evaluate(
                user_id=user_id,
                tool_name=tool.metadata.name,
                risk_level=assessment.level,
                permission=tool.metadata.permission,
                instruction=instruction,
                arguments=node.arguments,
                role=role,
            )
            decisions.append((node, decision, assessment))

        risk = {
            "level": risk_level.value,
            "reasons": [
                reason for assessment in assessments.values() for reason in assessment.reasons
            ],
            "requires_reauth": any(item.requires_reauth for item in assessments.values()),
        }

        blocked = next(
            (
                (node, decision, assessment)
                for node, decision, assessment in decisions
                if decision.denied
            ),
            None,
        )
        if blocked:
            node, decision, assessment = blocked
            evidence = evidence_payload(policy_decision_evidence(True, decision.reason))
            audit_entry = self.audit.record(
                event="gateway_blocked",
                user_id=user_id,
                instruction=instruction,
                dag_path=dag_path,
                tool_name=node.tool_name,
                arguments=node.arguments,
                result={
                    "reason": decision.reason,
                    "plan_hash": compiled.plan_hash,
                    "risk": assessment.as_dict(),
                },
                confirmation_state="blocked",
                risk_level=assessment.level.value,
                evidence=evidence,
            )
            return {
                "status": ExecutionStatus.BLOCKED.value,
                "run_id": run_id,
                "risk_level": assessment.level.value,
                "risk": risk,
                "reason": decision.reason,
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
                "evidence": evidence,
                "evidence_list": evidence,
            }

        pending = next(
            (
                (node, decision, assessment)
                for node, decision, assessment in decisions
                if not decision.allowed_now
            ),
            None,
        )
        if pending:
            _, decision, _ = pending
            requires_reauth = any(item.requires_reauth for item in assessments.values())
            action_id = f"cfm_{uuid4().hex}"
            run_id = action_id
            audit_run_id.set(action_id)
            created = datetime.now(UTC)
            expires = created + timedelta(seconds=self.confirmation_ttl_seconds)
            permissions = {
                node.id: self.registry.get(node.tool_name).metadata.permission for node in nodes
            }
            envelopes = build_envelopes(
                user_id=user_id,
                plan_hash=compiled.plan_hash,
                nodes=nodes,
                assessments=assessments,
                permissions=permissions,
                issued_at=created,
                expires_at=expires,
            )
            self.db.create_pending(
                {
                    "id": action_id,
                    "user_id": user_id,
                    "instruction": instruction,
                    "dag_json": json.dumps([node.as_dict() for node in nodes], ensure_ascii=False),
                    "plan_json": json.dumps(plan_payload, ensure_ascii=False),
                    "risk_level": risk_level.value,
                    "requires_reauth": int(requires_reauth),
                    "status": "pending",
                    "created_at": created.isoformat(timespec="seconds"),
                    "expires_at": expires.isoformat(timespec="seconds"),
                    "envelopes_json": json.dumps(
                        [envelope.as_dict(include_token=True) for envelope in envelopes],
                        ensure_ascii=False,
                    ),
                    "state": ActionState.DRAFT.value,
                }
            )
            machine = StateMachine(
                db=self.db,
                action_id=action_id,
                audit=self.audit,
                user_id=user_id,
                instruction=instruction,
                dag_path=dag_path,
                tool_name=nodes[0].tool_name,
                arguments=nodes[0].arguments,
                risk_level=risk_level.value,
            )
            target = (
                ActionState.AWAITING_REAUTH
                if requires_reauth
                else ActionState.AWAITING_CONFIRMATION
            )
            machine.transition(target, reason="等待用户确认")
            evidence = merge_evidence(
                evidence_payload(policy_decision_evidence(True, decision.reason)),
                self._chain_evidence(),
            )
            audit_entry = self.audit.record(
                event="confirmation_requested",
                user_id=user_id,
                instruction=instruction,
                dag_path=dag_path,
                tool_name=nodes[0].tool_name,
                arguments=nodes[0].arguments,
                result={
                    "reason": decision.reason,
                    "plan_hash": compiled.plan_hash,
                    "risk": risk,
                    "envelopes": [envelope.masked() for envelope in envelopes],
                },
                confirmation_state="pending",
                risk_level=risk_level.value,
                evidence=evidence,
            )
            return {
                "status": ExecutionStatus.AWAITING_CONFIRMATION.value,
                "run_id": run_id,
                "risk_level": risk_level.value,
                "risk": risk,
                "reason": decision.reason,
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
                "confirmation": {
                    "id": action_id,
                    "requires_reauth": requires_reauth,
                    "expires_at": expires.isoformat(timespec="seconds"),
                    "state": target.value,
                    "envelopes": [envelope.masked() for envelope in envelopes],
                },
                "evidence": evidence,
                "evidence_list": evidence,
            }

        try:
            results = self._execute_nodes(
                nodes=nodes,
                user_id=user_id,
                instruction=instruction,
                run_id=run_id,
                confirmation_state="not_required",
                action_id=run_id,
                plan=plan_payload,
                risk_level=risk_level.value,
                role=role,
            )
        except ExecutionPaused as paused:
            response = self._paused_response(
                action_id=run_id,
                user_id=user_id,
                instruction=instruction,
                plan=plan_payload,
                risk_level=risk_level.value,
                results=paused.results,
                pause=paused.pause,
                next_index=paused.next_index,
                nodes=paused.nodes,
                risk=risk,
            )
            self.journal.update_status(
                run_id,
                "paused",
                reason=paused.pause.get("reason") or "用户请求暂停",
                response=response,
            )
            return response
        except ExecutionOutcomeUnknown as exc:
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            reason = f"执行结果不确定：{exc}；不得自动重复执行，需人工对账。"
            response = {
                "status": ExecutionStatus.UNKNOWN.value,
                "run_id": run_id,
                "risk_level": risk_level.value,
                "risk": risk,
                "reason": reason,
                "plan": plan_payload,
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self.journal.update_status(run_id, "unknown", reason=reason, response=response)
            return response
        except Exception as exc:  # noqa: BLE001 - tool errors trigger compensation
            rollback = self._compensate(
                action_id=run_id,
                user_id=user_id,
                instruction=instruction,
                role=role,
            )
            executed = self._executed_results(run_id)
            if rollback["status"] == "blocked":
                reason = f"执行失败：{exc}；回滚被阻止：存在不可撤销步骤，需人工对账。"
                response = self._rollback_response(
                    action_id=run_id,
                    plan=plan_payload,
                    risk_level=risk_level.value,
                    results=executed,
                    rollback=rollback,
                    status=ExecutionStatus.UNKNOWN.value,
                    reason=reason,
                    risk=risk,
                )
                self.journal.update_status(run_id, "unknown", reason=reason, response=response)
                return response
            if rollback["status"] in {"completed", "partial", "failed"}:
                rolled_back = rollback["status"] == "completed"
                status = (
                    ExecutionStatus.ROLLED_BACK.value
                    if rolled_back
                    else ExecutionStatus.UNKNOWN.value
                )
                reason = (
                    f"执行失败后已自动回滚：{rollback['reason']}"
                    if rolled_back
                    else f"执行失败后补偿未全部成功：{rollback['reason']}"
                )
                response = self._rollback_response(
                    action_id=run_id,
                    plan=plan_payload,
                    risk_level=risk_level.value,
                    results=executed,
                    rollback=rollback,
                    status=status,
                    reason=reason,
                    risk=risk,
                )
                self.journal.update_status(run_id, status, reason=reason, response=response)
                return response
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            response = {
                "status": ExecutionStatus.FAILED.value,
                "run_id": run_id,
                "risk_level": risk_level.value,
                "risk": risk,
                "reason": f"工具执行失败：{exc}",
                "plan": plan_payload,
                "results": executed,
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self.journal.update_status(
                run_id, "failed", reason=f"工具执行失败：{exc}", response=response
            )
            return response
        evidence = merge_evidence(
            self._execution_evidence(confirmation_state="not_required"),
            self._chain_evidence(),
        )
        response = {
            "status": ExecutionStatus.COMPLETED.value,
            "run_id": run_id,
            "risk_level": risk_level.value,
            "risk": risk,
            "reason": "全部节点通过权限网关。",
            "plan": plan_payload,
            "results": results,
            "evidence": evidence,
            "evidence_list": evidence,
        }
        self.journal.update_status(
            run_id, "completed", reason="全部节点执行完成", response=response
        )
        return response

    # ---------- confirmation ----------
    def _recompute_plan(self, pending: dict[str, Any], nodes: list[PlanNode]) -> CompiledPlan:
        stored = json.loads(pending.get("plan_json") or "{}")
        if stored.get("steps"):
            plan = ExecutionPlan(
                intent=str(stored.get("intent") or "confirmed_action"),
                planner=str(stored.get("planner") or "stored"),
                semantic=stored.get("semantic"),
                steps=[
                    PlanStep(
                        id=str(step["id"]),
                        tool_name=str(step["tool_name"]),
                        arguments=dict(step.get("arguments") or {}),
                        depends_on=[str(item) for item in step.get("depends_on") or []],
                    )
                    for step in stored["steps"]
                ],
            )
            return self.compiler.compile(plan)
        restored = ExecutionPlan(
            intent="confirmed_action",
            planner="stored",
            steps=[
                PlanStep(
                    id=node.id,
                    tool_name=node.tool_name,
                    arguments=node.arguments,
                    depends_on=node.depends_on,
                )
                for node in nodes
            ],
        )
        return self.compiler.compile(restored)

    def _verify_envelopes(
        self,
        *,
        pending: dict[str, Any],
        nodes: list[PlanNode],
        compiled: CompiledPlan,
        assessments: dict[str, RiskAssessment],
        user_id: str,
    ) -> list[ActionEnvelope]:
        raw = json.loads(pending.get("envelopes_json") or "[]")
        envelopes = [ActionEnvelope.from_dict(item) for item in raw]
        if (
            len(envelopes) != len(nodes)
            or {item.step_id for item in envelopes} != {node.id for node in nodes}
            or len({item.nonce for item in envelopes}) != len(envelopes)
        ):
            raise EnvelopeMismatch("ActionEnvelope 必须与计划步骤完整且一一对应。")
        node_by_id = {node.id: node for node in nodes}
        for envelope in envelopes:
            node = node_by_id.get(envelope.step_id)
            if node is None:
                raise EnvelopeMismatch("ActionEnvelope 引用了不存在的计划步骤。")
            permission = self.registry.get(node.tool_name).metadata.permission
            self.envelopes.verify(
                envelope,
                user_id=user_id,
                expected_plan_hash=compiled.plan_hash,
                step=node,
                assessment=assessments[node.id],
                permission=permission,
            )
        return envelopes

    def _claim_envelopes(self, envelopes: list[ActionEnvelope], *, action_id: str) -> None:
        if envelopes:
            self.envelopes.claim_nonces(envelopes, action_id=action_id)

    @audit_scope
    @serialized_action
    def confirm(
        self,
        *,
        user_id: str,
        action_id: str,
        approved: bool,
        reauth_token: str | None,
        role: str = "user",
        mfa_provider: str | None = None,
    ) -> dict[str, Any]:
        pending = self.db.get_pending(action_id)
        if pending is None:
            raise IntentError("确认请求不存在。")
        if pending["user_id"] != user_id:
            raise IntentError("确认请求不属于当前用户。")
        if self.gateway.authz is not None:
            self.gateway.authz.require(role, "tool:execute")
        replay = self._stored_result(pending)
        if replay is not None:
            return replay
        if pending["status"] != "pending":
            raise IntentError(f"确认请求已处理：{pending['status']}。")

        breaker = self.breaker.status(user_id=user_id)
        if breaker["open"]:
            reason = CircuitBreaker.reason(breaker)
            audit_entry = self.audit.record(
                event="circuit_breaker_open",
                user_id=user_id,
                instruction=pending["instruction"],
                dag_path="circuit-breaker",
                tool_name="confirmation",
                arguments={},
                result={
                    "reason": reason,
                    "breaker": breaker,
                    "blocked_scope": "confirmation",
                },
                confirmation_state="blocked",
                risk_level=RiskLevel.RED.value,
                evidence=evidence_payload(
                    policy_decision_evidence(True, "熔断器打开，确认操作被拒绝；只读查询不受影响")
                ),
            )
            response = self._blocked_response(
                run_id=action_id,
                reason=reason,
                audit_entry=audit_entry,
                chain_evidence=self._chain_evidence(),
                extra={"breaker": breaker, "blocked_scope": "confirmation"},
            )
            self._finish(action_id, "blocked", response)
            return response

        nodes = [PlanNode.from_dict(item) for item in json.loads(pending["dag_json"])]
        plan_payload = self._restore_plan(nodes, pending)
        dag_path = self._dag_path(nodes)
        machine = self._load_machine(
            pending,
            dag_path=dag_path,
            tool_name=nodes[0].tool_name,
            arguments=nodes[0].arguments,
        )
        now = datetime.now(UTC)
        expires_at = datetime.fromisoformat(pending["expires_at"])
        if now > expires_at:
            machine.transition(ActionState.EXPIRED, reason="确认请求已过期")
            self.db.resolve_pending(action_id, "expired")
            raise EnvelopeExpired("确认请求已过期，请重新发起操作。")

        assessments = self._assess_nodes(nodes, user_id, pending["instruction"])
        plan_payload = self._decorate_plan(plan_payload, assessments)
        current_risk = self._max_assessed_risk(assessments)
        requires_reauth = any(item.requires_reauth for item in assessments.values())

        try:
            try:
                compiled = self._recompute_plan(pending, nodes)
            except (ValueError, TypeError, KeyError) as exc:
                raise EnvelopeMismatch("存储计划不符合契约，请重新发起操作。") from exc
            envelopes = self._verify_envelopes(
                pending=pending,
                nodes=nodes,
                compiled=compiled,
                assessments=assessments,
                user_id=user_id,
            )
        except EnvelopeError:
            self.db.resolve_pending(action_id, "blocked")
            raise

        if not approved:
            self._claim_envelopes(envelopes, action_id=action_id)
            machine.transition(ActionState.REJECTED, reason="用户拒绝本次操作")
            evidence = merge_evidence(
                evidence_payload(
                    approval_evidence(False, "用户拒绝，未执行任何工具"),
                    policy_decision_evidence(True, "拒绝决策已记录"),
                ),
                self._chain_evidence(),
            )
            audit_entry = self.audit.record(
                event="confirmation_rejected",
                user_id=user_id,
                instruction=pending["instruction"],
                dag_path=dag_path,
                tool_name=nodes[0].tool_name,
                arguments=nodes[0].arguments,
                result={"reason": "用户拒绝了本次操作"},
                confirmation_state="rejected",
                risk_level=pending["risk_level"],
                evidence=evidence,
            )
            response = {
                "status": ExecutionStatus.REJECTED.value,
                "run_id": action_id,
                "risk_level": pending["risk_level"],
                "reason": "用户已拒绝该操作。",
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self._finish(action_id, "rejected", response)
            return response

        if requires_reauth and machine.state is not ActionState.AWAITING_REAUTH:
            machine.transition(ActionState.AWAITING_REAUTH, reason="红色操作需要二次身份校验")
        mfa_result: MfaResult | None = None
        if requires_reauth:
            try:
                allowed = set.intersection(
                    *[
                        set(
                            self.mfa.providers_for(node.tool_name, assessments[node.id].level.value)
                        )
                        for node in nodes
                        if assessments[node.id].requires_reauth
                    ]
                )
                selected = mfa_provider or self.mfa.default_provider
                self.mfa.resolve(selected)
                if selected not in allowed:
                    raise MfaError("该验证方式不在本次计划的 MFA 策略允许范围内。")
                mfa_result = self.mfa.verify(
                    reauth_token,
                    user_id=user_id,
                    provider=mfa_provider,
                )
            except MfaError as exc:
                # MFA/OTP failures are identity-verification failures, not tool
                # execution failures and must never advance the breaker.
                self.audit.record(
                    event="mfa_failed",
                    user_id=user_id,
                    instruction=pending["instruction"],
                    dag_path=self._dag_path(nodes),
                    tool_name=nodes[0].tool_name,
                    arguments=nodes[0].arguments,
                    result={"error": str(exc), "mfa": None},
                    confirmation_state="reauth_failed",
                    risk_level=pending["risk_level"],
                )
                raise ReauthError(f"二次身份校验失败：{exc}") from exc
            if not mfa_result.ok:
                # Wrong OTP is an authentication failure; keep retry UX and the
                # circuit breaker untouched.
                self.audit.record(
                    event="mfa_failed",
                    user_id=user_id,
                    instruction=pending["instruction"],
                    dag_path=self._dag_path(nodes),
                    tool_name=nodes[0].tool_name,
                    arguments=nodes[0].arguments,
                    result={"mfa": mfa_result.as_dict()},
                    confirmation_state="reauth_failed",
                    risk_level=pending["risk_level"],
                )
                raise ReauthError(f"二次身份校验失败：{mfa_result.detail}")

        # Re-check permissions and dynamic risk immediately before execution.
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            assessment = assessments[node.id]
            decision = self.gateway.evaluate(
                user_id=user_id,
                tool_name=tool.metadata.name,
                risk_level=assessment.level,
                permission=tool.metadata.permission,
                instruction=pending["instruction"],
                arguments=node.arguments,
                role=role,
            )
            if decision.denied:
                machine.transition(
                    ActionState.FAILED, reason=f"确认后复检未通过：{decision.reason}"
                )
                evidence = merge_evidence(
                    evidence_payload(
                        policy_decision_evidence(False, decision.reason),
                    ),
                    self._chain_evidence(),
                )
                audit_entry = self.audit.record(
                    event="gateway_blocked",
                    user_id=user_id,
                    instruction=pending["instruction"],
                    dag_path=dag_path,
                    tool_name=node.tool_name,
                    arguments=node.arguments,
                    result={"reason": decision.reason, "risk": assessment.as_dict()},
                    confirmation_state="blocked",
                    risk_level=assessment.level.value,
                    evidence=evidence,
                )
                response = {
                    "status": ExecutionStatus.BLOCKED.value,
                    "run_id": action_id,
                    "risk_level": assessment.level.value,
                    "reason": f"确认后复检未通过：{decision.reason}",
                    "plan": plan_payload,
                    "audit_id": audit_entry["id"],
                    "evidence": evidence,
                    "evidence_list": evidence,
                }
                self._finish(action_id, "blocked", response)
                return response

        machine.transition(ActionState.APPROVED, reason="用户明确批准执行")
        envelopes = self.envelopes.approve(
            envelopes, action_id=action_id, reauth_verified=requires_reauth
        )
        self._claim_envelopes(envelopes, action_id=action_id)
        self.db.set_pending_envelopes(
            action_id,
            json.dumps(
                [envelope.as_dict(include_token=True) for envelope in envelopes],
                ensure_ascii=False,
            ),
        )
        approval_items = evidence_payload(
            approval_evidence(
                True,
                "用户明确批准" + ("并完成二次身份校验" if requires_reauth else ""),
            ),
            policy_decision_evidence(True, "确认前复检通过"),
        )
        audit_entry = self.audit.record(
            event="confirmation_approved",
            user_id=user_id,
            instruction=pending["instruction"],
            dag_path=dag_path,
            tool_name=nodes[0].tool_name,
            arguments=nodes[0].arguments,
            result={
                "reason": "用户明确批准执行",
                "envelopes": [envelope.masked() for envelope in envelopes],
                "mfa": mfa_result.as_dict() if mfa_result is not None else None,
            },
            confirmation_state="approved",
            risk_level=pending["risk_level"],
            evidence=merge_evidence(approval_items, self._chain_evidence()),
        )
        machine.transition(ActionState.EXECUTING, reason="开始执行已确认动作")
        plan_payload["authorization"] = {
            "risk_level": current_risk.value,
            "mfa_verified": bool(mfa_result and mfa_result.ok),
            "user_id": user_id,
            "expires_at": pending["expires_at"],
        }
        results: list[dict[str, Any]] = []
        current_risk_payload = {
            "level": current_risk.value,
            "reasons": [
                reason for assessment in assessments.values() for reason in assessment.reasons
            ],
            "requires_reauth": requires_reauth,
        }
        try:
            results = self._execute_nodes(
                nodes=nodes,
                user_id=user_id,
                instruction=pending["instruction"],
                run_id=action_id,
                confirmation_state="approved",
                action_id=action_id,
                plan=plan_payload,
                risk_level=current_risk.value,
                role=role,
            )
        except ExecutionPaused as paused:
            machine.transition(
                ActionState.PAUSED,
                reason=f"执行已暂停：{paused.pause.get('reason') or '用户请求暂停'}",
            )
            response = self._paused_response(
                action_id=action_id,
                user_id=user_id,
                instruction=pending["instruction"],
                plan=plan_payload,
                risk_level=current_risk.value,
                results=paused.results,
                pause=paused.pause,
                next_index=paused.next_index,
                nodes=paused.nodes,
                risk=current_risk_payload,
            )
            self._finish(action_id, "paused", response)
            return response
        except ExecutionOutcomeUnknown as exc:
            machine.transition(ActionState.UNKNOWN, reason=f"执行结果不确定：{exc}")
            evidence = merge_evidence(
                approval_items,
                self._failure_evidence(exc),
                self._chain_evidence(),
            )
            response = {
                "status": ExecutionStatus.UNKNOWN.value,
                "run_id": action_id,
                "risk_level": current_risk.value,
                "risk": current_risk_payload,
                "reason": f"执行结果不确定：{exc}；不得自动重复下单，请先对账。",
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self.journal.update_status(
                action_id,
                "unknown",
                reason=f"执行结果不确定：{exc}",
                response=response,
            )
            self._finish(action_id, ExecutionStatus.UNKNOWN.value, response)
            return response
        except Exception as exc:  # noqa: BLE001 - failure triggers reverse compensation
            rollback = self._compensate(
                action_id=action_id,
                user_id=user_id,
                instruction=pending["instruction"],
                role=role,
            )
            executed = self._executed_results(action_id)
            if rollback["status"] == "blocked":
                machine.transition(ActionState.UNKNOWN, reason="回滚被阻止：存在不可撤销步骤")
                reason = f"执行失败：{exc}；回滚被阻止：存在不可撤销步骤，需人工对账。"
                response = self._rollback_response(
                    action_id=action_id,
                    plan=plan_payload,
                    risk_level=current_risk.value,
                    results=executed,
                    rollback=rollback,
                    status=ExecutionStatus.UNKNOWN.value,
                    reason=reason,
                    risk=current_risk_payload,
                )
                response["audit_id"] = audit_entry["id"]
                self._finish(action_id, "unknown", response)
                return response
            if rollback["status"] in {"completed", "partial", "failed"}:
                rolled_back = rollback["status"] == "completed"
                status = (
                    ExecutionStatus.ROLLED_BACK.value
                    if rolled_back
                    else ExecutionStatus.UNKNOWN.value
                )
                machine.transition(
                    ActionState.ROLLED_BACK if rolled_back else ActionState.UNKNOWN,
                    reason=rollback["reason"],
                )
                reason = (
                    f"执行失败后已自动回滚：{rollback['reason']}"
                    if rolled_back
                    else f"执行失败后补偿未全部成功：{rollback['reason']}"
                )
                response = self._rollback_response(
                    action_id=action_id,
                    plan=plan_payload,
                    risk_level=current_risk.value,
                    results=executed,
                    rollback=rollback,
                    status=status,
                    reason=reason,
                    risk=current_risk_payload,
                )
                response["audit_id"] = audit_entry["id"]
                self._finish(action_id, status, response)
                return response
            machine.transition(ActionState.FAILED, reason=f"执行失败：{exc}")
            self.audit.record(
                event="action_failed",
                user_id=user_id,
                instruction=pending["instruction"],
                dag_path=dag_path,
                tool_name=nodes[0].tool_name,
                arguments=nodes[0].arguments,
                result={"error": str(exc)},
                confirmation_state="failed",
                risk_level=pending["risk_level"],
                evidence=self._failure_evidence(exc),
            )
            self.journal.update_status(action_id, "failed", reason=f"执行失败：{exc}")
            self.db.resolve_pending(action_id, "failed")
            raise ExecutionFailedError(f"确认后执行失败：{exc}") from exc

        machine.transition(ActionState.COMPLETED, reason="全部节点执行完成")
        evidence = merge_evidence(
            approval_items,
            self._execution_evidence(confirmation_state="approved"),
            self._chain_evidence(),
        )
        response = {
            "status": ExecutionStatus.COMPLETED.value,
            "run_id": action_id,
            "risk_level": current_risk.value,
            "risk": {
                "level": current_risk.value,
                "reasons": [
                    reason for assessment in assessments.values() for reason in assessment.reasons
                ],
                "requires_reauth": requires_reauth,
            },
            "reason": "确认通过，任务已执行。",
            "plan": plan_payload,
            "results": results,
            "audit_id": audit_entry["id"],
            "evidence": evidence,
            "evidence_list": evidence,
        }
        self.journal.update_status(
            action_id, "completed", reason="全部节点执行完成", response=response
        )
        self._finish(action_id, "completed", response)
        return response

    # ---------- execution ----------
    def _execute_nodes(
        self,
        *,
        nodes: list[PlanNode],
        user_id: str,
        instruction: str,
        run_id: str,
        confirmation_state: str,
        action_id: str | None = None,
        plan: dict[str, Any] | None = None,
        risk_level: str = "green",
        role: str = "user",
        start_index: int = 0,
        prior_results: list[dict[str, Any]] | None = None,
        count_failures: bool = True,
    ) -> list[dict[str, Any]]:
        dag_path = self._dag_path(nodes)
        read_only_plan = self._plan_is_read_only(nodes)
        results: list[dict[str, Any]] = []
        results_by_id: dict[str, dict[str, Any]] = {}
        for item in prior_results or []:
            stored_node = str(item.get("node_id") or "")
            stored_result = item.get("result")
            if stored_node and isinstance(stored_result, dict):
                results.append(stored_result)
                results_by_id[stored_node] = stored_result
        if action_id and start_index == 0:
            self.journal.begin(
                action_id,
                user_id=user_id,
                instruction=instruction,
                role=role,
                nodes=nodes,
                plan=plan,
                risk_level=risk_level,
            )
        for index, node in enumerate(nodes):
            if index < start_index:
                continue
            tool = self.registry.get(node.tool_name)
            if action_id:
                pause = self.pause.status(action_id)
                if pause["paused"]:
                    reason = pause["reason"] or "用户请求暂停"
                    self.journal.append_entry(
                        action_id,
                        node_id=node.id,
                        tool_name=node.tool_name,
                        phase="paused",
                        status="paused",
                        arguments=node.arguments,
                        result={"reason": reason, "next_index": index},
                        risk_level=tool.metadata.risk_level.value,
                    )
                    self.journal.update_status(action_id, "paused", reason=reason)
                    raise ExecutionPaused(
                        results=list(results),
                        next_index=index,
                        pause=pause,
                        nodes=list(nodes),
                    )
            authorization = (plan or {}).get("authorization") or {}
            authorized_risk = RiskLevel(authorization.get("risk_level") or "green")
            context = ExecutionContext(
                user_id=user_id,
                instruction=instruction,
                run_id=run_id,
                dag_path=dag_path,
                approved_risk=authorized_risk,
                reauth_verified=authorization.get("mfa_verified") is True,
            )
            try:
                resolved_args = self._resolve_arguments(node.arguments, results_by_id)
            except Exception as exc:  # noqa: BLE001
                self.audit.record(
                    event="tool_failed",
                    user_id=user_id,
                    instruction=instruction,
                    dag_path=dag_path,
                    tool_name=node.tool_name,
                    arguments=node.arguments,
                    result={"error": str(exc)},
                    confirmation_state=confirmation_state,
                    risk_level=tool.metadata.risk_level.value,
                    evidence=self._failure_evidence(exc),
                )
                raise
            assessment = self.risk_engine.assess(
                user_id=user_id,
                tool_name=tool.metadata.name,
                arguments=resolved_args,
                base_risk=tool.metadata.risk_level,
                instruction=instruction,
            )

            risk_holder = {"assessment": assessment}

            def authorize_node(
                tool=tool,
                node=node,
                resolved_args=resolved_args,
                authorized_risk=authorized_risk,
                context=context,
                authorization=authorization,
                risk_holder=risk_holder,
            ):
                nonlocal assessment
                assessment = self.risk_engine.assess(
                    user_id=user_id,
                    tool_name=tool.metadata.name,
                    arguments=resolved_args,
                    base_risk=tool.metadata.risk_level,
                    instruction=instruction,
                )
                risk_holder["assessment"] = assessment
                decision = self.gateway.evaluate(
                    user_id=user_id,
                    tool_name=node.tool_name,
                    risk_level=assessment.level,
                    permission=tool.metadata.permission,
                    instruction=instruction,
                    arguments=resolved_args,
                    role=role,
                )
                if decision.denied:
                    raise PermissionError(decision.reason)
                if not read_only_plan and self.breaker.is_open(user_id=user_id):
                    raise PermissionError("熔断已打开，执行前复检拒绝写入节点。")
                if decision.outcome == "confirm":
                    if authorized_risk is RiskLevel.GREEN or (
                        assessment.requires_reauth and not context.reauth_verified
                    ):
                        raise EnvelopeMismatch("步骤风险超出已确认范围，禁止继续执行。")
                    if datetime.now(UTC) > datetime.fromisoformat(authorization["expires_at"]):
                        raise EnvelopeExpired("执行授权已过期，禁止继续执行。")

            def persist_success(
                payload,
                node=node,
                index=index,
                resolved_args=resolved_args,
                risk_holder=risk_holder,
            ):
                assessment = risk_holder["assessment"]
                payload["risk"] = assessment.as_dict()
                self.audit.record(
                    event="tool_executed",
                    step_id=node.id,
                    user_id=user_id,
                    instruction=instruction,
                    dag_path=dag_path,
                    tool_name=node.tool_name,
                    arguments=resolved_args,
                    result=payload,
                    confirmation_state=confirmation_state,
                    risk_level=assessment.level.value,
                    evidence=self._execution_evidence(confirmation_state=confirmation_state),
                )
                if action_id:
                    self.journal.record_execution(
                        action_id,
                        index=index + 1,
                        results=[*results, payload],
                        node=node,
                        arguments=resolved_args,
                        result=payload,
                        risk_level=assessment.level.value,
                    )

            try:
                result = self.executor.execute(
                    tool,
                    resolved_args,
                    context,
                    on_success=persist_success,
                    authorize=authorize_node,
                )
            except ExecutionOutcomeUnknown as exc:
                self.audit.record(
                    event="tool_outcome_unknown",
                    user_id=user_id,
                    instruction=instruction,
                    dag_path=dag_path,
                    tool_name=node.tool_name,
                    arguments=resolved_args,
                    result={"error": str(exc), "risk": assessment.as_dict()},
                    confirmation_state=confirmation_state,
                    risk_level=assessment.level.value,
                    evidence=evidence_payload(
                        tool_result_evidence(False, f"执行结果未知：{exc}"),
                        policy_decision_evidence(True, "已标记 UNKNOWN，禁止自动重试"),
                    ),
                )
                raise
            except Exception as exc:  # noqa: BLE001 - tool errors become audited failures
                if isinstance(exc, SandboxViolation) and getattr(exc, "outcome_unknown", False):
                    raise ExecutionOutcomeUnknown(str(exc)) from exc
                if count_failures:
                    self.breaker.record_failure(user_id=user_id)
                self.audit.record(
                    event="tool_failed",
                    user_id=user_id,
                    instruction=instruction,
                    dag_path=dag_path,
                    tool_name=node.tool_name,
                    arguments=resolved_args,
                    result={"error": str(exc), "risk": assessment.as_dict()},
                    confirmation_state=confirmation_state,
                    risk_level=assessment.level.value,
                    evidence=self._failure_evidence(exc),
                )
                raise
            self.breaker.record_success(user_id=user_id, read_only=read_only_plan)
            result["risk"] = assessment.as_dict()
            results_by_id[node.id] = result
            results.append(result)
        return results

    # ---------- pause / resume / compensation ----------
    def _executed_results(self, action_id: str) -> list[dict[str, Any]]:
        return [entry["result"] for entry in self.journal.executed_entries(action_id)]

    @staticmethod
    def _compensation_arguments(entry: dict[str, Any]) -> dict[str, Any]:
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        arguments: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
        arguments["original_arguments"] = entry.get("arguments") or {}
        arguments["original_result"] = result
        arguments["compensating_node_id"] = entry.get("node_id")
        return arguments

    def _blocked_compensation_steps(
        self, entries: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        blocked: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        for entry in entries:
            tool_name = str(entry["tool_name"])
            base = {
                "node_id": str(entry["node_id"]),
                "tool_name": tool_name,
                "risk_level": str(entry.get("risk_level") or "green"),
            }
            try:
                tool = self.registry.get(tool_name)
            except KeyError:
                blocked.append({**base, "reason": "工具已不在注册表中，无法确认可逆性。"})
                continue
            spec = self.compensation.spec_for(tool_name)
            if spec is None:
                if tool.metadata.risk_level is RiskLevel.GREEN:
                    # Read-only steps need no compensation.
                    continue
                blocked.append({**base, "reason": "工具未登记补偿规格，无法确认其可逆性。"})
            elif spec.irreversible:
                detail = spec.description or "该工具声明为不可逆操作。"
                blocked.append({**base, "reason": f"不可撤销：{detail}"})
            else:
                candidates.append(entry)
        return blocked, candidates

    @staticmethod
    def _annotate_plan(
        plan: dict[str, Any] | None,
        blocked_steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not plan:
            return {}
        if not blocked_steps:
            return plan
        payload = json.loads(json.dumps(plan, ensure_ascii=False))
        by_node = {str(step["node_id"]): step for step in blocked_steps}
        payload["irreversible"] = True
        payload["rollback_blocked"] = True
        payload["rollback_blocked_reason"] = (
            "计划包含不可撤销步骤，自动回滚已被阻止，需人工对账处理。"
        )
        for step in payload.get("steps", []):
            blocked = by_node.get(str(step.get("id")))
            if blocked:
                step["irreversible"] = True
                step["irreversible_reason"] = blocked.get("reason", "")
        return payload

    def _rollback_response(
        self,
        *,
        action_id: str,
        plan: dict[str, Any] | None,
        risk_level: str,
        results: list[dict[str, Any]],
        rollback: dict[str, Any],
        status: str,
        reason: str,
        risk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan_payload = self._annotate_plan(plan, rollback.get("irreversible_steps") or [])
        evidence = merge_evidence(
            evidence_payload(
                tool_result_evidence(
                    status == ExecutionStatus.ROLLED_BACK.value,
                    reason,
                ),
                policy_decision_evidence(True, "补偿工具执行前已通过统一权限网关与动态风险复检"),
            ),
            self._chain_evidence(),
        )
        response: dict[str, Any] = {
            "status": status,
            "run_id": action_id,
            "risk_level": risk_level,
            "reason": reason,
            "plan": plan_payload,
            "results": results,
            "rollback": rollback,
            "rolled_back": status == ExecutionStatus.ROLLED_BACK.value,
            "evidence": evidence,
            "evidence_list": evidence,
        }
        if risk is not None:
            response["risk"] = risk
        return response

    def _paused_response(
        self,
        *,
        action_id: str,
        user_id: str,
        instruction: str,
        plan: dict[str, Any] | None,
        risk_level: str,
        results: list[dict[str, Any]],
        pause: dict[str, Any],
        next_index: int,
        nodes: list[PlanNode],
        risk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pause_reason = pause.get("reason") or "用户请求暂停"
        remaining = [
            {"id": node.id, "tool_name": node.tool_name, "arguments": node.arguments}
            for node in nodes[next_index:]
        ]
        evidence = merge_evidence(
            evidence_payload(
                tool_result_evidence(True, f"已在第 {next_index} 个节点后暂停执行"),
                policy_decision_evidence(True, "暂停在步骤之间生效，剩余节点未执行"),
            ),
            self._chain_evidence(),
        )
        audit_entry = self.audit.record(
            event="action_paused",
            user_id=user_id,
            instruction=instruction,
            dag_path=self._dag_path(nodes),
            tool_name="action_pause",
            arguments={"action_id": action_id, "next_index": next_index},
            result={
                "reason": pause_reason,
                "remaining_steps": [node.id for node in nodes[next_index:]],
            },
            confirmation_state="paused",
            risk_level=risk_level,
            evidence=evidence,
        )
        response: dict[str, Any] = {
            "status": "paused",
            "run_id": action_id,
            "risk_level": risk_level,
            "reason": f"执行已暂停：{pause_reason}；剩余 {len(remaining)} 个步骤未执行。",
            "plan": plan or {},
            "results": results,
            "paused": pause,
            "resume": {
                "endpoint": f"/api/actions/{action_id}/resume",
                "method": "POST",
                "next_index": next_index,
                "executed_steps": next_index,
                "remaining_steps": remaining,
                "guidance": "确认暂停原因后调用恢复端点继续执行；已执行步骤不会重复执行。",
            },
            "audit_id": audit_entry["id"],
            "evidence": evidence,
            "evidence_list": evidence,
        }
        if risk is not None:
            response["risk"] = risk
        return response

    def _record_compensation_failure(
        self,
        *,
        action_id: str,
        user_id: str,
        instruction: str,
        entry: dict[str, Any],
        compensation_tool: str,
        error: str,
        risk_level: str,
        gateway_reason: str = "",
    ) -> None:
        node_id = str(entry["node_id"])
        tool_name = str(entry["tool_name"])
        self.journal.append_entry(
            action_id,
            node_id=node_id,
            tool_name=tool_name,
            phase="compensation_failed",
            status="failed",
            arguments=entry.get("arguments") or {},
            result={"error": error, "compensation_tool": compensation_tool},
            risk_level=risk_level,
        )
        self.audit.record(
            event="compensation_blocked" if gateway_reason else "compensation_failed",
            user_id=user_id,
            instruction=instruction,
            dag_path=f"compensate:{node_id}:{tool_name}",
            tool_name=compensation_tool or tool_name,
            arguments=entry.get("arguments") or {},
            result={
                "node_id": node_id,
                "compensated_tool": tool_name,
                "compensation_tool": compensation_tool,
                "error": error,
                "gateway_reason": gateway_reason,
            },
            confirmation_state="compensation_failed",
            risk_level=risk_level,
            evidence=evidence_payload(
                tool_result_evidence(False, f"补偿失败：{error}"),
                policy_decision_evidence(True, "补偿失败已记录，需人工对账处理"),
            ),
        )

    def _compensate(
        self,
        *,
        action_id: str,
        user_id: str,
        instruction: str,
        role: str,
    ) -> dict[str, Any]:
        compensated_ids = self.journal.compensated_node_ids(action_id)
        entries = [
            entry
            for entry in self.journal.executed_entries(action_id)
            if str(entry["node_id"]) not in compensated_ids
        ]
        if not entries:
            return {
                "status": "not_needed",
                "compensated": [],
                "failed": [],
                "irreversible_steps": [],
                "reason": "没有已执行且待补偿的步骤。",
            }
        blocked, candidates = self._blocked_compensation_steps(entries)
        if blocked:
            reason = "回滚被阻止：已执行步骤中存在不可撤销的操作，自动补偿未执行，需人工对账处理。"
            self.journal.update_status(action_id, "rollback_blocked", reason=reason)
            for step in blocked:
                self.journal.append_entry(
                    action_id,
                    node_id=str(step["node_id"]),
                    tool_name=str(step["tool_name"]),
                    phase="rollback_blocked",
                    status="blocked",
                    arguments={},
                    result={"reason": step["reason"]},
                    risk_level=str(step.get("risk_level") or "green"),
                )
            self.audit.record(
                event="compensation_blocked",
                user_id=user_id,
                instruction=instruction,
                dag_path="compensation",
                tool_name="compensation",
                arguments={"action_id": action_id},
                result={
                    "reason": reason,
                    "irreversible_steps": blocked,
                },
                confirmation_state="rollback_blocked",
                risk_level="yellow",
                evidence=evidence_payload(
                    tool_result_evidence(False, reason),
                    policy_decision_evidence(True, "不可撤销步骤阻止自动回滚"),
                ),
            )
            return {
                "status": "blocked",
                "compensated": [],
                "failed": [],
                "irreversible_steps": blocked,
                "reason": reason,
            }

        compensated: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for entry in reversed(candidates):
            tool_name = str(entry["tool_name"])
            node_id = str(entry["node_id"])
            spec = self.compensation.spec_for(tool_name)
            compensation_tool_name = spec.compensation_tool if spec is not None else ""
            base = {
                "node_id": node_id,
                "tool_name": tool_name,
                "compensation_tool": compensation_tool_name,
            }
            try:
                compensation_tool = self.registry.get(compensation_tool_name)
            except KeyError:
                error = f"补偿工具未注册：{compensation_tool_name or '<empty>'}"
                failed.append({**base, "error": error})
                self._record_compensation_failure(
                    action_id=action_id,
                    user_id=user_id,
                    instruction=instruction,
                    entry=entry,
                    compensation_tool=compensation_tool_name,
                    error=error,
                    risk_level=str(entry.get("risk_level") or "yellow"),
                )
                continue
            arguments = self._compensation_arguments(entry)
            if compensation_tool.arguments_model is not None:
                allowed = compensation_tool.arguments_model.model_fields
                arguments = {key: value for key, value in arguments.items() if key in allowed}
            context = ExecutionContext(
                user_id=user_id,
                instruction=instruction,
                run_id=action_id,
                dag_path=f"compensate:{node_id}:{tool_name}->{compensation_tool_name}",
                purpose="compensation",
            )
            assessment = self.risk_engine.assess(
                user_id=user_id,
                tool_name=compensation_tool.metadata.name,
                arguments=arguments,
                base_risk=compensation_tool.metadata.risk_level,
                instruction=instruction,
            )
            decision = self.gateway.evaluate(
                user_id=user_id,
                tool_name=compensation_tool.metadata.name,
                risk_level=assessment.level,
                permission=compensation_tool.metadata.permission,
                instruction=instruction,
                arguments=arguments,
                role=role,
                purpose="compensation",
            )
            if decision.denied or decision.requires_reauth:
                error = (
                    f"补偿被权限网关拒绝：{decision.reason}"
                    if decision.denied
                    else "补偿工具需要二次身份校验，自动补偿拒绝执行。"
                )
                failed.append(
                    {
                        **base,
                        "error": error,
                        "gateway": {
                            "outcome": decision.outcome,
                            "reason": decision.reason,
                        },
                    }
                )
                self._record_compensation_failure(
                    action_id=action_id,
                    user_id=user_id,
                    instruction=instruction,
                    entry=entry,
                    compensation_tool=compensation_tool_name,
                    error=error,
                    risk_level=assessment.level.value,
                    gateway_reason=decision.reason,
                )
                continue

            authorization_state = {"assessment": assessment, "decision": decision}

            def persist_compensation(
                result,
                node_id=node_id,
                tool_name=tool_name,
                arguments=arguments,
                compensation_tool=compensation_tool,
                authorization_state=authorization_state,
            ):
                assessment = authorization_state["assessment"]
                decision = authorization_state["decision"]
                self.journal.append_entry(
                    action_id,
                    node_id=node_id,
                    tool_name=tool_name,
                    phase="compensated",
                    status="succeeded",
                    arguments=arguments,
                    result=result,
                    risk_level=assessment.level.value,
                )
                self.audit.record(
                    event="compensation_executed",
                    step_id=node_id,
                    user_id=user_id,
                    instruction=instruction,
                    dag_path=f"compensate:{node_id}:{tool_name}",
                    tool_name=compensation_tool.metadata.name,
                    arguments=arguments,
                    result={
                        "node_id": node_id,
                        "compensated_tool": tool_name,
                        "compensation_tool": compensation_tool.metadata.name,
                        "gateway": {
                            "outcome": decision.outcome,
                            "reason": decision.reason,
                        },
                        "risk": assessment.as_dict(),
                        "result": result,
                    },
                    confirmation_state="compensated",
                    risk_level=assessment.level.value,
                    evidence=evidence_payload(
                        tool_result_evidence(
                            True,
                            f"{tool_name} 已由 {compensation_tool.metadata.name} 补偿",
                        ),
                        policy_decision_evidence(True, "补偿执行前经统一权限网关复检通过"),
                    ),
                )

            def authorize_compensation(
                compensation_tool=compensation_tool,
                arguments=arguments,
                authorization_state=authorization_state,
            ):
                assessment = self.risk_engine.assess(
                    user_id=user_id,
                    tool_name=compensation_tool.metadata.name,
                    arguments=arguments,
                    base_risk=compensation_tool.metadata.risk_level,
                    instruction=instruction,
                )
                decision = self.gateway.evaluate(
                    user_id=user_id,
                    tool_name=compensation_tool.metadata.name,
                    risk_level=assessment.level,
                    permission=compensation_tool.metadata.permission,
                    instruction=instruction,
                    arguments=arguments,
                    role=role,
                    purpose="compensation",
                )
                authorization_state.update(assessment=assessment, decision=decision)
                if decision.denied:
                    raise PermissionError(decision.reason)
                if decision.requires_reauth or assessment.requires_reauth:
                    raise PermissionError("补偿工具需要二次身份校验，自动补偿拒绝执行。")

            try:
                result = self.executor.execute(
                    compensation_tool,
                    arguments,
                    context,
                    on_success=persist_compensation,
                    authorize=authorize_compensation,
                )
            except Exception as exc:  # noqa: BLE001 - compensation failures are recorded
                error = f"{type(exc).__name__}: {exc}"
                failed.append({**base, "error": error})
                self._record_compensation_failure(
                    action_id=action_id,
                    user_id=user_id,
                    instruction=instruction,
                    entry=entry,
                    compensation_tool=compensation_tool_name,
                    error=error,
                    risk_level=authorization_state["assessment"].level.value,
                    gateway_reason=str(exc) if isinstance(exc, PermissionError) else "",
                )
                continue
            compensated.append(
                {
                    **base,
                    "gateway_outcome": authorization_state["decision"].outcome,
                    "risk_level": authorization_state["assessment"].level.value,
                    "result": result,
                }
            )
        if failed:
            status = "partial" if compensated else "failed"
            reason = (
                f"部分补偿失败：成功 {len(compensated)} 个、失败 {len(failed)} 个，需人工对账处理。"
                if compensated
                else "补偿全部失败，需人工对账处理。"
            )
            self.journal.update_status(action_id, "unknown", reason=reason)
        else:
            status = "completed"
            reason = f"已按相反顺序成功补偿 {len(compensated)} 个已执行步骤。"
            self.journal.update_status(action_id, "rolled_back", reason=reason)
        return {
            "status": status,
            "compensated": compensated,
            "failed": failed,
            "irreversible_steps": [],
            "reason": reason,
        }

    @staticmethod
    def _advance(
        machine: StateMachine | None,
        target: ActionState,
        reason: str,
    ) -> None:
        if machine is None:
            return
        try:
            machine.transition(target, reason=reason)
        except IllegalTransition:
            return

    @audit_scope
    def run_dag(
        self,
        *,
        user_id: str,
        instruction: str,
        nodes: list[PlanNode],
        role: str = "user",
        intent: str = "demo_dag",
        action_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute an extension-provided DAG through the shared gateway path.

        Used by the compensation demo: every node still goes through the
        permission gateway, the risk engine, the tool executor and the audit
        chain. Only nodes that are allowed immediately (green) are accepted.
        """
        if not nodes:
            raise IntentError("DAG 至少需要一个工具节点。")
        action_id = action_id or f"dag_{uuid4().hex}"
        audit_run_id.set(action_id)
        assessments = self._assess_nodes(nodes, user_id, instruction)
        risk_level = self._max_assessed_risk(assessments)
        plan_payload: dict[str, Any] = {
            "intent": intent,
            "planner": "extension",
            "confidence": 1.0,
            "assumptions": ["演示用可控失败 DAG：所有节点经统一网关、执行器与审计链。"],
            "plan_hash": "",
            "dag_path": self._dag_path(nodes),
            "steps": [node.as_dict() for node in nodes],
        }
        plan_payload = self._decorate_plan(plan_payload, assessments)
        for step, node in zip(plan_payload["steps"], nodes, strict=True):
            tool = self.registry.get(node.tool_name)
            step["title"] = tool.metadata.title
            step["permission"] = tool.metadata.permission
        plan_payload["plan_hash"] = hashlib.sha256(
            json.dumps(
                {"intent": intent, "steps": [node.as_dict() for node in nodes]},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        risk = {
            "level": risk_level.value,
            "reasons": [
                reason for assessment in assessments.values() for reason in assessment.reasons
            ],
            "requires_reauth": any(
                assessment.requires_reauth for assessment in assessments.values()
            ),
        }
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            decision = self.gateway.evaluate(
                user_id=user_id,
                tool_name=tool.metadata.name,
                risk_level=assessments[node.id].level,
                permission=tool.metadata.permission,
                instruction=instruction,
                arguments=node.arguments,
                role=role,
            )
            if decision.denied:
                audit_entry = self.audit.record(
                    event="gateway_blocked",
                    user_id=user_id,
                    instruction=instruction,
                    dag_path=self._dag_path(nodes),
                    tool_name=node.tool_name,
                    arguments=node.arguments,
                    result={
                        "reason": decision.reason,
                        "plan_hash": plan_payload["plan_hash"],
                    },
                    confirmation_state="blocked",
                    risk_level=assessments[node.id].level.value,
                    evidence=evidence_payload(policy_decision_evidence(True, decision.reason)),
                )
                return {
                    "status": ExecutionStatus.BLOCKED.value,
                    "run_id": action_id,
                    "risk_level": assessments[node.id].level.value,
                    "risk": risk,
                    "reason": decision.reason,
                    "plan": plan_payload,
                    "audit_id": audit_entry["id"],
                    "evidence": evidence_payload(policy_decision_evidence(True, decision.reason)),
                }
            if not decision.allowed_now:
                raise IntentError("演示 DAG 只允许包含无需人工确认的绿色节点。")
        try:
            results = self._execute_nodes(
                nodes=nodes,
                user_id=user_id,
                instruction=instruction,
                run_id=action_id,
                confirmation_state="demo",
                action_id=action_id,
                plan=plan_payload,
                risk_level=risk_level.value,
                role=role,
                # Controlled demo failures must not trip the shared breaker.
                count_failures=False,
            )
        except ExecutionPaused as paused:
            response = self._paused_response(
                action_id=action_id,
                user_id=user_id,
                instruction=instruction,
                plan=plan_payload,
                risk_level=risk_level.value,
                results=paused.results,
                pause=paused.pause,
                next_index=paused.next_index,
                nodes=paused.nodes,
                risk=risk,
            )
            self.journal.update_status(
                action_id,
                "paused",
                reason=paused.pause.get("reason") or "用户请求暂停",
                response=response,
            )
            return response
        except ExecutionOutcomeUnknown as exc:
            reason = f"执行结果不确定：{exc}；不得自动重复执行，需人工对账。"
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            response = {
                "status": ExecutionStatus.UNKNOWN.value,
                "run_id": action_id,
                "risk_level": risk_level.value,
                "risk": risk,
                "reason": reason,
                "plan": plan_payload,
                "results": self._executed_results(action_id),
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self.journal.update_status(action_id, "unknown", reason=reason, response=response)
            return response
        except Exception as exc:  # noqa: BLE001 - compensation handles partial execution
            rollback = self._compensate(
                action_id=action_id,
                user_id=user_id,
                instruction=instruction,
                role=role,
            )
            executed = self._executed_results(action_id)
            if rollback["status"] == "blocked":
                reason = f"执行失败：{exc}；回滚被阻止：存在不可撤销步骤，需人工对账。"
                response = self._rollback_response(
                    action_id=action_id,
                    plan=plan_payload,
                    risk_level=risk_level.value,
                    results=executed,
                    rollback=rollback,
                    status=ExecutionStatus.UNKNOWN.value,
                    reason=reason,
                    risk=risk,
                )
                self.journal.update_status(action_id, "unknown", reason=reason, response=response)
                return response
            if rollback["status"] in {"completed", "partial", "failed"}:
                rolled_back = rollback["status"] == "completed"
                status = (
                    ExecutionStatus.ROLLED_BACK.value
                    if rolled_back
                    else ExecutionStatus.UNKNOWN.value
                )
                reason = (
                    f"执行失败后已自动回滚：{rollback['reason']}"
                    if rolled_back
                    else f"执行失败后补偿未全部成功：{rollback['reason']}"
                )
                response = self._rollback_response(
                    action_id=action_id,
                    plan=plan_payload,
                    risk_level=risk_level.value,
                    results=executed,
                    rollback=rollback,
                    status=status,
                    reason=reason,
                    risk=risk,
                )
                self.journal.update_status(action_id, status, reason=reason, response=response)
                return response
            reason = f"工具执行失败：{exc}"
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            response = {
                "status": ExecutionStatus.FAILED.value,
                "run_id": action_id,
                "risk_level": risk_level.value,
                "risk": risk,
                "reason": reason,
                "plan": plan_payload,
                "results": executed,
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self.journal.update_status(action_id, "failed", reason=reason, response=response)
            return response
        evidence = merge_evidence(
            self._execution_evidence(confirmation_state="demo"),
            self._chain_evidence(),
        )
        response = {
            "status": ExecutionStatus.COMPLETED.value,
            "run_id": action_id,
            "risk_level": risk_level.value,
            "risk": risk,
            "reason": "演示 DAG 全部节点执行完成。",
            "plan": plan_payload,
            "results": results,
            "evidence": evidence,
            "evidence_list": evidence,
        }
        self.journal.update_status(
            action_id, "completed", reason="全部节点执行完成", response=response
        )
        return response

    def pause_action(
        self,
        *,
        action_id: str,
        reason: str = "用户请求暂停",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        record = self.journal.get(action_id)
        pending = self.db.get_pending(action_id)
        if record is None and pending is None:
            raise IntentError("确认请求不存在。")
        owner_record = record or pending
        if user_id is not None and owner_record["user_id"] != user_id:
            raise IntentError("执行日志不属于当前用户。")
        if record is not None and record["status"] not in {"executing", "paused", "running"}:
            raise IntentError("当前动作状态不允许暂停。")
        pause = self.pause.pause(action_id, reason=reason)
        owner = user_id or (str(record["user_id"]) if record is not None else "demo-user")
        instruction = str(record["instruction"]) if record is not None else "暂停指定动作"
        audit_entry = self.audit.record(
            event="action_paused",
            user_id=owner,
            instruction=instruction,
            dag_path="pause",
            tool_name="action_pause",
            arguments={"action_id": action_id, "reason": reason},
            result={"pause": pause},
            confirmation_state="paused",
            risk_level="green",
            evidence=evidence_payload(policy_decision_evidence(True, "用户在步骤之间请求暂停")),
        )
        response: dict[str, Any] = {
            "status": "paused",
            "action_id": action_id,
            "pause": pause,
            "audit_id": audit_entry["id"],
            "note": "暂停在下一个节点执行前生效；调用 resume 端点继续执行。",
        }
        if record is not None:
            response["journal"] = {
                "status": record["status"],
                "next_index": record["next_index"],
            }
        return response

    def _pending_journal_view(self, action_id: str, pending: dict[str, Any]) -> dict[str, Any]:
        nodes = json.loads(pending.get("dag_json") or "[]")
        plan = json.loads(pending.get("plan_json") or "{}")
        pause = self.pause.status(action_id)
        status = "paused" if pause["paused"] else str(pending["status"])
        response: dict[str, Any] = {
            "action_id": action_id,
            "user_id": pending["user_id"],
            "instruction": pending["instruction"],
            "role": "user",
            "status": status,
            "state": pending["state"],
            "pending_status": pending["status"],
            "risk_level": pending["risk_level"],
            "next_index": 0,
            "created_at": pending["created_at"],
            "updated_at": pending["created_at"],
            "reason": "动作尚未开始执行，执行日志为空。",
            "nodes": nodes,
            "results": [],
            "plan": plan,
            "pause": pause,
            "entries": [],
            "executed": [],
            "compensations": [],
            "not_started": True,
        }
        if pause["paused"]:
            response["resume"] = {
                "endpoint": f"/api/actions/{action_id}/resume",
                "method": "POST",
                "next_index": 0,
                "remaining_steps": [
                    {"id": node.get("id"), "tool_name": node.get("tool_name")} for node in nodes
                ],
                "guidance": "动作尚未执行；确认暂停原因后可恢复，或直接继续确认流程。",
            }
        return response

    def journal_view(self, action_id: str) -> dict[str, Any]:
        record = self.journal.get(action_id)
        if record is None:
            pending = self.db.get_pending(action_id)
            if pending is None:
                raise IntentError("执行日志不存在。")
            return self._pending_journal_view(action_id, pending)
        entries = self.journal.entries(action_id)
        pause = self.pause.status(action_id)
        nodes = record["nodes"]
        next_index = int(record["next_index"] or 0)
        response: dict[str, Any] = {
            "action_id": action_id,
            "user_id": record["user_id"],
            "instruction": record["instruction"],
            "role": record["role"],
            "status": record["status"],
            "state": None,
            "risk_level": record["risk_level"],
            "next_index": next_index,
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "reason": record["reason"],
            "nodes": nodes,
            "results": record["results"],
            "plan": record["plan"],
            "pause": pause,
            "entries": entries,
            "executed": [entry for entry in entries if entry["phase"] == "executed"],
            "compensations": [
                entry
                for entry in entries
                if entry["phase"] in {"compensated", "compensation_failed", "rollback_blocked"}
            ],
        }
        pending = self.db.get_pending(action_id)
        if pending is not None:
            response["state"] = pending["state"]
            response["pending_status"] = pending["status"]
        if pause["paused"]:
            remaining = nodes[next_index:]
            response["resume"] = {
                "endpoint": f"/api/actions/{action_id}/resume",
                "method": "POST",
                "next_index": next_index,
                "remaining_steps": [
                    {"id": node.get("id"), "tool_name": node.get("tool_name")} for node in remaining
                ],
                "guidance": "确认暂停原因后调用恢复端点；已执行步骤不会重复执行。",
            }
        return response

    @audit_scope
    @serialized_action
    def resume_action(
        self,
        *,
        action_id: str,
        user_id: str | None = None,
        role: str = "user",
    ) -> dict[str, Any]:
        record = self.journal.get(action_id)
        if record is None:
            pending = self.db.get_pending(action_id)
            if pending is None:
                raise IntentError("执行日志不存在，无法恢复暂停的动作。")
            if user_id is not None and pending["user_id"] != user_id:
                raise IntentError("确认请求不属于当前用户。")
            pause = self.pause.resume(action_id)
            return {
                "status": pending["status"],
                "action_id": action_id,
                "state": pending["state"],
                "pause": pause,
                "reason": "动作尚未开始执行，暂停标记已清除；请继续确认或重新发起。",
                "resumed": False,
                "not_started": True,
            }
        if user_id is not None and record["user_id"] != user_id:
            raise IntentError("执行日志不属于当前用户。")
        if record["status"] != "paused":
            stored = record.get("response")
            if isinstance(stored, dict):
                return stored
            raise IntentError(f"动作当前状态为 {record['status']}，不在暂停状态，无法恢复。")
        nodes = [PlanNode.from_dict(item) for item in record["nodes"]]
        if not nodes:
            raise IntentError("执行日志缺少节点定义，无法恢复。")
        self.pause.resume(action_id)
        start_index = int(record["next_index"] or 0)
        entries = self.journal.executed_entries(action_id)
        prior = [
            {"node_id": entry["node_id"], "result": result}
            for entry, result in zip(entries, record["results"], strict=False)
            if isinstance(result, dict)
        ]
        plan = record["plan"] if isinstance(record["plan"], dict) else {}
        risk_level = str(record["risk_level"] or "green")
        instruction = str(record["instruction"] or "")
        owner = str(record["user_id"])
        risk = {
            "level": risk_level,
            "reasons": ["恢复暂停的执行：仅执行剩余节点"],
            "requires_reauth": False,
        }
        pending = self.db.get_pending(action_id)
        machine: StateMachine | None = None
        if pending is not None:
            machine = self._load_machine(
                pending,
                dag_path=self._dag_path(nodes),
                tool_name=nodes[0].tool_name,
                arguments=nodes[0].arguments,
            )
            if machine.state is ActionState.PAUSED:
                machine.transition(ActionState.EXECUTING, reason="恢复暂停的执行")
        self.journal.mark_running(action_id)
        try:
            results = self._execute_nodes(
                nodes=nodes,
                user_id=owner,
                instruction=instruction,
                run_id=action_id,
                confirmation_state="resumed",
                action_id=action_id,
                plan=plan,
                risk_level=risk_level,
                role=role,
                start_index=start_index,
                prior_results=prior,
            )
        except ExecutionPaused as paused:
            self._advance(machine, ActionState.PAUSED, "恢复后再次暂停")
            response = self._paused_response(
                action_id=action_id,
                user_id=owner,
                instruction=instruction,
                plan=plan,
                risk_level=risk_level,
                results=paused.results,
                pause=paused.pause,
                next_index=paused.next_index,
                nodes=paused.nodes,
                risk=risk,
            )
            self.journal.update_status(
                action_id,
                "paused",
                reason=paused.pause.get("reason") or "用户请求暂停",
                response=response,
            )
            if pending is not None:
                self._finish(action_id, "paused", response)
            return response
        except ExecutionOutcomeUnknown as exc:
            self._advance(machine, ActionState.UNKNOWN, f"执行结果不确定：{exc}")
            reason = f"执行结果不确定：{exc}；不得自动重复执行，需人工对账。"
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            response = {
                "status": ExecutionStatus.UNKNOWN.value,
                "run_id": action_id,
                "risk_level": risk_level,
                "risk": risk,
                "reason": reason,
                "plan": plan,
                "results": self._executed_results(action_id),
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self.journal.update_status(action_id, "unknown", reason=reason, response=response)
            if pending is not None:
                self._finish(action_id, "unknown", response)
            return response
        except Exception as exc:  # noqa: BLE001 - compensation path
            rollback = self._compensate(
                action_id=action_id,
                user_id=owner,
                instruction=instruction,
                role=str(record["role"] or role),
            )
            executed = self._executed_results(action_id)
            if rollback["status"] == "blocked":
                self._advance(machine, ActionState.UNKNOWN, "回滚被阻止：存在不可撤销步骤")
                reason = f"执行失败：{exc}；回滚被阻止：存在不可撤销步骤，需人工对账。"
                response = self._rollback_response(
                    action_id=action_id,
                    plan=plan,
                    risk_level=risk_level,
                    results=executed,
                    rollback=rollback,
                    status=ExecutionStatus.UNKNOWN.value,
                    reason=reason,
                    risk=risk,
                )
                self.journal.update_status(action_id, "unknown", reason=reason, response=response)
                if pending is not None:
                    self._finish(action_id, "unknown", response)
                return response
            if rollback["status"] in {"completed", "partial", "failed"}:
                rolled_back = rollback["status"] == "completed"
                status = (
                    ExecutionStatus.ROLLED_BACK.value
                    if rolled_back
                    else ExecutionStatus.UNKNOWN.value
                )
                self._advance(
                    machine,
                    ActionState.ROLLED_BACK if rolled_back else ActionState.UNKNOWN,
                    rollback["reason"],
                )
                reason = (
                    f"执行失败后已自动回滚：{rollback['reason']}"
                    if rolled_back
                    else f"执行失败后补偿未全部成功：{rollback['reason']}"
                )
                response = self._rollback_response(
                    action_id=action_id,
                    plan=plan,
                    risk_level=risk_level,
                    results=executed,
                    rollback=rollback,
                    status=status,
                    reason=reason,
                    risk=risk,
                )
                self.journal.update_status(action_id, status, reason=reason, response=response)
                if pending is not None:
                    self._finish(action_id, status, response)
                return response
            self._advance(machine, ActionState.FAILED, f"执行失败：{exc}")
            reason = f"工具执行失败：{exc}"
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            response = {
                "status": ExecutionStatus.FAILED.value,
                "run_id": action_id,
                "risk_level": risk_level,
                "risk": risk,
                "reason": reason,
                "plan": plan,
                "results": executed,
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self.journal.update_status(action_id, "failed", reason=reason, response=response)
            if pending is not None:
                self._finish(action_id, "failed", response)
            return response
        self._advance(machine, ActionState.COMPLETED, "恢复后全部节点执行完成")
        evidence = merge_evidence(
            self._execution_evidence(confirmation_state="resumed"),
            self._chain_evidence(),
        )
        response = {
            "status": ExecutionStatus.COMPLETED.value,
            "run_id": action_id,
            "risk_level": risk_level,
            "risk": risk,
            "reason": "恢复后剩余节点已执行完成。",
            "plan": plan,
            "results": results,
            "resumed_from_index": start_index,
            "evidence": evidence,
            "evidence_list": evidence,
        }
        self.journal.update_status(
            action_id, "completed", reason="恢复后执行完成", response=response
        )
        if pending is not None:
            self._finish(action_id, "completed", response)
        return response

    @audit_scope
    @serialized_action
    def rollback_action(
        self,
        *,
        action_id: str,
        user_id: str | None = None,
        role: str = "user",
        reason: str = "",
    ) -> dict[str, Any]:
        record = self.journal.get(action_id)
        if record is None:
            raise IntentError("执行日志不存在，无法回退。")
        if user_id is not None and record["user_id"] != user_id:
            raise IntentError("执行日志不属于当前用户。")
        stored = record.get("response")
        if record["status"] in {"rolled_back", "rollback_blocked"} and isinstance(stored, dict):
            return stored
        owner = str(record["user_id"])
        instruction = str(record["instruction"] or "")
        plan = record["plan"] if isinstance(record["plan"], dict) else {}
        risk_level = str(record["risk_level"] or "green")
        nodes = [PlanNode.from_dict(item) for item in record["nodes"]]
        if self.pause.is_paused(action_id):
            self.pause.resume(action_id)
        pending = self.db.get_pending(action_id)
        machine: StateMachine | None = None
        if pending is not None and nodes:
            machine = self._load_machine(
                pending,
                dag_path=self._dag_path(nodes),
                tool_name=nodes[0].tool_name,
                arguments=nodes[0].arguments,
            )
        rollback = self._compensate(
            action_id=action_id,
            user_id=owner,
            instruction=instruction or reason or "人工回退",
            role=role,
        )
        executed = self._executed_results(action_id)
        risk = {
            "level": risk_level,
            "reasons": ["人工回退：按相反顺序补偿已执行步骤"],
            "requires_reauth": False,
        }
        if rollback["status"] == "blocked":
            detail = reason or rollback["reason"]
            response = self._rollback_response(
                action_id=action_id,
                plan=plan,
                risk_level=risk_level,
                results=executed,
                rollback=rollback,
                status=ExecutionStatus.BLOCKED.value,
                reason=f"回滚被阻止：存在不可撤销步骤（{detail}）。",
                risk=risk,
            )
            self.journal.update_status(
                action_id,
                "rollback_blocked",
                reason=rollback["reason"],
                response=response,
            )
            self.audit.record(
                event="rollback_blocked",
                user_id=owner,
                instruction=instruction or "人工回退",
                dag_path="compensation",
                tool_name="rollback",
                arguments={"action_id": action_id},
                result={
                    "reason": rollback["reason"],
                    "irreversible_steps": rollback["irreversible_steps"],
                },
                confirmation_state="rollback_blocked",
                risk_level=risk_level,
                evidence=evidence_payload(
                    tool_result_evidence(False, rollback["reason"]),
                    policy_decision_evidence(True, "不可撤销步骤阻止人工回滚"),
                ),
            )
            return response
        if rollback["status"] in {"completed", "partial", "failed"}:
            rolled_back = rollback["status"] == "completed"
            status = (
                ExecutionStatus.ROLLED_BACK.value if rolled_back else ExecutionStatus.UNKNOWN.value
            )
            if machine is not None:
                self._advance(
                    machine,
                    ActionState.ROLLED_BACK if rolled_back else ActionState.UNKNOWN,
                    rollback["reason"],
                )
            detail = reason or rollback["reason"]
            response = self._rollback_response(
                action_id=action_id,
                plan=plan,
                risk_level=risk_level,
                results=executed,
                rollback=rollback,
                status=status,
                reason=(
                    f"人工回退完成：{detail}" if rolled_back else f"人工回退未全部成功：{detail}"
                ),
                risk=risk,
            )
            self.journal.update_status(
                action_id, status, reason=rollback["reason"], response=response
            )
            if pending is not None:
                self._finish(action_id, status, response)
            return response
        response = self._rollback_response(
            action_id=action_id,
            plan=plan,
            risk_level=risk_level,
            results=executed,
            rollback=rollback,
            status=ExecutionStatus.BLOCKED.value,
            reason="没有已执行且可补偿的步骤，无需回退。",
            risk=risk,
        )
        return response

    # ---------- trust inspection and recovery ----------
    def action_view(self, action_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        pending = self.db.get_pending(action_id)
        if pending is None:
            raise IntentError("确认请求不存在。")
        if user_id is not None and pending["user_id"] != user_id:
            raise IntentError("确认请求不属于当前用户。")
        try:
            history = json.loads(pending.get("state_history_json") or "[]")
        except ValueError:
            history = []
        envelopes = [
            ActionEnvelope.from_dict(item).masked()
            for item in json.loads(pending.get("envelopes_json") or "[]")
        ]
        evidence = evidence_payload(hash_chain_evidence(True, "任务状态已写入审计链"))
        return {
            "action_id": action_id,
            "user_id": pending["user_id"],
            "status": pending["status"],
            "state": pending["state"],
            "risk_level": pending["risk_level"],
            "requires_reauth": bool(pending["requires_reauth"]),
            "created_at": pending["created_at"],
            "expires_at": pending["expires_at"],
            "resolved_at": pending.get("resolved_at"),
            "history": history,
            "envelopes": envelopes,
            "evidence": evidence,
            "evidence_list": evidence,
            "instruction": pending["instruction"],
            "plan": json.loads(pending.get("plan_json") or "{}"),
            "result": self._stored_result(pending),
        }

    @audit_scope
    @serialized_action
    def reconcile(
        self,
        *,
        action_id: str,
        outcome: str,
        user_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if outcome != "reconciled":
            raise IntentError("对账接口不能代替实际资金补偿，请使用动作回滚接口。")
        if not reason.strip():
            raise IntentError("人工对账必须填写核查依据。")
        pending = self.db.get_pending(action_id)
        if pending is None:
            raise IntentError("确认请求不存在。")
        if pending["user_id"] != user_id:
            raise IntentError("确认请求不属于当前用户。")
        nodes = [PlanNode.from_dict(item) for item in json.loads(pending["dag_json"])]
        machine = self._load_machine(
            pending,
            dag_path=self._dag_path(nodes),
            tool_name=nodes[0].tool_name,
            arguments=nodes[0].arguments,
        )
        target = ActionState.RECONCILED if outcome == "reconciled" else ActionState.ROLLED_BACK
        try:
            machine.transition(target, reason=reason or "人工对账处理")
        except IllegalTransition as exc:
            raise IntentError(str(exc)) from exc
        self.db.resolve_pending(action_id, target.value.lower())
        result = self._stored_result(pending) or {"run_id": action_id}
        result.update(status="reconciled", reason="已记录人工对账结论；此操作不代表资金已冲正。")
        result["reconciliation"] = {"reason": reason, "funds_reversed": False}
        self._finish(action_id, "reconciled", result)
        self.audit.record(
            event=(
                "action_reconciled" if target is ActionState.RECONCILED else "action_rolled_back"
            ),
            user_id=user_id,
            instruction=pending["instruction"],
            dag_path=self._dag_path(nodes),
            tool_name=nodes[0].tool_name,
            arguments=nodes[0].arguments,
            result={"reason": reason or "人工对账处理", "outcome": target.value},
            confirmation_state=target.value,
            risk_level=pending["risk_level"],
            evidence=evidence_payload(
                approval_evidence(True, "人工对账结论"),
                policy_decision_evidence(True, f"UNKNOWN 已处理为 {target.value}"),
            ),
        )
        return self.action_view(action_id)

    def circuit_breaker_status(self, user_id: str = "demo-user") -> dict[str, Any]:
        return self.breaker.status(user_id=user_id)

    def reset_circuit_breaker(self, user_id: str = "demo-user") -> dict[str, Any]:
        self.breaker.reset(user_id=user_id)
        return self.breaker.status(user_id=user_id)
