"""Step-level pause/resume bookkeeping and execution journal (stage 2A).

The scheduler checks the pause flag *between* DAG nodes and records every
successfully executed node in an execution journal. Both live in SQLite so a
paused action can be resumed from a later HTTP request without repeating
already-executed side effects, and a failed action can be compensated in
reverse order with an auditable trail.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..db import Database

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS action_pauses (
    action_id TEXT PRIMARY KEY,
    paused INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    requested_at TEXT,
    resumed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_journal (
    action_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    instruction TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'executing',
    next_index INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT 'green',
    nodes_json TEXT NOT NULL DEFAULT '[]',
    results_json TEXT NOT NULL DEFAULT '[]',
    plan_json TEXT NOT NULL DEFAULT '{}',
    response_json TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    risk_level TEXT NOT NULL DEFAULT 'green',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_action_journal_entries_action
    ON action_journal_entries(action_id, id);
"""



def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _loads(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return fallback
    return parsed


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class PauseRegistry:
    """Persisted pause/resume flags keyed by action (or run) id.

    Repeating a pause or a resume is idempotent: the row is upserted and the
    current state is returned instead of raising.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.db.transaction() as conn:
            conn.executescript(SCHEMA_SQL)

    def pause(self, action_id: str, *, reason: str = "用户请求暂停") -> dict[str, Any]:
        now = _now()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO action_pauses
                (action_id, paused, reason, requested_at, resumed_at, updated_at)
                VALUES (?, 1, ?, ?, NULL, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    paused = 1,
                    reason = excluded.reason,
                    requested_at = excluded.requested_at,
                    updated_at = excluded.updated_at
                """,
                (action_id, reason, now, now),
            )
        return self.status(action_id)

    def resume(self, action_id: str) -> dict[str, Any]:
        now = _now()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO action_pauses
                (action_id, paused, reason, requested_at, resumed_at, updated_at)
                VALUES (?, 0, '', NULL, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    paused = 0,
                    resumed_at = excluded.resumed_at,
                    updated_at = excluded.updated_at
                """,
                (action_id, now, now),
            )
        return self.status(action_id)

    def is_paused(self, action_id: str) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT paused FROM action_pauses WHERE action_id = ?", (action_id,)
            ).fetchone()
        return bool(row["paused"]) if row is not None else False

    def status(self, action_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM action_pauses WHERE action_id = ?", (action_id,)
            ).fetchone()
        if row is None:
            return {
                "action_id": action_id,
                "paused": False,
                "reason": "",
                "requested_at": None,
                "resumed_at": None,
                "updated_at": None,
                "exists": False,
            }
        return {
            "action_id": action_id,
            "paused": bool(row["paused"]),
            "reason": str(row["reason"] or ""),
            "requested_at": row["requested_at"],
            "resumed_at": row["resumed_at"],
            "updated_at": row["updated_at"],
            "exists": True,
        }


class ActionJournal:
    """Append-only execution journal with per-node phase records."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.db.transaction() as conn:
            conn.executescript(SCHEMA_SQL)

    def begin(
        self,
        action_id: str,
        *,
        user_id: str,
        instruction: str = "",
        role: str = "user",
        nodes: list[Any],
        plan: dict[str, Any] | None = None,
        risk_level: str = "green",
    ) -> None:
        now = _now()
        nodes_json = _dumps([node.as_dict() for node in nodes])
        plan_json = _dumps(plan or {})
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO action_journal
                (action_id, user_id, instruction, role, status, next_index,
                 risk_level, nodes_json, results_json, plan_json, response_json,
                 reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'executing', 0, ?, ?, '[]', ?, '', '', ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    instruction = excluded.instruction,
                    role = excluded.role,
                    status = 'executing',
                    next_index = 0,
                    risk_level = excluded.risk_level,
                    nodes_json = excluded.nodes_json,
                    results_json = '[]',
                    plan_json = excluded.plan_json,
                    response_json = '',
                    reason = '',
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    action_id,
                    user_id,
                    instruction,
                    role,
                    risk_level,
                    nodes_json,
                    plan_json,
                    now,
                    now,
                ),
            )

    def mark_running(self, action_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE action_journal SET status = 'executing', reason = '', "
                "response_json = '', updated_at = ? WHERE action_id = ?",
                (_now(), action_id),
            )

    def record_execution(
        self,
        action_id: str,
        *,
        index: int,
        results: list[dict[str, Any]],
        node: Any,
        arguments: dict[str, Any],
        result: dict[str, Any],
        risk_level: str,
    ) -> None:
        now = _now()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE action_journal SET next_index = ?, results_json = ?, "
                "updated_at = ? WHERE action_id = ?",
                (index, _dumps(results), now, action_id),
            )
            self._insert_entry(
                conn,
                action_id=action_id,
                node_id=str(node.id),
                tool_name=str(node.tool_name),
                phase="executed",
                status="succeeded",
                arguments=arguments,
                result=result,
                risk_level=risk_level,
            )

    def append_entry(
        self,
        action_id: str,
        *,
        node_id: str,
        tool_name: str,
        phase: str,
        status: str,
        arguments: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        risk_level: str = "green",
    ) -> None:
        with self.db.transaction() as conn:
            self._insert_entry(
                conn,
                action_id=action_id,
                node_id=node_id,
                tool_name=tool_name,
                phase=phase,
                status=status,
                arguments=arguments or {},
                result=result or {},
                risk_level=risk_level,
            )

    @staticmethod
    def _insert_entry(
        conn: Any,
        *,
        action_id: str,
        node_id: str,
        tool_name: str,
        phase: str,
        status: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        risk_level: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO action_journal_entries
            (action_id, node_id, tool_name, phase, status, arguments_json,
             result_json, risk_level, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                node_id,
                tool_name,
                phase,
                status,
                _dumps(arguments),
                _dumps(result),
                risk_level,
                _now(),
            ),
        )

    def update_status(
        self,
        action_id: str,
        status: str,
        *,
        reason: str = "",
        response: dict[str, Any] | None = None,
    ) -> None:
        response_json = _dumps(response) if response is not None else None
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE action_journal SET status = ?, reason = ?, "
                "response_json = COALESCE(?, response_json), updated_at = ? "
                "WHERE action_id = ?",
                (status, reason, response_json, _now(), action_id),
            )

    def get(self, action_id: str) -> dict[str, Any] | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM action_journal WHERE action_id = ?", (action_id,)
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["nodes"] = _loads(record.pop("nodes_json", "[]"), [])
        record["results"] = _loads(record.pop("results_json", "[]"), [])
        record["plan"] = _loads(record.pop("plan_json", "{}"), {})
        record["response"] = _loads(record.pop("response_json", ""), None)
        return record

    def entries(self, action_id: str) -> list[dict[str, Any]]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM action_journal_entries WHERE action_id = ? ORDER BY id",
                (action_id,),
            ).fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["arguments"] = _loads(item.pop("arguments_json", "{}"), {})
            item["result"] = _loads(item.pop("result_json", "{}"), {})
            entries.append(item)
        return entries

    def executed_entries(self, action_id: str) -> list[dict[str, Any]]:
        return [entry for entry in self.entries(action_id) if entry["phase"] == "executed"]

    def compensated_node_ids(self, action_id: str) -> set[str]:
        return {
            str(entry["node_id"])
            for entry in self.entries(action_id)
            if entry["phase"] == "compensated"
        }