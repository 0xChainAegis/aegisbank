"""Wealth-management scenario: simulated products, holdings, purchases and redemptions.

Every fact in this module is simulated demo data stored in SQLite: the product
catalog, expected annual rates, holdings and orders are seeded mock facts. No
real money moves and nothing here is investment advice. The module owns its
schema, seed data, tool nodes, planner intents, risk rules and read-only routes,
so core wiring stays untouched (see ``README.md`` in this package).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator, model_validator

from ..banking.repository import BankingRepository, to_cents, to_cny
from ..db import Database
from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..planning.contracts import ExecutionPlan, PlanStep
from ..planning.intents import IntentContext, IntentRule
from ..registry import BaseTool
from ..risk_rules import RiskContext, RiskGuess, RiskRule
from ..services import CoreServices

NAME = "wealth"
SOURCE_ACCOUNT = "ACC-1001"
DEMO_HOLDING_ID = "HLTH-DEMO-R2"
DEMO_HOLDING_PRODUCT_ID = "WPRD-R2"
DEMO_HOLDING_SHARES = 3000.0
DEMO_HOLDING_PRINCIPAL_CENTS = 300_000
DEMO_HOLDING_MARKET_VALUE_CENTS = 306_000
SEED_OPENED_AT = "2025-01-15T09:00:00+00:00"
DISCLAIMER = "模拟数据，不构成任何投资建议，不产生真实资金变动。"
RISK_LEVELS = ("R1", "R2", "R3", "R4", "R5")
RISK_LABELS = {
    "R1": "保守型",
    "R2": "稳健型",
    "R3": "平衡型",
    "R4": "成长型",
    "R5": "进取型",
}
YELLOW_REDEEM_LIMIT_CNY = 1000.0
SIMULATED_NAV_CNY = 1.0

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wealth_products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    min_amount_cents INTEGER NOT NULL,
    expected_annual_rate REAL NOT NULL,
    term_days INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS wealth_holdings (
    holding_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    shares REAL NOT NULL DEFAULT 0,
    principal_cents INTEGER NOT NULL DEFAULT 0,
    market_value_cents INTEGER NOT NULL DEFAULT 0,
    opened_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS wealth_orders (
    order_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    side TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    shares REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wealth_profile (
    user_id TEXT PRIMARY KEY,
    risk_preference TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wealth_holdings_user
    ON wealth_holdings(user_id, status);
CREATE INDEX IF NOT EXISTS idx_wealth_orders_user
    ON wealth_orders(user_id, created_at);
"""

# (product_id, name, kind, risk_level, min_amount_cents, expected_annual_rate, term_days)
_SEED_PRODUCTS = (
    ("WPRD-R1", "稳健货币A", "货币基金", "R1", 10_000, 1.85, 0),
    ("WPRD-R2", "稳健短债A", "短债基金", "R2", 100_000, 2.65, 90),
    ("WPRD-R3", "平衡混合A", "混合基金", "R3", 100_000, 3.80, 180),
    ("WPRD-R4", "指数增强A", "指数增强基金", "R4", 500_000, 5.20, 365),
    ("WPRD-R5", "行业主题A", "股票基金", "R5", 1_000_000, 6.80, 730),
)


def seed(db: Database, user_id: str) -> None:
    """Insert the five demo products and one demo holding, idempotently."""
    with db.transaction() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO wealth_products
            (product_id, name, kind, risk_level, min_amount_cents,
             expected_annual_rate, term_days, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            list(_SEED_PRODUCTS),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO wealth_holdings
            (holding_id, user_id, product_id, shares, principal_cents,
             market_value_cents, opened_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                DEMO_HOLDING_ID,
                user_id,
                DEMO_HOLDING_PRODUCT_ID,
                DEMO_HOLDING_SHARES,
                DEMO_HOLDING_PRINCIPAL_CENTS,
                DEMO_HOLDING_MARKET_VALUE_CENTS,
                SEED_OPENED_AT,
            ),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _risk_index(level: str) -> int:
    return RISK_LEVELS.index(level) if level in RISK_LEVELS else -1


def _serialize_product(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": row["product_id"],
        "name": row["name"],
        "kind": row["kind"],
        "risk_level": row["risk_level"],
        "min_amount_cny": to_cny(row["min_amount_cents"]),
        "expected_annual_rate": row["expected_annual_rate"],
        "term_days": row["term_days"],
        "status": row["status"],
    }


def _serialize_holding(row: dict[str, Any]) -> dict[str, Any]:
    product = row.get("product") or {}
    return {
        "holding_id": row["holding_id"],
        "product_id": row["product_id"],
        "product_name": product.get("name", ""),
        "kind": product.get("kind", ""),
        "risk_level": product.get("risk_level", ""),
        "shares": row["shares"],
        "principal_cny": to_cny(row["principal_cents"]),
        "market_value_cny": to_cny(row["market_value_cents"]),
        "opened_at": row["opened_at"],
        "status": row["status"],
    }


def _products(db: Database, *, active_only: bool = True) -> list[dict[str, Any]]:
    query = "SELECT * FROM wealth_products"
    if active_only:
        query += " WHERE status = 'active'"
    query += " ORDER BY risk_level, product_id"
    with db.transaction() as conn:
        return [dict(row) for row in conn.execute(query).fetchall()]


def _product(db: Database, product_id: str) -> dict[str, Any] | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM wealth_products WHERE product_id = ?", (product_id,)
        ).fetchone()
    return None if row is None else dict(row)


