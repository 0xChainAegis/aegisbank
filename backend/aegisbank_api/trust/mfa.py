"""Pluggable MFA providers and demo verification policy (stage 2A).

The scheduler no longer compares a raw OTP: it asks this service to verify the
confirmation token with the provider chosen by the user (default: demo OTP).
Providers are registered at startup and audit their own verification kind, so
the audit trail records *how* the red operation was verified.

Stage 2A adds a simulated biometric provider plus an explicit policy that maps
``tool_name`` / ``risk_level`` to the allowed providers and the recommended
default. The policy is advisory metadata for the console and the demo; the
scheduler still verifies through :class:`MfaService`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

RISK_LEVELS = ("green", "yellow", "red")
DEFAULT_RISK_LEVEL = "red"


class MfaError(ValueError):
    """Raised when no usable MFA provider is configured."""


@dataclass(frozen=True, slots=True)
class MfaResult:
    ok: bool
    provider: str
    verification_kind: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "verification_kind": self.verification_kind,
            "detail": self.detail,
        }


class MfaProvider(Protocol):
    """One verification method (OTP, simulated biometric, device push...)."""

    name: str
    kind: str
    title: str

    def describe(self) -> dict[str, Any]: ...

    def verify(self, token: str | None, *, user_id: str) -> MfaResult: ...


class OtpProvider:
    """Demo one-time password provider (the only enabled provider by default)."""

    kind = "otp"

    def __init__(self, demo_otp: str = "246810", title: str = "演示动态验证码") -> None:
        self.name = "otp"
        self.title = title
        self._demo_otp = demo_otp

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "title": self.title,
            "enabled": True,
            "simulated": True,
            "demo_only": True,
            "hint": "演示环境固定验证码，生产环境须接入银行真实 MFA。",
        }

    def verify(self, token: str | None, *, user_id: str) -> MfaResult:
        ok = bool(token) and token == self._demo_otp
        detail = "OTP 校验通过" if ok else "OTP 校验失败，请检查演示验证码。"
        return MfaResult(ok=ok, provider=self.name, verification_kind="otp", detail=detail)


class SimulatedBiometricProvider:
    """Simulated face / device confirmation provider (demo only).

    It never touches a camera, a device sensor or a real identity provider: a
    fixed demo token simply proves that the pluggable provider protocol works
    end to end with the scheduler and the audit trail.
    """

    kind = "biometric"

    def __init__(
        self,
        demo_token: str = "FACE-888888",
        title: str = "模拟人脸 / 设备确认",
    ) -> None:
        self.name = "biometric"
        self.title = title
        self._demo_token = demo_token.strip().upper()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "title": self.title,
            "enabled": True,
            "simulated": True,
            "demo_only": True,
            "hint": (
                "模拟人脸/设备确认，仅用于本地演示；token 形如 FACE-XXXXXX，"
                "不连接任何真实生物识别服务。"
            ),
            "demo_token_format": "FACE-XXXXXX",
        }

    def verify(self, token: str | None, *, user_id: str) -> MfaResult:
        supplied = (token or "").strip().upper()
        ok = bool(supplied) and supplied == self._demo_token
        detail = (
            "模拟人脸/设备确认通过（演示数据，不涉及真实生物识别）。"
            if ok
            else "模拟人脸/设备确认失败：演示 token 不匹配。"
        )
        return MfaResult(
            ok=ok,
            provider=self.name,
            verification_kind="biometric",
            detail=detail,
        )


@dataclass(frozen=True, slots=True)
class MfaPolicyRule:
    """Allowed providers for one tool or risk level."""

    providers: tuple[str, ...] = ()
    default_provider: str | None = None
    required: bool = False
    reason: str = ""


RISK_POLICY_RULES: dict[str, MfaPolicyRule] = {
    "green": MfaPolicyRule(reason="绿色操作只读或低风险，不触发二次身份校验。"),
    "yellow": MfaPolicyRule(reason="黄色操作只需一次明确确认，不触发二次身份校验。"),
    "red": MfaPolicyRule(
        providers=("otp", "biometric"),
        default_provider="otp",
        required=True,
        reason="普通红色操作默认使用演示 OTP 完成二次身份校验。",
    ),
}

SENSITIVE_TOOL_POLICY_RULES: dict[str, MfaPolicyRule] = {
    "report_card_lost": MfaPolicyRule(
        providers=("biometric", "otp"),
        default_provider="biometric",
        required=True,
        reason="卡片挂失属于账户安全类红色操作，要求模拟生物识别或 OTP。",
    ),
    "reset_card_password": MfaPolicyRule(
        providers=("biometric", "otp"),
        default_provider="biometric",
        required=True,
        reason="卡片密码重置涉及账户安全凭证，要求模拟生物识别或 OTP。",
    ),
}


class MfaPolicy:
    """Demo policy: map tool/risk to allowed providers and a recommended default."""

    def __init__(
        self,
        *,
        risk_rules: Mapping[str, MfaPolicyRule] | None = None,
        tool_rules: Mapping[str, MfaPolicyRule] | None = None,
    ) -> None:
        self._risk_rules: dict[str, MfaPolicyRule] = dict(RISK_POLICY_RULES)
        if risk_rules is not None:
            self._risk_rules.update(risk_rules)
        self._tool_rules: dict[str, MfaPolicyRule] = dict(SENSITIVE_TOOL_POLICY_RULES)
        if tool_rules is not None:
            self._tool_rules.update(tool_rules)

    def rule_for(
        self, tool_name: str | None, risk_level: str | None
    ) -> tuple[str, str, MfaPolicyRule]:
        normalized_risk = (risk_level or DEFAULT_RISK_LEVEL).strip().lower()
        if normalized_risk not in RISK_LEVELS:
            normalized_risk = DEFAULT_RISK_LEVEL
        tool_key = (tool_name or "").strip()
        if tool_key and tool_key in self._tool_rules:
            return "tool_name", normalized_risk, self._tool_rules[tool_key]
        return "risk_level", normalized_risk, self._risk_rules[normalized_risk]

    def resolve(
        self,
        tool_name: str | None = None,
        risk_level: str | None = None,
        *,
        available: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        source, normalized_risk, rule = self.rule_for(tool_name, risk_level)
        allowed = list(rule.providers)
        dropped: list[str] = []
        if available is not None:
            registered = set(available)
            dropped = [name for name in allowed if name not in registered]
            allowed = [name for name in allowed if name in registered]
        default = rule.default_provider if rule.default_provider in allowed else None
        if default is None and allowed:
            default = allowed[0]
        reason = rule.reason or "MFA 策略未显式定义，按最严格红色策略处理。"
        if dropped:
            reason = f"{reason}（未注册的验证方式已剔除：{'、'.join(dropped)}）"
        return {
            "tool_name": (tool_name or "").strip() or None,
            "risk_level": normalized_risk,
            "source": source,
            "required": rule.required,
            "providers": allowed,
            "default_provider": default,
            "reason": reason,
            "dropped_providers": dropped,
        }

    def describe(self, *, available: Sequence[str] | None = None) -> dict[str, Any]:
        return {
            "risk_levels": {
                level: self.resolve(None, level, available=available) for level in RISK_LEVELS
            },
            "sensitive_tools": {
                tool_name: self.resolve(tool_name, DEFAULT_RISK_LEVEL, available=available)
                for tool_name in sorted(self._tool_rules)
            },
        }


class MfaService:
    """Registry of providers plus the default verification policy."""

    def __init__(
        self,
        providers: list[MfaProvider] | None = None,
        *,
        default_provider: str = "otp",
        policy: MfaPolicy | None = None,
    ) -> None:
        self._providers: dict[str, MfaProvider] = {}
        for provider in providers or []:
            self.register(provider)
        self.default_provider = default_provider
        self.policy = policy or MfaPolicy()

    def register(self, provider: MfaProvider, *, make_default: bool = False) -> None:
        self._providers[provider.name] = provider
        if make_default or not self._providers:
            self.default_provider = provider.name

    def is_known(self, name: str | None) -> bool:
        return not name or name in self._providers

    def registered_names(self) -> list[str]:
        return sorted(self._providers)

    def list_providers(self) -> list[dict[str, Any]]:
        items = [provider.describe() for provider in self._providers.values()]
        for item in items:
            item["default"] = item["name"] == self.default_provider
        return sorted(items, key=lambda item: str(item["name"]))

    def resolve(self, name: str | None = None) -> MfaProvider:
        chosen = name or self.default_provider
        provider = self._providers.get(chosen)
        if provider is None:
            known = "、".join(self.registered_names()) or "无"
            raise MfaError(f"未知的 MFA 验证方式：{chosen}（可用：{known}）")
        return provider

    def verify(
        self,
        token: str | None,
        *,
        user_id: str,
        provider: str | None = None,
    ) -> MfaResult:
        return self.resolve(provider).verify(token, user_id=user_id)

    def policy_for(
        self, tool_name: str | None = None, risk_level: str | None = None
    ) -> dict[str, Any]:
        return self.policy.resolve(tool_name, risk_level, available=self.registered_names())

    def providers_for(
        self, tool_name: str | None = None, risk_level: str | None = None
    ) -> list[str]:
        return list(self.policy_for(tool_name, risk_level)["providers"])

    def describe_policy(self) -> dict[str, Any]:
        description = self.policy.describe(available=self.registered_names())
        return {
            "default_provider": self.default_provider,
            "providers": self.registered_names(),
            **description,
        }
