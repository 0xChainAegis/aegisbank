"""Versioned planning contracts shared by rule and LLM planners."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanningRequest(BaseModel):
    """Everything a planner may use; tool access is deliberately absent."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(default="demo-user", min_length=1, max_length=64)
    instruction: str = Field(min_length=1, max_length=2_000)
    tool_name: str | None = Field(default=None, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    """One declarative step in a plan. It is not executable by itself."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=240)


class ExecutionPlan(BaseModel):
    """A planner proposal that must pass the deterministic PlanCompiler."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=64)
    steps: list[PlanStep] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    needs_clarification: bool = False
    clarification: str | None = Field(default=None, max_length=500)
    planner: str = Field(default="rule", max_length=64)

    @model_validator(mode="after")
    def validate_shape(self) -> ExecutionPlan:
        if self.needs_clarification and not self.clarification:
            raise ValueError("needs_clarification=true 时必须提供 clarification")
        if not self.needs_clarification and not self.steps:
            raise ValueError("可执行计划至少需要一个 step")
        if self.needs_clarification and self.steps:
            raise ValueError("clarification 计划不能同时包含可执行 steps")
        return self


class Planner(Protocol):
    """Planner interface: implementations may be rule-based or model-based."""

    name: str

    def plan(self, request: PlanningRequest) -> ExecutionPlan:
        ...
