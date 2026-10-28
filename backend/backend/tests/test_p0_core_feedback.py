"""P0 core feedback regressions: breaker scope, Shanghai dates, run-due reauth."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from aegisbank_api.banking.repository import BankingRepository
from aegisbank_api.db import Database
from aegisbank_api.main import create_app
from aegisbank_api.trust.circuit_breaker import CircuitBreaker

DEMO_OTP = "246810"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_client(tmp_path: Path, name: str = "core-feedback.db") -> TestClient:
    return TestClient(create_app(database_path=tmp_path / name))


def run_agent(client: TestClient, instruction: str, **extra: Any) -> dict[str, Any]:
    response = client.post("/api/agent/run", json={"instruction": instruction, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client: TestClient, action_id: str, **extra: Any):
    return client.post(
        f"/api/confirmations/{action_id}", json={"approved": True, **extra}
    )


def grant_tool(client: TestClient, user_id: str, tool_name: str) -> None:
    response = client.put(
        f"/api/permissions/{tool_name}",
        params={"user_id": user_id},
        json={"granted": True},
    )
    assert response.status_code == 200, response.text


def open_breaker_with_unexecuted_red_plans(client: TestClient) -> dict[str, Any]:
    for _ in range(3):
        body = run_agent(
            client,
            "挂失我的信用卡 CARD-8821",
            tool_name="report_card_lost",
            arguments={"card_id": "CARD-8821"},
        )
        assert body["status"] == "awaiting_confirmation", body
    response = client.get("/api/trust/circuit-breaker")
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["open"] is True
    return status


def insert_bank_transaction(
    db: Database,
    *,
    transaction_id: str,
    user_id: str,
    amount_cents: int,
    occurred_at: str,
    category: str,
) -> None:
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO bank_transactions
            (transaction_id,user_id,account_id,card_id,merchant,category,
             amount_cents,occurred_at,status,note)
            VALUES (?,?,?,NULL,?,?,?,?, 'posted', NULL)
            """,
            (
                transaction_id,
                user_id,
                "ACC-1001",
                "test",
                category,
                amount_cents,
                occurred_at,
            ),
        )


# ---------------------------------------------------------------------------
# 1) Breaker state is per user, not a shared global row.
# ---------------------------------------------------------------------------


def test_breaker_state_is_isolated_per_user(tmp_path: Path) -> None:
    db = Database(tmp_path / "per-user-breaker.db")
    breaker = CircuitBreaker(
        db,
        threshold=3,
        window_seconds=60,
        lock_seconds=3600,
        suspicious_red_events=3,
        suspicious_injection_events=3,
        suspicious_window_seconds=300,
    )
    base = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
    for offset in range(3):
        breaker.record_risk_level(
            user_id="user-a", level="red", now=base + timedelta(seconds=offset)
        )

    user_a = breaker.status(user_id="user-a", now=base + timedelta(seconds=5))
    user_b = breaker.status(user_id="user-b", now=base + timedelta(seconds=5))
    assert user_a["open"] is True
    assert user_a["scope"] == "user"
    assert user_a["user_id"] == "user-a"
    assert user_b["open"] is False
    assert user_b["user_id"] == "user-b"
    events = breaker.recent_events(user_id="user-a")
    assert events
    assert all(event["user_id"] == "user-a" for event in events)


