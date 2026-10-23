"""Demo MFA provider extension (stage 2A).

Registers a simulated biometric provider next to the built-in demo OTP and
exposes read-only/demo endpoints:

* ``GET  /api/mfa/providers``       -- enabled providers and demo limitations
* ``GET  /api/mfa/policy``          -- tool/risk -> allowed providers
* ``POST /api/mfa/demo/challenge``  -- issue a demo challenge hint (no secrets)

Red confirmations still run through the scheduler and ``MfaService.verify``;
this module never bypasses the gateway, the confirmation flow or the audit
chain. No real credential is stored or returned here.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import CoreServices
from ..trust.evidence import evidence_payload, policy_decision_evidence
from ..trust.mfa import MfaError, MfaService, SimulatedBiometricProvider

NAME = "mfa"
DEMO_USER = "demo-user"
DEMO_BIOMETRIC_TOKEN = "FACE-888888"
DEMO_TOKEN_FORMAT = "FACE-XXXXXX"
CHALLENGE_TTL_SECONDS = 300

_DEMO_HINTS = {
    "otp": "演示 OTP 为 6 位固定数字验证码（仅本地演示，不在此接口返回）。",
    "biometric": (
        "模拟人脸/设备确认 token 形如 FACE-XXXXXX（6 位数字），仅用于本地演示，不涉及真实生物识别。"
    ),
}

_NOTE = (
    "演示环境：OTP 为本地固定验证码，人脸/设备为模拟确认；"
    "不连接真实 MFA 服务，也不在此接口返回任何真实凭据。"
)


class DemoChallengeRequest(BaseModel):
    provider: str | None = Field(default=None, max_length=32)
    tool_name: str | None = Field(default=None, max_length=64)
    risk_level: str | None = Field(default=None, max_length=16)


def activate(services: CoreServices) -> None:
    """Attach the simulated biometric provider once the runtime exists."""
    mfa = services.mfa
    if mfa is None:
        raise RuntimeError("MFA 服务尚未初始化，无法注册演示生物识别 provider。")
    if not mfa.is_known("biometric"):
        mfa.register(SimulatedBiometricProvider(DEMO_BIOMETRIC_TOKEN))
    services.extras["mfa_demo_provider"] = "biometric"
    services.extras["mfa_demo_token_format"] = DEMO_TOKEN_FORMAT


def _require_mfa(services: CoreServices) -> MfaService:
    mfa = services.mfa
    if mfa is None:
        raise HTTPException(status_code=503, detail="MFA 服务尚未初始化。")
    return mfa


def _tool_rows(services: CoreServices, mfa: MfaService) -> list[dict[str, Any]]:
    """Per-tool policy for every registered tool (read-only, deterministic)."""
    registry = services.require_registry()
    rows: list[dict[str, Any]] = []
    for name in registry.names():
        metadata = registry.get(name).metadata
        policy = mfa.policy_for(name, metadata.risk_level.value)
        rows.append(
            {
                "tool_name": name,
                "title": metadata.title,
                "risk_level": metadata.risk_level.value,
                "required": policy["required"],
                "providers": policy["providers"],
                "default_provider": policy["default_provider"],
                "source": policy["source"],
                "reason": policy["reason"],
            }
        )
    return sorted(rows, key=lambda item: str(item["tool_name"]))


def router(services: CoreServices) -> APIRouter:
    api = APIRouter(prefix="/api/mfa", tags=["mfa"])

    @api.get("/providers")
    def list_providers() -> dict[str, Any]:
        mfa = _require_mfa(services)
        providers = mfa.list_providers()
        return {
            "providers": providers,
            "enabled": [item["name"] for item in providers],
            "default": mfa.default_provider,
            "kinds": sorted({str(item["kind"]) for item in providers}),
            "simulated": True,
            "demo_only": True,
            "note": _NOTE,
        }

    @api.get("/policy")
    def describe_policy() -> dict[str, Any]:
        mfa = _require_mfa(services)
        description = mfa.describe_policy()
        return {
            "default_provider": description["default_provider"],
            "providers": description["providers"],
            "risk_levels": description["risk_levels"],
            "sensitive_tools": description["sensitive_tools"],
            "tools": _tool_rows(services, mfa),
            "risk_level_source": "tool_baseline",
            "simulated": True,
            "demo_only": True,
            "note": (
                "tools 按工具基线风险展示；实际确认风险可能被动态风险引擎上调，"
                "请以 risk_levels 或 policy_for(tool_name, 实际风险) 为准。"
                "策略用于确认前的演示提示与前端选择；"
                "确认执行仍由调度器调用 MfaService.verify 复核。"
            ),
        }

    @api.post("/demo/challenge")
    def demo_challenge(body: DemoChallengeRequest | None = None) -> dict[str, Any]:
        mfa = _require_mfa(services)
        request = body or DemoChallengeRequest()
        policy = mfa.policy_for(request.tool_name, request.risk_level)
        chosen = request.provider or policy["default_provider"] or mfa.default_provider
        try:
            provider = mfa.resolve(chosen)
        except MfaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        hint = _DEMO_HINTS.get(provider.name, f"演示验证方式：{provider.title}（仅演示）。")
        challenge_id = f"mfa_ch_{uuid4().hex[:12]}"
        services.require_audit().record(
            event="mfa_challenge_issued",
            user_id=DEMO_USER,
            instruction="请求演示 MFA 挑战",
            dag_path="mfa.demo.challenge",
            tool_name=request.tool_name or "mfa",
            arguments={
                "provider": provider.name,
                "tool_name": request.tool_name,
                "risk_level": policy["risk_level"],
            },
            result={"challenge_id": challenge_id, "provider": provider.name},
            confirmation_state="mfa_challenge",
            risk_level="green",
            evidence=evidence_payload(
                policy_decision_evidence(True, "演示 MFA 挑战已签发，不返回真实凭据")
            ),
        )
        return {
            "challenge_id": challenge_id,
            "provider": provider.name,
            "kind": provider.kind,
            "title": provider.title,
            "providers": [item["name"] for item in mfa.list_providers()],
            "policy": policy,
            "token_hint": hint,
            "expires_in_seconds": CHALLENGE_TTL_SECONDS,
            "next_step": (
                "在 POST /api/confirmations/{action_id} 中提交 reauth_token 与 mfa_provider。"
            ),
            "simulated": True,
            "demo_only": True,
            "note": "接口不返回真实凭据；演示 token 只在本地演示中使用。",
        }

    return api
