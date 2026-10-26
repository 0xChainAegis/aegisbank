from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.banking.repository import BankingRepository
from aegisbank_api.config import Settings
from aegisbank_api.db import Database
from aegisbank_api.domain import ExecutionContext
from aegisbank_api.main import create_app
from aegisbank_api.scenarios import wealth
from aegisbank_api.services import CoreServices

DEMO_OTP = "246810"


def make_client(tmp_path, name="wealth.db"):
    return TestClient(create_app(database_path=tmp_path / name))


def account_available(client, account_id="ACC-1001"):
    overview = client.get("/api/banking/overview")
    assert overview.status_code == 200, overview.text
    accounts = overview.json()["accounts"]
    return next(item for item in accounts if item["account_id"] == account_id)["available_cny"]


def run(client, instruction, tool_name=None, arguments=None):
    body = {"instruction": instruction}
    if tool_name is not None:
        body["tool_name"] = tool_name
    if arguments is not None:
        body["arguments"] = arguments
    response = client.post("/api/agent/run", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, action_id, *, approved=True, token=None):
    payload = {"approved": approved}
    if token is not None:
        payload["reauth_token"] = token
    return client.post(f"/api/confirmations/{action_id}", json=payload)


def test_wealth_routes_expose_simulated_facts(tmp_path):
    with make_client(tmp_path) as client:
        products = client.get("/api/wealth/products").json()
        assert products["simulated"] is True
        assert "不构成任何投资建议" in products["disclaimer"]
        assert products["count"] == 5
        levels = [item["risk_level"] for item in products["products"]]
        assert levels == list(wealth.RISK_LEVELS)
        r2 = next(item for item in products["products"] if item["product_id"] == "WPRD-R2")
        assert r2["min_amount_cny"] == 1000.0
        assert r2["expected_annual_rate"] > 0

        holdings = client.get("/api/wealth/holdings").json()
        assert holdings["simulated"] is True
        assert "不构成任何投资建议" in holdings["disclaimer"]
        assert holdings["count"] == 1
        holding = holdings["holdings"][0]
        assert holding["holding_id"] == wealth.DEMO_HOLDING_ID
        assert holding["product_id"] == "WPRD-R2"
        assert holding["principal_cny"] == 3000.0
        assert holding["market_value_cny"] == 3060.0
        assert holdings["total_market_value_cny"] == 3060.0

        orders = client.get("/api/wealth/orders").json()
        assert orders["simulated"] is True
        assert orders["count"] == 0


def test_green_wealth_queries_execute_without_confirmation(tmp_path):
    with make_client(tmp_path) as client:
        listed = run(client, "有什么理财产品", "list_wealth_products", {})
        assert listed["status"] == "completed"
        assert listed["risk_level"] == "green"
        assert listed["results"][0]["data"]["count"] == 5
        assert listed["results"][0]["data"]["simulated"] is True

        holdings = run(client, "查询我的理财持仓", "query_wealth_holdings", {})
        assert holdings["status"] == "completed"
        assert holdings["risk_level"] == "green"
        data = holdings["results"][0]["data"]
        assert data["count"] == 1
        assert data["holdings"][0]["holding_id"] == wealth.DEMO_HOLDING_ID


def test_purchase_is_red_requires_reauth_and_updates_assets(tmp_path):
    with make_client(tmp_path) as client:
        before = account_available(client)
        pending = run(client, "买入 2000 元 R2 理财")
        assert pending["status"] == "awaiting_confirmation"
        assert pending["risk_level"] == "red"
        assert pending["confirmation"]["requires_reauth"] is True
        reasons = " ".join(pending["risk"]["reasons"])
        assert "理财申购属于资金投入" in reasons
        assert "R2" in reasons
        assert pending["plan"]["planner"] == "rule"
        assert pending["plan"]["steps"][0]["tool_name"] == "purchase_wealth"
        assert pending["plan"]["steps"][0]["arguments"]["product_id"] == "WPRD-R2"

        bad = confirm(client, pending["confirmation"]["id"], token="000000")
        assert bad.status_code == 403

        good = confirm(client, pending["confirmation"]["id"], token=DEMO_OTP)
        assert good.status_code == 200, good.text
        body = good.json()
        assert body["status"] == "completed"
        data = body["results"][0]["data"]
        assert data["product_id"] == "WPRD-R2"
        assert data["amount_cny"] == 2000.0
        assert data["simulated"] is True
        assert "不构成任何投资建议" in body["results"][0]["message"]

        holding = client.get("/api/wealth/holdings").json()["holdings"][0]
        assert holding["principal_cny"] == 5000.0
        assert holding["market_value_cny"] == 5060.0

        orders = client.get("/api/wealth/orders").json()
        assert orders["count"] == 1
        assert orders["orders"][0]["side"] == "purchase"
        assert orders["orders"][0]["amount_cny"] == 2000.0
        assert orders["orders"][0]["status"] == "completed"

        assert account_available(client) == before - 2000.0
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_purchase_below_minimum_amount_is_rejected(tmp_path):
    with make_client(tmp_path) as client:
        response = run(client, "买入 100 元 指数增强 理财")
        assert response["status"] == "needs_clarification"
        assert "起购" in response["reason"]


