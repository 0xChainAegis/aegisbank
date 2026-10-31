"""Regression tests for the verified second-retest NLP and timezone findings."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.main import create_app
from aegisbank_api.planning import semantic as semantic_module
from aegisbank_api.planning.contracts import PlanningRequest
from aegisbank_api.planning.rule import RuleBasedPlanner
from aegisbank_api.planning.semantic import analyze_rules, verify_frame
from aegisbank_api.scenarios import automation as automation_module
from aegisbank_api.scenarios import bills as bills_module

SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "second-retest-nlp.db"))


def run_agent(client: TestClient, instruction: str) -> dict:
    response = client.post("/api/agent/run", json={"instruction": instruction})
    assert response.status_code == 200, response.text
    return response.json()


def plan_steps(body: dict) -> list[dict]:
    return (body.get("plan") or {}).get("steps") or []


def plan_tools(body: dict) -> list[str]:
    return [step["tool_name"] for step in plan_steps(body)]


@pytest.mark.parametrize("instruction", ["这个月外卖花了多少", "外卖花了多少钱"])
def test_food_delivery_spend_questions_are_read_only_bill_reports(tmp_path, instruction):
    with make_client(tmp_path) as client:
        body = run_agent(client, instruction)

        assert body["status"] == "completed", body
        assert body["risk_level"] == "green", body
        assert plan_tools(body) == ["bill_report"], body
        step = plan_steps(body)[0]
        assert step["arguments"]["category"] == "food"
        assert "redeem_wealth" not in str(body["plan"])


def test_spending_questions_use_current_and_last_month_and_food_category(tmp_path):
    today = bills_module._today()
    previous_month_key = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    with make_client(tmp_path) as client:
        current = run_agent(client, "我这个月花了多少钱")
        assert current["status"] == "completed", current
        assert current["risk_level"] == "green"
        assert plan_tools(current) == ["bill_report"]
        current_step = plan_steps(current)[0]
        assert current_step["arguments"]["period"] == "month"
        assert current_step["arguments"]["month"] == today.strftime("%Y-%m")
        assert current_step["arguments"]["category"] is None
        assert current["results"][0]["data"]["period"] == "month"

        previous = run_agent(client, "我上个月在餐饮上花了多少钱")
        assert previous["status"] == "completed", previous
        assert previous["risk_level"] == "green"
        assert plan_tools(previous) == ["bill_report"]
        previous_step = plan_steps(previous)[0]
        assert previous_step["arguments"]["month"] == previous_month_key
        assert previous_step["arguments"]["category"] == "food"
        report = previous["results"][0]["data"]
        assert report["category"] == "food"
        assert isinstance(report["category_spend_cny"], float)
        assert report["total_spend_cny"] == report["category_spend_cny"]


def test_anomaly_question_is_a_read_only_bill_analysis(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "最近有没有乱扣钱的")

        assert body["status"] == "completed", body
        assert body["risk_level"] == "green", body
        assert plan_tools(body) == ["detect_bill_anomalies"], body
        assert body["results"][0]["data"]["simulated"] is True


def test_missing_payee_clarifies_instead_of_resolving_pronoun_me(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "帮我转200元")

        assert body["status"] == "needs_clarification", body
        assert plan_steps(body) == []
        assert "收款人" in (body.get("reason") or "")
        assert "未找到" not in (body.get("reason") or "")


def test_assisted_transfer_resolves_name_and_colloquial_amount(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "帮我给张三转个两百")

        assert body["status"] == "awaiting_confirmation", body
        assert plan_tools(body) == ["transfer_to_contact"]
        step = plan_steps(body)[0]
        assert step["arguments"]["to_name"] == "张三"
        assert step["arguments"]["amount_cny"] == 200.0


def test_salary_card_alias_resolves_to_account_1001(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "我的工资卡还剩多少钱")

        assert body["status"] == "completed", body
        assert body["risk_level"] == "green"
        assert plan_tools(body) == ["query_balance"]
        assert plan_steps(body)[0]["arguments"]["account_id"] == "ACC-1001"


def test_subscription_cancel_resolves_merchant_with_spoken_fillers(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "把健身房那个月卡取消掉")

        assert body["status"] == "awaiting_confirmation", body
        assert plan_tools(body) == ["cancel_subscription"]
        assert plan_steps(body)[0]["arguments"]["subscription_id"] == "SUB-3003"
        assert "请指定要取消的订阅编号" not in (body.get("reason") or "")


def test_repayment_day_without_card_clarifies_card_not_amount(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "把还款日改到 18 号")

        assert body["status"] == "needs_clarification", body
        assert body["plan"]["intent"] == "adjust_repayment_date"
        assert plan_steps(body) == []
        reason = body.get("reason") or ""
        assert "CARD-8821" in reason and "CARD-9902" in reason
        assert "ambiguous_amount" not in reason
        assert "amount" not in reason.lower()
        assert "account" not in reason.lower()


def test_monthly_schedule_transfer_uses_next_tenth_at_shanghai_nine(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "每个月10号给张三转300")

        assert body["status"] == "awaiting_confirmation", body
        assert plan_tools(body) == ["schedule_transfer"]
        step = plan_steps(body)[0]
        assert step["arguments"]["amount_cny"] == 300.0
        assert step["arguments"]["recurrence"] == "monthly"
        run_at = datetime.fromisoformat(step["arguments"]["run_at"])
        shanghai_run_at = run_at.astimezone(SHANGHAI)
        today = bills_module._today()
        if today.day >= 10:
            next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        else:
            next_month = today.replace(day=1)
        expected = datetime(
            next_month.year, next_month.month, 10, 9, tzinfo=SHANGHAI
        ).astimezone(UTC)
        assert run_at == expected
        assert shanghai_run_at.hour == 9
        assert shanghai_run_at.minute == 0


def test_weekly_schedule_remains_unsupported_and_clarifies(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "每周五给妈妈转100")

        assert body["status"] == "needs_clarification", body
        assert plan_steps(body) == []
        assert "暂不支持每天/每周" in (body.get("reason") or "")


def test_tomorrow_transfer_is_shanghai_nine_not_utc_nine(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "明天给张三转500")

        assert body["status"] == "awaiting_confirmation", body
        step = plan_steps(body)[0]
        assert step["tool_name"] == "schedule_transfer"
        run_at = datetime.fromisoformat(step["arguments"]["run_at"])
        shanghai_run_at = run_at.astimezone(SHANGHAI)
        expected_date = datetime.now(SHANGHAI).date() + timedelta(days=1)
        assert shanghai_run_at.date() == expected_date
        assert shanghai_run_at.hour == 9
        assert run_at.astimezone(UTC).hour == 1
        assert run_at.utcoffset() == timedelta(0)


def test_automation_morning_helpers_convert_shanghai_wall_clock():
    target = date(2030, 1, 15)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    expected = datetime(2030, 1, 15, 1, 0, tzinfo=UTC)
    assert automation_module._future_morning(target, now) == expected
    assert automation_module._at_morning_utc(target) == expected


def test_resolve_run_at_today_uses_shanghai_date():
    now = datetime(2026, 10, 29, 16, 30, tzinfo=UTC)
    run_at, recurrence = automation_module._resolve_run_at("明天给张三转300", now)
    shanghai_run_at = run_at.astimezone(SHANGHAI)
    assert recurrence == "none"
    assert shanghai_run_at.date() == date(2026, 10, 31)
    assert shanghai_run_at.hour == 9
    assert run_at.astimezone(UTC).hour == 1


def test_semantic_reference_date_and_birthday_today_use_shanghai(monkeypatch, tmp_path):
    real_datetime = datetime

    class FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            base = real_datetime(2026, 10, 29, 16, 30, tzinfo=UTC)
            return base.astimezone(tz) if tz is not None else base.replace(tzinfo=None)

    # Freeze both stages: the rule planner rechecks that the resolved scheduled
    # time is in the future. A real clock here makes this test expire on Oct 31.
    monkeypatch.setattr(semantic_module, "datetime", FixedDatetime)
    monkeypatch.setattr(automation_module, "datetime", FixedDatetime)
    with make_client(tmp_path) as client:
        services = client.app.state.services
        rule = RuleBasedPlanner(services.registry, services.repository)
        request = PlanningRequest(instruction="明天给张三转500")
        plan = verify_frame(analyze_rules(request.instruction), request, rule)
        assert plan.semantic.reference_date == "2026-10-30"
        run_at = datetime.fromisoformat(plan.steps[0].arguments["run_at"])
        assert run_at.astimezone(SHANGHAI).date() == date(2026, 10, 31)
        assert run_at.astimezone(SHANGHAI).hour == 9

    assert automation_module._today() == date(2026, 10, 30)


def test_semantic_and_schedule_cross_year_use_shanghai(monkeypatch, tmp_path):
    real_datetime = datetime

    class FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            base = real_datetime(2026, 12, 31, 16, 30, tzinfo=UTC)
            return base.astimezone(tz) if tz is not None else base.replace(tzinfo=None)

    monkeypatch.setattr(semantic_module, "datetime", FixedDatetime)
    monkeypatch.setattr(automation_module, "datetime", FixedDatetime)

    with make_client(tmp_path) as client:
        services = client.app.state.services
        rule = RuleBasedPlanner(services.registry, services.repository)
        request = PlanningRequest(instruction="明天给张三转500")
        plan = verify_frame(analyze_rules(request.instruction), request, rule)

        assert plan.semantic.reference_date == "2027-01-01"
        assert automation_module._today() == date(2027, 1, 1)
        step = plan.steps[0]
        assert step.tool_name == "schedule_transfer"
        run_at = datetime.fromisoformat(step.arguments["run_at"])
        shanghai_run_at = run_at.astimezone(SHANGHAI)
        assert shanghai_run_at.date() == date(2027, 1, 2)
        assert shanghai_run_at.hour == 9
        assert run_at.astimezone(UTC).hour == 1
