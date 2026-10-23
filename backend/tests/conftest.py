"""Pytest isolation guard for concurrent extension/scenario development.

When ``AEGIS_SCENARIO_ALLOW`` (scenarios) or ``AEGIS_EXTENSION_ALLOW``
(stage-2A extensions) selects a subset, tests that belong to modules outside
the allowlist are skipped instead of failing: those modules are not loaded into
the app under test, so their assertions cannot be meaningful in that mode.
Without the variables every test runs normally.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

SCENARIO_ALLOW_ENV = "AEGIS_SCENARIO_ALLOW"
EXTENSION_ALLOW_ENV = "AEGIS_EXTENSION_ALLOW"

# test module file name -> scenario module it exercises
SCENARIO_TEST_FILES: dict[str, str] = {
    "test_bills.py": "bills",
    "test_cards.py": "cards",
    "test_transfers.py": "transfers",
    "test_wealth.py": "wealth",
    "test_automation.py": "automation",
}

# test module file name -> stage-2A extension module it exercises
EXTENSION_TEST_FILES: dict[str, str] = {
    "test_compensation.py": "compensation",
    "test_breaker.py": "breaker",
    "test_mfa.py": "mfa",
    "test_sandbox.py": "sandbox",
    "test_im_channel.py": "im",
    "test_authz.py": "authz",
}


def _parse_allowlist(env_name: str) -> set[str] | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    if raw.lower() in {"all", "*"}:
        return None
    if raw.lower() == "none":
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    scenario_allow = _parse_allowlist(SCENARIO_ALLOW_ENV)
    if scenario_allow is not None:
        for item in items:
            scenario = SCENARIO_TEST_FILES.get(Path(str(item.path)).name)
            if scenario is None or scenario in scenario_allow:
                continue
            item.add_marker(
                pytest.mark.skip(
                    reason=f"场景 {scenario} 未在 {SCENARIO_ALLOW_ENV} 中启用，隔离模式下跳过"
                )
            )

    extension_allow = _parse_allowlist(EXTENSION_ALLOW_ENV)
    if extension_allow is not None:
        for item in items:
            extension = EXTENSION_TEST_FILES.get(Path(str(item.path)).name)
            if extension is None or extension in extension_allow:
                continue
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"扩展 {extension} 未在 {EXTENSION_ALLOW_ENV} 中启用，"
                        "隔离模式下跳过"
                    )
                )
            )
