"""Small SQLite persistence layer used by the local MVP."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """Thread-safe SQLite access with explicit short-lived connections."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS permissions (
                    user_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    granted INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, tool_name)
                );

                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    dag_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    risk_level TEXT NOT NULL,
                    requires_reauth INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    dag_path TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    confirmation_state TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(pending_actions)")
            }
            if "plan_json" not in columns:
                conn.execute(
                    "ALTER TABLE pending_actions ADD COLUMN plan_json TEXT NOT NULL DEFAULT '{}'"
                )

    @contextmanager
    def transaction(self):
        """Yield a short-lived connection with an explicit transaction boundary."""
        with self._lock, self._connect() as conn:
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise

    # ---------- permissions ----------
    def seed_permissions(self, user_id: str, tool_names: list[str]) -> None:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO permissions (user_id, tool_name, granted, updated_at)
                VALUES (?, ?, 1, ?)
                """,
                [(user_id, name, now) for name in tool_names],
            )

    def list_permissions(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT tool_name, granted, updated_at FROM permissions "
                "WHERE user_id = ? ORDER BY tool_name",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_permission(self, user_id: str, tool_name: str) -> bool | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT granted FROM permissions WHERE user_id = ? AND tool_name = ?",
                (user_id, tool_name),
            ).fetchone()
        return None if row is None else bool(row["granted"])

    def set_permission(self, user_id: str, tool_name: str, granted: bool) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO permissions (user_id, tool_name, granted, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, tool_name) DO UPDATE SET
                    granted = excluded.granted,
                    updated_at = excluded.updated_at
                """,
                (user_id, tool_name, int(granted), utc_now()),
            )

    # ---------- pending confirmations ----------
    def create_pending(self, record: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_actions
                (id, user_id, instruction, dag_json, plan_json, risk_level, requires_reauth,
                 status, created_at, expires_at, resolved_at)
                VALUES (:id, :user_id, :instruction, :dag_json, :plan_json, :risk_level,
                        :requires_reauth, :status, :created_at, :expires_at, NULL)
                """,
                record,
            )

    def get_pending(self, action_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def resolve_pending(self, action_id: str, status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE pending_actions SET status = ?, resolved_at = ? WHERE id = ?",
                (status, utc_now(), action_id),
            )

    # ---------- audit chain ----------
    def append_audit(self, record: dict[str, Any]) -> int:
        columns = (
            "created_at,event,user_id,instruction,dag_path,tool_name,arguments_json,"
            "result_json,confirmation_state,risk_level,prev_hash,entry_hash"
        )
        values = (
            record["created_at"],
            record["event"],
            record["user_id"],
            record["instruction"],
            record["dag_path"],
            record["tool_name"],
            record["arguments_json"],
            record["result_json"],
            record["confirmation_state"],
            record["risk_level"],
            record["prev_hash"],
            record["entry_hash"],
        )
        placeholders = ",".join("?" for _ in values)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO audit_log ({columns}) VALUES ({placeholders})", values
            )
            return int(cursor.lastrowid)

    def last_audit_hash(self) -> str:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return "" if row is None else str(row["entry_hash"])

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def all_audit_ascending(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]
