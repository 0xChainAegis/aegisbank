"""Internal transfers preserve assets without inflating reported spending."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from pathlib import Path

import pytest

from aegisbank_api.banking import repository as banking
from aegisbank_api.banking.repository import BankingRepository, to_cents
from aegisbank_api.db import Database

USER = "demo-user"
FIXED_NOW = datetime(2026, 10, 28, 4, 0, tzinfo=UTC)


def freeze_clock(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

    monkeypatch.setattr(banking, "datetime", FrozenDateTime)


@pytest.fixture
def bank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BankingRepository:
    freeze_clock(monkeypatch, FIXED_NOW)
    return BankingRepository(Database(tmp_path / "internal-transfers.db"))


def balances(bank: BankingRepository) -> dict[str, float]:
    return {account.account_id: account.balance_cny for account in bank.accounts(USER)}


def insert_legacy_debit(
    bank: BankingRepository,
    *,
    transaction_id: str,
    merchant: str,
    amount_cny: float,
    category: str = "transfer",
    occurred_at: str = FIXED_NOW.isoformat(),
) -> None:
    """Use only columns present before the accounting fix, with no new flags."""
    with bank.db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO bank_transactions
                (transaction_id, user_id, account_id, card_id, merchant, category,
                 amount_cents, occurred_at, status, note)
            VALUES (?, ?, 'ACC-1001', NULL, ?, ?, ?, ?, 'posted', NULL)
            """,
            (transaction_id, USER, merchant, category, -to_cents(amount_cny), occurred_at),
        )


def test_internal_transfer_preserves_assets_spending_and_categories(
    bank: BankingRepository,
) -> None:
    before_balances = balances(bank)
    before_bill = bank.bill(USER, "ACC-1001")
    before_month = bank.monthly_spend_cny(USER)
    before_daily = bank.daily_transfer_total_cny(USER)

    result = bank.transfer(
        USER, {"from_account": "ACC-1001", "to_account": "ACC-2002", "amount_cny": 880}
    )

    after_balances = balances(bank)
    assert after_balances["ACC-1001"] == before_balances["ACC-1001"] - 880
    assert after_balances["ACC-2002"] == before_balances["ACC-2002"] + 880
    assert sum(after_balances.values()) == sum(before_balances.values())
    assert bank.monthly_spend_cny(USER) == before_month
    after_bill = bank.bill(USER, "ACC-1001")
    assert after_bill.total_spend_cny == before_bill.total_spend_cny
    assert after_bill.categories == before_bill.categories
    assert len(after_bill.transactions) == len(before_bill.transactions) + 1
    transfer_row = next(
        row for row in after_bill.transactions if row["transaction_id"] == result["transaction_id"]
    )
    assert transfer_row["category"] == "transfer"
    assert transfer_row["amount_cny"] == -880
    assert transfer_row["merchant"] == "ACC-2002"
    assert transfer_row["status"] == "posted"
    assert bank.daily_transfer_total_cny(USER) == before_daily + 880
    assert result["daily_transfer_total_cny"] == before_daily + 880
    overview = bank.overview(USER)
    assert overview.monthly_spend_cny == before_month
    assert overview.daily_transfer_total_cny == before_daily + 880


@pytest.mark.parametrize("known_other_user", [False, True])
def test_external_transfer_remains_spending_even_if_destination_exists_for_another_user(
    bank: BankingRepository, known_other_user: bool
) -> None:
    destination = "ACC-3003"
    if known_other_user:
        with bank.db.transaction() as conn:
            conn.execute(
                "INSERT INTO bank_accounts VALUES (?, ?, ?, ?, 'CNY', 100000, 100000)",
                (destination, "another-user", "另一个用户的账户", "checking"),
            )
    before = bank.monthly_spend_cny(USER)
    before_bill = bank.bill(USER, "ACC-1001")
    before_total = sum(balances(bank).values())

    result = bank.transfer(
        USER, {"from_account": "ACC-1001", "to_account": destination, "amount_cny": 250}
    )

    assert bank.monthly_spend_cny(USER) == before + 250
    assert sum(balances(bank).values()) == before_total - 250
    bill = bank.bill(USER, "ACC-1001")
    assert bill.total_spend_cny == before_bill.total_spend_cny + 250
    assert bill.categories["transfer"] == 250
    assert any(row["transaction_id"] == result["transaction_id"] for row in bill.transactions)
    assert bank.daily_transfer_total_cny(USER) == 250


