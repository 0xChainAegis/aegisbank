"""Stage-2A suspicious-behaviour circuit breaker extension.

This module owns the persisted ``breaker_events`` table, swaps the scheduler's
phase-1 breaker for a configured multi-rule instance and exposes inspection /
recovery endpoints:

* ``GET  /api/trust/breaker/events``  recent breaker rule events (trust:inspect)
* ``GET  /api/trust/breaker/policy``  thresholds, windows and triggers (trust:inspect)
* ``POST /api/trust/breaker/unlock``  operator reset with audit (ops:manage)

The unlock route requires the ``operator`` role in addition to ``ops:manage``.
The stage-1 role matrix still grants ``ops:manage`` to the ``user`` role (see
``trust/authz.py``), so the extra role check is what makes a customer-initiated
unlock fail closed until the 2A wrap-up tightens that matrix.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from ..services import CoreServices
from ..trust.authz import AuthzError
from ..trust.circuit_breaker import CircuitBreaker

NAME = "breaker"
ROLE_HEADER = "X-Aegis-Role"
DEMO_USER = "demo-user"
OPERATOR_ROLE = "operator"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS breaker_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    user_id TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_breaker_events_created_at
    ON breaker_events (created_at);

CREATE INDEX IF NOT EXISTS idx_breaker_events_kind
    ON breaker_events (kind);
"""


def _breaker(services: CoreServices) -> CircuitBreaker:
    breaker = getattr(services.scheduler, "breaker", None)
    if not isinstance(breaker, CircuitBreaker):
        raise HTTPException(status_code=503, detail="执行熔断器尚未初始化。")
    return breaker


def _resolve_role(services: CoreServices, header: str | None) -> str:
    authz = services.authz
    if authz is None:
        raise HTTPException(status_code=503, detail="角色服务尚未初始化。")
    try:
        return authz.normalize(header, default=services.settings.authz_default_role)
    except AuthzError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _require(services: CoreServices, role: str, capability: str) -> None:
    authz = services.authz
    if authz is None:
        raise HTTPException(status_code=503, detail="角色服务尚未初始化。")
    try:
        authz.require(role, capability)
    except AuthzError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def activate(services: CoreServices) -> None:
    """Replace the phase-1 breaker with the configured multi-rule instance."""
    settings = services.settings
    breaker = CircuitBreaker(
        services.db,
        threshold=settings.circuit_breaker_threshold,
        window_seconds=settings.circuit_breaker_window_seconds,
        lock_seconds=settings.circuit_breaker_lock_seconds,
        suspicious_red_events=settings.suspicious_red_events,
        suspicious_injection_events=settings.suspicious_injection_events,
        suspicious_window_seconds=settings.suspicious_window_seconds,
    )
    services.scheduler.breaker = breaker
    services.extras["breaker"] = breaker


def router(services: CoreServices) -> APIRouter | None:
    api = APIRouter()
    prefix = services.settings.api_prefix.rstrip("/")

    @api.get(f"{prefix}/trust/breaker/events")
    def breaker_events(
        limit: int = Query(default=50, ge=1, le=200),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require(services, role, "trust:inspect")
        breaker = _breaker(services)
        events = breaker.recent_events(limit=limit)
        return {
            "events": events,
            "count": len(events),
            "limit": limit,
            "breaker_name": breaker.name,
        }

    @api.get(f"{prefix}/trust/breaker/policy")
    def breaker_policy(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require(services, role, "trust:inspect")
        breaker = _breaker(services)
        return {**breaker.policy(), "current": breaker.status()}

    @api.post(f"{prefix}/trust/breaker/unlock")
    def breaker_unlock(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require(services, role, "ops:manage")
        if role != OPERATOR_ROLE:
            raise HTTPException(
                status_code=403,
                detail=f"熔断解除仅允许运维（operator）角色执行，当前角色：{role}。",
            )
        breaker = _breaker(services)
        status = breaker.reset(user_id=DEMO_USER, reason="operator_unlock")
        audit_entry: dict[str, Any] | None = None
        if services.audit is not None:
            audit_entry = services.audit.record(
                event="circuit_breaker_unlock",
                user_id=DEMO_USER,
                instruction="运维解除执行熔断",
                dag_path="trust/breaker",
                tool_name="circuit_breaker",
                arguments={"role": role, "reason": "operator_unlock"},
                result={"breaker": status, "cleared": True},
                confirmation_state="ops",
                risk_level="green",
            )
        return {
            **status,
            "unlocked_by": role,
            "audit_id": audit_entry["id"] if audit_entry else None,
            "reason": "熔断已由运维解除，连续失败与可疑行为计数均已清零。",
        }

    return api