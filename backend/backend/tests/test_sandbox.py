"""Tests for the stage-2A tool execution sandbox."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.config import Settings
from aegisbank_api.domain import ExecutionContext
from aegisbank_api.executor import SandboxViolation
from aegisbank_api.extensions import reset_extension_cache
from aegisbank_api.main import create_app
from aegisbank_api.trust.sandbox import (
    SandboxedToolExecutor,
    SandboxGuard,
    SandboxPolicy,
)

QUERY_BILL_BODY = {
    "instruction": "查询我的本月账单",
    "tool_name": "query_bill",
    "arguments": {"account_id": "ACC-1001"},
}


def make_client(tmp_path, **settings_overrides) -> TestClient:
    settings = Settings(**settings_overrides) if settings_overrides else None
    return TestClient(
        create_app(database_path=tmp_path / "sandbox-test.db", settings=settings)
    )


def context(**overrides) -> ExecutionContext:
    values = {
        "user_id": "demo-user",
        "instruction": "沙箱单元测试",
        "run_id": "sandbox-unit",
        "dag_path": "sandbox",
    }
    values.update(overrides)
    return ExecutionContext(**values)


def test_network_access_is_blocked_and_audited(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/sandbox/demo/run", json={"kind": "network"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["blocked"] is True
        assert body["event"] == "sandbox_blocked"
        assert body["violation"] == "network"
        assert "网络" in body["reason"]
        assert body["tool_name"] == "sandbox_demo_network"

        entries = client.get("/api/audit").json()["entries"]
        assert len(entries) == 1
        assert entries[0]["event"] == "sandbox_blocked"
        assert entries[0]["tool_name"] == "sandbox_demo_network"
        assert entries[0]["result"]["kind"] == "network"
        assert client.get("/api/audit/verify").json()["valid"] is True

        # The shield must be restored once the guarded call has finished.
        policy = client.get("/api/sandbox/policy").json()
        assert policy["network_block_active"] is False


def test_oversized_output_is_rejected_and_audited(tmp_path):
    with make_client(tmp_path, sandbox_max_output_bytes=1024) as client:
        response = client.post("/api/sandbox/demo/run", json={"kind": "oversize"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["blocked"] is True
        assert body["event"] == "sandbox_blocked"
        assert body["violation"] == "output_too_large"
        assert "输出" in body["reason"]

        entries = client.get("/api/audit").json()["entries"]
        assert len(entries) == 1
        assert entries[0]["event"] == "sandbox_blocked"
        assert entries[0]["result"]["kind"] == "output_too_large"
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_slow_tool_times_out_and_is_audited(tmp_path):
    with make_client(tmp_path, sandbox_timeout_seconds=0.2) as client:
        response = client.post("/api/sandbox/demo/run", json={"kind": "slow"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["blocked"] is True
        assert body["event"] == "sandbox_timeout"
        assert body["violation"] == "timeout"
        assert "超时" in body["reason"]

        entries = client.get("/api/audit").json()["entries"]
        assert len(entries) == 1
        assert entries[0]["event"] == "sandbox_timeout"
        assert entries[0]["tool_name"] == "sandbox_demo_slow"
        assert entries[0]["result"]["kind"] == "timeout"
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_normal_tool_execution_is_unaffected(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/agent/run", json=QUERY_BILL_BODY)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert body["results"][0]["data"]["simulated"] is True

        policy = client.get("/api/sandbox/policy").json()
        assert policy["executor"] == "SandboxedToolExecutor"
        assert policy["guards"] == ["sandbox"]
        assert policy["network_block_active"] is False

        events = [entry["event"] for entry in client.get("/api/audit").json()["entries"]]
        assert "tool_executed" in events
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_policy_endpoint_reports_effective_policy(tmp_path):
    with make_client(
        tmp_path, sandbox_timeout_seconds=1.5, sandbox_max_output_bytes=2048
    ) as client:
        response = client.get("/api/sandbox/policy")
        assert response.status_code == 200
        body = response.json()
        policy = body["policy"]
        assert policy["enabled"] is True
        assert policy["timeout_seconds"] == 1.5
        assert policy["max_output_bytes"] == 2048
        assert policy["max_argument_bytes"] > 0
        assert policy["block_network"] is True
        assert policy["allowed_tools"] == []
        assert policy["tool_whitelist_enforced"] is False
        assert body["enabled"] is True
        assert body["timeout_seconds"] == 1.5
        assert body["executor"] == "SandboxedToolExecutor"
        assert body["guards"] == ["sandbox"]
        assert sorted(body["demo_kinds"]) == ["network", "oversize", "slow"]


def test_tool_whitelist_and_argument_limit_are_enforced(tmp_path):
    with make_client(tmp_path) as client:
        services = client.app.state.services
        tool = services.registry.get("query_bill")

        whitelist_policy = SandboxPolicy(allowed_tools=("transfer",))
        whitelist_executor = SandboxedToolExecutor(
            guards=[SandboxGuard(policy=whitelist_policy, audit=services.audit)],
            audit=services.audit,
            policy=whitelist_policy,
        )
        with pytest.raises(SandboxViolation, match="白名单"):
            whitelist_executor.execute(tool, {"account_id": "ACC-1001"}, context())
        entries = client.get("/api/audit").json()["entries"]
        assert len(entries) == 1
        assert entries[0]["event"] == "sandbox_blocked"
        assert entries[0]["result"]["kind"] == "tool_whitelist"

        size_policy = SandboxPolicy(max_argument_bytes=8)
        size_executor = SandboxedToolExecutor(
            guards=[SandboxGuard(policy=size_policy, audit=services.audit)],
            audit=services.audit,
            policy=size_policy,
        )
        with pytest.raises(SandboxViolation, match="入参"):
            size_executor.execute(tool, {"account_id": "ACC-1001"}, context())
        entries = client.get("/api/audit").json()["entries"]
        assert len(entries) == 2
        assert entries[0]["event"] == "sandbox_blocked"
        assert entries[0]["result"]["kind"] == "arguments_too_large"
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_disabled_sandbox_keeps_plain_executor(tmp_path):
    with make_client(tmp_path, sandbox_enabled=False) as client:
        body = client.get("/api/sandbox/policy").json()
        assert body["policy"]["enabled"] is False
        assert body["executor"] == "ToolExecutor"

        demo = client.post("/api/sandbox/demo/run", json={"kind": "network"}).json()
        assert demo["blocked"] is False
        assert demo["sandbox_enabled"] is False
        assert "未启用" in demo["reason"]

        run = client.post("/api/agent/run", json=QUERY_BILL_BODY)
        assert run.status_code == 200
        assert run.json()["status"] == "completed"


def test_extension_loads_in_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_EXTENSION_ALLOW", "sandbox")
    reset_extension_cache()
    try:
        with TestClient(create_app(database_path=tmp_path / "isolated.db")) as client:
            names = [module.NAME for module in client.app.state.extension_modules]
            assert names == ["sandbox"]
            assert client.get("/api/sandbox/policy").status_code == 200
            run = client.post("/api/agent/run", json=QUERY_BILL_BODY)
            assert run.status_code == 200
            assert run.json()["status"] == "completed"
    finally:
        reset_extension_cache()