def test_existing_internal_transfer_rows_are_excluded_without_schema_migration(
    bank: BankingRepository,
) -> None:
    before = bank.monthly_spend_cny(USER)
    before_bill = bank.bill(USER, "ACC-1001")
    insert_legacy_debit(bank, transaction_id="OLD-INTERNAL", merchant="ACC-2002", amount_cny=880)
    insert_legacy_debit(bank, transaction_id="OLD-EXTERNAL", merchant="ACC-9999", amount_cny=125)

    reopened = BankingRepository(bank.db)
    assert reopened.monthly_spend_cny(USER) == before + 125
    bill = reopened.bill(USER, "ACC-1001")
    assert bill.total_spend_cny == before_bill.total_spend_cny + 125
    assert bill.categories["transfer"] == 125
    assert {"OLD-INTERNAL", "OLD-EXTERNAL"} <= {
        row["transaction_id"] for row in bill.transactions
    }
    assert reopened.daily_transfer_total_cny(USER) == 1005


def test_non_transfer_debit_is_not_excluded_by_a_merchant_matching_an_owned_account(
    bank: BankingRepository,
) -> None:
    before = bank.monthly_spend_cny(USER)
    before_bill = bank.bill(USER, "ACC-1001")
    insert_legacy_debit(
        bank, transaction_id="SHOP-ACCOUNT-LABEL", merchant="ACC-2002",
        amount_cny=20, category="shopping",
    )

    assert bank.monthly_spend_cny(USER) == before + 20
    bill = bank.bill(USER, "ACC-1001")
    assert bill.total_spend_cny == before_bill.total_spend_cny + 20
    assert bill.categories["shopping"] == before_bill.categories["shopping"] + 20
    assert bank.daily_transfer_total_cny(USER) == 0


@pytest.mark.parametrize("hour,minute", [(0, 30), (7, 59), (8, 0)])
def test_bill_and_monthly_spending_share_shanghai_month_boundaries(
    bank: BankingRepository, monkeypatch: pytest.MonkeyPatch, hour: int, minute: int
) -> None:
    freeze_clock(monkeypatch, datetime(2026, 11, 1, hour, minute, tzinfo=banking.SHANGHAI_TZ))
    with bank.db.transaction() as conn:
        conn.execute("DELETE FROM bank_transactions")
    for transaction_id, occurred_at, amount in [
        ("PREVIOUS-MONTH", "2026-10-31T15:59:59+00:00", 10),
        ("MONTH-START", "2026-10-31T16:00:00+00:00", 20),
        ("NEW-MONTH-EARLY", "2026-10-31T16:05:00+00:00", 30),
        ("NEXT-MONTH", "2026-11-30T16:00:00+00:00", 40),
    ]:
        insert_legacy_debit(
            bank, transaction_id=transaction_id, merchant="餐饮",
            category="food", amount_cny=amount, occurred_at=occurred_at,
        )
    insert_legacy_debit(
        bank, transaction_id="NEW-MONTH-INTERNAL", merchant="ACC-2002", amount_cny=880,
        occurred_at="2026-10-31T16:10:00+00:00",
    )

    bill = bank.bill(USER, "ACC-1001")
    assert bill.month == "2026-11"
    assert bill.total_spend_cny == bank.monthly_spend_cny(USER) == 50
    assert bill.categories == {"food": 50}
    assert {row["transaction_id"] for row in bill.transactions} == {
        "MONTH-START", "NEW-MONTH-EARLY", "NEW-MONTH-INTERNAL"
    }
    assert bank.daily_transfer_total_cny(USER) == 880
    assert bank.overview(USER).monthly_spend_cny == bill.total_spend_cny

    previous_bill = bank.bill(USER, "ACC-1001", period="2026-10")
    assert previous_bill.month == "2026-10"
    assert previous_bill.total_spend_cny == 10
    assert {row["transaction_id"] for row in previous_bill.transactions} == {"PREVIOUS-MONTH"}


def test_invalid_explicit_month_retains_an_empty_bill(bank: BankingRepository) -> None:
    bill = bank.bill(USER, "ACC-1001", period="2026-13")
    assert bill.month == "2026-13"
    assert bill.total_spend_cny == 0
    assert bill.categories == {}
    assert bill.transactions == []
