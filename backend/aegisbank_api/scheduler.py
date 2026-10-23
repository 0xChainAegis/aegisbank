"""Structured planning and a confirmation-aware DAG scheduler.

Phase 1 adds the trust layer: pre-planner injection rejection, ActionEnvelope
binding, idempotent confirmations, audited state transitions, layered evidence,
readiness fail-closed gating, and a persisted circuit breaker.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .audit import AuditService
from .db import Database
from .domain import ExecutionContext, ExecutionStatus, PlanNode, RiskLevel
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
        self.envelopes = EnvelopeService(db)
        self.breaker = CircuitBreaker(
            db,
            threshold=circuit_breaker_threshold,
            window_seconds=circuit_breaker_window_seconds,
            lock_seconds=circuit_breaker_lock_seconds,
        )

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
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            assessments[node.id] = self.risk_engine.assess(
                user_id=user_id,
                tool_name=tool.metadata.name,
                arguments=node.arguments,
                base_risk=tool.metadata.risk_level,
                instruction=instruction,
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
            items = evidence_payload(
                approval_evidence(True, "用户明确批准并完成确认复检")
            ) + items
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
            evidence = evidence_payload(
                policy_decision_evidence(True, "Planner 请求澄清")
            )
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
                    reason
                    for assessment in assessments.values()
                    for reason in assessment.reasons
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
    def run(
        self,
        *,
        user_id: str,
        instruction: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        arguments = arguments or {}
        run_id = uuid4().hex

        breaker = self.breaker.status()
        if breaker["open"]:
            reason = CircuitBreaker.reason(breaker)
            audit_entry = self.audit.record(
                event="circuit_breaker_open",
                user_id=user_id,
                instruction=instruction,
                dag_path="circuit-breaker",
                tool_name=tool_name or "planner",
                arguments=arguments,
                result={"reason": reason, "breaker": breaker},
                confirmation_state="blocked",
                risk_level=RiskLevel.RED.value,
                evidence=evidence_payload(
                    policy_decision_evidence(True, "熔断器打开，写操作统一拒绝")
                ),
            )
            return self._blocked_response(
                run_id=run_id,
                reason=reason,
                audit_entry=audit_entry,
                chain_evidence=self._chain_evidence(),
                extra={"breaker": breaker},
            )

        matched = scan_injection(instruction, arguments)
        if matched:
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
                arguments={"tool_name": tool_name, "arguments": arguments},
                result={"clarification": plan.clarification},
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
            evidence = evidence_payload(
                policy_decision_evidence(True, decision.reason)
            )
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
            created = datetime.now(UTC)
            expires = created + timedelta(seconds=self.confirmation_ttl_seconds)
            permissions = {
                node.id: self.registry.get(node.tool_name).metadata.permission
                for node in nodes
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
                    "dag_json": json.dumps(
                        [node.as_dict() for node in nodes], ensure_ascii=False
                    ),
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
            )
        except ExecutionOutcomeUnknown as exc:
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            return {
                "status": ExecutionStatus.UNKNOWN.value,
                "run_id": run_id,
                "risk_level": risk_level.value,
                "risk": risk,
                "reason": f"执行结果不确定：{exc}；不得自动重复执行，需人工对账。",
                "plan": plan_payload,
                "evidence": evidence,
                "evidence_list": evidence,
            }
        except Exception as exc:  # noqa: BLE001 - tool errors become a failed response
            evidence = merge_evidence(self._failure_evidence(exc), self._chain_evidence())
            return {
                "status": ExecutionStatus.FAILED.value,
                "run_id": run_id,
                "risk_level": risk_level.value,
                "risk": risk,
                "reason": f"工具执行失败：{exc}",
                "plan": plan_payload,
                "evidence": evidence,
                "evidence_list": evidence,
            }
        evidence = merge_evidence(
            self._execution_evidence(confirmation_state="not_required"),
            self._chain_evidence(),
        )
        return {
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

    # ---------- confirmation ----------
    def _recompute_plan(
        self, pending: dict[str, Any], nodes: list[PlanNode]
    ) -> CompiledPlan:
        stored = json.loads(pending.get("plan_json") or "{}")
        if stored.get("steps"):
            plan = ExecutionPlan(
                intent=str(stored.get("intent") or "confirmed_action"),
                planner=str(stored.get("planner") or "stored"),
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
        if not envelopes:
            return []
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

    def _claim_envelopes(
        self, envelopes: list[ActionEnvelope], *, action_id: str
    ) -> None:
        if envelopes:
            self.envelopes.claim_nonces(envelopes, action_id=action_id)

    def confirm(
        self,
        *,
        user_id: str,
        action_id: str,
        approved: bool,
        reauth_token: str | None,
    ) -> dict[str, Any]:
        pending = self.db.get_pending(action_id)
        if pending is None:
            raise IntentError("确认请求不存在。")
        replay = self._stored_result(pending)
        if replay is not None:
            return replay
        if pending["user_id"] != user_id:
            raise IntentError("确认请求不属于当前用户。")
        if pending["status"] != "pending":
            raise IntentError(f"确认请求已处理：{pending['status']}。")

        breaker = self.breaker.status()
        if breaker["open"]:
            reason = CircuitBreaker.reason(breaker)
            audit_entry = self.audit.record(
                event="circuit_breaker_open",
                user_id=user_id,
                instruction=pending["instruction"],
                dag_path="circuit-breaker",
                tool_name="confirmation",
                arguments={},
                result={"reason": reason, "breaker": breaker},
                confirmation_state="blocked",
                risk_level=RiskLevel.RED.value,
                evidence=evidence_payload(
                    policy_decision_evidence(True, "熔断器打开，确认操作统一拒绝")
                ),
            )
            response = self._blocked_response(
                run_id=action_id,
                reason=reason,
                audit_entry=audit_entry,
                chain_evidence=self._chain_evidence(),
                extra={"breaker": breaker},
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
            compiled = self._recompute_plan(pending, nodes)
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
            machine.transition(
                ActionState.AWAITING_REAUTH, reason="红色操作需要二次身份校验"
            )
        if requires_reauth and reauth_token != self.demo_otp:
            raise ReauthError("二次身份校验失败，请检查演示验证码。")

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
            },
            confirmation_state="approved",
            risk_level=pending["risk_level"],
            evidence=merge_evidence(approval_items, self._chain_evidence()),
        )
        machine.transition(ActionState.EXECUTING, reason="开始执行已确认动作")
        results: list[dict[str, Any]] = []
        try:
            results = self._execute_nodes(
                nodes=nodes,
                user_id=user_id,
                instruction=pending["instruction"],
                run_id=action_id,
                confirmation_state="approved",
            )
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
                "risk": {
                    "level": current_risk.value,
                    "reasons": [
                        reason
                        for assessment in assessments.values()
                        for reason in assessment.reasons
                    ],
                    "requires_reauth": requires_reauth,
                },
                "reason": f"执行结果不确定：{exc}；不得自动重复下单，请先对账。",
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
                "evidence": evidence,
                "evidence_list": evidence,
            }
            self._finish(action_id, ExecutionStatus.UNKNOWN.value, response)
            return response
        except Exception as exc:  # noqa: BLE001 - predictable tool failure -> 422
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
                    reason
                    for assessment in assessments.values()
                    for reason in assessment.reasons
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
    ) -> list[dict[str, Any]]:
        dag_path = self._dag_path(nodes)
        results: list[dict[str, Any]] = []
        results_by_id: dict[str, dict[str, Any]] = {}
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            context = ExecutionContext(
                user_id=user_id,
                instruction=instruction,
                run_id=run_id,
                dag_path=dag_path,
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
            try:
                result = tool.execute(resolved_args, context).as_dict()
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
                self.breaker.record_failure()
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
            self.breaker.record_success()
            result["risk"] = assessment.as_dict()
            self.audit.record(
                event="tool_executed",
                user_id=user_id,
                instruction=instruction,
                dag_path=dag_path,
                tool_name=node.tool_name,
                arguments=resolved_args,
                result=result,
                confirmation_state=confirmation_state,
                risk_level=assessment.level.value,
                evidence=self._execution_evidence(confirmation_state=confirmation_state),
            )
            results_by_id[node.id] = result
            results.append(result)
        return results

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
        evidence = evidence_payload(
            hash_chain_evidence(True, "任务状态已写入审计链")
        )
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
        }

    def reconcile(
        self,
        *,
        action_id: str,
        outcome: str,
        user_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
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
        target = (
            ActionState.RECONCILED
            if outcome == "reconciled"
            else ActionState.ROLLED_BACK
        )
        try:
            machine.transition(target, reason=reason or "人工对账处理")
        except IllegalTransition as exc:
            raise IntentError(str(exc)) from exc
        self.db.resolve_pending(action_id, target.value.lower())
        self.audit.record(
            event=(
                "action_reconciled"
                if target is ActionState.RECONCILED
                else "action_rolled_back"
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

    def circuit_breaker_status(self) -> dict[str, Any]:
        return self.breaker.status()

    def reset_circuit_breaker(self) -> dict[str, Any]:
        self.breaker.reset()
        return self.breaker.status()
