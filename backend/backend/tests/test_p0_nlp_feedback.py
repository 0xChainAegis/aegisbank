"""Regression coverage for the six P0 oral-language feedback inputs.

These tests use the real FastAPI planning/execution chain with a temporary
SQLite demo bank. They assert the resolved plan as well as the user-visible
status, so a read-only fallback (for example list_subscriptions or a silent
CARD-8821 default) cannot be mistaken for a completed write intent.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "p0-nlp-feedback.db"))


def run_agent(client: TestClient, instruction: str) -> dict:
    response = client.post("/api/agent/run", json={"instruction": instruction})
    assert response.status_code == 200, response.text
    return response.json()


def plan_steps(body: dict) -> list[dict]:
    return (body.get("plan") or {}).get("steps") or []


def test_masked_suffix_9902_resolves_card_9902_never_8821(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "我那张尾号9902的卡挂失")

        assert body["status"] == "awaiting_confirmation", body
        assert body["risk_level"] == "red"
        assert body["plan"]["intent"] == "report_card_lost"
        steps = plan_steps(body)
        assert [step["tool_name"] for step in steps] == ["report_card_lost"]
        assert steps[0]["arguments"]["card_id"] == "CARD-9902"
        assert "CARD-8821" not in json.dumps(body["plan"], ensure_ascii=False)


def test_card_specific_write_requires_an_unambiguous_card(tmp_path):
    with make_client(tmp_path) as client:
        cases = (
            ("挂失我的卡", "report_card_lost"),
            ("挂失尾号0000的卡", "report_card_lost"),
            ("修改卡片密码", "reset_card_password"),
            ("把尾号0000的卡还款日改到18号", "adjust_repayment_date"),
            ("把尾号0000的卡额度调整到5000元", "adjust_card_limit"),
        )
        for instruction, expected_intent in cases:
            body = run_agent(client, instruction)
            assert body["status"] == "needs_clarification", (instruction, body)
            assert body["plan"]["intent"] == expected_intent, (instruction, body)
            assert plan_steps(body) == []
            reason = body.get("reason") or ""
            assert "CARD-8821" in reason and "CARD-9902" in reason, reason


def test_spoken_mother_alias_resolves_seeded_contact(tmp_path):
    with make_client(tmp_path) as client:
        for instruction in ("给我妈转200", "给我老妈转200", "给我母亲转200"):
            body = run_agent(client, instruction)
            assert body["status"] == "awaiting_confirmation", (instruction, body)
            steps = plan_steps(body)
            assert [step["tool_name"] for step in steps] == ["transfer_to_contact"]
            assert steps[0]["arguments"]["to_name"] == "妈妈"
            assert steps[0]["arguments"]["amount_cny"] == 200.0


def test_wan_amount_with_account_receiver_is_10000_cny(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "转1万给ACC-2002")

        assert body["status"] == "awaiting_confirmation", body
        assert body["plan"]["intent"] == "transfer"
        steps = plan_steps(body)
        assert [step["tool_name"] for step in steps] == ["transfer"]
        assert steps[0]["arguments"]["to_account"] == "ACC-2002"
        assert steps[0]["arguments"]["amount_cny"] == 10_000.0


def test_numeric_card_settings_without_card_ask_with_candidates(tmp_path):
    with make_client(tmp_path) as client:
        cases = (
            ("把还款日改到18号", "adjust_repayment_date"),
            ("把信用卡额度调整到10000元", "adjust_card_limit"),
            ("把单日交易限额调整到2000元", "set_transaction_limit"),
        )
        for instruction, expected_intent in cases:
            body = run_agent(client, instruction)
            assert body["status"] == "needs_clarification", (instruction, body)
            assert body["plan"]["intent"] == expected_intent, (instruction, body)
            assert plan_steps(body) == []
            reason = body.get("reason") or ""
            assert "CARD-8821" in reason and "CARD-9902" in reason, reason
            assert "ambiguous_amount" not in json.dumps(body, ensure_ascii=False)


def test_numeric_card_settings_with_explicit_card_plan_that_card(tmp_path):
    with make_client(tmp_path) as client:
        cases = (
            (
                "把 CARD-9902 的还款日改到18号",
                "adjust_repayment_date",
                "new_day",
                18,
            ),
            (
                "把 CARD-9902 的信用卡额度调整到10000元",
                "adjust_card_limit",
                "new_limit_cny",
                10_000.0,
            ),
            (
                "把 CARD-9902 的单日交易限额调整到2000元",
                "set_transaction_limit",
                "daily_limit_cny",
                2_000.0,
            ),
        )
        for instruction, expected_intent, field, value in cases:
            body = run_agent(client, instruction)
            assert body["status"] == "awaiting_confirmation", (instruction, body)
            assert body["plan"]["intent"] == expected_intent, (instruction, body)
            steps = plan_steps(body)
            assert len(steps) == 1, (instruction, body)
            assert steps[0]["arguments"]["card_id"] == "CARD-9902", instruction
            assert steps[0]["arguments"][field] == value, instruction


def test_single_existing_card_is_used_with_explicit_assumption(tmp_path):
    app = create_app(database_path=tmp_path / "single-card.db")
    with TestClient(app) as client:
        with app.state.services.db.transaction() as conn:
            conn.execute(
                "DELETE FROM bank_cards WHERE user_id = ? AND card_id = ?",
                ("demo-user", "CARD-9902"),
            )

        body = run_agent(client, "把还款日改到18号")
        assert body["status"] == "awaiting_confirmation", body
        step = plan_steps(body)[0]
        assert step["arguments"]["card_id"] == "CARD-8821"
        assert any("仅有一张卡片" in item for item in body["plan"]["assumptions"])


def test_price_increased_subscription_is_cancelled_not_listed(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "把那个涨价的订阅退掉")

        assert body["status"] == "awaiting_confirmation", body
        assert body["risk_level"] == "yellow"
        assert body["plan"]["intent"] == "cancel_subscription"
        steps = plan_steps(body)
        assert [step["tool_name"] for step in steps] == ["cancel_subscription"]
        assert steps[0]["arguments"]["subscription_id"] == "SUB-3002"
        assert "list_subscriptions" not in json.dumps(body["plan"], ensure_ascii=False)


def test_lost_card_freeze_phrase_maps_to_lost_intent_and_asks_for_card(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "卡丢了，帮我冻结一下")

        assert body["status"] == "needs_clarification", body
        assert body["plan"]["intent"] == "report_card_lost"
        assert plan_steps(body) == []
        reason = body.get("reason") or ""
        assert "CARD-8821" in reason and "CARD-9902" in reason

        explicit = run_agent(client, "卡丢了，帮我冻结 CARD-9902")
        assert explicit["status"] == "awaiting_confirmation", explicit
        step = plan_steps(explicit)[0]
        assert step["tool_name"] == "report_card_lost"
        assert step["arguments"]["card_id"] == "CARD-9902"
        assert any("冻结" in item for item in explicit["plan"]["assumptions"])

CARD_WRITE_TOOLS = (
    ("挂失", "report_card_lost", {}),
    ("解除挂失", "unlock_card", {}),
    ("修改卡片密码", "reset_card_password", {}),
    ("解锁交易限额", "unlock_transaction_limit", {}),
    ("把还款日改到18号", "adjust_repayment_date", {"new_day": 18}),
    ("把信用卡额度调整到10000元", "adjust_card_limit", {"new_limit_cny": 10_000}),
    ("把单日交易限额调整到2000元", "set_transaction_limit", {"daily_limit_cny": 2_000}),
)


def test_explicit_card_write_tools_without_card_require_clarification(tmp_path):
    with make_client(tmp_path) as client:
        for instruction, tool_name, arguments in CARD_WRITE_TOOLS:
            response = client.post(
                "/api/planner/plan",
                json={
                    "instruction": instruction,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )
            assert response.status_code == 200, (tool_name, response.text)
            body = response.json()
            assert body["status"] == "needs_clarification", (tool_name, body)
            assert body["plan"]["steps"] == [], (tool_name, body)
            reason = body.get("reason") or ""
            assert "CARD-8821" in reason and "CARD-9902" in reason, (
                tool_name,
                reason,
            )


def test_explicit_card_write_tool_with_card_id_in_arguments_is_planned(tmp_path):
    with make_client(tmp_path) as client:
        for _, tool_name, arguments in CARD_WRITE_TOOLS:
            payload_arguments = dict(arguments)
            payload_arguments["card_id"] = "CARD-9902"
            response = client.post(
                "/api/planner/plan",
                json={
                    "instruction": "执行卡片操作",
                    "tool_name": tool_name,
                    "arguments": payload_arguments,
                },
            )
            assert response.status_code == 200, (tool_name, response.text)
            body = response.json()
            assert body["status"] == "planned", (tool_name, body)
            assert body["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-9902"


def test_explicit_card_write_tool_resolves_card_from_instruction(tmp_path):
    with make_client(tmp_path) as client:
        for instruction, tool_name, arguments in (
            ("挂失 CARD-9902", "report_card_lost", {}),
            ("解除挂失 CARD-9902", "unlock_card", {}),
            ("修改 CARD-9902 的密码", "reset_card_password", {}),
            ("解锁 CARD-9902 的交易限额", "unlock_transaction_limit", {}),
            (
                "把 CARD-9902 的还款日改到18号",
                "adjust_repayment_date",
                {"new_day": 18},
            ),
            (
                "把 CARD-9902 的信用卡额度调整到10000元",
                "adjust_card_limit",
                {"new_limit_cny": 10_000},
            ),
            (
                "把 CARD-9902 的单日交易限额调整到2000元",
                "set_transaction_limit",
                {"daily_limit_cny": 2_000},
            ),
        ):
            response = client.post(
                "/api/planner/plan",
                json={
                    "instruction": instruction,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )
            assert response.status_code == 200, (tool_name, response.text)
            body = response.json()
            assert body["status"] == "planned", (tool_name, body)
            step = body["plan"]["steps"][0]
            assert step["tool_name"] == tool_name
            assert step["arguments"]["card_id"] == "CARD-9902"


def test_unlock_wording_routes_to_unlock_card(tmp_path):
    with make_client(tmp_path) as client:
        for instruction in ("解除挂失 CARD-9902", "解除卡片挂失 CARD-9902"):
            body = run_agent(client, instruction)
            assert body["status"] == "awaiting_confirmation", (instruction, body)
            steps = plan_steps(body)
            assert [step["tool_name"] for step in steps] == ["unlock_card"]
            assert steps[0]["arguments"]["card_id"] == "CARD-9902"
            assert body["risk_level"] == "red"


def test_card_tool_validation_rejects_missing_card_id(tmp_path):
    with make_client(tmp_path) as client:
        registry = client.app.state.services.require_registry()
        for _, tool_name, arguments in CARD_WRITE_TOOLS:
            tool = registry.get(tool_name)
            with pytest.raises(ValueError) as error:
                tool.validate_arguments(dict(arguments))
            assert "card_id" in str(error.value), (tool_name, str(error.value))
