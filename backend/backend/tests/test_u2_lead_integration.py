"""Lead integration acceptance for the U2 minimal multi-turn transfer flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(database_path=tmp_path / "aegisbank-u2.db"))


def post(client: TestClient, instruction: str, **extra):
    return client.post("/api/agent/run", json={"instruction": instruction, **extra})


def start_transfer(client: TestClient) -> dict:
    response = post(client, "给妈妈转钱")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["reason_code"] == "missing_amount"
    assert body["draft"]["status"] == "awaiting_amount"
    assert body["draft"]["version"] == 1
    assert "amount" in body["draft"]["missing_slots"]
    assert body["session_id"] == body["draft"]["session_id"]
    return body


def fill(
    client: TestClient,
    draft: dict,
    session_id: str,
    answer: str = "五百",
    headers: dict[str, str] | None = None,
):
    return client.post(
        "/api/agent/run",
        json={
            "instruction": answer,
            "session_id": session_id,
            "draft_id": draft["draft_id"],
            "draft_version": draft["version"],
        },
        headers=headers or {},
    )


def amend(
    client: TestClient, draft: dict, session_id: str, answer: str
):
    return client.post(
        "/api/agent/run",
        json={
            "instruction": answer,
            "session_id": session_id,
            "draft_id": draft["draft_id"],
            "draft_version": draft["version"],
        },
    )


def table_count(app, sql: str, params: tuple = ()) -> int:
    with app.state.services.db.transaction() as conn:
        return int(conn.execute(sql, params).fetchone()["n"])


def test_u2_main_chain_amount_fill_revision_reconfirmation_and_history(tmp_path):
    with make_client(tmp_path) as client:
        app = client.app
        first = start_transfer(client)

        filled = fill(client, first["draft"], first["session_id"]).json()
        assert filled["status"] == "awaiting_confirmation"
        assert filled["draft"]["version"] == 2
        assert filled["plan"]["steps"][0]["arguments"]["amount_cny"] == 500.0
        old_action = filled["confirmation"]["id"]
        old_hash = filled["plan"]["plan_hash"]
        assert old_hash

        amended = amend(
            client, filled["draft"], filled["session_id"], "不是500，改成300"
        )
        assert amended.status_code == 200, amended.text
        revised = amended.json()
        assert revised["status"] == "awaiting_confirmation"
        assert revised["draft"]["version"] == 3
        assert revised["plan"]["steps"][0]["arguments"]["amount_cny"] == 300.0
        assert revised["plan"]["plan_hash"] != old_hash
        new_action = revised["confirmation"]["id"]
        assert new_action != old_action

        old = client.post(
            f"/api/confirmations/{old_action}",
            json={"approved": True, "user_id": "demo-user"},
        )
        assert old.status_code == 409, old.text
        assert old.json()["detail"]["code"] == "draft_version_conflict"
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 0

        confirmed = client.post(
            f"/api/confirmations/{new_action}",
            json={
                "approved": True,
                "user_id": "demo-user",
                "session_id": revised["session_id"],
                "draft_id": revised["draft"]["draft_id"],
                "draft_version": revised["draft"]["version"],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        completed = confirmed.json()
        assert completed["status"] == "completed"
        assert completed["draft"]["status"] == "completed"
        assert completed["results"][0]["data"]["transfer"]["amount_cny"] == 300.0

        with app.state.services.db.transaction() as conn:
            rows = conn.execute(
                "SELECT amount_cents FROM bank_transactions WHERE category='transfer'"
            ).fetchall()
        assert [row["amount_cents"] for row in rows] == [-30_000]
        overview = client.get("/api/banking/overview").json()
        assert overview["daily_transfer_total_cny"] == 300.0

        history = post(client, "我刚才转了多少").json()
        assert history["status"] == "completed"
        assert "draft" not in history
        recent = history["results"][0]
        assert recent["tool_name"] == "query_recent_transfer"
        assert recent["data"]["found"] is True
        assert recent["data"]["amount_cny"] == 300.0
        assert recent["data"]["contact_name"] == "妈妈"
        assert recent["data"]["transaction_id"]
        assert recent["data"]["executed_at"]
        assert recent["data"]["simulated"] is True

        who = post(client, "我刚才转给谁").json()
        assert who["status"] == "completed"
        assert who["results"][0]["data"]["contact_name"] == "妈妈"
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 1


def test_u2_rejects_smuggled_recipient_actions_conditions_and_stale_versions(tmp_path):
    with make_client(tmp_path) as client:
        app = client.app
        first = start_transfer(client)

        for answer in ("给爸爸转300", "500然后转给爸爸100", "改成300并查余额"):
            response = fill(client, first["draft"], first["session_id"], answer=answer)
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "unsupported_amendment"
        stale = fill(
            client, {**first["draft"], "version": 99}, first["session_id"]
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "draft_version_conflict"
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 0
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 0

        filled = fill(client, first["draft"], first["session_id"]).json()
        assert filled["status"] == "awaiting_confirmation"
        for answer in ("500然后转给爸爸100", "改成300并查余额"):
            response = amend(
                client, filled["draft"], filled["session_id"], answer=answer
            )
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "unsupported_amendment"
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM pending_actions WHERE status='pending'"
        ) == 1
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 0


def test_u2_session_draft_are_user_scoped_and_expire(tmp_path):
    with make_client(tmp_path) as client:
        app = client.app
        first = start_transfer(client)
        other = post(
            client,
            "五百",
            user_id="user-b",
            session_id=first["session_id"],
            draft_id=first["draft"]["draft_id"],
            draft_version=first["draft"]["version"],
        )
        assert other.status_code == 409, other.text
        assert other.json()["detail"]["code"] == "context_expired"

        with app.state.services.db.transaction() as conn:
            conn.execute(
                "UPDATE agent_drafts SET expires_at='2000-01-01T00:00:00+00:00' "
                "WHERE draft_id=?",
                (first["draft"]["draft_id"],),
            )
        expired = fill(client, first["draft"], first["session_id"])
        assert expired.status_code == 409, expired.text
        assert expired.json()["detail"]["code"] == "context_expired"
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 0


def test_u2_idempotent_fill_and_amendment_never_duplicate_pending_or_payment(tmp_path):
    with make_client(tmp_path) as client:
        app = client.app
        first = start_transfer(client)
        headers = {"Idempotency-Key": "u2-fill-idem"}
        one = fill(
            client, first["draft"], first["session_id"], headers=headers
        )
        two = fill(
            client, first["draft"], first["session_id"], headers=headers
        )
        assert one.status_code == 200 and two.status_code == 200
        assert one.json()["run_id"] == two.json()["run_id"]
        assert one.json()["confirmation"]["id"] == two.json()["confirmation"]["id"]
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 1

        filled = one.json()
        amend_headers = {"Idempotency-Key": "u2-amend-idem"}
        a1 = client.post(
            "/api/agent/run",
            json={
                "instruction": "不是500，改成300",
                "session_id": first["session_id"],
                "draft_id": filled["draft"]["draft_id"],
                "draft_version": filled["draft"]["version"],
            },
            headers=amend_headers,
        )
        a2 = client.post(
            "/api/agent/run",
            json={
                "instruction": "不是500，改成300",
                "session_id": first["session_id"],
                "draft_id": filled["draft"]["draft_id"],
                "draft_version": filled["draft"]["version"],
            },
            headers=amend_headers,
        )
        assert a1.status_code == 200 and a2.status_code == 200, (a1.text, a2.text)
        assert a1.json()["run_id"] == a2.json()["run_id"]
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM pending_actions WHERE status='pending'"
        ) == 1
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 2

        revised = a1.json()
        confirm_key = {"Idempotency-Key": "u2-confirm-idem"}
        c1 = client.post(
            f"/api/confirmations/{revised['confirmation']['id']}",
            json={
                "approved": True,
                "user_id": "demo-user",
                "session_id": first["session_id"],
                "draft_id": revised["draft"]["draft_id"],
                "draft_version": revised["draft"]["version"],
            },
            headers=confirm_key,
        )
        c2 = client.post(
            f"/api/confirmations/{revised['confirmation']['id']}",
            json={
                "approved": True,
                "user_id": "demo-user",
                "session_id": first["session_id"],
                "draft_id": revised["draft"]["draft_id"],
                "draft_version": revised["draft"]["version"],
            },
            headers=confirm_key,
        )
        assert c1.status_code == 200 and c2.status_code == 200, (c1.text, c2.text)
        assert c1.json()["status"] == "completed"
        assert c2.json()["run_id"] == c1.json()["run_id"]
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 1


def test_u2_history_reads_only_current_users_completed_mock_transfer(tmp_path):
    with make_client(tmp_path) as client:
        app = client.app
        first = start_transfer(client)
        filled = fill(client, first["draft"], first["session_id"]).json()
        confirmed = client.post(
            f"/api/confirmations/{filled['confirmation']['id']}",
            json={"approved": True, "user_id": "demo-user"},
        )
        assert confirmed.status_code == 200, confirmed.text

        granted = client.put(
            "/api/permissions/query_recent_transfer?user_id=user-b",
            json={"granted": True},
            headers={"X-Aegis-Role": "operator"},
        )
        assert granted.status_code == 200, granted.text
        other = post(client, "我刚才转了多少", user_id="user-b").json()
        assert other["status"] == "completed"
        assert other["results"][0]["data"]["found"] is False
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 1
def test_u2_confirmation_rejects_stale_draft_version_without_execution(tmp_path):
    with make_client(tmp_path) as client:
        app = client.app
        first = start_transfer(client)
        filled = fill(client, first["draft"], first["session_id"]).json()
        action_id = filled["confirmation"]["id"]
        stale = client.post(
            f"/api/confirmations/{action_id}",
            json={
                "approved": True,
                "user_id": "demo-user",
                "session_id": first["session_id"],
                "draft_id": filled["draft"]["draft_id"],
                "draft_version": 1,
            },
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "draft_version_conflict"
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 0
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM pending_actions WHERE status='pending'"
        ) == 1

        good = client.post(
            f"/api/confirmations/{action_id}",
            json={
                "approved": True,
                "user_id": "demo-user",
                "session_id": first["session_id"],
                "draft_id": filled["draft"]["draft_id"],
                "draft_version": filled["draft"]["version"],
            },
        )
        assert good.status_code == 200, good.text
        assert good.json()["status"] == "completed"
        assert table_count(
            app, "SELECT COUNT(*) AS n FROM bank_transactions WHERE category='transfer'"
        ) == 1