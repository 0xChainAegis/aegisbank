"""Security counterexamples found in the 2026-10-23 review, using isolated Mock DBs."""

from __future__ import annotations

import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from aegisbank_api.executor import SandboxViolation
from aegisbank_api.main import create_app
from aegisbank_api.planning.contracts import ExecutionPlan, PlanStep
from aegisbank_api.registry import BaseTool
from aegisbank_api.risk import RiskAssessment
from aegisbank_api.trust.action_envelope import EnvelopeError
from aegisbank_api.trust.idempotency import IdempotencyInProgress
from aegisbank_api.trust.sandbox import SandboxedToolExecutor, SandboxGuard, SandboxPolicy


@pytest.fixture
def system(tmp_path):
    app = create_app(database_path=tmp_path / "security.db")
    with TestClient(app) as client:
        yield client, app.state.services


def start(client, tool="transfer", arguments=None, **extra):
    response = client.post(
        "/api/agent/run",
        json={
            "instruction": "安全回归显式请求",
            "tool_name": tool,
            "arguments": arguments
            if arguments is not None
            else {
                "from_account": "ACC-1001",
                "to_account": "ACC-2002",
                "amount_cny": 100,
            },
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, pending, **extra):
    return client.post(
        f"/api/confirmations/{pending['confirmation']['id']}", json={"approved": True, **extra}
    )


def balance(services):
    return services.repository.account("demo-user", "ACC-1001").balance_cny


def execute_setting(client, tool, arguments):
    pending = start(client, tool, arguments)
    if pending["status"] == "awaiting_confirmation":
        response = approve(client, pending, reauth_token="246810")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"
    else:
        assert pending["status"] == "completed", pending
    return pending["run_id"]


@pytest.mark.parametrize("return_to_same_value", [False, True])
def test_old_repayment_rollback_preserves_later_instruction(system, return_to_same_value):
    client, services = system
    action = execute_setting(
        client, "adjust_repayment_date", {"card_id": "CARD-9902", "new_day": 12}
    )
    execute_setting(client, "adjust_repayment_date", {"card_id": "CARD-9902", "new_day": 18})
    if return_to_same_value:
        execute_setting(
            client, "adjust_repayment_date", {"card_id": "CARD-9902", "new_day": 12}
        )
    expected = services.repository.card("demo-user", "CARD-9902").repayment_day
    result = services.scheduler.rollback_action(action_id=action, user_id="demo-user")
    assert services.repository.card("demo-user", "CARD-9902").repayment_day == expected
    assert result["status"] == "unknown"
    assert services.audit.verify()["valid"]


def test_old_limit_rollback_preserves_later_security_limit(system):
    client, services = system
    action = execute_setting(
        client, "unlock_transaction_limit", {"card_id": "CARD-9902", "daily_limit_cny": 3000}
    )
    execute_setting(
        client, "set_transaction_limit", {"card_id": "CARD-9902", "daily_limit_cny": 100}
    )
    result = services.scheduler.rollback_action(action_id=action, user_id="demo-user")
    assert services.repository.card("demo-user", "CARD-9902").transaction_limit_cny == 100
    assert result["status"] == "unknown"


def test_old_wealth_profile_rollback_preserves_later_preference(system):
    client, services = system
    action = execute_setting(client, "assess_wealth_risk", {"risk_preference": "R3"})
    execute_setting(client, "assess_wealth_risk", {"risk_preference": "R1"})
    result = services.scheduler.rollback_action(action_id=action, user_id="demo-user")
    with services.db.transaction() as conn:
        preference = conn.execute(
            "SELECT risk_preference FROM wealth_profile WHERE user_id='demo-user'"
        ).fetchone()
    assert preference is not None
    assert preference[0] == "R1"
    assert result["status"] == "unknown"


@pytest.mark.parametrize(
    ("tool", "field"),
    [("restore_card_limit", "previous_limit_cny"),
     ("restore_transaction_limit", "previous_transaction_limit_cny")],
)
def test_restore_limits_assesses_actual_target(system, tool, field):
    _, services = system
    assessment = services.scheduler.risk_engine.assess(
        user_id="demo-user", tool_name=tool,
        arguments={"original_result": {"data": {field: 10000}}},
        base_risk=RiskLevel.YELLOW,
    )
    assert assessment.level is RiskLevel.RED
    assert assessment.requires_reauth


def test_rollback_cannot_restore_high_limit_without_mfa(system):
    client, services = system
    with services.db.transaction() as conn:
        conn.execute("UPDATE bank_cards SET transaction_limit_cents=1000000 "
                     "WHERE card_id='CARD-9902'")
    action = execute_setting(
        client, "unlock_transaction_limit", {"card_id": "CARD-9902", "daily_limit_cny": 1000}
    )
    result = services.scheduler.rollback_action(action_id=action, user_id="demo-user")
    assert services.repository.card("demo-user", "CARD-9902").transaction_limit_cny == 1000
    assert result["status"] == "unknown"


def test_compensation_rechecks_mfa_inside_execution_transaction(system, monkeypatch):
    client, services = system
    pending = start(client)
    assert approve(client, pending).status_code == 200
    before = balance(services)
    original = services.scheduler.risk_engine.assess
    calls = 0

    def escalate(**kwargs):
        nonlocal calls
        if kwargs["tool_name"] == "reverse_transfer":
            calls += 1
            if calls >= 2:
                return RiskAssessment(RiskLevel.RED, 100, ["复检风险升级"], RiskLevel.YELLOW, True)
        return original(**kwargs)

    monkeypatch.setattr(services.scheduler.risk_engine, "assess", escalate)
    result = services.scheduler.rollback_action(
        action_id=pending["confirmation"]["id"], user_id="demo-user"
    )
    assert balance(services) == before
    assert result["status"] == "unknown"
    assert any(row["event"] == "compensation_blocked" for row in services.db.list_audit())
    assert services.audit.verify()["valid"]


@pytest.mark.parametrize("operation", ["grant", "revoke"])
def test_permission_mutation_is_atomic_with_audit(system, monkeypatch, operation):
    client, services = system
    granted = operation == "revoke"
    services.gateway.permissions.set_granted("demo-user", "transfer", granted)
    original = type(services.audit).record

    def fail_permission_audit(self, **kwargs):
        if kwargs["event"] in {"permission_updated", "role_revocation"}:
            raise OSError("injected permission audit failure")
        return original(self, **kwargs)

    monkeypatch.setattr(type(services.audit), "record", fail_permission_audit)
    with pytest.raises(OSError, match="injected permission audit failure"):
        if operation == "grant":
            client.put("/api/permissions/transfer", json={"granted": True})
        else:
            client.post("/api/authz/revoke/transfer")
    assert services.db.get_permission("demo-user", "transfer") is granted
    assert services.audit.verify()["valid"]


def test_old_credit_limit_rollback_preserves_later_limit(system):
    client, services = system
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE bank_cards SET credit_limit_cents=500000,available_limit_cents=500000 "
            "WHERE card_id='CARD-9902'"
        )
    action = execute_setting(
        client, "adjust_card_limit", {"card_id": "CARD-9902", "new_limit_cny": 3000}
    )
    execute_setting(client, "adjust_card_limit", {"card_id": "CARD-9902", "new_limit_cny": 2000})
    result = services.scheduler.rollback_action(action_id=action, user_id="demo-user")
    assert services.repository.card("demo-user", "CARD-9902").credit_limit_cny == 2000
    assert result["status"] == "unknown"


