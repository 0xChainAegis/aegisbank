"""Tool compensation registry for step-level rollback (stage 2A).

Tools declare whether they can be undone and which inverse tool performs the
compensation. The registry is the single source of truth used by the scheduler
when a multi-step DAG fails halfway and the reversible steps must be rolled
back in reverse order.

Tool-level declarations live in ``ToolMetadata.compensable`` /
``ToolMetadata.compensation_tool``; this registry adds the operational details
(argument mapping notes, irreversibility reasons) without editing every tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CompensationSpec:
    """How one executed tool can be compensated (or why it cannot)."""

    tool_name: str
    compensation_tool: str
    description: str = ""
    irreversible: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "compensation_tool": self.compensation_tool,
            "description": self.description,
            "irreversible": self.irreversible,
        }


class CompensationRegistry:
    """Map tool names to compensation specifications."""

    def __init__(self, specs: list[CompensationSpec] | None = None) -> None:
        self._specs: dict[str, CompensationSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: CompensationSpec) -> None:
        self._specs[spec.tool_name] = spec

    def spec_for(self, tool_name: str) -> CompensationSpec | None:
        return self._specs.get(tool_name)

    def is_compensable(self, tool_name: str) -> bool:
        spec = self._specs.get(tool_name)
        return spec is not None and not spec.irreversible

    def as_list(self) -> list[dict[str, Any]]:
        return [spec.as_dict() for spec in sorted(self._specs.values(), key=lambda s: s.tool_name)]

    def __len__(self) -> int:
        return len(self._specs)
