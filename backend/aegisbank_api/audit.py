"""Tamper-evident audit log built as a SHA-256 hash chain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .db import Database, utc_now


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(slots=True)
class AuditService:
    db: Database

    def record(
        self,
        *,
        event: str,
        user_id: str,
        instruction: str,
        dag_path: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any] | list[dict[str, Any]] | None,
        confirmation_state: str,
        risk_level: str,
    ) -> dict[str, Any]:
        entry = {
            "created_at": utc_now(),
            "event": event,
            "user_id": user_id,
            "instruction": instruction,
            "dag_path": dag_path,
            "tool_name": tool_name,
            "arguments_json": _canonical(arguments),
            "result_json": _canonical({"result": result}),
            "confirmation_state": confirmation_state,
            "risk_level": risk_level,
        }
        prev_hash = self.db.last_audit_hash()
        digest_input = prev_hash + _canonical(entry)
        entry_hash = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        row = {**entry, "prev_hash": prev_hash, "entry_hash": entry_hash}
        record_id = self.db.append_audit(row)
        return {
            "id": record_id,
            **entry,
            "arguments": arguments,
            "result": result,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.list_audit(limit=limit)
        for row in rows:
            row["arguments"] = json.loads(row.pop("arguments_json"))
            row["result"] = json.loads(row.pop("result_json")).get("result")
        return rows

    def verify(self) -> dict[str, Any]:
        prev_hash = ""
        checked = 0
        for row in self.db.all_audit_ascending():
            entry = {
                "created_at": row["created_at"],
                "event": row["event"],
                "user_id": row["user_id"],
                "instruction": row["instruction"],
                "dag_path": row["dag_path"],
                "tool_name": row["tool_name"],
                "arguments_json": row["arguments_json"],
                "result_json": row["result_json"],
                "confirmation_state": row["confirmation_state"],
                "risk_level": row["risk_level"],
            }
            expected = hashlib.sha256(
                (prev_hash + _canonical(entry)).encode("utf-8")
            ).hexdigest()
            if row["prev_hash"] != prev_hash or row["entry_hash"] != expected:
                return {
                    "valid": False,
                    "checked": checked,
                    "broken_at": row["id"],
                    "reason": "hash chain mismatch",
                }
            prev_hash = row["entry_hash"]
            checked += 1
        return {"valid": True, "checked": checked}
