#!/usr/bin/env python3
"""End-to-end regression across the six competition scenarios."""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from aegisbank_api.demo_seed import seed_virtual_card  # noqa: E402
from aegisbank_api.main import create_app  # noqa: E402

DEMO_OTP = "246810"
RESULTS: list[tuple[str, str, bool, str]] = []


def check(scenario: str, case: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((scenario, case, ok, detail))
    print(f"{'PASS' if ok else 'FAIL':4} | {scenario:6} | {case:28} | {detail}")


class Agent:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def run(self, instruction: str, **extra) -> dict:
        response = self.client.post(
            "/api/agent/run", json={"instruction": instruction, **extra}
        )
        assert response.status_code == 200, (instruction, response.status_code, response.text)
        return response.json()

    def confirm(self, body: dict) -> dict:
        confirmation = body.get("confirmation") or {}
        payload: dict = {"approved": True}
        if confirmation.get("requires_reauth"):
            payload["reauth_token"] = DEMO_OTP
        response = self.client.post(
            f"/api/confirmations/{confirmation['id']}", json=payload
        )
        assert response.status_code == 200, (body.get("plan", {}).get("intent"), response.text)
        return response.json()

    def run_and_complete(self, instruction: str, **extra) -> tuple[dict, dict]:
        body = self.run(instruction, **extra)
        if body.get("status") == "awaiting_confirmation":
            final = self.confirm(body)
        else:
            final = body
        return body, final

    def plan_steps(self, body: dict) -> list[str]:
        return [step["tool_name"] for step in (body.get("plan") or {}).get("steps", [])]


def scenario_bills(agent: Agent) -> None:
    _, final = agent.run_and_complete("查询我的本月账单")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "账单分析",
        "自然语言查本月账单",
        final.get("status") == "completed" and data.get("total_spend_cny", 0) > 0,
        f"total={data.get('total_spend_cny')}",
    )

    body, final = agent.run_and_complete("生成我的账单报告")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "账单分析",
        "月度账单报告",
        "bill_report" in agent.plan_steps(body) and final.get("status") == "completed",
        f"top={len(data.get('top_merchants') or [])} 商户",
    )

    body, final = agent.run_and_complete("有没有异常扣费")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "账单分析",
        "异常扣费检测",
        "detect_bill_anomalies" in agent.plan_steps(body)
        and final.get("status") == "completed",
        f"异常 {data.get('total', 'n/a')} 条",
    )


def scenario_cards(agent: Agent) -> None:
    body, final = agent.run_and_complete("挂失 CARD-9902")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "卡片管理",
        "挂失卡片（红+MFA）",
        body.get("risk_level") == "red"
        and final.get("status") == "completed"
        and data.get("status") == "lost",
    )

    body, final = agent.run_and_complete("解挂 CARD-9902")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "卡片管理",
        "解挂卡片（红+MFA）",
        final.get("status") == "completed" and data.get("status") == "active",
    )

    body, final = agent.run_and_complete("申请虚拟卡")
    steps = agent.plan_steps(body)
    data = (final.get("results") or [{}])[-1].get("data", {})
    issued_card = data.get("card_id")
    cards = {
        card["card_id"]
        for card in agent.client.get("/api/banking/overview").json()["cards"]
    }
    check(
        "卡片管理",
        "虚拟卡申请→审核发卡",
        steps == ["apply_virtual_card", "issue_virtual_card"]
        and final.get("status") == "completed"
        and issued_card in cards,
        f"新卡 {issued_card}",
    )

    body, final = agent.run_and_complete("重置 CARD-8821 密码")
    check(
        "卡片管理",
        "重置卡片密码（红+MFA）",
        body.get("risk_level") == "red" and final.get("status") == "completed",
    )


def scenario_transfers(agent: Agent) -> None:
    body, final = agent.run_and_complete("从 ACC-3003 向 ACC-2002 转账 500 元")
    check(
        "智能转账",
        "虚拟卡转出 500（黄）",
        body.get("risk_level") == "yellow" and final.get("status") == "completed",
    )

    body, final = agent.run_and_complete("从 ACC-3003 向 ACC-2002 转账 600 元")
    check(
        "智能转账",
        "同日再转 600（累计>1000→红）",
        body.get("risk_level") == "red" and final.get("status") == "completed",
        "需 OTP",
    )

    overview = agent.client.get("/api/banking/overview").json()
    virtual = next(item for item in overview["accounts"] if item["account_id"] == "ACC-3003")
    check(
        "智能转账",
        "虚拟卡余额正确",
        virtual["balance_cny"] == 1900.0,
        f"余额 {virtual['balance_cny']}",
    )

    body, final = agent.run_and_complete("给妈妈转 500")
    check(
        "智能转账",
        "联系人转账（妈妈）",
        final.get("status") == "completed",
        f"风险 {body.get('risk_level')}",
    )

    body, final = agent.run_and_complete("和妈妈、张三 AA 300")
    results = final.get("results") or []
    check(
        "智能转账",
        "AA 拆分并行 DAG",
        final.get("status") == "completed" and len(results) >= 2,
        f"{len(results)} 笔",
    )


