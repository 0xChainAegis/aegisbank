"""Role matrix and authorization checks for the multi-role demo (stage 2A).

Three demo roles are supported: ``user`` (the customer who owns the data),
``operator`` (ops console: breaker reset, trust inspection) and ``auditor``
(read-only audit review). Executing banking tools is a user-only capability, so
an operator or auditor role reaching a write endpoint is rejected by the
gateway before any tool runs.

阶段 2A 的收尾工作会进一步收紧矩阵（例如把 ``ops:manage`` 从 ``user`` 移除），
当前矩阵保持向后兼容，避免既有演示与测试失效。
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
        "ops:manage",
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

CAPABILITY_LABELS: dict[str, str] = {
    "tool:execute": "发起银行工具执行",
    "permission:manage": "管理工具授权",
    "audit:read": "查看操作审计",
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

    def roles(self) -> list[dict[str, Any]]:
        return [
            {
                "role": role,
                "capabilities": sorted(capabilities),
                "capability_labels": {
                    capability: CAPABILITY_LABELS.get(capability, capability)
                    for capability in sorted(capabilities)
                },
            }
            for role, capabilities in sorted(self.matrix.items())
        ]
