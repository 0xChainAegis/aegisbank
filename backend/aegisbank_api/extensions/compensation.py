"""Compensation specs, reverse tools and step-level recovery endpoints (stage 2A).

This extension is the *policy and tooling* half of step-level rollback:

* it registers which tools are reversible, irreversible or read-only, and which
  inverse tool performs the compensation;
* it contributes the inverse ``BaseTool`` nodes (they declare risk level and
  minimum permission like every other tool and are executed through the shared
  gateway/executor/audit path);
* it exposes pause / resume / rollback / journal endpoints plus a controllable
  failure demo DAG that goes through ``DagScheduler`` public methods.

No endpoint here bypasses the permission gateway, the confirmation flow or the
SHA-256 audit chain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..banking.repository import to_cents
from ..compensation import CompensationSpec
from ..domain import ExecutionContext, PlanNode, RiskLevel, ToolMetadata, ToolResult
from ..registry import BaseTool
from ..scheduler import IntentError
from ..services import CoreServices
from ..trust.authz import AuthzError

NAME = "compensation"
DEMO_USER = "demo-user"
ROLE_HEADER = "X-Aegis-Role"
DEMO_PERMISSION = "compensation:demo"
DEMO_MODES = ("reversible", "irreversible", "compensation_failure", "success")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS compensation_demo_ledger (
    entry_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount_cents INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'posted',
    reverses_entry_id TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compensation_reversals (
    original_kind TEXT NOT NULL,
    original_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reversal_id TEXT NOT NULL,
    PRIMARY KEY (original_kind, original_id)
);

CREATE INDEX IF NOT EXISTS idx_compensation_demo_ledger_action
    ON compensation_demo_ledger(action_id, created_at);
"""

