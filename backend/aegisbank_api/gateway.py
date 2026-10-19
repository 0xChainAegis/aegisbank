"""Unified pre-execution permission gateway."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .db import Database
from .domain import GatewayDecision, RiskLevel
from .registry import ToolRegistry

INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"忽略(之前|以上|前面).{0,12}(指令|规则)"),
    re.compile(r"绕过.{0,8}(权限|审批|风控|网关)"),
    re.compile(r"(system|developer)\s+prompt", re.IGNORECASE),
    re.compile(r"jailbreak|developer\s+mode", re.IGNORECASE),
)


class PermissionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def seed(self, user_id: str, registry: ToolRegistry) -> None:
        self.db.seed_permissions(user_id, registry.names())

    def ensure(self, user_id: str, registry: ToolRegistry) -> None:
        self.seed(user_id, registry)

    def is_granted(self, user_id: str, tool_name: str, registry: ToolRegistry) -> bool:
        self.ensure(user_id, registry)
        return self.db.get_permission(user_id, tool_name) is True

    def set_granted(self, user_id: str, tool_name: str, granted: bool) -> None:
        self.db.set_permission(user_id, tool_name, granted)

    def list(self, user_id: str, registry: ToolRegistry) -> list[dict[str, Any]]:
        self.ensure(user_id, registry)
        grants = {
            row["tool_name"]: bool(row["granted"])
            for row in self.db.list_permissions(user_id)
        }
        result: list[dict[str, Any]] = []
        for tool in registry.list():
            item = tool.metadata.as_dict()
            item["granted"] = grants.get(tool.metadata.name, False)
            result.append(item)
        return result


@dataclass(slots=True)
class PermissionGateway:
    registry: ToolRegistry
    permissions: PermissionStore

    def evaluate(
        self,
        *,
        user_id: str,
        tool_name: str,
        risk_level: RiskLevel,
        permission: str,
        instruction: str,
        arguments: dict[str, Any],
    ) -> GatewayDecision:
        scan_text = f"{instruction}\n{json.dumps(arguments, ensure_ascii=False)}"
        if any(pattern.search(scan_text) for pattern in INJECTION_PATTERNS):
            return GatewayDecision(
                outcome="deny",
                reason="检测到疑似 Prompt 注入或越权指令，已交由权限网关拦截。",
            )

        if not self.permissions.is_granted(user_id, tool_name, self.registry):
            return GatewayDecision(
                outcome="deny",
                reason=f"当前用户未授权工具权限 {permission}，请先在权限控制台开启。",
            )

        if risk_level is RiskLevel.GREEN:
            return GatewayDecision(outcome="allow", reason="绿色操作，满足最小权限，直接执行。")
        if risk_level is RiskLevel.YELLOW:
            return GatewayDecision(
                outcome="confirm",
                reason="黄色操作会修改账户设置，需要在 5 分钟内完成一次轻量确认。",
            )
        return GatewayDecision(
            outcome="confirm",
            reason="红色操作涉及资金变动，需要二次身份校验并明确确认。",
            requires_reauth=True,
        )