@pytest.mark.parametrize("other_card", [False, True])
def test_setting_rollback_allows_reverse_order_and_unrelated_resources(system, other_card):
    client, services = system
    before = services.repository.card("demo-user", "CARD-9902").repayment_day
    first = execute_setting(
        client, "adjust_repayment_date", {"card_id": "CARD-9902", "new_day": 12}
    )
    second = execute_setting(
        client, "adjust_repayment_date",
        {"card_id": "CARD-8821" if other_card else "CARD-9902", "new_day": 18},
    )
    if not other_card:
        assert services.scheduler.rollback_action(
            action_id=second, user_id="demo-user"
        )["status"] == "rolled_back"
    assert services.scheduler.rollback_action(
        action_id=first, user_id="demo-user"
    )["status"] == "rolled_back"
    assert services.repository.card("demo-user", "CARD-9902").repayment_day == before
    if other_card:
        assert services.repository.card("demo-user", "CARD-8821").repayment_day == 18
    assert services.audit.verify()["valid"]


@pytest.mark.parametrize(
    "tool",
    [
        "reverse_transfer",
        "reverse_purchase_wealth",
        "restore_card_limit",
        "reactivate_subscription",
    ],
)
def test_internal_compensation_cannot_be_called_publicly(system, tool):
    client, services = system
    before = balance(services)
    body = start(
        client,
        tool,
        {
            "original_arguments": {"amount_cny": 1000000, "from_account": "ACC-1001"},
            "original_result": {"data": {"transaction_id": "forged"}},
        },
    )
    assert body["status"] in {"blocked", "needs_clarification"}
    assert balance(services) == before


