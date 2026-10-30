"""Independent U4 delivery regression for the U2 conversation/draft flow.

These tests deliberately inspect the persisted business state (``agent_drafts``,
``pending_actions`` and ``bank_transactions``) as well as the public response.
They are independent from the U2 implementation tests and do not weaken or
replace any existing assertion.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app

TRANSFER_CATEGORY = "transfer"


def make_app(tmp_path):
    return create_app(database_path=tmp_path / "aegisbank-u4.db")


def post_run(client: TestClient, instruction: str, **extra: Any):
    return client.post(
        "/api/agent/run", json={"instruction": instruction, **extra}
    )


def start_transfer(
    client: TestClient,
    *,
    session_id: str | None = None,
    user_id: str = "demo-user",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"instruction": "给妈妈转钱", "user_id": user_id}
    if session_id is not None:
        payload["session_id"] = session_id
    response = post_run(client, payload.pop("instruction"), **payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["reason_code"] == "missing_amount"
    assert body["draft"]["status"] == "awaiting_amount"
    assert body["draft"]["version"] == 1
    assert body["session_id"] == body["draft"]["session_id"]
    assert "amount" in body["draft"]["missing_slots"]
    return body


def draft_payload(
    body: dict[str, Any],
    instruction: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "instruction": instruction,
        "session_id": body["session_id"],
        "draft_id": body["draft"]["draft_id"],
        "draft_version": body["draft"]["version"],
    }
    if user_id is not None:
        payload["user_id"] = user_id
    return payload


def confirmation_payload(
    body: dict[str, Any],
    *,
    user_id: str = "demo-user",
    approved: bool = True,
) -> dict[str, Any]:
    return {
        "approved": approved,
        "user_id": user_id,
        "session_id": body["session_id"],
        "draft_id": body["draft"]["draft_id"],
        "draft_version": body["draft"]["version"],
    }


def fetch_row(app, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with app.state.services.db.transaction() as conn:
        row = conn.execute(sql, params).fetchone()
    return None if row is None else dict(row)


def fetch_rows(app, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with app.state.services.db.transaction() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def table_count(app, sql: str, params: tuple[Any, ...] = ()) -> int:
    with app.state.services.db.transaction() as conn:
        row = conn.execute(sql, params).fetchone()
    assert row is not None
    return int(row["n"])


def assert_draft_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, dict), response.text
    assert detail.get("code") == code, response.text


def seed_terminal_draft(
    app,
    *,
    draft_id: str,
    user_id: str,
    updated_at: str,
    expires_at: str = "2999-01-01T00:00:00+00:00",
) -> None:
    with app.state.services.db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO agent_drafts
            (draft_id, session_id, user_id, version, status, reason_code,
             instruction, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, 1, 'completed', 'completed', 'seeded terminal draft',
                    ?, ?, ?)
            """,
            (
                draft_id,
                f"sess_{draft_id}",
                user_id,
                updated_at,
                updated_at,
                expires_at,
            ),
        )


