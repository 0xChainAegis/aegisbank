"""Regression tests: natural-language cancellation of the suspicious subscription.

Bug: phrasings such as「取消异常订阅」「帮我取消异常订阅」「退订异常订阅」used to fall
through to the read-only ``list_subscriptions`` tool (or required the exact
string「取消订阅」), so users could not cancel an abnormal subscription from the
console. The rule planner now resolves explicit ids, merchant names and the
abnormal-subscription hint, and asks for clarification instead of guessing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "cancel.db"))


def plan_steps(body: dict) -> list[str]:
    return [step["tool_name"] for step in body.get("plan", {}).get("steps", [])]


def test_abnormal_subscription_phrasings_plan_a_cancel(tmp_path):
    phrases = [
        "取消异常订阅",
        "帮我取消异常订阅",
        "把异常订阅取消掉",
        "退订异常订阅",
        "取消那个异常订阅",
    ]
    with make_client(tmp_path) as client:
        for phrase in phrases:
            response = client.post("/api/agent/run", json={"instruction": phrase})
            assert response.status_code == 200, (phrase, response.text)
            body = response.json()
            assert body["status"] == "awaiting_confirmation", (phrase, body)
            assert plan_steps(body) == ["cancel_subscription"], (phrase, body)
            assert body["plan"]["steps"][0]["arguments"]["subscription_id"] == "SUB-3002"
            assert body["risk_level"] == "yellow"


def test_cancel_by_merchant_name_resolves_the_right_subscription(tmp_path):
    cases = {
        "取消 AI 工具订阅": "SUB-3002",
        "退订 AI 工具订阅": "SUB-3002",
        "取消健身房月卡": "SUB-3003",
        "关闭云端影音订阅": "SUB-3001",
    }
    with make_client(tmp_path) as client:
        for phrase, expected in cases.items():
            body = client.post("/api/agent/run", json={"instruction": phrase}).json()
            assert body["status"] == "awaiting_confirmation", (phrase, body)
            assert plan_steps(body) == ["cancel_subscription"], (phrase, body)
            assert body["plan"]["steps"][0]["arguments"]["subscription_id"] == expected, phrase


def test_cancel_executes_end_to_end_and_is_audited(tmp_path):
    with make_client(tmp_path) as client:
        body = client.post("/api/agent/run", json={"instruction": "取消异常订阅"}).json()
        action_id = body["confirmation"]["id"]
        confirmed = client.post(
            f"/api/confirmations/{action_id}", json={"approved": True}
        )
        assert confirmed.status_code == 200, confirmed.text
        done = confirmed.json()
        assert done["status"] == "completed"
        assert done["results"][0]["data"]["subscription_id"] == "SUB-3002"
        assert done["results"][0]["data"]["status"] == "cancelled"

        subscriptions = client.get("/api/banking/overview").json()["subscriptions"]
        target = next(item for item in subscriptions if item["subscription_id"] == "SUB-3002")
        assert target["status"] == "cancelled"

        audit = client.get("/api/audit").json()["entries"]
        assert any(item["tool_name"] == "cancel_subscription" for item in audit)
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_generic_subscription_query_is_still_read_only(tmp_path):
    with make_client(tmp_path) as client:
        for phrase in ("我的订阅有哪些", "查询订阅列表", "看看订阅"):
            body = client.post("/api/agent/run", json={"instruction": phrase}).json()
            assert body["status"] == "completed", (phrase, body)
            assert plan_steps(body) == ["list_subscriptions"], (phrase, body)


def test_bare_cancel_without_target_asks_for_clarification(tmp_path):
    with make_client(tmp_path) as client:
        # Cancel the abnormal one explicitly first; remaining subscriptions have no
        # abnormal flag, so a bare request must not guess.
        body = client.post("/api/agent/run", json={"instruction": "取消订阅 SUB-3002"}).json()
        client.post(f"/api/confirmations/{body['confirmation']['id']}", json={"approved": True})

        result = client.post("/api/agent/run", json={"instruction": "取消订阅"}).json()
        assert result["status"] == "needs_clarification", result
        assert "订阅编号" in (result.get("reason") or "")


def test_unknown_target_does_not_guess(tmp_path):
    with make_client(tmp_path) as client:
        body = client.post("/api/agent/run", json={"instruction": "取消某个会员"}).json()
        assert body["status"] == "needs_clarification", body
