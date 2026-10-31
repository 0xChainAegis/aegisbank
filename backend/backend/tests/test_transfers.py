"""转账形态场景（联系人簿 / 人名手机号转账 / AA 拆分）的 API 闭环测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "aegisbank-transfers.db"))


def run_agent(client: TestClient, instruction: str, **extra) -> dict:
    response = client.post("/api/agent/run", json={"instruction": instruction, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client: TestClient, action_id: str, *, token: str | None = None):
    payload: dict = {"approved": True}
    if token is not None:
        payload["reauth_token"] = token
    return client.post(f"/api/confirmations/{action_id}", json=payload)


def test_list_contacts_is_green_and_read_only(tmp_path):
    with make_client(tmp_path) as client:
        explicit = run_agent(
            client, "查看我的联系人", tool_name="list_contacts", arguments={}
        )
        assert explicit["status"] == "completed"
        assert explicit["risk_level"] == "green"
        data = explicit["results"][0]["data"]
        assert data["simulated"] is True
        assert data["count"] == 4
        assert {item["name"] for item in data["contacts"]} == {"妈妈", "老爸", "张三", "李四"}

        inferred = run_agent(client, "查看我的联系人")
        assert inferred["status"] == "completed"
        assert inferred["risk_level"] == "green"
        assert inferred["plan"]["steps"][0]["tool_name"] == "list_contacts"


def test_transfer_to_mother_by_alias_requires_confirmation_then_executes(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "给妈妈转500")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "yellow"
        assert body["confirmation"]["requires_reauth"] is False
        step = body["plan"]["steps"][0]
        assert step["tool_name"] == "transfer_to_contact"
        assert step["arguments"]["to_name"] == "妈妈"
        assert step["arguments"]["amount_cny"] == 500.0
        assert step["arguments"]["from_account"] == "ACC-1001"

        confirmed = confirm(client, body["confirmation"]["id"])
        assert confirmed.status_code == 200, confirmed.text
        executed = confirmed.json()
        assert executed["status"] == "completed"
        data = executed["results"][0]["data"]
        assert data["simulated"] is True
        assert data["transfer"]["simulated"] is True
        assert data["transfer"]["amount_cny"] == 500.0
        assert data["contact"]["account_id"] == "ACC-****01"

        overview = client.get("/api/banking/overview").json()
        assert overview["daily_transfer_total_cny"] == 500.0


def test_contact_transfer_cannot_override_the_bound_demo_debit_account(tmp_path):
    with make_client(tmp_path) as client:
        db = client.app.state.services.db
        with db.transaction() as conn:
            before = conn.execute("SELECT COUNT(*) FROM bank_transactions").fetchone()[0]
            pending_before = conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0]
        response = client.post(
            "/api/agent/run",
            json={
                "instruction": "给妈妈转500",
                "tool_name": "transfer_to_contact",
                "arguments": {
                    "from_account": "ACC-3003", "to_name": "妈妈", "amount_cny": 500,
                },
            },
        )
        assert response.status_code == 400
        with db.transaction() as conn:
            assert conn.execute("SELECT COUNT(*) FROM bank_transactions").fetchone()[0] == before
            pending_after = conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0]
            assert pending_after == pending_before


def test_transfer_by_name_and_phone_resolves_contact(tmp_path):
    with make_client(tmp_path) as client:
        by_name = run_agent(client, "给张三转账1000")
        assert by_name["status"] == "awaiting_confirmation"
        name_step = by_name["plan"]["steps"][0]
        assert name_step["tool_name"] == "transfer_to_contact"
        assert name_step["arguments"]["to_name"] == "张三"
        assert name_step["arguments"]["amount_cny"] == 1000.0

        by_phone = run_agent(client, "给13800138000转200")
        assert by_phone["status"] == "awaiting_confirmation"
        phone_step = by_phone["plan"]["steps"][0]
        assert phone_step["tool_name"] == "transfer_to_contact"
        assert phone_step["arguments"]["to_name"] == "张三"
        assert phone_step["arguments"]["to_phone"] == "13800138000"
        assert phone_step["arguments"]["amount_cny"] == 200.0


def test_unknown_contact_requires_clarification(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "给小明转100")
        assert body["status"] == "needs_clarification"
        assert body["plan"]["needs_clarification"] is True
        assert "小明" in body["reason"]
        assert body["plan"]["steps"] == []


def test_aa_split_generates_parallel_dag_and_executes_all(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "和妈妈、张三 AA 300")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "yellow"
        steps = body["plan"]["steps"]
        assert len(steps) >= 2
        assert all(step["tool_name"] == "transfer_to_contact" for step in steps)
        assert all(step["depends_on"] == [] for step in steps)
        amounts = [step["arguments"]["amount_cny"] for step in steps]
        assert amounts == [100.0, 100.0]
        people = len(steps) + 1
        assert amounts[0] * people == 300.0  # 总额 = 人均 × 人数
        assert sum(amounts) + amounts[0] == 300.0  # 用户垫付自己那一份
        assert any("金额校验" in item for item in body["plan"]["assumptions"])

        confirmed = confirm(client, body["confirmation"]["id"])
        assert confirmed.status_code == 200, confirmed.text
        executed = confirmed.json()
        assert executed["status"] == "completed"
        assert len(executed["results"]) == len(steps)
        transferred = sum(item["data"]["transfer"]["amount_cny"] for item in executed["results"])
        assert transferred == 200.0
        overview = client.get("/api/banking/overview").json()
        assert overview["daily_transfer_total_cny"] == 200.0

        unresolved = run_agent(client, "和妈妈、老王 AA 300")
        assert unresolved["status"] == "needs_clarification"
        assert "老王" in unresolved["reason"]


def test_aa_total_over_daily_limit_escalates_to_red(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "和妈妈、张三 AA 3000")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "red"
        assert body["confirmation"]["requires_reauth"] is True
        assert any("3000" in reason for reason in body["risk"]["reasons"])


def test_single_transfer_over_5000_is_red_and_needs_reauth(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "给妈妈转6000")
        assert body["status"] == "awaiting_confirmation"
        assert body["risk_level"] == "red"
        assert body["confirmation"]["requires_reauth"] is True
        assert any("5000" in reason for reason in body["risk"]["reasons"])

        wrong = confirm(client, body["confirmation"]["id"], token="000000")
        assert wrong.status_code == 403

        good = confirm(client, body["confirmation"]["id"], token="246810")
        assert good.status_code == 200, good.text
        executed = good.json()
        assert executed["status"] == "completed"
        assert executed["results"][0]["data"]["transfer"]["amount_cny"] == 6000.0


def test_revoked_permission_blocks_contact_transfer(tmp_path):
    with make_client(tmp_path) as client:
        revoked = client.put(
            "/api/permissions/transfer_to_contact", json={"granted": False}
        )
        assert revoked.status_code == 200
        body = run_agent(client, "给妈妈转500")
        assert body["status"] == "blocked"
        assert "未授权" in body["reason"]
        assert "results" not in body


def test_contacts_route_returns_masked_contacts(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/api/contacts")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 4
        assert body["simulated"] is True
        by_name = {item["name"]: item for item in body["contacts"]}
        assert by_name["妈妈"]["birthday"] == "1990-11-18"
        assert by_name["妈妈"]["account_id"] == "ACC-****01"
        assert by_name["张三"]["phone"] == "138****8000"
        assert all("****" in item["account_id"] for item in body["contacts"])


def test_add_contact_then_ambiguous_name_requires_clarification(tmp_path):
    with make_client(tmp_path) as client:
        created = run_agent(
            client,
            "新增联系人张三",
            tool_name="add_contact",
            arguments={
                "name": "张三",
                "phone": "13700137000",
                "account_id": "ACC-9010",
                "alias": "三哥",
                "relation": "friend",
            },
        )
        assert created["status"] == "awaiting_confirmation"
        assert created["risk_level"] == "yellow"
        confirmed = confirm(client, created["confirmation"]["id"])
        assert confirmed.status_code == 200, confirmed.text
        created_contact = confirmed.json()["results"][0]["data"]["contact"]
        assert created_contact["name"] == "张三"

        ambiguous = run_agent(client, "给张三转100")
        assert ambiguous["status"] == "needs_clarification"
        assert "多个" in ambiguous["reason"]

        by_alias = run_agent(client, "给三哥转100")
        assert by_alias["status"] == "awaiting_confirmation"
        alias_step = by_alias["plan"]["steps"][0]
        assert alias_step["arguments"]["to_name"] == "张三"
        assert alias_step["arguments"]["to_phone"] == "13700137000"

        invalid = client.post(
            "/api/agent/run",
            json={
                "instruction": "新增联系人",
                "tool_name": "add_contact",
                "arguments": {"name": "王五", "phone": "123", "account_id": "ACC-9011"},
            },
        )
        assert invalid.status_code == 400

def test_spoken_kin_aliases_resolve_seeded_mother(tmp_path):
    with make_client(tmp_path) as client:
        for instruction in ("给我妈转200", "给我老妈转200", "给我母亲转200"):
            body = run_agent(client, instruction)
            assert body["status"] == "awaiting_confirmation", (instruction, body)
            step = body["plan"]["steps"][0]
            assert step["tool_name"] == "transfer_to_contact"
            assert step["arguments"]["to_name"] == "妈妈"
            assert step["arguments"]["amount_cny"] == 200.0


def test_unknown_kin_alias_is_not_guessed(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "给我舅舅转200")
        assert body["status"] == "needs_clarification"
        assert "舅舅" in (body.get("reason") or "")
        assert body["plan"]["steps"] == []


def test_missing_payee_is_clarified_without_treating_me_as_contact(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "帮我转200元")
        assert body["status"] == "needs_clarification", body
        assert body["plan"]["steps"] == []
        assert "收款人" in (body.get("reason") or "")
        assert "未找到" not in (body.get("reason") or "")


def test_assisted_transfer_with_colloquial_amount_resolves_contact(tmp_path):
    with make_client(tmp_path) as client:
        body = run_agent(client, "帮我给张三转个两百")
        assert body["status"] == "awaiting_confirmation", body
        step = body["plan"]["steps"][0]
        assert step["tool_name"] == "transfer_to_contact"
        assert step["arguments"]["to_name"] == "张三"
        assert step["arguments"]["amount_cny"] == 200.0