def test_two_transfers_require_cumulative_mfa(system):
    client, services = system
    services.scheduler.planner.plan = lambda _: ExecutionPlan(
        intent="two_transfers",
        planner="regression",
        steps=[
            PlanStep(
                id="one",
                tool_name="transfer",
                arguments={"to_account": "ACC-2002", "amount_cny": 600},
            ),
            PlanStep(
                id="two",
                tool_name="transfer",
                arguments={"to_account": "ACC-2002", "amount_cny": 600},
                depends_on=["one"],
            ),
        ],
    )
    pending = start(client)
    before = balance(services)
    assert pending["risk_level"] == "red"
    assert approve(client, pending).status_code == 403
    assert balance(services) == before
    done = approve(client, pending, reauth_token="246810")
    assert done.status_code == 200, done.text
    assert balance(services) == before - 1200


def test_success_audit_failure_rolls_back_tool_and_journal(system, monkeypatch):
    client, services = system
    pending = start(client)
    before = balance(services)
    original = type(services.audit).record

    def fail_success(self, **kwargs):
        if kwargs["event"] == "tool_executed":
            raise OSError("injected audit storage failure")
        return original(self, **kwargs)

    monkeypatch.setattr(type(services.audit), "record", fail_success)
    response = approve(client, pending)
    assert response.status_code == 422, response.text
    assert balance(services) == before
    assert not services.scheduler.journal.executed_entries(pending["confirmation"]["id"])
    assert services.audit.verify()["valid"]


def test_concurrent_rollback_refunds_only_once(system):
    client, services = system
    before = balance(services)
    pending = start(client)
    assert approve(client, pending).status_code == 200
    action_id = pending["confirmation"]["id"]
    barrier = threading.Barrier(2)

    def rollback():
        barrier.wait(timeout=5)
        try:
            return services.scheduler.rollback_action(action_id=action_id, user_id="demo-user")
        except EnvelopeError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: rollback(), range(2)))
    assert balance(services) == before, results
    entries = services.scheduler.journal.entries(action_id)
    assert sum(entry["phase"] == "compensated" for entry in entries) == 1


def test_concurrent_overspend_is_rejected(system):
    _, services = system
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE bank_accounts SET balance_cents=100000,available_cents=100000 "
            "WHERE account_id='ACC-1001'"
        )
    barrier = threading.Barrier(2)

    def transfer():
        barrier.wait(timeout=5)
        try:
            services.repository.transfer(
                "demo-user",
                {
                    "from_account": "ACC-1001",
                    "to_account": "ACC-2002",
                    "amount_cny": 800,
                    "note": "race",
                },
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: transfer(), range(2)))
    assert results.count(True) == 1
    assert balance(services) == 200


def test_auditor_cannot_reject_or_read_other_owner_replay(system):
    client, services = system
    pending = start(client)
    aid = pending["confirmation"]["id"]
    rejected = client.post(
        f"/api/confirmations/{aid}", json={"approved": False}, headers={"X-Aegis-Role": "auditor"}
    )
    assert rejected.status_code == 403
    assert services.db.get_pending(aid)["status"] == "pending"
    assert approve(client, pending).status_code == 200
    events = client.get("/api/audit", params={"run_id": aid}).json()["entries"]
    assert {"confirmation_requested", "confirmation_approved", "tool_executed"} <= {
        e["event"] for e in events
    }
    assert next(e for e in events if e["event"] == "tool_executed")["step_id"] == "step-1"
    with pytest.raises(ValueError, match="不属于"):
        services.scheduler.confirm(
            user_id="stranger", action_id=aid, approved=True, reauth_token=None, role="user"
        )


