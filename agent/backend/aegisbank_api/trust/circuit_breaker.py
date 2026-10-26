"""Persisted multi-rule circuit breaker (phase-1 failures + stage-2A rules).

Three rules share a single open state and a single cooldown clock:

* ``consecutive_failures`` - phase-1 rule: N tool failures inside a window;
* ``suspicious_red`` - stage-2A rule: N red-risk operations inside a window;
* ``suspicious_injection`` - stage-2A rule: N prompt-injection hits in a window.

While open, every write operation is rejected with ``status=blocked`` and a
reason that always contains 「执行熔断已触发」, names the trigger and explains
the recovery path. Rule events live in ``breaker_events``, created by the
``breaker`` extension's ``SCHEMA_SQL``; when that extension is disabled the
breaker falls back to an in-memory event buffer so the core trust layer keeps
working in isolated test runs.

A red operation is counted when it enters the confirmation flow. Once a tool
actually executes (success or failure) the red attempt is considered closed:
``record_failure``/``record_success`` append a ``red_cleared``/``reset`` marker
so the same operation is not double-counted by the failure rule and the
suspicious-red rule at the same time.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from ..db import Database, utc_now

TRIGGER_FAILURES = "consecutive_failures"
TRIGGER_RED = "suspicious_red"
TRIGGER_INJECTION = "suspicious_injection"

TRIGGER_LABELS: dict[str, str] = {
    TRIGGER_FAILURES: "连续失败",
    TRIGGER_RED: "短时多次红色操作",
    TRIGGER_INJECTION: "注入命中累计",
}

REASON_MARKER = "执行熔断已触发"
_MEMORY_EVENT_LIMIT = 500


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _as_utc(parsed)


def window_start(now: datetime, window_seconds: int) -> str:
    return (now - timedelta(seconds=window_seconds)).isoformat(timespec="seconds")


class CircuitBreaker:
    name = "tool_execution"

    def __init__(
        self,
        db: Database,
        *,
        threshold: int = 3,
        window_seconds: int = 60,
        lock_seconds: int = 60,
        suspicious_red_events: int = 3,
        suspicious_injection_events: int = 3,
        suspicious_window_seconds: int = 300,
    ) -> None:
        self.db = db
        self.threshold = max(1, int(threshold))
        self.window_seconds = max(1, int(window_seconds))
        self.lock_seconds = max(1, int(lock_seconds))
        self.suspicious_red_events = max(0, int(suspicious_red_events))
        self.suspicious_injection_events = max(0, int(suspicious_injection_events))
        self.suspicious_window_seconds = max(1, int(suspicious_window_seconds))
        self._open_trigger: str | None = None
        self._memory_events: list[dict[str, Any]] = []
        self._memory_seq = 0

    # ---------- event persistence ----------
    def _append_event(
        self,
        kind: str,
        user_id: str,
        detail: dict[str, Any],
        now: datetime,
    ) -> bool:
        """Persist an event; keep an in-memory copy as the extension-less fallback."""
        current = _as_utc(now)
        self._memory_seq += 1
        self._memory_events.append(
            {
                "id": self._memory_seq,
                "created_at": current.isoformat(timespec="seconds"),
                "kind": kind,
                "user_id": user_id or "system",
                "detail": dict(detail or {}),
            }
        )
        overflow = len(self._memory_events) - _MEMORY_EVENT_LIMIT
        if overflow > 0:
            del self._memory_events[:overflow]
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO breaker_events (created_at, kind, user_id, detail_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        current.isoformat(timespec="seconds"),
                        kind,
                        user_id or "system",
                        json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
                    ),
                )
        except sqlite3.OperationalError:
            # The breaker extension's SCHEMA_SQL was not applied (isolated run).
            return False
        return True

    def _event_rows_since(self, since_iso: str) -> list[dict[str, Any]]:
        try:
            with self.db.transaction() as conn:
                rows = conn.execute(
                    """
                    SELECT id, created_at, kind, user_id, detail_json
                    FROM breaker_events
                    WHERE created_at >= ?
                    ORDER BY id ASC
                    """,
                    (since_iso,),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            return [
                {
                    "id": event["id"],
                    "created_at": event["created_at"],
                    "kind": event["kind"],
                    "user_id": event["user_id"],
                    "detail_json": json.dumps(
                        event["detail"], ensure_ascii=False, sort_keys=True
                    ),
                }
                for event in self._memory_events
                if event["created_at"] >= since_iso
            ]

    def _counts(self, now: datetime) -> tuple[int, int]:
        """Return (red_events, injection_events) inside the suspicious window."""
        since = window_start(now, self.suspicious_window_seconds)
        red = 0
        injection = 0
        for row in self._event_rows_since(since):
            kind = row["kind"]
            if kind == "reset":
                red = 0
                injection = 0
            elif kind == "red_cleared":
                red = 0
            elif kind == "red_operation":
                red += 1
            elif kind == "injection_hit":
                injection += 1
        return red, injection

    def _latest_open_trigger(self) -> str | None:
        if self._open_trigger:
            return self._open_trigger
        try:
            with self.db.transaction() as conn:
                row = conn.execute(
                    """
                    SELECT kind, detail_json
                    FROM breaker_events
                    WHERE kind IN ('circuit_open', 'reset')
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.OperationalError:
            for event in reversed(self._memory_events):
                if event["kind"] == "circuit_open":
                    trigger = event["detail"].get("trigger")
                    return str(trigger) if trigger else None
                if event["kind"] == "reset":
                    return None
            return None
        if row is None or row["kind"] == "reset":
            return None
        try:
            payload = json.loads(row["detail_json"])
        except ValueError:
            return None
        trigger = payload.get("trigger")
        return str(trigger) if trigger else None

    # ---------- state transitions ----------
    def _mark_open(
        self,
        trigger: str,
        user_id: str,
        now: datetime,
        detail: dict[str, Any],
    ) -> None:
        self._open_trigger = trigger
        self._append_event(
            "circuit_open",
            user_id,
            {"trigger": trigger, "label": TRIGGER_LABELS.get(trigger, trigger), **detail},
            now,
        )

    def _save_open(
        self,
        *,
        now: datetime,
        trigger: str,
        user_id: str,
        detail: dict[str, Any],
    ) -> None:
        row = self.db.get_circuit_breaker(self.name)
        failures = int(row["failures"]) if row else 0
        last_failure_at = row["last_failure_at"] if row else None
        self.db.save_circuit_breaker(
            name=self.name,
            failures=failures,
            last_failure_at=last_failure_at,
            opened_at=now.isoformat(timespec="seconds"),
        )
        self._mark_open(trigger, user_id, now, detail)

    def _clear_red_flow(self, now: datetime, *, reason: str) -> None:
        red, _ = self._counts(now)
        if red > 0:
            self._append_event(
                "red_cleared", "system", {"reason": reason, "red_events": red}, now
            )

    def _reset_state(
        self,
        *,
        now: datetime,
        reason: str,
        user_id: str,
        record_event: bool = True,
    ) -> None:
        row = self.db.get_circuit_breaker(self.name)
        failures = int(row["failures"]) if row else 0
        opened_at = row["opened_at"] if row else None
        red, injection = self._counts(now)
        self.db.reset_circuit_breaker(self.name)
        self._open_trigger = None
        if record_event and (failures or opened_at or red or injection):
            self._append_event(
                "reset",
                user_id,
                {
                    "reason": reason,
                    "failures": failures,
                    "red_events": red,
                    "injection_events": injection,
                },
                now,
            )

    # ---------- read model ----------
    def status(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        row = self.db.get_circuit_breaker(self.name)
        failures = int(row["failures"]) if row else 0
        opened_at = _parse(row["opened_at"]) if row else None
        cooled_down = False
        if (
            opened_at is not None
            and (current - opened_at).total_seconds() >= self.lock_seconds
        ):
            self._reset_state(
                now=current, reason="lock_expired", user_id="system", record_event=True
            )
            row = None
            failures = 0
            opened_at = None
            cooled_down = True
        red, injection = self._counts(current)
        payload: dict[str, Any] = {
            "name": self.name,
            "open": opened_at is not None,
            "trigger": None,
            "trigger_label": None,
            "failures": failures,
            "threshold": self.threshold,
            "window_seconds": self.window_seconds,
            "lock_seconds": self.lock_seconds,
            "opened_at": opened_at.isoformat(timespec="seconds") if opened_at else None,
            "retry_after_seconds": 0,
            "cooled_down": cooled_down,
            "reason": "",
            "suspicious": {
                "red_events": red,
                "red_threshold": self.suspicious_red_events,
                "injection_events": injection,
                "injection_threshold": self.suspicious_injection_events,
                "window_seconds": self.suspicious_window_seconds,
                "window_start": window_start(current, self.suspicious_window_seconds),
            },
        }
        if opened_at is None:
            return payload
        trigger = self._resolve_trigger(failures, red, injection)
        payload["trigger"] = trigger
        payload["trigger_label"] = TRIGGER_LABELS.get(trigger, trigger)
        payload["retry_after_seconds"] = max(
            1, math.ceil(self.lock_seconds - (current - opened_at).total_seconds())
        )
        payload["reason"] = self.reason(payload)
        return payload

    def _resolve_trigger(self, failures: int, red: int, injection: int) -> str:
        stored = self._latest_open_trigger()
        if stored in TRIGGER_LABELS:
            return stored
        if failures >= self.threshold:
            return TRIGGER_FAILURES
        if self.suspicious_red_events > 0 and red >= self.suspicious_red_events:
            return TRIGGER_RED
        if (
            self.suspicious_injection_events > 0
            and injection >= self.suspicious_injection_events
        ):
            return TRIGGER_INJECTION
        return TRIGGER_FAILURES

    def is_open(self, *, now: datetime | None = None) -> bool:
        return bool(self.status(now=now)["open"])

    def policy(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": "fail_closed",
            "shared_open_state": True,
            "lock_seconds": self.lock_seconds,
            "reason_marker": REASON_MARKER,
            "thresholds": {
                TRIGGER_FAILURES: {
                    "label": TRIGGER_LABELS[TRIGGER_FAILURES],
                    "threshold": self.threshold,
                    "window_seconds": self.window_seconds,
                },
                TRIGGER_RED: {
                    "label": TRIGGER_LABELS[TRIGGER_RED],
                    "threshold": self.suspicious_red_events,
                    "window_seconds": self.suspicious_window_seconds,
                },
                TRIGGER_INJECTION: {
                    "label": TRIGGER_LABELS[TRIGGER_INJECTION],
                    "threshold": self.suspicious_injection_events,
                    "window_seconds": self.suspicious_window_seconds,
                },
            },
            "rules": [
                "连续失败：窗口内工具执行失败达到阈值后锁定写操作。",
                "短时多次红色操作：窗口内红色风险操作达到阈值后锁定；green/yellow 忽略。",
                "注入命中累计：窗口内 Prompt 注入或越权指令命中达到阈值后锁定。",
                "三类规则共用同一 open 状态与冷却时间，任一规则触发即整体 fail closed。",
            ],
            "recovery": {
                "auto": f"{self.lock_seconds} 秒锁定到期后自动冷却并清零计数。",
                "manual": (
                    "运营（operator）角色调用 POST /api/trust/breaker/unlock，"
                    "写入 circuit_breaker_unlock 审计。"
                ),
                "legacy": "POST /api/trust/circuit-breaker/reset（需 ops:manage 能力）。",
            },
        }

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        try:
            with self.db.transaction() as conn:
                rows = conn.execute(
                    """
                    SELECT id, created_at, kind, user_id, detail_json
                    FROM breaker_events
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            items = [dict(row) for row in rows]
        except sqlite3.OperationalError:
            items = [
                {
                    "id": event["id"],
                    "created_at": event["created_at"],
                    "kind": event["kind"],
                    "user_id": event["user_id"],
                    "detail_json": json.dumps(
                        event["detail"], ensure_ascii=False, sort_keys=True
                    ),
                }
                for event in reversed(self._memory_events[-limit:])
            ]
        events: list[dict[str, Any]] = []
        for item in items:
            try:
                detail = json.loads(item.get("detail_json") or "{}")
            except ValueError:
                detail = {"raw": item.get("detail_json")}
            events.append(
                {
                    "id": item.get("id"),
                    "created_at": item.get("created_at"),
                    "kind": item.get("kind"),
                    "user_id": item.get("user_id"),
                    "detail": detail,
                }
            )
        return events

    # ---------- recording ----------
    def record_failure(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        row = self.db.get_circuit_breaker(self.name)
        failures = int(row["failures"]) if row else 0
        last_failure = _parse(row["last_failure_at"]) if row else None
        if (
            last_failure is not None
            and (current - last_failure).total_seconds() > self.window_seconds
        ):
            failures = 0
        failures += 1
        opened_at = None
        if failures >= self.threshold:
            opened_at = current.isoformat(timespec="seconds")
        self.db.save_circuit_breaker(
            name=self.name,
            failures=failures,
            last_failure_at=current.isoformat(timespec="seconds"),
            opened_at=opened_at,
        )
        self._append_event(
            "consecutive_failure", "system", {"failures": failures}, current
        )
        self._clear_red_flow(current, reason="tool_executed")
        if opened_at is not None:
            self._mark_open(
                TRIGGER_FAILURES, "system", current, {"failures": failures}
            )
        return self.status(now=current)

    def record_success(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        self._reset_state(
            now=current, reason="tool_execution_success", user_id="system"
        )
        return self.status(now=current)

    def record_risk_level(
        self, *, user_id: str, level: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Count red operations in a sliding window (green/yellow are ignored)."""
        current = _as_utc(now or datetime.now(UTC))
        normalized = str(getattr(level, "value", level) or "").strip().lower()
        if normalized != "red":
            return self.status(now=current)
        if self.is_open(now=current):
            return self.status(now=current)
        self._append_event("red_operation", user_id, {"level": "red"}, current)
        red, _ = self._counts(current)
        if self.suspicious_red_events > 0 and red >= self.suspicious_red_events:
            self._save_open(
                now=current,
                trigger=TRIGGER_RED,
                user_id=user_id,
                detail={
                    "red_events": red,
                    "threshold": self.suspicious_red_events,
                    "window_seconds": self.suspicious_window_seconds,
                },
            )
        return self.status(now=current)

    def record_injection(
        self, *, user_id: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Accumulate injection hits in a sliding window."""
        current = _as_utc(now or datetime.now(UTC))
        if self.is_open(now=current):
            return self.status(now=current)
        self._append_event("injection_hit", user_id, {}, current)
        _, injection = self._counts(current)
        if (
            self.suspicious_injection_events > 0
            and injection >= self.suspicious_injection_events
        ):
            self._save_open(
                now=current,
                trigger=TRIGGER_INJECTION,
                user_id=user_id,
                detail={
                    "injection_events": injection,
                    "threshold": self.suspicious_injection_events,
                    "window_seconds": self.suspicious_window_seconds,
                },
            )
        return self.status(now=current)

    def reset(
        self,
        *,
        user_id: str = "system",
        reason: str = "manual_reset",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _as_utc(now or datetime.now(UTC))
        self._reset_state(
            now=current, reason=reason, user_id=user_id, record_event=True
        )
        return self.status(now=current)

    # ---------- presentation ----------
    @staticmethod
    def reason(status: dict[str, Any]) -> str:
        suspicious = status.get("suspicious") or {}
        trigger = status.get("trigger") or TRIGGER_FAILURES
        retry = int(status.get("retry_after_seconds") or 0)
        recovery = (
            f"等待 {retry} 秒冷却结束后自动恢复，或由运维角色调用 "
            "POST /api/trust/breaker/unlock 手工解除。"
        )
        if trigger == TRIGGER_RED:
            source = (
                f"最近 {suspicious.get('window_seconds', 0)} 秒内红色操作 "
                f"{suspicious.get('red_events', 0)} 次"
                f"（阈值 {suspicious.get('red_threshold', 0)}）"
            )
            return (
                f"{REASON_MARKER}：检测到可疑行为——{source}，写操作已拒绝。"
                f"触发来源：短时多次红色操作规则；恢复方式：{recovery}"
            )
        if trigger == TRIGGER_INJECTION:
            source = (
                f"最近 {suspicious.get('window_seconds', 0)} 秒内注入命中 "
                f"{suspicious.get('injection_events', 0)} 次"
                f"（阈值 {suspicious.get('injection_threshold', 0)}）"
            )
            return (
                f"{REASON_MARKER}：检测到可疑行为——{source}，写操作已拒绝。"
                f"触发来源：注入命中累计规则；恢复方式：{recovery}"
            )
        return (
            f"{REASON_MARKER}：连续失败 {status['failures']} 次"
            f"（阈值 {status['threshold']}，窗口 {status['window_seconds']} 秒），"
            f"写操作已拒绝。触发来源：连续失败规则；恢复方式：{recovery}"
        )

    @staticmethod
    def now_text() -> str:
        return utc_now()