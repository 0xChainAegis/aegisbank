"""Idempotency keys with request-body hashing and persisted first results.

A repeated ``Idempotency-Key`` returns the first result instead of creating a
second pending action or a second execution. Reusing the same key with a
different request body is a hard conflict (HTTP 409).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..db import Database
from .action_envelope import canonical_hash


class IdempotencyError(ValueError):
    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class IdempotencyKeyReused(IdempotencyError):
    code = "IDEMPOTENCY_KEY_REUSED"


class IdempotencyInProgress(IdempotencyError):
    code = "IDEMPOTENCY_IN_PROGRESS"


@dataclass(slots=True)
class IdempotencyOutcome:
    state: str
    response: dict[str, Any] | None = None


class IdempotencyStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def request_hash(payload: dict[str, Any]) -> str:
        return canonical_hash(payload)

    def begin(self, *, scope: str, key: str, request_hash: str) -> IdempotencyOutcome:
        existing = self.db.get_idempotency(scope, key)
        if existing is None:
            self.db.create_idempotency(scope=scope, key=key, request_hash=request_hash)
            return IdempotencyOutcome(state="new")
        if existing["request_hash"] != request_hash:
            raise IdempotencyKeyReused(
                "同一个 Idempotency-Key 携带了不同的请求内容，拒绝处理。"
            )
        if existing["status"] == "completed" and existing.get("response_json"):
            return IdempotencyOutcome(
                state="replay", response=json.loads(existing["response_json"])
            )
        raise IdempotencyInProgress("相同 Idempotency-Key 的请求正在处理中，请稍后重试。")

    def complete(self, *, scope: str, key: str, response: dict[str, Any]) -> None:
        self.db.complete_idempotency(
            scope=scope,
            key=key,
            response_json=json.dumps(response, ensure_ascii=False, sort_keys=True),
        )

    def release(self, *, scope: str, key: str) -> None:
        """Drop an unfinished record so a failed attempt can be retried."""
        self.db.delete_idempotency(scope=scope, key=key)

    def get(self, *, scope: str, key: str) -> dict[str, Any] | None:
        return self.db.get_idempotency(scope, key)