def test_u4_real_delivery_chain_is_idempotent_and_audited(tmp_path):
    """Full chain: fill -> amend -> old confirmation -> one real -300 payment.

    It also proves that idempotent replays do not allocate extra pending actions,
    that the completed draft cannot be edited, and that recent-history reads the
    concrete bank row for the current user while a second user sees no record.
    """

    with TestClient(make_app(tmp_path)) as client:
        app = client.app
        initial = start_transfer(client)
        session_id = initial["session_id"]
        draft_id = initial["draft"]["draft_id"]

        initial_row = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert initial_row is not None
        assert initial_row["user_id"] == "demo-user"
        assert initial_row["session_id"] == session_id
        assert initial_row["version"] == 1
        assert initial_row["status"] == "awaiting_amount"
        assert initial_row["pending_action_id"] is None
        assert initial_row["missing_slots_json"] == '["amount"]'
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 0
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )

        fill_key = {"Idempotency-Key": "u4-fill-idem"}
        fill_payload = draft_payload(initial, "五百")
        fill_one = client.post(
            "/api/agent/run", json=fill_payload, headers=fill_key
        )
        fill_two = client.post(
            "/api/agent/run", json=fill_payload, headers=fill_key
        )
        assert fill_one.status_code == 200, fill_one.text
        assert fill_two.status_code == 200, fill_two.text
        filled = fill_one.json()
        assert fill_two.json() == filled
        assert filled["status"] == "awaiting_confirmation"
        assert filled["draft"]["version"] == 2
        assert filled["draft"]["status"] == "awaiting_confirmation"
        assert filled["draft"]["changed_fields"] == ["amount"]
        assert filled["draft"]["amount_cny"] == 500.0
        assert filled["draft"]["missing_slots"] == []
        assert filled["plan"]["steps"][0]["arguments"]["amount_cny"] == 500.0
        old_action = filled["confirmation"]["id"]
        old_hash = filled["plan"]["plan_hash"]
        assert old_hash
        assert filled["draft"]["pending_action_id"] == old_action
        assert filled["draft"]["plan_hash"] == old_hash

        filled_row = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert filled_row is not None
        assert filled_row["version"] == 2
        assert filled_row["status"] == "awaiting_confirmation"
        assert filled_row["pending_action_id"] == old_action
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 1
        old_pending = fetch_row(
            app, "SELECT * FROM pending_actions WHERE id = ?", (old_action,)
        )
        assert old_pending is not None
        assert old_pending["status"] == "pending"
        assert old_pending["result_json"] == ""

        amend_key = {"Idempotency-Key": "u4-amend-idem"}
        amend_payload = draft_payload(
            filled, "不是500，改成300"
        )
        amend_one = client.post(
            "/api/agent/run", json=amend_payload, headers=amend_key
        )
        amend_two = client.post(
            "/api/agent/run", json=amend_payload, headers=amend_key
        )
        assert amend_one.status_code == 200, amend_one.text
        assert amend_two.status_code == 200, amend_two.text
        revised = amend_one.json()
        assert amend_two.json() == revised
        assert revised["status"] == "awaiting_confirmation"
        assert revised["draft"]["version"] == 3
        assert revised["draft"]["status"] == "awaiting_confirmation"
        assert revised["draft"]["changed_fields"] == ["amount"]
        assert revised["draft"]["amount_cny"] == 300.0
        assert revised["plan"]["steps"][0]["arguments"]["amount_cny"] == 300.0
        new_action = revised["confirmation"]["id"]
        new_hash = revised["plan"]["plan_hash"]
        assert new_action != old_action
        assert new_hash != old_hash
        assert revised["draft"]["pending_action_id"] == new_action
        assert revised["draft"]["plan_hash"] == new_hash

        # Replaying the already-committed fill request must not resurrect v2 or
        # rewrite the latest draft.  It returns the cached v2 response as a
        # transport-level replay only.
        stale_fill_replay = client.post(
            "/api/agent/run", json=fill_payload, headers=fill_key
        )
        assert stale_fill_replay.status_code == 200, stale_fill_replay.text
        assert stale_fill_replay.json() == filled
        current_row = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert current_row is not None
        assert current_row["version"] == 3
        assert current_row["pending_action_id"] == new_action

        old_after_amend = fetch_row(
            app, "SELECT * FROM pending_actions WHERE id = ?", (old_action,)
        )
        new_after_amend = fetch_row(
            app, "SELECT * FROM pending_actions WHERE id = ?", (new_action,)
        )
        assert old_after_amend is not None
        assert old_after_amend["status"] == "superseded"
        assert old_after_amend["resolved_at"] is not None
        assert old_after_amend["result_json"] == ""
        assert new_after_amend is not None
        assert new_after_amend["status"] == "pending"
        assert new_after_amend["resolved_at"] is None
        assert new_after_amend["result_json"] == ""
        assert (
            table_count(
                app, "SELECT COUNT(*) AS n FROM pending_actions WHERE status='pending'"
            )
            == 1
        )
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )

        # The superseded confirmation cannot execute even through the legacy
        # request shape that omits all draft fields.
        stale_confirm = client.post(
            f"/api/confirmations/{old_action}",
            json={"approved": True, "user_id": "demo-user"},
        )
        assert_draft_error(stale_confirm, 409, "draft_version_conflict")
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )

        # A stale version of the *current* action is also rejected before any
        # business write.
        stale_current_payload = confirmation_payload(revised)
        stale_current_payload["draft_version"] = 2
        stale_current = client.post(
            f"/api/confirmations/{new_action}", json=stale_current_payload
        )
        assert_draft_error(stale_current, 409, "draft_version_conflict")
        still_pending = fetch_row(
            app, "SELECT * FROM pending_actions WHERE id = ?", (new_action,)
        )
        assert still_pending is not None and still_pending["status"] == "pending"
        assert still_pending["result_json"] == ""
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )

        confirm_key = {"Idempotency-Key": "u4-confirm-idem"}
        confirm_request = confirmation_payload(revised)
        confirm_one = client.post(
            f"/api/confirmations/{new_action}",
            json=confirm_request,
            headers=confirm_key,
        )
        confirm_two = client.post(
            f"/api/confirmations/{new_action}",
            json=confirm_request,
            headers=confirm_key,
        )
        assert confirm_one.status_code == 200, confirm_one.text
        assert confirm_two.status_code == 200, confirm_two.text
        completed = confirm_one.json()
        assert confirm_two.json() == completed
        assert completed["status"] == "completed"
        assert completed["draft"]["status"] == "completed"
        assert completed["draft"]["version"] == 4
        assert completed["draft"]["pending_action_id"] == new_action
        assert (
            completed["results"][0]["data"]["transfer"]["amount_cny"] == 300.0
        )
        paid_transaction_id = completed["results"][0]["data"]["transfer"][
            "transaction_id"
        ]

        # A terminal draft cannot be amended or replayed into another payment.
        after_complete_edit = client.post(
            "/api/agent/run", json=draft_payload(completed, "改成100")
        )
        assert_draft_error(after_complete_edit, 409, "context_expired")
        completed_row = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert completed_row is not None
        assert completed_row["version"] == 4
        assert completed_row["status"] == "completed"
        assert completed_row["reason_code"] == "completed"
        assert completed_row["pending_action_id"] == new_action

        transfer_rows = fetch_rows(
            app,
            """
            SELECT transaction_id, user_id, category, amount_cents, status,
                   merchant, note, occurred_at
            FROM bank_transactions
            WHERE category = ?
            """,
            (TRANSFER_CATEGORY,),
        )
        assert len(transfer_rows) == 1
        transfer = transfer_rows[0]
        assert transfer["transaction_id"] == paid_transaction_id
        assert transfer["user_id"] == "demo-user"
        assert transfer["category"] == "transfer"
        assert transfer["amount_cents"] == -30_000
        assert transfer["status"] == "posted"

        pending_rows = fetch_rows(
            app, "SELECT * FROM pending_actions ORDER BY created_at, id"
        )
        assert len(pending_rows) == 2
        pending_by_id = {row["id"]: row for row in pending_rows}
        assert pending_by_id[old_action]["status"] == "superseded"
        assert pending_by_id[old_action]["result_json"] == ""
        assert pending_by_id[new_action]["status"] == "completed"
        assert pending_by_id[new_action]["result_json"] != ""
        stored_confirmation = json.loads(
            pending_by_id[new_action]["result_json"]
        )
        assert stored_confirmation["status"] == "completed"
        assert (
            stored_confirmation["results"][0]["data"]["transfer"][
                "transaction_id"
            ]
            == paid_transaction_id
        )

        overview = client.get("/api/banking/overview").json()
        assert overview["daily_transfer_total_cny"] == 300.0

        history_response = post_run(client, "我刚才转了多少")
        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert history["status"] == "completed"
        assert "draft" not in history
        recent = history["results"][0]
        assert recent["tool_name"] == "query_recent_transfer"
        recent_data = recent["data"]
        assert recent_data["found"] is True
        assert recent_data["transaction_id"] == transfer["transaction_id"]
        assert recent_data["amount_cny"] == 300.0
        assert recent_data["contact_name"] == "妈妈"
        assert recent_data["executed_at"] == transfer["occurred_at"]
        assert recent_data["source"] == "mock_bank_core.bank_transactions"
        assert recent_data["simulated"] is True

        granted = client.put(
            "/api/permissions/query_recent_transfer?user_id=user-b",
            json={"granted": True},
            headers={"X-Aegis-Role": "operator"},
        )
        assert granted.status_code == 200, granted.text
        other_history_response = post_run(
            client, "我刚才转了多少", user_id="user-b"
        )
        assert other_history_response.status_code == 200, other_history_response.text
        other_history = other_history_response.json()
        assert other_history["status"] == "completed"
        other_data = other_history["results"][0]["data"]
        assert other_data["found"] is False
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE user_id='user-b'",
            )
            == 0
        )

        # Both history queries are read-only: the one real transaction, one
        # completed draft and two terminal pending actions remain untouched.
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 1
        )
        assert table_count(app, "SELECT COUNT(*) AS n FROM agent_drafts") == 1
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 2

        events = [
            item["event"]
            for item in app.state.services.audit.list(limit=10_000)
        ]
        for expected_event in (
            "conversation_draft_created",
            "conversation_draft_followup_reserved",
            "conversation_draft_amount_filled",
            "conversation_draft_amount_amended",
            "confirmation_superseded",
            "confirmation_approved",
            "conversation_draft_closed",
        ):
            assert expected_event in events
        assert events.count("conversation_draft_created") == 1
        assert events.count("conversation_draft_followup_reserved") == 2
        assert events.count("conversation_draft_amount_filled") == 1
        assert events.count("conversation_draft_amount_amended") == 1
        assert events.count("confirmation_superseded") == 1
        assert events.count("confirmation_approved") == 1
        assert events.count("conversation_draft_closed") == 1

        verify = client.get("/api/audit/verify")
        assert verify.status_code == 200, verify.text
        verification = verify.json()
        assert verification["valid"] is True
        assert verification["checked"] == len(events)


