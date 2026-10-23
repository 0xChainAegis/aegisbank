"""Deterministic planner used as the local default and LLM fallback."""

from __future__ import annotations

import re

from ..banking.repository import BankingRepository
from ..registry import ToolRegistry
from .contracts import ExecutionPlan, PlanningRequest, PlanStep
from .intents import IntentContext, collect_intent_rules, extract_amounts

_CANCEL_WORDS = ("取消", "关闭", "关掉", "退订", "停掉", "cancel", "unsubscribe")
_SUBSCRIPTION_WORDS = (
    "订阅",
    "代扣",
    "自动扣费",
    "会员",
    "月卡",
    "续费",
    "subscription",
)


class RuleBasedPlanner:
    """A safe, deterministic planner that never calls a tool by itself."""

    name = "rule"

    def __init__(
        self,
        registry: ToolRegistry,
        repository: BankingRepository | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.scenario_rules = collect_intent_rules()

    def plan(self, request: PlanningRequest) -> ExecutionPlan:
        if re.search(
            r"不要|别(?:给|转|改|调|挂失|取消)|不(?:要|必|用)|暂不|取消这次|don't|do not",
            request.instruction,
            re.I,
        ):
            return self._clarification(
                "已识别否定或取消意图，不生成写操作；请明确需要查询或执行的任务。", "negated_intent"
            )
        if len(re.findall(r"转账|汇款|给.{1,12}?转|向.{1,20}?转", request.instruction)) > 1:
            return self._clarification(
                "识别到多笔转账，请分别明确每笔收款人和金额后发起。", "multiple_transfers"
            )
        write_kinds = [
            r"转账|汇款|给.{1,12}?转",
            r"挂失|解挂",
            r"额度|限额",
            r"申购|购买理财|赎回",
            r"重置密码|修改密码",
            r"取消订阅",
        ]
        if sum(bool(re.search(pattern, request.instruction)) for pattern in write_kinds) > 1:
            return self._clarification(
                "指令含多个不同写操作，请逐项明确后分别发起。", "multiple_writes"
            )
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

    def _scenario_plan(self, request: PlanningRequest) -> ExecutionPlan | None:
        if not self.scenario_rules:
            return None
        context = IntentContext(
            request=request,
            registry=self.registry,
            repository=self.repository,
        )
        for rule in self.scenario_rules:
            plan = rule.build(context)
            if plan is not None:
                return plan
        return None

    def _infer_plan(self, request: PlanningRequest) -> ExecutionPlan:
        scenario = self._scenario_plan(request)
        if scenario is not None:
            return scenario

        text = request.instruction.lower()
        accounts = re.findall(r"ACC-\d{3,}", request.instruction, re.IGNORECASE)
        card_match = re.search(r"CARD-\d{3,}", request.instruction, re.IGNORECASE)
        card_id = card_match.group(0) if card_match else "CARD-8821"
        amounts = self._amounts(request.instruction)

        if self._is_cross_scenario_subscription_flow(text):
            return self._bill_and_cancel_subscription_plan(request, accounts)
        if any(word in text for word in ("转账", "汇款", "transfer")):
            return self._transfer_plan(request, accounts, amounts)
        if any(word in text for word in ("挂失", "丢失", "report lost")):
            return self._single_plan("report_card_lost", "report_card_lost", {"card_id": card_id})
        if any(word in text for word in ("解挂", "解除挂失", "unlock")):
            return self._single_plan("unlock_card", "unlock_card", {"card_id": card_id})
        if any(word in text for word in ("交易限额", "单日限额", "transaction limit")):
            if not amounts:
                return self._clarification(
                    "请明确目标单日交易限额，不会代填金额。", "set_transaction_limit"
                )
            return self._single_plan(
                "set_transaction_limit",
                "set_transaction_limit",
                {"card_id": card_id, "daily_limit_cny": amounts[0] if amounts else 2000.0},
            )
        if any(word in text for word in ("额度", "limit")):
            if not amounts:
                return self._clarification("请明确目标额度，不会代填金额。", "adjust_card_limit")
            return self._single_plan(
                "adjust_card_limit",
                "adjust_card_limit",
                {"card_id": card_id, "new_limit_cny": amounts[0] if amounts else 5000.0},
            )
        if any(word in text for word in ("还款日", "repayment")):
            day_match = re.search(r"(\d{1,2})\s*(?:日|号)", request.instruction)
            if not day_match:
                return self._clarification(
                    "请补充目标还款日，例如把还款日调整到每月 18 日。", "adjust_repayment_date"
                )
            return self._single_plan(
                "adjust_repayment_date",
                "adjust_repayment_date",
                {"card_id": card_id, "new_day": int(day_match.group(1))},
            )
        if self._is_subscription_cancel_request(request, text):
            return self._cancel_subscription_plan(request, text)
        if any(word in text for word in ("订阅", "subscription")):
            return self._single_plan("list_subscriptions", "list_subscriptions", {})
        if any(word in text for word in ("余额", "balance")):
            return self._single_plan(
                "query_balance",
                "query_balance",
                {"account_id": accounts[0] if accounts else "ACC-1001"},
            )
        if any(word in text for word in ("账单", "bill", "statement")):
            return self._bill_plan(request, accounts)
        return self._clarification(
            "暂时无法识别该指令。可尝试：分析账单、转账、调整卡片额度/限额/还款日、挂失/解挂或取消订阅。",
            intent="unknown",
        )

    @staticmethod
    def _amounts(instruction: str) -> list[float]:
        return extract_amounts(instruction)

    @staticmethod
    def _is_cross_scenario_subscription_flow(text: str) -> bool:
        return (
            ("账单" in text or "bill" in text)
            and ("订阅" in text or "subscription" in text)
            and any(word in text for word in ("取消", "关闭", "cancel"))
        )

    def _bill_and_cancel_subscription_plan(
        self, request: PlanningRequest, accounts: list[str]
    ) -> ExecutionPlan:
        account_id = accounts[0] if accounts else "ACC-1001"
        return ExecutionPlan(
            intent="bill_analysis_and_subscription_cleanup",
            planner=self.name,
            confidence=0.9,
            assumptions=[] if accounts else ["未指定账户，默认分析演示账户 ACC-1001。"],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="query_bill",
                    arguments={"account_id": account_id, "period": "current_month"},
                    description="分析账单并定位异常订阅。",
                ),
                PlanStep(
                    id="step-2",
                    tool_name="cancel_subscription",
                    arguments={
                        "subscription_id": "${steps.step-1.data.suspicious_subscription_id}"
                    },
                    depends_on=["step-1"],
                    description="根据账单分析结果取消异常订阅。",
                ),
            ],
        )

    def _transfer_plan(
        self, request: PlanningRequest, accounts: list[str], amounts: list[float]
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
        return self._single_plan(
            "transfer",
            "transfer",
            {
                "from_account": from_account,
                "to_account": to_account,
                "amount_cny": amounts[0],
                "note": request.instruction[:120],
            },
            assumptions=assumptions,
            description="按金额和日累计动态评估风险后发起转账。",
        )

    def _bill_plan(self, request: PlanningRequest, accounts: list[str]) -> ExecutionPlan:
        return self._single_plan(
            "query_bill",
            "query_bill",
            {
                "account_id": accounts[0] if accounts else "ACC-1001",
                "period": "current_month",
            },
            assumptions=[] if accounts else ["未指定账户，默认查询演示账户 ACC-1001。"],
            description="查询并分析指定账户的本月账单。",
        )

    def _is_subscription_cancel_request(self, request: PlanningRequest, text: str) -> bool:
        if not any(word in text for word in _CANCEL_WORDS):
            return False
        if any(word in text for word in _SUBSCRIPTION_WORDS):
            return True
        if self.repository is None:
            return False
        try:
            return any(
                sub.merchant.lower() in text
                for sub in self.repository.subscriptions(request.user_id)
                if sub.status == "active"
            )
        except Exception:  # noqa: BLE001 - repository is a local mock adapter
            return False

    def _cancel_subscription_plan(self, request: PlanningRequest, text: str) -> ExecutionPlan:
        explicit = re.search(r"SUB-\d{3,}", request.instruction, re.IGNORECASE)
        if explicit:
            return self._single_plan(
                "cancel_subscription",
                "cancel_subscription",
                {"subscription_id": explicit.group(0).upper()},
            )

        subscriptions = []
        if self.repository is not None:
            try:
                subscriptions = [
                    sub
                    for sub in self.repository.subscriptions(request.user_id)
                    if sub.status == "active"
                ]
            except Exception:  # noqa: BLE001 - repository is a local mock adapter
                subscriptions = []

        matched = [sub for sub in subscriptions if sub.merchant.lower() in text]
        if len(matched) == 1:
            sub = matched[0]
            return self._single_plan(
                "cancel_subscription",
                "cancel_subscription",
                {"subscription_id": sub.subscription_id},
                description=f"取消订阅：{sub.merchant}（{sub.subscription_id}）",
            )
        if len(matched) > 1:
            names = "、".join(f"{sub.merchant}（{sub.subscription_id}）" for sub in matched)
            return self._clarification(
                f"匹配到多个订阅：{names}，请补充要取消哪一个的订阅编号。",
                "cancel_subscription",
            )

        suspicious = next((sub for sub in subscriptions if sub.risk_flag), None)
        abnormal_hint = "异常" in request.instruction or "可疑" in request.instruction
        if suspicious is not None and abnormal_hint:
            return self._single_plan(
                "cancel_subscription",
                "cancel_subscription",
                {"subscription_id": suspicious.subscription_id},
                assumptions=[
                    f"按异常标记定位到 {suspicious.merchant}（{suspicious.subscription_id}）。"
                ],
                description=f"取消异常订阅：{suspicious.merchant}（{suspicious.subscription_id}）",
            )

        if subscriptions:
            candidates = "、".join(
                f"{sub.merchant}（{sub.subscription_id}）" for sub in subscriptions
            )
            return self._clarification(
                f"请指定要取消的订阅编号，例如：取消订阅 "
                f"{subscriptions[0].subscription_id}。当前订阅：{candidates}",
                "cancel_subscription",
            )
        return self._single_plan(
            "cancel_subscription",
            "cancel_subscription",
            {"subscription_id": "SUB-3002"},
            assumptions=["未读取到订阅列表，回退到演示订阅 SUB-3002。"],
        )

    def _single_plan(
        self,
        intent: str,
        tool_name: str,
        arguments: dict[str, object],
        *,
        assumptions: list[str] | None = None,
        description: str | None = None,
    ) -> ExecutionPlan:
        return ExecutionPlan(
            intent=intent,
            planner=self.name,
            confidence=0.93,
            assumptions=assumptions or [],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name=tool_name,
                    arguments=arguments,
                    description=description or f"执行 {tool_name}。",
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
