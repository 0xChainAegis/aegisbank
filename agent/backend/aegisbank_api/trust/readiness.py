"""Readiness probes and fail-closed gating for write operations.

``GET /api/health/ready`` reports every critical dependency. When the service is
not ready, write endpoints must reject the request with HTTP 503 instead of
pretending that the operation succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..audit import AuditService
from ..banking.repository import BankingRepository
from ..db import Database
from ..planning.contracts import Planner


class NotReadyError(RuntimeError):
    """Raised when a write operation is attempted while the app is not ready."""

    def __init__(
        self,
        message: str,
        *,
        status: str = "not_ready",
        components: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.components = components or {}


@dataclass(slots=True)
class ComponentHealth:
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail}


CRITICAL_COMPONENTS = ("sqlite", "audit_chain", "mock_bank_seed")


class ReadinessService:
    def __init__(
        self,
        *,
        db: Database,
        audit: AuditService,
        repository: BankingRepository,
        planner: Planner,
        user_id: str = "demo-user",
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.audit = audit
        self.repository = repository
        self.planner = planner
        self.user_id = user_id
        self.overrides = dict(overrides or {})

    def _check_sqlite(self) -> ComponentHealth:
        try:
            with self.db.transaction() as conn:
                conn.execute("SELECT 1").fetchone()
            return ComponentHealth(True, "SQLite 可读写")
        except Exception as exc:  # noqa: BLE001 - readiness must never raise
            return ComponentHealth(False, f"SQLite 不可用：{exc}")

    def _check_audit_chain(self) -> ComponentHealth:
        try:
            result = self.audit.verify()
        except Exception as exc:  # noqa: BLE001
            return ComponentHealth(False, f"审计链校验失败：{exc}")
        if not result.get("valid"):
            return ComponentHealth(
                False, f"审计链断裂于第 {result.get('broken_at')} 条：{result.get('reason')}"
            )
        return ComponentHealth(True, f"哈希链校验通过，共 {result.get('checked', 0)} 条")

    def _check_mock_bank_seed(self) -> ComponentHealth:
        try:
            overview = self.repository.overview(self.user_id)
        except Exception as exc:  # noqa: BLE001
            return ComponentHealth(False, f"模拟银行数据不可用：{exc}")
        if not overview.accounts or not overview.cards:
            return ComponentHealth(False, "模拟银行种子数据缺失")
        return ComponentHealth(
            True,
            f"模拟银行种子就绪：{len(overview.accounts)} 个账户 / {len(overview.cards)} 张卡",
        )

    def _check_planner(self) -> ComponentHealth:
        if self.planner is None or not callable(getattr(self.planner, "plan", None)):
            return ComponentHealth(False, "Planner 未初始化")
        mode = str(getattr(self.planner, "name", "unknown"))
        return ComponentHealth(True, f"Planner 可用：{mode}")

    def check(self) -> dict[str, Any]:
        components: dict[str, dict[str, Any]] = {
            "sqlite": self._check_sqlite().as_dict(),
            "audit_chain": self._check_audit_chain().as_dict(),
            "mock_bank_seed": self._check_mock_bank_seed().as_dict(),
            "planner": self._check_planner().as_dict(),
        }
        for name, override in self.overrides.items():
            if name not in components or override is True:
                continue
            detail = override if isinstance(override, str) else f"依赖注入故障：{name} 不可用"
            components[name] = {"ok": False, "detail": detail}
        if any(not components[name]["ok"] for name in CRITICAL_COMPONENTS):
            status = "not_ready"
        elif not components["planner"]["ok"]:
            status = "degraded"
        else:
            status = "ready"
        return {"status": status, "components": components}

    def require_ready(self) -> dict[str, Any]:
        snapshot = self.check()
        if snapshot["status"] != "ready":
            reasons = [
                f"{name}: {item.get('detail') or '不可用'}"
                for name, item in snapshot["components"].items()
                if not item["ok"]
            ]
            raise NotReadyError(
                "系统未就绪，写操作已按 fail closed 拒绝（" + "；".join(reasons) + "）。",
                status=snapshot["status"],
                components=snapshot["components"],
            )
        return snapshot
