"""Pluggable MFA providers for red-risk confirmations (stage 2A).

The scheduler no longer compares a raw OTP: it asks this service to verify the
confirmation token with the provider chosen by the user (default: demo OTP).
Providers are registered at startup and audit their own verification kind, so
the audit trail records *how* the red operation was verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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
            "hint": "演示环境固定验证码，生产环境须接入银行真实 MFA。",
        }

    def verify(self, token: str | None, *, user_id: str) -> MfaResult:
        ok = bool(token) and token == self._demo_otp
        detail = "OTP 校验通过" if ok else "OTP 校验失败，请检查演示验证码。"
        return MfaResult(ok=ok, provider=self.name, verification_kind="otp", detail=detail)


class MfaService:
    """Registry of providers plus the default verification policy."""

    def __init__(
        self,
        providers: list[MfaProvider] | None = None,
        *,
        default_provider: str = "otp",
    ) -> None:
        self._providers: dict[str, MfaProvider] = {}
        for provider in providers or []:
            self.register(provider)
        self.default_provider = default_provider

    def register(self, provider: MfaProvider, *, make_default: bool = False) -> None:
        self._providers[provider.name] = provider
        if make_default or not self._providers:
            self.default_provider = provider.name

    def is_known(self, name: str | None) -> bool:
        return not name or name in self._providers

    def list_providers(self) -> list[dict[str, Any]]:
        items = [provider.describe() for provider in self._providers.values()]
        for item in items:
            item["default"] = item["name"] == self.default_provider
        return sorted(items, key=lambda item: str(item["name"]))

    def resolve(self, name: str | None = None) -> MfaProvider:
        chosen = name or self.default_provider
        provider = self._providers.get(chosen)
        if provider is None:
            raise MfaError(f"MFA 验证方式不可用：{chosen}")
        if not self.is_known(chosen):
            raise MfaError(f"未知的 MFA 验证方式：{chosen}")
        return provider

    def verify(
        self,
        token: str | None,
        *,
        user_id: str,
        provider: str | None = None,
    ) -> MfaResult:
        return self.resolve(provider).verify(token, user_id=user_id)
