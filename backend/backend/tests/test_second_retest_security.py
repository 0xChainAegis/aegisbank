"""Second-retest security regressions: OTP lockout, reasons, permissions."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from aegisbank_api.gateway import DEMO_INTERNAL_TOOLS, DEMO_PREGRANTED_TOOLS
from aegisbank_api.main import create_app

DEMO_OTP = "246810"
WRONG_OTP = "000000"
YELLOW_REASON = "黄色操作涉及资金变动或账户设置，需要在 5 分钟内完成一次轻量确认。"
LEGACY_YELLOW_REASON = "黄色操作会修改账户设置，需要在 5 分钟内完成一次轻量确认。"


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "second-retest-security.db"))


def start_red_transfer(client: TestClient, amount: float = 1500) -> dict[str, Any]:
    response = client.post(
        "/api/agent/run",
        json={
            "instruction": f"向 ACC-2002 转账 {amount:g} 元",
            "tool_name": "transfer",
            "arguments": {
                "from_account": "ACC-1001",
                "to_account": "ACC-2002",
                "amount_cny": amount,
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "awaiting_confirmation", body
    assert body["risk_level"] == "red", body
    assert body["confirmation"]["requires_reauth"] is True, body
    return body


def approve(client: TestClient, pending: dict[str, Any], otp: str) -> Any:
    return client.post(
        f"/api/confirmations/{pending['confirmation']['id']}",
        json={"approved": True, "reauth_token": otp},
    )


def account_balance(services: Any) -> float:
    return services.repository.account("demo-user", "ACC-1001").balance_cny


def audit_entries(client: TestClient, action_id: str) -> list[dict[str, Any]]:
    response = client.get("/api/audit", params={"run_id": action_id, "limit": 200})
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def test_five_wrong_otps_lock_confirmation_and_correct_otp_cannot_execute(tmp_path):
    with make_client(tmp_path) as client:
        services = client.app.state.services
        pending = start_red_transfer(client)
        action_id = pending["confirmation"]["id"]
        before = account_balance(services)

        for _ in range(5):
            wrong = approve(client, pending, WRONG_OTP)
            assert wrong.status_code == 403, wrong.text
            assert "二次身份校验" in wrong.json()["detail"]

        stored = services.db.get_pending(action_id)
        assert stored is not None
        assert stored["status"] == "blocked"
        assert stored["state"] == "FAILED"
        assert stored["mfa_failures"] == 5

        entries = audit_entries(client, action_id)
        assert sum(entry["event"] == "mfa_failed" for entry in entries) == 5
        locked = [entry for entry in entries if entry["event"] == "mfa_locked"]
        assert len(locked) == 1
        assert locked[0]["result"]["attempt_count"] == 5
        assert locked[0]["result"]["max_attempts"] == 5

        correct_after_lock = approve(client, pending, DEMO_OTP)
        assert correct_after_lock.status_code == 403, correct_after_lock.text
        assert "锁定" in correct_after_lock.json()["detail"]
        assert account_balance(services) == before
        assert "tool_executed" not in {
            entry["event"] for entry in audit_entries(client, action_id)
        }
        assert services.scheduler.breaker.is_open(user_id="demo-user") is False

        read_only = client.post(
            "/api/agent/run",
            json={
                "instruction": "查询我的本月账单",
                "tool_name": "query_bill",
                "arguments": {"account_id": "ACC-1001"},
            },
        )
        assert read_only.status_code == 200, read_only.text
        assert read_only.json()["status"] == "completed"


def test_four_wrong_otps_then_correct_otp_still_executes(tmp_path):
    with make_client(tmp_path) as client:
        services = client.app.state.services
        pending = start_red_transfer(client)
        action_id = pending["confirmation"]["id"]
        before = account_balance(services)

        for _ in range(4):
            wrong = approve(client, pending, WRONG_OTP)
            assert wrong.status_code == 403, wrong.text

        stored = services.db.get_pending(action_id)
        assert stored is not None
        assert stored["status"] == "pending"
        assert stored["mfa_failures"] == 4

        correct = approve(client, pending, DEMO_OTP)
        assert correct.status_code == 200, correct.text
        assert correct.json()["status"] == "completed"
        assert account_balance(services) == before - 1500
        assert services.db.get_pending(action_id)["status"] == "completed"

        entries = audit_entries(client, action_id)
        assert sum(entry["event"] == "mfa_failed" for entry in entries) == 4
        assert "mfa_locked" not in {entry["event"] for entry in entries}
        assert "tool_executed" in {entry["event"] for entry in entries}
        assert services.scheduler.breaker.is_open(user_id="demo-user") is False


def test_yellow_confirmation_uses_generic_reason_and_preserves_risk_reasons(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/agent/run",
            json={
                "instruction": "把还款日调整到每月 18 日",
                "tool_name": "adjust_repayment_date",
                "arguments": {"card_id": "CARD-8821", "new_day": 18},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "yellow"
        assert body["reason"] == YELLOW_REASON
        assert LEGACY_YELLOW_REASON not in body["reason"]
        risk_reasons = body["risk"]["reasons"]
        assert risk_reasons
        assert any("账户设置" in reason or "订阅" in reason for reason in risk_reasons)
        assert body["plan"]["steps"][0]["risk_reasons"] == risk_reasons


def test_demo_permissions_exclude_internal_tools_but_keep_user_tools(tmp_path):
    with make_client(tmp_path) as client:
        services = client.app.state.services
        response = client.get("/api/permissions")
        assert response.status_code == 200, response.text
        permissions = {item["name"]: item for item in response.json()["permissions"]}

        user_tools = {
            "query_bill",
            "query_balance",
            "transfer",
            "adjust_repayment_date",
            "run_due_tasks",
        }
        assert user_tools <= set(permissions)
        assert all(permissions[name]["granted"] is True for name in user_tools)

        assert not (DEMO_INTERNAL_TOOLS & DEMO_PREGRANTED_TOOLS)
        assert not (DEMO_INTERNAL_TOOLS & set(permissions))
        for tool_name in (
            "demo_fail_step",
            "demo_charge_fee",
            "demo_irreversible_marker",
            "demo_reserve_funds",
            "reverse_transfer",
            "restore_card_limit",
            "execute_gift_order",
        ):
            assert services.gateway.permissions.is_granted(
                "demo-user", tool_name, services.registry
            ) is False

        public_call = client.post(
            "/api/agent/run",
            json={
                "instruction": "直接调用演示扣费工具",
                "tool_name": "demo_charge_fee",
                "arguments": {"amount_cny": 59},
            },
        )
        assert public_call.status_code == 200, public_call.text
        public_body = public_call.json()
        assert public_body["status"] == "blocked", public_body
        assert "内部" in public_body["reason"] or "权限" in public_body["reason"]

        internal_demo = client.post("/api/compensation/demo/run", json={"mode": "success"})
        assert internal_demo.status_code == 200, internal_demo.text
        assert internal_demo.json()["status"] == "completed", internal_demo.text