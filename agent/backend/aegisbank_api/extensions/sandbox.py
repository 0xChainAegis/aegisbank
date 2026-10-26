"""Tool execution sandbox extension (stage 2A).

``activate`` wraps the scheduler executor with ``SandboxedToolExecutor`` when
``AEGIS_SANDBOX_ENABLED`` is on (the default). The router exposes the effective
policy and a side-effect-free demo endpoint: each demo tool is constructed in
memory and executed through the *real* executor, so the block / timeout / audit
path is the same one production tool nodes take. No business table is touched;
every block is written to the audit hash chain.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..executor import SandboxViolation
from ..registry import BaseTool
from ..services import CoreServices
from ..trust.sandbox import (
    SANDBOX_BLOCKED_EVENT,
    SandboxedToolExecutor,
    SandboxGuard,
    SandboxPolicy,
    network_block_active,
)

NAME = "sandbox"
DEMO_USER = "demo-user"
DEMO_KINDS = ("network", "slow", "oversize")

DemoRunner = Callable[[dict[str, Any], ExecutionContext], ToolResult]


class SandboxDemoRequest(BaseModel):
    """Which sandbox control to demonstrate."""

    kind: Literal["network", "slow", "oversize"] = "network"


class _SandboxDemoTool(BaseTool):
    """Synthetic tool node used only by the demo route (never registered)."""

    def __init__(
        self,
        *,
        name: str,
        title: str,
        description: str,
        runner: DemoRunner,
    ) -> None:
        self.metadata = ToolMetadata(
            name=name,
            title=title,
            description=description,
            risk_level=RiskLevel.GREEN,
            permission="sandbox:demo",
        )
        self._runner = runner

    def execute(
        self, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        return self._runner(arguments, context)


def _network_runner(name: str) -> DemoRunner:
    def run(_arguments: dict[str, Any], _context: ExecutionContext) -> ToolResult:
        # TEST-NET-1 address: never a real service, safe even if the shield is off.
        socket.create_connection(("192.0.2.1", 9), timeout=0.5)
        return ToolResult(
            name,
            "网络访问未被沙箱拦截（异常）。",
            {"network_attempted": True, "simulated": True},
        )

    return run


def _slow_runner(name: str, seconds: float) -> DemoRunner:
    def run(_arguments: dict[str, Any], _context: ExecutionContext) -> ToolResult:
        time.sleep(seconds)
        return ToolResult(
            name,
            "慢工具执行完成（本应被超时拦截）。",
            {"slept_seconds": seconds, "simulated": True},
        )

    return run


def _oversize_runner(name: str, size: int) -> DemoRunner:
    def run(_arguments: dict[str, Any], _context: ExecutionContext) -> ToolResult:
        return ToolResult(
            name,
            "超大输出（本应被输出上限拦截）。",
            {"payload": "x" * size, "simulated": True},
        )

    return run


def _build_demo_tool(kind: str, policy: SandboxPolicy) -> BaseTool:
    if kind == "network":
        return _SandboxDemoTool(
            name="sandbox_demo_network",
            title="沙箱网络探测",
            description="尝试发起一次 socket 连接，用于验证工具执行期间的网络阻断。",
            runner=_network_runner("sandbox_demo_network"),
        )
    if kind == "slow":
        seconds = max(policy.timeout_seconds + 0.25, 0.5)
        return _SandboxDemoTool(
            name="sandbox_demo_slow",
            title="沙箱超时探测",
            description="故意休眠超过沙箱超时上限，用于验证超时拦截与审计。",
            runner=_slow_runner("sandbox_demo_slow", seconds),
        )
    size = max(policy.max_output_bytes + 256, 512)
    return _SandboxDemoTool(
        name="sandbox_demo_oversize",
        title="沙箱输出上限探测",
        description="返回超过沙箱输出上限的结构化结果，用于验证输出体积拦截。",
        runner=_oversize_runner("sandbox_demo_oversize", size),
    )


def _runtime(services: CoreServices) -> tuple[SandboxPolicy, Any]:
    runtime = services.extras.get("sandbox")
    if isinstance(runtime, dict):
        policy = runtime.get("policy")
        if isinstance(policy, SandboxPolicy):
            return policy, runtime.get("executor")
    scheduler = getattr(services, "scheduler", None)
    executor = getattr(scheduler, "executor", None) or services.executor
    return SandboxPolicy.from_settings(services.settings), executor


def activate(services: CoreServices) -> None:
    """Swap in the sandboxed executor when the switch is on."""
    policy = SandboxPolicy.from_settings(services.settings)
    executor = getattr(services.scheduler, "executor", None) or services.executor
    if policy.enabled:
        audit = services.require_audit()
        existing_guards = [
            guard
            for guard in getattr(executor, "guards", [])
            if getattr(guard, "name", None) != "sandbox"
        ]
        guarded = SandboxedToolExecutor(
            guards=[*existing_guards, SandboxGuard(policy=policy, audit=audit)],
            audit=audit,
            policy=policy,
        )
        services.scheduler.executor = guarded
        services.executor = guarded
        executor = guarded
    services.extras["sandbox"] = {"policy": policy, "executor": executor}


def router(services: CoreServices) -> APIRouter:
    """Policy inspection plus a safe, audited sandbox demonstration."""
    api = APIRouter(tags=["sandbox"])

    @api.get("/api/sandbox/policy")
    def get_sandbox_policy() -> dict[str, Any]:
        policy, executor = _runtime(services)
        guard_names = (
            executor.guard_names() if isinstance(executor, SandboxedToolExecutor) else []
        )
        policy_payload = policy.as_dict()
        return {
            "policy": policy_payload,
            **policy_payload,
            "executor": type(executor).__name__ if executor is not None else None,
            "guards": guard_names,
            "network_block_active": network_block_active(),
            "demo_kinds": list(DEMO_KINDS),
        }

    @api.post("/api/sandbox/demo/run")
    def run_sandbox_demo(body: SandboxDemoRequest) -> dict[str, Any]:
        policy, executor = _runtime(services)
        payload: dict[str, Any] = {
            "kind": body.kind,
            "sandbox_enabled": policy.enabled,
            "policy": policy.as_dict(),
        }
        if not policy.enabled:
            return {
                **payload,
                "blocked": False,
                "event": None,
                "violation": None,
                "reason": "沙箱未启用（AEGIS_SANDBOX_ENABLED=0），演示未执行。",
            }
        if body.kind == "network" and not policy.block_network:
            return {
                **payload,
                "blocked": False,
                "event": None,
                "violation": None,
                "reason": "沙箱已启用但网络阻断开关关闭，演示未发起真实网络访问。",
            }
        if body.kind == "slow" and policy.timeout_seconds <= 0:
            return {
                **payload,
                "blocked": False,
                "event": None,
                "violation": None,
                "reason": "沙箱已启用但超时上限为 0，演示未等待慢工具。",
            }
        if not isinstance(executor, SandboxedToolExecutor):
            raise HTTPException(
                status_code=503,
                detail="沙箱执行器未装配，拒绝执行演示工具。",
            )

        tool = _build_demo_tool(body.kind, policy)
        context = ExecutionContext(
            user_id=DEMO_USER,
            instruction=f"沙箱演示：{body.kind}",
            run_id=f"sandbox-demo-{body.kind}",
            dag_path="sandbox",
        )
        try:
            result = executor.execute(tool, {}, context)
        except SandboxViolation as exc:
            return {
                **payload,
                "blocked": True,
                "event": getattr(exc, "sandbox_event", SANDBOX_BLOCKED_EVENT),
                "violation": getattr(exc, "sandbox_kind", body.kind),
                "reason": str(exc),
                "tool_name": tool.metadata.name,
            }
        except Exception as exc:  # noqa: BLE001 - demo reports instead of 500
            return {
                **payload,
                "blocked": False,
                "event": None,
                "violation": "error",
                "reason": f"演示工具未被沙箱拦截：{exc}",
                "tool_name": tool.metadata.name,
            }
        return {
            **payload,
            "blocked": False,
            "event": None,
            "violation": None,
            "reason": "沙箱未拦截该调用（策略或输入未越界）。",
            "tool_name": tool.metadata.name,
            "result": result,
        }

    return api