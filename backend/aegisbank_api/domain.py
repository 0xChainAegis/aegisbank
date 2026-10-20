"""Domain primitives shared by the gateway, scheduler, tools, and audit log."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    """The three risk levels used by AegisBank."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class ExecutionStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    NEEDS_CLARIFICATION = "needs_clarification"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    name: str
    title: str
    description: str
    risk_level: RiskLevel
    permission: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "permission": self.permission,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    user_id: str
    instruction: str
    run_id: str
    dag_path: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_name: str
    message: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"tool_name": self.tool_name, "message": self.message, "data": self.data}


@dataclass(frozen=True, slots=True)
class GatewayDecision:
    outcome: str
    reason: str
    requires_reauth: bool = False

    @property
    def allowed_now(self) -> bool:
        return self.outcome == "allow"

    @property
    def denied(self) -> bool:
        return self.outcome == "deny"


@dataclass(slots=True)
class PlanNode:
    id: str
    tool_name: str
    arguments: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PlanNode:
        return cls(
            id=str(value["id"]),
            tool_name=str(value["tool_name"]),
            arguments=dict(value.get("arguments") or {}),
            depends_on=[str(item) for item in value.get("depends_on") or []],
        )
