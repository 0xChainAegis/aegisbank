"""Planner intent extension surface for scenario modules.

Core rule-based intents stay in :mod:`aegisbank_api.planning.rule`. Scenario
modules contribute ``IntentRule`` objects from their ``intents()`` factory.
Rules run in ascending ``priority`` order *before* the core chain and return
``None`` when they do not apply, so unrelated instructions keep the previous
behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ..banking.repository import BankingRepository
from ..registry import ToolRegistry
from .amounts import extract_amounts  # re-export for scenario intent rules
from .contracts import ExecutionPlan, PlanningRequest

_ACCOUNT_PATTERN = re.compile(r"ACC-\d{3,}", re.IGNORECASE)
_CARD_PATTERN = re.compile(r"CARD-\d{3,}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IntentContext:
    """Read-only facts a scenario intent rule may use. It never executes tools."""

    request: PlanningRequest
    registry: ToolRegistry
    repository: BankingRepository | None = None

    @property
    def instruction(self) -> str:
        return self.request.instruction

    @property
    def text(self) -> str:
        return self.request.instruction.lower()

    def has_tool(self, name: str) -> bool:
        try:
            self.registry.get(name)
        except KeyError:
            return False
        return True

    def amounts(self) -> list[float]:
        return extract_amounts(self.instruction)

    def account_ids(self) -> list[str]:
        return [match.group(0).upper() for match in _ACCOUNT_PATTERN.finditer(self.instruction)]

    def card_id(self, default: str = "CARD-8821") -> str:
        match = _CARD_PATTERN.search(self.instruction)
        return match.group(0).upper() if match else default


class IntentRule(Protocol):
    """One deterministic natural-language intent owned by a scenario module."""

    name: str
    priority: int

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        """Return a plan when the instruction matches this intent, else ``None``."""
        ...


def collect_intent_rules() -> list[IntentRule]:
    """Gather scenario intent rules; the import stays local to avoid a cycle."""
    from ..scenarios import iter_scenario_modules

    rules: list[IntentRule] = []
    for module in iter_scenario_modules():
        factory = getattr(module, "intents", None)
        if callable(factory):
            rules.extend(factory())
    return sorted(rules, key=lambda item: (item.priority, item.name))
