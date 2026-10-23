"""Persisted consecutive-failure circuit breaker (phase-1 skeleton).

After ``threshold`` consecutive tool failures within ``window_seconds`` the
breaker opens for ``lock_seconds``. While open, every write operation is
rejected with ``status=blocked`` and a readable reason. Success resets the
counter; operators can reset it explicitly for the demo.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from ..db import Database, utc_now


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class CircuitBreaker:
    name = "tool_execution"

    def __init__(
        self,
        db: Database,
        *,
        threshold: int = 3,
        window_seconds: int = 60,
        lock_seconds: int = 60,
    ) -> None:
        self.db = db
        self.threshold = max(1, int(threshold))
        self.window_seconds = max(1, int(window_seconds))
        self.lock_seconds = max(1, int(lock_seconds))

    def status(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        row = self.db.get_circuit_breaker(self.name)
        failures = int(row["failures"]) if row else 0
        opened_at = _parse(row["opened_at"]) if row else None
        payload: dict[str, Any] = {
            "name": self.name,
            "open": False,
            "failures": failures,
            "threshold": self.threshold,
            "window_seconds": self.window_seconds,
            "lock_seconds": self.lock_seconds,
            "opened_at": row["opened_at"] if row else None,
            "retry_after_seconds": 0,
        }
        if opened_at is None:
            return payload
        elapsed = (current - opened_at).total_seconds()
        if elapsed >= self.lock_seconds:
            self.reset()
            payload["failures"] = 0
            payload["opened_at"] = None
            return payload
        payload["open"] = True
        payload["retry_after_seconds"] = max(
            1, math.ceil(self.lock_seconds - elapsed)
        )
        return payload

    def is_open(self, *, now: datetime | None = None) -> bool:
        return bool(self.status(now=now)["open"])

    def record_failure(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(UTC)
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
        return self.status(now=current)

    def record_success(self) -> None:
        self.reset()

    def record_risk_level(
        self, *, user_id: str, level: str, now: datetime | None = None
    ) -> None:
        """Observation hook for red operations (stage-2A suspicious rules)."""
        return None

    def record_injection(
        self, *, user_id: str, now: datetime | None = None
    ) -> None:
        """Observation hook for injection hits (stage-2A suspicious rules)."""
        return None

    def reset(self) -> None:
        self.db.reset_circuit_breaker(self.name)

    @staticmethod
    def reason(status: dict[str, Any]) -> str:
        return (
            f"执行熔断已触发：连续失败 {status['failures']} 次（阈值 {status['threshold']}），"
            f"写操作已拒绝，请 {status['retry_after_seconds']} 秒后重试或由运维重置。"
        )

    @staticmethod
    def now_text() -> str:
        return utc_now()


def window_start(now: datetime, window_seconds: int) -> str:
    return (now - timedelta(seconds=window_seconds)).isoformat(timespec="seconds")