@pytest.mark.parametrize("envelopes", [[], [{"bad": "data"}]])
def test_missing_or_corrupt_envelopes_fail_closed(system, envelopes):
    client, services = system
    pending = start(client)
    aid = pending["confirmation"]["id"]
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE pending_actions SET envelopes_json=? WHERE id=?", (json.dumps(envelopes), aid)
        )
    before = balance(services)
    response = approve(client, pending)
    assert response.status_code == 409, response.text
    assert balance(services) == before


def test_mfa_failures_do_not_open_breaker(system):
    client, services = system
    pending = start(client, arguments={"to_account": "ACC-2002", "amount_cny": 1500})
    for _ in range(3):
        assert approve(client, pending, reauth_token="000000").status_code == 403
    assert not services.scheduler.breaker.is_open(user_id="demo-user")
    before = balance(services)
    result = approve(client, pending, reauth_token="246810")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    assert balance(services) == before - 1500


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("put", "/api/permissions/transfer", {"granted": False}),
        ("post", "/api/compensation/demo/run", {"mode": "success"}),
        ("post", "/api/sandbox/demo/run", {"kind": "network"}),
        ("post", "/api/channels/im/message", {"text": "查询余额", "sender_id": "alice"}),
        ("post", "/api/trust/breaker/unlock", {}),
        ("post", "/api/automation/run-due", {}),
    ],
)
def test_all_mutations_share_readiness(system, method, path, body):
    client, _ = system
    client.app.state.readiness.overrides["sqlite"] = False
    response = getattr(client, method)(path, json=body, headers={"X-Aegis-Role": "operator"})
    assert response.status_code == 503


def test_scheduled_transfer_rechecks_role_permission_and_risk(system):
    client, services = system
    run_at = datetime.now(UTC) + timedelta(days=2)
    pending = start(
        client,
        "schedule_transfer",
        {
            "to_account": "ACC-2002",
            "amount_cny": 1500,
            "run_at": run_at.isoformat(),
        },
    )
    assert pending["risk_level"] == "red"
    assert approve(client, pending).status_code == 403
    assert approve(client, pending, reauth_token="246810").status_code == 200
    before = balance(services)
    due = {"now": (run_at + timedelta(hours=1)).isoformat()}
    assert (
        client.post(
            "/api/automation/run-due", json=due, headers={"X-Aegis-Role": "auditor"}
        ).status_code
        == 403
    )
    client.put("/api/permissions/transfer", json={"granted": False})
    result = client.post("/api/automation/run-due", json=due)
    assert result.status_code == 200, result.text
    assert balance(services) == before
    assert result.json()["failed_count"] == 1


def test_resuming_rechecks_permission_and_concurrent_resume_executes_once(system):
    client, services = system
    paused = client.post(
        "/api/compensation/demo/run", json={"mode": "success", "pause_after_first": True}
    ).json()
    aid = paused["run_id"]
    client.put("/api/permissions/demo_charge_fee", json={"granted": False})
    response = client.post(f"/api/actions/{aid}/resume")
    assert response.status_code in {200, 422}, response.text
    assert not any(
        e["tool_name"] == "demo_charge_fee"
        for e in services.scheduler.journal.executed_entries(aid)
    )
    client.put("/api/permissions/demo_charge_fee", json={"granted": True})
    paused = client.post(
        "/api/compensation/demo/run", json={"mode": "success", "pause_after_first": True}
    ).json()
    aid = paused["run_id"]
    barrier = threading.Barrier(2)

    def resume():
        barrier.wait(timeout=5)
        try:
            return services.scheduler.resume_action(action_id=aid, user_id="demo-user")
        except (EnvelopeError, ValueError) as exc:
            return str(exc)

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: resume(), range(2)))
    entries = services.scheduler.journal.executed_entries(aid)
    assert sum(e["tool_name"] == "demo_charge_fee" for e in entries) == 1


