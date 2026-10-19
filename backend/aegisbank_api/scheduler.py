"""Rule-based intent planning and a confirmation-aware DAG scheduler."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .audit import AuditService
from .db import Database
from .domain import ExecutionContext, ExecutionStatus, PlanNode, RiskLevel
from .gateway import PermissionGateway
from .registry import ToolRegistry


class IntentError(ValueError):
    pass


class ReauthError(ValueError):
    pass


def infer_tool(instruction: str) -> str:
    text = instruction.lower()
    if any(word in text for word in ("转账", "汇款", "transfer")):
        return "transfer"
    if any(word in text for word in ("还款日", "repayment")):
        return "adjust_repayment_date"
    if any(word in text for word in ("账单", "余额", "bill", "statement")):
        return "query_bill"
    raise IntentError("暂时无法识别该指令。可尝试查询账单、调整还款日或小额转账。")


def infer_arguments(instruction: str, tool_name: str) -> dict[str, Any]:
    amounts = re.findall(r"(\d+(?:\.\d+)?)\s*(?:元|rmb|cny)", instruction, re.IGNORECASE)
    accounts = re.findall(r"ACC-\d+", instruction, re.IGNORECASE)
    if tool_name == "transfer":
        return {
            "from_account": accounts[0] if accounts else "ACC-1001",
            "to_account": accounts[1] if len(accounts) > 1 else "ACC-2002",
            "amount_cny": float(amounts[0]) if amounts else 880.0,
            "note": instruction[:120],
        }
    if tool_name == "adjust_repayment_date":
        day_match = re.search(r"(\d{1,2})\s*日", instruction)
        return {
            "card_id": "CARD-8821",
            "new_day": int(day_match.group(1)) if day_match else 18,
        }
    return {
        "account_id": accounts[0] if accounts else "ACC-1001",
        "period": "current_month",
    }


class DagScheduler:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        gateway: PermissionGateway,
        db: Database,
        audit: AuditService,
        confirmation_ttl_seconds: int,
        demo_otp: str,
    ) -> None:
        self.registry = registry
        self.gateway = gateway
        self.db = db
        self.audit = audit
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.demo_otp = demo_otp

    def _plan(
        self, instruction: str, tool_name: str | None, arguments: dict[str, Any]
    ) -> list[PlanNode]:
        resolved_name = tool_name or infer_tool(instruction)
        try:
            tool = self.registry.get(resolved_name)
        except KeyError as exc:
            raise IntentError(str(exc)) from exc
        resolved_args = arguments or infer_arguments(instruction, resolved_name)
        return [
            PlanNode(
                id="node-1",
                tool_name=tool.metadata.name,
                arguments=resolved_args,
            )
        ]

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

    def run(
        self,
        *,
        user_id: str,
        instruction: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nodes = self._plan(instruction, tool_name, arguments or {})
        dag_path = self._dag_path(nodes)
        run_id = uuid4().hex
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
                result={"reason": decision.reason},
                confirmation_state="blocked",
                risk_level=metadata.risk_level.value,
            )
            return {
                "status": ExecutionStatus.BLOCKED.value,
                "run_id": run_id,
                "risk_level": metadata.risk_level.value,
                "reason": decision.reason,
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
                    "dag_json": json.dumps([node.as_dict() for node in nodes], ensure_ascii=False),
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
                result={"reason": decision.reason},
                confirmation_state="pending",
                risk_level=risk_level.value,
            )
            return {
                "status": ExecutionStatus.AWAITING_CONFIRMATION.value,
                "run_id": run_id,
                "risk_level": risk_level.value,
                "reason": decision.reason,
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
                "reason": "用户已拒绝该操作。",
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
