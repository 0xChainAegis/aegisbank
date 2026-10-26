"""Role matrix and authorization checks for the multi-role demo (stage 2A).

Three demo roles are supported: ``user`` (the customer who owns the data),
``operator`` (ops console: breaker reset, trust inspection) and ``auditor``
(read-only audit review). Executing banking tools is a user-only capability, so
an operator or auditor role reaching a write endpoint is rejected by the
gateway before any tool runs.

Stage 2A hardening: ``ops:manage`` has been removed from ``user`` -- a customer
may manage tool grants but must never reset the circuit breaker. ``operator``
keeps ``permission:manage`` for emergency revocation but has no
``tool:execute``. This matrix is the single source of truth for both the API
role header (``X-Aegis-Role``) and the permission gateway.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class Role(StrEnum):
    USER = "user"
    OPERATOR = "operator"
    AUDITOR = "auditor"


class AuthzError(ValueError):
    """Raised when the current role is not allowed to perform an action."""

    def __init__(self, role: str, capability: str) -> None:
        super().__init__(f"角色 {role} 不具备能力 {capability} 的执行权限。")
        self.role = role
        self.capability = capability


DEFAULT_MATRIX: dict[str, set[str]] = {
    Role.USER.value: {
        "tool:execute",
        "permission:manage",
        "audit:read",
        "trust:inspect",
    },
    Role.OPERATOR.value: {
        "ops:manage",
        "trust:inspect",
        "audit:read",
        "permission:manage",
    },
    Role.AUDITOR.value: {
        "audit:read",
        "trust:inspect",
    },
}

ROLE_LABELS: dict[str, str] = {
    Role.USER.value: "普通用户（账户持有人，唯一可发起银行操作的角色）",
    Role.OPERATOR.value: "运维操作员（熔断重置与信任运维，不执行银行操作）",
    Role.AUDITOR.value: "审计员（只读审计与信任核查）",
}

CAPABILITY_LABELS: dict[str, str] = {
    "tool:execute": "发起银行工具执行",
    "permission:manage": "管理工具授权（授予/撤回）",
    "audit:read": "查看操作审计与哈希链校验",
    "ops:manage": "运维操作（熔断重置、锁库）",
    "trust:inspect": "查看信任状态与任务对账",
}


class AuthzService:
    """Resolve roles and answer capability questions."""

    def __init__(self, matrix: dict[str, set[str]] | None = None) -> None:
        self.matrix: dict[str, set[str]] = {
            role: set(capabilities)
            for role, capabilities in (matrix or DEFAULT_MATRIX).items()
        }

    def is_known(self, role: str | None) -> bool:
        return bool(role) and role in self.matrix

    def normalize(self, role: str | None, *, default: str = "user") -> str:
        candidate = (role or default).strip().lower()
        if not self.is_known(candidate):
            raise AuthzError(candidate or "<empty>", "role:resolve")
        return candidate

    def capabilities(self, role: str) -> list[str]:
        return sorted(self.matrix.get(role, set()))

    def allowed(self, role: str, capability: str) -> bool:
        return capability in self.matrix.get(role, set())

    def require(self, role: str, capability: str) -> None:
        if not self.allowed(role, capability):
            raise AuthzError(role, capability)

    def roles_with(self, capability: str) -> list[str]:
        """Return the roles holding *capability*, sorted for stable output."""
        return [role for role in sorted(self.matrix) if self.allowed(role, capability)]

    def label(self, role: str) -> str:
        return ROLE_LABELS.get(role, role)

    def describe(self, role: str) -> dict[str, Any]:
        capabilities = self.capabilities(role)
        return {
            "role": role,
            "label": self.label(role),
            "capabilities": capabilities,
            "capability_labels": {
                capability: CAPABILITY_LABELS.get(capability, capability)
                for capability in capabilities
            },
        }

    def roles(self) -> list[dict[str, Any]]:
        return [self.describe(role) for role in sorted(self.matrix)]