def test_im_sender_channel_and_content_are_bound(system):
    client, _ = system

    def message(sender, text, channel="im", message_id="same"):
        return client.post(
            "/api/channels/im/message",
            json={"sender_id": sender, "text": text, "channel": channel, "message_id": message_id},
        )

    alice = message("alice", "向 ACC-2002 转账 100 元").json()
    bob = message("bob", "查询余额").json()
    assert alice != bob
    # Reusing the same sender's message ID for a different request is a conflict.
    assert message("alice", "查询余额").status_code == 409
    aid = alice["confirmation"]["id"]
    denied = message("bob", f"确认 {aid}", message_id="confirm-other")
    assert "不属于该通道发送者" in denied.text
    assert message("alice", "查询余额", channel="cli").status_code == 200


@pytest.mark.parametrize("amount", [0, -1, 0.001, float("inf"), float("nan")])
def test_money_must_be_finite_positive_and_exact_to_cent(system, amount):
    _, services = system
    with pytest.raises(ValueError):
        services.registry.get("transfer").validate_arguments(
            {"to_account": "ACC-2002", "amount_cny": amount}
        )


def test_unknown_user_and_new_tool_have_no_implicit_grants(system):
    client, services = system
    assert not services.gateway.permissions.is_granted("stranger", "transfer", services.registry)
    assert not services.gateway.permissions.is_granted(
        "demo-user", "future_money_tool", services.registry
    )
    before = services.db.list_permissions("stranger")
    client.get("/api/permissions", params={"user_id": "stranger"})
    assert services.db.list_permissions("stranger") == before


def test_card_limit_preserves_used_credit(system):
    client, services = system
    before = services.repository.card("demo-user", "CARD-8821")
    pending = start(client, "adjust_card_limit", {"card_id": "CARD-8821", "new_limit_cny": 10000})
    response = approve(client, pending, reauth_token="246810")
    assert response.status_code == 200, response.text
    after = services.repository.card("demo-user", "CARD-8821")
    assert (
        before.credit_limit_cny - before.available_limit_cny
        == after.credit_limit_cny - after.available_limit_cny
    )
    low = start(client, "adjust_card_limit", {"card_id": "CARD-8821", "new_limit_cny": 8000})
    assert approve(client, low, reauth_token="246810").status_code == 422


def test_no_defaults_negations_or_silent_partial_multi_intent(system):
    client, _ = system
    for instruction in ["转账", "帮我设置限额", "不要挂失 CARD-9902", "给张三转100，再给李四转200"]:
        response = client.post("/api/agent/run", json={"instruction": instruction})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "needs_clarification", response.text
    missing = client.post(
        "/api/agent/run", json={"instruction": "转账", "tool_name": "transfer", "arguments": {}}
    )
    assert missing.status_code == 400
    explicit_negation = client.post(
        "/api/agent/run",
        json={
            "instruction": "不要转账",
            "tool_name": "transfer",
            "arguments": {"to_account": "ACC-2002", "amount_cny": 100},
        },
    )
    assert explicit_negation.json()["status"] == "needs_clarification"


def test_balance_query_returns_bank_balance_and_bills_respect_revoke(system):
    client, services = system
    body = client.post("/api/agent/run", json={"instruction": "查询余额"}).json()
    assert body["results"][0]["data"]["balance_cny"] == balance(services)
    client.put("/api/permissions/bill_report", json={"granted": False})
    assert client.get("/api/bills/report").status_code == 403


def test_audit_is_atomic_and_searchable_by_distinct_run(system):
    client, services = system
    before = len(services.audit.list(200))

    def query(_):
        return services.scheduler.run(user_id="demo-user", instruction="查询余额")

    with ThreadPoolExecutor(4) as pool:
        runs = list(pool.map(query, range(8)))
    assert services.audit.verify()["valid"]
    assert len(services.audit.list(200)) >= before + 8
    for run in runs:
        entries = client.get("/api/audit", params={"run_id": run["run_id"]}).json()["entries"]
        assert entries and all(e["run_id"] == run["run_id"] for e in entries)
        assert any(e["event"] == "tool_executed" for e in entries)


