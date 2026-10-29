"""P1 acceptance: oral rephrasings, complete evidence and business dates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.config import Settings
from aegisbank_api.main import create_app

PROBES = json.loads(
    (Path(__file__).resolve().parents[1] / "evals/nlp/p1-review-probes.json").read_text()
)


@pytest.fixture
def system(tmp_path):
    app = create_app(database_path=tmp_path / "p1.db", settings=Settings(_env_file=None))
    with TestClient(app) as client:
        yield client, app.state.services


@pytest.mark.parametrize("case", PROBES, ids=lambda c: c["id"])
def test_review_rephrasings_are_semantically_verified(system, case):
    client, _ = system
    response = client.post("/api/planner/plan", json={"instruction": case["instruction"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "planned", body
    assert body["plan"]["semantic"]["status"] == "verified", body
    assert [s["tool_name"] for s in body["plan"]["steps"]] == case["tools"]
    for key, value in case["checks"].items():
        assert body["plan"]["steps"][0]["arguments"][key] == value


def test_semantic_calendar_uses_shanghai_month_and_tomorrow(system, monkeypatch):
    from aegisbank_api.planning import semantic

    class Clock(datetime):
        @classmethod
        def now(cls, tz=UTC):
            return datetime(2026, 10, 31, 16, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(semantic, "datetime", Clock)
    client, _ = system
    bill = client.post("/api/planner/plan", json={"instruction": "上个月花销明细"}).json()
    assert bill["plan"]["steps"][0]["arguments"]["month"] == "2026-10"
    assert bill["plan"]["semantic"]["reference_date"] == "2026-11-01"
    assert bill["plan"]["semantic"]["timezone"] == "Asia/Shanghai"


@pytest.mark.parametrize("value", [999, "not-a-number", None])
def test_canonical_planner_cannot_change_verified_amount(system, value):
    from aegisbank_api.planning.contracts import PlanningRequest
    from aegisbank_api.planning.rule import RuleBasedPlanner
    from aegisbank_api.planning.semantic import SemanticPlanner

    _, services = system

    class WrongAmount(RuleBasedPlanner):
        def plan(self, request):
            plan = super().plan(request)
            plan.steps[0].arguments["amount_cny"] = value
            return plan

    planner = SemanticPlanner(WrongAmount(services.registry, services.repository))
    result = planner.plan(PlanningRequest(instruction="给妈妈汇五百元"))
    assert result.needs_clarification and not result.steps
    assert "不一致" in result.clarification


@pytest.mark.parametrize(
    "instruction",
    [
        "麻烦给小明汇五百元",
        "麻烦给妈妈汇1,50元",
        "给妈妈汇人民币500美元",
        "请给妈妈汇五百元，然后顺便发邮件",
        "假如余额足够请给妈妈汇五百元",
        "不要给妈妈汇五百元",
        "以后别给AI 工具订阅续费了，但先给妈妈汇500元",
    ],
)
def test_new_grammar_rejections_leave_no_financial_or_pending_changes(system, instruction):
    client, services = system
    before = services.repository.overview("demo-user").model_dump()
    result = client.post("/api/agent/run", json={"instruction": instruction})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] in {"needs_clarification", "blocked"}, body
    assert services.repository.overview("demo-user").model_dump() == before
    with services.db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0


def test_contact_without_phone_uses_verified_name_selector(system):
    client, services = system
    with services.db.transaction() as conn:
        conn.execute("UPDATE contacts SET phone=NULL WHERE name='妈妈'")
    body = client.post("/api/planner/plan", json={"instruction": "给妈妈汇五百元"}).json()
    assert body["status"] == "planned", body
    assert body["plan"]["steps"][0]["arguments"]["to_name"] == "妈妈"
    assert body["plan"]["semantic"]["status"] == "verified"


@pytest.mark.parametrize(
    "instruction",
    [
        ";".join(["查余额"] * 13),
        ";".join(["未知"] * 25),
        "如果" * 13,
    ],
)
def test_large_frames_clarify_without_truncating_or_exposing_validation_errors(system, instruction):
    client, _ = system
    response = client.post("/api/planner/plan", json={"instruction": instruction})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "needs_clarification"
    assert not response.json()["plan"].get("steps")


@pytest.mark.parametrize(
    "instruction",
    [
        "我不想给妈妈转500元",
        "不是要给妈妈转500元",
        "给妈妈转500元别执行",
        "给妈妈转500元要等工资到账",
        "给妈妈转500元后给爸爸发条短信",
        "帮我准备妈妈的生日，预算1000元，还要订个餐厅",
    ],
)
@pytest.mark.parametrize("arguments", [{}, {"unused": True}, {"amount_cny": 500}])
def test_uncovered_or_argument_only_requests_cannot_create_partial_writes(
    system,
    instruction,
    arguments,
):
    client, services = system
    before = services.repository.overview("demo-user").model_dump()
    response = client.post(
        "/api/agent/run",
        json={
            "instruction": instruction,
            "arguments": arguments,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "needs_clarification", response.text
    assert services.repository.overview("demo-user").model_dump() == before
    with services.db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0


@pytest.mark.parametrize(
    "instruction,expected",
    [
        ("明天给张三汇500元", "2026-11-02"),
        ("明天给张三转账500元", "2026-11-02"),
        ("明天给ACC-9003转500元", "2026-11-02"),
        ("每月1号给张三转500元", "2026-12-01"),
    ],
)
def test_relative_schedule_legacy_and_semantics_agree_after_shanghai_midnight(
    system,
    monkeypatch,
    instruction,
    expected,
):
    from aegisbank_api.planning import semantic, semantic_legacy
    from aegisbank_api.scenarios import automation

    class Clock(datetime):
        @classmethod
        def now(cls, tz=UTC):
            return datetime(2026, 10, 31, 16, 30, tzinfo=UTC).astimezone(tz)

    for module in (semantic, semantic_legacy, automation):
        monkeypatch.setattr(module, "datetime", Clock)
    client, _ = system
    response = client.post("/api/planner/plan", json={"instruction": instruction})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "planned", body
    assert body["plan"]["steps"][0]["arguments"]["to_account"] == "ACC-9003"
    assert body["plan"]["steps"][0]["arguments"]["run_at"].startswith(expected)
