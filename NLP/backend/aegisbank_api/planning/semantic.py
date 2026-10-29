"""Verified, bounded SemanticFrame -> existing deterministic execution plan."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, DecimalException

from ..banking.repository import SHANGHAI_TZ
from .amounts import AmountError, parse_amount
from .contracts import ExecutionPlan
from .safety import _CONDITION, planning_clarification
from .semantic_catalog import collect_entity_facts, collect_semantic_specs
from .semantic_contracts import (
    SemanticAnalysis,
    SemanticFrame,
    SemanticIntent,
    SlotEvidence,
    TextSpan,
)
from .semantic_legacy import allow_legacy

_SLOT_LABELS = {
    "money": "金额",
    "amount": "金额",
    "account": "账户",
    "card": "卡片",
    "subscription": "订阅",
    "contact": "收款人",
    "contact_name": "联系人",
    "product": "理财产品",
    "day": "还款日",
    "date": "执行日期",
    "month": "月份",
}


def _slot_label(key: str) -> str:
    return _SLOT_LABELS.get(key, "目标信息")


def _account_key(value: str) -> str:
    text = value.strip().casefold().replace(" ", "")
    return text[2:] if text.startswith("我的") else text[1:] if text.startswith("我") else text


# A clause boundary may not split a thousands separator.
_SEPARATOR = re.compile(r"(?<!\d)[,，]|[,，](?!\d)|[。；;！!？?\n]+")
_NEGATIVE = re.compile(r"^(?:不要|暂不|不必|别)(?:再)?")
_NEGATIVE_TOPICS = {
    "contact_transfer": r"转账|汇款|打款|转钱",
    "cancel_subscription": r"取消[^,，。；;\n]*订阅|退订[^,，。；;\n]*",
    "card_limit": r"调[^,，。；;\n]*额度|修改[^,，。；;\n]*额度",
    "wealth_purchase": r"买[^,，。；;\n]*理财|申购[^,，。；;\n]*",
}


class SemanticError(ValueError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or []


def span(text, start, end):
    return TextSpan(start=start, end=end, text=text[start:end])


def _body(text, start, end):
    while start < end and (text[start].isspace() or text[start] in "，,。；;！!？?"):
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in "，,。；;！!？?"):
        end -= 1
    return start, end


def _match(text, start, end, specs):
    start, end = _body(text, start, end)
    if start == end:
        return None
    original_start = start
    polite = re.match(
        r"(?:(?:请|麻烦(?:你|您)?|劳驾|帮我|替我|烦请|能否|我想)\s*){1,3}", text[start:end]
    )
    if polite:
        start += polite.end()
    negative = _NEGATIVE.match(text[start:end])
    if negative:
        start += negative.end()
    else:
        # Explicitly scoped positive read after a denied action.
        positive = re.match(r"(?:只|仅)(?:需|要)?", text[start:end])
        if positive:
            start += positive.end()
    for spec in specs.values():
        for pattern in spec.patterns:
            match = re.fullmatch(pattern, text[start:end], re.I)
            if match:
                slots = {
                    key: span(text, start + match.start(key), start + match.end(key))
                    for key, value in match.groupdict().items()
                    if value is not None
                }
                return SemanticIntent(
                    id="i",
                    kind=spec.kind,
                    span=span(text, original_start, end),
                    polarity="negative" if negative else "affirmative",
                    slots=slots,
                )
    if negative:
        for kind, pattern in _NEGATIVE_TOPICS.items():
            if re.fullmatch(pattern, text[start:end]):
                return SemanticIntent(
                    id="i", kind=kind, span=span(text, original_start, end), polarity="negative"
                )
    return None


def analyze_rules(text, specs=None):
    specs = specs or collect_semantic_specs()
    condition_matches = list(_CONDITION.finditer(text))
    if len(condition_matches) > 12 or len(list(_SEPARATOR.finditer(text))) > 23:
        return SemanticFrame(
            uncovered=[span(text, 0, len(text))],
            needs_clarification=True,
            clarification="指令分句过多，请分成较短的完整任务。",
        )
    conditions = [span(text, m.start(), m.end()) for m in condition_matches]
    whole = _match(text, 0, len(text), specs)
    if whole:
        whole.id = "i1"
        return SemanticFrame(intents=[whole], conditions=conditions)
    intents, uncovered = [], []
    start = 0
    for end, next_start in [(m.start(), m.end()) for m in _SEPARATOR.finditer(text)] + [
        (len(text), len(text))
    ]:
        left, right = _body(text, start, end)
        if left < right:
            item = _match(text, left, right, specs)
            if item:
                item.id = f"i{len(intents) + 1}"
                intents.append(item)
            else:
                uncovered.append(span(text, left, right))
        start = next_start
    if len(intents) > 12 or len(uncovered) > 24:
        return SemanticFrame(
            uncovered=[span(text, 0, len(text))],
            needs_clarification=True,
            clarification="指令分句过多，请分成较短的完整任务。",
        )
    return SemanticFrame(
        intents=intents,
        conditions=conditions,
        uncovered=uncovered,
        needs_clarification=bool(uncovered),
    )


def _check_span(item, text):
    if item.end > len(text) or text[item.start : item.end] != item.text:
        raise SemanticError("语义候选的原文位置或内容不匹配，不能验证来源")


def _candidate_shape(frame, text, specs):
    if frame.needs_clarification or frame.uncovered or frame.missing_slots:
        raise SemanticError(frame.clarification or "仍有未理解的片段，请明确任务")
    if frame.conditions or _CONDITION.search(text):
        raise SemanticError("已保留条件，但当前不执行条件任务；请先确认条件再单独发起")
    if frame.ordering:
        raise SemanticError("已保留步骤顺序，通用组合执行尚未开放，请分别发起")
    covered = set()
    for item in frame.intents:
        _check_span(item.span, text)
        positions = set(range(item.span.start, item.span.end))
        if positions & covered:
            raise SemanticError("意图片段重叠，不能证明任务完整性")
        covered |= positions
        spec = specs.get(item.kind)
        if spec is None:
            raise SemanticError("语义意图不在已注册目录内")
        for slot in item.slots.values():
            _check_span(slot, text)
            if not (item.span.start <= slot.start < slot.end <= item.span.end):
                raise SemanticError("槽位必须来自对应意图的原文片段")
        expected = _match(text, item.span.start, item.span.end, specs)
        if expected is not None:
            if (expected.kind, expected.polarity, expected.slots) != (
                item.kind,
                item.polarity,
                item.slots,
            ):
                raise SemanticError("意图、否定作用域或槽位与独立解析结果冲突")
        else:
            raise SemanticError("该表达尚不能独立验证，请提供更明确的指令")
    if any(
        i not in covered and not (c.isspace() or c in "，,。；;！!？?") for i, c in enumerate(text)
    ):
        raise SemanticError("语义候选遗漏了原始指令片段，不能生成部分计划")
    affirmative = [i for i in frame.intents if i.polarity == "affirmative"]
    if len(affirmative) != 1:
        raise SemanticError("请明确一个要执行的任务；否定动作不会执行")
    if len(frame.intents) > 1 and not specs[affirmative[0].kind].read_anchor:
        raise SemanticError("混合否定与写操作尚不执行，请单独发起明确任务")
    return affirmative[0]


def _resolve_date(raw, today):
    if raw == "明天":
        result = today + timedelta(days=1)
    elif raw == "后天":
        result = today + timedelta(days=2)
    elif raw.startswith("下周"):
        weekday = "一二三四五六日".index(raw[-1].replace("天", "日"))
        result = today + timedelta(days=7 - today.weekday() + weekday)
    else:
        result = date.fromisoformat(raw)
    if result <= today:
        raise SemanticError("执行日期必须在未来，请明确日期")
    return result.isoformat()


def _arguments_match(request, plan):
    return all(
        any(
            step.arguments.get(key) == value
            and key in step.arguments
            and isinstance(step.arguments[key], bool) == isinstance(value, bool)
            for step in plan.steps
        )
        for key, value in request.arguments.items()
    )


def _slot_matches(actual, expected, kind):
    try:
        if kind in {"money", "day"}:
            return actual is not None and Decimal(str(actual)) == Decimal(expected)
        if kind == "date":
            moment = datetime.fromisoformat(str(actual))
            return (
                moment.tzinfo is not None
                and moment.astimezone(SHANGHAI_TZ).date().isoformat() == expected
            )
        return actual == expected
    except (ValueError, TypeError, DecimalException, OverflowError):
        return False


def verify_frame(frame, request, rule, specs=None, today=None):
    """Returns a deterministic plan; model values/tools/permissions are never used."""
    specs = specs or collect_semantic_specs()
    today = today or datetime.now(SHANGHAI_TZ).date()
    item = _candidate_shape(frame, request.instruction, specs)
    spec = specs[item.kind]
    resolved, evidence = {}, []
    for key, kind in spec.slot_types.items():
        mention = item.slots.get(key)
        raw = mention.text.strip() if mention else None
        source, method = "user_text", "literal"
        if raw is None:
            if key == "account":
                raw = "ACC-1001"
                source, method = "demo_policy", "explicit_demo_default"
            elif key == "period":
                raw = "本月"
                source, method = "demo_policy", "current_month_default"
            else:
                frame.missing_slots.append(f"{item.id}.{key}")
                raise SemanticError(f"请补充{_slot_label(key)}，系统不会猜测关键参数")
        try:
            if kind == "money":
                value, method = str(parse_amount(raw)), "decimal_whole_token"
            elif kind in (
                "account",
                "card",
                "subscription",
                "contact",
                "contact_name",
                "contact_account",
                "product",
            ):
                rows = collect_entity_facts(
                    rule.repository, request.user_id, "contact" if kind == "contact_name" else kind
                )
                def name_matches(
                    name: str, *, kind: str = kind, raw: str = raw
                ) -> bool:
                    if kind == "account":
                        return _account_key(raw) == _account_key(name)
                    return (
                        raw.replace(" ", "").casefold()
                        == name.replace(" ", "").casefold()
                    )

                hits = [
                    (value, names)
                    for value, names in rows
                    if any(name_matches(name) for name in names)
                ]
                if len(hits) != 1:
                    options = hits or (rows if kind == "card" else [])
                    if kind == "card":
                        choices = [
                            identity
                            + "（"
                            + next(
                                (name for name in names if name.startswith("尾号")), "未提供尾号"
                            )
                            + "）"
                            for identity, names in options
                        ][:8]
                    else:
                        choices = [
                            names[0] + "（尾号" + value[-4:] + "）" for value, names in options
                        ][:8]
                    unresolved = SlotEvidence(
                        intent_id=item.id,
                        slot=key,
                        span=mention,
                        value=raw,
                        source="mock_entity_catalog",
                        verified=False,
                        verification_kind="ambiguous_or_missing",
                        candidates=choices,
                    )
                    raise SemanticError(
                        f"未找到唯一的{_slot_label(key)}「{raw}」；"
                        + (
                            ("匹配到多个对象，请选择：" if hits else "请选择有效卡片：")
                            + "、".join(choices)
                            if choices
                            else "请明确有效对象"
                        ),
                        [*evidence, unresolved],
                    )
                value = hits[0][1][0] if kind == "contact_name" else hits[0][0]
                if source != "demo_policy":
                    source = "mock_entity_catalog"
                method = "user_scoped_exact_entity"
            elif kind == "day":
                day = parse_amount(raw)
                if day != day.to_integral_value() or not 1 <= day <= 28:
                    raise SemanticError("还款日必须为 1–28 日")
                value = str(int(day))
                method = "repayment_day_range"
            elif kind == "date":
                value, source, method = (
                    _resolve_date(raw, today),
                    "calendar",
                    "shanghai_future_calendar_date",
                )
            elif kind == "month":
                month = today.replace(day=1)
                if raw in ("上月", "上个月"):
                    month = month - timedelta(days=1)
                value, source, method = (
                    month.strftime("%Y-%m"),
                    source if source == "demo_policy" else "calendar",
                    "shanghai_month_normalization",
                )
            else:
                raise SemanticError("未知槽位类型")
        except (ValueError, AmountError) as exc:
            if isinstance(exc, SemanticError):
                raise
            raise SemanticError(f"{_slot_label(key)}无法验证：{exc}") from exc
        resolved[key] = value
        evidence.append(
            SlotEvidence(
                intent_id=item.id,
                slot=key,
                span=mention,
                value=value,
                source=source,
                verification_kind=method,
            )
        )
    canonical = spec.template.format(**resolved)
    # No tool is invoked here: templates target the existing declarative planner.
    plan = rule.plan(request.model_copy(update={"instruction": canonical}))
    if plan.needs_clarification:
        raise SemanticError(plan.clarification, evidence)
    for step in plan.steps:
        for key in ("account_id", "from_account"):
            value = step.arguments.get(key)
            if value and not any(e.value == value and e.slot == "account" for e in evidence):
                try:
                    facts = collect_entity_facts(rule.repository, request.user_id, "account")
                except ValueError as exc:
                    raise SemanticError(str(exc), evidence) from exc
                if value not in {identity for identity, _ in facts}:
                    raise SemanticError("默认演示账户不属于当前用户，请明确账户", evidence)
                evidence.append(
                    SlotEvidence(
                        intent_id=item.id,
                        slot=key,
                        value=value,
                        source="demo_policy",
                        verification_kind="user_scoped_demo_default",
                    )
                )
    for step in plan.steps:
        if "note" in step.arguments:
            step.arguments["note"] = request.instruction[:120]
    expected_tools = list(spec.tools)
    if [s.tool_name for s in plan.steps] != expected_tools:
        raise SemanticError("编译后的动作与已验证意图不一致，已停止规划", evidence)
    if set(spec.bindings) != set(spec.slot_types):
        raise SemanticError("场景未声明完整槽位参数绑定，已停止规划", evidence)
    for key, (index, argument) in spec.bindings.items():
        arguments = plan.steps[index].arguments if 0 <= index < len(plan.steps) else {}
        keys = (argument,) if isinstance(argument, str) else argument
        actual = next((arguments.get(k) for k in keys if arguments.get(k) is not None), None)
        if not _slot_matches(actual, resolved[key], spec.slot_types[key]):
            raise SemanticError(f"已验证槽位 {key} 与计划参数不一致，已停止规划", evidence)
    if not _arguments_match(request, plan):
        raise SemanticError("显式参数与完整指令的计划不一致，请明确参数。", evidence)
    plan.semantic = SemanticAnalysis(
        status="verified",
        instruction_hash=hashlib.sha256(request.instruction.encode()).hexdigest(),
        frame=frame,
        slots=evidence,
        reference_date=today.isoformat(),
        timezone="Asia/Shanghai",
    )
    # Canonical-template offsets are not positions in the original utterance.
    plan.assumptions = [a for a in plan.assumptions if not a.startswith("金额来源：")]
    for entry in evidence:
        if entry.verification_kind == "decimal_whole_token" and entry.span:
            plan.assumptions.append(
                f"金额来源：原文[{entry.span.start}:{entry.span.end}]"
                f"「{entry.span.text}」 = {entry.value} CNY。"
            )
    plan.assumptions.append("语义与槽位已验证；实体目录仅用于解析，权限与风险仍须执行链复核。")
    return plan


class SemanticPlanner:
    semantic_contract = "SemanticFrame/v1"

    def __init__(self, rule, model=None):
        self.rule, self.model = rule, model
        self.name = model.name if model else rule.name
        self.specs = collect_semantic_specs()

    def _attach(self, plan, request, frame, status, evidence=None):
        if (
            not request.tool_name
            and not plan.needs_clarification
            and not _arguments_match(request, plan)
        ):
            plan = ExecutionPlan(
                intent="semantic_clarification",
                planner=self.name,
                confidence=0,
                needs_clarification=True,
                clarification="显式参数与完整指令的计划不一致。",
            )
            status = "clarification"
        plan.semantic = SemanticAnalysis(
            status=status,
            instruction_hash=hashlib.sha256(request.instruction.encode()).hexdigest(),
            frame=frame,
            slots=evidence or [],
            reason=plan.clarification
            if plan.needs_clarification
            else "沿用 P0 规则路径，未迁移到语义编译",
        )
        return plan

    def plan(self, request):
        if request.tool_name:
            plan = self.rule.plan(request)
            return self._attach(
                plan, request, None, "clarification" if plan.needs_clarification else "legacy"
            )
        frame = analyze_rules(request.instruction, self.specs)
        guard = planning_clarification(request)
        migratable = not frame.conditions and not frame.uncovered and bool(frame.intents)
        if guard and (guard.intent != "unsupported_composition" or not migratable):
            return self._attach(guard, request, frame, "clarification")
        if frame.needs_clarification and frame.clarification:
            plan = ExecutionPlan(
                intent="semantic_clarification",
                planner=self.name,
                confidence=0,
                needs_clarification=True,
                clarification=frame.clarification,
            )
            return self._attach(plan, request, frame, "clarification")
        if self.model:
            frame = self.model.analyze(request.instruction, self.specs)
        elif frame.uncovered and frame.intents:
            plan = ExecutionPlan(
                intent="semantic_clarification",
                planner=self.name,
                confidence=0,
                needs_clarification=True,
                clarification="还有未理解的片段，请明确完整任务，不能只执行已识别部分。",
            )
            return self._attach(plan, request, frame, "clarification")
        elif frame.uncovered:
            plan = self.rule.plan(request)
            if not allow_legacy(request, plan, self.rule.repository):
                plan = ExecutionPlan(
                    intent="semantic_clarification",
                    planner=self.name,
                    confidence=0,
                    needs_clarification=True,
                    clarification="尚不能完整验证这条指令，请明确一个完整任务；不会执行部分计划。",
                )
            return self._attach(
                plan, request, frame, "clarification" if plan.needs_clarification else "legacy"
            )
        try:
            plan = verify_frame(frame, request, self.rule, self.specs)
            if self.model:
                plan.planner = self.name
            return plan
        except SemanticError as exc:
            intent = "semantic_clarification"
            if len(frame.intents) == 1:
                spec = self.specs.get(frame.intents[0].kind)
                if spec and len(spec.tools) == 1:
                    intent = spec.tools[0]
            plan = ExecutionPlan(
                intent=intent,
                planner=self.name,
                confidence=0,
                needs_clarification=True,
                clarification=str(exc)[:500],
            )
            return self._attach(plan, request, frame, "clarification", exc.evidence)