def _holdings(db: Database, user_id: str, *, status: str = "active") -> list[dict[str, Any]]:
    query = "SELECT * FROM wealth_holdings WHERE user_id = ?"
    params: list[Any] = [user_id]
    if status != "all":
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY opened_at, holding_id"
    with db.transaction() as conn:
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    products = {item["product_id"]: item for item in _products(db, active_only=False)}
    for row in rows:
        row["product"] = products.get(row["product_id"])
    return rows


def _risk_preference(db: Database, user_id: str) -> str | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT risk_preference FROM wealth_profile WHERE user_id = ?", (user_id,)
        ).fetchone()
    return None if row is None else str(row["risk_preference"])


def _save_risk_preference(db: Database, user_id: str, preference: str) -> str | None:
    previous = _risk_preference(db, user_id)
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO wealth_profile (user_id, risk_preference, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                risk_preference = excluded.risk_preference,
                updated_at = excluded.updated_at
            """,
            (user_id, preference, _now()),
        )
    return previous


def _redeem_amount_cents(
    repository: BankingRepository, user_id: str, arguments: dict[str, Any]
) -> int | None:
    """Deterministic redemption amount for the risk rule; never guesses money."""
    amount = arguments.get("amount_cny")
    if amount is not None:
        return to_cents(float(amount))
    shares = arguments.get("shares")
    if shares is not None:
        return to_cents(float(shares) * SIMULATED_NAV_CNY)
    holding_id = arguments.get("holding_id")
    product_id = arguments.get("product_id")
    query = (
        "SELECT market_value_cents FROM wealth_holdings "
        "WHERE user_id = ? AND status = 'active'"
    )
    params: list[Any] = [user_id]
    if holding_id:
        query += " AND holding_id = ?"
        params.append(str(holding_id))
    elif product_id:
        query += " AND product_id = ?"
        params.append(str(product_id))
    query += " ORDER BY opened_at, holding_id LIMIT 1"
    with repository.db.transaction() as conn:
        row = conn.execute(query, params).fetchone()
    return None if row is None else int(row["market_value_cents"])

class WealthProductOut(BaseModel):
    product_id: str
    name: str
    kind: str
    risk_level: str
    min_amount_cny: float
    expected_annual_rate: float
    term_days: int
    status: str


class HoldingOut(BaseModel):
    holding_id: str
    product_id: str
    product_name: str
    kind: str
    risk_level: str
    shares: float
    principal_cny: float
    market_value_cny: float
    opened_at: str
    status: str


class ListWealthProductsArgs(BaseModel):
    risk_level: str | None = Field(default=None, max_length=8)


class ListWealthProductsOutput(BaseModel):
    products: list[WealthProductOut]
    count: int
    simulated: bool
    disclaimer: str


class QueryWealthHoldingsArgs(BaseModel):
    status: str = Field(default="active", max_length=16)


class QueryWealthHoldingsOutput(BaseModel):
    holdings: list[HoldingOut]
    count: int
    total_market_value_cny: float
    total_principal_cny: float
    simulated: bool
    disclaimer: str


class AssessWealthRiskArgs(BaseModel):
    risk_preference: str = Field(min_length=2, max_length=2, pattern=r"^R[1-5]$")

    @field_validator("risk_preference", mode="before")
    @classmethod
    def normalize_preference(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class AssessWealthRiskOutput(BaseModel):
    risk_preference: str
    risk_label: str
    previous_preference: str | None
    updated_at: str
    simulated: bool
    disclaimer: str


class PurchaseWealthArgs(BaseModel):
    product_id: str = Field(min_length=3, max_length=32)
    amount_cny: float = Field(gt=0, le=1_000_000)


class PurchaseWealthOutput(BaseModel):
    order_id: str
    holding_id: str
    product_id: str
    product_name: str
    risk_level: str
    amount_cny: float
    shares: float
    balance_after_cny: float | None
    risk_preference: str | None
    risk_warning: list[str]
    executed_at: str
    simulated: bool
    disclaimer: str


class RedeemWealthArgs(BaseModel):
    holding_id: str | None = Field(default=None, max_length=32)
    product_id: str | None = Field(default=None, max_length=32)
    amount_cny: float | None = Field(default=None, gt=0, le=1_000_000)
    shares: float | None = Field(default=None, gt=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_target(self) -> RedeemWealthArgs:
        if not self.holding_id and not self.product_id:
            raise ValueError("赎回需要提供 holding_id 或 product_id。")
        if self.amount_cny is not None and self.shares is not None:
            raise ValueError("赎回金额与赎回份额只能二选一。")
        return self


class RedeemWealthOutput(BaseModel):
    order_id: str
    holding_id: str
    product_id: str
    product_name: str
    amount_cny: float
    remaining_market_value_cny: float
    remaining_principal_cny: float
    remaining_shares: float
    holding_status: str
    balance_after_cny: float | None
    executed_at: str
    simulated: bool
    disclaimer: str


class ListWealthProductsTool(BaseTool):
    metadata = ToolMetadata(
        name="list_wealth_products",
        title="查看理财产品",
        description="只读查询模拟理财产品清单（R1-R5），不构成任何投资建议。",
        risk_level=RiskLevel.GREEN,
        permission="wealth:read",
        input_schema=ListWealthProductsArgs.model_json_schema(),
        output_schema=ListWealthProductsOutput.model_json_schema(),
    )
    arguments_model = ListWealthProductsArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ListWealthProductsArgs.model_validate(arguments)
        products = _products(self.services.db)
        if args.risk_level:
            wanted = args.risk_level.upper()
            products = [item for item in products if item["risk_level"] == wanted]
        serialized = [_serialize_product(item) for item in products]
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"共 {len(serialized)} 只模拟理财产品。{DISCLAIMER}",
            data={
                "products": serialized,
                "count": len(serialized),
                "simulated": True,
                "disclaimer": DISCLAIMER,
            },
        )


class QueryWealthHoldingsTool(BaseTool):
    metadata = ToolMetadata(
        name="query_wealth_holdings",
        title="查询理财持仓",
        description="只读查询本人模拟理财持仓、本金与市值。",
        risk_level=RiskLevel.GREEN,
        permission="wealth:read",
        input_schema=QueryWealthHoldingsArgs.model_json_schema(),
        output_schema=QueryWealthHoldingsOutput.model_json_schema(),
    )
    arguments_model = QueryWealthHoldingsArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = QueryWealthHoldingsArgs.model_validate(arguments)
        rows = _holdings(self.services.db, context.user_id, status=args.status)
        holdings = [_serialize_holding(row) for row in rows]
        total_market = round(sum(item["market_value_cny"] for item in holdings), 2)
        total_principal = round(sum(item["principal_cny"] for item in holdings), 2)
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"已读取 {len(holdings)} 条模拟理财持仓。{DISCLAIMER}",
            data={
                "holdings": holdings,
                "count": len(holdings),
                "total_market_value_cny": total_market,
                "total_principal_cny": total_principal,
                "simulated": True,
                "disclaimer": DISCLAIMER,
            },
        )


class AssessWealthRiskTool(BaseTool):
    metadata = ToolMetadata(
        name="assess_wealth_risk",
        title="风险测评",
        description="记录用户的风险偏好（R1-R5），用于申购时的风险匹配提示。",
        risk_level=RiskLevel.GREEN,
        permission="wealth:read",
        compensable=True,
        compensation_tool="restore_wealth_risk",
        input_schema=AssessWealthRiskArgs.model_json_schema(),
        output_schema=AssessWealthRiskOutput.model_json_schema(),
    )
    arguments_model = AssessWealthRiskArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = AssessWealthRiskArgs.model_validate(arguments)
        previous = _save_risk_preference(
            self.services.db, context.user_id, args.risk_preference
        )
        label = RISK_LABELS[args.risk_preference]
        return ToolResult(
            tool_name=self.metadata.name,
            message=(
                f"已完成模拟风险测评：风险偏好 {args.risk_preference}（{label}）。"
                f"{DISCLAIMER}"
            ),
            data={
                "risk_preference": args.risk_preference,
                "risk_label": label,
                "previous_preference": previous,
                "updated_at": _now(),
                "simulated": True,
                "disclaimer": DISCLAIMER,
            },
        )

class PurchaseWealthTool(BaseTool):
    metadata = ToolMetadata(
        name="purchase_wealth",
        title="申购理财产品",
        description=(
            "从演示账户申购模拟理财产品；资金投入恒为红色，需要二次身份校验，"
            "产品风险高于用户偏好时给出更强的风险提示。"
        ),
        risk_level=RiskLevel.RED,
        permission="wealth:execute",
        compensable=True,
        compensation_tool="reverse_purchase_wealth",
        input_schema=PurchaseWealthArgs.model_json_schema(),
        output_schema=PurchaseWealthOutput.model_json_schema(),
    )
    arguments_model = PurchaseWealthArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = PurchaseWealthArgs.model_validate(arguments)
        db = self.services.db
        product = _product(db, args.product_id)
        if product is None:
            raise ValueError(f"理财产品不存在：{args.product_id}")
        if product["status"] != "active":
            raise ValueError(f"理财产品当前不可申购：{args.product_id}")

        amount_cents = to_cents(args.amount_cny)
        minimum_cents = int(product["min_amount_cents"])
        if amount_cents < minimum_cents:
            raise ValueError(
                f"{product['name']} 起购金额为 {to_cny(minimum_cents):.2f} 元，"
                f"本次申购 {args.amount_cny:.2f} 元不足起购金额。"
            )

        account = self.services.repository.account(context.user_id, SOURCE_ACCOUNT)
        if account is None:
            raise ValueError(f"扣款账户不存在：{SOURCE_ACCOUNT}")
        if to_cents(account.available_cny) < amount_cents:
            raise ValueError("扣款账户可用余额不足，无法完成模拟申购。")

        preference = _risk_preference(db, context.user_id)
        risk_warning: list[str] = []
        if preference is not None and _risk_index(product["risk_level"]) > _risk_index(
            preference
        ):
            risk_warning.append(
                f"产品风险等级 {product['risk_level']} 高于您的风险偏好 {preference}，"
                "本次申购属于主动提升风险敞口，请确认可以承受相应净值波动。"
            )

        now = _now()
        order_id = _new_id("WOD")
        shares = round(amount_cents / 100.0 * SIMULATED_NAV_CNY, 2)
        with db.transaction() as conn:
            existing = conn.execute(
                "SELECT holding_id FROM wealth_holdings "
                "WHERE user_id = ? AND product_id = ? AND status = 'active' "
                "ORDER BY opened_at, holding_id LIMIT 1",
                (context.user_id, product["product_id"]),
            ).fetchone()
            if existing is None:
                holding_id = _new_id("HLTH")
                conn.execute(
                    """
                    INSERT INTO wealth_holdings
                    (holding_id, user_id, product_id, shares, principal_cents,
                     market_value_cents, opened_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                    """,
                    (
                        holding_id,
                        context.user_id,
                        product["product_id"],
                        shares,
                        amount_cents,
                        amount_cents,
                        now,
                    ),
                )
            else:
                holding_id = str(existing["holding_id"])
                conn.execute(
                    "UPDATE wealth_holdings SET shares = shares + ?, "
                    "principal_cents = principal_cents + ?, "
                    "market_value_cents = market_value_cents + ? "
                    "WHERE holding_id = ?",
                    (shares, amount_cents, amount_cents, holding_id),
                )
            conn.execute(
                """
                INSERT INTO wealth_orders
                (order_id, user_id, product_id, side, amount_cents, shares, status, created_at)
                VALUES (?, ?, ?, 'purchase', ?, ?, 'completed', ?)
                """,
                (
                    order_id,
                    context.user_id,
                    product["product_id"],
                    amount_cents,
                    shares,
                    now,
                ),
            )
            conn.execute(
                "UPDATE bank_accounts SET balance_cents = balance_cents - ?, "
                "available_cents = available_cents - ? WHERE user_id = ? AND account_id = ?",
                (amount_cents, amount_cents, context.user_id, SOURCE_ACCOUNT),
            )
            conn.execute(
                """
                INSERT INTO bank_transactions
                (transaction_id, user_id, account_id, card_id, merchant, category,
                 amount_cents, occurred_at, status, note)
                VALUES (?, ?, ?, NULL, ?, 'wealth', ?, ?, 'posted', ?)
                """,
                (
                    _new_id("TX-W"),
                    context.user_id,
                    SOURCE_ACCOUNT,
                    f"理财申购-{product['name']}",
                    -amount_cents,
                    now,
                    DISCLAIMER,
                ),
            )

        refreshed = self.services.repository.account(context.user_id, SOURCE_ACCOUNT)
        message_parts = [
            f"理财申购已按模拟规则成交：{product['name']}（{product['risk_level']}）"
            f"{to_cny(amount_cents):.2f} 元。"
        ]
        message_parts.extend(risk_warning)
        message_parts.append(DISCLAIMER)
        return ToolResult(
            tool_name=self.metadata.name,
            message=" ".join(message_parts),
            data={
                "order_id": order_id,
                "holding_id": holding_id,
                "product_id": product["product_id"],
                "product_name": product["name"],
                "risk_level": product["risk_level"],
                "amount_cny": to_cny(amount_cents),
                "shares": shares,
                "balance_after_cny": None if refreshed is None else refreshed.available_cny,
                "risk_preference": preference,
                "risk_warning": risk_warning,
                "executed_at": now,
                "simulated": True,
                "disclaimer": DISCLAIMER,
            },
        )


class RedeemWealthTool(BaseTool):
    metadata = ToolMetadata(
        name="redeem_wealth",
        title="赎回理财产品",
        description=(
            "赎回模拟理财持仓；金额不超过 1000 元为黄色确认，超过 1000 元升级为红色强验证。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="wealth:execute",
        input_schema=RedeemWealthArgs.model_json_schema(),
        output_schema=RedeemWealthOutput.model_json_schema(),
    )
    arguments_model = RedeemWealthArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = RedeemWealthArgs.model_validate(arguments)
        db = self.services.db
        active = _holdings(db, context.user_id)
        target: dict[str, Any] | None = None
        if args.holding_id:
            target = next(
                (item for item in active if item["holding_id"] == args.holding_id), None
            )
            if target is None:
                raise ValueError(f"可赎回的模拟持仓不存在：{args.holding_id}")
        else:
            candidates = [
                item for item in active if item["product_id"] == args.product_id
            ]
            if not candidates:
                raise ValueError(f"当前没有该理财产品的可赎回持仓：{args.product_id}")
            if len(candidates) > 1:
                raise ValueError("该产品存在多笔持仓，请指定 holding_id 后再赎回。")
            target = candidates[0]

        product = target.get("product") or {}
        product_name = str(product.get("name") or target["product_id"])
        market_value = int(target["market_value_cents"])
        if args.amount_cny is not None:
            amount_cents = to_cents(args.amount_cny)
        elif args.shares is not None:
            amount_cents = to_cents(args.shares * SIMULATED_NAV_CNY)
        else:
            amount_cents = market_value
        if amount_cents <= 0:
            raise ValueError("赎回金额必须大于 0。")
        if amount_cents > market_value:
            raise ValueError(
                f"赎回金额 {to_cny(amount_cents):.2f} 元超过持仓市值 "
                f"{to_cny(market_value):.2f} 元。"
            )

        closing = amount_cents >= market_value
        if closing:
            remaining_principal = 0
            remaining_market = 0
            remaining_shares = 0.0
            holding_status = "closed"
        else:
            principal_cents = int(target["principal_cents"])
            principal_cut = int(round(principal_cents * amount_cents / market_value))
            remaining_principal = principal_cents - principal_cut
            remaining_market = market_value - amount_cents
            remaining_shares = round(float(target["shares"]) - amount_cents / 100.0, 2)
            holding_status = "active"

        now = _now()
        order_id = _new_id("WOD")
        with db.transaction() as conn:
            conn.execute(
                "UPDATE wealth_holdings SET shares = ?, principal_cents = ?, "
                "market_value_cents = ?, status = ? WHERE holding_id = ?",
                (
                    remaining_shares,
                    remaining_principal,
                    remaining_market,
                    holding_status,
                    target["holding_id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO wealth_orders
                (order_id, user_id, product_id, side, amount_cents, shares, status, created_at)
                VALUES (?, ?, ?, 'redeem', ?, ?, 'completed', ?)
                """,
                (
                    order_id,
                    context.user_id,
                    target["product_id"],
                    amount_cents,
                    round(amount_cents / 100.0 * SIMULATED_NAV_CNY, 2),
                    now,
                ),
            )
            conn.execute(
                "UPDATE bank_accounts SET balance_cents = balance_cents + ?, "
                "available_cents = available_cents + ? WHERE user_id = ? AND account_id = ?",
                (amount_cents, amount_cents, context.user_id, SOURCE_ACCOUNT),
            )
            conn.execute(
                """
                INSERT INTO bank_transactions
                (transaction_id, user_id, account_id, card_id, merchant, category,
                 amount_cents, occurred_at, status, note)
                VALUES (?, ?, ?, NULL, ?, 'wealth', ?, ?, 'posted', ?)
                """,
                (
                    _new_id("TX-W"),
                    context.user_id,
                    SOURCE_ACCOUNT,
                    f"理财赎回-{product_name}",
                    amount_cents,
                    now,
                    DISCLAIMER,
                ),
            )

        refreshed = self.services.repository.account(context.user_id, SOURCE_ACCOUNT)
        return ToolResult(
            tool_name=self.metadata.name,
            message=(
                f"理财赎回已按模拟规则成交：{product_name} "
                f"{to_cny(amount_cents):.2f} 元，剩余市值 "
                f"{to_cny(remaining_market):.2f} 元。{DISCLAIMER}"
            ),
            data={
                "order_id": order_id,
                "holding_id": target["holding_id"],
                "product_id": target["product_id"],
                "product_name": product_name,
                "amount_cny": to_cny(amount_cents),
                "remaining_market_value_cny": to_cny(remaining_market),
                "remaining_principal_cny": to_cny(remaining_principal),
                "remaining_shares": remaining_shares,
                "holding_status": holding_status,
                "balance_after_cny": None if refreshed is None else refreshed.available_cny,
                "executed_at": now,
                "simulated": True,
                "disclaimer": DISCLAIMER,
            },
        )


def tools(services: CoreServices) -> list[BaseTool]:
    """Build this scenario's tool nodes from the shared service container."""
    return [
        ListWealthProductsTool(services),
        QueryWealthHoldingsTool(services),
        AssessWealthRiskTool(services),
        PurchaseWealthTool(services),
        RedeemWealthTool(services),
    ]


class PurchaseWealthRiskRule:
    """purchase_wealth is always red: money leaves the account into a product."""

    name = "purchase_wealth_risk"
    priority = 10

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "purchase_wealth":
            return None
        reasons = ["理财申购属于资金投入，需要强验证与二次身份校验。"]
        product_id = str(ctx.arguments.get("product_id") or "")
        product = _product(ctx.repository.db, product_id) if product_id else None
        if product is None:
            reasons.append("待申购产品的风险等级未知，按最高谨慎标准处理。")
        else:
            reasons.append(
                f"目标产品 {product['name']} 风险等级为 {product['risk_level']}，"
                "申购前请确认它与您的风险偏好和资金期限匹配。"
            )
        reasons.append(DISCLAIMER)
        return RiskGuess(level=RiskLevel.RED, score=85, reasons=reasons)


class RedeemWealthRiskRule:
    """Redemption by amount: <=1000 yuan yellow, >1000 yuan red."""

    name = "redeem_wealth_risk"
    priority = 20

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "redeem_wealth":
            return None
        amount_cents = _redeem_amount_cents(ctx.repository, ctx.user_id, ctx.arguments)
        if amount_cents is None:
            return RiskGuess(
                level=RiskLevel.RED,
                score=90,
                reasons=["无法从持仓确认赎回金额，按红色高风险处理。", DISCLAIMER],
            )
        amount_cny = to_cny(amount_cents)
        if amount_cny <= YELLOW_REDEEM_LIMIT_CNY:
            return RiskGuess(
                level=RiskLevel.YELLOW,
                score=40,
                reasons=[
                    f"赎回金额 {amount_cny:.2f} 元未超过 1000 元，按黄色操作确认。",
                    DISCLAIMER,
                ],
            )
        return RiskGuess(
            level=RiskLevel.RED,
            score=85,
            reasons=[
                f"赎回金额 {amount_cny:.2f} 元超过 1000 元阈值，需要红色强验证。",
                f"赎回资金将回到演示账户 {SOURCE_ACCOUNT}（模拟）。",
                DISCLAIMER,
            ],
        )


def risk_rules() -> list[RiskRule]:
    return [PurchaseWealthRiskRule(), RedeemWealthRiskRule()]


_RISK_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])R([1-5])(?![0-9])", re.IGNORECASE)
_PREFERENCE_WORDS = (
    ("保守", "R1"),
    ("稳健", "R2"),
    ("平衡", "R3"),
    ("成长", "R4"),
    ("进取", "R5"),
    ("激进", "R5"),
)
_QUERY_HINTS = ("有什么", "推荐", "哪些", "看看", "介绍", "列表")
_PURCHASE_VERBS = ("买入", "申购", "购买", "买")
_REDEEM_VERBS = ("赎回", "卖出", "卖掉", "卖")
_HOLDING_HINTS = ("持仓", "持有", "我的理财", "理财账户", "查询理财")
_ASSESS_HINTS = ("风险测评", "风险评估", "风险偏好", "风险承受")


