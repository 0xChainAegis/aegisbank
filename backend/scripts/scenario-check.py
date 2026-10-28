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


def fast_forward_result(
    status_code: int, payload: dict, *, target_task_id: str | None = None
) -> tuple[bool, str]:
    """A successful batch must execute its target, not leave it awaiting reauth."""
    if not isinstance(payload, dict):
        return False, "响应格式错误：run-due 响应不是 JSON 对象；处理建议：检查响应构造。"

    invalid: list[str] = []

    def strict_count(name: str) -> int | None:
        value = payload.get(name)
        if type(value) is not int:
            shown = "missing" if value is None else repr(value)
            invalid.append(f"{name}={shown}")
            return None
        return value

    executed = strict_count("executed_count")
    failed = strict_count("failed_count")
    raw_pending = payload.get("pending_reauth_count")
    pending_reauth = (
        raw_pending if type(raw_pending) is int and raw_pending >= 0 else 0
    )
    if raw_pending is not None and (type(raw_pending) is not int or raw_pending < 0):
        invalid.append(f"pending_reauth_count={raw_pending!r}")
    target_executed = target_task_id is None or any(
        isinstance(item, dict)
        and item.get("task_id") == target_task_id
        and item.get("kind") == "transfer"
        and item.get("status") == "executed"
        for item in payload.get("executed") or []
    )
    ok = (
        status_code == 200
        and not invalid
        and executed is not None
        and executed >= 1
        and failed == 0
        and pending_reauth == 0
        and target_executed
    )

    parts = [
        f"HTTP={status_code}",
        f"executed={executed if executed is not None else 'missing'}",
        f"failed={failed if failed is not None else 'missing'}",
    ]
    if pending_reauth:
        parts.append(f"pending_reauth={pending_reauth}")
        parts.append("处理建议：补验证代表安全暂停，不能当作目标转账已执行。")
    if not target_executed:
        parts.append(f"目标任务 {target_task_id} 未在 executed 中完成。")
    if invalid:
        parts.append("响应格式错误：" + "；".join(invalid))
        parts.append(
            "处理建议：run-due 必须返回整型 executed_count/failed_count，"
            "并保证 executed_count>=1 且 failed_count==0。"
        )
    elif failed:
        failure_notes = []
        for item in payload.get("failed") or []:
            task_id = item.get("task_id", "?")
            reason = item.get("reason") or item.get("execution_status") or "unknown"
            failure_notes.append(f"{task_id}: {reason}")
        parts.append("失败详情：" + "；".join(failure_notes[:3]))
        parts.append(
            "处理建议：核对权限/余额与任务授权后修复失败原因；"
            "若为风险升级，按 pending_reauth.action_required 重新强验证。"
        )
    elif status_code != 200:
        parts.append("处理建议：检查 run-due HTTP 状态与 readiness/权限错误。")
    elif executed < 1:
        parts.append("处理建议：确认任务已到期、未被取消，且 run_at <= now。")
    return ok, " ".join(parts)


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
        final = self.confirm(body) if body.get("status") == "awaiting_confirmation" else body
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
    scheduled = next(
        (
            item.get("data") or {}
            for item in final.get("results") or []
            if item.get("tool_name") == "schedule_transfer"
        ),
        {},
    )
    target_task_id = scheduled.get("task_id")
    check(
        "定时/触发",
        "自然语言创建定时转账",
        "schedule_transfer" in agent.plan_steps(body)
        and final.get("status") == "completed"
        and bool(target_task_id)
        and scheduled.get("status") == "pending"
        and scheduled.get("amount_cny") == 500.0,
        str(target_task_id or "未创建目标任务"),
    )

    accounts_before = {
        item["account_id"]: item
        for item in agent.client.get("/api/banking/overview").json()["accounts"]
    }
    fast_forward = datetime.now(UTC) + timedelta(days=30)
    response = agent.client.post(
        "/api/automation/run-due", params={"now": fast_forward.isoformat()}
    )
    payload = response.json()
    fast_forward_ok, fast_forward_detail = fast_forward_result(
        response.status_code, payload, target_task_id=target_task_id or "missing-target"
    )
    tasks = agent.client.get("/api/automation/schedules").json()["tasks"]
    target = next((item for item in tasks if item["task_id"] == target_task_id), {})
    accounts_after = {
        item["account_id"]: item
        for item in agent.client.get("/api/banking/overview").json()["accounts"]
    }
    source_id = scheduled.get("from_account")
    before, after = accounts_before.get(source_id, {}), accounts_after.get(source_id, {})
    gift_spend = sum(
        item.get("amount_cny", 0)
        for item in payload.get("executed") or []
        if item.get("kind") == "gift"
    )
    # Gift purchases consume previously locked funds from ACC-1001, so they
    # reduce its balance but not its available balance. This target transfers
    # exactly 500 CNY from that account to external contact account ACC-9003.
    correct_balance = (
        source_id == "ACC-1001"
        and scheduled.get("to_account") == "ACC-9003"
        and before
        and after
        and round(before["available_cny"] - after["available_cny"], 2) == 500.0
        and round(before["balance_cny"] - after["balance_cny"], 2)
        == round(500.0 + gift_spend, 2)
    )
    persisted = target.get("last_result") or {}
    target_done = (
        target.get("status") == "done"
        and persisted.get("status") == "executed"
        and persisted.get("task_id") == target_task_id
        and persisted.get("amount_cny") == 500.0
        and persisted.get("to_account") == scheduled.get("to_account")
        and bool(persisted.get("transaction_id"))
    )
    check(
        "定时/触发",
        "时间快进执行到期任务",
        fast_forward_ok and target_done and bool(correct_balance),
        f"{fast_forward_detail} target_done={target_done} balance_ok={bool(correct_balance)}",
    )

    body = agent.run("取消异常订阅")
    check(
        "订阅代扣",
        "无可取消异常订阅时澄清",
        body.get("status") == "needs_clarification",
        str(body.get("reason"))[:40],
    )


