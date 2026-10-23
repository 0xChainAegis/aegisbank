"""Pytest isolation guard for concurrent scenario development.

When ``AEGIS_SCENARIO_ALLOW`` selects a subset of scenario modules, tests that
belong to modules outside the allowlist are skipped instead of failing: the
scenario modules are not loaded into the app under test, so their assertions
cannot be meaningful in that mode. Without the variable (or with ``all``) every
test runs normally.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ALLOW_ENV = "AEGIS_SCENARIO_ALLOW"

# test module file name -> scenario module it exercises
SCENARIO_TEST_FILES: dict[str, str] = {
    "test_bills.py": "bills",
    "test_cards.py": "cards",
    "test_transfers.py": "transfers",
    "test_wealth.py": "wealth",
    "test_automation.py": "automation",
}


def _allowlist() -> set[str] | None:
    raw = os.environ.get(ALLOW_ENV, "").strip()
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
    allow = _allowlist()
    if allow is None:
        return
    for item in items:
        scenario = SCENARIO_TEST_FILES.get(Path(str(item.path)).name)
        if scenario is None or scenario in allow:
            continue
        item.add_marker(
            pytest.mark.skip(
                reason=f"场景 {scenario} 未在 {ALLOW_ENV} 中启用，隔离模式下跳过"
            )
        )
