"""SQLite-backed deterministic mock bank core.

The repository is intentionally boring: all balances, cards, bills and
subscriptions come from here, so tools and the LLM cannot invent financial
facts. It is a demo adapter, not a core-banking integration.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..db import Database
from .models import (
    AccountInfo,
    BankingOverview,
    BillAnalysis,
    CardInfo,
    SubscriptionInfo,
)

CENT = Decimal("0.01")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def to_cents(value: float | str | Decimal) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("金额必须为有限数。")
    amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    return int(amount * 100)


def to_cny(cents: int) -> float:
    return float((Decimal(cents) / 100).quantize(CENT, rounding=ROUND_HALF_UP))


def _shanghai_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(SHANGHAI_TZ)


def _banking_day_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    local = _shanghai_now(now)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _banking_month_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    local = _shanghai_now(now)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.astimezone(UTC), end.astimezone(UTC)


class BankingRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_schema()
        self.seed_demo()

    def _ensure_schema(self) -> None:
        with self.db.transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bank_accounts (
                    account_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'CNY',
                    balance_cents INTEGER NOT NULL,
                    available_cents INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bank_cards (
                    card_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    masked_number TEXT NOT NULL,
                    status TEXT NOT NULL,
                    credit_limit_cents INTEGER NOT NULL,
                    available_limit_cents INTEGER NOT NULL,
                    repayment_day INTEGER NOT NULL,
                    transaction_limit_cents INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bank_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    card_id TEXT,
                    merchant TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT
                );

                CREATE TABLE IF NOT EXISTS bank_subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    cycle TEXT NOT NULL,
                    next_charge_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk_flag TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_bank_tx_user_date
                    ON bank_transactions(user_id, occurred_at);
                """
            )

    def seed_demo(self) -> None:
        today = _shanghai_now().date()
        with self.db.transaction() as conn:
            exists = conn.execute(
                "SELECT COUNT(*) AS n FROM bank_accounts WHERE user_id = ?",
                ("demo-user",),
            ).fetchone()["n"]
            if exists:
                return

            accounts = [
                ("ACC-1001", "demo-user", "工资卡", "checking", "CNY", 2865000, 2865000),
                ("ACC-2002", "demo-user", "日常储蓄", "savings", "CNY", 1200000, 1200000),
            ]
            conn.executemany(
                "INSERT INTO bank_accounts VALUES (?, ?, ?, ?, ?, ?, ?)",
                accounts,
            )
            cards = [
                (
                    "CARD-8821",
                    "demo-user",
                    "ACC-1001",
                    "**** 8821",
                    "active",
                    3000000,
                    2175000,
                    8,
                    1000000,
                ),
                (
                    "CARD-9902",
                    "demo-user",
                    "ACC-1001",
                    "**** 9902",
                    "active",
                    1500000,
                    1500000,
                    20,
                    500000,
                ),
            ]
            conn.executemany(
                "INSERT INTO bank_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                cards,
            )

            raw_transactions = [
                (today - timedelta(days=12), "工资入账", "income", 18500.00, None),
                (today - timedelta(days=5), "城市生活超市", "shopping", -286.40, None),
                (today - timedelta(days=4), "地铁出行", "transport", -54.00, None),
                (today - timedelta(days=3), "云端影音", "subscription", -45.00, "SUB-3001"),
                (today - timedelta(days=2), "AI 工具订阅", "subscription", -199.00, "SUB-3002"),
                (today - timedelta(days=2), "健身房月卡", "subscription", -299.00, "SUB-3003"),
                (today - timedelta(days=1), "午餐", "food", -68.00, None),
                (today - timedelta(days=1), "咖啡店", "food", -32.00, None),
                (today - timedelta(days=1), "电商购物", "shopping", -128.00, None),
                (today - timedelta(days=0), "早餐", "food", -23.00, None),
            ]
            for index, item in enumerate(raw_transactions, 1):
                day, merchant, category, amount, subscription_id = item
                conn.execute(
                    """
                    INSERT INTO bank_transactions
                    (transaction_id, user_id, account_id, card_id, merchant, category,
                     amount_cents, occurred_at, status, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?)
                    """,
                    (
                        f"TX-SEED-{index:03d}",
                        "demo-user",
                        "ACC-1001",
                        "CARD-8821",
                        merchant,
                        category,
                        to_cents(amount),
                        f"{day.isoformat()}T09:00:00+00:00",
                        subscription_id,
                    ),
                )

            subscriptions = [
                (
                    "SUB-3001",
                    "demo-user",
                    "云端影音",
                    4500,
                    "monthly",
                    (today + timedelta(days=9)).isoformat(),
                    "active",
                    None,
                ),
                (
                    "SUB-3002",
                    "demo-user",
                    "AI 工具订阅",
                    19900,
                    "monthly",
                    (today + timedelta(days=6)).isoformat(),
                    "active",
                    "本月扣费较上月上涨 120%",
                ),
                (
                    "SUB-3003",
                    "demo-user",
                    "健身房月卡",
                    29900,
                    "monthly",
                    (today + timedelta(days=14)).isoformat(),
                    "active",
                    None,
                ),
            ]
            conn.executemany(
                "INSERT INTO bank_subscriptions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                subscriptions,
            )

    def _account_row(self, row: sqlite3.Row) -> AccountInfo:
        return AccountInfo(
            account_id=row["account_id"],
            name=row["name"],
            kind=row["kind"],
            currency=row["currency"],
            balance_cny=to_cny(row["balance_cents"]),
            available_cny=to_cny(row["available_cents"]),
        )

    def _card_row(self, row: sqlite3.Row) -> CardInfo:
        return CardInfo(
            card_id=row["card_id"],
            account_id=row["account_id"],
            masked_number=row["masked_number"],
            status=row["status"],
            credit_limit_cny=to_cny(row["credit_limit_cents"]),
            available_limit_cny=to_cny(row["available_limit_cents"]),
            repayment_day=row["repayment_day"],
            transaction_limit_cny=to_cny(row["transaction_limit_cents"]),
        )

    def _subscription_row(self, row: sqlite3.Row) -> SubscriptionInfo:
        return SubscriptionInfo(
            subscription_id=row["subscription_id"],
            merchant=row["merchant"],
            amount_cny=to_cny(row["amount_cents"]),
            cycle=row["cycle"],
            next_charge_date=row["next_charge_date"],
            status=row["status"],
            risk_flag=row["risk_flag"],
        )

    def accounts(self, user_id: str) -> list[AccountInfo]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bank_accounts WHERE user_id = ? ORDER BY account_id",
                (user_id,),
            ).fetchall()
        return [self._account_row(row) for row in rows]

    def account(self, user_id: str, account_id: str) -> AccountInfo | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM bank_accounts WHERE user_id = ? AND account_id = ?",
                (user_id, account_id),
            ).fetchone()
        return None if row is None else self._account_row(row)

    def cards(self, user_id: str) -> list[CardInfo]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bank_cards WHERE user_id = ? ORDER BY card_id",
                (user_id,),
            ).fetchall()
        return [self._card_row(row) for row in rows]

    def card(self, user_id: str, card_id: str) -> CardInfo | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM bank_cards WHERE user_id = ? AND card_id = ?",
                (user_id, card_id),
            ).fetchone()
        return None if row is None else self._card_row(row)

    def subscriptions(self, user_id: str) -> list[SubscriptionInfo]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bank_subscriptions WHERE user_id = ? ORDER BY subscription_id",
                (user_id,),
            ).fetchall()
        return [self._subscription_row(row) for row in rows]

    def subscription(self, user_id: str, subscription_id: str) -> SubscriptionInfo | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM bank_subscriptions WHERE user_id = ? AND subscription_id = ?",
                (user_id, subscription_id),
            ).fetchone()
        return None if row is None else self._subscription_row(row)

    def monthly_spend_cny(
        self, user_id: str, *, now: datetime | None = None
    ) -> float:
        """Sum debits in the current Asia/Shanghai banking month.

        ``occurred_at`` values are stored as ISO-8601 timestamps (normally UTC).
        SQLite's ``julianday`` comparison converts both the stored instant and
        the Shanghai month boundaries to the same UTC instant, so a timestamp
        at 00:30 Beijing time belongs to the new month even though its UTC date
        is still the previous day.
        """
        start, end = _banking_month_bounds_utc(now)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(-amount_cents), 0) AS cents FROM bank_transactions "
                "WHERE user_id = ? AND amount_cents < 0 "
                "AND julianday(occurred_at) >= julianday(?) "
                "AND julianday(occurred_at) < julianday(?)",
                (user_id, start.isoformat(), end.isoformat()),
            ).fetchone()
        return to_cny(row["cents"])

    def daily_transfer_total_cny(
        self, user_id: str, *, now: datetime | None = None
    ) -> float:
        """Sum outgoing transfers in the current Asia/Shanghai banking day."""
        start, end = _banking_day_bounds_utc(now)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(-amount_cents), 0) AS cents FROM bank_transactions "
                "WHERE user_id = ? AND category = 'transfer' AND amount_cents < 0 "
                "AND julianday(occurred_at) >= julianday(?) "
                "AND julianday(occurred_at) < julianday(?)",
                (user_id, start.isoformat(), end.isoformat()),
            ).fetchone()
        return to_cny(row["cents"])

    def bill(self, user_id: str, account_id: str, period: str = "current_month") -> BillAnalysis:
        account = self.account(user_id, account_id)
        if account is None:
            raise ValueError(f"账户不存在：{account_id}")
        month = _shanghai_now().date().strftime("%Y-%m")
        if period != "current_month" and len(period) == 7 and period[4] == "-":
            month = period
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bank_transactions WHERE user_id = ? AND account_id = ? "
                "AND occurred_at LIKE ? ORDER BY occurred_at DESC, transaction_id DESC",
                (user_id, account_id, f"{month}%"),
            ).fetchall()
            subscriptions = conn.execute(
                "SELECT * FROM bank_subscriptions WHERE user_id = ? AND status = 'active' "
                "ORDER BY subscription_id",
                (user_id,),
            ).fetchall()

        categories: dict[str, float] = {}
        spend_cents = 0
        transactions: list[dict[str, Any]] = []
        for row in rows:
            amount = to_cny(row["amount_cents"])
            if row["amount_cents"] < 0:
                spend_cents += -row["amount_cents"]
                categories[row["category"]] = round(
                    categories.get(row["category"], 0.0) + abs(amount), 2
                )
            transactions.append(
                {
                    "transaction_id": row["transaction_id"],
                    "date": row["occurred_at"][:10],
                    "merchant": row["merchant"],
                    "category": row["category"],
                    "amount_cny": amount,
                    "status": row["status"],
                }
            )

        suspicious = next(
            (self._subscription_row(row) for row in subscriptions if row["risk_flag"]),
            None,
        )
        anomalies: list[str] = []
        if suspicious:
            anomalies.append(
                f"{suspicious.merchant}（{suspicious.subscription_id}）"
                f"存在订阅异常：{suspicious.risk_flag}"
            )
        subscription_spend = categories.get("subscription", 0.0)
        if subscription_spend > 0:
            anomalies.append(f"本月订阅类支出合计 {subscription_spend:.2f} 元，请核对续费项目。")
        if not anomalies:
            anomalies.append("本月未发现明显异常交易。")

        return BillAnalysis(
            account_id=account_id,
            period=period,
            month=month,
            total_spend_cny=to_cny(spend_cents),
            categories=categories,
            anomalies=anomalies,
            suspicious_subscription_id=suspicious.subscription_id if suspicious else None,
            suspicious_subscription_name=suspicious.merchant if suspicious else None,
            transactions=transactions,
        )

    def overview(self, user_id: str) -> BankingOverview:
        sub = next((item for item in self.subscriptions(user_id) if item.risk_flag), None)
        return BankingOverview(
            accounts=self.accounts(user_id),
            cards=self.cards(user_id),
            subscriptions=self.subscriptions(user_id),
            monthly_spend_cny=self.monthly_spend_cny(user_id),
            daily_transfer_total_cny=self.daily_transfer_total_cny(user_id),
            suspicious_subscription_id=sub.subscription_id if sub else None,
            suspicious_reason=sub.risk_flag if sub else None,
        )

    def transfer(self, user_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from_account = str(arguments["from_account"])
        to_account = str(arguments["to_account"])
        amount_cents = to_cents(float(arguments["amount_cny"]))
        if amount_cents <= 0:
            raise ValueError("转账金额必须至少为 0.01 元。")
        if from_account == to_account:
            raise ValueError("转出账户与转入账户不能相同")
        source = self.account(user_id, from_account)
        if source is None:
            raise ValueError(f"转出账户不存在：{from_account}")
        if source.available_cny * 100 < amount_cents:
            raise ValueError("转出账户可用余额不足")
        transaction_id = f"TX-{uuid4().hex[:12].upper()}"
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            updated = conn.execute(
                "UPDATE bank_accounts SET balance_cents = balance_cents - ?, "
                "available_cents = available_cents - ? WHERE user_id = ? AND account_id = ? "
                "AND available_cents >= ? AND balance_cents >= ?",
                (amount_cents, amount_cents, user_id, from_account, amount_cents, amount_cents),
            ).rowcount
            if updated != 1:
                raise ValueError("转出账户可用余额不足，已拒绝并发扣款。")
            target = conn.execute(
                "SELECT account_id FROM bank_accounts WHERE user_id = ? AND account_id = ?",
                (user_id, to_account),
            ).fetchone()
            if target:
                conn.execute(
                    "UPDATE bank_accounts SET balance_cents = balance_cents + ?, "
                    "available_cents = available_cents + ? WHERE user_id = ? AND account_id = ?",
                    (amount_cents, amount_cents, user_id, to_account),
                )
            conn.execute(
                """
                INSERT INTO bank_transactions
                (transaction_id, user_id, account_id, card_id, merchant, category,
                 amount_cents, occurred_at, status, note)
                VALUES (?, ?, ?, NULL, ?, 'transfer', ?, ?, 'posted', ?)
                """,
                (
                    transaction_id,
                    user_id,
                    from_account,
                    to_account,
                    -amount_cents,
                    now,
                    str(arguments.get("note") or "AegisBank 转账"),
                ),
            )
        return {
            "transaction_id": transaction_id,
            "from_account": from_account,
            "to_account": to_account,
            "amount_cny": to_cny(amount_cents),
            "daily_transfer_total_cny": self.daily_transfer_total_cny(user_id),
            "status": "simulated_success",
            "executed_at": now,
            "simulated": True,
        }

    def adjust_repayment_date(self, user_id: str, card_id: str, new_day: int) -> dict[str, Any]:
        card = self.card(user_id, card_id)
        if card is None:
            raise ValueError(f"卡片不存在：{card_id}")
        if not 1 <= new_day <= 28:
            raise ValueError("还款日必须在 1 至 28 日之间")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE bank_cards SET repayment_day = ? WHERE user_id = ? AND card_id = ?",
                (new_day, user_id, card_id),
            )
        return {
            "card_id": card_id,
            "previous_day": card.repayment_day,
            "new_day": new_day,
            "status": "updated",
            "simulated": True,
        }

    def adjust_card_limit(self, user_id: str, card_id: str, new_limit_cny: float) -> dict[str, Any]:
        card = self.card(user_id, card_id)
        if card is None:
            raise ValueError(f"卡片不存在：{card_id}")
        if new_limit_cny <= 0:
            raise ValueError("信用额度必须大于 0")
        limit_cents = to_cents(new_limit_cny)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT credit_limit_cents, available_limit_cents FROM bank_cards "
                "WHERE user_id = ? AND card_id = ?",
                (user_id, card_id),
            ).fetchone()
            used_cents = max(0, int(row["credit_limit_cents"]) - int(row["available_limit_cents"]))
            if limit_cents < used_cents:
                raise ValueError("目标信用额度低于已用额度，不能直接调整。")
            conn.execute(
                "UPDATE bank_cards SET credit_limit_cents = ?, available_limit_cents = ? "
                "WHERE user_id = ? AND card_id = ?",
                (limit_cents, limit_cents - used_cents, user_id, card_id),
            )
        return {
            "card_id": card_id,
            "previous_limit_cny": card.credit_limit_cny,
            "new_limit_cny": new_limit_cny,
            "status": "updated",
            "simulated": True,
        }

    def set_transaction_limit(
        self, user_id: str, card_id: str, daily_limit_cny: float
    ) -> dict[str, Any]:
        card = self.card(user_id, card_id)
        if card is None:
            raise ValueError(f"卡片不存在：{card_id}")
        if daily_limit_cny <= 0:
            raise ValueError("交易限额必须大于 0")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE bank_cards SET transaction_limit_cents = ? "
                "WHERE user_id = ? AND card_id = ?",
                (to_cents(daily_limit_cny), user_id, card_id),
            )
        return {
            "card_id": card_id,
            "daily_limit_cny": daily_limit_cny,
            "status": "updated",
            "simulated": True,
        }

    def set_card_status(self, user_id: str, card_id: str, status: str) -> dict[str, Any]:
        card = self.card(user_id, card_id)
        if card is None:
            raise ValueError(f"卡片不存在：{card_id}")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE bank_cards SET status = ? WHERE user_id = ? AND card_id = ?",
                (status, user_id, card_id),
            )
        return {"card_id": card_id, "status": status, "simulated": True}

    def cancel_subscription(self, user_id: str, subscription_id: str) -> dict[str, Any]:
        subscription = self.subscription(user_id, subscription_id)
        if subscription is None:
            raise ValueError(f"订阅不存在：{subscription_id}")
        if subscription.status != "active":
            raise ValueError(f"订阅当前不是 active 状态：{subscription_id}")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE bank_subscriptions SET status = 'cancelled' "
                "WHERE user_id = ? AND subscription_id = ?",
                (user_id, subscription_id),
            )
        return {
            "subscription_id": subscription_id,
            "merchant": subscription.merchant,
            "amount_cny": subscription.amount_cny,
            "status": "cancelled",
            "simulated": True,
        }

    def suspicious_subscription_id(self, user_id: str) -> str | None:
        item = next((sub for sub in self.subscriptions(user_id) if sub.risk_flag), None)
        return item.subscription_id if item else None
