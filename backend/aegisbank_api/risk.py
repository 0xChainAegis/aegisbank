"""Dynamic risk engine for banking operations.

The tool manifest declares a baseline risk. The engine may only keep or
escalate that risk using deterministic facts: amount, daily transfer total,
card state, and operation type. LLM output is never trusted as a risk input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .banking.repository import BankingRepository
from .domain import RiskLevel
from .risk_rules import RiskContext, RiskRule, collect_risk_rules

_RISK_ORDER = {RiskLevel.GREEN: 0, RiskLevel.YELLOW: 1, RiskLevel.RED: 2}


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel
    score: int
    reasons: list[str]
    base_risk: RiskLevel
    requires_reauth: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "score": self.score,
            "reasons": self.reasons,
            "base_risk": self.base_risk.value,
            "requires_reauth": self.requires_reauth,
        }


class DynamicRiskEngine:
    def __init__(
        self,
        repository: BankingRepository,
        rules: list[RiskRule] | None = None,
    ) -> None:
        self.repository = repository
        # Scenario modules contribute deterministic rules for their own tools.
        self.rules: list[RiskRule] = collect_risk_rules() if rules is None else list(rules)

    @staticmethod
    def max_level(*levels: RiskLevel) -> RiskLevel:
        return max(levels, key=lambda level: _RISK_ORDER[level])

    def _assessment(
        self,
        *,
        level: RiskLevel,
        base_risk: RiskLevel,
        reasons: list[str],
        score: int,
    ) -> RiskAssessment:
        final_level = self.max_level(base_risk, level)
        return RiskAssessment(
            level=final_level,
            score=score,
            reasons=reasons,
            base_risk=base_risk,
            requires_reauth=final_level is RiskLevel.RED,
        )

    def _scenario_assessment(
        self,
        *,
        user_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        base_risk: RiskLevel,
        instruction: str,
    ) -> RiskAssessment | None:
        """Let scenario modules score their own tools; core tools are untouched."""
        if not self.rules:
            return None
        context = RiskContext(
            user_id=user_id,
            tool_name=tool_name,
            arguments=arguments,
            base_risk=base_risk,
            instruction=instruction,
            repository=self.repository,
        )
        for rule in self.rules:
            guess = rule.assess(context)
            if guess is not None:
                return self._assessment(
                    level=guess.level,
                    base_risk=base_risk,
                    reasons=list(guess.reasons),
                    score=guess.score,
                )
        return None

    def assess(
        self,
        *,
        user_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        base_risk: RiskLevel,
        instruction: str = "",
    ) -> RiskAssessment:
        restore_limits = {
            "restore_card_limit": "previous_limit_cny",
            "restore_transaction_limit": "previous_transaction_limit_cny",
        }
        if tool_name in restore_limits:
            data = (arguments.get("original_result") or {}).get("data") or {}
            amount = float(data.get(restore_limits[tool_name]) or 0)
            return self._assessment(
                level=RiskLevel.RED if amount > 5000 else RiskLevel.YELLOW,
                base_risk=base_risk,
                reasons=[f"补偿实际恢复额度 {amount:.2f} 元，按目标额度重新评估风险。"],
                score=85 if amount > 5000 else 45,
            )
        scenario = self._scenario_assessment(
            user_id=user_id,
            tool_name=tool_name,
            arguments=arguments,
            base_risk=base_risk,
            instruction=instruction,
        )
        if scenario is not None:
            return scenario

        if tool_name == "transfer":
            amount = float(arguments.get("amount_cny") or 0)
            daily = self.repository.daily_transfer_total_cny(user_id)
            projected = round(daily + amount, 2)
            if amount > 5000:
                return self._assessment(
                    level=RiskLevel.RED,
                    base_risk=base_risk,
                    reasons=[
                        f"单笔转账 {amount:.2f} 元超过 5000 元高风险阈值。",
                        f"今日累计转账将达到 {projected:.2f} 元。",
                    ],
                    score=100,
                )
            if projected > 1000:
                return self._assessment(
                    level=RiskLevel.RED,
                    base_risk=base_risk,
                    reasons=[
                        f"今日累计转账将达到 {projected:.2f} 元，超过 1000 元上限。",
                        "需要红色强验证和明确确认。",
                    ],
                    score=80,
                )
            return self._assessment(
                level=RiskLevel.YELLOW,
                base_risk=base_risk,
                reasons=[
                    f"小额转账 {amount:.2f} 元，今日累计 {projected:.2f} 元，未超过 1000 元。",
                    "需要黄色操作确认。",
                ],
                score=40,
            )

        if tool_name == "adjust_card_limit":
            amount = float(arguments.get("new_limit_cny") or 0)
            if amount > 5000:
                return self._assessment(
                    level=RiskLevel.RED,
                    base_risk=base_risk,
                    reasons=[f"调整信用额度至 {amount:.2f} 元，超过 5000 元阈值。"],
                    score=85,
                )
            return self._assessment(
                level=RiskLevel.YELLOW,
                base_risk=base_risk,
                reasons=["信用卡额度调整需要用户确认。"],
                score=45,
            )

        if tool_name == "set_transaction_limit":
            amount = float(arguments.get("daily_limit_cny") or 0)
            if amount > 5000:
                return self._assessment(
                    level=RiskLevel.RED,
                    base_risk=base_risk,
                    reasons=[f"设置交易限额至 {amount:.2f} 元，超过 5000 元阈值。"],
                    score=85,
                )
            return self._assessment(
                level=RiskLevel.YELLOW,
                base_risk=base_risk,
                reasons=["信用卡交易限额调整需要用户确认。"],
                score=45,
            )

        if tool_name in {"report_card_lost", "unlock_card"}:
            return self._assessment(
                level=RiskLevel.RED,
                base_risk=base_risk,
                reasons=["卡片挂失/解挂属于高风险账户安全操作，需要强验证。"],
                score=90,
            )

        if tool_name in {
            "adjust_repayment_date",
            "set_transaction_limit",
            "cancel_subscription",
        }:
            return self._assessment(
                level=RiskLevel.YELLOW,
                base_risk=base_risk,
                reasons=["该操作会修改账户设置或订阅状态，需要用户确认。"],
                score=45,
            )

        if tool_name in {"query_bill", "list_subscriptions"}:
            return self._assessment(
                level=RiskLevel.GREEN,
                base_risk=base_risk,
                reasons=["只读查询操作，满足最小权限后自动执行。"],
                score=10,
            )

        return self._assessment(
            level=base_risk,
            base_risk=base_risk,
            reasons=["使用工具声明的基线风险等级。"],
            score=50 if base_risk is not RiskLevel.GREEN else 10,
        )
