"""Untrusted language candidates and server-owned semantic evidence, version 1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextSpan(StrictModel):
    start: int = Field(ge=0, le=2000)
    end: int = Field(gt=0, le=2000)
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Source span must be nonempty")
        return self


class SemanticIntent(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    kind: str = Field(min_length=1, max_length=64)
    span: TextSpan
    polarity: Literal["affirmative", "negative"] = "affirmative"
    slots: dict[str, TextSpan] = Field(default_factory=dict, max_length=12)


class OrderRelation(StrictModel):
    before: str
    after: str


class SemanticFrame(StrictModel):
    schema_version: Literal["SemanticFrame/v1"] = "SemanticFrame/v1"
    intents: list[SemanticIntent] = Field(default_factory=list, max_length=12)
    conditions: list[TextSpan] = Field(default_factory=list, max_length=12)
    ordering: list[OrderRelation] = Field(default_factory=list, max_length=12)
    uncovered: list[TextSpan] = Field(default_factory=list, max_length=24)
    missing_slots: list[str] = Field(default_factory=list, max_length=24)
    needs_clarification: bool = False
    clarification: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def identifiers(self):
        ids = [intent.id for intent in self.intents]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate semantic intent ids")
        for edge in self.ordering:
            if edge.before not in ids or edge.after not in ids or edge.before == edge.after:
                raise ValueError("Invalid semantic order reference")
        return self


class SlotEvidence(StrictModel):
    intent_id: str
    slot: str
    span: TextSpan | None = None
    value: str
    source: Literal["user_text", "mock_entity_catalog", "demo_policy", "calendar"]
    verified: bool = True
    verification_kind: str
    candidates: list[str] = Field(default_factory=list)


class SemanticAnalysis(StrictModel):
    schema_version: Literal["SemanticAnalysis/v1"] = "SemanticAnalysis/v1"
    status: Literal["verified", "clarification", "legacy"]
    instruction_hash: str
    frame: SemanticFrame | None = None
    slots: list[SlotEvidence] = Field(default_factory=list)
    reason: str | None = None
    reference_date: str | None = None
    timezone: Literal["UTC", "Asia/Shanghai"] = "Asia/Shanghai"
