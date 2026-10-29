"""Small SQLite persistence layer used by the local MVP."""

from __future__ import annotations

import fcntl
import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

execution_deadline: ContextVar[float | None] = ContextVar("execution_deadline", default=None)


class ExecutionDeadlineExceeded(RuntimeError):
    """The guarded execution is no longer permitted to persist changes."""


def check_execution_deadline() -> None:
    deadline = execution_deadline.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise ExecutionDeadlineExceeded("工具已超时，禁止继续写入或提交数据库。")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """Thread-safe SQLite access with explicit short-lived connections."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self.transaction() as conn:
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
                    resolved_at TEXT,
                    envelopes_json TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL DEFAULT 'DRAFT',
                    state_history_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT NOT NULL DEFAULT '',
                    mfa_failures INTEGER NOT NULL DEFAULT 0
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

                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, key)
                );

                CREATE TABLE IF NOT EXISTS used_nonces (
                    nonce TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    used_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS clarification_uses (
                    run_id TEXT PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS circuit_breaker (
                    name TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL DEFAULT 0,
                    last_failure_at TEXT,
                    opened_at TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            pending_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(pending_actions)")
            }
            migrations = {
                "plan_json": "ALTER TABLE pending_actions ADD COLUMN "
                "plan_json TEXT NOT NULL DEFAULT '{}'",
                "envelopes_json": "ALTER TABLE pending_actions ADD COLUMN "
                "envelopes_json TEXT NOT NULL DEFAULT '[]'",
                "state": "ALTER TABLE pending_actions ADD COLUMN "
                "state TEXT NOT NULL DEFAULT 'DRAFT'",
                "state_history_json": "ALTER TABLE pending_actions ADD COLUMN "
                "state_history_json TEXT NOT NULL DEFAULT '[]'",
                "result_json": "ALTER TABLE pending_actions ADD COLUMN "
                "result_json TEXT NOT NULL DEFAULT ''",
                "mfa_failures": "ALTER TABLE pending_actions ADD COLUMN "
                "mfa_failures INTEGER NOT NULL DEFAULT 0",
            }
            for column, statement in migrations.items():
                if column not in pending_columns:
                    conn.execute(statement)

    @contextmanager
    def transaction(self):
        """One reentrant unit of work, including domain writes, audit and journal.

        Nested repository calls on the same worker use the outer connection.
        BEGIN IMMEDIATE also serializes competing processes before reading balances.
        """
        check_execution_deadline()
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            sequence = getattr(self._local, "sequence", 0) + 1
            self._local.sequence = sequence
            name = f"unit_{sequence}"
            existing.execute(f"SAVEPOINT {name}")
            try:
                yield existing
                check_execution_deadline()
                existing.execute(f"RELEASE SAVEPOINT {name}")
            except BaseException:
                existing.execute(f"ROLLBACK TO SAVEPOINT {name}")
                existing.execute(f"RELEASE SAVEPOINT {name}")
                raise
            return
        with self._lock:
            check_execution_deadline()
            conn = self._connect()
            self._local.connection = conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                check_execution_deadline()
                yield conn
                check_execution_deadline()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                self._local.connection = None
                conn.close()

    @property
    def in_transaction(self) -> bool:
        return getattr(self._local, "connection", None) is not None

    @contextmanager
    def action_lock(self, action_id: str):
        """Cross-process action ownership; the OS releases it after a crash."""
        directory = self.path.parent / ".action-locks"
        directory.mkdir(exist_ok=True)
        key = hashlib.sha256(action_id.encode()).hexdigest()
        with (directory / key).open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                from .trust.action_envelope import EnvelopeError

                raise EnvelopeError(
                    "该动作正在处理，请查询原动作，勿重新下单。", code="ACTION_IN_PROGRESS"
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    # ---------- permissions ----------
    def seed_permissions(self, user_id: str, tool_names: list[str]) -> None:
        now = utc_now()
        with self.transaction() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO permissions (user_id, tool_name, granted, updated_at)
                VALUES (?, ?, 1, ?)
                """,
                [(user_id, name, now) for name in tool_names],
            )

    def remove_granted_permissions(self, user_id: str, tool_names: list[str]) -> None:
        """Delete stale positive grants without reviving an explicit denial."""
        names = sorted({str(name) for name in tool_names if str(name)})
        if not names:
            return
        placeholders = ",".join("?" for _ in names)
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM permissions WHERE user_id = ? AND granted = 1 "
                f"AND tool_name IN ({placeholders})",
                (user_id, *names),
            )

    def list_permissions(self, user_id: str) -> list[dict[str, Any]]:
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT tool_name, granted, updated_at FROM permissions "
                "WHERE user_id = ? ORDER BY tool_name",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_permission(self, user_id: str, tool_name: str) -> bool | None:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT granted FROM permissions WHERE user_id = ? AND tool_name = ?",
                (user_id, tool_name),
            ).fetchone()
        return None if row is None else bool(row["granted"])

    def set_permission(self, user_id: str, tool_name: str, granted: bool) -> None:
        with self.transaction() as conn:
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
        payload = {
            "envelopes_json": "[]",
            "state": "DRAFT",
            "state_history_json": "[]",
            "result_json": "",
            "mfa_failures": 0,
            **record,
        }
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO pending_actions
                (id, user_id, instruction, dag_json, plan_json, risk_level, requires_reauth,
                 status, created_at, expires_at, resolved_at, envelopes_json, state,
                 state_history_json, result_json, mfa_failures)
                VALUES (:id, :user_id, :instruction, :dag_json, :plan_json, :risk_level,
                        :requires_reauth, :status, :created_at, :expires_at, NULL,
                        :envelopes_json, :state, :state_history_json, :result_json,
                        :mfa_failures)
                """,
                payload,
            )

    def get_pending(self, action_id: str) -> dict[str, Any] | None:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def resolve_pending(self, action_id: str, status: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE pending_actions SET status = ?, resolved_at = ? WHERE id = ?",
                (status, utc_now(), action_id),
            )

    def increment_mfa_failures(self, action_id: str) -> int:
        """Persist one failed MFA attempt for exactly one pending confirmation."""
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE pending_actions SET mfa_failures = mfa_failures + 1 WHERE id = ?",
                (action_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("确认请求不存在。")
            row = conn.execute(
                "SELECT mfa_failures FROM pending_actions WHERE id = ?", (action_id,)
            ).fetchone()
        if row is None:
            raise ValueError("确认请求不存在。")
        return int(row["mfa_failures"])

    def set_pending_state(self, action_id: str, state: str, history_json: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE pending_actions SET state = ?, state_history_json = ? WHERE id = ?",
                (state, history_json, action_id),
            )

    def set_pending_envelopes(self, action_id: str, envelopes_json: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE pending_actions SET envelopes_json = ? WHERE id = ?",
                (envelopes_json, action_id),
            )

    def set_pending_result(self, action_id: str, result_json: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE pending_actions SET result_json = ? WHERE id = ?",
                (result_json, action_id),
            )

    # ---------- idempotency ----------
    def get_idempotency(self, scope: str, key: str) -> dict[str, Any] | None:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM idempotency_keys WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()
        return None if row is None else dict(row)

    def create_idempotency(self, *, scope: str, key: str, request_hash: str) -> None:
        now = utc_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO idempotency_keys
                (scope, key, request_hash, status, response_json, created_at, updated_at)
                VALUES (?, ?, ?, 'running', NULL, ?, ?)
                """,
                (scope, key, request_hash, now, now),
            )

    def complete_idempotency(self, *, scope: str, key: str, response_json: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE idempotency_keys
                SET status = 'completed', response_json = ?, updated_at = ?
                WHERE scope = ? AND key = ?
                """,
                (response_json, utc_now(), scope, key),
            )

    def delete_idempotency(self, *, scope: str, key: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM idempotency_keys WHERE scope = ? AND key = ?", (scope, key))

    # ---------- nonce one-time store ----------
    def nonce_used(self, nonce: str) -> bool:
        with self.transaction() as conn:
            row = conn.execute("SELECT 1 FROM used_nonces WHERE nonce = ?", (nonce,)).fetchone()
        return row is not None

    def claim_nonce(self, nonce: str, action_id: str) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO used_nonces (nonce, action_id, used_at) VALUES (?, ?, ?)",
                (nonce, action_id, utc_now()),
            )
            return int(cursor.rowcount) == 1

    # ---------- circuit breaker ----------
    def get_circuit_breaker(self, name: str) -> dict[str, Any] | None:
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM circuit_breaker WHERE name = ?", (name,)).fetchone()
        return None if row is None else dict(row)

    def save_circuit_breaker(
        self,
        *,
        name: str,
        failures: int,
        last_failure_at: str | None,
        opened_at: str | None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO circuit_breaker
                (name, failures, last_failure_at, opened_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    failures = excluded.failures,
                    last_failure_at = excluded.last_failure_at,
                    opened_at = excluded.opened_at,
                    updated_at = excluded.updated_at
                """,
                (name, failures, last_failure_at, opened_at, utc_now()),
            )

    def reset_circuit_breaker(self, name: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO circuit_breaker
                (name, failures, last_failure_at, opened_at, updated_at)
                VALUES (?, 0, NULL, NULL, ?)
                ON CONFLICT(name) DO UPDATE SET
                    failures = 0,
                    last_failure_at = NULL,
                    opened_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (name, utc_now()),
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
        with self.transaction() as conn:
            cursor = conn.execute(
                f"INSERT INTO audit_log ({columns}) VALUES ({placeholders})", values
            )
            return int(cursor.lastrowid)

    def last_audit_hash(self) -> str:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return "" if row is None else str(row["entry_hash"])

    def list_audit(self, limit: int = 100, run_id: str | None = None) -> list[dict[str, Any]]:
        with self.transaction() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE json_extract(result_json, '$.run_id') = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (run_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def all_audit_ascending(self) -> list[dict[str, Any]]:
        with self.transaction() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]
