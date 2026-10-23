"""Data contracts for legacy tools that predate dedicated Pydantic outputs.

Each contract requires semantic result fields as well as the Mock marker.
Dedicated tool schemas take precedence. Additional evidence fields remain extensible.
"""

from __future__ import annotations

from typing import Any

STRING = {"type": "string", "minLength": 1}
MONEY = {"type": "number", "minimum": 0}
INTEGER = {"type": "integer", "minimum": 0}
OBJECT = {"type": "object"}
ARRAY = {"type": "array"}
BOOLEAN = {"type": "boolean"}
NULLABLE_STRING = {"type": ["string", "null"]}

CARD_RESULT = {"card_id": STRING, "status": STRING}
DAY_RESULT = {**CARD_RESULT, "previous_day": INTEGER, "new_day": INTEGER}
LIMIT_RESULT = {**CARD_RESULT, "previous_limit_cny": MONEY, "new_limit_cny": MONEY}
TRANSACTION_LIMIT_RESULT = {**CARD_RESULT, "daily_limit_cny": MONEY}
GIFT_RESULT = {
    "order_id": STRING,
    "task_id": STRING,
    "goal_id": STRING,
    "gift_kind": STRING,
    "amount_cny": MONEY,
    "birthday": STRING,
    "due_at": STRING,
    "status": STRING,
}
DEMO_RESULT = {"entry_id": STRING, "kind": STRING, "status": STRING}

CONTRACTS: dict[str, dict[str, Any]] = {
    "adjust_repayment_date": DAY_RESULT,
    "adjust_card_limit": LIMIT_RESULT,
    "set_transaction_limit": TRANSACTION_LIMIT_RESULT,
    "report_card_lost": CARD_RESULT,
    "unlock_card": CARD_RESULT,
    "list_subscriptions": {"subscriptions": ARRAY},
    "cancel_subscription": {
        "subscription_id": STRING,
        "merchant": STRING,
        "amount_cny": MONEY,
        "status": STRING,
    },
    "query_contact_birthday": {
        "contact": OBJECT,
        "birthday": STRING,
        "next_birthday": STRING,
        "days_until": INTEGER,
    },
    "lock_budget_funds": {
        "goal_id": STRING,
        "name": STRING,
        "target_cny": MONEY,
        "locked_cny": MONEY,
        "status": STRING,
        "account_id": STRING,
    },
    "unlock_budget_funds": {
        "goal_id": STRING,
        "released_cny": MONEY,
        "status": STRING,
        "cancelled_task_ids": ARRAY,
        "account_id": STRING,
    },
    "schedule_flower_order": GIFT_RESULT,
    "schedule_cake_order": GIFT_RESULT,
    "schedule_transfer": {
        "task_id": STRING,
        "kind": STRING,
        "status": STRING,
        "run_at": STRING,
        "recurrence": STRING,
        "amount_cny": MONEY,
        "from_account": STRING,
        "to_account": STRING,
    },
    "list_scheduled_tasks": {"tasks": ARRAY, "count": INTEGER},
    "cancel_scheduled_task": {
        "task_id": STRING,
        "kind": STRING,
        "status": STRING,
        "run_at": STRING,
    },
    "run_due_tasks": {
        "now": STRING,
        "executed": ARRAY,
        "failed": ARRAY,
        "executed_count": INTEGER,
        "failed_count": INTEGER,
    },
    "execute_gift_order": {
        "task_id": STRING,
        "order_id": STRING,
        "gift_kind": STRING,
        "amount_cny": MONEY,
    },
    "list_contacts": {"contacts": ARRAY, "count": INTEGER},
    "add_contact": {"contact": OBJECT, "status": STRING},
    "transfer_to_contact": {"contact": OBJECT, "transfer": OBJECT, "amount_cny": MONEY},
    "reverse_transfer": {
        "reversal_transaction_id": STRING,
        "from_account": STRING,
        "to_account": STRING,
        "amount_cny": MONEY,
        "status": STRING,
    },
    "restore_repayment_date": {**DAY_RESULT, "restored": BOOLEAN},
    "restore_card_limit": {**LIMIT_RESULT, "restored": BOOLEAN},
    "restore_transaction_limit": {**TRANSACTION_LIMIT_RESULT, "restored": BOOLEAN},
    "reactivate_subscription": {"subscription_id": STRING, "status": STRING, "restored": BOOLEAN},
    "cancel_virtual_card_application": {
        "application_id": STRING,
        "status": STRING,
        "restored": BOOLEAN,
    },
    "restore_wealth_risk": {
        "risk_preference": NULLABLE_STRING,
        "status": STRING,
        "restored": BOOLEAN,
    },
    "reverse_purchase_wealth": {
        "order_id": STRING,
        "holding_id": STRING,
        "holding_status": STRING,
        "amount_cny": MONEY,
        "restored": BOOLEAN,
    },
    "demo_reserve_funds": {**DEMO_RESULT, "amount_cny": MONEY, "paused_after": BOOLEAN},
    "demo_charge_fee": {**DEMO_RESULT, "amount_cny": MONEY, "fail_compensation": BOOLEAN},
    "demo_irreversible_marker": DEMO_RESULT,
    "demo_fail_step": {"unreachable_success": {"const": False}},
    "reverse_demo_reserve": DEMO_RESULT,
    "reverse_demo_charge": DEMO_RESULT,
}


def legacy_output_schema(name: str) -> dict[str, Any]:
    fields = {"simulated": {"const": True}, **CONTRACTS.get(name, {})}
    return {"type": "object", "required": list(fields), "properties": fields}
