"""Environment-backed application configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")

    app_name: str = "AegisBank Trusted Agent"
    api_prefix: str = "/api"
    database_path: Path = Path(__file__).resolve().parent.parent / "data" / "aegisbank.db"
    demo_otp: str = "246810"
    confirmation_ttl_seconds: int = 300
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    planner_mode: Literal["rule", "llm", "auto"] = "rule"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 20.0
    automation_enabled: bool = False
    automation_interval_seconds: int = 30
    circuit_breaker_threshold: int = 3
    circuit_breaker_window_seconds: int = 60
    circuit_breaker_lock_seconds: int = 60
    # stage 2A switches
    authz_default_role: str = "user"
    mfa_default_provider: str = "otp"
    sandbox_enabled: bool = True
    sandbox_timeout_seconds: float = 5.0
    sandbox_max_output_bytes: int = 64_000
    sandbox_block_network: bool = True
    suspicious_red_events: int = 3
    suspicious_injection_events: int = 3
    suspicious_window_seconds: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


def get_settings() -> Settings:
    return Settings()
