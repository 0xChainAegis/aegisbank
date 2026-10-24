"""Role introspection and audited tool-grant revocation endpoints (stage 2A).

The core API stays the only path that executes tools. This extension only adds
read-only role inspection plus a revocation action that flips the shared
permission store: after revocation the next plan is blocked by the permission
gateway before any tool runs, and the change itself is written to the audit
hash chain as ``role_revocation`` so it is immediately visible to auditors.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from ..services import CoreServices
from ..trust.authz import CAPABILITY_LABELS, AuthzError

NAME = "authz"
ROLE_HEADER = "X-Aegis-Role"
DEMO_USER = "demo-user"


def router(services: CoreServices) -> APIRouter:
    authz = services.authz
    settings = services.settings
    prefix = settings.api_prefix
    router = APIRouter()

    def resolve_role(header: str | None) -> str:
        try:
            return authz.normalize(header, default=settings.authz_default_role)
        except AuthzError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def require_capability(role: str, capability: str) -> None:
        try:
            authz.require(role, capability)
        except AuthzError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.get(f"{prefix}/authz/roles")
    def list_roles(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = resolve_role(x_aegis_role)
        require_capability(role, "audit:read")
        roles = authz.roles()
        return {"current_role": role, "count": len(roles), "roles": roles}

    @router.get(f"{prefix}/authz/me")
    def who_am_i(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        return authz.describe(resolve_role(x_aegis_role))

    @router.post(f"{prefix}/authz/revoke/{{tool_name}}")
    def revoke_tool(
        tool_name: str,
        user_id: str = Query(default=DEMO_USER, max_length=64),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = resolve_role(x_aegis_role)
        require_capability(role, "permission:manage")
        gateway = services.require_gateway()
        registry = services.require_registry()
        try:
            tool = registry.get(tool_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="工具不存在。") from exc

        with services.db.transaction():
            gateway.permissions.set_granted(user_id, tool_name, False)
            granted = gateway.permissions.is_granted(user_id, tool_name, registry)
            audit = services.require_audit()
            entry = audit.record(
                event="role_revocation",
                user_id=user_id,
                instruction=f"角色 {role} 撤回工具 {tool_name} 的授权",
                dag_path="authz",
                tool_name=tool_name,
                arguments={"tool_name": tool_name, "role": role, "user_id": user_id},
                result={
                    "granted": granted,
                    "permission": tool.metadata.permission,
                    "role": role,
                },
                confirmation_state="permission_change",
                risk_level="green",
            )
        return {
            "tool_name": tool_name,
            "title": tool.metadata.title,
            "permission": tool.metadata.permission,
            "user_id": user_id,
            "role": role,
            "granted": granted,
            "revoked": not granted,
            "effective": "blocked" if not granted else "granted",
            "audit_id": entry["id"],
        }

    @router.get(f"{prefix}/authz/audit/policy")
    def audit_policy(
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = resolve_role(x_aegis_role)
        require_capability(role, "audit:read")
        return {
            "policy": "audit_read_only",
            "read_only": True,
            "description": (
                "审计日志是只追加的 SHA-256 哈希链：任何角色都不能通过 API 修改或删除已有条目，"
                "只能读取、校验并查看哈希链完整性。"
            ),
            "writable_by_roles": [],
            "read_roles": authz.roles_with("audit:read"),
            "capability": "audit:read",
            "capability_label": CAPABILITY_LABELS["audit:read"],
            "integrity": "sha256-hash-chain",
            "endpoints": [
                f"GET {prefix}/audit",
                f"GET {prefix}/audit/verify",
                f"GET {prefix}/authz/audit/policy",
            ],
        }

    return router