"""Cards scenario tests: DAG issuance, red password reset, unlock and guards."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path):
    return TestClient(create_app(database_path=tmp_path / "aegisbank-cards.db"))


def run_agent(client, **body):
    response = client.post("/api/agent/run", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, action_id, **body):
    return client.post(f"/api/confirmations/{action_id}", json=body)


def overview_card(client, card_id):
    cards = client.get("/api/banking/overview").json()["cards"]
    return next(item for item in cards if item["card_id"] == card_id)


def test_apply_virtual_card_is_two_step_dag_and_issues_real_card(tmp_path):
    with make_client(tmp_path) as client:
        cards_before = client.get("/api/banking/overview").json()["cards"]

        body = run_agent(client, instruction="申请虚拟卡")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "yellow"
        assert body["confirmation"]["requires_reauth"] is False

        steps = body["plan"]["steps"]
        assert [step["tool_name"] for step in steps] == [
            "apply_virtual_card",
            "issue_virtual_card",
        ]
        assert steps[0]["arguments"]["requested_limit_cny"] == 3000.0
        assert steps[1]["depends_on"] == ["step-1"]
        assert steps[1]["arguments"]["application_id"] == ("${steps.step-1.data.application_id}")

        confirmed = confirm(client, body["confirmation"]["id"], approved=True)
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()
        assert result["status"] == "completed"
        assert len(result["results"]) == 2

        application_id = result["results"][0]["data"]["application_id"]
        issued_card = result["results"][1]["data"]
        assert issued_card["card_id"] == "CARD-9001"
        assert issued_card["masked_number"] == "**** 9001"
        assert issued_card["credit_limit_cny"] == 3000.0
        assert issued_card["available_limit_cny"] == 3000.0
        assert issued_card["transaction_limit_cny"] == 10000.0
        assert issued_card["account_id"] == "ACC-1001"
        assert issued_card["status"] == "active"

        applications = client.get("/api/cards/applications").json()["applications"]
        issued_application = next(
            item for item in applications if item["application_id"] == application_id
        )
        assert issued_application["status"] == "issued"
        assert issued_application["kind"] == "virtual"
        assert issued_application["card_id"] == "CARD-9001"
        assert issued_application["masked_number"] == "**** 9001"
        assert issued_application["requested_limit_cny"] == 3000.0

        cards_after = client.get("/api/banking/overview").json()["cards"]
        assert len(cards_after) == len(cards_before) + 1
        persisted = overview_card(client, "CARD-9001")
        assert persisted["credit_limit_cny"] == 3000.0
        assert persisted["repayment_day"] == 8


def test_reset_card_password_red_with_otp_and_audit_has_no_plaintext(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, instruction="修改卡片密码")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "red"
        assert body["confirmation"]["requires_reauth"] is True
        assert body["plan"]["steps"][0]["tool_name"] == "reset_card_password"
        assert body["plan"]["steps"][0]["arguments"] == {"card_id": "CARD-8821"}
        assert any("强验证" in reason for reason in body["risk"]["reasons"])

        action_id = body["confirmation"]["id"]
        wrong = confirm(client, action_id, approved=True, reauth_token="000000")
        assert wrong.status_code == 403

        confirmed = confirm(client, action_id, approved=True, reauth_token="246810")
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()
        assert result["status"] == "completed"
        data = result["results"][0]["data"]
        assert data["card_id"] == "CARD-8821"
        assert data["status"] == "password_reset_accepted"
        assert data["password_changed_at"]
        assert "password" not in {key for key in data if key == "password"}

        entries = client.get("/api/audit").json()["entries"]
        reset_entries = [item for item in entries if item["tool_name"] == "reset_card_password"]
        assert reset_entries
        assert {item["event"] for item in reset_entries} >= {
            "confirmation_requested",
            "tool_executed",
        }
        for item in reset_entries:
            assert item["arguments"] == {"card_id": "CARD-8821"}
            assert "password" not in json.dumps(item["arguments"]).lower()
            assert "123456" not in json.dumps(item, ensure_ascii=False)
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_unlock_transaction_limit_is_red_and_restores_default(tmp_path):
    with make_client(tmp_path) as client:
        setup = run_agent(
            client,
            instruction="设置交易限额",
            tool_name="set_transaction_limit",
            arguments={"card_id": "CARD-8821", "daily_limit_cny": 2000},
        )
        assert setup["status"] == "awaiting_confirmation"
        setup_done = confirm(client, setup["confirmation"]["id"], approved=True)
        assert setup_done.status_code == 200, setup_done.text
        assert overview_card(client, "CARD-8821")["transaction_limit_cny"] == 2000.0

        body = run_agent(client, instruction="解锁交易限额")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "red"
        assert body["confirmation"]["requires_reauth"] is True
        assert body["plan"]["steps"][0]["tool_name"] == "unlock_transaction_limit"
        assert body["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-8821"

        confirmed = confirm(
            client, body["confirmation"]["id"], approved=True, reauth_token="246810"
        )
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()
        assert result["status"] == "completed"
        data = result["results"][0]["data"]
        assert data["restored_default"] is True
        assert data["previous_transaction_limit_cny"] == 2000.0
        assert data["daily_limit_cny"] == 10000.0
        assert overview_card(client, "CARD-8821")["transaction_limit_cny"] == 10000.0


def test_unlock_transaction_limit_high_target_escalates_to_red(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, instruction="把交易限额恢复到 8000 元")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "red"
        assert body["confirmation"]["requires_reauth"] is True
        assert any("5000" in reason for reason in body["risk"]["reasons"])

        confirmed = confirm(
            client,
            body["confirmation"]["id"],
            approved=True,
            reauth_token="246810",
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "completed"
        assert overview_card(client, "CARD-8821")["transaction_limit_cny"] == 8000.0


def test_issue_virtual_card_rejects_invalid_application_id(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/agent/run",
            json={
                "instruction": "审核并发放虚拟卡",
                "tool_name": "issue_virtual_card",
                "arguments": {"application_id": "NOT-AN-APP"},
            },
        )
        assert response.status_code == 400, response.text
        assert "申请编号" in response.json()["detail"]
        applications = client.get("/api/cards/applications").json()["applications"]
        assert all(item["application_id"] != "NOT-AN-APP" for item in applications)


def test_revoked_permission_blocks_virtual_card_application(tmp_path):
    with make_client(tmp_path) as client:
        update = client.put("/api/permissions/apply_virtual_card", json={"granted": False})
        assert update.status_code == 200

        body = run_agent(client, instruction="申请虚拟卡")
        assert body["status"] == "blocked"
        assert "未授权" in body["reason"]
        assert "card:manage" in body["reason"]
        cards = client.get("/api/banking/overview").json()["cards"]
        assert all(card["card_id"] != "CARD-9001" for card in cards)


def test_cards_applications_route_returns_simulated_facts(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/api/cards/applications")
        assert response.status_code == 200
        body = response.json()
        assert body["simulated"] is True
        assert body["count"] == len(body["applications"])
        assert body["count"] >= 1

        seeded = next(item for item in body["applications"] if item["application_id"] == "APP-8001")
        assert seeded["kind"] == "virtual"
        assert seeded["status"] == "issued"
        assert seeded["card_id"] == "CARD-8821"
        assert seeded["masked_number"] == "**** 8821"
        assert seeded["requested_limit_cny"] == 8000.0


def test_card_intents_route_natural_language_without_hijacking_core(tmp_path):
    with make_client(tmp_path) as client:
        apply = run_agent(client, instruction="申请一张虚拟卡")
        assert [step["tool_name"] for step in apply["plan"]["steps"]] == [
            "apply_virtual_card",
            "issue_virtual_card",
        ]
        assert apply["risk_level"] == "yellow"

        password = run_agent(client, instruction="修改卡片密码 CARD-9902")
        assert password["plan"]["steps"][0]["tool_name"] == "reset_card_password"
        assert password["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-9902"
        assert password["risk_level"] == "red"

        credit_limit = run_agent(client, instruction="把信用卡额度调整到 8000 元")
        assert credit_limit["plan"]["steps"][0]["tool_name"] == "adjust_card_limit"
        assert credit_limit["risk_level"] == "red"


def test_password_intent_tolerates_card_id_between_verb_and_noun(tmp_path):
    with make_client(tmp_path) as client:
        for phrase in (
            "重置 CARD-8821 密码",
            "修改 CARD-8821 的密码",
            "重置卡片密码 CARD-8821",
        ):
            body = run_agent(client, instruction=phrase)
            assert body["status"] == "awaiting_confirmation", (phrase, body)
            assert [step["tool_name"] for step in body["plan"]["steps"]] == [
                "reset_card_password"
            ], phrase
            assert body["risk_level"] == "red", phrase
            assert body["confirmation"]["requires_reauth"] is True, phrase