def test_idempotency_concurrent_claim_is_stable(system):
    client, _ = system
    barrier = threading.Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        try:
            return client.app.state.idempotency.begin(scope="test", key="same", request_hash="body")
        except IdempotencyInProgress:
            return "running"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert results.count("running") == 1


def test_corrupt_tool_output_cannot_commit_balance_change(system, monkeypatch):
    client, services = system
    pending = start(client)
    tool = services.registry.get("transfer")
    original = tool.execute

    def corrupt(args, context):
        result = original(args, context)
        result.data["amount_cny"] = "invented"
        return result

    monkeypatch.setattr(tool, "execute", corrupt)
    before = balance(services)
    response = approve(client, pending)
    assert response.status_code == 422, response.text
    assert balance(services) == before


def test_timeout_cannot_write_late_and_network_guard_does_not_block_other_threads(
    system, monkeypatch
):
    _, services = system
    policy = SandboxPolicy(timeout_seconds=0.05)
    executor = SandboxedToolExecutor(
        [SandboxGuard(policy=policy, audit=services.audit)], policy=policy, audit=services.audit
    )
    started, finished = threading.Event(), threading.Event()

    class DelayedWrite(BaseTool):
        metadata = ToolMetadata(
            name="delayed_regression",
            title="test",
            description="test",
            risk_level=RiskLevel.GREEN,
            permission="test",
        )

        def execute(self, arguments, context):
            started.set()
            time.sleep(0.12)
            try:
                with services.db.transaction() as conn:
                    conn.execute(
                        "UPDATE bank_accounts SET balance_cents=balance_cents+12345 "
                        "WHERE account_id='ACC-1001'"
                    )
            finally:
                finished.set()
            return ToolResult(
                tool_name=self.metadata.name, message="test", data={"simulated": True}
            )

    before = balance(services)

    def execute():
        with pytest.raises(SandboxViolation):
            executor.execute(
                DelayedWrite(),
                {},
                ExecutionContext(
                    user_id="demo-user", instruction="test", run_id="timeout", dag_path="test"
                ),
            )

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(execute)
        assert started.wait(5)
        assert socket.getaddrinfo("localhost", 80)
        future.result(timeout=5)
    assert finished.wait(5)
    assert balance(services) == before
    # A queued tool has the submission deadline, and is cancelled before it starts.
    import aegisbank_api.trust.sandbox as sandbox_module

    queued = threading.Event()
    started.clear()
    with ThreadPoolExecutor(1) as pool:
        monkeypatch.setattr(sandbox_module, "_WORKERS", pool)
        blocker = pool.submit(queued.wait, 5)
        try:
            with pytest.raises(SandboxViolation):
                executor.execute(
                    DelayedWrite(),
                    {},
                    ExecutionContext(
                        user_id="demo-user",
                        instruction="queued",
                        run_id="queued",
                        dag_path="queued",
                    ),
                )
        finally:
            queued.set()
        blocker.result(timeout=5)
    assert not started.is_set()
    assert balance(services) == before


