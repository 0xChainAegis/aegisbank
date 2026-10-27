"""Planner selection from environment-backed settings."""

from __future__ import annotations

from ..banking.repository import BankingRepository
from ..config import Settings
from ..registry import ToolRegistry
from .contracts import ExecutionPlan, Planner, PlanningRequest
from .llm import OpenAICompatiblePlanner, PlannerError
from .rule import RuleBasedPlanner
from .semantic import SemanticPlanner
from .semantic_model import SemanticModel


class PlannerConfigurationError(ValueError):
    pass


class FallbackPlanner:
    """Use the LLM planner when available, but degrade safely to rules."""

    name = "auto"

    def __init__(self, primary: Planner, fallback: Planner) -> None:
        self.primary = primary
        self.fallback = fallback

    def plan(self, request: PlanningRequest) -> ExecutionPlan:
        try:
            return self.primary.plan(request)
        except PlannerError as exc:
            plan = self.fallback.plan(request)
            plan.assumptions.append(
                f"LLM Planner 不可用，已回退到规则 Planner：{type(exc).__name__}"
            )
            plan.planner = "auto:rule-fallback"
            return plan


def build_planner(
    settings: Settings,
    registry: ToolRegistry,
    repository: BankingRepository | None = None,
) -> Planner:
    mode = settings.planner_mode
    baseline = RuleBasedPlanner(registry, repository)
    rule = SemanticPlanner(baseline) if settings.semantic_enabled else baseline
    if mode == "rule":
        return rule
    if mode not in {"llm", "auto"}:
        raise PlannerConfigurationError(f"未知 planner_mode：{mode}")

    if not settings.llm_base_url or not settings.llm_model:
        if mode == "auto":
            return rule
        raise PlannerConfigurationError(
            "planner_mode=llm 时必须配置 AEGIS_LLM_BASE_URL 和 AEGIS_LLM_MODEL。"
        )

    if settings.semantic_enabled:
        llm = SemanticPlanner(
            baseline,
            SemanticModel(
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                credential=settings.llm_api_key,
                timeout=settings.llm_timeout_seconds,
            ),
        )
        return FallbackPlanner(llm, rule) if mode == "auto" else llm

    llm = OpenAICompatiblePlanner(
        registry=registry,
        base_url=settings.llm_base_url,
        credential=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        repository=repository,
    )
    return FallbackPlanner(llm, rule) if mode == "auto" else llm


def describe_planner(planner: Planner) -> dict[str, str]:
    active = planner.primary if isinstance(planner, FallbackPlanner) else planner
    return {
        "mode": planner.name,
        "contract": "ExecutionPlan/v1",
        "semantic_contract": getattr(active, "semantic_contract", "disabled"),
    }