def test_u4_invalid_fill_and_amendment_preserve_pending_state_and_zero_writes(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        app = client.app
        started = start_transfer(client)
        draft_id = started["draft"]["draft_id"]
        audit_before = table_count(app, "SELECT COUNT(*) AS n FROM audit_log")

        for answer in ("给爸爸转300", "500然后转给爸爸100"):
            response = client.post(
                "/api/agent/run", json=draft_payload(started, answer)
            )
            assert_draft_error(response, 409, "unsupported_amendment")
        invalid_amount = client.post(
            "/api/agent/run", json=draft_payload(started, "零")
        )
        assert_draft_error(invalid_amount, 422, "missing_amount")

        unchanged = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert unchanged is not None
        assert unchanged["version"] == 1
        assert unchanged["status"] == "awaiting_amount"
        assert unchanged["pending_action_id"] is None
        assert unchanged["plan_hash"] == ""
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 0
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )
        assert table_count(app, "SELECT COUNT(*) AS n FROM audit_log") == audit_before

        filled_response = client.post(
            "/api/agent/run", json=draft_payload(started, "五百")
        )
        assert filled_response.status_code == 200, filled_response.text
        filled = filled_response.json()
        old_action = filled["confirmation"]["id"]
        old_hash = filled["plan"]["plan_hash"]
        audit_after_fill = table_count(app, "SELECT COUNT(*) AS n FROM audit_log")
        assert audit_after_fill > audit_before

        for answer in ("不是400，改成300", "改成300并查余额"):
            response = client.post(
                "/api/agent/run", json=draft_payload(filled, answer)
            )
            assert_draft_error(response, 409, "unsupported_amendment")

        preserved = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert preserved is not None
        assert preserved["version"] == 2
        assert preserved["status"] == "awaiting_confirmation"
        assert preserved["reason_code"] == "awaiting_confirmation"
        assert preserved["pending_action_id"] == old_action
        assert preserved["plan_hash"] == old_hash
        pending = fetch_row(
            app, "SELECT * FROM pending_actions WHERE id = ?", (old_action,)
        )
        assert pending is not None
        assert pending["status"] == "pending"
        assert pending["result_json"] == ""
        assert (
            table_count(
                app, "SELECT COUNT(*) AS n FROM pending_actions WHERE status='pending'"
            )
            == 1
        )
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )
        assert table_count(app, "SELECT COUNT(*) AS n FROM audit_log") == audit_after_fill


