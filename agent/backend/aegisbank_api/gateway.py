"""Unified pre-execution permission gateway."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .db import Database
from .domain import GatewayDecision, RiskLevel, ToolMetadata
from .registry import ToolRegistry
from .trust.authz import AuthzService

INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"忽略(之前|以上|前面).{0,12}(指令|规则)"),
    re.compile(r"绕过.{0,8}(权限|审批|风控|网关)"),
    re.compile(r"(system|developer)\s+prompt", re.IGNORECASE),
    re.compile(r"jailbreak|developer\s+mode", re.IGNORECASE),
)


def scan_text(instruction: str, arguments: dict[str, Any] | None = None) -> str:
    return f"{instruction}\n{json.dumps(arguments or {}, ensure_ascii=False)}"


def detect_injection(text: str) -> list[str]:
    """Return the matched injection rule sources for a piece of text."""
    return [pattern.pattern for pattern in INJECTION_PATTERNS if pattern.search(text)]


def scan_injection(instruction: str, arguments: dict[str, Any] | None = None) -> list[str]:
    """Scan instruction *and* arguments before a plan is even proposed."""
    return detect_injection(scan_text(instruction, arguments))


# Tools that are implementation details of compensation, scheduled execution or
# the demo harness. They are deliberately not ordinary-user capabilities.
DEMO_INTERNAL_TOOLS = frozenset(
    (
        "cancel_virtual_card_application",
        "demo_charge_fee",
        "demo_fail_step",
        "demo_irreversible_marker",
        "demo_reserve_funds",
        "execute_gift_order",
        "reactivate_subscription",
        "restore_card_limit",
        "restore_repayment_date",
        "restore_transaction_limit",
        "restore_wealth_risk",
        "reverse_demo_charge",
        "reverse_demo_reserve",
        "reverse_purchase_wealth",
        "reverse_transfer",
    )
)

# Minimum permissions: demo users receive only user-operable tools. Internal
# compensation tools are reachable only through an internal execution purpose,
# never through an implicit user grant.
DEMO_PREGRANTED_TOOLS = frozenset(
    (
        "add_contact",
        "adjust_card_limit",
        "adjust_repayment_date",
        "apply_virtual_card",
        "assess_wealth_risk",
        "bill_report",
        "cancel_scheduled_task",
        "cancel_subscription",
        "detect_bill_anomalies",
        "identify_subscription_charges",
        "issue_virtual_card",
        "list_contacts",
        "list_renewal_reminders",
        "list_scheduled_tasks",
        "list_subscriptions",
        "list_wealth_products",
        "lock_budget_funds",
        "purchase_wealth",
        "query_balance",
        "query_bill",
        "query_recent_transfer",
        "query_contact_birthday",
        "query_wealth_holdings",
        "redeem_wealth",
        "report_card_lost",
        "reset_card_password",
        "run_due_tasks",
        "schedule_cake_order",
        "schedule_flower_order",
        "schedule_transfer",
        "set_transaction_limit",
        "transfer",
        "transfer_to_contact",
        "unlock_budget_funds",
        "unlock_card",
        "unlock_transaction_limit",
    )
)


def is_internal_tool(tool_name: str, manifest: ToolMetadata) -> bool:
    """Return whether a tool is internal-only for user-facing permission UX."""
    return bool(manifest.internal_only or tool_name in DEMO_INTERNAL_TOOLS)


class PermissionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def seed(self, user_id: str, registry: ToolRegistry) -> None:
        if user_id != "demo-user":
            return
        user_facing = sorted(
            tool.metadata.name
            for tool in registry.list()
            if tool.metadata.name in DEMO_PREGRANTED_TOOLS
            and not is_internal_tool(tool.metadata.name, tool.metadata)
        )
        internal_tools = sorted(
            tool.metadata.name
            for tool in registry.list()
            if is_internal_tool(tool.metadata.name, tool.metadata)
        )
        with self.db.transaction():
            self.db.seed_permissions(user_id, user_facing)
            # Older builds silently granted all 50 tools. Remove positive
            # internal grants while preserving an explicit revocation row.
            self.db.remove_granted_permissions(user_id, internal_tools)

    def ensure(self, user_id: str, registry: ToolRegistry) -> None:
        # Reading permissions never grants new capabilities.
        return None

    def permission_state(
        self, user_id: str, tool_name: str, registry: ToolRegistry
    ) -> bool | None:
        self.ensure(user_id, registry)
        return self.db.get_permission(user_id, tool_name)

    def is_granted(self, user_id: str, tool_name: str, registry: ToolRegistry) -> bool:
        return self.permission_state(user_id, tool_name, registry) is True

    def set_granted(self, user_id: str, tool_name: str, granted: bool) -> None:
        self.db.set_permission(user_id, tool_name, granted)

    def list(self, user_id: str, registry: ToolRegistry) -> list[dict[str, Any]]:
        self.ensure(user_id, registry)
        grants = {
            row["tool_name"]: bool(row["granted"]) for row in self.db.list_permissions(user_id)
        }
        result: list[dict[str, Any]] = []
        for tool in registry.list():
            if is_internal_tool(tool.metadata.name, tool.metadata):
                continue
            item = tool.metadata.as_dict()
            item["granted"] = grants.get(tool.metadata.name, False)
            result.append(item)
        return result


@dataclass(slots=True)
class PermissionGateway:
    registry: ToolRegistry
    permissions: PermissionStore
    authz: AuthzService | None = None

    def evaluate(
        self,
        *,
        user_id: str,
        tool_name: str,
        risk_level: RiskLevel,
        permission: str,
        instruction: str,
        arguments: dict[str, Any],
        role: str = "user",
        purpose: str = "execution",
    ) -> GatewayDecision:
        manifest = self.registry.get(tool_name).metadata
        internal_tool = is_internal_tool(manifest.name, manifest)
        if internal_tool and purpose not in manifest.allowed_purposes:
            return GatewayDecision(
                outcome="deny",
                reason="该工具仅供已记录动作的内部补偿或调度执行使用。",
            )
        if scan_injection(instruction, arguments):
            return GatewayDecision(
                outcome="deny",
                reason="检测到疑似 Prompt 注入或越权指令，已交由权限网关拦截。",
            )

        if self.authz is not None and not self.authz.allowed(role, "tool:execute"):
            return GatewayDecision(
                outcome="deny",
                reason=f"当前角色 {role} 无工具执行权限，仅普通用户可发起银行操作。",
            )

        if internal_tool:
            state = self.permissions.permission_state(user_id, tool_name, self.registry)
            if state is False:
                return GatewayDecision(
                    outcome="deny",
                    reason=f"内部工具权限已被显式撤回，当前用户未授权工具权限 {permission}。",
                )
        elif not self.permissions.is_granted(user_id, tool_name, self.registry):
            return GatewayDecision(
                outcome="deny",
                reason=f"当前用户未授权工具权限 {permission}，请先在权限控制台开启。",
            )

        if risk_level is RiskLevel.GREEN:
            return GatewayDecision(outcome="allow", reason="绿色操作，满足最小权限，直接执行。")
        if risk_level is RiskLevel.YELLOW:
            return GatewayDecision(
                outcome="confirm",
                reason="黄色操作涉及资金变动或账户设置，需要在 5 分钟内完成一次轻量确认。",
            )
        return GatewayDecision(
            outcome="confirm",
            reason="红色操作涉及资金变动，需要二次身份校验并明确确认。",
            requires_reauth=True,
        )