def test_breaker_isolation_between_users_over_http(tmp_path: Path) -> None:
    with make_client(tmp_path, name="http-user-isolation.db") as client:
        user_cards = {"user-a": "CARD-8811", "user-b": "CARD-8822"}
        with client.app.state.services.db.transaction() as conn:
            for index, (user_id, card_id) in enumerate(user_cards.items(), 1):
                account_id = f"ACC-300{index}"
                conn.execute(
                    "INSERT INTO bank_accounts VALUES (?, ?, ?, 'checking', 'CNY', 100000, 100000)",
                    (account_id, user_id, f"{user_id}的账户"),
                )
                conn.execute(
                    "INSERT INTO bank_cards VALUES "
                    "(?, ?, ?, ?, 'active', 100000, 100000, 8, 100000)",
                    (card_id, user_id, account_id, f"**** {card_id[-4:]}"),
                )
        for user_id in user_cards:
            grant_tool(client, user_id, "report_card_lost")

        for _ in range(3):
            body = run_agent(
                client,
                f"挂失我的信用卡 {user_cards['user-a']}",
                user_id="user-a",
                tool_name="report_card_lost",
                arguments={"card_id": user_cards["user-a"]},
            )
            assert body["status"] == "awaiting_confirmation", body

        blocked = run_agent(
            client,
            f"挂失我的信用卡 {user_cards['user-a']}",
            user_id="user-a",
            tool_name="report_card_lost",
            arguments={"card_id": user_cards["user-a"]},
        )
        assert blocked["status"] == "blocked", blocked
        assert blocked["blocked_scope"] == "write"
        assert blocked["breaker"]["user_id"] == "user-a"

        # The same red write from another user must still reach its own
        # confirmation flow; it is not blocked by user-a's open breaker.
        user_b = run_agent(
            client,
            f"挂失我的信用卡 {user_cards['user-b']}",
            user_id="user-b",
            tool_name="report_card_lost",
            arguments={"card_id": user_cards["user-b"]},
        )
        assert user_b["status"] == "awaiting_confirmation", user_b
        assert user_b["risk_level"] == "red"
        repository = client.app.state.services.repository
        assert all(
            repository.card(user_id, card_id).status == "active"
            for user_id, card_id in user_cards.items()
        )


# ---------------------------------------------------------------------------
# 2) Reads bypass an open breaker; writes remain fail-closed.
# ---------------------------------------------------------------------------