def test_reconciliation_needs_operator_and_cannot_claim_a_refund(system, monkeypatch):
    from aegisbank_api.trust.state_machine import ExecutionOutcomeUnknown

    client, services = system
    pending = start(client)
    aid = pending["confirmation"]["id"]

    def unknown(*_args):
        raise ExecutionOutcomeUnknown("external outcome unavailable")

    monkeypatch.setattr(services.registry.get("transfer"), "execute", unknown)
    assert approve(client, pending).json()["status"] == "unknown"
    endpoint = f"/api/trust/actions/{aid}/reconcile"
    assert (
        client.post(
            endpoint,
            json={"outcome": "reconciled", "reason": "checked"},
            headers={"X-Aegis-Role": "auditor"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            endpoint,
            json={"outcome": "rolled_back", "reason": "checked"},
            headers={"X-Aegis-Role": "operator"},
        ).status_code
        == 400
    )
    response = client.post(
        endpoint,
        json={"outcome": "reconciled", "reason": "checked mock ledger"},
        headers={"X-Aegis-Role": "operator"},
    )
    assert response.status_code == 200, response.text
    replay = approve(client, pending).json()
    assert replay["status"] == "reconciled"
    assert replay["reconciliation"]["funds_reversed"] is False


def test_scheduled_risk_escalation_without_original_mfa_is_blocked(system):
    client, services = system
    moment = datetime.now(UTC) + timedelta(days=1)
    pending = start(
        client,
        "schedule_transfer",
        {
            "to_account": "ACC-2002",
            "amount_cny": 500,
            "run_at": moment.isoformat(),
        },
    )
    assert approve(client, pending).status_code == 200
    other = start(client, arguments={"to_account": "ACC-2002", "amount_cny": 900})
    assert approve(client, other).status_code == 200
    before = balance(services)
    response = client.post(
        "/api/automation/run-due", json={"now": (moment + timedelta(hours=1)).isoformat()}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["failed_count"] == 0
    assert payload["executed_count"] == 0
    assert payload["pending_reauth_count"] == 1
    assert payload["action_required"] is True
    assert "OTP" in payload["pending_reauth"][0]["action_required"]
    assert balance(services) == before

    replay = client.post(
        "/api/automation/run-due", json={"now": (moment + timedelta(hours=2)).isoformat()}
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["pending_reauth_count"] == 1
    assert replay.json()["executed_count"] == 0
    assert balance(services) == before


def test_gifts_respect_budget_and_create_consistent_transactions(system):
    client, services = system
    too_small = client.post(
        "/api/agent/run", json={"instruction": "帮我准备妈妈的生日，预算100元"}
    ).json()
    assert too_small["status"] == "needs_clarification"
    before = balance(services)
    pending = client.post(
        "/api/agent/run", json={"instruction": "帮我准备妈妈的生日，预算500元"}
    ).json()
    assert approve(client, pending, reauth_token="246810").status_code == 200
    response = client.post("/api/automation/run-due", json={"now": "2030-12-31T00:00:00+00:00"})
    assert response.status_code == 200, response.text
    assert response.json()["executed_count"] == 2, response.text
    account = services.repository.account("demo-user", "ACC-1001")
    assert account.available_cny <= account.balance_cny
    assert balance(services) == before - 358
    with services.db.transaction() as conn:
        rows = conn.execute(
            "SELECT amount_cents FROM bank_transactions WHERE category='gift'"
        ).fetchall()
    assert sum(row["amount_cents"] for row in rows) == -35800


def test_redeem_all_shares_closes_market_value_and_conserves_shares(system):
    client, services = system
    before = balance(services)
    pending = start(client, "redeem_wealth", {"holding_id": "HLTH-DEMO-R2", "shares": 3000})
    response = approve(client, pending, reauth_token="246810")
    assert response.status_code == 200, response.text
    with services.db.transaction() as conn:
        holding = conn.execute(
            "SELECT * FROM wealth_holdings WHERE holding_id='HLTH-DEMO-R2'"
        ).fetchone()
        order = conn.execute("SELECT * FROM wealth_orders WHERE side='redeem'").fetchone()
    assert holding["status"] == "closed"
    assert holding["shares"] == 0 and holding["market_value_cents"] == 0
    assert order["shares"] == 3000
    assert balance(services) - before == order["amount_cents"] / 100


def test_scheduled_failure_cannot_leave_a_false_done_status(system, monkeypatch):
    import aegisbank_api.scenarios.automation as automation

    client, services = system
    moment = datetime.now(UTC) + timedelta(days=1)
    pending = start(
        client,
        "schedule_transfer",
        {
            "to_account": "ACC-2002",
            "amount_cny": 100,
            "run_at": moment.isoformat(),
        },
    )
    assert approve(client, pending).status_code == 200
    original = automation._claim_task

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected failure after claim")

    monkeypatch.setattr(automation, "_claim_task", interrupted)
    before = balance(services)
    response = client.post(
        "/api/automation/run-due", json={"now": (moment + timedelta(hours=1)).isoformat()}
    )
    assert response.status_code == 200, response.text
    with services.db.transaction() as conn:
        rows = conn.execute("SELECT status FROM scheduled_tasks").fetchall()
    assert all(row["status"] != "done" for row in rows)
    assert balance(services) == before


def test_follow_up_context_is_owned_single_use_and_idempotent(system):
    client, _ = system
    first = client.post("/api/agent/run", json={"instruction": "给张三转账"}).json()
    assert first["status"] == "needs_clarification"
    body = {"instruction": "100元", "clarification_run_id": first["run_id"]}
    headers = {"Idempotency-Key": "follow-up-key"}
    wrong_owner = client.post("/api/agent/run", json={**body, "user_id": "stranger"})
    assert wrong_owner.status_code == 409
    result = client.post("/api/agent/run", json=body, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "awaiting_confirmation", result.text
    step = result.json()["plan"]["steps"][0]
    assert step["arguments"]["amount_cny"] == 100
    replay = client.post("/api/agent/run", json=body, headers=headers)
    assert replay.json() == result.json()
    assert client.post("/api/agent/run", json=body).status_code == 409


def test_model_cannot_add_extra_transfer_or_change_critical_scenario_fields():
    from aegisbank_api.planning.contracts import PlanningRequest
    from aegisbank_api.planning.llm import _candidate_conflict

    expected = ExecutionPlan(
        intent="transfer",
        planner="rule",
        steps=[
            PlanStep(
                id="one",
                tool_name="transfer",
                arguments={"to_account": "ACC-2002", "amount_cny": 100},
            )
        ],
    )
    duplicate = expected.model_copy(deep=True)
    duplicate.steps.append(
        PlanStep(
            id="two", tool_name="transfer", arguments={"to_account": "ACC-2002", "amount_cny": 100}
        )
    )
    assert _candidate_conflict(
        duplicate, PlanningRequest(instruction="向 ACC-2002 转账100元"), expected
    )
    wrong_amount = ExecutionPlan(
        intent="transfer",
        steps=[
            PlanStep(
                id="one",
                tool_name="transfer_to_contact",
                arguments={"to_name": "张三", "amount_cny": 10},
            )
        ],
    )
    assert _candidate_conflict(wrong_amount, PlanningRequest(instruction="给张三转100元"))
    extra_write = ExecutionPlan(
        intent="query",
        steps=[
            PlanStep(id="one", tool_name="query_balance"),
            PlanStep(
                id="two",
                tool_name="transfer",
                arguments={"to_account": "ACC-2002", "amount_cny": 100},
            ),
        ],
    )
    assert _candidate_conflict(
        extra_write, PlanningRequest(instruction="查询余额", tool_name="query_balance")
    )


def test_transfer_rollback_cannot_overdraw_a_spent_recipient(system):
    client, services = system
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE bank_accounts SET balance_cents=0, available_cents=0 "
            "WHERE account_id='ACC-2002'"
        )
    pending = start(client)
    assert approve(client, pending).status_code == 200
    onward = start(
        client, arguments={"from_account": "ACC-2002", "to_account": "ACC-9009", "amount_cny": 100}
    )
    assert approve(client, onward).status_code == 200
    before = balance(services)
    response = client.post(f"/api/actions/{pending['confirmation']['id']}/rollback")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unknown", response.text
    assert balance(services) == before
    assert services.repository.account("demo-user", "ACC-2002").balance_cny == 0
    assert services.audit.verify()["valid"]


def test_wealth_purchase_rollback_cannot_refund_a_redeemed_holding(system):
    client, services = system
    purchase = start(client, "purchase_wealth", {"product_id": "WPRD-R2", "amount_cny": 1000})
    bought = approve(client, purchase, reauth_token="246810")
    assert bought.status_code == 200, bought.text
    holding_id = bought.json()["results"][0]["data"]["holding_id"]
    redemption = start(client, "redeem_wealth", {"holding_id": holding_id})
    assert approve(client, redemption, reauth_token="246810").status_code == 200
    before = balance(services)
    response = client.post(f"/api/actions/{purchase['confirmation']['id']}/rollback")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unknown", response.text
    assert balance(services) == before
    assert services.audit.verify()["valid"]
