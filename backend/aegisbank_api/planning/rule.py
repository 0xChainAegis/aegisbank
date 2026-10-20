"""Deterministic planner used as the local default and LLM fallback."""

from __future__ import annotations

import re

from ..registry import ToolRegistry
from .contracts import ExecutionPlan, PlanningRequest, PlanStep


class RuleBasedPlanner:
    """A safe, deterministic planner that never calls a tool by itself."""

    name = "rule"

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def plan(self, request: PlanningRequest) -> ExecutionPlan:
        if request.tool_name:
            return self._explicit_tool_plan(request)
        return self._infer_plan(request)

    def _explicit_tool_plan(self, request: PlanningRequest) -> ExecutionPlan:
        return ExecutionPlan(
            intent=request.tool_name or "unknown",
            planner=self.name,
            confidence=1.0,
            assumptions=["用户显式指定了工具节点，参数由请求提供。"],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name=request.tool_name or "",
                    arguments=dict(request.arguments),
                    description=f"执行用户显式选择的工具：{request.tool_name}",
                )
            ],
        )

    def _infer_plan(self, request: PlanningRequest) -> ExecutionPlan:
        text = request.instruction.lower()
        accounts = re.findall(r"ACC-\d{3,}", request.instruction, re.IGNORECASE)
        amounts = re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:元|rmb|cny)", request.instruction, re.IGNORECASE
        )
        if any(word in text for word in ("转账", "汇款", "transfer")):
            return self._transfer_plan(request, accounts, amounts)
        if any(word in text for word in ("还款日", "repayment")):
            return self._repayment_plan(request)
        if any(word in text for word in ("账单", "余额", "bill", "statement")):
            return self._bill_plan(request, accounts)
        return self._clarification(
            "暂时无法识别该指令。请说明要查询账单、调整还款日，还是进行小额转账。",
            intent="unknown",
        )

    def _transfer_plan(
        self, request: PlanningRequest, accounts: list[str], amounts: list[str]
    ) -> ExecutionPlan:
        if not amounts:
            return self._clarification("请补充转账金额，例如向 ACC-2002 转账 880 元。", "transfer")
        if not accounts:
            return self._clarification("请补充收款账户，例如向 ACC-2002 转账 880 元。", "transfer")
        assumptions: list[str] = []
        if len(accounts) == 1:
            from_account = "ACC-1001"
            to_account = accounts[0]
            assumptions.append("未指定转出账户，默认使用演示账户 ACC-1001。")
        else:
            from_account, to_account = accounts[0], accounts[1]
        return ExecutionPlan(
            intent="transfer",
            planner=self.name,
            confidence=0.93,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="transfer",
                    arguments={
                        "from_account": from_account,
                        "to_account": to_account,
                        "amount_cny": float(amounts[0]),
                        "note": request.instruction[:120],
                    },
                    description="向指定账户发起小额转账。",
                )
            ],
        )

    def _repayment_plan(self, request: PlanningRequest) -> ExecutionPlan:
        day_match = re.search(r"(\d{1,2})\s*(?:日|号)", request.instruction)
        if not day_match:
            return self._clarification(
                "请补充目标还款日，例如把还款日调整到每月 18 日。", "adjust_repayment_date"
            )
        card_match = re.search(r"CARD-\d{3,}", request.instruction, re.IGNORECASE)
        return ExecutionPlan(
            intent="adjust_repayment_date",
            planner=self.name,
            confidence=0.95,
            assumptions=[] if card_match else ["未指定卡片，默认使用演示卡片 CARD-8821。"],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="adjust_repayment_date",
                    arguments={
                        "card_id": card_match.group(0) if card_match else "CARD-8821",
                        "new_day": int(day_match.group(1)),
                    },
                    description="修改信用卡每月还款日。",
                )
            ],
        )

    def _bill_plan(self, request: PlanningRequest, accounts: list[str]) -> ExecutionPlan:
        assumptions = [] if accounts else ["未指定账户，默认查询演示账户 ACC-1001。"]
        return ExecutionPlan(
            intent="query_bill",
            planner=self.name,
            confidence=0.98,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="query_bill",
                    arguments={
                        "account_id": accounts[0] if accounts else "ACC-1001",
                        "period": "current_month",
                    },
                    description="查询指定账户的本月账单。",
                )
            ],
        )

    @staticmethod
    def _clarification(message: str, intent: str = "clarification") -> ExecutionPlan:
        return ExecutionPlan(
            intent=intent,
            planner="rule",
            confidence=0.25,
            needs_clarification=True,
            clarification=message,
        )
