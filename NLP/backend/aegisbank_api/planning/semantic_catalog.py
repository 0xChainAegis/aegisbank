"""Scenario-owned, bounded semantic bindings. No model-chosen tool names/code."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MONEY = r"[0-9０-９零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟.,，．点]+"
CURRENCY = r"\s*(?:(?:元|块钱|块)(?:人民币|CNY|RMB)?|人民币|CNY|RMB)?"
ENTITY = r"[^，,。；;!?！？\n]{1,48}?"
CARD = r"(?:CARD-\d{3,}|尾号\s*\d{4}|\d{4}\s*尾号)"
ACCOUNT = r"ACC-\d{3,}"
CURRENCY_PREFIX = r"(?:人民币|CNY|RMB)?\s*"
DATE = r"(?:明天|后天|下周[一二三四五六日天]|\d{4}-\d{2}-\d{2})"


@dataclass(frozen=True)
class SemanticSpec:
    kind: str
    patterns: tuple[str, ...]
    template: str
    slot_types: dict[str, str] = field(default_factory=dict)
    # Read-only model classifications still need an independent domain anchor.
    read_anchor: str | None = None
    tools: tuple[str, ...] = ()
    bindings: dict[str, tuple[int, str | tuple[str, ...]]] = field(default_factory=dict)


def core_specs() -> list[SemanticSpec]:
    return [
        SemanticSpec(
            "balance",
            (
                r"(?:查(?:询|看|一下)?|查查|看看|看下|查看一下)(?:我的?(?:账户)?|账户)?余额",
                r"(?:我的?)?(?:账户里)?(?:还剩|还有|剩下)(?:多少)?钱",
                rf"(?:看看|查查)?(?P<account>{ENTITY})(?:里面)?(?:还剩|还有)多少(?:钱|余额)",
                rf"(?P<account>{ENTITY})(?:账户)?余额(?:是多少|有多少)",
            ),
            "查询{account}余额",
            {"account": "account"},
            r"余额|剩.*钱|账户.*钱",
            tools=("query_balance",),
            bindings={"account": (0, "account_id")},
        ),
        SemanticSpec(
            "account_transfer",
            (
                rf"(?:向|给)(?P<account>{ACCOUNT})(?:转账|转|汇款){CURRENCY_PREFIX}(?P<amount>{MONEY}){CURRENCY}",
                rf"(?:汇款|转账|打款|转){CURRENCY_PREFIX}(?P<amount>{MONEY}){CURRENCY}(?:到|至|给)(?P<account>{ACCOUNT})",
            ),
            "向{account}转账{amount}元",
            {"account": "account", "amount": "money"},
            tools=("transfer",),
            bindings={"account": (0, "to_account"), "amount": (0, "amount_cny")},
        ),
        SemanticSpec(
            "cancel_subscription",
            (
                rf"(?:把|将)?(?P<subscription>{ENTITY})(?:的)?(?:停掉|关掉|退订|停止续费|取消掉)(?:[，,](?:之后|以后)不续了)?",
                rf"关闭(?P<subscription>{ENTITY})的自动续费",
                rf"(?P<subscription>{ENTITY})这个订阅[，,]我要停掉下次续费",
                rf"以后别(?:再)?给(?P<subscription>{ENTITY})续费(?:了)?",
                rf"(?:取消订阅|停掉|关掉|退订|停止续费)(?P<subscription>{ENTITY})",
                rf"取消(?:那个|这个)?(?P<subscription>(?!定时任务|预约|任务|订阅$){ENTITY})",
            ),
            "取消订阅 {subscription}",
            {"subscription": "subscription"},
            tools=("cancel_subscription",),
            bindings={"subscription": (0, "subscription_id")},
        ),
    ]


def collect_semantic_specs():
    from ..scenarios import iter_scenario_modules

    specs = core_specs()
    for module in iter_scenario_modules():
        factory = getattr(module, "semantic_intents", None)
        if callable(factory):
            specs.extend(factory())
    result = {spec.kind: spec for spec in specs}
    if len(result) != len(specs):
        raise ValueError("Duplicate semantic intent kind")
    return result


def collect_entity_facts(repository, user_id: str, kind: str):
    try:
        return _entity_facts(repository, user_id, kind)
    except Exception as exc:  # a failed read is never evidence for a guessed entity
        raise ValueError("实体事实暂不可用，请稍后重试") from exc


def _entity_facts(repository, user_id: str, kind: str):
    """Only identity metadata, scoped to the caller; no balances or tool execution."""
    if repository is None:
        raise ValueError("实体事实不可用，请稍后重试")
    if kind == "account":
        return [(a.account_id, [a.account_id, a.name]) for a in repository.accounts(user_id)]
    if kind == "card":
        rows = []
        for card in repository.cards(user_id):
            tail = re.search(r"(?<!\d)(\d{4})\s*$", card.masked_number)
            names = [card.card_id]
            if tail:
                names.extend(["尾号" + tail.group(1), tail.group(1) + "尾号"])
            rows.append((card.card_id, names))
        return rows
    if kind == "subscription":
        return [
            (
                s.subscription_id,
                [s.subscription_id, s.merchant, s.merchant + "订阅"]
                + (["异常订阅", "可疑订阅"] if s.risk_flag else []),
            )
            for s in repository.subscriptions(user_id)
            if s.status == "active"
        ]
    from ..scenarios import iter_scenario_modules

    rows = []
    for module in iter_scenario_modules():
        factory = getattr(module, "semantic_entities", None)
        if callable(factory):
            rows.extend(factory(repository, user_id, kind))
    return rows