def scenario_schedule_reauth(agent: Agent) -> None:
    """A fresh bank isolates expected safety suspension from successful execution."""
    body, final = agent.run_and_complete("明天给张三转 500")
    scheduled = (final.get("results") or [{}])[0].get("data") or {}
    task_id = scheduled.get("task_id")
    _, immediate = agent.run_and_complete("向 ACC-2002 转账 600 元")
    before = agent.client.get("/api/banking/overview").json()["accounts"]
    run_at = datetime.fromisoformat(scheduled["run_at"]) + timedelta(hours=1)
    response = agent.client.post("/api/automation/run-due", params={"now": run_at.isoformat()})
    payload = response.json()
    target = next(
        (
            item
            for item in agent.client.get("/api/automation/schedules").json()["tasks"]
            if item["task_id"] == task_id
        ),
        {},
    )
    pending = payload.get("pending_reauth") or []
    check(
        "定时/安全",
        "风险升级暂停且不扣款（非执行成功）",
        body.get("risk_level") == "yellow"
        and final.get("status") == "completed"
        and immediate.get("status") == "completed"
        and response.status_code == 200
        and payload.get("executed_count") == 0
        and payload.get("failed_count") == 0
        and payload.get("pending_reauth_count") == 1
        and len(pending) == 1
        and pending[0].get("task_id") == task_id
        and pending[0].get("execution_status") == "needs_reauth"
        and bool(pending[0].get("action_required"))
        and target.get("status") == "pending"
        and (target.get("last_result") or {}).get("execution_status") == "needs_reauth"
        and agent.client.get("/api/banking/overview").json()["accounts"] == before,
        f"target={task_id} pending_reauth={payload.get('pending_reauth_count')}",
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

    reauth_app = create_app(database_path=database.parent / "scheduled-reauth-regression.db")
    with TestClient(reauth_app) as client:
        scenario_schedule_reauth(Agent(client))

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
