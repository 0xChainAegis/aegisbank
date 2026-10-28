"""A due-time risk escalation has a usable, confirmed cancel/recreate path."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from aegisbank_api.config import Settings
from aegisbank_api.main import create_app


def run(client: TestClient, instruction: str) -> dict[str, Any]:
    response = client.post("/api/agent/run", json={"instruction": instruction})
    assert response.status_code == 200, response.text
    return response.json()


def approve(client: TestClient, plan: dict[str, Any], *, otp: str | None = None):
    body: dict[str, Any] = {"approved": True}
    if otp is not None:
        body.update(reauth_token=otp, mfa_provider="otp")
    return client.post(f"/api/confirmations/{plan['confirmation']['id']}", json=body)


def balance(client: TestClient) -> float:
    response = client.get("/api/banking/overview")
    assert response.status_code == 200, response.text
    return next(
        account["balance_cny"]
        for account in response.json()["accounts"]
        if account["account_id"] == "ACC-1001"
    )


def fast_forward(client: TestClient, plan: dict[str, Any]) -> dict[str, Any]:
    run_at = datetime.fromisoformat(plan["plan"]["steps"][0]["arguments"]["run_at"])
    response = client.post(
        "/api/automation/run-due", params={"now": (run_at + timedelta(hours=1)).isoformat()}
    )
    assert response.status_code == 200, response.text
    return response.json()


def transfer_600(client: TestClient) -> None:
    plan = run(client, "向 ACC-2002 转账 600 元")
    assert plan["status"] == "awaiting_confirmation", plan
    response = approve(client, plan)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.text


def test_cancel_recreate_escalated_schedule_requires_otp_and_executes_once(tmp_path):
    settings = Settings(_env_file=None, planner_mode="rule", automation_enabled=False)
    app = create_app(database_path=tmp_path / "recreate.db", settings=settings)
    with TestClient(app) as client:
        initial_balance = balance(client)
        instruction = "明天给张三转 500"
        original = run(client, instruction)
        assert original["status"] == "awaiting_confirmation", original
        assert original["risk_level"] == "yellow"
        assert original["confirmation"]["requires_reauth"] is False
        created = approve(client, original)
        assert created.status_code == 200, created.text
        assert created.json()["status"] == "completed"
        original_task_id = created.json()["results"][0]["data"]["task_id"]
        assert balance(client) == initial_balance

        transfer_600(client)
        before_due = balance(client)
        blocked = fast_forward(client, original)
        assert blocked["executed_count"] == 0
        assert blocked["failed_count"] == 0
        assert blocked["pending_reauth_count"] == 1
        assert blocked["pending_reauth"][0]["task_id"] == original_task_id
        assert balance(client) == before_due

        cancel_plan = run(client, f"取消定时任务 {original_task_id}")
        assert cancel_plan["status"] == "awaiting_confirmation", cancel_plan
        assert cancel_plan["risk_level"] == "yellow"
        cancelled = approve(client, cancel_plan)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "completed", cancelled.text
        recreated = run(client, instruction)
        assert recreated["status"] == "awaiting_confirmation", recreated
        assert recreated["risk_level"] == "red"
        assert recreated["confirmation"]["requires_reauth"] is True
        assert recreated["plan"]["steps"][0]["arguments"]["amount_cny"] == 500

        missing_otp = approve(client, recreated)
        assert missing_otp.status_code == 403, missing_otp.text
        assert balance(client) == before_due
        verified = approve(client, recreated, otp=settings.demo_otp)
        assert verified.status_code == 200, verified.text
        assert verified.json()["status"] == "completed", verified.text
        new_task_id = verified.json()["results"][0]["data"]["task_id"]
        assert new_task_id != original_task_id
        assert balance(client) == before_due

        executed = fast_forward(client, recreated)
        assert executed["executed_count"] == 1, executed
        assert executed["failed_count"] == 0, executed
        assert executed["pending_reauth_count"] == 0, executed
        assert executed["executed"][0]["task_id"] == new_task_id
        assert balance(client) == before_due - 500
        repeated = fast_forward(client, recreated)
        assert repeated["executed_count"] == 0, repeated
        assert repeated["failed_count"] == 0, repeated
        assert repeated["pending_reauth_count"] == 0, repeated
        assert balance(client) == initial_balance - 1100

        tasks = client.get("/api/automation/schedules").json()["tasks"]
        states = {task["task_id"]: task["status"] for task in tasks}
        assert states[original_task_id] == "cancelled"
        assert states[new_task_id] == "done"


def test_confirmation_rechecks_the_underlying_transfer_risk(tmp_path):
    settings = Settings(_env_file=None, planner_mode="rule", automation_enabled=False)
    with TestClient(create_app(database_path=tmp_path / "recheck.db", settings=settings)) as client:
        original = run(client, "明天给张三转 500")
        assert original["risk_level"] == "yellow", original
        transfer_600(client)
        before = balance(client)

        # The yellow confirmation cannot be promoted by simply attaching an OTP:
        # the changed risk must invalidate the old bound envelope first.
        outdated = approve(client, original, otp=settings.demo_otp)
        assert outdated.status_code == 409, outdated.text
        assert balance(client) == before
        assert client.get("/api/automation/schedules").json()["tasks"] == []

        fresh = run(client, "明天给张三转 500")
        assert fresh["risk_level"] == "red", fresh
        assert fresh["confirmation"]["requires_reauth"] is True
