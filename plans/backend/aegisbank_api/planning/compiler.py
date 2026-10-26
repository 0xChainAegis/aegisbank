"""Deterministic validation and DAG compilation for planner output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..domain import PlanNode
from ..registry import ToolRegistry
from .contracts import ExecutionPlan


class PlanCompilationError(ValueError):
    """Raised when a proposed plan is unsafe, incomplete, or not executable."""


@dataclass(slots=True)
class CompiledPlan:
    intent: str
    planner: str
    confidence: float
    assumptions: list[str]
    nodes: list[PlanNode]
    step_meta: dict[str, dict[str, Any]]
    plan_hash: str

    @property
    def dag_path(self) -> str:
        return " -> ".join(f"{node.id}:{node.tool_name}" for node in self.nodes)

    def as_dict(self) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        for node in self.nodes:
            item = node.as_dict()
            item.update(self.step_meta.get(node.id, {}))
            steps.append(item)
        return {
            "intent": self.intent,
            "planner": self.planner,
            "confidence": self.confidence,
            "assumptions": self.assumptions,
            "plan_hash": self.plan_hash,
            "dag_path": self.dag_path,
            "steps": steps,
        }


class PlanCompiler:
    """Validates planner output and turns it into an ordered DAG."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def compile(self, plan: ExecutionPlan) -> CompiledPlan:
        if plan.needs_clarification:
            raise PlanCompilationError("计划仍在等待补充信息，不能进入执行阶段。")
        if not plan.steps:
            raise PlanCompilationError("计划至少需要一个工具节点。")
        if len(plan.steps) > 12:
            raise PlanCompilationError("单个计划最多允许 12 个工具节点。")

        node_by_id: dict[str, PlanNode] = {}
        step_meta: dict[str, dict[str, Any]] = {}
        normalized_steps: dict[str, dict[str, Any]] = {}

        for step in plan.steps:
            if step.id in node_by_id:
                raise PlanCompilationError(f"计划节点 id 重复：{step.id}")
            try:
                tool = self.registry.get(step.tool_name)
            except KeyError as exc:
                raise PlanCompilationError(f"计划引用了未注册工具：{step.tool_name}") from exc
            try:
                normalized_args = tool.validate_arguments(step.arguments)
            except Exception as exc:  # noqa: BLE001 - surface schema errors uniformly
                raise PlanCompilationError(
                    f"节点 {step.id} 的参数未通过 {step.tool_name} Schema 校验：{exc}"
                ) from exc

            node_by_id[step.id] = PlanNode(
                id=step.id,
                tool_name=tool.metadata.name,
                arguments=normalized_args,
                depends_on=list(step.depends_on),
            )
            normalized_steps[step.id] = {
                "id": step.id,
                "tool_name": tool.metadata.name,
                "arguments": normalized_args,
                "depends_on": list(step.depends_on),
            }
            step_meta[step.id] = {
                "title": tool.metadata.title,
                "risk_level": tool.metadata.risk_level.value,
                "permission": tool.metadata.permission,
                "description": step.description or tool.metadata.description,
            }

        for step in plan.steps:
            if len(set(step.depends_on)) != len(step.depends_on):
                raise PlanCompilationError(f"节点 {step.id} 存在重复依赖。")
            for dependency in step.depends_on:
                if dependency not in node_by_id:
                    raise PlanCompilationError(
                        f"节点 {step.id} 依赖不存在的节点：{dependency}"
                    )
                if dependency == step.id:
                    raise PlanCompilationError(f"节点 {step.id} 不能依赖自身。")

        ordered_ids = self._topological_order(node_by_id)
        nodes = [node_by_id[step_id] for step_id in ordered_ids]
        plan_hash = hashlib.sha256(
            json.dumps(
                {"intent": plan.intent, "steps": normalized_steps},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return CompiledPlan(
            intent=plan.intent,
            planner=plan.planner,
            confidence=plan.confidence,
            assumptions=list(plan.assumptions),
            nodes=nodes,
            step_meta=step_meta,
            plan_hash=plan_hash,
        )

    @staticmethod
    def _topological_order(nodes: dict[str, PlanNode]) -> list[str]:
        state: dict[str, int] = {}
        ordered: list[str] = []

        def visit(node_id: str) -> None:
            current = state.get(node_id, 0)
            if current == 1:
                raise PlanCompilationError(f"计划存在循环依赖：{node_id}")
            if current == 2:
                return
            state[node_id] = 1
            for dependency in nodes[node_id].depends_on:
                visit(dependency)
            state[node_id] = 2
            ordered.append(node_id)

        for node_id in nodes:
            visit(node_id)
        return ordered
