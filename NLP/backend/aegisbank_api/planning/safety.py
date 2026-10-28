"""Shared P0 fail-closed checks before rule or model planning.

This is a bounded language guard, not a general semantic parser. Unknown
conditions/compositions must be clarified until the planner can represent them.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .amounts import AmountError, money_mentions
from .contracts import ExecutionPlan, PlanningRequest

_CONDITION = re.compile(
    r"如果|假如|假设|倘若|若|只要|只有|除非|否则|前提|满足|"
    r"(?:余额|钱|资金).{0,16}(?:足够|不足|够|超过|大于|小于|高于|低于|至少|不低于|[><≥≤])|"
    r"(?:成功|失败|到账|完成)后(?:再|才)|有钱再|到时候再决定|"
    r"\b(?:if|unless|provided|when|otherwise|only\s+after)\b",
    re.I,
)
_ACTION = re.compile(
    r"查询|查看|查一下|查(?=余额|账单|订阅|联系人)|看看|分析|生成|"
    r"转账|汇款|打款|转(?=\s*[0-9０-９零一二两三四五六七八九十百千万¥￥])|"
    r"取消|退订|退掉|终止|关闭|关掉|停掉|挂失|解挂|冻结|申购|赎回|购买|买入|"
    r"调整|设置|恢复|重置|修改|申请|解锁|准备|安排|预约|"
    r"\b(?:query|check|list|transfer|send|cancel|unsubscribe|report|adjust|schedule)\b",
    re.I,
)
_SEQUENCE = re.compile(
    r"然后|接着|顺便|同时|以及|之后再|再(?:给|向|查|转|取消|调整)|"
    r"并(?:且)?(?:给|向|查|转|取消|调整|挂失)|\b(?:then|also|and)\b",
    re.I,
)
# Full-string whitelist: adding another action/target must not inherit this exception.
_BILL_CLEANUP = re.compile(
    r"\s*(?:请|帮我)?\s*(?:先)?(?:分析|查询|查看)(?:一下)?(?:我的?|本月|当前|这个月|\s)*账单"
    r"\s*(?:[,，]?\s*(?:并|然后|再|并且)\s*)"
    r"取消(?:异常|可疑)订阅[。！!\s]*"
)
_DOMAINS = (
    r"余额|\bbalance\b",
    r"账单|消费报告|支出报告|\bbill\b",
    r"订阅|会员|代扣|自动扣费|\bsubscription\b",
    r"转账|汇款|打款|(?:给|向).{1,20}转|(?:^|[\s，,。；;！!])(?:请|帮我|给我|给|向|从|帮|替)?\s*转|\btransfer\b",
    r"(?:信用卡)?额度|限额",
    r"还款日",
    r"挂失|解挂|冻结|丢失|遗失|卡.{0,6}(?:丢|不见|遗失|被盗)",
    r"密码",
    r"理财|持仓",
    r"生日",
    r"\baa\b",
)
_MONEY_FIELDS = {"amount_cny", "new_limit_cny", "daily_limit_cny", "requested_limit_cny"}


def clarification(message: str, intent: str) -> ExecutionPlan:
    return ExecutionPlan(
        intent=intent,
        planner="safety",
        confidence=0.0,
        needs_clarification=True,
        clarification=message,
    )


def planning_clarification(request: PlanningRequest) -> ExecutionPlan | None:
    text = request.instruction
    if _CONDITION.search(text):
        return clarification(
            "当前无法完整执行条件任务，不会忽略条件生成操作；请先查询条件，"
            "确认满足后再单独发起操作。",
            "unsupported_condition",
        )
    try:
        mentions = money_mentions(text)
    except AmountError as exc:
        return clarification(str(exc), "ambiguous_amount")
    values = {m.value for m in mentions}
    if len(values) > 1:
        return clarification(
            "指令包含多个金额，暂不能可靠区分目标金额、预算或修改前后的值；"
            "请分别明确任务与最终金额。",
            "ambiguous_amount",
        )
    for key in _MONEY_FIELDS & request.arguments.keys():
        if values and str(request.arguments[key]) not in {"None", "True", "False"}:
            try:
                agrees = Decimal(str(request.arguments[key])) in values
            except InvalidOperation:
                agrees = False
            if not agrees:
                return clarification(
                    "显式参数与指令金额不一致，请明确最终金额。", "amount_conflict"
                )
    for kind in ("CARD", "SUB", "TASK"):
        identifiers = re.findall(rf"{kind}-[A-Za-z0-9]+", text, re.I)
        if kind == "CARD":
            identifiers = [value.upper() for value in identifiers]
        if len(set(identifiers)) > 1:
            return clarification("指令包含多个操作对象，请分别明确任务。", "multiple_targets")
    if len(set(re.findall(r"(?<!\d)1[3-9]\d{9}(?!\d)", text))) > 1 and not re.search(
        r"\baa\b", text, re.I
    ):
        return clarification("识别到多个联系人号码，请分别明确任务。", "multiple_targets")
    if re.search(
        r"所有|全部|分别|各自|每张|每个|[两二三四五六七八九十]+(?:张|个|笔)", text
    ) and re.search(r"挂失|取消|退订|调整|设置|转账|重置", text):
        return clarification("批量操作目标尚不能完整解析，请分别发起。", "multiple_targets")
    accounts = re.findall(r"ACC-\d{3,}", text, re.I)
    if len(accounts) > 1 and not (
        len(accounts) == 2
        and re.search(r"从\s*ACC-\d+.*(?:向|到|至|给)\s*ACC-\d+", text, re.I)
        and "转账" in text
    ):
        return clarification("多个账户的用途或转账方向不明确，请分别说明。", "multiple_targets")
    if _BILL_CLEANUP.fullmatch(text) and not request.tool_name:
        return None
    actions = list(_ACTION.finditer(text))
    domains = sum(bool(re.search(pattern, text, re.I)) for pattern in _DOMAINS)
    # Read-only subscription bill analysis is a single supported domain query.
    subscription_report = (
        domains == 2
        and "账单" in text
        and "订阅" in text
        and len(actions) <= 1
        and not _SEQUENCE.search(text.lstrip().removeprefix("再"))
    )
    if (
        len(actions) > 1
        or _SEQUENCE.search(text.lstrip().removeprefix("再"))
        or (domains > 1 and not subscription_report)
    ):
        return clarification(
            "识别到组合任务或多个操作目标，当前不能保证完整保留所有步骤和顺序；"
            "请分别发起，系统不会只执行其中一部分。",
            "unsupported_composition",
        )
    return None
