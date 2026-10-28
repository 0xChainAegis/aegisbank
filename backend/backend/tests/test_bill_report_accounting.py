"""Bill reports share account ownership and Shanghai periods with bank views."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from pathlib import Path

import pytest

from aegisbank_api.banking import repository as banking
from aegisbank_api.banking.repository import BankingRepository, to_cents
from aegisbank_api.db import Database
from aegisbank_api.domain import ExecutionContext
from aegisbank_api.scenarios import bills
from aegisbank_api.tools.finance import QueryBillTool

USER = "demo-user"
NOW = datetime(2026, 10, 28, 4, tzinfo=UTC)


def freeze(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

    monkeypatch.setattr(banking, "datetime", FrozenDateTime)
    monkeypatch.setattr(bills, "datetime", FrozenDateTime)


@pytest.fixture
def bank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BankingRepository:
    freeze(monkeypatch, NOW)
    bank = BankingRepository(Database(tmp_path / "bill-report-accounting.db"))
    with bank.db.transaction() as conn:
        conn.executescript(bills.SCHEMA_SQL)
    bills.seed(bank.db)
    return bank


def insert_debit(
    bank: BankingRepository,
    transaction_id: str,
    *,
    merchant: str,
    amount: float,
    category: str = "food",
    occurred_at: str = NOW.isoformat(),
) -> None:
    with bank.db.transaction() as conn:
        conn.execute(
            "INSERT INTO bank_transactions "
            "(transaction_id,user_id,account_id,card_id,merchant,category,"
            "amount_cents,occurred_at,status,note) "
            "VALUES (?,?,'ACC-1001',NULL,?,?,?,?,'posted',NULL)",
            (transaction_id, USER, merchant, category, -to_cents(amount), occurred_at),
        )


def test_internal_transfer_does_not_inflate_any_bill_report_or_hide_the_flow(bank):
    month_before = bills.build_bill_report(bank.db, USER)
    year_before = bills.build_bill_report(bank.db, USER, period="year")
    total_before = sum(item.balance_cny for item in bank.accounts(USER))
    result = bank.transfer(
        USER, {"from_account": "ACC-1001", "to_account": "ACC-2002", "amount_cny": 880}
    )
    month_after = bills.build_bill_report(bank.db, USER)
    year_after = bills.build_bill_report(bank.db, USER, period="year")
    for before, after in [(month_before, month_after), (year_before, year_after)]:
        assert after["total_spend_cny"] == before["total_spend_cny"]
        assert after["categories"] == before["categories"]
        assert after["top_merchants"] == before["top_merchants"]
        assert after["transaction_count"] == before["transaction_count"]
        assert after["all_transaction_count"] == before["all_transaction_count"] + 1
    query_bill = QueryBillTool(bank).execute(
        {"account_id": "ACC-1001"}, ExecutionContext(USER, "分析账单", "query", "query_bill")
    ).data
    assert query_bill["total_spend_cny"] == month_after["total_spend_cny"]
    assert query_bill["categories"] == month_after["categories"]
    assert any(row["transaction_id"] == result["transaction_id"]
               for row in query_bill["transactions"])
    assert bank.overview(USER).monthly_spend_cny == month_after["total_spend_cny"]
    assert sum(item.balance_cny for item in bank.accounts(USER)) == total_before
    assert bank.daily_transfer_total_cny(USER) == 880


@pytest.mark.parametrize("known_other_user", [False, True])
def test_external_transfer_stays_spending_for_month_and_year(bank, known_other_user):
    if known_other_user:
        with bank.db.transaction() as conn:
            conn.execute(
                "INSERT INTO bank_accounts VALUES "
                "('ACC-3003','other-user','外部账户','checking','CNY',100000,100000)"
            )
    before = bills.build_bill_report(bank.db, USER)
    before_year = bills.build_bill_report(bank.db, USER, period="year")
    bank.transfer(USER, {"from_account": "ACC-1001", "to_account": "ACC-3003", "amount_cny": 250})
    after = bills.build_bill_report(bank.db, USER)
    after_year = bills.build_bill_report(bank.db, USER, period="year")
    assert after["total_spend_cny"] == before["total_spend_cny"] + 250
    assert after_year["total_spend_cny"] == before_year["total_spend_cny"] + 250
    assert after["categories"]["transfer"] == 250
    assert bank.bill(USER, "ACC-1001").total_spend_cny == after["total_spend_cny"]
    assert bank.overview(USER).monthly_spend_cny == after["total_spend_cny"]
    assert bank.daily_transfer_total_cny(USER) == 250


def test_non_transfer_debit_with_an_owned_account_merchant_is_still_spending(bank):
    before = bills.build_bill_report(bank.db, USER)
    insert_debit(bank, "SHOP-OWN-NAME", merchant="ACC-2002", category="shopping", amount=20)
    after = bills.build_bill_report(bank.db, USER)
    assert after["total_spend_cny"] == before["total_spend_cny"] + 20
    assert after["categories"]["shopping"] == before["categories"]["shopping"] + 20


@pytest.mark.parametrize("hour,minute", [(0, 30), (7, 59), (8, 0)])
def test_month_report_uses_shanghai_start_end_and_default_period(bank, monkeypatch, hour, minute):
    freeze(monkeypatch, datetime(2026, 11, 1, hour, minute, tzinfo=banking.SHANGHAI_TZ))
    with bank.db.transaction() as conn:
        conn.execute("DELETE FROM bank_transactions")
    for transaction_id, occurred_at, amount in [
        ("OCT-END", "2026-10-31T15:59:59+00:00", 10),
        ("NOV-START", "2026-10-31T16:00:00+00:00", 20),
        ("NOV-EARLY", "2026-11-01T00:05:00+08:00", 30),
        ("DEC-START", "2026-11-30T16:00:00+00:00", 40),
    ]:
        insert_debit(bank, transaction_id, merchant="餐饮", amount=amount, occurred_at=occurred_at)
    insert_debit(bank, "NOV-INTERNAL", merchant="ACC-2002", amount=880, category="transfer",
                 occurred_at="2026-10-31T16:10:00+00:00")
    report = bills.build_bill_report(bank.db, USER)
    assert report["month"] == "2026-11"
    assert report["total_spend_cny"] == bank.bill(USER, "ACC-1001").total_spend_cny == 50
    assert report["total_spend_cny"] == bank.overview(USER).monthly_spend_cny
    assert report["categories"] == {"food": 50}
    assert report["all_transaction_count"] == 3
    assert report["comparison"]["previous_total_cny"] == 10
    assert bills.build_bill_report(bank.db, USER, period="2026-10")["total_spend_cny"] == 10
    assert bank.daily_transfer_total_cny(USER) == 880


def test_year_report_uses_shanghai_year_including_previous_year_comparison(bank, monkeypatch):
    freeze(monkeypatch, datetime(2027, 1, 1, 0, 30, tzinfo=banking.SHANGHAI_TZ))
    with bank.db.transaction() as conn:
        conn.execute("DELETE FROM bank_transactions")
    for transaction_id, occurred_at, amount in [
        ("2026-END", "2026-12-31T15:59:59+00:00", 10),
        ("2027-START", "2026-12-31T16:00:00+00:00", 20),
        ("2027-END", "2027-12-31T15:59:59+00:00", 30),
        ("2028-START", "2027-12-31T16:00:00+00:00", 40),
    ]:
        insert_debit(bank, transaction_id, merchant="餐饮", amount=amount, occurred_at=occurred_at)
    insert_debit(bank, "2027-INTERNAL", merchant="ACC-2002", amount=880, category="transfer",
                 occurred_at="2026-12-31T16:10:00+00:00")
    report = bills.build_bill_report(bank.db, USER, period="year")
    assert report["year"] == 2027
    assert report["total_spend_cny"] == 50
    assert report["categories"] == {"food": 50}
    assert report["all_transaction_count"] == 3
    assert report["comparison"]["previous_total_cny"] == 10
    assert bills.build_bill_report(bank.db, USER, period="2026")["total_spend_cny"] == 10
    assert bills.build_bill_report(bank.db, USER)["total_spend_cny"] == 20
    assert bank.bill(USER, "ACC-1001").total_spend_cny == 20
    assert bank.daily_transfer_total_cny(USER) == 880