DEMO_NOTE = (
    "演示扩展：演示 DAG 只写入本地模拟账本，不触碰真实资金；"
    "补偿仍经统一权限网关、执行器与审计哈希链。"
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _result_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _reserve_reversal(conn, *, kind: str, original_id: str, user_id: str, reversal_id: str):
    if conn.execute(
        "SELECT 1 FROM compensation_reversals WHERE original_kind=? AND original_id=?",
        (kind, original_id),
    ).fetchone():
        raise ValueError("原交易已冲正，禁止再次返款。")
    conn.execute(
        "INSERT INTO compensation_reversals (original_kind,original_id,user_id,reversal_id) "
        "VALUES (?,?,?,?)",
        (kind, original_id, user_id, reversal_id),
    )


class ReverseArgs(BaseModel):
    """Uniform payload handed to every inverse tool by the scheduler."""

    original_arguments: dict[str, Any] = Field(default_factory=dict)
    original_result: dict[str, Any] = Field(default_factory=dict)
    compensating_node_id: str | None = None


class DemoReserveArgs(BaseModel):
    amount_cny: float = Field(default=199.0, gt=0, le=5000)
    pause_after: bool = False


class DemoChargeArgs(BaseModel):
    amount_cny: float = Field(default=59.0, gt=0, le=5000)
    fail_compensation: bool = False


class DemoMarkerArgs(BaseModel):
    note: str = Field(default="演示不可撤销标记", max_length=200)


class DemoFailArgs(BaseModel):
    message: str = Field(default="演示可控失败", max_length=200)


class DemoRunRequest(BaseModel):
    mode: str = Field(default="reversible", max_length=32)
    pause_after_first: bool = False
    user_id: str = Field(default=DEMO_USER, max_length=64)


# ---------------------------------------------------------------------------
# Compensation specs: one entry for every tool with side effects
# ---------------------------------------------------------------------------


def build_specs() -> list[CompensationSpec]:
    return [
        # ---- reversible core tools ----
        CompensationSpec(
            tool_name="transfer",
            compensation_tool="reverse_transfer",
            description="按原路径冲正模拟转账，恢复付款账户余额。",
        ),
        CompensationSpec(
            tool_name="adjust_repayment_date",
            compensation_tool="restore_repayment_date",
            description="恢复调整前的信用卡还款日。",
        ),
        CompensationSpec(
            tool_name="adjust_card_limit",
            compensation_tool="restore_card_limit",
            description="恢复调整前的信用卡额度。",
        ),
        CompensationSpec(
            tool_name="cancel_subscription",
            compensation_tool="reactivate_subscription",
            description="把已取消的订阅恢复为 active 状态。",
        ),
        CompensationSpec(
            tool_name="unlock_transaction_limit",
            compensation_tool="restore_transaction_limit",
            description="恢复解锁前的信用卡交易限额。",
        ),
        # ---- reversible scenario tools ----
        CompensationSpec(
            tool_name="transfer_to_contact",
            compensation_tool="reverse_transfer",
            description="联系人转账同样按原路径冲正。",
        ),
        CompensationSpec(
            tool_name="apply_virtual_card",
            compensation_tool="cancel_virtual_card_application",
            description="把仍处于 applying 的虚拟卡申请单标记为 rejected。",
        ),
        CompensationSpec(
            tool_name="lock_budget_funds",
            compensation_tool="unlock_budget_funds",
            description="解锁预算目标并退回尚未使用的锁定金额。",
        ),
        CompensationSpec(
            tool_name="schedule_flower_order",
            compensation_tool="cancel_scheduled_task",
            description="取消尚未执行的鲜花订购计划。",
        ),
        CompensationSpec(
            tool_name="schedule_cake_order",
            compensation_tool="cancel_scheduled_task",
            description="取消尚未执行的蛋糕订购计划。",
        ),
        CompensationSpec(
            tool_name="schedule_transfer",
            compensation_tool="cancel_scheduled_task",
            description="取消尚未执行的定时转账任务。",
        ),
        CompensationSpec(
            tool_name="purchase_wealth",
            compensation_tool="reverse_purchase_wealth",
            description="撤销刚完成的模拟理财申购：恢复持仓与扣款账户余额。",
        ),
        CompensationSpec(
            tool_name="assess_wealth_risk",
            compensation_tool="restore_wealth_risk",
            description="恢复风险测评前的风险偏好记录。",
        ),
        # ---- irreversible tools ----
        CompensationSpec(
            tool_name="report_card_lost",
            compensation_tool="",
            description="卡片挂失是账户安全终态，不能自动撤销，需人工与银行核实。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="reset_card_password",
            compensation_tool="",
            description="安全凭证变更不可自动回退，需人工重新核身。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="unlock_card",
            compensation_tool="",
            description="解挂属于安全状态变更，自动重新挂失会放大风险。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="set_transaction_limit",
            compensation_tool="",
            description="缺少变更前限额快照，无法精确回退，需人工指定目标限额。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="issue_virtual_card",
            compensation_tool="",
            description="已发卡会写入卡片清单，自动删卡不可逆，需人工处理。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="add_contact",
            compensation_tool="",
            description="联系人属于 KYC 记录，没有删除工具，不可自动回退。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="cancel_scheduled_task",
            compensation_tool="",
            description="取消后的定时任务没有恢复接口，不可自动回退。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="unlock_budget_funds",
            compensation_tool="",
            description="预算解锁是补偿动作本身，重新锁定会改变资金安排，不可自动回退。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="redeem_wealth",
            compensation_tool="",
            description="赎回是资金退出动作，不能自动反向申购。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="run_due_tasks",
            compensation_tool="",
            description="到期任务已实际执行扣款，不可自动回退。",
            irreversible=True,
        ),
        # ---- demo sandbox tools ----
        CompensationSpec(
            tool_name="demo_reserve_funds",
            compensation_tool="reverse_demo_reserve",
            description="演示：释放预留资金并写入反向账本记录。",
        ),
        CompensationSpec(
            tool_name="demo_charge_fee",
            compensation_tool="reverse_demo_charge",
            description="演示：撤销手续费扣减并写入反向账本记录。",
        ),
        CompensationSpec(
            tool_name="demo_irreversible_marker",
            compensation_tool="",
            description="演示：该步骤声明为不可撤销，用于验证回滚阻断。",
            irreversible=True,
        ),
        CompensationSpec(
            tool_name="demo_fail_step",
            compensation_tool="",
            description="演示：可控失败节点不会成功执行，声明为不可撤销。",
            irreversible=True,
        ),
    ]


# ---------------------------------------------------------------------------
# Inverse tools (real bank core)
# ---------------------------------------------------------------------------


class ReverseTransferTool(BaseTool):
    metadata = ToolMetadata(
        name="reverse_transfer",
        title="转账冲正",
        description=(
            "补偿工具：按原路径冲正已完成的模拟转账，恢复付款账户余额，"
            "并写入 transfer_reversal 交易；需要转账执行权限。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="transfer:execute",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        nested = data.get("transfer")
        if isinstance(nested, dict):
            data = {**data, **nested}
        original = args.original_arguments or {}
        from_account = str(original.get("from_account") or data.get("from_account") or "")
        to_account = str(original.get("to_account") or data.get("to_account") or "")
        amount_cny = original.get("amount_cny")
        if amount_cny is None:
            amount_cny = data.get("amount_cny")
        if not from_account or not to_account or amount_cny is None:
            raise ValueError("冲正失败：缺少原始转账的付款账户、收款账户或金额。")
        amount_cents = to_cents(float(amount_cny))
        if amount_cents <= 0:
            raise ValueError("冲正失败：冲正金额必须大于 0。")
        if from_account == to_account:
            raise ValueError("冲正失败：付款账户与收款账户相同。")
        now = _iso_now()
        reversal_id = f"RV-{uuid4().hex[:12].upper()}"
        with self.services.db.transaction() as conn:
            original_id = str(data.get("transaction_id") or "")
            transaction = conn.execute(
                "SELECT * FROM bank_transactions WHERE transaction_id=? AND user_id=?",
                (original_id, context.user_id),
            ).fetchone()
            if (
                transaction is None
                or transaction["category"] != "transfer"
                or transaction["account_id"] != from_account
                or transaction["merchant"] != to_account
                or int(transaction["amount_cents"]) != -amount_cents
            ):
                raise ValueError("冲正失败：原交易证据与账本不一致。")
            _reserve_reversal(
                conn,
                kind="transfer",
                original_id=original_id,
                user_id=context.user_id,
                reversal_id=reversal_id,
            )
            target = conn.execute(
                "SELECT 1 FROM bank_accounts WHERE user_id=? AND account_id=?",
                (context.user_id, to_account),
            ).fetchone()
            if target is not None:
                debited = conn.execute(
                    "UPDATE bank_accounts SET balance_cents=balance_cents-?, "
                    "available_cents=available_cents-? WHERE user_id=? AND account_id=? "
                    "AND balance_cents>=? AND available_cents>=?",
                    (
                        amount_cents,
                        amount_cents,
                        context.user_id,
                        to_account,
                        amount_cents,
                        amount_cents,
                    ),
                ).rowcount
                if debited != 1:
                    raise ValueError("收款账户资金已被使用或锁定，不能自动冲正，需人工对账。")
            credited = conn.execute(
                "UPDATE bank_accounts SET balance_cents = balance_cents + ?, "
                "available_cents = available_cents + ? WHERE user_id = ? AND account_id = ?",
                (amount_cents, amount_cents, context.user_id, from_account),
            ).rowcount
            if not credited:
                raise ValueError(f"冲正失败：付款账户不存在或不属于当前用户：{from_account}")
            conn.execute(
                """
                INSERT INTO bank_transactions
                (transaction_id, user_id, account_id, card_id, merchant, category,
                 amount_cents, occurred_at, status, note)
                VALUES (?, ?, ?, NULL, ?, 'transfer_reversal', ?, ?, 'posted', ?)
                """,
                (
                    reversal_id,
                    context.user_id,
                    from_account,
                    to_account,
                    amount_cents,
                    now,
                    f"冲正原交易 {data.get('transaction_id') or '-'}",
                ),
            )
        output = {
            "reversal_transaction_id": reversal_id,
            "source_transaction_id": data.get("transaction_id"),
            "from_account": to_account,
            "to_account": from_account,
            "amount_cny": amount_cents / 100.0,
            "status": "reversed",
            "simulated": True,
        }
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"已按原路径冲正 {output['amount_cny']:.2f} 元（演示数据）。",
            data=output,
        )


class RestoreRepaymentDateTool(BaseTool):
    metadata = ToolMetadata(
        name="restore_repayment_date",
        title="恢复还款日",
        description="补偿工具：把信用卡还款日恢复到调整前的取值。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        original = args.original_arguments or {}
        card_id = str(original.get("card_id") or data.get("card_id") or "")
        previous_day = data.get("previous_day")
        if not card_id or previous_day is None:
            raise ValueError("恢复还款日失败：缺少卡片或调整前的还款日。")
        result = self.services.repository.adjust_repayment_date(
            context.user_id, card_id, int(previous_day)
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"还款日已恢复到每月 {int(previous_day)} 日（演示数据）。",
            data={**result, "restored": True},
        )


class RestoreCardLimitTool(BaseTool):
    metadata = ToolMetadata(
        name="restore_card_limit",
        title="恢复卡片额度",
        description="补偿工具：把信用卡额度恢复到调整前的取值。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        original = args.original_arguments or {}
        card_id = str(original.get("card_id") or data.get("card_id") or "")
        previous_limit = data.get("previous_limit_cny")
        if not card_id or previous_limit is None:
            raise ValueError("恢复卡片额度失败：缺少卡片或调整前的额度。")
        result = self.services.repository.adjust_card_limit(
            context.user_id, card_id, float(previous_limit)
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"卡片额度已恢复到 {float(previous_limit):.2f} 元（演示数据）。",
            data={**result, "restored": True},
        )


class RestoreTransactionLimitTool(BaseTool):
    metadata = ToolMetadata(
        name="restore_transaction_limit",
        title="恢复交易限额",
        description="补偿工具：把信用卡交易限额恢复到解锁前的取值。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        original = args.original_arguments or {}
        card_id = str(original.get("card_id") or data.get("card_id") or "")
        previous_limit = data.get("previous_transaction_limit_cny")
        if not card_id or previous_limit is None:
            raise ValueError("恢复交易限额失败：缺少卡片或解锁前的限额快照。")
        result = self.services.repository.set_transaction_limit(
            context.user_id, card_id, float(previous_limit)
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"交易限额已恢复到 {float(previous_limit):.2f} 元（演示数据）。",
            data={**result, "restored": True},
        )


class ReactivateSubscriptionTool(BaseTool):
    metadata = ToolMetadata(
        name="reactivate_subscription",
        title="恢复订阅",
        description="补偿工具：把刚取消的订阅恢复为 active 状态。",
        risk_level=RiskLevel.YELLOW,
        permission="subscription:manage",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        original = args.original_arguments or {}
        subscription_id = str(original.get("subscription_id") or data.get("subscription_id") or "")
        if not subscription_id:
            raise ValueError("恢复订阅失败：缺少订阅编号。")
        with self.services.db.transaction() as conn:
            row = conn.execute(
                "SELECT status FROM bank_subscriptions WHERE user_id = ? AND subscription_id = ?",
                (context.user_id, subscription_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"恢复订阅失败：订阅不存在：{subscription_id}")
            if str(row["status"]) != "active":
                conn.execute(
                    "UPDATE bank_subscriptions SET status = 'active' "
                    "WHERE user_id = ? AND subscription_id = ?",
                    (context.user_id, subscription_id),
                )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"订阅 {subscription_id} 已恢复为 active（演示数据）。",
            data={
                "subscription_id": subscription_id,
                "status": "active",
                "restored": True,
                "simulated": True,
            },
        )


class CancelVirtualCardApplicationTool(BaseTool):
    metadata = ToolMetadata(
        name="cancel_virtual_card_application",
        title="撤销虚拟卡申请",
        description="补偿工具：把仍处于 applying 的虚拟卡申请标记为 rejected。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        original = args.original_arguments or {}
        application_id = str(original.get("application_id") or data.get("application_id") or "")
        if not application_id:
            raise ValueError("撤销虚拟卡申请失败：缺少申请编号。")
        with self.services.db.transaction() as conn:
            row = conn.execute(
                "SELECT status FROM card_applications WHERE user_id = ? AND application_id = ?",
                (context.user_id, application_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"撤销虚拟卡申请失败：申请不存在：{application_id}")
            if str(row["status"]) != "applying":
                raise ValueError(
                    f"撤销虚拟卡申请失败：申请 {application_id} 当前状态为 "
                    f"{row['status']}，只有 applying 可以撤销。"
                )
            conn.execute(
                "UPDATE card_applications SET status = 'rejected', updated_at = ? "
                "WHERE user_id = ? AND application_id = ? AND status = 'applying'",
                (_iso_now(), context.user_id, application_id),
            )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"虚拟卡申请 {application_id} 已撤销（演示数据）。",
            data={
                "application_id": application_id,
                "status": "rejected",
                "restored": True,
                "simulated": True,
            },
        )


class RestoreWealthRiskTool(BaseTool):
    metadata = ToolMetadata(
        name="restore_wealth_risk",
        title="恢复风险偏好",
        description="补偿工具：恢复风险测评前的风险偏好记录。",
        risk_level=RiskLevel.YELLOW,
        permission="wealth:execute",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        if "previous_preference" not in data:
            raise ValueError("恢复风险偏好失败：缺少测评前的偏好快照。")
        previous = data.get("previous_preference")
        with self.services.db.transaction() as conn:
            if previous is None:
                conn.execute("DELETE FROM wealth_profile WHERE user_id = ?", (context.user_id,))
            else:
                conn.execute(
                    """
                    INSERT INTO wealth_profile (user_id, risk_preference, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        risk_preference = excluded.risk_preference,
                        updated_at = excluded.updated_at
                    """,
                    (context.user_id, str(previous), _iso_now()),
                )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"风险偏好已恢复为 {previous or '未测评'}（演示数据）。",
            data={
                "risk_preference": previous,
                "status": "restored",
                "restored": True,
                "simulated": True,
            },
        )


class ReversePurchaseWealthTool(BaseTool):
    metadata = ToolMetadata(
        name="reverse_purchase_wealth",
        title="撤销理财申购",
        description=(
            "补偿工具：撤销刚完成的模拟理财申购，回滚持仓份额/本金并退回扣款账户，"
            "写入 wealth_reversal 交易；需要理财执行权限。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="wealth:execute",
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        original = args.original_arguments or {}
        holding_id = str(data.get("holding_id") or original.get("holding_id") or "")
        product_id = str(data.get("product_id") or original.get("product_id") or "")
        amount_cny = data.get("amount_cny")
        if amount_cny is None:
            amount_cny = original.get("amount_cny")
        shares = float(data.get("shares") or 0.0)
        if not holding_id or not product_id or amount_cny is None:
            raise ValueError("撤销理财申购失败：缺少持仓编号、产品编号或申购金额。")
        amount_cents = to_cents(float(amount_cny))
        source_account = "ACC-1001"
        now = _iso_now()
        reversal_order = f"WOD-RV-{uuid4().hex[:8].upper()}"
        with self.services.db.transaction() as conn:
            original_id = str(data.get("order_id") or "")
            order = conn.execute(
                "SELECT * FROM wealth_orders WHERE order_id=? AND user_id=?",
                (original_id, context.user_id),
            ).fetchone()
            if (
                order is None
                or order["side"] != "purchase"
                or order["status"] != "completed"
                or order["product_id"] != product_id
                or int(order["amount_cents"]) != amount_cents
                or float(order["shares"]) != shares
                or amount_cents <= 0
                or shares <= 0
            ):
                raise ValueError("撤销申购失败：原订单证据与账本不一致。")
            _reserve_reversal(
                conn,
                kind="wealth_purchase",
                original_id=original_id,
                user_id=context.user_id,
                reversal_id=reversal_order,
            )
            holding = conn.execute(
                "SELECT * FROM wealth_holdings WHERE holding_id = ? AND user_id = ?",
                (holding_id, context.user_id),
            ).fetchone()
            if holding is None:
                raise ValueError(f"撤销理财申购失败：持仓不存在：{holding_id}")
            if (
                holding["status"] != "active"
                or float(holding["shares"]) < shares
                or int(holding["principal_cents"]) < amount_cents
                or int(holding["market_value_cents"]) < amount_cents
            ):
                raise ValueError("原持仓已赎回或发生变化，禁止重复返款，请人工对账。")
            remaining_shares = round(float(holding["shares"]) - shares, 8)
            remaining_principal = int(holding["principal_cents"]) - amount_cents
            remaining_market = int(holding["market_value_cents"]) - amount_cents
            if remaining_shares == 0 and remaining_principal == 0 and remaining_market == 0:
                conn.execute(
                    "UPDATE wealth_holdings SET shares = 0, principal_cents = 0, "
                    "market_value_cents = 0, status = 'closed' WHERE holding_id = ?",
                    (holding_id,),
                )
                holding_status = "closed"
            else:
                if min(remaining_shares, remaining_principal, remaining_market) <= 0:
                    raise ValueError("剩余份额与金额不一致，自动撤销已拒绝，请人工对账。")
                conn.execute(
                    "UPDATE wealth_holdings SET shares = ?, principal_cents = ?, "
                    "market_value_cents = ? WHERE holding_id = ?",
                    (remaining_shares, remaining_principal, remaining_market, holding_id),
                )
                holding_status = "active"
            credited = conn.execute(
                "UPDATE bank_accounts SET balance_cents = balance_cents + ?, "
                "available_cents = available_cents + ? WHERE user_id = ? AND account_id = ?",
                (amount_cents, amount_cents, context.user_id, source_account),
            ).rowcount
            if not credited:
                raise ValueError(f"撤销理财申购失败：扣款账户不存在：{source_account}")
            conn.execute(
                """
                INSERT INTO bank_transactions
                (transaction_id, user_id, account_id, card_id, merchant, category,
                 amount_cents, occurred_at, status, note)
                VALUES (?, ?, ?, NULL, ?, 'wealth_reversal', ?, ?, 'posted', ?)
                """,
                (
                    f"TX-WRV-{uuid4().hex[:8].upper()}",
                    context.user_id,
                    source_account,
                    f"理财申购冲正-{product_id}",
                    amount_cents,
                    now,
                    f"撤销申购持仓 {holding_id}",
                ),
            )
            conn.execute(
                """
                INSERT INTO wealth_orders
                (order_id, user_id, product_id, side, amount_cents, shares,
                 status, created_at)
                VALUES (?, ?, ?, 'purchase_reversal', ?, ?, 'completed', ?)
                """,
                (
                    reversal_order,
                    context.user_id,
                    product_id,
                    amount_cents,
                    -shares,
                    now,
                ),
            )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"理财申购 {holding_id} 已撤销，退回 {float(amount_cny):.2f} 元（演示数据）。",
            data={
                "order_id": reversal_order,
                "holding_id": holding_id,
                "holding_status": holding_status,
                "amount_cny": float(amount_cny),
                "restored": True,
                "simulated": True,
            },
        )


# ---------------------------------------------------------------------------
# Demo sandbox tools (green: local demo ledger only, no real money)
# ---------------------------------------------------------------------------


def _insert_demo_entry(
    db: Any,
    *,
    user_id: str,
    action_id: str,
    kind: str,
    amount_cents: int,
    note: str,
) -> str:
    entry_id = f"CD-{uuid4().hex[:10].upper()}"
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO compensation_demo_ledger
            (entry_id, user_id, action_id, kind, amount_cents, status,
             reverses_entry_id, note, created_at)
            VALUES (?, ?, ?, ?, ?, 'posted', NULL, ?, ?)
            """,
            (entry_id, user_id, action_id, kind, amount_cents, note, _iso_now()),
        )
    return entry_id


class DemoReserveFundsTool(BaseTool):
    metadata = ToolMetadata(
        name="demo_reserve_funds",
        title="演示预留资金",
        description="演示用：在本地模拟账本中预留一笔资金，可由 reverse_demo_reserve 补偿。",
        risk_level=RiskLevel.GREEN,
        permission=DEMO_PERMISSION,
        input_schema=DemoReserveArgs.model_json_schema(),
        output_schema={},
        compensable=True,
        compensation_tool="reverse_demo_reserve",
    )
    arguments_model = DemoReserveArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = DemoReserveArgs.model_validate(arguments)
        amount_cents = to_cents(args.amount_cny)
        entry_id = _insert_demo_entry(
            self.services.db,
            user_id=context.user_id,
            action_id=context.run_id,
            kind="reserve",
            amount_cents=amount_cents,
            note="演示预留资金",
        )
        if args.pause_after:
            pause = self.services.extras.get("pause")
            if pause is not None:
                pause.pause(context.run_id, reason="演示：第一个节点执行后自动暂停")
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"演示预留资金 {args.amount_cny:.2f} 元已记账（模拟）。",
            data={
                "entry_id": entry_id,
                "kind": "reserve",
                "amount_cny": amount_cents / 100.0,
                "status": "posted",
                "paused_after": args.pause_after,
                "simulated": True,
            },
        )


class DemoChargeFeeTool(BaseTool):
    metadata = ToolMetadata(
        name="demo_charge_fee",
        title="演示手续费扣减",
        description="演示用：在本地模拟账本中扣减手续费，可由 reverse_demo_charge 补偿。",
        risk_level=RiskLevel.GREEN,
        permission=DEMO_PERMISSION,
        input_schema=DemoChargeArgs.model_json_schema(),
        output_schema={},
        compensable=True,
        compensation_tool="reverse_demo_charge",
    )
    arguments_model = DemoChargeArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = DemoChargeArgs.model_validate(arguments)
        amount_cents = to_cents(args.amount_cny)
        entry_id = _insert_demo_entry(
            self.services.db,
            user_id=context.user_id,
            action_id=context.run_id,
            kind="fee",
            amount_cents=amount_cents,
            note="演示手续费",
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"演示手续费 {args.amount_cny:.2f} 元已记账（模拟）。",
            data={
                "entry_id": entry_id,
                "kind": "fee",
                "amount_cny": amount_cents / 100.0,
                "status": "posted",
                "fail_compensation": args.fail_compensation,
                "simulated": True,
            },
        )


class DemoIrreversibleMarkerTool(BaseTool):
    metadata = ToolMetadata(
        name="demo_irreversible_marker",
        title="演示不可撤销步骤",
        description="演示用：写入一条声明为不可撤销的标记，用于验证回滚阻断。",
        risk_level=RiskLevel.GREEN,
        permission=DEMO_PERMISSION,
        input_schema=DemoMarkerArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = DemoMarkerArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = DemoMarkerArgs.model_validate(arguments)
        entry_id = _insert_demo_entry(
            self.services.db,
            user_id=context.user_id,
            action_id=context.run_id,
            kind="irreversible",
            amount_cents=0,
            note=args.note,
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message="已写入不可撤销演示标记（模拟）。",
            data={
                "entry_id": entry_id,
                "kind": "irreversible",
                "status": "posted",
                "simulated": True,
            },
        )


class DemoFailStepTool(BaseTool):
    metadata = ToolMetadata(
        name="demo_fail_step",
        title="演示可控失败",
        description="演示用：按参数确定性失败，用于触发逆序补偿。",
        risk_level=RiskLevel.GREEN,
        permission=DEMO_PERMISSION,
        input_schema=DemoFailArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = DemoFailArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = DemoFailArgs.model_validate(arguments)
        raise ValueError(f"演示可控失败：{args.message}")


class _DemoReverseTool(BaseTool):
    kind = "reserve"
    arguments_model = ReverseArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def _reverse(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        data = _result_data(args.original_result)
        original = args.original_arguments or {}
        entry_id = str(original.get("entry_id") or data.get("entry_id") or "")
        if not entry_id:
            raise ValueError("演示补偿失败：缺少原账本条目编号。")
        with self.services.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM compensation_demo_ledger WHERE entry_id = ? AND user_id = ?",
                (entry_id, context.user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"演示补偿失败：账本条目不存在：{entry_id}")
            if str(row["status"]) == "reversed":
                return ToolResult(
                    tool_name=self.metadata.name,
                    message=f"演示账本条目 {entry_id} 已冲正（幂等）。",
                    data={
                        "entry_id": entry_id,
                        "kind": str(row["kind"]),
                        "status": "reversed",
                        "idempotent": True,
                        "simulated": True,
                    },
                )
            reversal_id = f"CD-{uuid4().hex[:10].upper()}"
            conn.execute(
                "UPDATE compensation_demo_ledger SET status = 'reversed' "
                "WHERE entry_id = ? AND user_id = ?",
                (entry_id, context.user_id),
            )
            conn.execute(
                """
                INSERT INTO compensation_demo_ledger
                (entry_id, user_id, action_id, kind, amount_cents, status,
                 reverses_entry_id, note, created_at)
                VALUES (?, ?, ?, ?, ?, 'posted', ?, ?, ?)
                """,
                (
                    reversal_id,
                    context.user_id,
                    str(row["action_id"]),
                    f"{row['kind']}_reversal",
                    int(row["amount_cents"]),
                    entry_id,
                    f"演示冲正 {entry_id}",
                    _iso_now(),
                ),
            )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"演示账本条目 {entry_id} 已冲正（模拟）。",
            data={
                "entry_id": reversal_id,
                "reversed_entry_id": entry_id,
                "kind": f"{row['kind']}_reversal",
                "amount_cny": int(row["amount_cents"]) / 100.0,
                "status": "reversed",
                "simulated": True,
            },
        )


class ReverseDemoReserveTool(_DemoReverseTool):
    kind = "reserve"
    metadata = ToolMetadata(
        name="reverse_demo_reserve",
        title="演示释放预留资金",
        description="补偿工具：把演示预留资金标记为已冲正，并写入反向账本记录。",
        risk_level=RiskLevel.GREEN,
        permission=DEMO_PERMISSION,
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return self._reverse(arguments, context)


class ReverseDemoChargeTool(_DemoReverseTool):
    kind = "fee"
    metadata = ToolMetadata(
        name="reverse_demo_charge",
        title="演示撤销手续费",
        description="补偿工具：撤销演示手续费并写入反向账本记录；可模拟补偿通道故障。",
        risk_level=RiskLevel.GREEN,
        permission=DEMO_PERMISSION,
        input_schema=ReverseArgs.model_json_schema(),
        output_schema={},
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ReverseArgs.model_validate(arguments)
        original = args.original_arguments or {}
        if original.get("fail_compensation"):
            raise RuntimeError("演示补偿通道故障：手续费冲正暂不可用。")
        return self._reverse(arguments, context)


# ---------------------------------------------------------------------------
# Module contract
# ---------------------------------------------------------------------------


def activate(services: CoreServices) -> None:
    """Register specs and expose the pause/journal registries to tools."""
    compensation = services.compensation
    if compensation is None:
        raise RuntimeError("补偿注册表尚未初始化，无法注册补偿规格。")
    for spec in build_specs():
        compensation.register(spec)
    scheduler = services.scheduler
    services.extras["pause"] = getattr(scheduler, "pause", None)
    services.extras["journal"] = getattr(scheduler, "journal", None)
    services.extras["compensation_demo_modes"] = list(DEMO_MODES)
    services.extras["compensation_note"] = DEMO_NOTE


def tools(services: CoreServices) -> list[BaseTool]:
    return [
        ReverseTransferTool(services),
        RestoreRepaymentDateTool(services),
        RestoreCardLimitTool(services),
        RestoreTransactionLimitTool(services),
        ReactivateSubscriptionTool(services),
        CancelVirtualCardApplicationTool(services),
        RestoreWealthRiskTool(services),
        ReversePurchaseWealthTool(services),
        DemoReserveFundsTool(services),
        DemoChargeFeeTool(services),
        DemoIrreversibleMarkerTool(services),
        DemoFailStepTool(services),
        ReverseDemoReserveTool(services),
        ReverseDemoChargeTool(services),
    ]


def _demo_nodes(mode: str, pause_after_first: bool) -> list[PlanNode]:
    reserve = PlanNode(
        id="step-1",
        tool_name="demo_reserve_funds",
        arguments={"amount_cny": 199.0, "pause_after": pause_after_first},
    )
    charge = PlanNode(
        id="step-2",
        tool_name="demo_charge_fee",
        arguments={
            "amount_cny": 59.0,
            "fail_compensation": mode == "compensation_failure",
        },
        depends_on=["step-1"],
    )
    nodes = [reserve, charge]
    if mode == "irreversible":
        nodes.append(
            PlanNode(
                id="step-3",
                tool_name="demo_irreversible_marker",
                arguments={"note": "演示不可撤销资金标记"},
                depends_on=["step-2"],
            )
        )
    if mode != "success":
        nodes.append(
            PlanNode(
                id=f"step-{len(nodes) + 1}",
                tool_name="demo_fail_step",
                arguments={"message": f"演示可控失败（mode={mode}）"},
                depends_on=[nodes[-1].id],
            )
        )
    return nodes


def _coverage(services: CoreServices) -> dict[str, Any]:
    registry = services.require_registry()
    compensation = services.compensation
    specs = compensation.as_list() if compensation is not None else []
    registered = {str(spec["tool_name"]) for spec in specs}
    reversible = [spec for spec in specs if not spec["irreversible"]]
    inverse_names = {str(spec["compensation_tool"]) for spec in reversible}
    read_only: list[str] = []
    missing: list[str] = []
    for tool in registry.list():
        name = tool.metadata.name
        if name in registered or name in inverse_names:
            continue
        if tool.metadata.risk_level is RiskLevel.GREEN:
            read_only.append(name)
        else:
            missing.append(name)
    inverse_tools: dict[str, dict[str, Any]] = {}
    for spec in reversible:
        name = str(spec["compensation_tool"])
        if name in inverse_tools:
            continue
        try:
            tool = registry.get(name)
        except KeyError:
            inverse_tools[name] = {"tool_name": name, "registered": False}
            continue
        inverse_tools[name] = {
            "tool_name": name,
            "registered": True,
            "risk_level": tool.metadata.risk_level.value,
            "permission": tool.metadata.permission,
        }
    return {
        "registered": len(specs),
        "compensable": len(reversible),
        "irreversible": len(specs) - len(reversible),
        "read_only_tools": sorted(read_only),
        "unregistered_mutating_tools": sorted(missing),
        "fully_covered": not missing,
        "inverse_tools": sorted(inverse_tools.values(), key=lambda item: str(item["tool_name"])),
    }


def _resolve_role(services: CoreServices, header: str | None) -> str:
    authz = services.authz
    if authz is None:
        return header or services.settings.authz_default_role
    try:
        return authz.normalize(header, default=services.settings.authz_default_role)
    except AuthzError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _require_capability(services: CoreServices, role: str, capability: str) -> None:
    authz = services.authz
    if authz is None:
        return
    try:
        authz.require(role, capability)
    except AuthzError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def router(services: CoreServices) -> APIRouter:
    prefix = services.settings.api_prefix
    api = APIRouter(tags=["compensation"])

    @api.get(f"{prefix}/compensation/specs")
    def list_specs() -> dict[str, Any]:
        compensation = services.compensation
        specs = compensation.as_list() if compensation is not None else []
        return {
            "specs": specs,
            "count": len(specs),
            "compensable": [str(spec["tool_name"]) for spec in specs if not spec["irreversible"]],
            "irreversible": [str(spec["tool_name"]) for spec in specs if spec["irreversible"]],
            "compensation_tools": sorted(
                {str(spec["compensation_tool"]) for spec in specs if not spec["irreversible"]}
            ),
            "coverage": _coverage(services),
            "demo": {
                "endpoint": f"POST {prefix}/compensation/demo/run",
                "modes": list(DEMO_MODES),
                "description": "可控失败 DAG：可逆回滚 / 不可逆阻断 / 部分补偿失败 / 成功。",
            },
            "policy": {
                "reverse_order": True,
                "gateway_recheck": True,
                "executor": "ToolExecutor",
                "audit_events": ["compensation_executed", "compensation_failed"],
                "rollback_states": ["ROLLED_BACK", "UNKNOWN"],
            },
            "simulated": True,
            "demo_only": True,
            "note": DEMO_NOTE,
        }

    @api.post(f"{prefix}/compensation/demo/run")
    def run_demo(
        body: DemoRunRequest | None = None,
        mode: str | None = Query(default=None, max_length=32),
        pause_after_first: bool | None = Query(default=None),
        user_id: str = Query(default=DEMO_USER, max_length=64),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require_capability(services, role, "tool:execute")
        request = body or DemoRunRequest()
        effective_mode = str(mode or request.mode or "reversible").strip().lower()
        if effective_mode not in DEMO_MODES:
            raise HTTPException(
                status_code=400,
                detail=f"未知的演示模式：{effective_mode}（可选：{'、'.join(DEMO_MODES)}）",
            )
        effective_pause = (
            request.pause_after_first if pause_after_first is None else pause_after_first
        )
        effective_user = user_id or request.user_id
        nodes = _demo_nodes(effective_mode, effective_pause)
        try:
            response = services.scheduler.run_dag(
                user_id=effective_user,
                instruction=f"运行补偿演示 DAG（mode={effective_mode}）",
                nodes=nodes,
                role=role,
                intent=f"compensation_demo_{effective_mode}",
            )
        except IntentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response["demo"] = {
            "mode": effective_mode,
            "pause_after_first": effective_pause,
            "user_id": effective_user,
            "nodes": [node.as_dict() for node in nodes],
            "endpoints": {
                "journal": f"GET {prefix}/actions/{{action_id}}/journal",
                "pause": f"POST {prefix}/actions/{{action_id}}/pause",
                "resume": f"POST {prefix}/actions/{{action_id}}/resume",
                "rollback": f"POST {prefix}/actions/{{action_id}}/rollback",
            },
        }
        return response

    @api.post(f"{prefix}/actions/{{action_id}}/pause")
    def pause_action(
        action_id: str,
        reason: str = Query(default="用户请求暂停", max_length=200),
        user_id: str = Query(default=DEMO_USER, max_length=64),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require_capability(services, role, "tool:execute")
        try:
            response = services.scheduler.pause_action(
                action_id=action_id, reason=reason, user_id=user_id
            )
        except IntentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response["role"] = role
        return response

    @api.post(f"{prefix}/actions/{{action_id}}/resume")
    def resume_action(
        action_id: str,
        user_id: str = Query(default=DEMO_USER, max_length=64),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require_capability(services, role, "tool:execute")
        try:
            response = services.scheduler.resume_action(
                action_id=action_id, user_id=user_id, role=role
            )
        except IntentError as exc:
            message = str(exc)
            status = 404 if "不存在" in message else 400
            raise HTTPException(status_code=status, detail=message) from exc
        response["role"] = role
        return response

    @api.post(f"{prefix}/actions/{{action_id}}/rollback")
    def rollback_action(
        action_id: str,
        reason: str = Query(default="用户请求人工回退", max_length=200),
        user_id: str = Query(default=DEMO_USER, max_length=64),
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require_capability(services, role, "tool:execute")
        try:
            response = services.scheduler.rollback_action(
                action_id=action_id, user_id=user_id, role=role, reason=reason
            )
        except IntentError as exc:
            message = str(exc)
            status = 404 if "不存在" in message else 400
            raise HTTPException(status_code=status, detail=message) from exc
        response["role"] = role
        return response

    @api.get(f"{prefix}/actions/{{action_id}}/journal")
    def action_journal(
        action_id: str,
        x_aegis_role: str | None = Header(default=None, alias=ROLE_HEADER),
    ) -> dict[str, Any]:
        role = _resolve_role(services, x_aegis_role)
        _require_capability(services, role, "trust:inspect")
        try:
            response = services.scheduler.journal_view(action_id)
        except IntentError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        response["role"] = role
        return response

    return api
