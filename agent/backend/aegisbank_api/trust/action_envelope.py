"""ActionEnvelope/v1: one-shot binding of plan, arguments, risk, and identity.

A human confirmation is a confirmation of *this envelope*. Before execution the
server recomputes the plan hash, the arguments hash, the risk level, and the
permission; any divergence aborts the action with ``ENVELOPE_MISMATCH``. The
nonce is single-use, so a captured envelope cannot be replayed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..db import Database, utc_now
from ..domain import PlanNode
from ..risk import RiskAssessment

SCHEMA_VERSION = "action-envelope/v1"


class EnvelopeError(ValueError):
    """Base class for envelope verification failures; carries a stable code."""

    code = "ENVELOPE_MISMATCH"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class EnvelopeMismatch(EnvelopeError):
    code = "ENVELOPE_MISMATCH"


class EnvelopeExpired(EnvelopeError):
    code = "ENVELOPE_EXPIRED"


class NonceReused(EnvelopeError):
    code = "NONCE_REUSED"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def arguments_hash(arguments: dict[str, Any]) -> str:
    return canonical_hash(arguments)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(slots=True)
class ActionEnvelope:
    schema_version: str = SCHEMA_VERSION
    user_id: str = ""
    plan_hash: str = ""
    step_id: str = ""
    tool_name: str = ""
    arguments_hash: str = ""
    risk_level: str = "green"
    risk_reasons: list[str] = field(default_factory=list)
    permission: str = ""
    nonce: str = ""
    issued_at: str = ""
    expires_at: str = ""
    confirmation_state: str = "pending"
    approval_token: str | None = None

    def as_dict(self, *, include_token: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "user_id": self.user_id,
            "plan_hash": self.plan_hash,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "arguments_hash": self.arguments_hash,
            "risk_level": self.risk_level,
            "risk_reasons": list(self.risk_reasons),
            "permission": self.permission,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "confirmation_state": self.confirmation_state,
            "approval_token": self.approval_token if include_token else None,
        }
        return payload

    def masked(self) -> dict[str, Any]:
        """API/audit representation that never exposes the approval token."""
        payload = self.as_dict(include_token=False)
        payload["approval_token_present"] = bool(self.approval_token)
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ActionEnvelope:
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            user_id=str(value.get("user_id") or ""),
            plan_hash=str(value.get("plan_hash") or ""),
            step_id=str(value.get("step_id") or ""),
            tool_name=str(value.get("tool_name") or ""),
            arguments_hash=str(value.get("arguments_hash") or ""),
            risk_level=str(value.get("risk_level") or "green"),
            risk_reasons=[str(item) for item in value.get("risk_reasons") or []],
            permission=str(value.get("permission") or ""),
            nonce=str(value.get("nonce") or ""),
            issued_at=str(value.get("issued_at") or ""),
            expires_at=str(value.get("expires_at") or ""),
            confirmation_state=str(value.get("confirmation_state") or "pending"),
            approval_token=value.get("approval_token"),
        )


def build_envelopes(
    *,
    user_id: str,
    plan_hash: str,
    nodes: list[PlanNode],
    assessments: dict[str, RiskAssessment],
    permissions: dict[str, str],
    issued_at: datetime,
    expires_at: datetime,
) -> list[ActionEnvelope]:
    """Create one envelope per plan node at confirmation-request time."""
    envelopes: list[ActionEnvelope] = []
    for node in nodes:
        assessment = assessments[node.id]
        envelopes.append(
            ActionEnvelope(
                user_id=user_id,
                plan_hash=plan_hash,
                step_id=node.id,
                tool_name=node.tool_name,
                arguments_hash=arguments_hash(node.arguments),
                risk_level=assessment.level.value,
                risk_reasons=list(assessment.reasons),
                permission=permissions[node.id],
                nonce=uuid4().hex,
                issued_at=issued_at.isoformat(timespec="seconds"),
                expires_at=expires_at.isoformat(timespec="seconds"),
                confirmation_state="pending",
            )
        )
    return envelopes


def approval_token_for(*, action_id: str, approvals: list[ActionEnvelope]) -> str:
    """Deterministic demo approval token; only its hash is ever persisted."""
    seed = "|".join(f"{item.step_id}:{item.nonce}" for item in approvals)
    return hashlib.sha256(f"{action_id}|{seed}|approved".encode()).hexdigest()


class EnvelopeService:
    """Server-side envelope verification and one-time nonce bookkeeping."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def is_nonce_used(self, nonce: str) -> bool:
        return self.db.nonce_used(nonce)

    def verify(
        self,
        envelope: ActionEnvelope,
        *,
        user_id: str,
        expected_plan_hash: str,
        step: PlanNode,
        assessment: RiskAssessment,
        permission: str,
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(UTC)
        if envelope.schema_version != SCHEMA_VERSION:
            raise EnvelopeMismatch(
                f"不支持的 ActionEnvelope 版本：{envelope.schema_version}。",
                code="ENVELOPE_VERSION_UNSUPPORTED",
            )
        try:
            expires_at = _parse_time(envelope.expires_at)
        except ValueError as exc:
            raise EnvelopeMismatch("ActionEnvelope 过期时间格式非法。") from exc
        if current > expires_at:
            raise EnvelopeExpired("ActionEnvelope 已过期，请重新发起操作。")
        if self.is_nonce_used(envelope.nonce):
            raise NonceReused("ActionEnvelope nonce 已被使用，拒绝重放。")
        if envelope.user_id != user_id:
            raise EnvelopeMismatch("ActionEnvelope 的用户身份与当前请求不一致。")
        if envelope.plan_hash != expected_plan_hash:
            raise EnvelopeMismatch("计划哈希与确认时不一致，拒绝执行。")
        if envelope.step_id != step.id or envelope.tool_name != step.tool_name:
            raise EnvelopeMismatch("ActionEnvelope 绑定的步骤或工具与计划不一致。")
        if envelope.arguments_hash != arguments_hash(step.arguments):
            raise EnvelopeMismatch("工具参数哈希与确认时不一致，拒绝执行。")
        if envelope.risk_level != assessment.level.value:
            raise EnvelopeMismatch(
                f"风险等级已变化（{envelope.risk_level} → {assessment.level.value}），拒绝执行。"
            )
        if envelope.permission != permission:
            raise EnvelopeMismatch("工具权限声明与确认时不一致，拒绝执行。")

    def claim_nonces(self, envelopes: list[ActionEnvelope], *, action_id: str) -> None:
        """Consume every nonce at resolution time; replay attempts are rejected."""
        for envelope in envelopes:
            if not self.db.claim_nonce(envelope.nonce, action_id):
                raise NonceReused("ActionEnvelope nonce 已被使用，拒绝重放。")

    def approve(
        self,
        envelopes: list[ActionEnvelope],
        *,
        action_id: str,
        reauth_verified: bool,
    ) -> list[ActionEnvelope]:
        token = approval_token_for(action_id=action_id, approvals=envelopes)
        approved: list[ActionEnvelope] = []
        for envelope in envelopes:
            envelope.confirmation_state = "approved"
            envelope.approval_token = token if reauth_verified else token[:16]
            approved.append(envelope)
        return approved

    @staticmethod
    def now_text() -> str:
        return utc_now()
