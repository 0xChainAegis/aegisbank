"""Stage-2A IM channel adapter tests.

Coverage: green run through IM, red run + IM text confirmation with OTP, wrong
OTP rejection with audit, ``message_id`` idempotency, clarification receipts,
payload validation/help, and direct adapter use for the CLI/webhook channels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aegisbank_api.channels.im import ImChannel, ImMessage
from aegisbank_api.main import create_app

DEMO_OTP = "246810"


def make_client(tmp_path: Path, name: str = "im-channel.db") -> TestClient:
    return TestClient(create_app(database_path=tmp_path / name))


def send(
    client: TestClient,
    text: str,
    *,
    message_id: str | None = None,
    channel: str = "im",
    sender_id: str = "alice",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "channel": channel,
        "sender_id": sender_id,
        "text": text,
    }
    if message_id is not None:
        payload["message_id"] = message_id
    response = client.post("/api/channels/im/message", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def audit_entries(client: TestClient, limit: int = 200) -> list[dict[str, Any]]:
    return client.get("/api/audit", params={"limit": limit}).json()["entries"]


def test_green_instruction_runs_through_im_and_returns_receipt(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = send(
            client,
            "查询我的本月账单",
            message_id="msg-green-1",
            channel="cli",
            sender_id="alice",
        )

        assert body["status"] == "completed"
        assert body["channel"] == "cli"
        assert body["replayed"] is False
        assert "已完成" in body["text"]
        assert body["structured"]["results"][0]["data"]["simulated"] is True
        assert body["confirmation"] is None

        entry = next(
            item for item in audit_entries(client) if item["event"] == "im_message_executed"
        )
        assert entry["arguments"]["channel"] == "cli"
        assert entry["arguments"]["sender_id"] == "alice"
        assert entry["arguments"]["message_id"] == "msg-green-1"
        assert entry["result"]["status"] == "completed"
        assert entry["result"]["channel"] == "cli"
        assert client.get("/api/audit/verify").json()["valid"] is True


def test_red_instruction_then_im_otp_confirmation_executes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        start = send(client, "挂失 CARD-9902", message_id="msg-red-1")

        assert start["status"] == "awaiting_confirmation"
        confirmation = start["confirmation"]
        assert confirmation["requires_reauth"] is True
        assert confirmation["id"] in start["text"]
        assert "确认" in start["text"]
        assert start["structured"]["risk_level"] == "red"

        done = send(
            client,
            f"确认 {confirmation['id']} 验证码 {DEMO_OTP}",
            message_id="msg-red-2",
        )

        assert done["status"] == "completed"
        assert "已完成" in done["text"]
        assert done["structured"]["results"][0]["data"]["status"] == "lost"

        cards = client.get("/api/banking/overview").json()["cards"]
        card = next(item for item in cards if item["card_id"] == "CARD-9902")
        assert card["status"] == "lost"
        assert any(
            item["event"] == "im_message_executed" and item["result"]["status"] == "completed"
            for item in audit_entries(client)
        )


def test_wrong_otp_returns_readable_rejection_and_audit(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        start = send(client, "挂失 CARD-9902")
        action_id = start["confirmation"]["id"]

        bad = send(client, f"确认 {action_id} 000000", message_id="msg-bad-otp")

        assert bad["status"] == "rejected"
        assert "二次身份校验失败" in bad["text"]
        assert bad["structured"]["error_type"] == "ReauthError"
        entry = next(
            item for item in audit_entries(client) if item["event"] == "im_message_rejected"
        )
        assert entry["arguments"]["channel"] == "im"
        assert entry["arguments"]["sender_id"] == "alice"
        assert entry["result"]["status"] == "rejected"
        assert "二次身份校验失败" in entry["result"]["error"]

        # A rejected MFA attempt does not consume the pending action.
        good = send(client, f"确认 {action_id} {DEMO_OTP}")
        assert good["status"] == "completed"


def test_repeated_message_id_replays_first_reply_without_second_execution(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        first = send(client, "查询我的本月账单", message_id="msg-dup-1")
        second = send(client, "查询我的本月账单", message_id="msg-dup-1")

        assert second["replayed"] is True
        assert second["text"] == first["text"]
        assert second["status"] == first["status"]
        assert second["structured"]["run_id"] == first["structured"]["run_id"]

        entries = audit_entries(client)
        assert sum(1 for item in entries if item["event"] == "im_message_executed") == 1
        assert (
            sum(
                1
                for item in entries
                if item["event"] == "tool_executed" and item["tool_name"] == "query_bill"
            )
            == 1
        )


def test_unknown_instruction_returns_clarification_receipt(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = send(client, "帮我处理一下", channel="webhook", sender_id="bot")

        assert body["status"] == "needs_clarification"
        assert "无法识别" in body["text"] or "请补充" in body["text"]
        assert body["structured"]["plan"]["needs_clarification"] is True
        entry = next(
            item
            for item in audit_entries(client)
            if item["event"] == "im_message_executed"
        )
        assert entry["result"]["status"] == "needs_clarification"


def test_help_endpoint_and_payload_validation(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        help_response = client.get("/api/channels/im/help")
        assert help_response.status_code == 200
        help_body = help_response.json()
        assert help_body["demo_otp"] == DEMO_OTP
        assert len(help_body["confirmation_syntax"]) == 2
        assert help_body["channels"] == ["im", "cli", "webhook"]
        assert help_body["examples"]
        assert "message_id" in help_body["message_fields"]

        bad_channel = client.post(
            "/api/channels/im/message",
            json={"channel": "sms", "sender_id": "alice", "text": "查询账单"},
        )
        assert bad_channel.status_code == 422

        blank_text = client.post(
            "/api/channels/im/message",
            json={"channel": "im", "sender_id": "alice", "text": "   "},
        )
        assert blank_text.status_code == 422


def test_direct_adapter_handles_cli_and_missing_confirmation(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "im-direct.db")
    with TestClient(app) as client:
        services = app.state.services
        adapter = services.extras["im"]
        assert isinstance(adapter, ImChannel)

        message = ImMessage(
            channel="webhook",
            sender_id="bot",
            text="查询账单",
            message_id="msg-direct-1",
        )
        reply = adapter.handle(services, message)
        assert reply.status == "completed"
        assert reply.structured["results"][0]["data"]["simulated"] is True

        replay = adapter.handle(services, message)
        assert replay.as_dict() == reply.as_dict()

        missing = adapter.handle(
            services,
            ImMessage(channel="im", sender_id="bot", text="确认 cfm_missing 246810"),
        )
        assert missing.status == "rejected"
        assert "确认请求不存在" in missing.text
        assert any(
            item["event"] == "im_message_rejected" for item in audit_entries(client)
        )

        with_error = adapter.handle(
            services,
            ImMessage(channel="cli", sender_id="ops", text="确认 cfm_missing"),
        )
        assert with_error.status == "rejected"
        assert "验证码" in with_error.text or "确认请求不存在" in with_error.text