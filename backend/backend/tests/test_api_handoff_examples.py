"""Regression guard for the examples in docs/API-HANDOFF.md."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path):
    return TestClient(create_app(database_path=tmp_path / "api-handoff.db"))


def test_handoff_health_overview_and_planner(tmp_path):
    with make_client(tmp_path) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        ready = client.get("/api/health/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        overview = client.get("/api/banking/overview")
        assert overview.status_code == 200
        assert overview.json()["accounts"][0]["account_id"] == "ACC-1001"
        assert overview.json()["suspicious_subscription_id"] == "SUB-3002"

        planned = client.post(
            "/api/planner/plan",
            json={"instruction": "向 ACC-2002 转账 880 元"},
        )
        assert planned.status_code == 200
        body = planned.json()
        assert body["status"] == "planned"
        assert body["risk_level"] == "yellow"
        assert body["plan"]["steps"][0]["tool_name"] == "transfer"
        assert len(body["plan"]["plan_hash"]) == 64

        clarification = client.post(
            "/api/planner/plan",
            json={"instruction": "如果余额超过1000元，就给妈妈转500元"},
        )
        assert clarification.status_code == 200
        assert clarification.json()["status"] == "needs_clarification"
        assert clarification.json()["plan"]["steps"] == []


def test_handoff_green_yellow_red_flow(tmp_path):
    with make_client(tmp_path) as client:
        green = client.post(
            "/api/agent/run",
            headers={"Idempotency-Key": "handoff-green"},
            json={
                "instruction": "查询我的本月账单",
                "tool_name": "query_bill",
                "arguments": {"account_id": "ACC-1001"},
            },
        )
        assert green.status_code == 200
        assert green.json()["status"] == "completed"
        assert green.json()["results"][0]["data"]["simulated"] is True

        yellow = client.post(
            "/api/agent/run",
            headers={"Idempotency-Key": "handoff-yellow"},
            json={"instruction": "向 ACC-2002 转账 880 元"},
        )
        assert yellow.status_code == 200
        yellow_body = yellow.json()
        assert yellow_body["status"] == "awaiting_confirmation"
        assert yellow_body["risk_level"] == "yellow"
        assert yellow_body["confirmation"]["requires_reauth"] is False

        confirmed = client.post(
            f"/api/confirmations/{yellow_body['confirmation']['id']}",
            headers={"Idempotency-Key": "handoff-yellow-confirm"},
            json={"approved": True},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "completed"
        assert confirmed.json()["results"][0]["data"]["simulated"] is True

        red = client.post(
            "/api/agent/run",
            headers={"Idempotency-Key": "handoff-red"},
            json={"instruction": "向 ACC-2002 转账 1200 元"},
        )
        assert red.status_code == 200
        red_body = red.json()
        assert red_body["status"] == "awaiting_confirmation"
        assert red_body["risk_level"] == "red"
        assert red_body["confirmation"]["requires_reauth"] is True

        action_id = red_body["confirmation"]["id"]
        bad_otp = client.post(
            f"/api/confirmations/{action_id}",
            headers={"Idempotency-Key": "handoff-red-bad-otp"},
            json={"approved": True, "reauth_token": "000000"},
        )
        assert bad_otp.status_code == 403

        good_otp = client.post(
            f"/api/confirmations/{action_id}",
            headers={"Idempotency-Key": "handoff-red-good-otp"},
            json={"approved": True, "reauth_token": "246810"},
        )
        assert good_otp.status_code == 200
        assert good_otp.json()["status"] == "completed"
        assert good_otp.json()["plan"]["authorization"]["mfa_verified"] is True
        assert good_otp.json()["results"][0]["data"]["daily_transfer_total_cny"] == 2080.0

        verified = client.get("/api/audit/verify")
        assert verified.status_code == 200
        assert verified.json()["valid"] is True
        assert verified.json()["checked"] >= 1


def test_handoff_tools_permissions_and_audit_list(tmp_path):
    with make_client(tmp_path) as client:
        tools = client.get("/api/tools")
        assert tools.status_code == 200
        tool_names = {item["name"] for item in tools.json()["tools"]}
        assert "query_bill" in tool_names
        assert "transfer" in tool_names

        permissions = client.get("/api/permissions")
        assert permissions.status_code == 200
        permission_names = {item["name"] for item in permissions.json()["permissions"]}
        assert "query_bill" in permission_names

        revoked = client.put("/api/permissions/query_bill", json={"granted": False})
        assert revoked.status_code == 200
        assert revoked.json() == {
            "tool_name": "query_bill",
            "title": "分析账单",
            "granted": False,
        }

        restored = client.put("/api/permissions/query_bill", json={"granted": True})
        assert restored.status_code == 200
        assert restored.json()["granted"] is True

        audit = client.get("/api/audit?limit=3", headers={"X-Aegis-Role": "auditor"})
        assert audit.status_code == 200
        assert audit.json()["count"] <= 3