def test_read_only_query_bypasses_open_breaker_but_writes_stay_blocked(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        status = open_breaker_with_unexecuted_red_plans(client)
        assert "只读查询仍可执行" in status["reason"]
        assert "仅写操作与确认已拒绝" in status["reason"]

        read = run_agent(
            client,
            "查询我的本月账单",
            tool_name="query_bill",
            arguments={"account_id": "ACC-1001"},
        )
        assert read["status"] == "completed", read
        assert client.get("/api/trust/circuit-breaker").json()["open"] is True

        write = run_agent(
            client,
            "向 ACC-2002 转账 600 元",
            tool_name="transfer",
            arguments={
                "from_account": "ACC-1001",
                "to_account": "ACC-2002",
                "amount_cny": 600,
            },
        )
        assert write["status"] == "blocked", write
        assert write["blocked_scope"] == "write"
        assert "只读查询仍可执行" in write["reason"]


# ---------------------------------------------------------------------------
# 2b) An already-pending confirmation is blocked when that user's breaker opens.
# ---------------------------------------------------------------------------


def test_pending_confirmation_is_blocked_while_breaker_open(tmp_path: Path) -> None:
    with make_client(tmp_path, name="pending-confirmation-blocked.db") as client:
        pending = run_agent(
            client,
            "把还款日调整到每月 18 日",
            tool_name="adjust_repayment_date",
            arguments={"card_id": "CARD-8821", "new_day": 18},
        )
        assert pending["status"] == "awaiting_confirmation", pending

        open_breaker_with_unexecuted_red_plans(client)
        blocked = confirm(client, pending["confirmation"]["id"])
        assert blocked.status_code == 200, blocked.text
        body = blocked.json()
        assert body["status"] == "blocked", body
        assert body["blocked_scope"] == "confirmation"
        assert body["breaker"]["open"] is True
        assert body["breaker"]["user_id"] == "demo-user"
        assert "只读查询仍可执行" in body["reason"]
        assert "results" not in body


# ---------------------------------------------------------------------------
# 3) Wrong OTP is an auth failure, not a tool failure / red trigger.
# ---------------------------------------------------------------------------


def test_wrong_otp_does_not_trip_breaker_and_correct_otp_still_works(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, name="wrong-otp.db") as client:
        body = run_agent(
            client,
            "向 ACC-2002 转账 1200 元",
            tool_name="transfer",
            arguments={
                "from_account": "ACC-1001",
                "to_account": "ACC-2002",
                "amount_cny": 1200,
            },
        )
        assert body["status"] == "awaiting_confirmation"
        assert body["confirmation"]["requires_reauth"] is True
        action_id = body["confirmation"]["id"]

        for _ in range(3):
            wrong = confirm(client, action_id, reauth_token="000000")
            assert wrong.status_code == 403, wrong.text
            status = client.get("/api/trust/circuit-breaker").json()
            assert status["open"] is False, status

        good = confirm(client, action_id, reauth_token=DEMO_OTP)
        assert good.status_code == 200, good.text
        assert good.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# 4) Banking day/month boundaries use Asia/Shanghai, not UTC dates.
# ---------------------------------------------------------------------------


def test_shanghai_day_and_month_boundaries(tmp_path: Path) -> None:
    db = Database(tmp_path / "shanghai-boundary.db")
    repo = BankingRepository(db)
    user_id = "boundary-user"

    # 23:30 Beijing on Oct 26 belongs to the previous banking day.
    insert_bank_transaction(
        db,
        transaction_id="TX-BJ-DAY-OLD",
        user_id=user_id,
        amount_cents=-10000,
        occurred_at="2026-10-26T23:30:00+08:00",
        category="transfer",
    )
    # 00:10 Beijing on Oct 27 belongs to the new banking day.
    insert_bank_transaction(
        db,
        transaction_id="TX-BJ-DAY-NEW",
        user_id=user_id,
        amount_cents=-20000,
        occurred_at="2026-10-27T00:10:00+08:00",
        category="transfer",
    )
    # 23:30 Beijing on Oct 31 belongs to the previous banking month.
    insert_bank_transaction(
        db,
        transaction_id="TX-BJ-MONTH-OLD",
        user_id=user_id,
        amount_cents=-30000,
        occurred_at="2026-10-31T23:30:00+08:00",
        category="shopping",
    )
    # 00:10 Beijing on Nov 1 belongs to the new banking month.
    insert_bank_transaction(
        db,
        transaction_id="TX-BJ-MONTH-NEW",
        user_id=user_id,
        amount_cents=-40000,
        occurred_at="2026-11-01T00:10:00+08:00",
        category="shopping",
    )

    day_now = datetime(2026, 10, 27, 0, 30, tzinfo=SHANGHAI)
    assert repo.daily_transfer_total_cny(user_id, now=day_now) == 200.0

    month_now = datetime(2026, 11, 1, 0, 30, tzinfo=SHANGHAI)
    assert repo.monthly_spend_cny(user_id, now=month_now) == 400.0


# ---------------------------------------------------------------------------
# 5) Escalated run-due task remains pending with an actionable reauth path.
# ---------------------------------------------------------------------------


def test_run_due_escalation_stays_pending_with_reauth_guidance(tmp_path: Path) -> None:
    with make_client(tmp_path, name="run-due-reauth.db") as client:
        scheduled = run_agent(client, "明天给张三转 500")
        assert scheduled["status"] == "awaiting_confirmation"
        step = scheduled["plan"]["steps"][0]
        assert step["tool_name"] == "schedule_transfer"
        scheduled_confirm = confirm(client, scheduled["confirmation"]["id"])
        assert scheduled_confirm.status_code == 200, scheduled_confirm.text
        scheduled_data = scheduled_confirm.json()["results"][0]["data"]
        task_id = scheduled_data["task_id"]
        run_at = datetime.fromisoformat(step["arguments"]["run_at"])

        # Execute 600 today so the due 500 transfer is re-assessed at 1100 > 1000.
        immediate = run_agent(
            client,
            "向 ACC-2002 转账 600 元",
            tool_name="transfer",
            arguments={
                "from_account": "ACC-1001",
                "to_account": "ACC-2002",
                "amount_cny": 600,
            },
        )
        assert immediate["status"] == "awaiting_confirmation"
        immediate_confirm = confirm(client, immediate["confirmation"]["id"])
        assert immediate_confirm.status_code == 200, immediate_confirm.text

        balance_before = client.get("/api/banking/overview").json()["accounts"][0][
            "balance_cny"
        ]
        response = client.post(
            "/api/automation/run-due",
            params={"now": (run_at + timedelta(hours=1)).isoformat()},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["executed_count"] == 0
        assert result["failed_count"] == 0
        assert result["pending_reauth_count"] == 1
        assert result["action_required"] is True
        pending = result["pending_reauth"][0]
        assert pending["task_id"] == task_id
        assert pending["status"] == "pending"
        assert pending["execution_status"] == "needs_reauth"
        assert "升为 red" in pending["reason"]
        assert "OTP" in pending["action_required"]

        tasks = client.get("/api/automation/schedules").json()["tasks"]
        task = next(item for item in tasks if item["task_id"] == task_id)
        assert task["status"] == "pending"
        assert task["last_result"]["execution_status"] == "needs_reauth"
        balance_after = client.get("/api/banking/overview").json()["accounts"][0][
            "balance_cny"
        ]
        assert balance_after == balance_before

        # A second fast-forward must not double-execute or silently fail it.
        second = client.post(
            "/api/automation/run-due",
            params={"now": (run_at + timedelta(hours=2)).isoformat()},
        )
        assert second.status_code == 200, second.text
        assert second.json()["executed_count"] == 0
        assert second.json()["failed_count"] == 0
        assert second.json()["pending_reauth_count"] == 1
        assert client.get("/api/banking/overview").json()["accounts"][0][
            "balance_cny"
        ] == balance_before

        entries = client.get("/api/audit", params={"limit": 200}).json()["entries"]
        needs_reauth = [
            entry
            for entry in entries
            if entry["event"] == "scheduled_task_needs_reauth"
            and (entry["result"] or {}).get("task_id") == task_id
        ]
        assert needs_reauth
        assert not [
            entry
            for entry in entries
            if entry["event"] == "scheduled_task_failed"
            and (entry["result"] or {}).get("task_id") == task_id
        ]
        assert not [
            entry
            for entry in entries
            if entry["event"] == "scheduled_task_executed"
            and (entry["result"] or {}).get("task_id") == task_id
        ]


# ---------------------------------------------------------------------------
# 6) scenario-check must fail when a fast-forward reports any failed task.
# ---------------------------------------------------------------------------


def load_scenario_check():
    test_file = Path(__file__).resolve()
    candidates = [
        test_file.parents[2] / "scripts" / "scenario-check.py",
        test_file.parents[3] / "backend" / "scripts" / "scenario-check.py",
    ]
    script = next(path for path in candidates if path.exists())
    spec = importlib.util.spec_from_file_location("scenario_check_regression", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scenario_check_fast_forward_requires_zero_failures() -> None:
    module = load_scenario_check()
    ok, detail = module.fast_forward_result(
        200,
        {
            "executed_count": 1,
            "failed_count": 1,
            "failed": [{"task_id": "TASK-1", "reason": "权限复检失败"}],
        },
    )
    assert ok is False
    assert "failed=1" in detail
    assert "TASK-1" in detail
    assert "处理建议" in detail

    ok, detail = module.fast_forward_result(
        200, {"executed_count": 1, "failed_count": 0, "pending_reauth_count": 0}
    )
    assert ok is True
    assert "failed=0" in detail


def test_scenario_check_fast_forward_fails_closed_on_missing_or_non_int_counts() -> None:
    module = load_scenario_check()
    malformed_payloads = [
        {},
        {"executed_count": 1},
        {"failed_count": 0},
        {"executed_count": "1", "failed_count": 0},
        {"executed_count": 1, "failed_count": "0"},
        {"executed_count": 1, "failed_count": 0.0},
        {"executed_count": True, "failed_count": 0},
    ]
    for payload in malformed_payloads:
        ok, detail = module.fast_forward_result(200, payload)
        assert ok is False, payload
        assert "响应格式错误" in detail, (payload, detail)
        assert "处理建议" in detail, (payload, detail)

    ok, detail = module.fast_forward_result(
        500, {"executed_count": 1, "failed_count": 0}
    )
    assert ok is False
    assert "HTTP=500" in detail
    assert "处理建议" in detail
