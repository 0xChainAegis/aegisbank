"""Every named card reference must agree before a card write is planned."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(database_path=tmp_path / "card-reference-conflicts.db")) as current:
        yield current


def request_plan(client: TestClient, instruction: str, **extra) -> dict:
    response = client.post("/api/planner/plan", json={"instruction": instruction, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def assert_clarification(body: dict) -> None:
    assert body["status"] == "needs_clarification", body
    assert body["plan"]["needs_clarification"] is True
    assert body["plan"]["steps"] == []
    assert not body.get("confirmation")


@pytest.mark.parametrize(
    "instruction",
    [
        "挂失尾号9902的卡和尾号8821的卡",
        "挂失尾号9902的卡 CARD-8821",
        "挂失 CARD-8821 尾号9902的卡",
        "挂失尾号9902的卡和后四位8821的卡",
        "挂失尾号9902的卡和尾号0000的卡",
        "挂失尾号0000的卡和尾号9902的卡",
        "挂失 CARD-9902 尾号0000的卡",
        "挂失 CARD-0000 尾号9902的卡",
        "挂失尾号99022的卡",
        "挂失 CARD-9902oops",
    ],
)
def test_conflicting_or_unknown_references_never_create_partial_card_actions(
    client: TestClient, instruction: str
) -> None:
    response = client.post("/api/agent/run", json={"instruction": instruction})
    assert response.status_code == 200, response.text
    assert_clarification(response.json())
    repository = client.app.state.services.repository
    assert all(card.status == "active" for card in repository.cards("demo-user"))
    with client.app.state.services.db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM pending_actions").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "instruction",
    [
        "挂失尾号9902的卡 CARD-9902",
        "挂失尾号9902的卡和末四位9902的卡",
        "挂失尾号9902的卡和尾号9902的卡",
        "挂失 CARD-9902（card-9902）",
    ],
)
def test_repeated_references_to_the_same_card_produce_exactly_one_step(
    client: TestClient, instruction: str
) -> None:
    body = request_plan(client, instruction)
    assert body["status"] == "planned", body
    assert len(body["plan"]["steps"]) == 1
    assert body["plan"]["steps"][0]["tool_name"] == "report_card_lost"
    assert body["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-9902"


@pytest.mark.parametrize(
    "instruction", ["挂失尾号9902的卡", "挂失 CARD-9902 尾号9902的卡"]
)
def test_an_ambiguous_suffix_is_not_silently_overridden_by_an_explicit_id(
    client: TestClient, instruction: str
) -> None:
    with client.app.state.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO bank_cards VALUES (?, ?, ?, ?, 'active', 100000, 100000, 8, 100000)",
            ("CARD-19902", "demo-user", "ACC-1001", "**** 9902"),
        )
    body = request_plan(client, instruction)
    assert_clarification(body)
    assert "CARD-19902" in body["reason"]
    # A complete ID alone remains unambiguous, including IDs longer than four digits.
    explicit = request_plan(client, "挂失 CARD-19902 的卡")
    assert explicit["status"] == "planned", explicit
    assert explicit["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-19902"


def add_other_users_card(client: TestClient, card_id: str, suffix: str) -> None:
    with client.app.state.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO bank_accounts VALUES (?, ?, ?, 'checking', 'CNY', 100000, 100000)",
            ("ACC-7777", "another-user", "另一用户的账户"),
        )
        conn.execute(
            "INSERT INTO bank_cards VALUES (?, ?, ?, ?, 'active', 100000, 100000, 8, 100000)",
            (card_id, "another-user", "ACC-7777", f"**** {suffix}"),
        )


def test_a_second_reference_owned_by_another_user_requires_clarification(
    client: TestClient,
) -> None:
    add_other_users_card(client, "CARD-7777", "7777")
    body = request_plan(client, "挂失尾号9902的卡和尾号7777的卡")
    assert_clarification(body)
    assert "CARD-7777" not in body["reason"]

    other_user = request_plan(
        client, "挂失 CARD-9902 尾号9902的卡", user_id="another-user"
    )
    assert_clarification(other_user)


def test_another_users_matching_suffix_does_not_make_the_current_card_ambiguous(
    client: TestClient,
) -> None:
    add_other_users_card(client, "CARD-79902", "9902")
    body = request_plan(client, "挂失尾号9902的卡")
    assert body["status"] == "planned", body
    assert body["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-9902"


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("report_card_lost", {}),
        ("unlock_card", {}),
        ("reset_card_password", {}),
        ("unlock_transaction_limit", {}),
        ("adjust_repayment_date", {"new_day": 18}),
        ("adjust_card_limit", {"new_limit_cny": 3000}),
        ("set_transaction_limit", {"daily_limit_cny": 2000}),
    ],
)
def test_explicit_tool_card_id_cannot_override_a_different_card_in_the_instruction(
    client: TestClient, tool_name: str, arguments: dict
) -> None:
    body = request_plan(
        client, "处理尾号9902的卡", tool_name=tool_name,
        arguments={**arguments, "card_id": "CARD-8821"},
    )
    assert_clarification(body)


def test_explicit_tool_arguments_do_not_hide_conflicting_text_references(
    client: TestClient,
) -> None:
    body = request_plan(
        client, "挂失尾号9902的卡和尾号8821的卡", tool_name="report_card_lost",
        arguments={"card_id": "CARD-9902"},
    )
    assert_clarification(body)
    unknown = request_plan(
        client, "挂失尾号0000的卡", tool_name="report_card_lost",
        arguments={"card_id": "CARD-9902"},
    )
    assert_clarification(unknown)


def test_single_card_default_does_not_override_an_explicit_missing_card(client: TestClient) -> None:
    with client.app.state.services.db.transaction() as conn:
        conn.execute("DELETE FROM bank_cards WHERE card_id = 'CARD-8821'")
    unspecified = request_plan(client, "挂失我的卡")
    assert unspecified["status"] == "planned", unspecified
    assert unspecified["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-9902"
    assert any("仅有一张卡片" in item for item in unspecified["plan"]["assumptions"])
    missing = request_plan(client, "挂失尾号8821的卡")
    assert_clarification(missing)