def test_purchase_tool_guards_minimum_amount_and_missing_product(tmp_path):
    db = Database(tmp_path / "wealth-tools.db")
    repository = BankingRepository(db)
    with db.transaction() as conn:
        conn.executescript(wealth.SCHEMA_SQL)
    wealth.seed(db, "demo-user")
    services = CoreServices(db=db, repository=repository, settings=Settings())
    tools = {tool.metadata.name: tool for tool in wealth.tools(services)}
    context = ExecutionContext(
        user_id="demo-user",
        instruction="买入理财",
        run_id="run-under-test",
        dag_path="step-1:purchase_wealth",
    )
    with pytest.raises(ValueError, match="起购"):
        tools["purchase_wealth"].execute(
            {"product_id": "WPRD-R4", "amount_cny": 100}, context
        )
    with pytest.raises(ValueError, match="不存在"):
        tools["purchase_wealth"].execute(
            {"product_id": "WPRD-MISSING", "amount_cny": 1000}, context
        )

def test_small_redemption_is_yellow_and_large_redemption_is_red(tmp_path):
    with make_client(tmp_path) as client:
        before = account_available(client)
        small = run(client, "赎回 500 元")
        assert small["status"] == "awaiting_confirmation"
        assert small["risk_level"] == "yellow"
        assert small["confirmation"]["requires_reauth"] is False
        assert small["plan"]["steps"][0]["arguments"]["holding_id"] == wealth.DEMO_HOLDING_ID

        approved = confirm(client, small["confirmation"]["id"])
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "completed"
        small_data = approved.json()["results"][0]["data"]
        assert small_data["amount_cny"] == 500.0
        assert small_data["holding_status"] == "active"
        assert account_available(client) == before + 500.0

        large = run(client, "赎回 2000 元")
        assert large["status"] == "awaiting_confirmation"
        assert large["risk_level"] == "red"
        assert large["confirmation"]["requires_reauth"] is True
        assert any("1000" in reason for reason in large["risk"]["reasons"])

        confirmed = confirm(client, large["confirmation"]["id"], token=DEMO_OTP)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "completed"
        assert confirmed.json()["results"][0]["data"]["amount_cny"] == 2000.0

        holding = client.get("/api/wealth/holdings").json()["holdings"][0]
        assert holding["market_value_cny"] == 560.0
        orders = client.get("/api/wealth/orders").json()
        sides = [item["side"] for item in orders["orders"]]
        assert sides.count("redeem") == 2


