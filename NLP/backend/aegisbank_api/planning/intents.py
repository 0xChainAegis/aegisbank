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
_CARD_PATTERN = re.compile(r"CARD-[A-Za-z0-9_-]+", re.IGNORECASE)
# Card suffixes are only recognised when the text explicitly frames them as a
# card reference. A bare number (an amount, a date or an account suffix) must
# never be mistaken for a card.
_CARD_SUFFIX_PATTERNS = (
    re.compile(r"(?:尾号|末四位|后四位|末位)\D{0,4}(\d+)", re.IGNORECASE),
    re.compile(r"(?<!\d)(\d+)\s*(?:的)?\s*卡(?:片)?", re.IGNORECASE),
    re.compile(r"卡号\s*[:：]?\s*(\d+)", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class CardResolution:
    """Result of resolving one card reference against the current user's cards."""

    card_id: str | None
    candidates: tuple[str, ...] = ()
    reference: str | None = None
    reason: str | None = None


def _card_candidate(card: object) -> str:
    card_id = str(getattr(card, "card_id", ""))
    masked = str(getattr(card, "masked_number", ""))
    return f"{card_id}（{masked}）" if masked else card_id


def resolve_card_reference(
    instruction: str,
    repository: BankingRepository | None,
    user_id: str,
) -> CardResolution:
    """Require every explicit ID/suffix to resolve to the same card for one user.

    The resolver never falls back to a demo card. When a referenced card is
    missing or matches more than one card the caller must ask the user to
    choose. A full ID cannot hide a contradictory suffix, and an ambiguous
    suffix cannot be silently disambiguated by another reference.
    """
    cards = []
    if repository is not None:
        try:
            cards = repository.cards(user_id)
        except Exception:  # noqa: BLE001 - repository is a local mock adapter
            cards = []
    candidates = tuple(_card_candidate(card) for card in cards)
    by_id = {str(card.card_id).upper(): card for card in cards}

    explicit_matches = list(_CARD_PATTERN.finditer(instruction))
    explicit = list(dict.fromkeys(match.group(0).upper() for match in explicit_matches))
    suffixes = []
    for pattern in _CARD_SUFFIX_PATTERNS:
        for match in pattern.finditer(instruction):
            # The numeric portion of CARD-12345 is an ID, not a shorter suffix.
            start, end = match.span(1)
            if any(item.start() <= start and end <= item.end() for item in explicit_matches):
                continue
            suffixes.append(match.group(1))
    suffixes = list(dict.fromkeys(suffixes))
    references = [(value, "id") for value in explicit] + [(value, "suffix") for value in suffixes]
    if not references:
        return CardResolution(None, candidates, reason="card_unspecified")

    reference = "、".join(value for value, _ in references)
    resolved: dict[str, str] = {}
    for value, kind in references:
        if kind == "id":
            if repository is None:
                # Preserve standalone rule-planner compatibility; execution
                # still requires repository-backed ownership checks.
                matched_ids = [value]
                matched_candidates = candidates
            else:
                card = by_id.get(value)
                matched_ids = [str(card.card_id)] if card is not None else []
                matched_candidates = candidates
        else:
            # Keep the supported 3/4-digit suffix contract. Longer numbers are
            # unresolved references, never a valid 4-digit substring.
            matched = [
                card for card in cards
                if 3 <= len(value) <= 4 and (
                    str(card.card_id).upper().split("-")[-1].endswith(value)
                    or re.sub(r"\s+", "", str(card.masked_number)).endswith(value)
                )
            ]
            matched_ids = [str(card.card_id) for card in matched]
            matched_candidates = tuple(_card_candidate(card) for card in matched) or candidates
        if len(matched_ids) != 1:
            return CardResolution(
                None, matched_candidates, reference=reference,
                reason="ambiguous_card" if len(matched_ids) > 1 else "unknown_card",
            )
        resolved[matched_ids[0].upper()] = matched_ids[0]
        if len(resolved) > 1:
            return CardResolution(
                None, candidates, reference=reference, reason="conflicting_card_references"
            )

    return CardResolution(
        next(iter(resolved.values())), candidates, reference=reference,
        reason="masked_suffix" if suffixes else "explicit_id",
    )


def card_clarification_plan(
    intent: str,
    resolution: CardResolution,
    *,
    action: str,
) -> ExecutionPlan:
    """Build a safe clarification for an unresolved card-specific write."""
    if resolution.candidates:
        options = "、".join(resolution.candidates)
        message = (
            f"已识别{action}，但无法唯一确定要操作的卡片。"
            f"请补充卡号或尾号；当前可选：{options}。"
        )
    elif resolution.reference:
        message = (
            f"未能在当前用户的卡片中找到「{resolution.reference}」对应的卡片，"
            "请补充完整卡号或尾号。"
        )
    else:
        message = f"当前用户没有可用卡片，无法执行{action}。"
    return ExecutionPlan(
        intent=intent,
        planner="safety",
        confidence=0.0,
        needs_clarification=True,
        clarification=message,
    )


def resolve_card_for_write(
    instruction: str,
    repository: BankingRepository | None,
    user_id: str,
    *,
    intent: str,
    action: str,
) -> tuple[str | None, ExecutionPlan | None, list[str]]:
    """Resolve the target card for a card-specific write, or require clarification.

    A named card must resolve unambiguously. When no card is named, the current
    user's card list is consulted: exactly one card may be used with an explicit
    assumption, while zero or multiple cards produce a clarification with the
    candidates. A demo card id is never used as a fallback.
    """
    resolution = resolve_card_reference(instruction, repository, user_id)
    if resolution.card_id is not None:
        return resolution.card_id, None, []
    if resolution.reference is not None:
        return None, card_clarification_plan(intent, resolution, action=action), []

    cards = []
    if repository is not None:
        try:
            cards = repository.cards(user_id)
        except Exception:  # noqa: BLE001 - repository is a local mock adapter
            cards = []
    if len(cards) == 1:
        card = cards[0]
        card_id = str(card.card_id)
        masked = str(getattr(card, "masked_number", ""))
        label = f"{card_id}（{masked}）" if masked else card_id
        return card_id, None, [
            f"未指定卡片，当前仅有一张卡片 {label}，将使用该卡。"
        ]
    return None, card_clarification_plan(intent, resolution, action=action), []


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

    def resolve_card(self) -> CardResolution:
        return resolve_card_reference(self.instruction, self.repository, self.request.user_id)

    def card_id(self, default: str = "CARD-8821") -> str:
        """Legacy helper: resolve when possible, otherwise return the caller default.

        New card-specific write intents must call resolve_card() and turn an
        unresolved result into a clarification instead of using this helper.
        """
        resolved = self.resolve_card()
        return resolved.card_id or default


class IntentRule(Protocol):
    """One deterministic natural-language intent owned by a scenario module."""

    name: str
    priority: int

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        """Return a plan when the instruction matches this intent, else None."""
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
