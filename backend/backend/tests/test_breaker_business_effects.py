"""The breaker bypass is based on server-declared business effects, not labels."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.domain import RiskLevel, ToolMetadata
from aegisbank_api.main import create_app
from aegisbank_api.scheduler import DagScheduler


def open_breaker(client: TestClient, user_id: str = "demo-user") -> None:
    breaker = client.app.state.services.scheduler.breaker
    for _ in range(3):
        breaker.record_risk_level(user_id=user_id, level="red")
    assert breaker.is_open(user_id=user_id)


def test_read_capability_without_pure_query_declaration_is_conservative() -> None:
    tool = SimpleNamespace(metadata=ToolMetadata(
        name="new_green_tool", title="test", description="test",
        risk_level=RiskLevel.GREEN, permission="wealth:read",
    ))
    assert DagScheduler._tool_is_read_only(tool) is False


def test_open_breaker_blocks_profile_update_but_allows_wealth_query(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "effects.db")) as client:
        services = client.app.state.services
        with services.db.transaction() as conn:
            before = [tuple(row) for row in conn.execute("SELECT * FROM wealth_profile")]
        open_breaker(client)
        response = client.post("/api/agent/run", json={
            "instruction": "将我的风险偏好记录为R5",
            "tool_name": "assess_wealth_risk",
            "arguments": {"risk_preference": "R5"},
        })
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "blocked", response.json()
        with services.db.transaction() as conn:
            after = [tuple(row) for row in conn.execute("SELECT * FROM wealth_profile")]
        assert after == before
        query = client.post("/api/agent/run", json={
            "instruction": "查询理财产品", "tool_name": "list_wealth_products", "arguments": {},
        })
        assert query.status_code == 200, query.text
        assert query.json()["status"] == "completed", query.json()
        assert services.scheduler.breaker.is_open(user_id="demo-user")


@pytest.mark.parametrize("open_user,expected", [("demo-user", "completed"), ("user-b", "blocked")])
def test_due_task_execution_checks_the_executing_users_breaker(
    tmp_path: Path, open_user: str, expected: str,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "due-scope.db")) as client:
        grant = client.put("/api/permissions/run_due_tasks", params={"user_id": "user-b"},
                           json={"granted": True})
        assert grant.status_code == 200, grant.text
        open_breaker(client, open_user)
        response = client.post("/api/agent/run", json={
            "user_id": "user-b", "instruction": "执行我的到期任务",
            "tool_name": "run_due_tasks", "arguments": {},
        })
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected, response.json()
