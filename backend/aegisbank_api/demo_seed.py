"""One-off demo provisioning for onboarding: a 3000 CNY virtual card.

This module is **not** imported by the running application: it seeds a demo
SQLite database (by default ``backend/data/dogfood.db``) so a first-time user
can immediately see and use a "virtual card" with a 3000 CNY deposit.

Usage::

    cd backend
    uv run python -m aegisbank_api.demo_seed --db data/dogfood.db --reset

``--reset`` removes the database (and its WAL/SHM files) first, so the demo
starts from a clean, deterministic state; without it the seed is idempotent.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .banking.repository import BankingRepository, to_cents
from .db import Database, utc_now

VIRTUAL_ACCOUNT_ID = "ACC-3003"
VIRTUAL_CARD_ID = "CARD-9001"
VIRTUAL_CARD_MASKED = "**** 9001"
VIRTUAL_AMOUNT_CNY = 3000.0
DEMO_USER = "demo-user"


def _remove_db_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def seed_virtual_card(db_path: str | Path, *, reset: bool = False) -> dict[str, Any]:
    """Ensure the database exists and contains the demo virtual card."""
    path = Path(db_path)
    if reset:
        _remove_db_files(path)

    db = Database(path)
    # Base seed (accounts/cards/transactions/subscriptions) runs on first use.
    BankingRepository(db)

    cents = to_cents(VIRTUAL_AMOUNT_CNY)
    now = utc_now()
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO bank_accounts
            (account_id, user_id, name, kind, currency, balance_cents, available_cents)
            VALUES (?, ?, ?, ?, 'CNY', ?, ?)
            """,
            (VIRTUAL_ACCOUNT_ID, DEMO_USER, "虚拟卡账户", "virtual_card", cents, cents),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO bank_cards
            (card_id, user_id, account_id, masked_number, status,
             credit_limit_cents, available_limit_cents, repayment_day,
             transaction_limit_cents)
            VALUES (?, ?, ?, ?, 'active', ?, ?, 8, ?)
            """,
            (
                VIRTUAL_CARD_ID,
                DEMO_USER,
                VIRTUAL_ACCOUNT_ID,
                VIRTUAL_CARD_MASKED,
                cents,
                cents,
                cents,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO bank_transactions
            (transaction_id, user_id, account_id, card_id, merchant, category,
             amount_cents, occurred_at, status, note)
            VALUES ('TX-VCARD-001', ?, ?, ?, '虚拟卡开卡入金', 'income', ?, ?,
                    'posted', '演示用虚拟卡初始存款 3000 元')
            """,
            (DEMO_USER, VIRTUAL_ACCOUNT_ID, VIRTUAL_CARD_ID, cents, now),
        )

    return {
        "db_path": str(path),
        "reset": reset,
        "account_id": VIRTUAL_ACCOUNT_ID,
        "card_id": VIRTUAL_CARD_ID,
        "masked_number": VIRTUAL_CARD_MASKED,
        "balance_cny": VIRTUAL_AMOUNT_CNY,
        "deposit_transaction_id": "TX-VCARD-001",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisBank demo virtual-card seed")
    parser.add_argument(
        "--db",
        default=str(Path("data") / "dogfood.db"),
        help="SQLite database path (relative paths are resolved from backend/)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the existing database first for a clean demo",
    )
    args = parser.parse_args()
    result = seed_virtual_card(args.db, reset=args.reset)
    print("[demo-seed] 虚拟卡已就绪：", result)


if __name__ == "__main__":
    main()
