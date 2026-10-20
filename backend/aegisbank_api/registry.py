"""Standard, pluggable tool SDK and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from .domain import ExecutionContext, ToolMetadata, ToolResult


class BaseTool(ABC):
    """Every financial capability is an independent, declarative tool node."""

    metadata: ToolMetadata
    arguments_model: type[BaseModel] | None = None

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize tool arguments before authorization/execution."""
        if self.arguments_model is None:
            return dict(arguments)
        return self.arguments_model.model_validate(arguments).model_dump()

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