def scenario_subscriptions(agent: Agent) -> None:
    body, final = agent.run_and_complete("我的订阅还有哪些要续费")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "订阅代扣",
        "续费提醒",
        "list_renewal_reminders" in agent.plan_steps(body)
        and final.get("status") == "completed",
        f"{len(data.get('reminders') or [])} 条提醒",
    )

    body, final = agent.run_and_complete("订阅扣费分析")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "订阅代扣",
        "扣费识别 + 未登记代扣",
        "identify_subscription_charges" in agent.plan_steps(body)
        and final.get("status") == "completed",
        f"{data.get('total', 'n/a')} 个实体",
    )

    body, final = agent.run_and_complete("取消健身房月卡")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "订阅代扣",
        "按商户名取消订阅",
        final.get("status") == "completed"
        and data.get("status") == "cancelled"
        and data.get("subscription_id") == "SUB-3003",
        data.get("subscription_id", ""),
    )


def scenario_cross(agent: Agent) -> None:
    body, final = agent.run_and_complete("分析我的账单并取消异常订阅")
    steps = agent.plan_steps(body)
    results = final.get("results") or []
    check(
        "跨场景联动",
        "账单→取消异常订阅 DAG",
        steps == ["query_bill", "cancel_subscription"]
        and final.get("status") == "completed"
        and len(results) == 2,
        f"{len(results)} 步",
    )

    body, final = agent.run_and_complete("帮我准备下个月妈妈的生日，预算 1000 元")
    steps = agent.plan_steps(body)
    check(
        "跨场景联动",
        "生日 4 步 DAG（锁预算+礼物）",
        len(steps) == 4 and final.get("status") == "completed",
        "→".join(steps),
    )

    goals = agent.client.get("/api/automation/goals").json()
    orders = agent.client.get("/api/automation/orders").json()
    check(
        "跨场景联动",
        "预算锁定与礼物订单",
        goals.get("count", 0) >= 1 and orders.get("count", 0) >= 2,
        f"goals={goals.get('count')} orders={orders.get('count')}",
    )

    body, final = agent.run_and_complete("下周三给张三转 500")
    check(
        "定时/触发",
        "自然语言创建定时转账",
        "schedule_transfer" in agent.plan_steps(body)
        and final.get("status") == "completed",
    )

    fast_forward = datetime.now(UTC) + timedelta(days=30)
    response = agent.client.post(
        "/api/automation/run-due", params={"now": fast_forward.isoformat()}
    )
    payload = response.json()
    check(
        "定时/触发",
        "时间快进执行到期任务",
        response.status_code == 200 and payload.get("executed_count", 0) >= 1,
        f"executed={payload.get('executed_count')} failed={payload.get('failed_count')}",
    )

    body = agent.run("取消异常订阅")
    check(
        "订阅代扣",
        "无可取消异常订阅时澄清",
        body.get("status") == "needs_clarification",
        str(body.get("reason"))[:40],
    )


def scenario_wealth(agent: Agent) -> None:
    body, final = agent.run_and_complete("有什么理财产品")
    data = (final.get("results") or [{}])[0].get("data", {})
    check(
        "理财操作",
        "产品清单（R1–R5）",
        "list_wealth_products" in agent.plan_steps(body)
        and final.get("status") == "completed",
        f"{data.get('count', len(data.get('products') or []))} 只产品",
    )

    body, final = agent.run_and_complete("买 1000 元稳健短债A")
    check(
        "理财操作",
        "按产品名申购（红+MFA）",
        body.get("risk_level") == "red" and final.get("status") == "completed",
        f"intent={body.get('plan', {}).get('intent')}",
    )

    body, final = agent.run_and_complete("我的理财持仓")
    check(
        "理财操作",
        "持仓查询",
        "query_wealth_holdings" in agent.plan_steps(body)
        and final.get("status") == "completed",
    )

    body, final = agent.run_and_complete("赎回 500 元")
    check(
        "理财操作",
        "理财赎回（黄）",
        body.get("risk_level") == "yellow" and final.get("status") == "completed",
    )


def global_checks(agent: Agent) -> None:
    ready = agent.client.get("/api/health/ready").json()
    check("全局", "readiness 四组件就绪", ready.get("status") == "ready", str(ready.get("status")))

    verify = agent.client.get("/api/audit/verify").json()
    check("全局", "审计哈希链完整", verify.get("valid") is True, f"checked={verify.get('checked')}")

    overview = agent.client.get("/api/banking/overview").json()
    cards = {card["card_id"] for card in overview["cards"]}
    subscriptions = {
        sub["subscription_id"]: sub["status"] for sub in overview["subscriptions"]
    }
    check(
        "全局",
        "虚拟卡仍在银行概览",
        "CARD-9001" in cards
        and any(acc["account_id"] == "ACC-3003" for acc in overview["accounts"]),
    )
    check(
        "全局",
        "订阅状态已更新",
        subscriptions.get("SUB-3002") == "cancelled"
        and subscriptions.get("SUB-3003") == "cancelled",
        str(subscriptions),
    )


def main() -> int:
    database = Path(tempfile.mkdtemp()) / "scenario-regression.db"
    app = create_app(database_path=database)
    seed_virtual_card(database)
    with TestClient(app) as client:
        agent = Agent(client)
        for scenario in (
            scenario_bills,
            scenario_cards,
            scenario_transfers,
            scenario_subscriptions,
            scenario_cross,
            scenario_wealth,
            global_checks,
        ):
            scenario(agent)

    failed = [item for item in RESULTS if not item[2]]
    print()
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)}，失败 {len(failed)}")
    if failed:
        for scenario, case, _, detail in failed:
            print(f"  FAILED: {scenario} / {case} / {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
