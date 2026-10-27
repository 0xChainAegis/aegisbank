"""P1 semantics, candidate attacks, scoped facts and execution-chain regressions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aegisbank_api.config import Settings
from aegisbank_api.main import create_app
from aegisbank_api.planning.compiler import PlanCompiler
from aegisbank_api.planning.contracts import PlanningRequest
from aegisbank_api.planning.factory import FallbackPlanner
from aegisbank_api.planning.llm import OpenAICompatiblePlanner, PlannerError
from aegisbank_api.planning.rule import RuleBasedPlanner
from aegisbank_api.planning.semantic import (
    SemanticError,
    SemanticPlanner,
    analyze_rules,
    verify_frame,
)
from aegisbank_api.planning.semantic_contracts import SemanticFrame, SemanticIntent, TextSpan
from aegisbank_api.planning.semantic_model import SemanticModel

CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "evals/nlp/p1-regression.json").read_text()
)


@pytest.fixture
def system(tmp_path):
    app = create_app(database_path=tmp_path / "semantic.db", settings=Settings(_env_file=None))
    with TestClient(app) as client:
        yield client, app.state.services


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_semantic_regression_corpus(system, case):
    client, _ = system
    response = client.post("/api/planner/plan", json={"instruction": case["instruction"]})
    assert response.status_code == 200, response.text
    body = response.json()
    if not case["tools"]:
        assert body["status"] in {"needs_clarification", "blocked"}, body
        assert not (body.get("plan") or {}).get("steps")
        return
    assert body["status"] == "planned", body
    plan = body["plan"]
    assert [s["tool_name"] for s in plan["steps"]] == case["tools"]
    for key, value in case["checks"].items():
        assert plan["steps"][0]["arguments"][key] == value
    assert plan["semantic"]["status"] == "verified"
    for evidence in plan["semantic"]["slots"]:
        assert evidence["verified"] is True
        source = evidence["span"]
        if source:
            assert case["instruction"][source["start"] : source["end"]] == source["text"]


def test_frame_strict_fields_and_version():
    frame = analyze_rules("给妈妈汇500元").model_dump()
    for patch in (
        {"risk_level": "green"},
        {"verified": True},
        {"user_id": "victim"},
        {"schema_version": "SemanticFrame/v2"},
        {"tool_name": "transfer"},
    ):
        with pytest.raises(ValidationError):
            SemanticFrame.model_validate({**frame, **patch})
    frame["intents"][0]["slots"]["amount"]["value"] = 9999
    with pytest.raises(ValidationError):
        SemanticFrame.model_validate(frame)


def test_mutated_candidates_rejected_without_tool_execution(system):
    _, services = system
    rule = RuleBasedPlanner(services.registry, services.repository)
    request = PlanningRequest(instruction="不要转账，只查余额")
    valid = analyze_rules(request.instruction)
    assert verify_frame(valid, request, rule).steps[0].tool_name == "query_balance"
    mutations = []
    f = valid.model_copy(deep=True)
    f.intents = f.intents[1:]
    mutations.append(f)
    f = valid.model_copy(deep=True)
    f.intents[0].polarity = "affirmative"
    mutations.append(f)
    f = valid.model_copy(deep=True)
    f.intents[1].kind = "contact_transfer"
    mutations.append(f)
    f = valid.model_copy(deep=True)
    f.intents[1].span.text = "伪造来源"
    mutations.append(f)
    f = valid.model_copy(deep=True)
    f.intents.append(f.intents[-1])
    mutations.append(f)
    for frame in mutations:
        with pytest.raises(SemanticError):
            verify_frame(frame, request, rule)
    request = PlanningRequest(instruction="给妈妈汇500元")
    frame = analyze_rules(request.instruction)
    frame.intents[0].slots["amount"] = frame.intents[0].slots["contact"]
    with pytest.raises(SemanticError):
        verify_frame(frame, request, rule)


def test_condition_cannot_be_hidden_in_full_span(system):
    _, services = system
    instruction = "如果余额足够，给妈妈汇500元"
    frame = SemanticFrame(
        intents=[
            SemanticIntent(
                id="i",
                kind="contact_transfer",
                span=TextSpan(start=0, end=len(instruction), text=instruction),
            )
        ]
    )
    with pytest.raises(SemanticError, match="条件"):
        verify_frame(
            frame,
            PlanningRequest(instruction=instruction),
            RuleBasedPlanner(services.registry, services.repository),
        )


def test_missing_amount_and_cross_user_fact_isolation(system):
    client, _ = system
    body = client.post("/api/agent/run", json={"instruction": "给妈妈汇钱"}).json()
    assert body["status"] == "needs_clarification"
    assert body["plan"]["semantic"]["frame"]["missing_slots"] == ["i1.amount"]
    body = client.post(
        "/api/agent/run", json={"instruction": "给妈妈汇500元", "user_id": "stranger"}
    ).json()
    assert body["status"] == "needs_clarification"
    assert body["plan"]["semantic"]["slots"][0]["candidates"] == []
    assert not body.get("confirmation")


def test_duplicate_contact_yields_scoped_choices(system):
    client, services = system
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO contacts (contact_id,user_id,name,alias,phone,account_id,"
            "birthday,relation,status) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "CONTACT-X",
                "demo-user",
                "张三",
                "另一个张三",
                "13800138009",
                "ACC-9009",
                "1990-01-01",
                "friend",
                "active",
            ),
        )
    body = client.post("/api/agent/run", json={"instruction": "给张三汇500元"}).json()
    assert body["status"] == "needs_clarification"
    evidence = body["plan"]["semantic"]["slots"][-1]
    assert not evidence["verified"]
    assert len(evidence["candidates"]) == 2
    assert all("138001380" not in c for c in evidence["candidates"])


def test_fact_failure_is_clarification_not_demo_fallback(system, monkeypatch):
    client, services = system

    def fail(*_):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(services.repository, "accounts", fail)
    request = PlanningRequest(instruction="看看工资卡还剩多少钱")
    plan = SemanticPlanner(RuleBasedPlanner(services.registry, services.repository)).plan(request)
    assert plan.needs_clarification
    assert not plan.steps
    response = client.post("/api/agent/run", json={"instruction": request.instruction})
    assert response.status_code == 503  # readiness also observes the failed bank read


def test_calendar_normalization_and_invalid_date(system):
    _, services = system
    rule = RuleBasedPlanner(services.registry, services.repository)
    request = PlanningRequest(instruction="上个月花销明细")
    plan = verify_frame(analyze_rules(request.instruction), request, rule, today=date(2027, 1, 1))
    assert plan.steps[0].arguments["month"] == "2026-12"
    assert plan.semantic.reference_date == "2027-01-01"
    request = PlanningRequest(instruction="2027-02-30给张三汇500元")
    with pytest.raises(SemanticError):
        verify_frame(analyze_rules(request.instruction), request, rule, today=date(2027, 1, 1))


def test_negative_write_plus_read_has_no_pending_or_balance_change(system):
    client, services = system
    before = services.repository.account("demo-user", "ACC-1001").balance_cny
    body = client.post("/api/agent/run", json={"instruction": "不要转账，只查余额"}).json()
    assert body["status"] == "completed"
    assert [r["tool_name"] for r in body["results"]] == ["query_balance"]
    assert services.repository.account("demo-user", "ACC-1001").balance_cny == before
    with services.db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0
    assert client.get("/api/audit/verify").json()["valid"]


def test_verified_transfer_confirmation_hash_and_idempotency(system):
    client, services = system
    instruction = "给妈妈汇1,500元"
    before = services.repository.account("demo-user", "ACC-1001").balance_cny
    body = client.post(
        "/api/agent/run",
        json={"instruction": instruction},
        headers={"Idempotency-Key": "semantic-run"},
    ).json()
    assert body["status"] == "awaiting_confirmation" and body["risk_level"] == "red"
    assert body["plan"]["semantic"]["status"] == "verified"
    endpoint = "/api/confirmations/" + body["confirmation"]["id"]
    data = {"approved": True, "reauth_token": "246810"}
    headers = {"Idempotency-Key": "semantic-confirm"}
    response = client.post(endpoint, json=data, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert client.post(endpoint, json=data, headers=headers).json() == response.json()
    assert services.repository.account("demo-user", "ACC-1001").balance_cny == before - 1500
    entries = client.get("/api/audit").json()["entries"]
    assert any(e["instruction"] == instruction for e in entries)
    assert client.get("/api/audit/verify").json()["valid"]


@pytest.mark.parametrize("malformed", [False, True])
def test_semantic_metadata_tampering_invalidates_confirmation(system, malformed):
    client, services = system
    before = services.repository.account("demo-user", "ACC-1001").balance_cny
    body = client.post("/api/agent/run", json={"instruction": "给妈妈汇500元"}).json()
    action = body["confirmation"]["id"]
    with services.db.transaction() as conn:
        row = conn.execute("SELECT plan_json FROM pending_actions WHERE id=?", (action,)).fetchone()
        plan = json.loads(row[0])
        if malformed:
            plan["semantic"]["status"] = "forged"
        else:
            plan["semantic"]["slots"][0]["value"] = "tampered"
        conn.execute(
            "UPDATE pending_actions SET plan_json=? WHERE id=?", (json.dumps(plan), action)
        )
    response = client.post("/api/confirmations/" + action, json={"approved": True})
    assert response.status_code == 409, response.text
    assert services.repository.account("demo-user", "ACC-1001").balance_cny == before


def test_model_adapter_only_accepts_semantics_and_sends_no_bank_facts(system):
    _, services = system
    instruction = "给妈妈汇500元"

    def handler(request):
        payload = json.loads(request.content)
        prompt = json.loads(payload["messages"][1]["content"])
        assert "tool_catalog" not in prompt and "contacts" not in prompt
        assert "balance_cny" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": analyze_rules(instruction).model_dump_json()}}]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        model = SemanticModel(base_url="https://example.test/v1", model="test", client=http)
        planner = SemanticPlanner(RuleBasedPlanner(services.registry, services.repository), model)
        plan = planner.plan(PlanningRequest(instruction=instruction))
        assert plan.semantic.status == "verified"
        assert plan.steps[0].arguments["amount_cny"] == 500


@pytest.mark.parametrize(
    "instruction,kind",
    [
        ("上周的花销让我困惑", "bill_analysis"),
        ("请告诉我备用账户余额", "balance"),
        ("不想查余额", "balance"),
        ("这月的花销有些让人困惑", "bill_analysis"),
    ],
)
def test_model_cannot_validate_unknown_read_qualifiers(system, instruction, kind):
    _, services = system
    frame = SemanticFrame(
        intents=[
            SemanticIntent(
                id="i",
                kind=kind,
                span=TextSpan(start=0, end=len(instruction), text=instruction),
            )
        ]
    )
    rule = RuleBasedPlanner(services.registry, services.repository)
    with pytest.raises(SemanticError, match="独立验证"):
        verify_frame(frame, PlanningRequest(instruction=instruction), rule)


def test_auto_fallback_retains_semantic_validation(system):
    _, services = system

    def fail(_):
        raise PlannerError("offline")

    baseline = RuleBasedPlanner(services.registry, services.repository)

    class Unavailable:
        plan = staticmethod(fail)

    planner = FallbackPlanner(Unavailable(), SemanticPlanner(baseline))
    plan = planner.plan(PlanningRequest(instruction="给妈妈汇500元"))
    assert plan.planner == "auto:rule-fallback" and plan.semantic.status == "verified"


def test_legacy_model_cannot_forge_verified_semantic_analysis(system):
    _, services = system

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "intent": "query_balance",
                                    "steps": [
                                        {"id": "q", "tool_name": "query_balance", "arguments": {}}
                                    ],
                                    "semantic": {"status": "verified"},
                                }
                            )
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        legacy = OpenAICompatiblePlanner(
            registry=services.registry,
            base_url="https://example.test",
            credential="",
            model="test",
            client=http,
        )
        with pytest.raises(PlannerError, match="契约外"):
            legacy.plan(PlanningRequest(instruction="查余额"))


def test_semantics_are_hash_bound_and_legacy_is_explicit(system):
    client, services = system
    planner = services.scheduler.planner
    request = PlanningRequest(instruction="给妈妈汇500元")
    plan = planner.plan(request)
    compiler = PlanCompiler(services.registry)
    first = compiler.compile(plan).plan_hash
    plan.semantic.slots[0].value = "changed"
    assert compiler.compile(plan).plan_hash != first
    body = client.post("/api/planner/plan", json={"instruction": "查询我的本月账单"}).json()
    assert body["plan"]["semantic"]["status"] == "legacy"
    assert client.get("/api/planner/info").json()["semantic_contract"] == "SemanticFrame/v1"


def test_card_tail_comes_from_bank_record_and_duplicate_is_ambiguous(system):
    client, services = system
    with services.db.transaction() as conn:
        conn.execute("UPDATE bank_cards SET masked_number='**** 9902' WHERE card_id='CARD-8821'")
        conn.execute("UPDATE bank_cards SET masked_number='**** 8821' WHERE card_id='CARD-9902'")
    body = client.post(
        "/api/planner/plan",
        json={
            "instruction": "尾号8821额度设成3000元",
        },
    ).json()
    assert body["status"] == "planned"
    assert body["plan"]["steps"][0]["arguments"]["card_id"] == "CARD-9902"
    with services.db.transaction() as conn:
        conn.execute("UPDATE bank_cards SET masked_number='**** 8821'")
    body = client.post(
        "/api/planner/plan",
        json={
            "instruction": "尾号8821额度设成3000元",
        },
    ).json()
    assert body["status"] == "needs_clarification"


def test_factory_roll_back_and_auto_without_model(system):
    from aegisbank_api.planning.factory import build_planner

    _, services = system
    request = PlanningRequest(instruction="给妈妈汇五百元")
    legacy = build_planner(
        Settings(_env_file=None, semantic_enabled=False, planner_mode="rule"),
        services.registry,
        services.repository,
    ).plan(request)
    assert legacy.semantic is None and legacy.needs_clarification
    current = build_planner(
        Settings(
            _env_file=None,
            semantic_enabled=True,
            planner_mode="auto",
            llm_base_url="",
            llm_model="",
        ),
        services.registry,
        services.repository,
    ).plan(request)
    assert current.semantic.status == "verified"
    assert current.steps[0].arguments["amount_cny"] == 500