def test_u4_cross_user_draft_and_confirmation_are_invisible_and_write_nothing(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        app = client.app
        started = start_transfer(client)
        filled_response = client.post(
            "/api/agent/run", json=draft_payload(started, "五百")
        )
        assert filled_response.status_code == 200, filled_response.text
        filled = filled_response.json()
        draft_id = filled["draft"]["draft_id"]
        action_id = filled["confirmation"]["id"]

        def persisted_counts() -> dict[str, int]:
            return {
                "drafts": table_count(
                    app, "SELECT COUNT(*) AS n FROM agent_drafts"
                ),
                "pending": table_count(
                    app, "SELECT COUNT(*) AS n FROM pending_actions"
                ),
                "bank": table_count(
                    app, "SELECT COUNT(*) AS n FROM bank_transactions"
                ),
                "audit": table_count(app, "SELECT COUNT(*) AS n FROM audit_log"),
            }

        before = persisted_counts()
        cross_run = client.post(
            "/api/agent/run",
            json=draft_payload(filled, "五百", user_id="user-b"),
        )
        assert_draft_error(cross_run, 409, "context_expired")
        cross_confirm = client.post(
            f"/api/confirmations/{action_id}",
            json=confirmation_payload(filled, user_id="user-b"),
        )
        assert_draft_error(cross_confirm, 409, "context_expired")
        assert persisted_counts() == before

        demo_draft = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert demo_draft is not None
        assert demo_draft["user_id"] == "demo-user"
        assert demo_draft["version"] == 2
        assert demo_draft["status"] == "awaiting_confirmation"
        assert demo_draft["pending_action_id"] == action_id
        demo_pending = fetch_row(
            app, "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
        )
        assert demo_pending is not None
        assert demo_pending["status"] == "pending"
        assert demo_pending["user_id"] == "demo-user"
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM agent_drafts WHERE user_id='user-b'",
            )
            == 0
        )
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM pending_actions WHERE user_id='user-b'",
            )
            == 0
        )
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )

        # The owner's confirmation still works afterwards, proving the rejected
        # cross-user requests did not corrupt or resolve the pending action.
        owner_confirm = client.post(
            f"/api/confirmations/{action_id}",
            json=confirmation_payload(filled),
        )
        assert owner_confirm.status_code == 200, owner_confirm.text
        assert owner_confirm.json()["status"] == "completed"
        transfers = fetch_rows(
            app,
            """
            SELECT transaction_id, user_id, amount_cents, status
            FROM bank_transactions WHERE category = ?
            """,
            (TRANSFER_CATEGORY,),
        )
        assert len(transfers) == 1
        assert transfers[0]["user_id"] == "demo-user"
        assert transfers[0]["amount_cents"] == -50_000
        assert transfers[0]["status"] == "posted"


