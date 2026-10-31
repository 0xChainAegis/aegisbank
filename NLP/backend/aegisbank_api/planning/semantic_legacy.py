"""Whole-expression admission for legacy rule plans.

A substring rule is not evidence that an entire instruction was understood.
This compatibility gate accepts a small grammar for known old expressions,
then checks its explicit values against the proposed plan. It never executes
or authorizes a tool. New language must be added to the semantic catalogue or
this auditable grammar; an unknown suffix is not treated as a harmless note.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from sqlite3 import Error as SqliteError

from ..banking.repository import SHANGHAI_TZ
from .amounts import AmountError, parse_amount
from .semantic_catalog import MONEY, collect_entity_facts

_AMOUNT = rf"(?:人民币|CNY|RMB)?(?P<amount>{MONEY})(?:元|块钱|块|人民币|CNY|RMB)?"
_ACCOUNT = r"ACC-\d{3,}"
_QUERY = r"(?:查|查询|查看|看看|看下|分析|生成|统计|汇总)(?:一下)?"


def _text(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("。！!？?")


def _match(pattern: str, text: str):
    return re.fullmatch(pattern, text, re.I)


def _aliases(rows) -> str:
    names = {_text(name) for _identity, aliases in rows for name in aliases if name}
    return "(?:" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + ")"


def _number(raw, value) -> bool:
    try:
        return raw is not None and parse_amount(raw) == Decimal(str(value))
    except (AmountError, ValueError, TypeError, InvalidOperation):
        return False


def _one_fact(rows, token):
    hits = [
        (identity, names)
        for identity, names in rows
        if any(_text(name).casefold() == token.casefold() for name in names)
    ]
    return hits[0] if len(hits) == 1 else None


def _contact_rows(repository, user_id):
    from ..scenarios.transfers import contact_rows

    return contact_rows(repository.db, user_id)


def _card_ok(text, arguments, repository, user_id) -> bool:
    from .intents import resolve_card_reference

    result = resolve_card_reference(text, repository, user_id)
    if result.card_id:
        return result.card_id == arguments.get("card_id")
    # The old planner has a visible, single-card policy when no card was named.
    # Do not admit an unresolved explicit reference through that policy.
    if result.reference is not None or repository is None:
        return False
    cards = repository.cards(user_id)
    return len(cards) == 1 and cards[0].card_id == arguments.get("card_id")


def _card_plan(text, tool, arguments, repository, user_id):
    ref = r"(?:CARD-[A-Za-z0-9_-]+|(?:尾号|末四位|后四位|末位)\d{3,4}|\d{3,4}(?:的)?卡(?:片)?)"
    unit = rf"(?:我的?|我那张|那张|这张)?(?:信用卡|卡片|卡)?{ref}(?:的)?(?:信用卡|卡片|卡)?"
    target = rf"(?:{unit}(?:[和,，（）()]?{unit})*[）)]?|(?:我的?)?(?:信用卡|卡片|卡))"
    patterns = {
        "report_card_lost": [
            rf"(?:挂失|冻结){target}",
            rf"{target}(?:挂失|冻结|丢了|遗失|不见了|被盗了)",
            rf"{target}(?:丢了|遗失|不见了)[，,](?:帮我)?挂失",
            rf"(?:我的)?卡(?:片)?(?:丢了|不见了)[，,](?:帮我)?(?:冻结|挂失){target}",
        ],
        "unlock_card": [
            rf"(?:解挂|解除挂失|解除卡片挂失|解锁卡片挂失|取消挂失|撤销挂失|unlock){target}",
            rf"{target}(?:解挂|解除挂失)",
        ],
        "reset_card_password": [
            rf"(?:重置|修改)(?:卡片)?密码{target}",
            rf"(?:重置|修改){target}(?:的)?密码",
            rf"{target}(?:的)?密码(?:重置|修改)",
        ],
        "unlock_transaction_limit": [
            rf"(?:解锁|恢复)(?:卡片)?交易限额{target}",
            rf"(?:把|将)?{target}(?:的)?交易限额(?:解锁|恢复)(?:到{_AMOUNT})?",
        ],
        "adjust_card_limit": [
            rf"(?:把|将)?{target}(?:的)?(?:信用卡|消费)?额度(?:调整到|调整为|改到|改为|调到|设为|设置为){_AMOUNT}",
        ],
        "set_transaction_limit": [
            rf"(?:把|将)?{target}(?:的)?(?:单日|每日)?交易限额(?:调整到|调整为|改到|改为|设为|设置为){_AMOUNT}",
        ],
        "adjust_repayment_date": [
            rf"(?:把|将)?{target}(?:的)?还款日(?:期)?(?:调整到|调整为|改到|改为|设为|设置为)(?:每月)?(?P<day>\d{{1,2}})(?:日|号)",
            r"(?:把|将)?还款日(?:期)?(?:调整到|调整为|改到|改为|设为|设置为)(?:每月)?(?P<day>\d{1,2})(?:日|号)",
        ],
    }
    for pattern in patterns.get(tool, []):
        match = _match(pattern, text)
        if not match or not _card_ok(text, arguments, repository, user_id):
            continue
        values = match.groupdict()
        if "day" in values and int(values["day"]) != arguments.get("new_day"):
            return False
        if values.get("amount") is not None:
            key = {
                "adjust_card_limit": "new_limit_cny",
                "set_transaction_limit": "daily_limit_cny",
                "unlock_transaction_limit": "daily_limit_cny",
            }.get(tool)
            if not key or not _number(values["amount"], arguments.get(key)):
                return False
        return True
    return False


def _account_transfer(text, arguments):
    patterns = [
        rf"(?:再)?(?:从(?P<source>{_ACCOUNT}))?(?:向|给)(?P<target>{_ACCOUNT})(?:转账|转|汇款){_AMOUNT}",
        rf"(?:再)?(?:转账|转|汇款){_AMOUNT}(?:给|到)(?P<target>{_ACCOUNT})",
    ]
    for pattern in patterns:
        match = _match(pattern, text)
        if match:
            values = match.groupdict()
            return (
                arguments.get("from_account") == (values.get("source") or "ACC-1001").upper()
                and arguments.get("to_account") == values["target"].upper()
                and _number(values["amount"], arguments.get("amount_cny"))
            )
    return False


def _contact_transfer(text, arguments, repository, user_id):
    rows = collect_entity_facts(repository, user_id, "contact")
    pattern = (
        rf"(?:给|向)(?P<contact>{_aliases(rows)})"
        rf"(?:转账|汇款|打款|转|汇|打|划)(?:个|笔)?(?:补充信息：)?{_AMOUNT}"
    )
    match = _match(pattern, text)
    if not match:
        return False
    hit = _one_fact(rows, match["contact"])
    return (
        hit is not None
        and hit[0] == arguments.get("to_phone")
        and _number(match["amount"], arguments.get("amount_cny"))
    )


def _subscription(text, arguments, repository, user_id):
    rows = collect_entity_facts(repository, user_id, "subscription")
    # Spoken fillers are not part of the merchant identity: "健身房那个月卡"
    # must still resolve to the single controlled fact "健身房月卡".
    text = re.sub(r"(?:那个|这个|那张|这张|一下)", "", text)
    rows = [
        (
            identity,
            [re.sub(r"(?:那个|这个|那张|这张|一下)", "", name) for name in names],
        )
        for identity, names in rows
    ]
    increased = {
        item.subscription_id
        for item in repository.subscriptions(user_id)
        if item.status == "active" and re.search(r"涨价|上涨", str(item.risk_flag or ""))
    }
    rows = [
        (identity, names + (["那个涨价的订阅", "涨价的订阅"] if identity in increased else []))
        for identity, names in rows
    ]
    target = rf"(?P<subscription>{_aliases(rows)})"
    for pattern in [
        rf"(?:取消|关闭|关掉|退订|退掉|终止|停掉)(?:那个)?(?:订阅)?{target}",
        rf"(?:把|将){target}(?:取消|取消掉|关闭|关掉|退订|退掉|终止|停掉)",
    ]:
        match = _match(pattern, text)
        if match:
            hit = _one_fact(rows, match["subscription"])
            return hit is not None and hit[0] == arguments.get("subscription_id")
    return False


def _aa(text, steps, repository, user_id):
    rows = collect_entity_facts(repository, user_id, "contact")
    contact = _aliases(rows)
    match = _match(rf"和(?P<people>{contact}(?:[、,，和]{contact})+)AA{_AMOUNT}", text)
    if not match:
        return False
    tokens = re.split(r"[、,，和]", match["people"])
    contacts = [_one_fact(rows, token) for token in tokens]
    if any(contact is None for contact in contacts) or len(contacts) != len(steps):
        return False
    identities = [contact[0] for contact in contacts]
    if len(identities) != len(set(identities)):
        return False
    total = parse_amount(match["amount"])
    cents = int(total * 100)
    each, remainder = divmod(cents, len(contacts) + 1)
    for index, (identity, step) in enumerate(zip(identities, steps, strict=True)):
        expected = Decimal(each + (remainder if index == len(steps) - 1 else 0)) / 100
        if (
            step.arguments.get("to_phone") != identity
            or Decimal(str(step.arguments.get("amount_cny"))) != expected
        ):
            return False
    return True


def _birthday(text, steps, repository, user_id):
    rows = collect_entity_facts(repository, user_id, "contact")
    match = _match(
        rf"(?:准备|筹备|安排)(?P<period>下个月)?(?P<contact>{_aliases(rows)})(?:的)?生日[，,]?预算{_AMOUNT}",
        text,
    )
    if not match:
        return False
    hit = _one_fact(rows, match["contact"])
    if hit is None or steps[0].arguments.get("to_name") != hit[1][0]:
        return False
    if not _number(match["amount"], steps[1].arguments.get("amount_cny")):
        return False
    if match["period"]:
        from ..banking.repository import _shanghai_now

        current = _shanghai_now().date()
        contact = next((c for c in _contact_rows(repository, user_id) if c.phone == hit[0]), None)
        if contact is None or not contact.birthday:
            return False
        birthday = datetime.fromisoformat(contact.birthday).date()
        # A stated month may not be silently dropped by the old birthday plan.
        if birthday.month != current.month % 12 + 1:
            return False
    expected = [[], [steps[0].id], [steps[0].id, steps[1].id], [steps[0].id, steps[1].id]]
    return [step.depends_on for step in steps] == expected and all(
        step.arguments.get("goal_id") == "${steps.step-2.data.goal_id}"
        and step.arguments.get("birthday") == "${steps.step-1.data.next_birthday}"
        for step in steps[2:]
    )


def _scheduled(text, arguments, repository, user_id):
    rows = collect_entity_facts(repository, user_id, "contact")
    when = r"(?:明天|后天|下周[一二三四五六日天]|每(?:个)?月\d{1,2}[号日]|\d{4}-\d{2}-\d{2})"
    match = _match(
        rf"(?:定时)?(?P<when>{when})(?:给|向)(?P<contact>{_aliases(rows)}|{_ACCOUNT})(?:转账|转|汇款|汇){_AMOUNT}",
        text,
    )
    if not match or not _number(match["amount"], arguments.get("amount_cny")):
        return False
    token = match["contact"]
    if _match(_ACCOUNT, token):
        if arguments.get("to_account") != token.upper():
            return False
    else:
        hit = _one_fact(rows, token)
        if hit is None:
            return False
        contact = next((c for c in _contact_rows(repository, user_id) if c.phone == hit[0]), None)
        if (
            contact is None
            or arguments.get("to_name") != contact.name
            or arguments.get("to_account") != contact.account_id
        ):
            return False
    from ..scenarios.automation import _resolve_run_at

    moment, recurrence = _resolve_run_at(text, datetime.now(SHANGHAI_TZ))
    actual = datetime.fromisoformat(str(arguments.get("run_at")))
    return (
        actual.tzinfo is not None and actual == moment and arguments.get("recurrence") == recurrence
    )


def _wealth(text, tool, arguments, repository, user_id):
    from ..scenarios.wealth import _holdings, _product_tokens, _products

    products = _products(repository.db)
    aliases = [
        (p["product_id"], [p["product_id"], p["risk_level"], *_product_tokens(p)]) for p in products
    ]
    token = _aliases(aliases)
    if tool == "purchase_wealth":
        patterns = [
            rf"(?:买入|购买|买|申购){_AMOUNT}(?P<product>{token})(?:理财产品|理财)?",
            rf"(?:买入|购买|买|申购)(?P<product>{token})(?:理财产品|理财)?{_AMOUNT}",
        ]
        for pattern in patterns:
            match = _match(pattern, text)
            if match:
                hit = _one_fact(aliases, match["product"])
                return (
                    hit is not None
                    and arguments.get("product_id") == hit[0]
                    and _number(match["amount"], arguments.get("amount_cny"))
                )
    if tool == "redeem_wealth":
        if _match(r"赎回全部理财", text):
            holdings = _holdings(repository.db, user_id)
            return (
                len(holdings) == 1
                and arguments.get("amount_cny") is None
                and holdings[0]["holding_id"] == arguments.get("holding_id")
            )
        match = _match(rf"赎回(?:(?P<product>{token})(?:理财产品|理财)?)?{_AMOUNT}", text)
        if not match or not _number(match["amount"], arguments.get("amount_cny")):
            return False
        holdings = _holdings(repository.db, user_id)
        if match["product"]:
            hit = _one_fact(aliases, match["product"])
            holdings = [h for h in holdings if hit and h["product_id"] == hit[0]]
        return len(holdings) == 1 and holdings[0]["holding_id"] == arguments.get("holding_id")
    return False


def _bill_spend(text, arguments) -> bool:
    """Validate the new colloquial bill-spend grammar against the rule plan."""
    from ..scenarios.bills import _spend_category, _spend_month

    match = _match(
        r"(?:我)?(?:(?P<period>这个月|本月|上个月|上月))?(?:在)?"
        r"(?P<category>餐饮|外卖|购物|交通|订阅)?(?:上)?"
        r"(?:花了?多少钱?|花费多少|消费多少|支出多少)",
        text,
    )
    if not match:
        return False
    return (
        arguments.get("period") == "month"
        and arguments.get("month") == _spend_month(text)
        and arguments.get("category") == _spend_category(text)
    )


def allow_legacy(request, plan, repository) -> bool:
    """Admit only a complete legacy expression whose plan keeps explicit values.

    Clarification plans cannot execute and keep their detailed original reason.
    Facts are local user-scoped identity metadata; read failure denies admission.
    Supplemental request arguments are checked separately against every final
    plan field by SemanticPlanner; they never extend this expression grammar.
    """
    if plan.needs_clarification:
        return not plan.steps
    if request.tool_name or not plan.steps:
        return False
    text = _text(request.instruction)
    # Only these leading courtesy words have no business meaning.
    text = re.sub(r"^(?:(?:请|帮我|麻烦|劳驾|烦请|替我)){1,3}", "", text)
    tools = tuple(step.tool_name for step in plan.steps)
    arguments = plan.steps[0].arguments
    try:
        if tools == ("transfer",):
            return _account_transfer(text, arguments)
        if len(tools) >= 2 and set(tools) == {"transfer_to_contact"}:
            return _aa(text, plan.steps, repository, request.user_id)
        if tools == ("transfer_to_contact",):
            return _contact_transfer(text, arguments, repository, request.user_id)
        if tools == ("cancel_subscription",):
            return _subscription(text, arguments, repository, request.user_id)
        if tools == (
            "query_contact_birthday",
            "lock_budget_funds",
            "schedule_flower_order",
            "schedule_cake_order",
        ):
            return _birthday(text, plan.steps, repository, request.user_id)
        if tools == ("schedule_transfer",):
            return _scheduled(text, arguments, repository, request.user_id)
        if tools == ("query_bill", "cancel_subscription"):
            return bool(
                _match(r"分析(?:我的?|本月|我的本月)?账单并取消(?:异常|可疑)订阅", text)
            ) and (
                plan.steps[1].depends_on == [plan.steps[0].id]
                and plan.steps[1].arguments.get("subscription_id")
                == "${steps.step-1.data.suspicious_subscription_id}"
            )
        if tools == ("apply_virtual_card", "issue_virtual_card"):
            match = _match(rf"申请(?:一张)?虚拟卡(?:[，,]?(?:额度|限额){_AMOUNT})?", text)
            return (
                bool(match)
                and (
                    not match.groupdict().get("amount")
                    or _number(match["amount"], arguments.get("requested_limit_cny"))
                )
                and (
                    plan.steps[1].depends_on == [plan.steps[0].id]
                    and plan.steps[1].arguments.get("application_id")
                    == "${steps.step-1.data.application_id}"
                )
            )
        if len(tools) != 1:
            return False
        tool = tools[0]
        if tool in {
            "report_card_lost",
            "unlock_card",
            "reset_card_password",
            "unlock_transaction_limit",
            "adjust_card_limit",
            "set_transaction_limit",
            "adjust_repayment_date",
        }:
            return _card_plan(text, tool, arguments, repository, request.user_id)
        if tool in {"purchase_wealth", "redeem_wealth"}:
            return _wealth(text, tool, arguments, repository, request.user_id)
        if tool == "bill_report" and _bill_spend(text, arguments):
            return True
        if tool == "assess_wealth_risk":
            match = _match(r"我的风险偏好是(?P<level>R[1-5])", text)
            return bool(match) and arguments.get("risk_preference") == match["level"].upper()
        if tool == "cancel_scheduled_task":
            match = _match(r"取消定时任务(?P<task>TASK-[A-Za-z0-9_-]+)", text)
            return bool(match) and match["task"] == arguments.get("task_id")
        reads = {
            "query_bill": rf"{_QUERY}(?:我的?|(?P<account>{_ACCOUNT})(?:的)?)?(?:本月|这个月)?账单",
            "query_balance": (
                rf"(?:{_QUERY})?(?:我的?|(?P<account>{_ACCOUNT})(?:的)?)?"
                r"(?:账户)?余额"
            ),
            "list_subscriptions": (
                r"(?:我的订阅有哪些|"
                r"(?:查|查询|查看|看看|看下|列出)(?:一下)?(?:我的)?订阅(?:列表|清单)?|"
                r"(?:我的)?订阅(?:列表|清单)?)"
            ),
            "list_contacts": r"(?:查看|查询|看看|列出)(?:我的)?(?:联系人|通讯录)",
            "list_scheduled_tasks": r"(?:查看|查询|看看)(?:我的)?定时任务",
            "list_wealth_products": r"(?:有什么|推荐|查询|查看|列出)(?:可买的)?理财产品",
            "query_wealth_holdings": r"(?:查询|查看)?(?:我的)?理财持仓",
            "bill_report": (r"(?:生成|查询|分析)(?:我的?)?(?:(?:本月|月度)?账单报告|年度账单)"),
            "annual_bill": r"(?:生成|查询|分析)(?:我的?)?年度账单",
            "detect_bill_anomalies": (
                r"(?:最近)?(?:有没有|检查|查询|分析)?(?:账单)?"
                r"(?:异常扣费|乱扣钱|乱扣费|可疑扣费)(?:的)?"
            ),
            "identify_subscription_charges": r"(?:做|分析)?订阅扣费分析",
            "list_renewal_reminders": (
                r"(?:有哪些快到期订阅|我的订阅还有哪些要续费|"
                r"查询订阅续费提醒)"
            ),
        }
        pattern = reads.get(tool)
        if pattern:
            match = _match(pattern, text)
            return bool(match) and (
                not match.groupdict().get("account")
                or arguments.get("account_id") == match["account"].upper()
            )
        return False
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        LookupError,
        ArithmeticError,
        SqliteError,
        RuntimeError,
    ):
        return False
