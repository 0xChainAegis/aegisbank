from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from aegisbank_api.main import create_app
from aegisbank_api.planning.compiler import PlanCompilationError, PlanCompiler
from aegisbank_api.planning.contracts import (
    ExecutionPlan,
    PlanningRequest,
    PlanStep,
)
from aegisbank_api.planning.factory import FallbackPlanner
from aegisbank_api.planning.llm import OpenAICompatiblePlanner, PlannerError
from aegisbank_api.planning.rule import RuleBasedPlanner
from aegisbank_api.tools.finance import build_registry


def test_rule_planner_returns_structured_transfer_plan():
    registry = build_registry()
    planner = RuleBasedPlanner(registry)
    plan = planner.plan(
        PlanningRequest(instruction="向 ACC-2002 转账 880 元")
    )

    assert plan.needs_clarification is False
    assert plan.intent == "transfer"
    assert plan.steps[0].tool_name == "transfer"
    assert plan.steps[0].arguments["to_account"] == "ACC-2002"
    assert plan.steps[0].arguments["amount_cny"] == 880.0
    assert plan.assumptions


def test_rule_planner_asks_for_missing_high_risk_arguments():
    registry = build_registry()
    planner = RuleBasedPlanner(registry)

    plan = planner.plan(PlanningRequest(instruction="我要转账"))

    assert plan.needs_clarification is True
    assert plan.steps == []
    assert "金额" in (plan.clarification or "")


def test_plan_compiler_validates_schema_and_produces_dag_hash():
    registry = build_registry()
    planner = RuleBasedPlanner(registry)
    plan = planner.plan(PlanningRequest(instruction="查询 ACC-1001 的本月账单"))

    compiled = PlanCompiler(registry).compile(plan)

    assert compiled.dag_path == "step-1:query_bill"
    assert len(compiled.plan_hash) == 64
    assert compiled.nodes[0].arguments["period"] == "current_month"
    assert compiled.as_dict()["steps"][0]["risk_level"] == "green"


def test_plan_compiler_rejects_unknown_tool_and_cycles():
    registry = build_registry()
    compiler = PlanCompiler(registry)

    unknown = ExecutionPlan(
        intent="unknown-tool",
        steps=[PlanStep(id="step-1", tool_name="drop_table", arguments={})],
    )
    try:
        compiler.compile(unknown)
    except PlanCompilationError as exc:
        assert "未注册" in str(exc)
    else:
        raise AssertionError("unknown tool should be rejected")

    cyclic = ExecutionPlan(
        intent="cycle",
        steps=[
            PlanStep(id="step-1", tool_name="query_bill", depends_on=["step-2"]),
            PlanStep(id="step-2", tool_name="query_bill", depends_on=["step-1"]),
        ],
    )
    try:
        compiler.compile(cyclic)
    except PlanCompilationError as exc:
        assert "循环依赖" in str(exc)
    else:
        raise AssertionError("cycle should be rejected")


def test_openai_compatible_planner_parses_structured_output():
    registry = build_registry()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        content = json.dumps(
            {
                "intent": "query_bill",
                "steps": [
                    {
                        "id": "step-1",
                        "tool_name": "query_bill",
                        "arguments": {"account_id": "ACC-1001"},
                        "depends_on": [],
                        "description": "查询账单",
                    }
                ],
                "confidence": 0.9,
                "assumptions": [],
                "needs_clarification": False,
                "clarification": None,
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    planner = OpenAICompatiblePlanner(
        registry=registry,
        base_url="https://llm.example/v1",
        credential="test-key",
        model="demo-model",
        client=client,
    )
    plan = planner.plan(PlanningRequest(instruction="查询我的账单"))

    assert plan.intent == "query_bill"
    assert plan.steps[0].tool_name == "query_bill"
    assert plan.planner == "llm:demo-model"


class FailingPlanner:
    name = "failing"

    def plan(self, request: PlanningRequest) -> ExecutionPlan:
        raise PlannerError("provider unavailable")


def test_auto_planner_falls_back_to_rules():
    registry = build_registry()
    fallback = FallbackPlanner(FailingPlanner(), RuleBasedPlanner(registry))

    plan = fallback.plan(PlanningRequest(instruction="查询我的账单"))

    assert plan.intent == "query_bill"
    assert plan.planner == "auto:rule-fallback"
    assert any("回退" in item for item in plan.assumptions)


def test_planner_preview_api_exposes_plan_without_executing(tmp_path):
    app = create_app(database_path=tmp_path / "planner-preview.db")
    with TestClient(app) as client:
        response = client.post(
            "/api/planner/plan",
            json={"instruction": "向 ACC-2002 转账 880 元"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "planned"
        assert body["plan"]["intent"] == "transfer"
        assert body["plan"]["planner"] == "rule"
        assert len(body["plan"]["plan_hash"]) == 64
        assert body["plan"]["steps"][0]["tool_name"] == "transfer"

        audit = client.get("/api/audit").json()
        assert audit["count"] == 0


def test_planner_preview_returns_clarification_for_vague_intent(tmp_path):
    app = create_app(database_path=tmp_path / "planner-clarify.db")
    with TestClient(app) as client:
        response = client.post(
            "/api/planner/plan",
            json={"instruction": "帮我处理一下"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "needs_clarification"
        assert body["plan"]["needs_clarification"] is True
        assert body["reason"]