def test_u4_expired_draft_is_invalidated_on_read_and_removed_by_cleanup(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        app = client.app
        started = start_transfer(client)
        session_id = started["session_id"]
        old_draft_id = started["draft"]["draft_id"]

        with app.state.services.db.transaction() as conn:
            conn.execute(
                "UPDATE agent_drafts SET expires_at='2000-01-01T00:00:00+00:00' "
                "WHERE draft_id = ?",
                (old_draft_id,),
            )

        expired_response = client.post(
            "/api/agent/run", json=draft_payload(started, "五百")
        )
        assert_draft_error(expired_response, 409, "context_expired")
        expired_row = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (old_draft_id,)
        )
        assert expired_row is not None
        assert expired_row["status"] == "expired"
        assert expired_row["reason_code"] == "context_expired"
        assert expired_row["version"] == 2
        assert expired_row["pending_action_id"] is None
        assert table_count(app, "SELECT COUNT(*) AS n FROM pending_actions") == 0
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )

        # Creation performs the bounded cleanup, so the expired row disappears
        # rather than accumulating in the demo state.
        renewed = start_transfer(client, session_id=session_id)
        assert renewed["draft"]["draft_id"] != old_draft_id
        assert renewed["draft"]["version"] == 1
        assert renewed["draft"]["status"] == "awaiting_amount"
        assert (
            fetch_row(
                app,
                "SELECT * FROM agent_drafts WHERE draft_id = ?",
                (old_draft_id,),
            )
            is None
        )
        assert table_count(app, "SELECT COUNT(*) AS n FROM agent_drafts") == 1
        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM agent_drafts WHERE status='expired'",
            )
            == 0
        )


