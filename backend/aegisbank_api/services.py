"""Runtime service container shared by core wiring and scenario modules.

``create_app`` builds the container progressively: persistence is ready
first, the tool registry is filled next, and authorization/audit services are
attached once constructed. Scenario tool nodes therefore receive the container
itself and only resolve authorization pieces when a tool actually runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .audit import AuditService
from .banking.repository import BankingRepository
from .config import Settings
from .db import Database
from .gateway import PermissionGateway
from .registry import ToolRegistry


@dataclass(slots=True)
class CoreServices:
    """Dependencies every scenario module may use; fields fill in over time."""

    db: Database
    repository: BankingRepository
    settings: Settings
    registry: ToolRegistry | None = None
    gateway: PermissionGateway | None = None
    audit: AuditService | None = None
    scheduler: Any = None
    executor: Any = None
    mfa: Any = None
    authz: Any = None
    compensation: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    def require_registry(self) -> ToolRegistry:
        if self.registry is None:
            raise RuntimeError("工具注册表尚未初始化，无法注册场景工具。")
        return self.registry

    def require_gateway(self) -> PermissionGateway:
        if self.gateway is None:
            raise RuntimeError("权限网关尚未初始化，禁止绕过网关执行。")
        return self.gateway

    def require_audit(self) -> AuditService:
        if self.audit is None:
            raise RuntimeError("审计服务尚未初始化，禁止执行无审计操作。")
        return self.audit
