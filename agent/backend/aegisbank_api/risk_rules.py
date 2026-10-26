"""Risk rule extension surface for scenario modules.

The engine may only keep or escalate the tool baseline. Scenario modules add
deterministic rules for their own tools; the original core rules keep handling
the original tool set. A rule returns ``None`` when it does not apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .banking.repository import BankingRepository
from .domain import RiskLevel


@dataclass(frozen=True, slots=True)
class RiskContext:
    """Deterministic facts a scenario risk rule may use; never LLM output."""

    user_id: str
    tool_name: str
    arguments: dict[str, Any]
    base_risk: RiskLevel
    instruction: str
    repository: BankingRepository


@dataclass(frozen=True, slots=True)
class RiskGuess:
    """A rule's escalation proposal; the engine keeps the max with base risk."""

    level: RiskLevel
    score: int
    reasons: list[str]


class RiskRule(Protocol):
    """One deterministic risk rule owned by a scenario module."""

    name: str
    priority: int

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        """Return a risk guess for the tool, or ``None`` when not applicable."""
        ...


def collect_risk_rules() -> list[RiskRule]:
    """Gather scenario risk rules; the import stays local to avoid a cycle."""
    from .scenarios import iter_scenario_modules

    rules: list[RiskRule] = []
    for module in iter_scenario_modules():
        factory = getattr(module, "risk_rules", None)
        if callable(factory):
            rules.extend(factory())
    return sorted(rules, key=lambda item: (item.priority, item.name))