def test_u4_terminal_cleanup_is_per_user_and_keeps_newest_bounded_rows(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        app = client.app
        # Keep every fixture row during setup, then prove the configurable cap is
        # enforced when the next draft creation triggers cleanup.
        app.state.drafts.max_terminal_per_user = 100
        terminal_ids: list[str] = []
        for index in range(4):
            body = start_transfer(client, session_id=f"u4-clean-{index}")
            marked = app.state.drafts.mark_superseded(
                body["draft"]["draft_id"],
                user_id="demo-user",
                reason="u4 terminal cleanup fixture",
                reason_code="completed",
            )
            assert marked is not None
            assert marked["status"] == "superseded"
            terminal_ids.append(marked["draft_id"])

        with app.state.services.db.transaction() as conn:
            for index, draft_id in enumerate(terminal_ids):
                conn.execute(
                    "UPDATE agent_drafts SET updated_at=? WHERE draft_id=?",
                    (f"2026-10-30T00:00:0{index}+00:00", draft_id),
                )

        expired = start_transfer(client, session_id="u4-clean-expired")
        expired_id = expired["draft"]["draft_id"]
        with app.state.services.db.transaction() as conn:
            conn.execute(
                "UPDATE agent_drafts SET expires_at='2000-01-01T00:00:00+00:00' "
                "WHERE draft_id=?",
                (expired_id,),
            )

        seed_terminal_draft(
            app,
            draft_id="drf_u4_other_00",
            user_id="user-b",
            updated_at="2026-10-30T00:00:00+00:00",
        )
        seed_terminal_draft(
            app,
            draft_id="drf_u4_other_01",
            user_id="user-b",
            updated_at="2026-10-30T00:00:01+00:00",
        )

        app.state.drafts.max_terminal_per_user = 2
        triggered = start_transfer(client, session_id="u4-clean-trigger")

        assert (
            fetch_row(
                app,
                "SELECT * FROM agent_drafts WHERE draft_id = ?",
                (expired_id,),
            )
            is None
        )
        demo_terminal = fetch_rows(
            app,
            """
            SELECT draft_id, status FROM agent_drafts
            WHERE user_id='demo-user'
              AND status NOT IN ('awaiting_amount','awaiting_confirmation','processing')
            ORDER BY updated_at DESC
            """,
        )
        assert {row["draft_id"] for row in demo_terminal} == set(terminal_ids[-2:])
        assert len(demo_terminal) == 2
        assert all(row["status"] == "superseded" for row in demo_terminal)

        demo_active = fetch_rows(
            app,
            """
            SELECT draft_id, version, status FROM agent_drafts
            WHERE user_id='demo-user'
              AND status IN ('awaiting_amount','awaiting_confirmation','processing')
            """,
        )
        assert len(demo_active) == 1
        assert demo_active[0]["draft_id"] == triggered["draft"]["draft_id"]
        assert demo_active[0]["version"] == 1
        assert demo_active[0]["status"] == "awaiting_amount"

        other_terminal = fetch_rows(
            app,
            """
            SELECT draft_id FROM agent_drafts WHERE user_id='user-b'
            ORDER BY updated_at
            """,
        )
        assert {row["draft_id"] for row in other_terminal} == {
            "drf_u4_other_00",
            "drf_u4_other_01",
        }
        # 2 retained demo terminal rows + 1 new active demo row + 2 untouched
        # user-b terminal rows.  The cap is per user, not a global cap.
        assert table_count(app, "SELECT COUNT(*) AS n FROM agent_drafts") == 5


def test_u4_request_bounds_and_draft_pair_validation_return_422_without_writes(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        app = client.app

        too_long_instruction = post_run(client, "x" * 2001)
        assert too_long_instruction.status_code == 422, too_long_instruction.text
        exact_instruction = "查余额" + " " * (2_000 - len("查余额"))
        assert len(exact_instruction) == 2_000
        exact_response = post_run(client, exact_instruction)
        assert exact_response.status_code == 200, exact_response.text
        assert exact_response.json()["status"] == "completed"

        session_65 = "s" * 65
        draft_65 = "d" * 65
        assert post_run(
            client, "查余额", session_id=session_65
        ).status_code == 422
        assert post_run(
            client,
            "五百",
            draft_id=draft_65,
            draft_version=1,
        ).status_code == 422
        assert post_run(
            client, "五百", draft_id="drf_missing_version"
        ).status_code == 422
        assert post_run(
            client, "五百", draft_version=1
        ).status_code == 422
        assert post_run(
            client, "五百", draft_id="drf_zero", draft_version=0
        ).status_code == 422
        assert post_run(
            client,
            "五百",
            draft_id="drf_too_big",
            draft_version=1_000_001,
        ).status_code == 422
        assert post_run(
            client, "查余额", user_id="u" * 65
        ).status_code == 422

        session_64 = "s" * 64
        at_session_limit = post_run(client, "查余额", session_id=session_64)
        assert at_session_limit.status_code == 200, at_session_limit.text
        assert at_session_limit.json()["session_id"] == session_64
        at_draft_limit = post_run(
            client,
            "五百",
            draft_id="d" * 64,
            draft_version=1,
        )
        assert_draft_error(at_draft_limit, 409, "context_expired")

        started = start_transfer(client)
        filled_response = client.post(
            "/api/agent/run", json=draft_payload(started, "五百")
        )
        assert filled_response.status_code == 200, filled_response.text
        filled = filled_response.json()
        action_id = filled["confirmation"]["id"]
        draft_id = filled["draft"]["draft_id"]
        version = filled["draft"]["version"]
        audit_before = table_count(app, "SELECT COUNT(*) AS n FROM audit_log")

        invalid_confirmations: list[dict[str, Any]] = [
            {"approved": True, "user_id": "demo-user", "draft_id": draft_id},
            {"approved": True, "user_id": "demo-user", "draft_version": version},
            {
                "approved": True,
                "user_id": "demo-user",
                "session_id": session_65,
                "draft_id": draft_id,
                "draft_version": version,
            },
            {
                "approved": True,
                "user_id": "demo-user",
                "draft_id": draft_65,
                "draft_version": 1,
            },
            {
                "approved": True,
                "user_id": "demo-user",
                "draft_id": draft_id,
                "draft_version": 0,
            },
            {
                "approved": True,
                "user_id": "demo-user",
                "draft_id": draft_id,
                "draft_version": 1_000_001,
            },
        ]
        for payload in invalid_confirmations:
            response = client.post(
                f"/api/confirmations/{action_id}", json=payload
            )
            assert response.status_code == 422, response.text

        # Exactly-64 confirmation fields pass schema validation and then fail
        # business context checks without being misreported as length errors.
        session_boundary = confirmation_payload(filled)
        session_boundary["session_id"] = "s" * 64
        session_boundary_response = client.post(
            f"/api/confirmations/{action_id}", json=session_boundary
        )
        assert_draft_error(
            session_boundary_response, 409, "context_expired"
        )
        draft_boundary = confirmation_payload(filled)
        draft_boundary["draft_id"] = "d" * 64
        draft_boundary["draft_version"] = 1
        draft_boundary_response = client.post(
            f"/api/confirmations/{action_id}", json=draft_boundary
        )
        assert_draft_error(draft_boundary_response, 409, "context_expired")

        assert (
            table_count(
                app,
                "SELECT COUNT(*) AS n FROM bank_transactions WHERE category = ?",
                (TRANSFER_CATEGORY,),
            )
            == 0
        )
        pending = fetch_row(
            app, "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
        )
        assert pending is not None
        assert pending["status"] == "pending"
        assert pending["result_json"] == ""
        draft = fetch_row(
            app, "SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)
        )
        assert draft is not None
        assert draft["version"] == version
        assert draft["status"] == "awaiting_confirmation"
        assert draft["pending_action_id"] == action_id
        assert table_count(app, "SELECT COUNT(*) AS n FROM audit_log") == audit_before
