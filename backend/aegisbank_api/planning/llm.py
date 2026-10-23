"""OpenAI-compatible structured-output planner adapter.

The model output is treated as an untrusted *candidate*: only ExecutionPlan
contract fields are accepted, unknown tools are rejected, and the model may not
override user-supplied high-risk arguments or invent a recipient/amount that the
user never provided. Conflicts become ``needs_clarification`` plans instead of
silently winning.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

import httpx

from ..registry import ToolRegistry
from .contracts import ExecutionPlan, Planner, PlanningRequest, PlanStep

_ALLOWED_PLAN_FIELDS = frozenset(ExecutionPlan.model_fields)
_ALLOWED_STEP_FIELDS = frozenset(PlanStep.model_fields)
_HIGH_RISK_ARGUMENTS = frozenset(
    {
        "to_account",
        "from_account",
        "amount_cny",
        "new_day",
        "new_limit_cny",
        "daily_limit_cny",
        "card_id",
        "subscription_id",
    }
)


class PlannerError(ValueError):
    """Raised when a model-backed planner cannot produce a valid plan."""


def _extract_json(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise PlannerError("模型没有返回 JSON 对象。")
    return text[start : end + 1]


def _reject_unknown_fields(raw: dict[str, Any]) -> None:
    """Strict field whitelist: only ExecutionPlan/PlanStep contract fields."""
    unknown = set(raw) - _ALLOWED_PLAN_FIELDS
    if unknown:
        raise PlannerError(f"模型返回了契约外字段：{sorted(unknown)}")
    steps = raw.get("steps") or []
    if not isinstance(steps, list):
        raise PlannerError("模型返回的 steps 必须是数组。")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlannerError(f"模型返回的第 {index} 个 step 不是 JSON 对象。")
        extra = set(step) - _ALLOWED_STEP_FIELDS
        if extra:
            raise PlannerError(f"模型返回的第 {index} 个 step 含契约外字段：{sorted(extra)}")


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return str(left).strip() == str(right).strip()


def _value_mentioned(value: Any, text: str) -> bool:
    """True when the model's value can be traced back to the user's words."""
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    haystack = text or ""
    if isinstance(value, (int, float)):
        candidates = {str(value), f"{value:g}", f"{float(value):.2f}"}
        if float(value).is_integer():
            candidates.add(str(int(value)))
        return any(
            re.search(r"(?<![\d.\-])" + re.escape(item) + r"(?![\d.])", haystack)
            for item in candidates
        )
    return str(value) in haystack


def _candidate_conflict(
    plan: ExecutionPlan, request: PlanningRequest, reference: ExecutionPlan | None = None
) -> str | None:
    """Return a human-readable conflict reason, or ``None`` when safe."""
    explicit = request.arguments or {}
    if request.tool_name and (len(plan.steps) != 1 or plan.steps[0].tool_name != request.tool_name):
        return f"模型步骤与用户显式指定的 {request.tool_name} 冲突"
    for step in plan.steps:
        for key, value in explicit.items():
            if key in step.arguments:
                if not _same_value(step.arguments[key], value):
                    return (
                        f"模型试图覆盖用户显式给定的参数 {key}（{value} → {step.arguments[key]}）"
                    )
            elif key in _HIGH_RISK_ARGUMENTS:
                return f"模型丢弃了用户显式给定的参数 {key}"
    instruction = request.instruction or ""
    if re.search(r"不要|暂不|不必|do not|don't", instruction, re.I):
        return "指令含否定意图，需要明确意图后再规划"
    write_fields = {
        "transfer": ("from_account", "to_account", "amount_cny"),
        "transfer_to_contact": ("to_name", "to_phone", "amount_cny"),
        "add_contact": ("name", "phone", "account_id"),
        "apply_virtual_card": ("requested_limit_cny", "card_type"),
        "issue_virtual_card": ("application_id",),
        "run_due_tasks": ("now",),
        "schedule_transfer": ("to_account", "to_name", "amount_cny", "run_at"),
        "purchase_wealth": ("product_id", "amount_cny"),
        "redeem_wealth": ("holding_id", "product_id", "amount_cny", "shares"),
        "adjust_card_limit": ("card_id", "new_limit_cny"),
        "adjust_repayment_date": ("card_id", "new_day"),
        "report_card_lost": ("card_id",),
        "unlock_card": ("card_id",),
        "reset_card_password": ("card_id",),
        "unlock_transaction_limit": ("card_id", "daily_limit_cny"),
        "cancel_subscription": ("subscription_id",),
        "cancel_scheduled_task": ("task_id",),
        "unlock_budget_funds": ("goal_id",),
        "schedule_flower_order": ("to_name", "goal_id", "birthday"),
        "schedule_cake_order": ("to_name", "goal_id", "birthday"),
        "set_transaction_limit": ("daily_limit_cny",),
        "assess_wealth_risk": ("risk_preference",),
        "lock_budget_funds": ("amount_cny",),
    }
    if reference is not None:
        candidate_writes = Counter(s.tool_name for s in plan.steps if s.tool_name in write_fields)
        expected_writes = Counter(
            s.tool_name for s in reference.steps if s.tool_name in write_fields
        )
        if candidate_writes != expected_writes:
            return "模型改变了确定性规划中的写操作种类或笔数，需要重新明确任务"
    for step in plan.steps:
        if step.tool_name in write_fields:
            if reference is not None and reference.needs_clarification:
                return "确定性意图校验仍缺少必要信息，模型不能补全写参数"
            for key in write_fields[step.tool_name]:
                value = step.arguments.get(key)
                if value is None or key in explicit:
                    continue
                grounded = reference is not None and any(
                    ref.tool_name == step.tool_name and _same_value(ref.arguments.get(key), value)
                    for ref in reference.steps
                )
                if not grounded and not _value_mentioned(value, instruction):
                    return (
                        f"模型的 {step.tool_name}.{key}（收款方或关键参数）"
                        "无法对应用户指令或确定性解析结果"
                    )
    for step in plan.steps:
        if step.tool_name != "transfer":
            continue
        if "to_account" not in explicit and not _value_mentioned(
            step.arguments.get("to_account"), instruction
        ):
            return "模型补全了用户未提供的收款方"
        if "amount_cny" not in explicit and not _value_mentioned(
            step.arguments.get("amount_cny"), instruction
        ):
            return "模型补全了用户未提供的转账金额"
    return None


def _conflict_clarification(plan: ExecutionPlan, message: str, planner_name: str) -> ExecutionPlan:
    return ExecutionPlan(
        intent=plan.intent,
        planner=planner_name,
        confidence=0.0,
        assumptions=[f"候选校验拦截：{message}。"],
        needs_clarification=True,
        clarification=f"{message}。请明确后再执行，模型不会替用户补全。",
    )


class OpenAICompatiblePlanner:
    """Calls an OpenAI-compatible chat completions endpoint.

    The model receives a read-only tool catalog and returns an ExecutionPlan.
    It never receives database or tool-execution capabilities.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        base_url: str,
        credential: str,
        model: str,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
        repository: Any = None,
    ) -> None:
        self.registry = registry
        self.base_url = base_url.rstrip("/")
        self.credential = credential
        self.model = model
        self.name = f"llm:{model}"
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)
        from .rule import RuleBasedPlanner

        self.reference_planner = RuleBasedPlanner(registry, repository)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def plan(self, request: PlanningRequest) -> ExecutionPlan:
        if not self.base_url or not self.model:
            raise PlannerError("LLM Planner 缺少 base_url 或 model 配置。")
        catalog = [
            {
                "name": tool.metadata.name,
                "title": tool.metadata.title,
                "description": tool.metadata.description,
                "risk_level": tool.metadata.risk_level.value,
                "permission": tool.metadata.permission,
                "input_schema": tool.metadata.input_schema,
            }
            for tool in self.registry.list()
            if not tool.metadata.internal_only
        ]
        system_prompt = (
            "你是 AegisBank 的结构化 Planner，只负责把用户意图变成计划，不执行任何工具。"
            "必须只返回一个 JSON 对象，禁止 Markdown 和解释文字。"
            "计划只能使用给定工具目录中的工具。不要猜测高风险参数；"
            "缺少金额、收款账户、还款日等必要信息时返回 needs_clarification=true。"
            "每个 step 必须有唯一 id、tool_name、arguments，depends_on 用来表达 DAG 依赖。"
            "字段必须符合提供的 ExecutionPlan JSON Schema。"
        )
        user_prompt = json.dumps(
            {
                "user_instruction": request.instruction,
                "explicit_tool": request.tool_name,
                "explicit_arguments": request.arguments,
                "tool_catalog": catalog,
                "output_schema": ExecutionPlan.model_json_schema(),
            },
            ensure_ascii=False,
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.credential:
            headers["Authorization"] = f"Bearer {self.credential}"

        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            raw = json.loads(_extract_json(content))
            if not isinstance(raw, dict):
                raise PlannerError("模型没有返回 JSON 对象。")
            _reject_unknown_fields(raw)
            plan = ExecutionPlan.model_validate(raw)
        except PlannerError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise PlannerError(f"LLM Planner 调用或解析失败：{exc}") from exc

        known_tools = {
            tool.metadata.name for tool in self.registry.list() if not tool.metadata.internal_only
        }
        unknown_tools = sorted(
            {step.tool_name for step in plan.steps if step.tool_name not in known_tools}
        )
        if unknown_tools:
            raise PlannerError(f"模型返回了未注册工具：{', '.join(unknown_tools)}")

        conflict = _candidate_conflict(plan, request, self.reference_planner.plan(request))
        if conflict:
            return _conflict_clarification(plan, conflict, self.name)

        plan.planner = self.name
        return plan


__all__ = ["OpenAICompatiblePlanner", "Planner", "PlannerError"]
