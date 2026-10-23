"""Task lifecycle state machine with audited, persisted transitions.

``UNKNOWN`` is deliberately not a failure: the side effect may or may not have
happened, so the action must be reconciled or rolled back instead of being
submitted again automatically.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from ..audit import AuditService
from ..db import Database
from .evidence import hash_chain_evidence, merge_evidence


class ActionState(StrEnum):
    DRAFT = "DRAFT"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    AWAITING_REAUTH = "AWAITING_REAUTH"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    RECONCILED = "RECONCILED"
    ROLLED_BACK = "ROLLED_BACK"


ALLOWED_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    ActionState.DRAFT: frozenset(
        {
            ActionState.AWAITING_CONFIRMATION,
            ActionState.AWAITING_REAUTH,
            ActionState.REJECTED,
            ActionState.EXPIRED,
        }
    ),
    ActionState.AWAITING_CONFIRMATION: frozenset(
        {
            ActionState.AWAITING_REAUTH,
            ActionState.APPROVED,
            ActionState.REJECTED,
            ActionState.EXPIRED,
            ActionState.FAILED,
        }
    ),
    ActionState.AWAITING_REAUTH: frozenset(
        {
            ActionState.APPROVED,
            ActionState.REJECTED,
            ActionState.EXPIRED,
            ActionState.FAILED,
        }
    ),
    ActionState.APPROVED: frozenset({ActionState.EXECUTING, ActionState.FAILED}),
    ActionState.EXECUTING: frozenset(
        {ActionState.COMPLETED, ActionState.FAILED, ActionState.UNKNOWN}
    ),
    ActionState.UNKNOWN: frozenset({ActionState.RECONCILED, ActionState.ROLLED_BACK}),
    ActionState.COMPLETED: frozenset(),
    ActionState.FAILED: frozenset(),
    ActionState.REJECTED: frozenset(),
    ActionState.EXPIRED: frozenset(),
    ActionState.RECONCILED: frozenset(),
    ActionState.ROLLED_BACK: frozenset(),
}

TERMINAL_STATES = frozenset(
    {
        ActionState.COMPLETED,
        ActionState.FAILED,
        ActionState.REJECTED,
        ActionState.EXPIRED,
        ActionState.RECONCILED,
        ActionState.ROLLED_BACK,
    }
)


class IllegalTransition(ValueError):
    """Raised when a requested state transition is not part of the contract."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"非法状态迁移：{current} → {target}")
        self.current = current
        self.target = target


class ExecutionOutcomeUnknown(RuntimeError):
    """A tool raised after possibly sending the request; outcome is unknown."""


class StateMachine:
    """Persists state/history in ``pending_actions`` and audits each move."""

    def __init__(
        self,
        *,
        db: Database,
        action_id: str,
        audit: AuditService | None = None,
        user_id: str = "demo-user",
        instruction: str = "",
        dag_path: str = "",
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
        risk_level: str = "green",
        state: ActionState = ActionState.DRAFT,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        self.db = db
        self.action_id = action_id
        self.audit = audit
        self.user_id = user_id
        self.instruction = instruction
        self.dag_path = dag_path
        self.tool_name = tool_name
        self.arguments = arguments or {}
        self.risk_level = risk_level
        self.state = state
        self.history = list(history or [])

    @classmethod
    def load(
        cls,
        *,
        db: Database,
        audit: AuditService | None,
        record: dict[str, Any],
    ) -> StateMachine:
        raw_state = str(record.get("state") or "").strip()
        try:
            state = ActionState(raw_state)
        except ValueError:
            state = (
                ActionState.AWAITING_CONFIRMATION
                if record.get("status") == "pending"
                else ActionState.DRAFT
            )
        try:
            history = json.loads(record.get("state_history_json") or "[]")
        except ValueError:
            history = []
        return cls(
            db=db,
            action_id=str(record["id"]),
            audit=audit,
            user_id=str(record.get("user_id") or "demo-user"),
            instruction=str(record.get("instruction") or ""),
            dag_path=str(record.get("dag_path") or ""),
            tool_name=str(record.get("tool_name") or ""),
            risk_level=str(record.get("risk_level") or "green"),
            state=state,
            history=history if isinstance(history, list) else [],
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transition(
        self,
        target: ActionState | str,
        *,
        reason: str = "",
        evidence: list[dict[str, Any]] | None = None,
    ) -> ActionState:
        try:
            wanted = target if isinstance(target, ActionState) else ActionState(str(target))
        except ValueError as exc:
            raise IllegalTransition(self.state.value, str(target)) from exc
        if wanted not in ALLOWED_TRANSITIONS[self.state]:
            if self.audit is not None:
                self.audit.record(
                    event="state_transition_rejected",
                    user_id=self.user_id,
                    instruction=self.instruction,
                    dag_path=self.dag_path,
                    tool_name=self.tool_name or "state-machine",
                    arguments=self.arguments,
                    result={
                        "action_id": self.action_id,
                        "from": self.state.value,
                        "to": wanted.value,
                        "reason": reason or "非法状态迁移已拒绝",
                    },
                    confirmation_state=self.state.value,
                    risk_level=self.risk_level,
                    evidence=merge_evidence(
                        evidence,
                        [
                            hash_chain_evidence(
                                True, "非法迁移拒绝记录已进入审计链"
                            ).as_dict()
                        ],
                    ),
                )
            raise IllegalTransition(self.state.value, wanted.value)
        previous = self.state
        self.state = wanted
        self.history.append(
            {
                "from": previous.value,
                "to": wanted.value,
                "reason": reason,
            }
        )
        self.db.set_pending_state(
            self.action_id,
            self.state.value,
            json.dumps(self.history, ensure_ascii=False),
        )
        if self.audit is not None:
            self.audit.record(
                event="state_transition",
                user_id=self.user_id,
                instruction=self.instruction,
                dag_path=self.dag_path,
                tool_name=self.tool_name or "state-machine",
                arguments=self.arguments,
                result={
                    "action_id": self.action_id,
                    "from": previous.value,
                    "to": wanted.value,
                    "reason": reason,
                },
                confirmation_state=wanted.value,
                risk_level=self.risk_level,
                evidence=merge_evidence(
                    evidence,
                    [
                        hash_chain_evidence(
                            True, f"状态迁移 {previous.value} -> {wanted.value}"
                        ).as_dict()
                    ],
                ),
            )
        return wanted
