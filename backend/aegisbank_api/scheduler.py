"""Structured planning and a confirmation-aware DAG scheduler."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .audit import AuditService
from .db import Database
from .domain import ExecutionContext, ExecutionStatus, PlanNode, RiskLevel
from .gateway import PermissionGateway
from .planning.compiler import CompiledPlan, PlanCompilationError, PlanCompiler
from .planning.contracts import ExecutionPlan, Planner, PlanningRequest, PlanStep
from .registry import ToolRegistry


class IntentError(ValueError):
    pass


class ReauthError(ValueError):
    pass


class DagScheduler:
    def __init__(
        self,
        *,
        planner: Planner,
        registry: ToolRegistry,
        gateway: PermissionGateway,
        db: Database,
        audit: AuditService,
        confirmation_ttl_seconds: int,
        demo_otp: str,
    ) -> None:
        self.planner = planner
        self.registry = registry
        self.gateway = gateway
        self.db = db
        self.audit = audit
        self.compiler = PlanCompiler(registry)
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.demo_otp = demo_otp

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

    def preview(
        self,
        *,
        user_id: str,
        instruction: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = PlanningRequest(
            user_id=user_id,
            instruction=instruction,
            tool_name=tool_name,
            arguments=arguments or {},
        )
        plan = self._propose(request)
        if plan.needs_clarification:
            return {
                "status": ExecutionStatus.NEEDS_CLARIFICATION.value,
                "plan": plan.model_dump(),
                "reason": plan.clarification,
            }
        compiled = self._compile(plan)
        return {
            "status": "planned",
            "plan": compiled.as_dict(),
            "reason": "计划已通过 Schema、工具注册和 DAG 依赖校验。",
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

    def run(
        self,
        *,
        user_id: str,
        instruction: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = uuid4().hex
        request = PlanningRequest(
            user_id=user_id,
            instruction=instruction,
            tool_name=tool_name,
            arguments=arguments or {},
        )
        plan = self._propose(request)
        if plan.needs_clarification:
            audit_entry = self.audit.record(
                event="planning_clarification",
                user_id=user_id,
                instruction=instruction,
                dag_path="planner",
                tool_name="planner",
                arguments={"tool_name": tool_name, "arguments": arguments or {}},
                result={"clarification": plan.clarification},
                confirmation_state="clarification",
                risk_level=RiskLevel.GREEN.value,
            )
            return {
                "status": ExecutionStatus.NEEDS_CLARIFICATION.value,
                "run_id": run_id,
                "risk_level": RiskLevel.GREEN.value,
                "reason": plan.clarification,
                "plan": plan.model_dump(),
                "audit_id": audit_entry["id"],
            }

        compiled = self._compile(plan)
        nodes = compiled.nodes
        plan_payload = compiled.as_dict()
        dag_path = compiled.dag_path
        decisions: list[tuple[PlanNode, Any]] = []
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            decision = self.gateway.evaluate(
                user_id=user_id,
                tool_name=tool.metadata.name,
                risk_level=tool.metadata.risk_level,
                permission=tool.metadata.permission,
                instruction=instruction,
                arguments=node.arguments,
            )
            decisions.append((node, decision))

        blocked = next(((node, dec) for node, dec in decisions if dec.denied), None)
        if blocked:
            node, decision = blocked
            metadata = self.registry.get(node.tool_name).metadata
            audit_entry = self.audit.record(
                event="gateway_blocked",
                user_id=user_id,
                instruction=instruction,
                dag_path=dag_path,
                tool_name=node.tool_name,
                arguments=node.arguments,
                result={"reason": decision.reason, "plan_hash": compiled.plan_hash},
                confirmation_state="blocked",
                risk_level=metadata.risk_level.value,
            )
            return {
                "status": ExecutionStatus.BLOCKED.value,
                "run_id": run_id,
                "risk_level": metadata.risk_level.value,
                "reason": decision.reason,
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
            }

        pending = next(((node, dec) for node, dec in decisions if not dec.allowed_now), None)
        risk_level = self._max_risk(nodes, self.registry)
        if pending:
            _, decision = pending
            action_id = f"cfm_{uuid4().hex}"
            created = datetime.now(UTC)
            expires = created + timedelta(seconds=self.confirmation_ttl_seconds)
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
                    "requires_reauth": int(decision.requires_reauth),
                    "status": "pending",
                    "created_at": created.isoformat(timespec="seconds"),
                    "expires_at": expires.isoformat(timespec="seconds"),
                }
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
                },
                confirmation_state="pending",
                risk_level=risk_level.value,
            )
            return {
                "status": ExecutionStatus.AWAITING_CONFIRMATION.value,
                "run_id": run_id,
                "risk_level": risk_level.value,
                "reason": decision.reason,
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
                "confirmation": {
                    "id": action_id,
                    "requires_reauth": decision.requires_reauth,
                    "expires_at": expires.isoformat(timespec="seconds"),
                },
            }

        results = self._execute_nodes(
            nodes=nodes,
            user_id=user_id,
            instruction=instruction,
            run_id=run_id,
            confirmation_state="not_required",
        )
        return {
            "status": ExecutionStatus.COMPLETED.value,
            "run_id": run_id,
            "risk_level": risk_level.value,
            "reason": "全部节点通过权限网关。",
            "plan": plan_payload,
            "results": results,
        }

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
        if pending["user_id"] != user_id:
            raise IntentError("确认请求不属于当前用户。")
        if pending["status"] != "pending":
            raise IntentError(f"确认请求已处理：{pending['status']}。")
        expires_at = datetime.fromisoformat(pending["expires_at"])
        if datetime.now(UTC) > expires_at:
            self.db.resolve_pending(action_id, "expired")
            raise IntentError("确认请求已过期，请重新发起操作。")

        nodes = [PlanNode.from_dict(item) for item in json.loads(pending["dag_json"])]
        plan_payload = self._restore_plan(nodes, pending)
        dag_path = self._dag_path(nodes)

        if not approved:
            self.db.resolve_pending(action_id, "rejected")
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
            )
            return {
                "status": ExecutionStatus.REJECTED.value,
                "run_id": action_id,
                "risk_level": pending["risk_level"],
                "reason": "用户已拒绝该操作。",
                "plan": plan_payload,
                "audit_id": audit_entry["id"],
            }

        if pending["requires_reauth"] and reauth_token != self.demo_otp:
            raise ReauthError("二次身份校验失败，请检查演示验证码。")

        # Re-check permissions immediately before execution. A grant may have been
        # revoked while the confirmation request was waiting for the user.
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            decision = self.gateway.evaluate(
                user_id=user_id,
                tool_name=tool.metadata.name,
                risk_level=tool.metadata.risk_level,
                permission=tool.metadata.permission,
                instruction=pending["instruction"],
                arguments=node.arguments,
            )
            if decision.denied:
                self.db.resolve_pending(action_id, "blocked")
                audit_entry = self.audit.record(
                    event="gateway_blocked",
                    user_id=user_id,
                    instruction=pending["instruction"],
                    dag_path=dag_path,
                    tool_name=node.tool_name,
                    arguments=node.arguments,
                    result={"reason": decision.reason},
                    confirmation_state="blocked",
                    risk_level=tool.metadata.risk_level.value,
                )
                return {
                    "status": ExecutionStatus.BLOCKED.value,
                    "run_id": action_id,
                    "risk_level": tool.metadata.risk_level.value,
                    "reason": f"确认后复检未通过：{decision.reason}",
                    "plan": plan_payload,
                    "audit_id": audit_entry["id"],
                }

        self.db.resolve_pending(action_id, "approved")
        self.audit.record(
            event="confirmation_approved",
            user_id=user_id,
            instruction=pending["instruction"],
            dag_path=dag_path,
            tool_name=nodes[0].tool_name,
            arguments=nodes[0].arguments,
            result={"reason": "用户明确批准执行"},
            confirmation_state="approved",
            risk_level=pending["risk_level"],
        )
        results = self._execute_nodes(
            nodes=nodes,
            user_id=user_id,
            instruction=pending["instruction"],
            run_id=action_id,
            confirmation_state="approved",
        )
        self.db.resolve_pending(action_id, "completed")
        return {
            "status": ExecutionStatus.COMPLETED.value,
            "run_id": action_id,
            "risk_level": pending["risk_level"],
            "reason": "确认通过，任务已执行。",
            "plan": plan_payload,
            "results": results,
        }

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
        for node in nodes:
            tool = self.registry.get(node.tool_name)
            context = ExecutionContext(
                user_id=user_id,
                instruction=instruction,
                run_id=run_id,
                dag_path=dag_path,
            )
            try:
                result = tool.execute(node.arguments, context).as_dict()
            except Exception as exc:  # noqa: BLE001 - tool errors become audited failures
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
                )
                raise
            self.audit.record(
                event="tool_executed",
                user_id=user_id,
                instruction=instruction,
                dag_path=dag_path,
                tool_name=node.tool_name,
                arguments=node.arguments,
                result=result,
                confirmation_state=confirmation_state,
                risk_level=tool.metadata.risk_level.value,
            )
            results.append(result)
        return results