def _risk_tokens(text: str) -> list[str]:
    levels: list[str] = []
    for match in _RISK_TOKEN_RE.finditer(text):
        level = f"R{match.group(1)}"
        if level not in levels:
            levels.append(level)
    return levels


def _preference_from_text(text: str) -> str | None:
    levels = _risk_tokens(text)
    if len(levels) == 1:
        return levels[0]
    for word, level in _PREFERENCE_WORDS:
        if word in text:
            return level
    return None


def _product_tokens(product: dict[str, Any]) -> list[str]:
    name = str(product["name"])
    kind = str(product["kind"])
    tokens = [name, kind]
    if name.endswith("A"):
        tokens.append(name[:-1])
    if kind.endswith("基金"):
        tokens.append(kind[:-2])
    unique: list[str] = []
    for token in tokens:
        if len(token) >= 2 and token not in unique:
            unique.append(token)
    return unique


def _match_products(
    instruction: str, products: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Match products by id, name/kind keyword, then risk level; never guesses."""
    upper = instruction.upper()
    for product in products:
        if str(product["product_id"]).upper() in upper:
            return [product]
    matched = [
        product
        for product in products
        if any(token in instruction for token in _product_tokens(product))
    ]
    risk_levels = _risk_tokens(instruction)
    if matched:
        if len(matched) > 1 and risk_levels:
            narrowed = [item for item in matched if item["risk_level"] in risk_levels]
            if narrowed:
                return narrowed
        return matched
    if risk_levels:
        return [item for item in products if item["risk_level"] in risk_levels]
    return []


def _intent_products(ctx: IntentContext) -> list[dict[str, Any]] | None:
    if ctx.repository is None:
        return None
    return _products(ctx.repository.db)


def _intent_holdings(ctx: IntentContext) -> list[dict[str, Any]] | None:
    if ctx.repository is None:
        return None
    return _holdings(ctx.repository.db, ctx.request.user_id)


def _plan(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    intent: str | None = None,
    assumptions: list[str] | None = None,
    description: str | None = None,
) -> ExecutionPlan:
    return ExecutionPlan(
        intent=intent or tool_name,
        planner="rule",
        confidence=0.92,
        assumptions=list(assumptions or []),
        steps=[
            PlanStep(
                id="step-1",
                tool_name=tool_name,
                arguments=arguments,
                description=description or f"执行 {tool_name}。",
            )
        ],
    )


def _clarify(message: str, intent: str) -> ExecutionPlan:
    return ExecutionPlan(
        intent=intent,
        planner="rule",
        confidence=0.25,
        needs_clarification=True,
        clarification=message,
    )


class PurchaseWealthIntent:
    name = "purchase_wealth"
    priority = 10

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("purchase_wealth"):
            return None
        text = ctx.instruction
        if not any(verb in text for verb in _PURCHASE_VERBS):
            return None
        has_wealth_context = any(word in text for word in ("理财", "基金", "产品"))
        if not has_wealth_context and not _risk_tokens(text):
            return None
        explicit_buy = any(verb in text for verb in ("买入", "申购", "购买"))
        if any(hint in text for hint in _QUERY_HINTS) and not explicit_buy:
            return None
        products = _intent_products(ctx)
        if products is None:
            return _clarify("理财数据尚未初始化，暂时无法申购。", self.name)
        matches = _match_products(text, products)
        if not matches:
            return _clarify(
                "未找到匹配的模拟理财产品，请补充产品名称或风险等级"
                "（如：稳健短债A / R2）。",
                self.name,
            )
        if len(matches) > 1:
            labels = "、".join(
                f"{item['name']}({item['risk_level']})" for item in matches
            )
            return _clarify(
                f"匹配到多个模拟理财产品（{labels}），"
                "请明确产品名称或风险等级后重试。",
                self.name,
            )
        product = matches[0]
        min_amount_cny = to_cny(product["min_amount_cents"])
        amounts = ctx.amounts()
        if not amounts:
            return _clarify(
                f"请补充申购金额，例如“买入 {product['name']} 5000 元”；"
                f"该产品起购金额为 {min_amount_cny:.2f} 元。",
                self.name,
            )
        amount_cny = amounts[0]
        if amount_cny < min_amount_cny:
            return _clarify(
                f"{product['name']} 起购金额为 {min_amount_cny:.2f} 元，"
                f"本次 {amount_cny:.2f} 元不足起购金额，请调整申购金额后重试。",
                self.name,
            )
        return _plan(
            "purchase_wealth",
            {"product_id": product["product_id"], "amount_cny": amount_cny},
            intent=self.name,
            assumptions=[
                f"已按产品关键词匹配到 {product['name']}（{product['risk_level']}）。",
                DISCLAIMER,
            ],
            description="申购模拟理财产品，红色操作需要二次身份校验。",
        )


class RedeemWealthIntent:
    name = "redeem_wealth"
    priority = 15

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("redeem_wealth"):
            return None
        text = ctx.instruction
        if not any(verb in text for verb in _REDEEM_VERBS):
            return None
        products = _intent_products(ctx)
        holdings = _intent_holdings(ctx)
        if products is None or holdings is None:
            return _clarify("理财数据尚未初始化，暂时无法赎回。", self.name)
        if not holdings:
            return _clarify("您当前没有可赎回的模拟理财持仓。", self.name)
        matches = _match_products(text, products)
        if len(matches) > 1:
            labels = "、".join(
                f"{item['name']}({item['risk_level']})" for item in matches
            )
            return _clarify(
                f"匹配到多个模拟理财产品（{labels}），"
                "请明确要赎回的产品名称或风险等级。",
                self.name,
            )
        assumptions: list[str] = []
        if matches:
            product = matches[0]
            product_holdings = [
                item for item in holdings if item["product_id"] == product["product_id"]
            ]
            if not product_holdings:
                return _clarify(
                    f"您当前没有 {product['name']} 的模拟持仓。", self.name
                )
            if len(product_holdings) > 1:
                return _clarify(
                    f"{product['name']} 存在多笔模拟持仓，"
                    "请在持仓列表中选择具体持仓后再赎回。",
                    self.name,
                )
            holding = product_holdings[0]
            assumptions.append(
                f"已按产品匹配到持仓 {holding['holding_id']}（{product['name']}）。"
            )
        else:
            if len(holdings) > 1:
                return _clarify(
                    "当前有多笔模拟理财持仓，请明确要赎回的产品名称。", self.name
                )
            holding = holdings[0]
            product = holding.get("product") or {}
            assumptions.append(
                f"未指定产品，默认赎回唯一持仓 {holding['holding_id']}"
                f"（{product.get('name', holding['product_id'])}）。"
            )
        arguments: dict[str, Any] = {"holding_id": holding["holding_id"]}
        amounts = ctx.amounts()
        if amounts:
            amount_cny = amounts[0]
            market_value_cents = int(holding["market_value_cents"])
            if to_cents(amount_cny) > market_value_cents:
                return _clarify(
                    f"赎回金额 {amount_cny:.2f} 元超过持仓市值 "
                    f"{to_cny(market_value_cents):.2f} 元。",
                    self.name,
                )
            arguments["amount_cny"] = amount_cny
        assumptions.append(DISCLAIMER)
        return _plan(
            "redeem_wealth",
            arguments,
            intent=self.name,
            assumptions=assumptions,
            description="赎回模拟理财持仓；金额超过 1000 元升级为红色强验证。",
        )


class QueryWealthHoldingsIntent:
    name = "query_wealth_holdings"
    priority = 20

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("query_wealth_holdings"):
            return None
        text = ctx.instruction
        if "产品" in text:
            return None
        if not any(word in text for word in _HOLDING_HINTS):
            return None
        return _plan(
            "query_wealth_holdings",
            {},
            intent=self.name,
            assumptions=["只读取模拟持仓数据。", DISCLAIMER],
            description="查询本人模拟理财持仓。",
        )


class AssessWealthRiskIntent:
    name = "assess_wealth_risk"
    priority = 25

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("assess_wealth_risk"):
            return None
        text = ctx.instruction
        if not any(word in text for word in _ASSESS_HINTS):
            return None
        preference = _preference_from_text(text)
        if preference is None:
            return _clarify(
                "请补充风险偏好等级（R1 保守型至 R5 进取型），"
                "例如“我的风险偏好是 R3”。",
                self.name,
            )
        return _plan(
            "assess_wealth_risk",
            {"risk_preference": preference},
            intent=self.name,
            assumptions=["风险测评结果只保存在本地模拟数据库。", DISCLAIMER],
            description="记录模拟风险偏好等级，用于申购时的风险提示。",
        )


class ListWealthProductsIntent:
    name = "list_wealth_products"
    priority = 30

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("list_wealth_products"):
            return None
        text = ctx.instruction
        if not any(word in text for word in ("理财", "基金")):
            return None
        if any(word in text for word in ("持仓", "持有", "赎回", "卖出")):
            return None
        return _plan(
            "list_wealth_products",
            {},
            intent=self.name,
            assumptions=["只返回模拟理财产品清单，不构成任何投资建议。", DISCLAIMER],
            description="列出模拟理财产品。",
        )


def intents() -> list[IntentRule]:
    return [
        PurchaseWealthIntent(),
        RedeemWealthIntent(),
        QueryWealthHoldingsIntent(),
        AssessWealthRiskIntent(),
        ListWealthProductsIntent(),
    ]


def router(services: CoreServices) -> APIRouter:
    from . import DEMO_USER

    api = APIRouter(prefix="/api/wealth", tags=["wealth"])

    @api.get("/products")
    def list_products(risk_level: str | None = None) -> dict[str, Any]:
        products = [_serialize_product(item) for item in _products(services.db)]
        if risk_level:
            wanted = risk_level.upper()
            products = [item for item in products if item["risk_level"] == wanted]
        return {
            "products": products,
            "count": len(products),
            "simulated": True,
            "message": "模拟理财产品清单。",
            "disclaimer": DISCLAIMER,
        }

    @api.get("/holdings")
    def list_holdings(user_id: str = DEMO_USER) -> dict[str, Any]:
        holdings = [
            _serialize_holding(item) for item in _holdings(services.db, user_id)
        ]
        return {
            "holdings": holdings,
            "count": len(holdings),
            "total_market_value_cny": round(
                sum(item["market_value_cny"] for item in holdings), 2
            ),
            "total_principal_cny": round(
                sum(item["principal_cny"] for item in holdings), 2
            ),
            "simulated": True,
            "message": "模拟理财持仓。",
            "disclaimer": DISCLAIMER,
        }

    @api.get("/orders")
    def list_orders(user_id: str = DEMO_USER) -> dict[str, Any]:
        with services.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM wealth_orders WHERE user_id = ? "
                "ORDER BY created_at DESC, order_id DESC",
                (user_id,),
            ).fetchall()
        products = {
            item["product_id"]: item for item in _products(services.db, active_only=False)
        }
        orders: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            product = products.get(item["product_id"]) or {}
            orders.append(
                {
                    "order_id": item["order_id"],
                    "product_id": item["product_id"],
                    "product_name": product.get("name", ""),
                    "side": item["side"],
                    "amount_cny": to_cny(item["amount_cents"]),
                    "shares": item["shares"],
                    "status": item["status"],
                    "created_at": item["created_at"],
                }
            )
        return {
            "orders": orders,
            "count": len(orders),
            "simulated": True,
            "message": "模拟理财委托单。",
            "disclaimer": DISCLAIMER,
        }

    return api