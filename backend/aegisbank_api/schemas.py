"""HTTP request models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2_000)
    user_id: str = Field(default="demo-user", min_length=1, max_length=64)
    tool_name: str | None = Field(default=None, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ConfirmationRequest(BaseModel):
    approved: bool
    reauth_token: str | None = Field(default=None, max_length=32)


class PermissionUpdateRequest(BaseModel):
    granted: bool
