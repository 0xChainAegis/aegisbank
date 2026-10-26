"""Stage 2A multi-role matrix and revocation tests.

Covers the role endpoints, the role gate in front of tool execution, the
separation between ``ops:manage`` and ``permission:manage``, and the audited
revocation flow: revoke -> replay blocked -> ``role_revocation`` audit entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app

USER = {"X-Aegis-Role": "user"}
OPERATOR = {"X-Aegis-Role": "operator"}
AUDITOR = {"X-Aegis-Role": "auditor"}

QUERY_BILL = {
    "instruction": "查询我的本月账单",
    "tool_name": "query_bill",
    "arguments": {"account_id": "ACC-1001"},
}


def make_client(tmp_path: Path, name: str = "authz.db") -> TestClient:
    return TestClient(create_app(database_path=tmp_path / name))


def audit_entries(
    client: TestClient, headers: dict[str, str] = AUDITOR, limit: int = 200
) -> list[dict[str, Any]]:
    response = client.get("/api/audit", params={"limit": limit}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def test_roles_endpoint_exposes_matrix_labels_and_capabilities(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/authz/roles", headers=AUDITOR)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["current_role"] == "auditor"
        assert body["count"] == 3
        roles = {item["role"]: item for item in body["roles"]}
        assert set(roles) == {"user", "operator", "auditor"}

        for item in roles.values():
            assert item["label"]
            assert item["capabilities"] == sorted(item["capabilities"])
            assert set(item["capability_labels"]) == set(item["capabilities"])

        assert "ops:manage" not in roles["user"]["capabilities"]
        assert "tool:execute" not in roles["operator"]["capabilities"]
        assert roles["auditor"]["capabilities"] == ["audit:read", "trust:inspect"]
        assert roles["user"]["capability_labels"]["tool:execute"]


def test_me_endpoint_resolves_role_and_rejects_unknown_role(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        me = client.get("/api/authz/me", headers=OPERATOR)
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["role"] == "operator"
        assert "ops:manage" in body["capabilities"]
        assert body["capability_labels"]["ops:manage"]

        # 缺省角色来自配置（user），未知角色拒绝
        default = client.get("/api/authz/me")
        assert default.json()["role"] == "user"
        unknown = client.get("/api/authz/me", headers={"X-Aegis-Role": "intruder"})
        assert unknown.status_code == 403


def test_operator_cannot_execute_tools(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/agent/run", json=QUERY_BILL, headers=OPERATOR)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "blocked"
        assert "operator" in body["reason"]
        assert "工具执行" in body["reason"]
        assert body["plan"]["steps"][0]["tool_name"] == "query_bill"
        events = [entry["event"] for entry in audit_entries(client)]
        assert "gateway_blocked" in events
        assert "tool_executed" not in events


def test_auditor_cannot_manage_permissions_or_revoke(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        denied = client.put(
            "/api/permissions/query_bill", json={"granted": False}, headers=AUDITOR
        )
        assert denied.status_code == 403
        assert "permission:manage" in denied.json()["detail"]

        revoke = client.post("/api/authz/revoke/query_bill", headers=AUDITOR)
        assert revoke.status_code == 403
        assert "permission:manage" in revoke.json()["detail"]

        # 审计员仍可读审计，但不能修改
        assert client.get("/api/audit", headers=AUDITOR).status_code == 200
        # 撤权未生效
        assert client.get("/api/tools").json()["tools"]


def test_user_cannot_reset_circuit_breaker(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/trust/circuit-breaker/reset", headers=USER)
        assert response.status_code == 403
        assert "ops:manage" in response.json()["detail"]
        # 用户保留只读信任检查能力
        status = client.get("/api/trust/circuit-breaker", headers=USER)
        assert status.status_code == 200
        assert status.json()["open"] is False


def test_operator_can_reset_circuit_breaker(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/trust/circuit-breaker/reset", headers=OPERATOR)
        assert response.status_code == 200, response.text
        assert response.json()["open"] is False
        events = [entry["event"] for entry in audit_entries(client)]
        assert "circuit_breaker_reset" in events


def test_revocation_blocks_replay_and_is_audited(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first = client.post("/api/agent/run", json=QUERY_BILL, headers=USER)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "completed"

        revoked = client.post("/api/authz/revoke/query_bill", headers=USER)
        assert revoked.status_code == 200, revoked.text
        body = revoked.json()
        assert body["tool_name"] == "query_bill"
        assert body["granted"] is False
        assert body["revoked"] is True
        assert body["effective"] == "blocked"

        replay = client.post("/api/agent/run", json=QUERY_BILL, headers=USER)
        assert replay.status_code == 200, replay.text
        assert replay.json()["status"] == "blocked"
        assert "未授权" in replay.json()["reason"]

        entries = audit_entries(client)
        revocation = next(
            entry for entry in entries if entry["event"] == "role_revocation"
        )
        assert revocation["tool_name"] == "query_bill"
        assert revocation["arguments"]["tool_name"] == "query_bill"
        assert revocation["arguments"]["role"] == "user"
        assert revocation["result"]["granted"] is False
        assert revocation["confirmation_state"] == "permission_change"
        assert client.get("/api/audit/verify", headers=AUDITOR).json()["valid"] is True

        # 恢复授权后立即可以再次执行，撤权不是永久的
        restored = client.put(
            "/api/permissions/query_bill", json={"granted": True}, headers=USER
        )
        assert restored.status_code == 200
        recovered = client.post("/api/agent/run", json=QUERY_BILL, headers=USER)
        assert recovered.json()["status"] == "completed"


def test_revoke_unknown_tool_returns_404_without_audit(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/authz/revoke/drop_table", headers=USER)
        assert response.status_code == 404
        assert "工具不存在" in response.json()["detail"]
        assert all(
            entry["event"] != "role_revocation" for entry in audit_entries(client)
        )


def test_audit_policy_is_read_only_for_every_role(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for headers in (USER, OPERATOR, AUDITOR):
            response = client.get("/api/authz/audit/policy", headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["policy"] == "audit_read_only"
            assert body["read_only"] is True
            assert body["writable_by_roles"] == []
            assert set(body["read_roles"]) == {"user", "operator", "auditor"}
            assert body["integrity"] == "sha256-hash-chain"