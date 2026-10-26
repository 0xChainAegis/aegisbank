"""Stage-2A demo MFA provider and policy tests.

The extension registers a simulated biometric provider next to the demo OTP.
These tests cover the provider catalogue, the tool/risk policy, a full red
confirmation through the biometric provider, readable 403 failures, audit
visibility (``confirmation_approved`` / ``mfa_failed``) and the demo challenge
endpoint that must never leak real credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.main import create_app
from aegisbank_api.trust.mfa import (
    MfaError,
    MfaPolicy,
    MfaService,
    OtpProvider,
    SimulatedBiometricProvider,
)

DEMO_OTP = "246810"
DEMO_BIOMETRIC_TOKEN = "FACE-888888"


def make_client(tmp_path: Path, name: str = "mfa.db") -> TestClient:
    return TestClient(create_app(database_path=tmp_path / name))


def audit_entries(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/api/audit", params={"limit": 200})
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def event_names(client: TestClient) -> list[str]:
    return [str(entry["event"]) for entry in audit_entries(client)]


def account_balance(client: TestClient, account_id: str = "ACC-1001") -> float:
    overview = client.get("/api/banking/overview").json()
    return float(
        next(item for item in overview["accounts"] if item["account_id"] == account_id)[
            "balance_cny"
        ]
    )


def start_red_transfer(client: TestClient, amount: float = 1200) -> dict[str, Any]:
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
    body = response.json()
    assert body["status"] == "awaiting_confirmation", body
    assert body["risk_level"] == "red"
    assert body["confirmation"]["requires_reauth"] is True
    return body


def test_providers_endpoint_lists_otp_and_simulated_biometric(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/mfa/providers")
        assert response.status_code == 200, response.text
        body = response.json()
        providers = {item["name"]: item for item in body["providers"]}

        assert {"otp", "biometric"} <= set(providers)
        assert body["default"] == "otp"
        assert body["enabled"] == ["biometric", "otp"]
        assert body["simulated"] is True
        assert body["demo_only"] is True

        biometric = providers["biometric"]
        assert biometric["kind"] == "biometric"
        assert biometric["simulated"] is True
        assert biometric["default"] is False
        assert "模拟" in biometric["hint"] and "演示" in biometric["hint"]
        assert providers["otp"]["default"] is True

        # 接口只给演示说明与格式提示，不返回真实凭据。
        assert DEMO_OTP not in response.text
        assert DEMO_BIOMETRIC_TOKEN not in response.text


def test_policy_endpoint_maps_risk_levels_and_sensitive_tools(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/mfa/policy")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["default_provider"] == "otp"
        levels = body["risk_levels"]
        assert levels["green"]["providers"] == []
        assert levels["green"]["required"] is False
        assert levels["yellow"]["providers"] == []
        assert levels["red"]["providers"] == ["otp", "biometric"]
        assert levels["red"]["default_provider"] == "otp"
        assert levels["red"]["required"] is True

        sensitive = body["sensitive_tools"]
        for tool_name in ("report_card_lost", "reset_card_password"):
            rule = sensitive[tool_name]
            assert set(rule["providers"]) == {"biometric", "otp"}
            assert rule["default_provider"] == "biometric"
            assert rule["required"] is True

        tools = {item["tool_name"]: item for item in body["tools"]}
        assert tools["transfer"]["risk_level"] == "yellow"
        assert tools["transfer"]["providers"] == []
        assert tools["report_card_lost"]["risk_level"] == "red"
        assert tools["report_card_lost"]["default_provider"] == "biometric"
        assert tools["query_bill"]["providers"] == []
        assert tools["query_bill"]["required"] is False


def test_policy_falls_back_when_biometric_is_not_registered() -> None:
    resolved = MfaPolicy().resolve("reset_card_password", "red", available=["otp"])
    assert resolved["providers"] == ["otp"]
    assert resolved["default_provider"] == "otp"
    assert resolved["required"] is True
    assert resolved["dropped_providers"] == ["biometric"]


def test_biometric_token_completes_red_confirmation_and_audits(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = start_red_transfer(client, 1200)
        action_id = body["confirmation"]["id"]
        before = account_balance(client)

        response = client.post(
            f"/api/confirmations/{action_id}",
            json={
                "approved": True,
                "reauth_token": DEMO_BIOMETRIC_TOKEN,
                "mfa_provider": "biometric",
            },
        )
        assert response.status_code == 200, response.text
        confirmed = response.json()
        assert confirmed["status"] == "completed"
        assert confirmed["risk_level"] == "red"
        assert account_balance(client) == before - 1200

        entries = audit_entries(client)
        approved = next(entry for entry in entries if entry["event"] == "confirmation_approved")
        mfa = approved["result"]["mfa"]
        assert mfa["provider"] == "biometric"
        assert mfa["verification_kind"] == "biometric"
        assert mfa["ok"] is True
        assert "tool_executed" in [entry["event"] for entry in entries]


def test_wrong_biometric_token_returns_403_and_writes_mfa_failed(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = start_red_transfer(client, 1200)
        action_id = body["confirmation"]["id"]
        before = account_balance(client)

        response = client.post(
            f"/api/confirmations/{action_id}",
            json={
                "approved": True,
                "reauth_token": "FACE-000000",
                "mfa_provider": "biometric",
            },
        )
        assert response.status_code == 403, response.text
        detail = response.json()["detail"]
        assert "二次身份校验失败" in detail
        assert "模拟人脸" in detail

        assert account_balance(client) == before
        events = event_names(client)
        assert "mfa_failed" in events
        assert "tool_executed" not in events
        failed = next(entry for entry in audit_entries(client) if entry["event"] == "mfa_failed")
        payload = failed["result"]["mfa"]
        assert payload["ok"] is False
        assert payload["provider"] == "biometric"
        assert payload["verification_kind"] == "biometric"

        # 失败不消耗确认请求：用正确 token 仍可完成。
        retry = client.post(
            f"/api/confirmations/{action_id}",
            json={
                "approved": True,
                "reauth_token": DEMO_BIOMETRIC_TOKEN,
                "mfa_provider": "biometric",
            },
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["status"] == "completed"


def test_unknown_provider_returns_readable_403(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = start_red_transfer(client, 1200)
        action_id = body["confirmation"]["id"]

        response = client.post(
            f"/api/confirmations/{action_id}",
            json={
                "approved": True,
                "reauth_token": "anything",
                "mfa_provider": "face-scan",
            },
        )
        assert response.status_code == 403, response.text
        detail = response.json()["detail"]
        assert "未知的 MFA 验证方式" in detail
        assert "face-scan" in detail
        assert "biometric" in detail and "otp" in detail

        events = event_names(client)
        assert "mfa_failed" in events
        assert "tool_executed" not in events
        failed = next(entry for entry in audit_entries(client) if entry["event"] == "mfa_failed")
        assert failed["result"]["mfa"] is None
        assert "face-scan" in failed["result"]["error"]


def test_default_provider_is_still_otp_after_extension_activation(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = start_red_transfer(client, 1200)
        response = client.post(
            f"/api/confirmations/{body['confirmation']['id']}",
            json={"approved": True, "reauth_token": DEMO_OTP},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"

        approved = next(
            entry for entry in audit_entries(client) if entry["event"] == "confirmation_approved"
        )
        mfa = approved["result"]["mfa"]
        assert mfa["provider"] == "otp"
        assert mfa["verification_kind"] == "otp"


def test_demo_challenge_returns_hint_without_credentials(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/mfa/demo/challenge",
            json={
                "provider": "biometric",
                "tool_name": "reset_card_password",
                "risk_level": "red",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["provider"] == "biometric"
        assert body["kind"] == "biometric"
        assert body["simulated"] is True
        assert body["demo_only"] is True
        assert {"otp", "biometric"} <= set(body["providers"])
        assert body["policy"]["providers"] == ["biometric", "otp"]
        assert body["policy"]["default_provider"] == "biometric"
        assert "FACE-XXXXXX" in body["token_hint"]

        # 只给提示，不泄露真实演示 token / OTP。
        assert DEMO_OTP not in response.text
        assert DEMO_BIOMETRIC_TOKEN not in response.text

        entries = audit_entries(client)
        challenge = next(entry for entry in entries if entry["event"] == "mfa_challenge_issued")
        assert challenge["result"]["provider"] == "biometric"
        assert challenge["confirmation_state"] == "mfa_challenge"


def test_unknown_challenge_provider_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/mfa/demo/challenge", json={"provider": "fingerprint"})
        assert response.status_code == 400
        assert "未知的 MFA 验证方式" in response.json()["detail"]


def test_mfa_service_provider_protocol_and_policy_api() -> None:
    service = MfaService([OtpProvider(DEMO_OTP), SimulatedBiometricProvider(DEMO_BIOMETRIC_TOKEN)])
    assert service.registered_names() == ["biometric", "otp"]
    assert service.providers_for("report_card_lost", "red") == ["biometric", "otp"]
    assert service.providers_for("transfer", "red") == ["otp", "biometric"]
    assert service.providers_for("query_bill", "green") == []

    result = service.verify(DEMO_BIOMETRIC_TOKEN, user_id="demo-user", provider="biometric")
    assert result.ok is True
    assert result.verification_kind == "biometric"

    with pytest.raises(MfaError, match="未知的 MFA 验证方式"):
        service.verify("x", user_id="demo-user", provider="unknown")
