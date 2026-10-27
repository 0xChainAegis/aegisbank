"""P0 semantic safety: partial understanding must never become a write plan."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from aegisbank_api.config import Settings
from aegisbank_api.main import create_app
from aegisbank_api.planning.amounts import AmountError, money_mentions
from aegisbank_api.planning.contracts import ExecutionPlan, PlanningRequest, PlanStep
from aegisbank_api.planning.factory import FallbackPlanner
from aegisbank_api.planning.llm import OpenAICompatiblePlanner, _candidate_conflict
from aegisbank_api.planning.rule import RuleBasedPlanner
from aegisbank_api.tools.finance import build_registry


@pytest.fixture
def system(tmp_path):
    app = create_app(
        database_path=tmp_path / "nlp.db",
        settings=Settings(_env_file=None, planner_mode="rule", automation_enabled=False),
    )
    with TestClient(app) as client:
        yield client, app.state.services


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1,500元", "1500"),
        ("１，５００．５０元", "1500.50"),
        ("五百块", "500"),
        ("壹仟伍佰元", "1500"),
        ("两千元", "2000"),
        ("一千零五元", "1005"),
        ("一千零五十元", "1050"),
        ("一万零五元", "10005"),
        ("1.5万元", "15000"),
        ("0.01元", "0.01"),
        ("五百点五元", "500.5"),
        ("￥1,500.50", "1500.50"),
        ("CNY 1500", "1500"),
        ("人民币500", "500"),
    ],
)
def test_money_whole_token_and_provenance(text, expected):
    instruction = f"给妈妈转{text}"
    mentions = money_mentions(instruction)
    assert len(mentions) == 1
    item = mentions[0]
    assert item.value == Decimal(expected)
    assert instruction[item.start : item.end] == item.raw
    assert [m.value for m in money_mentions(f"给妈妈转一笔{text}")] == [Decimal(expected)]


@pytest.mark.parametrize(
    "text",
    [
        "1,50元",
        "1,500,00元",
        "1.500,00元",
        ".50元",
        "1 500元",
        "1_500元",
        "1e3元",
        "-500元",
        "+500元",
        "1/2元",
        "500.001元",
        "0元",
        "500美元",
        "$500",
        "500欧元",
        "一百五元",
        "一万五元",
        "500元5角",
        "500多元",
        "500左右",
        "大约500元",
        "500k",
        "1.5万亿",
        "一百百元",
        "500ＵＳＤ",
        "500港元",
        "500刀",
        "1.00000000000000000000000000000001元",
    ],
)
def test_ambiguous_amount_never_yields_substring(text):
    with pytest.raises(AmountError):
        money_mentions(f"给妈妈转{text}")


UNSUPPORTED = [
    "如果余额超过1000元，就给妈妈转500元",
    "余额够了就给妈妈转500元",
    "向 ACC-2002 转账500元，前提是有足够余额",
    "只有余额大于1000元才转账500元给 ACC-2002",
    "向 ACC-2002 转账500元 if balance exceeds 1000",
    "先查余额，再给妈妈转500元，然后查询订阅",
    "给妈妈转500元，查询余额",
    "查询余额和订阅",
    "分析账单并取消异常订阅，然后查余额",
    "帮我准备妈妈的生日，预算1000元，然后查询订阅",
    "和妈妈、张三 AA 300，然后查余额",
    "取消订阅 SUB-3001 和 SUB-3002",
    "向 ACC-2002 和 ACC-3003 转账100元",
    "把额度从500元改成300元",
    "向 ACC-2002 转账1,50元",
    "给妈妈转1.001元",
    "明天给张三转500美元",
    "和妈妈、张三 AA 300，挂失CARD-8821",
    "给13800138000和13900001111转500元",
    "挂失所有银行卡",
]


def snapshot(services):
    # Compare every business table and pending action, allowing only audit and
    # idempotency/clarification bookkeeping to change.
    with services.db.transaction() as conn:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            if r[0]
            not in {"audit_log", "sqlite_sequence", "idempotency_keys", "clarification_uses"}
        ]
        return {t: [tuple(r) for r in conn.execute(f'SELECT * FROM "{t}"')] for t in tables}


def test_unsupported_semantics_do_not_create_pending_or_write_business_state(system):
    client, services = system
    before = snapshot(services)
    for instruction in UNSUPPORTED:
        for endpoint in ("/api/planner/plan", "/api/agent/run"):
            response = client.post(endpoint, json={"instruction": instruction})
            assert response.status_code == 200, (instruction, response.text)
            body = response.json()
            assert body["status"] == "needs_clarification", (instruction, body)
            assert body["plan"]["steps"] == []
            assert not body.get("confirmation")
            assert snapshot(services) == before, instruction
    assert client.get("/api/audit/verify").json()["valid"] is True
    entries = client.get("/api/audit").json()["entries"]
    assert any(e["event"] == "planning_clarification" for e in entries)
    assert not any(e["event"] == "tool_executed" for e in entries)


def test_explicit_tool_cannot_bypass_preflight(system):
    client, services = system
    before = snapshot(services)
    for instruction in UNSUPPORTED + ["向 ACC-2002 转账1,500元"]:
        for endpoint in ("/api/planner/plan", "/api/agent/run"):
            response = client.post(
                endpoint,
                json={
                    "instruction": instruction,
                    "tool_name": "transfer",
                    "arguments": {
                        "from_account": "ACC-1001",
                        "to_account": "ACC-2002",
                        "amount_cny": 500,
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "needs_clarification", instruction
            assert snapshot(services) == before


def test_normalization_in_all_money_scenarios(system):
    client, _ = system
    cases = [
        ("向 ACC-2002 转账1,500元", "transfer", "amount_cny", 1500),
        ("给妈妈转五百块", "transfer_to_contact", "amount_cny", 500),
        ("明天给张三转1,500", "schedule_transfer", "amount_cny", 1500),
        ("和妈妈、张三 AA 1,500", "transfer_to_contact", "amount_cny", 500),
        ("把 CARD-8821 的信用卡额度调整到1.5万元", "adjust_card_limit", "new_limit_cny", 15000),
        ("买一千元稳健短债A", "purchase_wealth", "amount_cny", 1000),
    ]
    for instruction, tool, field, value in cases:
        response = client.post("/api/planner/plan", json={"instruction": instruction})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "planned", (instruction, body)
        step = body["plan"]["steps"][0]
        assert step["tool_name"] == tool
        assert step["arguments"][field] == value
        assert any("金额来源：" in a for a in body["plan"]["assumptions"])


def test_1500_red_confirmation_exact_debit_idempotency_original_audit(system):
    client, services = system
    instruction = "向 ACC-2002 转账 1,500 元"
    before = services.repository.account("demo-user", "ACC-1001").balance_cny
    headers = {"Idempotency-Key": "nlp-run"}
    body = client.post("/api/agent/run", json={"instruction": instruction}, headers=headers).json()
    assert body["status"] == "awaiting_confirmation"
    assert body["risk_level"] == "red"
    assert body["confirmation"]["requires_reauth"] is True
    assert (
        client.post("/api/agent/run", json={"instruction": instruction}, headers=headers).json()
        == body
    )
    endpoint = f"/api/confirmations/{body['confirmation']['id']}"
    confirmation = {"approved": True, "reauth_token": "246810"}
    headers = {"Idempotency-Key": "nlp-confirm"}
    response = client.post(endpoint, json=confirmation, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert client.post(endpoint, json=confirmation, headers=headers).json() == response.json()
    assert services.repository.account("demo-user", "ACC-1001").balance_cny == before - 1500
    entries = client.get("/api/audit").json()["entries"]
    assert any(
        e["instruction"] == instruction and e["arguments"].get("amount_cny") == 1500
        for e in entries
    )
    assert client.get("/api/audit/verify").json()["valid"] is True


def test_supported_compositions_and_schedule_survive(system):
    client, _ = system
    cases = [
        ("分析我的本月账单并取消异常订阅", ["query_bill", "cancel_subscription"]),
        (
            "帮我准备下个月妈妈的生日，预算一千元",
            [
                "query_contact_birthday",
                "lock_budget_funds",
                "schedule_flower_order",
                "schedule_cake_order",
            ],
        ),
        ("和妈妈、张三 AA 300", ["transfer_to_contact", "transfer_to_contact"]),
        ("每月5号给张三转500", ["schedule_transfer"]),
        ("再向 ACC-2002 转账500元", ["transfer"]),
    ]
    for instruction, tools in cases:
        body = client.post("/api/planner/plan", json={"instruction": instruction}).json()
        assert body["status"] == "planned", body
        assert [s["tool_name"] for s in body["plan"]["steps"]] == tools
        if "生日" in instruction:
            assert body["plan"]["steps"][1]["arguments"]["amount_cny"] == 1000


def test_clarification_follow_up_uses_same_safety_checks(system):
    client, services = system
    for answer in ("如果余额够就转100元", "100元，然后查询订阅", "1,50元"):
        first = client.post("/api/agent/run", json={"instruction": "给张三转账"}).json()
        before = snapshot(services)
        response = client.post(
            "/api/agent/run", json={"instruction": answer, "clarification_run_id": first["run_id"]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "needs_clarification"
        assert snapshot(services) == before
    first = client.post("/api/agent/run", json={"instruction": "给张三转账"}).json()
    body = client.post(
        "/api/agent/run", json={"instruction": "五百块", "clarification_run_id": first["run_id"]}
    ).json()
    assert body["status"] == "awaiting_confirmation", body
    assert body["plan"]["steps"][0]["arguments"]["amount_cny"] == 500


def test_llm_and_auto_reject_unsupported_before_network():
    def handler(request):
        pytest.fail("Unsupported semantics must not reach a model")

    registry = build_registry()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm = OpenAICompatiblePlanner(
            registry=registry,
            base_url="https://example.test/v1",
            credential="",
            model="test",
            client=client,
        )
        for planner in (llm, FallbackPlanner(llm, RuleBasedPlanner(registry))):
            for instruction in UNSUPPORTED:
                plan = planner.plan(PlanningRequest(instruction=instruction))
                assert plan.needs_clarification, instruction
                assert plan.steps == []


def test_candidate_cannot_reintroduce_truncation_or_partial_plan():
    rule = RuleBasedPlanner(build_registry())
    request = PlanningRequest(instruction="向 ACC-2002 转账1,500元")
    correct = rule.plan(request)
    assert not _candidate_conflict(correct, request, correct)
    wrong = correct.model_copy(deep=True)
    wrong.steps[0].arguments["amount_cny"] = 500
    assert _candidate_conflict(wrong, request, correct)
    assert _candidate_conflict(wrong, request)
    query = ExecutionPlan(
        intent="query_balance",
        steps=[PlanStep(id="q", tool_name="query_balance", arguments={"account_id": "ACC-1001"})],
    )
    for instruction in UNSUPPORTED:
        assert _candidate_conflict(query, PlanningRequest(instruction=instruction))


def test_llm_candidate_normalized_amount_and_truncation():
    for amount in (500, 1500):
        candidate = {
            "intent": "transfer",
            "steps": [
                {
                    "id": "s",
                    "tool_name": "transfer",
                    "arguments": {
                        "from_account": "ACC-1001",
                        "to_account": "ACC-2002",
                        "amount_cny": amount,
                    },
                }
            ],
        }

        def handler(request, candidate=candidate):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(candidate)}}]}
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = OpenAICompatiblePlanner(
                registry=build_registry(),
                base_url="https://example.test/v1",
                credential="",
                model="test",
                client=client,
            )
            plan = llm.plan(PlanningRequest(instruction="向 ACC-2002 转账1,500元"))
            assert plan.needs_clarification is (amount == 500)
            if amount == 1500:
                assert any("1,500" in a for a in plan.assumptions)


def test_missing_subscription_facts_cannot_select_demo_target():
    plan = RuleBasedPlanner(build_registry()).plan(PlanningRequest(instruction="取消订阅"))
    assert plan.needs_clarification
    assert plan.steps == []
