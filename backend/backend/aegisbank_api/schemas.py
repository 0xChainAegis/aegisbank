"""HTTP request models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AgentRunRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2_000)
    user_id: str = Field(default="demo-user", min_length=1, max_length=64)
    tool_name: str | None = Field(default=None, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    clarification_run_id: str | None = Field(default=None, max_length=64)
    # U2: one bounded active draft per user/session. ``draft_version`` is a
    # compare-and-swap guard; clients must send the version returned with the
    # draft and refresh after a 409 draft_version_conflict.
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    draft_id: str | None = Field(default=None, min_length=1, max_length=64)
    draft_version: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def draft_fields_are_complete(self):
        if self.draft_id is not None and self.draft_version is None:
            raise ValueError("使用 draft_id 时必须同时提供 draft_version。")
        if self.draft_version is not None and self.draft_id is None:
            raise ValueError("提供 draft_version 时必须同时提供 draft_id。")
        return self


class ConfirmationRequest(BaseModel):
    approved: bool
    reauth_token: str | None = Field(default=None, max_length=32)
    mfa_provider: str | None = Field(default=None, max_length=32)
    user_id: str = Field(default="demo-user", min_length=1, max_length=64)
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    draft_id: str | None = Field(default=None, min_length=1, max_length=64)
    draft_version: int | None = Field(default=None, ge=1, le=1_000_000)


class PermissionUpdateRequest(BaseModel):
    granted: bool


class ReconcileRequest(BaseModel):
    outcome: Literal["reconciled", "rolled_back"]
    reason: str = Field(default="", max_length=240)