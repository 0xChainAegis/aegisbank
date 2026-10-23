"""时间维度场景（定时转账 / 预算锁定 / 生日跨场景 DAG / 时间快进）测试。

只依赖 ``AEGIS_SCENARIO_ALLOW=automation,transfers``（生日联动需要 contacts 表）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "aegisbank-automation.db"))


def run_agent(client: TestClient, instruction: str, **extra) -> dict:
    response = client.post("/api/agent/run", json={"instruction": instruction, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client: TestClient, action_id: str, **extra):
    payload = {"approved": True, **extra}
    return client.post(f"/api/confirmations/{action_id}", json=payload)


def account(client: TestClient, account_id: str = "ACC-1001") -> dict:
    accounts = client.get("/api/banking/overview").json()["accounts"]
    return next(item for item in accounts if item["account_id"] == account_id)


def list_tasks(client: TestClient, status: str | None = None) -> dict:
    params = {"status": status} if status else None
    response = client.get("/api/automation/schedules", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def find_task(client: TestClient, task_id: str) -> dict:
    return next(item for item in list_tasks(client)["tasks"] if item["task_id"] == task_id)


def run_due(client: TestClient, now: str | datetime) -> dict:
    moment = now if isinstance(now, str) else now.isoformat()
    response = client.post("/api/automation/run-due", params={"now": moment})
    assert response.status_code == 200, response.text
    return response.json()


def create_scheduled_transfer(
    client: TestClient, instruction: str = "明天给张三转 500"
) -> tuple[dict, dict, datetime]:
    body = run_agent(client, instruction)
    assert body["status"] == "awaiting_confirmation", body
    step = body["plan"]["steps"][0]
    assert step["tool_name"] == "schedule_transfer", step
    confirmed = confirm(client, body["confirmation"]["id"])
    assert confirmed.status_code == 200, confirmed.text
    executed = confirmed.json()
    assert executed["status"] == "completed", executed
    data = executed["results"][0]["data"]
    return body, data, datetime.fromisoformat(step["arguments"]["run_at"])


def confirm_birthday(client: TestClient, instruction: str) -> tuple[dict, dict, list[dict]]:
    body = run_agent(client, instruction)
    assert body["status"] == "awaiting_confirmation", body
    confirmed = confirm(client, body["confirmation"]["id"])
    assert confirmed.status_code == 200, confirmed.text
    executed = confirmed.json()
    assert executed["status"] == "completed", executed
    orders = client.get("/api/automation/orders").json()["orders"]
    return body, executed, orders


# ---------------------------------------------------------------------------
# 1) 定时转账创建：黄色确认 → scheduled_tasks pending
# ---------------------------------------------------------------------------


def test_schedule_transfer_needs_yellow_confirmation_then_creates_pending_task(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "明天给张三转 500")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "yellow"
        assert body["confirmation"]["requires_reauth"] is False
        assert body["plan"]["intent"] == "scheduled_transfer"
        step = body["plan"]["steps"][0]
        assert step["tool_name"] == "schedule_transfer"
        assert step["arguments"]["to_name"] == "张三"
        assert step["arguments"]["to_account"] == "ACC-9003"
        assert step["arguments"]["amount_cny"] == 500.0
        assert step["arguments"]["recurrence"] == "none"
        run_at = datetime.fromisoformat(step["arguments"]["run_at"])
        assert run_at > datetime.now(UTC)
        assert (run_at.date() - datetime.now(UTC).date()).days >= 1

        confirmed = confirm(client, body["confirmation"]["id"])
        assert confirmed.status_code == 200, confirmed.text
        executed = confirmed.json()
        assert executed["status"] == "completed"
        data = executed["results"][0]["data"]
        assert data["kind"] == "transfer"
        assert data["status"] == "pending"
        stored = find_task(client, data["task_id"])
        assert stored["status"] == "pending"
        assert stored["kind"] == "transfer"
        assert stored["amount_cny"] == 500.0
        assert stored["run_at"] == step["arguments"]["run_at"]


# ---------------------------------------------------------------------------
# 2) 时间快进执行到期任务：余额变化 + trigger_source 审计
# ---------------------------------------------------------------------------


def test_run_due_executes_scheduled_transfer_and_audits_trigger_source(tmp_path):
    with make_client(tmp_path) as client:
        balance_before = account(client)["balance_cny"]
        _, data, run_at = create_scheduled_transfer(client, "明天给张三转 500")
        task_id = data["task_id"]

        result = run_due(client, run_at + timedelta(hours=1))
        assert result["status"] == "completed"
        assert result["executed_count"] == 1
        assert result["failed_count"] == 0
        executed = result["executed"][0]
        assert executed["task_id"] == task_id
        assert executed["trigger_source"] == "scheduled"

        assert account(client)["balance_cny"] == balance_before - 500.0
        assert find_task(client, task_id)["status"] == "done"

        entries = client.get("/api/audit").json()["entries"]
        matches = [
            entry
            for entry in entries
            if entry["event"] == "scheduled_task_executed"
            and (entry["result"] or {}).get("task_id") == task_id
        ]
        assert matches
        assert matches[0]["result"]["trigger_source"] == "scheduled"
        assert matches[0]["result"]["amount_cny"] == 500.0
        assert client.get("/api/audit/verify").json()["valid"] is True


# ---------------------------------------------------------------------------
# 3) 重复时间快进不重复扣款
# ---------------------------------------------------------------------------


def test_repeated_run_due_does_not_double_charge(tmp_path):
    with make_client(tmp_path) as client:
        balance_before = account(client)["balance_cny"]
        _, data, run_at = create_scheduled_transfer(client)
        task_id = data["task_id"]

        first = run_due(client, run_at + timedelta(hours=1))
        assert first["executed_count"] == 1
        balance_after = account(client)["balance_cny"]
        assert balance_after == balance_before - 500.0

        second = run_due(client, run_at + timedelta(days=3))
        assert second["executed_count"] == 0
        assert second["failed_count"] == 0
        assert account(client)["balance_cny"] == balance_after
        assert find_task(client, task_id)["status"] == "done"


# ---------------------------------------------------------------------------
# 4) 生日 DAG：4 步计划 → 预算锁定 + 2 个 scheduled 礼物（生日前 2 天）
# ---------------------------------------------------------------------------


def test_birthday_flow_is_four_step_dag_and_locks_budget(tmp_path):
    with make_client(tmp_path) as client:
        available_before = account(client)["available_cny"]
        balance_before = account(client)["balance_cny"]

        body = run_agent(client, "帮我准备下个月妈妈的生日，预算 1000 元")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "yellow"
        assert body["plan"]["intent"] == "birthday_plan"
        steps = body["plan"]["steps"]
        assert [step["tool_name"] for step in steps] == [
            "query_contact_birthday",
            "lock_budget_funds",
            "schedule_flower_order",
            "schedule_cake_order",
        ]
        assert steps[0]["arguments"]["to_name"] == "妈妈"
        assert steps[1]["arguments"]["amount_cny"] == 1000.0
        assert steps[2]["arguments"]["goal_id"] == "${steps.step-2.data.goal_id}"
        assert steps[2]["arguments"]["birthday"] == "${steps.step-1.data.next_birthday}"
        assert steps[2]["depends_on"] == ["step-1", "step-2"]
        assert steps[3]["depends_on"] == ["step-1", "step-2"]

        confirmed = confirm(client, body["confirmation"]["id"])
        assert confirmed.status_code == 200, confirmed.text
        executed = confirmed.json()
        assert executed["status"] == "completed"
        results = executed["results"]
        identity = results[0]["data"]
        goal = results[1]["data"]
        assert identity["birthday"] == "1990-11-18"
        assert identity["next_birthday"].endswith("-11-18")
        assert identity["days_until"] >= 0
        assert goal["status"] == "active"
        assert goal["locked_cny"] == 1000.0

        goals = client.get("/api/automation/goals").json()["goals"]
        assert len(goals) == 1
        assert goals[0]["goal_id"] == goal["goal_id"]
        assert goals[0]["target_cny"] == 1000.0
        assert goals[0]["locked_cny"] == 1000.0
        assert goals[0]["status"] == "active"

        orders = client.get("/api/automation/orders").json()["orders"]
        assert len(orders) == 2
        assert {order["gift_kind"] for order in orders} == {"flowers", "cake"}
        assert {order["amount_cny"] for order in orders} == {199.0, 159.0}
        assert all(order["status"] == "scheduled" for order in orders)
        expected_due = (
            date.fromisoformat(identity["next_birthday"]) - timedelta(days=2)
        ).isoformat()
        assert {order["due_at"] for order in orders} == {expected_due}

        # 锁定只减少可用余额，实际余额在礼物真正下单前不变。
        assert account(client)["available_cny"] == available_before - 1000.0
        assert account(client)["balance_cny"] == balance_before

        # 预算缺失/联系人无法解析都要澄清；带“预算 800”同样生成 4 步 DAG。
        no_budget = run_agent(client, "帮我准备妈妈的生日")
        assert no_budget["status"] == "needs_clarification"
        assert "预算" in no_budget["reason"]
        unknown = run_agent(client, "准备小明的生日，预算 500")
        assert unknown["status"] == "needs_clarification"
        assert "联系人簿" in unknown["reason"]
        variant = run_agent(client, "准备妈妈的生日，预算 800")
        assert variant["status"] == "awaiting_confirmation"
        assert len(variant["plan"]["steps"]) == 4
        assert variant["plan"]["steps"][1]["arguments"]["amount_cny"] == 800.0


# ---------------------------------------------------------------------------
# 5) 时间快进 → gift_orders ordered
# ---------------------------------------------------------------------------


def test_time_fast_forward_marks_gift_orders_ordered(tmp_path):
    with make_client(tmp_path) as client:
        available_before = account(client)["available_cny"]
        balance_before = account(client)["balance_cny"]
        _, executed, orders = confirm_birthday(
            client, "帮我准备下个月妈妈的生日，预算 1000 元"
        )
        goal = executed["results"][1]["data"]
        due_at = orders[0]["due_at"]

        result = run_due(client, (date.fromisoformat(due_at) + timedelta(days=1)).isoformat())
        assert result["executed_count"] == 2
        assert result["failed_count"] == 0
        assert {item["kind"] for item in result["executed"]} == {"gift"}

        inventory = client.get("/api/automation/orders").json()["orders"]
        assert len(inventory) == 2
        assert all(order["status"] == "ordered" for order in inventory)
        assert {
            item["order_id"] for item in inventory
        } == {order["order_id"] for order in orders}

        goals = client.get("/api/automation/goals").json()["goals"]
        stored_goal = next(item for item in goals if item["goal_id"] == goal["goal_id"])
        assert stored_goal["locked_cny"] == 1000.0 - 199.0 - 159.0
        assert stored_goal["status"] == "active"

        # 已订购的礼物从锁定预算中实际扣款。
        assert account(client)["balance_cny"] == balance_before - 199.0 - 159.0
        assert account(client)["available_cny"] == available_before - 1000.0

        gift_tasks = [
            task for task in list_tasks(client)["tasks"] if task["kind"] == "gift"
        ]
        assert len(gift_tasks) == 2
        assert all(task["status"] == "done" for task in gift_tasks)

        entries = client.get("/api/audit").json()["entries"]
        gift_audits = [
            entry
            for entry in entries
            if entry["event"] == "scheduled_task_executed"
            and (entry["result"] or {}).get("kind") == "gift"
        ]
        assert len(gift_audits) == 2
        assert all(
            entry["result"]["trigger_source"] == "scheduled" for entry in gift_audits
        )


# ---------------------------------------------------------------------------
# 6) 单笔 6000 定时转账 → 红色 + OTP 246810
# ---------------------------------------------------------------------------


def test_scheduled_transfer_over_5000_is_red_and_requires_otp(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "明天给张三转 6000")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "red"
        assert body["confirmation"]["requires_reauth"] is True
        assert any("5000" in reason for reason in body["risk"]["reasons"])
        step = body["plan"]["steps"][0]
        assert step["tool_name"] == "schedule_transfer"
        assert step["arguments"]["amount_cny"] == 6000.0

        wrong = confirm(client, body["confirmation"]["id"], reauth_token="000000")
        assert wrong.status_code == 403
        good = confirm(client, body["confirmation"]["id"], reauth_token="246810")
        assert good.status_code == 200, good.text
        executed = good.json()
        assert executed["status"] == "completed"
        task = find_task(client, executed["results"][0]["data"]["task_id"])
        assert task["status"] == "pending"
        assert task["amount_cny"] == 6000.0


# ---------------------------------------------------------------------------
# 7) 取消定时任务：不再执行
# ---------------------------------------------------------------------------


def test_cancel_scheduled_task_is_yellow_and_stops_execution(tmp_path):
    with make_client(tmp_path) as client:
        balance_before = account(client)["balance_cny"]
        _, data, run_at = create_scheduled_transfer(client)
        task_id = data["task_id"]

        body = run_agent(client, f"取消定时任务 {task_id}")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "yellow"
        step = body["plan"]["steps"][0]
        assert step["tool_name"] == "cancel_scheduled_task"
        assert step["arguments"]["task_id"] == task_id

        confirmed = confirm(client, body["confirmation"]["id"])
        assert confirmed.status_code == 200, confirmed.text
        executed = confirmed.json()
        assert executed["status"] == "completed"
        assert executed["results"][0]["data"]["status"] == "cancelled"
        assert find_task(client, task_id)["status"] == "cancelled"

        result = run_due(client, run_at + timedelta(hours=1))
        assert result["executed_count"] == 0
        assert account(client)["balance_cny"] == balance_before

        missing_id = run_agent(client, "取消定时任务")
        assert missing_id["status"] == "needs_clarification"
        assert "TASK-" in missing_id["reason"]


# ---------------------------------------------------------------------------
# 8) 权限撤销后 run-due 该任务失败并有审计
# ---------------------------------------------------------------------------


def test_revoked_permission_makes_due_task_fail_with_audit(tmp_path):
    with make_client(tmp_path) as client:
        balance_before = account(client)["balance_cny"]
        _, data, run_at = create_scheduled_transfer(client)
        task_id = data["task_id"]

        revoked = client.put("/api/permissions/schedule_transfer", json={"granted": False})
        assert revoked.status_code == 200

        result = run_due(client, run_at + timedelta(hours=1))
        assert result["status"] == "completed"
        assert result["executed_count"] == 0
        assert result["failed_count"] == 1
        assert result["failed"][0]["task_id"] == task_id
        assert "未授权" in result["failed"][0]["reason"]

        assert find_task(client, task_id)["status"] == "failed"
        assert account(client)["balance_cny"] == balance_before

        entries = client.get("/api/audit").json()["entries"]
        failed_audits = [
            entry
            for entry in entries
            if entry["event"] == "scheduled_task_failed"
            and (entry["result"] or {}).get("task_id") == task_id
        ]
        assert failed_audits
        assert failed_audits[0]["result"]["trigger_source"] == "scheduled"
        assert not [
            entry
            for entry in entries
            if entry["event"] == "scheduled_task_executed"
            and (entry["result"] or {}).get("task_id") == task_id
        ]
        assert client.get("/api/audit/verify").json()["valid"] is True


# ---------------------------------------------------------------------------
# 9) 补偿工具 unlock_budget_funds：退回余额并取消未执行的礼物
# ---------------------------------------------------------------------------


def test_unlock_budget_funds_compensates_and_cancels_pending_gifts(tmp_path):
    with make_client(tmp_path) as client:
        available_before = account(client)["available_cny"]
        balance_before = account(client)["balance_cny"]
        _, executed, orders = confirm_birthday(
            client, "帮我准备下个月妈妈的生日，预算 1000 元"
        )
        goal_id = executed["results"][1]["data"]["goal_id"]
        assert account(client)["available_cny"] == available_before - 1000.0

        unlock = run_agent(
            client,
            "解锁生日预算",
            tool_name="unlock_budget_funds",
            arguments={"goal_id": goal_id},
        )
        assert unlock["status"] == "awaiting_confirmation"
        assert unlock["risk_level"] == "yellow"
        confirmed = confirm(client, unlock["confirmation"]["id"])
        assert confirmed.status_code == 200, confirmed.text
        data = confirmed.json()["results"][0]["data"]
        assert data["status"] == "cancelled"
        assert data["released_cny"] == 1000.0
        assert len(data["cancelled_task_ids"]) == 2
        assert account(client)["available_cny"] == available_before

        goals = client.get("/api/automation/goals").json()["goals"]
        assert goals[0]["status"] == "cancelled"
        assert goals[0]["locked_cny"] == 0.0
        assert all(
            order["status"] == "cancelled"
            for order in client.get("/api/automation/orders").json()["orders"]
        )
        due_at = orders[0]["due_at"]
        result = run_due(client, (date.fromisoformat(due_at) + timedelta(days=1)).isoformat())
        assert result["executed_count"] == 0
        assert account(client)["balance_cny"] == balance_before


# ---------------------------------------------------------------------------
# 10) 路由 + 查询意图 + 时间解析澄清 + 不抢占普通转账
# ---------------------------------------------------------------------------


def test_automation_routes_queries_and_guards(tmp_path):
    with make_client(tmp_path) as client:
        schedules = client.get("/api/automation/schedules")
        assert schedules.status_code == 200
        assert schedules.json()["count"] == 0
        assert schedules.json()["simulated"] is True
        goals = client.get("/api/automation/goals")
        assert goals.status_code == 200
        assert goals.json()["count"] == 0
        assert goals.json()["simulated"] is True
        orders = client.get("/api/automation/orders")
        assert orders.status_code == 200
        assert orders.json()["count"] == 0
        assert orders.json()["simulated"] is True
        fast_forward = client.post(
            "/api/automation/run-due", params={"now": datetime.now(UTC).isoformat()}
        )
        assert fast_forward.status_code == 200, fast_forward.text
        assert fast_forward.json()["status"] == "completed"
        assert fast_forward.json()["executed_count"] == 0

        create_scheduled_transfer(client)
        query = run_agent(client, "查看我的定时任务")
        assert query["status"] == "completed"
        assert query["risk_level"] == "green"
        assert query["plan"]["steps"][0]["tool_name"] == "list_scheduled_tasks"
        tasks = query["results"][0]["data"]["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["status"] == "pending"
        pending = list_tasks(client, "pending")
        assert pending["count"] == 1

        # 时间解析失败 → 澄清（不要猜执行时间）。
        bad_time = run_agent(client, "之后给张三转 500")
        assert bad_time["status"] == "needs_clarification"
        assert "执行时间" in bad_time["reason"]

        # 定时/生日指令不会被 transfers 的普通转账意图抢走。
        plain = run_agent(client, "给妈妈转 500")
        assert plain["plan"]["steps"][0]["tool_name"] == "transfer_to_contact"
        scheduled = run_agent(client, "下周三给张三转 500")
        assert scheduled["plan"]["steps"][0]["tool_name"] == "schedule_transfer"
        monthly = run_agent(client, "每月 5 号给张三转 500")
        assert monthly["plan"]["steps"][0]["tool_name"] == "schedule_transfer"
        assert monthly["plan"]["steps"][0]["arguments"]["recurrence"] == "monthly"


def test_run_due_write_endpoint_is_fail_closed_when_not_ready(tmp_path):
    """时间快进是写操作：readiness 未就绪时必须 503，而不是假装执行成功。"""
    app = create_app(
        database_path=tmp_path / "aegisbank-automation-readiness.db",
        readiness_overrides={"sqlite": "故障注入：SQLite 不可用"},
    )
    with TestClient(app) as client:
        ready = client.get("/api/health/ready")
        assert ready.status_code == 200, ready.text
        assert ready.json()["status"] == "not_ready"

        response = client.post(
            "/api/automation/run-due",
            params={"now": datetime.now(UTC).isoformat()},
        )
        assert response.status_code == 503, response.text
        assert "未就绪" in response.text
