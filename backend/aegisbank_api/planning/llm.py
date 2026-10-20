"""OpenAI-compatible structured-output planner adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..registry import ToolRegistry
from .contracts import ExecutionPlan, PlanningRequest


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
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.registry = registry
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = f"llm:{model}"
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)

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
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            plan = ExecutionPlan.model_validate_json(_extract_json(content))
        except PlannerError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise PlannerError(f"LLM Planner 调用或解析失败：{exc}") from exc

        plan.planner = self.name
        return plan