def test_natural_language_wealth_intents(tmp_path):
    with make_client(tmp_path) as client:
        for instruction in ("有什么理财产品", "推荐理财产品", "查询理财产品"):
            listed = run(client, instruction)
            assert listed["status"] == "completed", instruction
            assert listed["plan"]["planner"] == "rule"
            assert listed["plan"]["steps"][0]["tool_name"] == "list_wealth_products"

        holdings = run(client, "我的理财持仓")
        assert holdings["status"] == "completed"
        assert holdings["plan"]["steps"][0]["tool_name"] == "query_wealth_holdings"

        missing_amount = run(client, "买入 R2 理财")
        assert missing_amount["status"] == "needs_clarification"
        assert "金额" in missing_amount["reason"]

        planned = run(client, "买入 5000 元 R2 理财")
        assert planned["status"] == "awaiting_confirmation"
        step = planned["plan"]["steps"][0]
        assert step["tool_name"] == "purchase_wealth"
        assert step["arguments"]["product_id"] == "WPRD-R2"
        assert step["arguments"]["amount_cny"] == 5000.0

        by_name = run(client, "买稳健短债理财产品 1000 元")
        assert by_name["status"] == "awaiting_confirmation"
        assert by_name["plan"]["steps"][0]["arguments"]["product_id"] == "WPRD-R2"

        redeem_by_name = run(client, "赎回稳健短债 300 元")
        assert redeem_by_name["status"] == "awaiting_confirmation"
        assert redeem_by_name["risk_level"] == "yellow"
        assert (
            redeem_by_name["plan"]["steps"][0]["arguments"]["holding_id"]
            == wealth.DEMO_HOLDING_ID
        )

        ambiguous = run(client, "买货币基金和混合基金 2000 元")
        assert ambiguous["status"] == "needs_clarification"
        assert "多个" in ambiguous["reason"]

        unknown = run(client, "买黄金理财产品 1000 元")
        assert unknown["status"] == "needs_clarification"
        assert "未找到" in unknown["reason"]


def test_risk_profile_escalates_purchase_warning(tmp_path):
    with make_client(tmp_path) as client:
        assessment = run(client, "我的风险偏好是 R2")
        assert assessment["status"] == "completed"
        assert assessment["risk_level"] == "green"
        profile = assessment["results"][0]["data"]
        assert profile["risk_preference"] == "R2"
        assert profile["risk_label"] == "稳健型"

        pending = run(client, "买入 5000 元 指数增强 理财")
        assert pending["status"] == "awaiting_confirmation"
        assert pending["risk_level"] == "red"

        confirmed = confirm(client, pending["confirmation"]["id"], token=DEMO_OTP)
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()["results"][0]
        data = result["data"]
        assert data["product_id"] == "WPRD-R4"
        assert data["risk_preference"] == "R2"
        assert data["risk_warning"]
        warning = " ".join(data["risk_warning"])
        assert "R4" in warning
        assert "R2" in warning
        assert "高于" in warning
        assert "高于" in result["message"]


def test_revoked_purchase_permission_blocks_wealth_tool(tmp_path):
    with make_client(tmp_path) as client:
        revoked = client.put("/api/permissions/purchase_wealth", json={"granted": False})
        assert revoked.status_code == 200
        assert revoked.json()["granted"] is False

        blocked = run(client, "买入 1000 元 R2 理财")
        assert blocked["status"] == "blocked"
        assert "未授权" in blocked["reason"]
        assert "results" not in blocked

def test_full_redemption_closes_the_holding(tmp_path):
    with make_client(tmp_path) as client:
        before = account_available(client)
        pending = run(client, "赎回全部理财")
        assert pending["status"] == "awaiting_confirmation"
        assert pending["risk_level"] == "red"

        confirmed = confirm(client, pending["confirmation"]["id"], token=DEMO_OTP)
        assert confirmed.status_code == 200, confirmed.text
        data = confirmed.json()["results"][0]["data"]
        assert data["amount_cny"] == 3060.0
        assert data["holding_status"] == "closed"
        assert data["remaining_market_value_cny"] == 0.0
        assert account_available(client) == before + 3060.0

        holdings = client.get("/api/wealth/holdings").json()
        assert holdings["count"] == 0


def test_seed_is_idempotent_across_app_restarts(tmp_path):
    database_path = tmp_path / "wealth-restart.db"
    with TestClient(create_app(database_path=database_path)) as client:
        first = client.get("/api/wealth/holdings").json()
    with TestClient(create_app(database_path=database_path)) as client:
        second = client.get("/api/wealth/holdings").json()
        products = client.get("/api/wealth/products").json()
    assert first == second
    assert first["count"] == 1
    assert products["count"] == 5


def test_purchase_by_product_name_without_wealth_keyword(tmp_path):
    """「买 1000 元稳健短债A」这类只报产品名的说法也必须命中申购意图。"""
    with make_client(tmp_path) as client:
        body = run(client, instruction="买 1000 元稳健短债A")
        assert body["status"] == "awaiting_confirmation", body
        assert [step["tool_name"] for step in body["plan"]["steps"]] == ["purchase_wealth"]
        assert body["risk_level"] == "red"
        assert body["confirmation"]["requires_reauth"] is True
