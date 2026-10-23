"""Central tool executor with pluggable execution guards (stage 2A sandbox hook).

The scheduler never calls ``tool.execute`` directly any more: every tool run
goes through this executor, which lets cross-cutting guards (sandbox timeout,
network blocking, size limits, audit trails) wrap execution without touching
individual tool nodes.
"""

from __future__ import annotations

from typing import Any, Protocol

from .domain import (
    ExecutionContext,
    ToolMetadata,  # noqa: F401 - re-exported for guard authors
    ToolResult,
)
from .registry import BaseTool


class SandboxViolation(RuntimeError):
    """Raised by a guard when a tool call is rejected by the sandbox."""


class ExecutionGuard(Protocol):
    """Hook point around a single tool execution."""

    name: str

    def before_execute(
        self,
        *,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> None: ...

    def after_execute(
        self,
        *,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
        result: ToolResult,
    ) -> None: ...


class ToolExecutor:
    """Run tool nodes under an ordered guard chain."""

    def __init__(self, guards: list[ExecutionGuard] | None = None) -> None:
        self.guards: list[ExecutionGuard] = list(guards or [])

    def add_guard(self, guard: ExecutionGuard) -> None:
        self.guards.append(guard)

    def remove_guard(self, name: str) -> None:
        self.guards = [guard for guard in self.guards if guard.name != name]

    def guard_names(self) -> list[str]:
        return [guard.name for guard in self.guards]

    def execute(
        self,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        active = tuple(self.guards)
        for guard in active:
            guard.before_execute(tool=tool, arguments=arguments, context=context)
        result = tool.execute(arguments, context)
        for guard in reversed(active):
            guard.after_execute(
                tool=tool,
                arguments=arguments,
                context=context,
                result=result,
            )
        return result.as_dict()
