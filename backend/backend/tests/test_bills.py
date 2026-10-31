"""账单与订阅深度场景的闭环测试：工具执行 / 自然语言意图 / 只读路由。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "aegisbank-bills.db"))


def run_tool(client: TestClient, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/agent/run",
        json={
            "instruction": "执行账单场景只读查询",
            "tool_name": tool_name,
            "arguments": arguments,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed", body
    assert body["risk_level"] == "green", body
    data: dict[str, Any] = body["results"][0]["data"]
    return data


def test_bill_report_month_green_with_merchants_and_comparison(tmp_path):
    with make_client(tmp_path) as client:
        data = run_tool(client, "bill_report", {"account_id": "ACC-1001", "period": "month"})
        assert data["simulated"] is True
        assert data["period"] == "month"
        assert data["label"] == datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
        assert data["total_spend_cny"] > 0
        assert data["transaction_count"] > 0
        assert 1 <= len(data["top_merchants"]) <= 5
        top = data["top_merchants"][0]
        assert top["amount_cny"] > 0
        assert top["count"] >= 1
        comparison = data["comparison"]
        assert comparison["baseline"] == "上月"
        assert comparison["previous_total_cny"] > 0
        assert comparison["change_pct"] is not None
        assert data["conclusion"]
        assert any(item["over_budget"] for item in data["budget_usage"])


def test_bill_report_year_period_uses_annual_window(tmp_path):
    with make_client(tmp_path) as client:
        data = run_tool(client, "bill_report", {"account_id": "ACC-1001", "period": "year"})
        assert data["period"] == "year"
        assert data["month"] is None
        assert data["year"] == datetime.now(ZoneInfo("Asia/Shanghai")).year
        assert data["total_spend_cny"] > 0
        assert data["categories"]
        assert data["comparison"]["baseline"] == "去年"


def test_detect_bill_anomalies_hits_all_seeded_rule_kinds(tmp_path):
    with make_client(tmp_path) as client:
        data = run_tool(client, "detect_bill_anomalies", {"account_id": "ACC-1001"})
        anomalies = data["anomalies"]
        assert anomalies
        kinds = {item["kind"] for item in anomalies}
        expected = {
            "duplicate_charge",
            "over_budget",
            "subscription_price_jump",
            "off_hours",
        }
        assert expected <= kinds
        for item in anomalies:
            assert {"kind", "severity", "message", "evidence"} <= set(item)
            assert item["message"]
        duplicates = [item for item in anomalies if item["kind"] == "duplicate_charge"]
        assert duplicates and duplicates[0]["evidence"]["count"] >= 2
        assert duplicates[0]["evidence"]["transaction_ids"]
        over_budget = [item for item in anomalies if item["kind"] == "over_budget"]
        assert any(item["evidence"]["category"] == "food" for item in over_budget)
        jumps = [item for item in anomalies if item["kind"] == "subscription_price_jump"]
        assert any(item["evidence"]["merchant"] == "星云影音会员" for item in jumps)
        off_hours = [item for item in anomalies if item["kind"] == "off_hours"]
        assert any(item["evidence"]["hour"] == 2 for item in off_hours)
        assert data["counts_by_kind"]["off_hours"] >= 1
        assert data["simulated"] is True


def test_identify_subscription_charges_marks_unregistered_debit(tmp_path):
    with make_client(tmp_path) as client:
        data = run_tool(client, "identify_subscription_charges", {})
        assert data["total"] >= 1
        subscriptions = {item["merchant"]: item for item in data["subscriptions"]}
        assert "星云影音会员" in subscriptions
        unregistered = subscriptions["星云影音会员"]
        assert unregistered["unregistered_debit"] is True
        assert unregistered["registered"] is False
        assert unregistered["subscription_id"] is None
        assert unregistered["charge_count"] >= 1
        assert unregistered["average_amount_cny"] > 0
        assert unregistered["latest_charge_date"]
        assert "未登记" in unregistered["advice"]
        assert data["unregistered_count"] >= 1
        registered = subscriptions["云端影音"]
        assert registered["registered"] is True
        assert registered["subscription_id"] == "SUB-3001"


def test_list_renewal_reminders_days_left_and_cycle_filter(tmp_path):
    with make_client(tmp_path) as client:
        data = run_tool(client, "list_renewal_reminders", {"days_ahead": 30})
        reminders = data["reminders"]
        assert reminders
        assert all(item["days_left"] >= 0 for item in reminders)
        target = next(item for item in reminders if item["subscription_id"] == "SUB-3001")
        assert target["amount_cny"] == 45.0
        assert target["cycle"] == "monthly"
        assert target["next_charge_date"]
        assert target["advice"]
        assert "站内" in data["note"]

        monthly = run_tool(client, "list_renewal_reminders", {"cycle": "monthly", "days_ahead": 30})
        assert monthly["reminders"]
        assert all(item["cycle"] == "monthly" for item in monthly["reminders"])
        yearly = run_tool(client, "list_renewal_reminders", {"cycle": "yearly", "days_ahead": 30})
        assert all(item["cycle"] == "yearly" for item in yearly["reminders"])


def test_natural_language_bill_and_subscription_intents(tmp_path):
    with make_client(tmp_path) as client:
        report = client.post("/api/agent/run", json={"instruction": "生成我的账单报告"}).json()
        assert report["status"] == "completed", report
        assert report["plan"]["steps"][0]["tool_name"] == "bill_report"
        assert report["results"][0]["data"]["period"] == "month"

        annual = client.post("/api/agent/run", json={"instruction": "生成我的年度账单"}).json()
        assert annual["plan"]["steps"][0]["tool_name"] == "bill_report"
        assert annual["plan"]["steps"][0]["arguments"]["period"] == "year"

        anomaly = client.post("/api/agent/run", json={"instruction": "有没有异常扣费"}).json()
        assert anomaly["status"] == "completed", anomaly
        assert anomaly["plan"]["steps"][0]["tool_name"] == "detect_bill_anomalies"
        assert anomaly["results"][0]["data"]["anomalies"]

        charges = client.post("/api/agent/run", json={"instruction": "帮我做订阅扣费分析"}).json()
        assert charges["plan"]["steps"][0]["tool_name"] == "identify_subscription_charges"

        reminders = client.post("/api/agent/run", json={"instruction": "有哪些快到期订阅"}).json()
        assert reminders["plan"]["steps"][0]["tool_name"] == "list_renewal_reminders"

        # 纯"查询本月账单"必须保持原有的 query_bill 语义，不被报告意图抢占
        legacy = client.post("/api/agent/run", json={"instruction": "查询我的本月账单"}).json()
        assert legacy["plan"]["steps"][0]["tool_name"] == "query_bill"


def test_bills_read_only_routes_are_complete(tmp_path):
    with make_client(tmp_path) as client:
        report = client.get(
            "/api/bills/report", params={"account_id": "ACC-1001", "period": "month"}
        )
        assert report.status_code == 200, report.text
        report_data = report.json()
        assert report_data["total_spend_cny"] > 0
        assert report_data["top_merchants"]
        assert report_data["comparison"]
        assert report_data["simulated"] is True

        anomalies = client.get("/api/bills/anomalies")
        assert anomalies.status_code == 200, anomalies.text
        anomaly_data = anomalies.json()
        assert anomaly_data["anomalies"]
        assert {"kind", "severity", "message", "evidence"} <= set(anomaly_data["anomalies"][0])

        charges = client.get("/api/subscriptions/charges")
        assert charges.status_code == 200, charges.text
        assert charges.json()["subscriptions"]

        reminders = client.get("/api/subscriptions/reminders")
        assert reminders.status_code == 200, reminders.text
        assert reminders.json()["reminders"]
        assert reminders.json()["simulated"] is True


def test_seed_is_idempotent_across_app_restarts(tmp_path):
    db_path = tmp_path / "aegisbank-bills-idempotent.db"
    with TestClient(create_app(database_path=db_path)) as client:
        first = run_tool(client, "bill_report", {"account_id": "ACC-1001"})
    with TestClient(create_app(database_path=db_path)) as client:
        second = run_tool(client, "bill_report", {"account_id": "ACC-1001"})
    assert first["total_spend_cny"] == second["total_spend_cny"]
    assert first["transaction_count"] == second["transaction_count"]
    assert first["all_transaction_count"] == second["all_transaction_count"]
