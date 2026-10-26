"""Stage 2A step-level pause / resume / rollback / compensation tests.

The compensation extension is loaded in isolation with::

    AEGIS_EXTENSION_ALLOW=compensation AEGIS_SCENARIO_ALLOW=none

so the assertions focus on core tools plus the extension-owned demo DAG. The
suite also passes in the default (all modules loaded) mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.audit import AuditService
from aegisbank_api.db import Database
from aegisbank_api.main import create_app
from aegisbank_api.trust.state_machine import (
    ActionState,
    IllegalTransition,
    StateMachine,
)

DEMO_OTP = "246810"


def make_client(tmp_path: Path, name: str = "compensation.db") -> TestClient:
    return TestClient(create_app(database_path=tmp_path / name))


def audit_events(client: TestClient, limit: int = 200) -> list[dict[str, Any]]:
    return client.get("/api/audit", params={"limit": limit}).json()["entries"]


def event_names(client: TestClient) -> list[str]:
    return [str(entry["event"]) for entry in audit_events(client)]


def balance(client: TestClient, account_id: str = "ACC-1001") -> float:
    overview = client.get("/api/banking/overview").json()
    return float(
        next(item for item in overview["accounts"] if item["account_id"] == account_id)[
            "balance_cny"
        ]
    )


def start_transfer(client: TestClient, amount: float) -> dict[str, Any]:
    response = client.post(
        "/api/agent/run",
        json={
            "instruction": f"向 ACC-2002 转账 {amount:g} 元",
            "tool_name": "transfer",
            "arguments": {
                "from_account": "ACC-1001",
                "to_account": "ACC-2002",
                "amount_cny": amount,
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def run_demo(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.post("/api/compensation/demo/run", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# 1. 补偿规格覆盖所有有副作用的工具，工具元数据声明可逆性
def test_compensation_specs_cover_mutating_tools(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/compensation/specs")
        assert response.status_code == 200
        body = response.json()
        coverage = body["coverage"]
        assert coverage["fully_covered"] is True
        assert coverage["unregistered_mutating_tools"] == []
        assert coverage["registered"] == body["count"] >= 20
        assert "reverse_transfer" in body["compensation_tools"]
        assert "restore_repayment_date" in body["compensation_tools"]
        assert "transfer" in body["compensable"]
        assert "report_card_lost" in body["irreversible"]
        assert "reset_card_password" in body["irreversible"]

        catalog = {
            item["name"]: item for item in client.get("/api/tools").json()["tools"]
        }
        assert catalog["transfer"]["compensable"] is True
        assert catalog["transfer"]["compensation_tool"] == "reverse_transfer"
        assert catalog["adjust_repayment_date"]["compensable"] is True
        assert catalog["adjust_card_limit"]["compensation_tool"] == "restore_card_limit"
        assert catalog["report_card_lost"]["compensable"] is False
        assert catalog["query_bill"]["compensable"] is False


# 2. 可逆步骤失败后按相反顺序回滚，并写入 compensation_executed 审计
def test_reversible_failure_compensates_in_reverse_order(tmp_path: Path) -> None:
    with make_client(tmp_path, "reverse.db") as client:
        body = run_demo(client, mode="reversible")
        assert body["status"] == "rolled_back"
        assert body["rolled_back"] is True
        rollback = body["rollback"]
        assert rollback["status"] == "completed"
        assert [item["tool_name"] for item in rollback["compensated"]] == [
            "demo_charge_fee",
            "demo_reserve_funds",
        ]
        assert [item["compensation_tool"] for item in rollback["compensated"]] == [
            "reverse_demo_charge",
            "reverse_demo_reserve",
        ]

        events = event_names(client)
        assert events.count("compensation_executed") == 2
        assert "compensation_failed" not in events
        assert client.get("/api/audit/verify").json()["valid"] is True

        journal = client.get(f"/api/actions/{body['run_id']}/journal").json()
        assert journal["status"] == "rolled_back"
        phases = [entry["phase"] for entry in journal["entries"]]
        assert phases.count("executed") == 2
        assert phases.count("compensated") == 2
        assert [entry["tool_name"] for entry in journal["compensations"]] == [
            "demo_charge_fee",
            "demo_reserve_funds",
        ]


# 3. 不可逆步骤阻止回滚，响应与 plan 标注“不可撤销”
def test_irreversible_step_blocks_rollback(tmp_path: Path) -> None:
    with make_client(tmp_path, "irreversible.db") as client:
        body = run_demo(client, mode="irreversible")
        assert body["status"] == "unknown"
        assert body["rolled_back"] is False
        rollback = body["rollback"]
        assert rollback["status"] == "blocked"
        assert rollback["compensated"] == []
        blocked_tools = {item["tool_name"] for item in rollback["irreversible_steps"]}
        assert "demo_irreversible_marker" in blocked_tools
        assert "不可撤销" in body["reason"]
        assert body["plan"]["irreversible"] is True
        assert "不可撤销" in body["plan"]["rollback_blocked_reason"]
        marked = {
            step["id"]: step for step in body["plan"]["steps"] if step.get("irreversible")
        }
        assert "step-3" in marked
        assert "不可撤销" in marked["step-3"]["irreversible_reason"]

        events = event_names(client)
        assert "compensation_blocked" in events
        assert "compensation_executed" not in events

        manual = client.post(f"/api/actions/{body['run_id']}/rollback")
        assert manual.status_code == 200
        manual_body = manual.json()
        assert manual_body["rollback"]["status"] == "blocked"
        assert "不可撤销" in manual_body["reason"]


# 4. 部分补偿失败 -> unknown，并记录 compensation_failed
def test_partial_compensation_failure_is_unknown(tmp_path: Path) -> None:
    with make_client(tmp_path, "partial.db") as client:
        body = run_demo(client, mode="compensation_failure")
        assert body["status"] == "unknown"
        rollback = body["rollback"]
        assert rollback["status"] == "partial"
        assert [item["tool_name"] for item in rollback["compensated"]] == [
            "demo_reserve_funds"
        ]
        assert [item["tool_name"] for item in rollback["failed"]] == ["demo_charge_fee"]
        assert "补偿通道故障" in rollback["failed"][0]["error"]

        events = event_names(client)
        assert events.count("compensation_executed") == 1
        assert events.count("compensation_failed") == 1
        journal = client.get(f"/api/actions/{body['run_id']}/journal").json()
        phases = [entry["phase"] for entry in journal["entries"]]
        assert "compensated" in phases
        assert "compensation_failed" in phases


# 5. 节点间暂停：返回 paused + 已执行结果 + 恢复指引；resume 不重复已执行节点
def test_pause_after_node_then_resume_without_repeating(tmp_path: Path) -> None:
    with make_client(tmp_path, "pause-node.db") as client:
        paused = run_demo(client, mode="success", pause_after_first=True)
        assert paused["status"] == "paused"
        assert len(paused["results"]) == 1
        assert paused["results"][0]["tool_name"] == "demo_reserve_funds"
        assert paused["resume"]["endpoint"].endswith("/resume")
        assert paused["resume"]["next_index"] == 1
        assert [item["tool_name"] for item in paused["resume"]["remaining_steps"]] == [
            "demo_charge_fee"
        ]
        assert "action_paused" in event_names(client)

        action_id = paused["run_id"]
        journal = client.get(f"/api/actions/{action_id}/journal").json()
        assert journal["status"] == "paused"
        assert journal["pause"]["paused"] is True

        resumed = client.post(f"/api/actions/{action_id}/resume")
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["status"] == "completed"
        assert len(body["results"]) == 2
        assert [result["tool_name"] for result in body["results"]] == [
            "demo_reserve_funds",
            "demo_charge_fee",
        ]

        journal = client.get(f"/api/actions/{action_id}/journal").json()
        assert journal["status"] == "completed"
        assert [entry["tool_name"] for entry in journal["executed"]] == [
            "demo_reserve_funds",
            "demo_charge_fee",
        ]
        assert client.get("/api/audit/verify").json()["valid"] is True


# 6. 确认前暂停 -> confirm 返回 paused，resume 后只执行一次
def test_pause_before_confirmation_then_resume(tmp_path: Path) -> None:
    with make_client(tmp_path, "pause-confirm.db") as client:
        before = balance(client)
        run = start_transfer(client, 600)
        assert run["status"] == "awaiting_confirmation"
        action_id = run["confirmation"]["id"]

        paused_req = client.post(
            f"/api/actions/{action_id}/pause", params={"reason": "确认前暂停"}
        )
        assert paused_req.status_code == 200
        assert paused_req.json()["pause"]["paused"] is True

        confirmed = client.post(
            f"/api/confirmations/{action_id}", json={"approved": True}
        )
        assert confirmed.status_code == 200, confirmed.text
        paused = confirmed.json()
        assert paused["status"] == "paused"
        assert paused["results"] == []
        assert balance(client) == before
        view = client.get(f"/api/trust/actions/{action_id}").json()
        assert view["state"] == "PAUSED"

        resumed = client.post(f"/api/actions/{action_id}/resume")
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["status"] == "completed"
        assert balance(client) == before - 600
        assert len(body["results"]) == 1

        journal = client.get(f"/api/actions/{action_id}/journal").json()
        assert len(journal["executed"]) == 1
        assert journal["status"] == "completed"


# 7. rollback 端点可对已完成动作做逆序补偿
def test_rollback_endpoint_reverses_completed_transfer(tmp_path: Path) -> None:
    with make_client(tmp_path, "manual-rollback.db") as client:
        before = balance(client)
        run = start_transfer(client, 600)
        action_id = run["confirmation"]["id"]
        confirmed = client.post(
            f"/api/confirmations/{action_id}", json={"approved": True}
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "completed"
        assert balance(client) == before - 600

        response = client.post(f"/api/actions/{action_id}/rollback")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "rolled_back"
        assert body["rollback"]["status"] == "completed"
        assert body["rollback"]["compensated"][0]["compensation_tool"] == (
            "reverse_transfer"
        )
        assert balance(client) == before
        assert "compensation_executed" in event_names(client)
        assert body["rolled_back"] is True

        journal = client.get(f"/api/actions/{action_id}/journal").json()
        assert journal["status"] == "rolled_back"
        assert journal["state"] == "ROLLED_BACK"

        again = client.post(f"/api/actions/{action_id}/rollback")
        assert again.status_code == 200
        assert again.json()["status"] == "rolled_back"
        assert balance(client) == before
        assert client.get("/api/audit/verify").json()["valid"] is True


# 8. 撤权后补偿被权限网关拒绝 -> unknown，审计记录 compensation_failed
def test_revoked_compensation_permission_is_denied(tmp_path: Path) -> None:
    with make_client(tmp_path, "revoked.db") as client:
        revoked = client.put(
            "/api/permissions/reverse_demo_reserve", json={"granted": False}
        )
        assert revoked.status_code == 200

        body = run_demo(client, mode="reversible")
        assert body["status"] == "unknown"
        rollback = body["rollback"]
        assert rollback["status"] == "partial"
        assert [item["tool_name"] for item in rollback["failed"]] == [
            "demo_reserve_funds"
        ]
        failure = rollback["failed"][0]
        assert failure["compensation_tool"] == "reverse_demo_reserve"
        assert "未授权" in failure["error"]

        failed_entries = [
            entry for entry in audit_events(client) if entry["event"] == "compensation_blocked"
        ]
        assert failed_entries
        assert "未授权" in failed_entries[0]["result"]["error"]
        assert client.get("/api/audit/verify").json()["valid"] is True


# 9. 状态机新增回滚迁移，非法迁移仍被拒绝
def test_state_machine_allows_recovery_transitions(tmp_path: Path) -> None:
    db = Database(tmp_path / "state-machine.db")
    audit = AuditService(db)
    machine = StateMachine(
        db=db,
        action_id="act-compensation",
        audit=audit,
        user_id="demo-user",
        instruction="向 ACC-2002 转账 600 元",
        dag_path="step-1:transfer",
        tool_name="transfer",
        arguments={"amount_cny": 600},
        risk_level="yellow",
    )
    machine.transition(ActionState.AWAITING_CONFIRMATION, reason="等待确认")
    machine.transition(ActionState.APPROVED, reason="批准")
    machine.transition(ActionState.EXECUTING, reason="执行")
    machine.transition(ActionState.PAUSED, reason="暂停")
    machine.transition(ActionState.EXECUTING, reason="恢复")
    machine.transition(ActionState.ROLLED_BACK, reason="补偿完成")
    assert machine.state is ActionState.ROLLED_BACK

    completed = StateMachine(db=db, action_id="act-completed", audit=audit)
    completed.state = ActionState.COMPLETED
    completed.transition(ActionState.ROLLED_BACK, reason="人工回退")
    assert completed.state is ActionState.ROLLED_BACK

    failed = StateMachine(db=db, action_id="act-failed", audit=audit)
    failed.state = ActionState.FAILED
    failed.transition(ActionState.ROLLED_BACK, reason="失败后回退")
    assert failed.state is ActionState.ROLLED_BACK

    draft = StateMachine(db=db, action_id="act-draft", audit=audit)
    with pytest.raises(IllegalTransition):
        draft.transition(ActionState.EXECUTING, reason="非法迁移")
    with pytest.raises(IllegalTransition):
        draft.transition(ActionState.COMPLETED, reason="非法迁移")
    with pytest.raises(IllegalTransition):
        draft.transition(ActionState.ROLLED_BACK, reason="非法迁移")
    assert draft.state is ActionState.DRAFT


# 10. 真实红色安全工具不可逆：完成后 rollback 被阻止
def test_completed_irreversible_red_action_cannot_roll_back(tmp_path: Path) -> None:
    with make_client(tmp_path, "red.db") as client:
        run = client.post(
            "/api/agent/run",
            json={
                "instruction": "我的卡 CARD-8821 丢了，帮我挂失",
                "tool_name": "report_card_lost",
                "arguments": {"card_id": "CARD-8821"},
            },
        ).json()
        assert run["status"] == "awaiting_confirmation"
        action_id = run["confirmation"]["id"]
        confirmed = client.post(
            f"/api/confirmations/{action_id}",
            json={"approved": True, "reauth_token": DEMO_OTP},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "completed"

        response = client.post(f"/api/actions/{action_id}/rollback")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "blocked"
        assert body["rollback"]["status"] == "blocked"
        assert "不可撤销" in body["reason"]
        assert body["plan"]["irreversible"] is True
        assert body["rollback"]["irreversible_steps"][0]["tool_name"] == (
            "report_card_lost"
        )
        assert client.get("/api/audit/verify").json()["valid"] is True
