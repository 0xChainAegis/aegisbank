"""Standard, pluggable tool SDK and registry."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any

from jsonschema import validate
from pydantic import BaseModel

from .domain import ExecutionContext, ToolMetadata, ToolResult
from .tool_outputs import legacy_output_schema


class BaseTool(ABC):
    """Every financial capability is an independent, declarative tool node."""

    metadata: ToolMetadata
    arguments_model: type[BaseModel] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        metadata = getattr(cls, "metadata", None)
        if metadata is not None and (
            metadata.name.startswith(("reverse_", "restore_"))
            or metadata.name in {"reactivate_subscription", "cancel_virtual_card_application"}
        ):
            cls.metadata = metadata = replace(metadata, internal_only=True)
        if metadata is not None and not metadata.output_schema:
            cls.metadata = replace(metadata, output_schema=legacy_output_schema(metadata.name))

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize tool arguments before authorization/execution."""
        if self.arguments_model is None:
            return dict(arguments)
        unknown = set(arguments) - set(self.arguments_model.model_fields)
        if unknown:
            raise ValueError(f"工具包含未知参数：{sorted(unknown)}")
        for key, value in arguments.items():
            if key.endswith("_cny") and value is not None:
                try:
                    amount = Decimal(str(value))
                    precise = amount.is_finite() and amount == amount.quantize(Decimal("0.01"))
                except InvalidOperation as exc:
                    raise ValueError(f"{key} 必须为合法金额。") from exc
                if not precise:
                    raise ValueError(f"{key} 必须为有限数且精确到分。")
        return self.arguments_model.model_validate(arguments).model_dump()

    def validate_result(self, result: ToolResult) -> None:
        if result.tool_name != self.metadata.name:
            raise ValueError("工具回执与实际执行工具不一致。")
        if result.data.get("simulated") is not True:
            raise ValueError("工具回执必须明确标记 simulated=true。")
        json.dumps(result.as_dict(), allow_nan=False)
        validate(result.data, self.metadata.output_schema)

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        name = tool.metadata.name
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list(self) -> list[BaseTool]:
        return sorted(self._tools.values(), key=lambda item: item.metadata.name)

    def names(self) -> list[str]:
        return [item.metadata.name for item in self.list()]
