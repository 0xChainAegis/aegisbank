"""In-process tool execution sandbox for stage 2A.

The sandbox wraps every tool run with four predictable controls:

* a structured-input size limit (oversized arguments are rejected before a tool runs),
* an optional tool allowlist (tools that are not explicitly permitted are rejected),
* network blocking while a tool executes (socket-level interception, restored after),
* a wall-clock timeout and an output size limit around the tool body.

This is deliberately an in-process, demonstration-grade restricted runtime - not
an OS-level container. Every violation is raised as ``SandboxViolation`` and is
written to the tamper-evident audit chain before a trusted result can exist.
Python threads cannot be killed, so a timed-out worker may keep running until it
returns; its guard cleanup is idempotent and the timeout path force-releases the
network block to avoid leaving the whole process offline.
"""

from __future__ import annotations

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

from ..audit import AuditService
from ..config import Settings
from ..domain import ExecutionContext, ToolResult
from ..executor import ExecutionGuard, SandboxViolation, ToolExecutor
from ..registry import BaseTool
from .evidence import evidence_payload, policy_decision_evidence, tool_result_evidence

SANDBOX_BLOCKED_EVENT = "sandbox_blocked"
SANDBOX_TIMEOUT_EVENT = "sandbox_timeout"
DEFAULT_MAX_ARGUMENT_BYTES = 8_192


def _json_size(value: Any) -> int:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return len(payload.encode("utf-8"))


# ---------------------------------------------------------------------------
# network shield
# ---------------------------------------------------------------------------


def _network_violation(address: Any) -> SandboxViolation:
    violation = SandboxViolation(f"沙箱禁止工具访问网络：{address!r}")
    violation.sandbox_kind = "network"
    return violation


def _blocked_connect(_sock: Any, address: Any, *_args: Any, **_kwargs: Any) -> Any:
    raise _network_violation(address)


def _blocked_connect_ex(_sock: Any, address: Any, *_args: Any, **_kwargs: Any) -> Any:
    raise _network_violation(address)


def _blocked_create_connection(address: Any, *_args: Any, **_kwargs: Any) -> Any:
    raise _network_violation(address)


def _blocked_sendto(_sock: Any, *args: Any, **_kwargs: Any) -> Any:
    address = args[-1] if args else None
    raise _network_violation(address)


def _blocked_getaddrinfo(host: Any, *_args: Any, **_kwargs: Any) -> Any:
    raise _network_violation(host)


def _blocked_gethostbyname(host: Any) -> Any:
    raise _network_violation(host)


class _NetworkShield:
    """Install and restore socket-level network blocking around tool runs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._depth = 0
        self._original_connect: Any = None
        self._original_connect_ex: Any = None
        self._original_create_connection: Any = None
        self._original_sendto: Any = None
        self._original_getaddrinfo: Any = None
        self._original_gethostbyname: Any = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._depth > 0

    def enter(self) -> None:
        with self._lock:
            if self._depth == 0:
                self._install()
            self._depth += 1

    def exit(self) -> None:
        with self._lock:
            if self._depth == 0:
                return
            self._depth -= 1
            if self._depth == 0:
                self._restore()

    def _install(self) -> None:
        self._original_connect = socket.socket.connect
        self._original_connect_ex = socket.socket.connect_ex
        self._original_create_connection = socket.create_connection
        self._original_sendto = socket.socket.sendto
        self._original_getaddrinfo = socket.getaddrinfo
        self._original_gethostbyname = socket.gethostbyname
        socket.socket.connect = _blocked_connect
        socket.socket.connect_ex = _blocked_connect_ex
        socket.create_connection = _blocked_create_connection
        socket.socket.sendto = _blocked_sendto
        socket.getaddrinfo = _blocked_getaddrinfo
        socket.gethostbyname = _blocked_gethostbyname

    def _restore(self) -> None:
        if self._original_connect is not None:
            socket.socket.connect = self._original_connect
        if self._original_connect_ex is not None:
            socket.socket.connect_ex = self._original_connect_ex
        if self._original_create_connection is not None:
            socket.create_connection = self._original_create_connection
        if self._original_sendto is not None:
            socket.socket.sendto = self._original_sendto
        if self._original_getaddrinfo is not None:
            socket.getaddrinfo = self._original_getaddrinfo
        if self._original_gethostbyname is not None:
            socket.gethostbyname = self._original_gethostbyname
        self._original_connect = None
        self._original_connect_ex = None
        self._original_create_connection = None
        self._original_sendto = None
        self._original_getaddrinfo = None
        self._original_gethostbyname = None


_NETWORK_SHIELD = _NetworkShield()


def network_block_active() -> bool:
    """Whether the sandbox currently has socket-level network blocking installed."""
    return _NETWORK_SHIELD.active


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Effective sandbox policy derived from ``Settings`` plus optional allowlist."""

    enabled: bool = True
    timeout_seconds: float = 5.0
    max_output_bytes: int = 64_000
    max_argument_bytes: int = DEFAULT_MAX_ARGUMENT_BYTES
    block_network: bool = True
    allowed_tools: tuple[str, ...] = ()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        allowed_tools: tuple[str, ...] = (),
    ) -> SandboxPolicy:
        return cls(
            enabled=bool(settings.sandbox_enabled),
            timeout_seconds=max(0.0, float(settings.sandbox_timeout_seconds)),
            max_output_bytes=max(0, int(settings.sandbox_max_output_bytes)),
            block_network=bool(settings.sandbox_block_network),
            allowed_tools=tuple(allowed_tools),
        )

    @property
    def enforces_tool_whitelist(self) -> bool:
        return bool(self.allowed_tools)

    def allows_tool(self, tool_name: str) -> bool:
        return not self.allowed_tools or tool_name in self.allowed_tools

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_argument_bytes": self.max_argument_bytes,
            "block_network": self.block_network,
            "allowed_tools": list(self.allowed_tools),
            "tool_whitelist_enforced": self.enforces_tool_whitelist,
        }


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------


class SandboxGuard:
    """``ExecutionGuard`` enforcing argument limits, allowlist and network isolation."""

    name = "sandbox"

    def __init__(self, policy: SandboxPolicy, audit: AuditService | None = None) -> None:
        self.policy = policy
        self.audit = audit
        self._entered = threading.local()

    def before_execute(
        self,
        *,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> None:
        if not self.policy.enabled:
            return
        tool_name = tool.metadata.name
        if not self.policy.allows_tool(tool_name):
            self._block(
                tool=tool,
                arguments=arguments,
                context=context,
                kind="tool_whitelist",
                reason=(
                    f"工具 {tool_name} 不在沙箱白名单内（允许："
                    f"{', '.join(self.policy.allowed_tools)}）。"
                ),
            )
        argument_bytes = _json_size(arguments)
        if argument_bytes > self.policy.max_argument_bytes:
            self._block(
                tool=tool,
                arguments=arguments,
                context=context,
                kind="arguments_too_large",
                reason=(
                    f"工具入参大小 {argument_bytes} 字节超过沙箱上限 "
                    f"{self.policy.max_argument_bytes} 字节。"
                ),
            )
        if self.policy.block_network:
            _NETWORK_SHIELD.enter()
            self._entered.value = True

    def after_execute(
        self,
        *,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
        result: ToolResult,
    ) -> None:
        if not self.policy.enabled:
            return
        self.release_thread()
        output_bytes = _json_size(result.as_dict())
        if output_bytes > self.policy.max_output_bytes:
            self._block(
                tool=tool,
                arguments=arguments,
                context=context,
                kind="output_too_large",
                reason=(
                    f"工具输出大小 {output_bytes} 字节超过沙箱上限 "
                    f"{self.policy.max_output_bytes} 字节，结果已拒绝。"
                ),
            )

    def release_thread(self) -> None:
        """Release the network block entered by this thread, if any."""
        if getattr(self._entered, "value", False):
            self._entered.value = False
            _NETWORK_SHIELD.exit()

    def force_release(self) -> None:
        """Best-effort release from another thread (timeout path)."""
        _NETWORK_SHIELD.exit()

    def _block(
        self,
        *,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
        kind: str,
        reason: str,
    ) -> None:
        audit_id: int | None = None
        audited = False
        if self.audit is not None:
            try:
                entry = self.audit.record(
                    event=SANDBOX_BLOCKED_EVENT,
                    user_id=context.user_id,
                    instruction=context.instruction,
                    dag_path=context.dag_path or "sandbox",
                    tool_name=tool.metadata.name,
                    arguments=dict(arguments),
                    result={
                        "kind": kind,
                        "reason": reason,
                        "policy": self.policy.as_dict(),
                    },
                    confirmation_state="blocked",
                    risk_level=tool.metadata.risk_level.value,
                    evidence=evidence_payload(
                        policy_decision_evidence(True, f"沙箱拦截：{reason}"),
                        tool_result_evidence(False, "工具调用未通过沙箱检查"),
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - the block must still take effect
                reason = f"{reason}（审计写入失败：{exc}）"
            else:
                audit_id = int(entry["id"])
                audited = True
        violation = SandboxViolation(reason)
        violation.sandbox_kind = kind
        violation.sandbox_event = SANDBOX_BLOCKED_EVENT
        violation.sandbox_audited = audited
        violation.sandbox_audit_id = audit_id
        raise violation


# ---------------------------------------------------------------------------
# executor
# ---------------------------------------------------------------------------


def _policy_from_guards(guards: list[ExecutionGuard]) -> SandboxPolicy:
    for guard in guards:
        policy = getattr(guard, "policy", None)
        if isinstance(policy, SandboxPolicy):
            return policy
    return SandboxPolicy()


def _audit_from_guards(guards: list[ExecutionGuard]) -> AuditService | None:
    for guard in guards:
        candidate = getattr(guard, "audit", None)
        if candidate is not None:
            return candidate
    return None


class SandboxedToolExecutor(ToolExecutor):
    """``ToolExecutor`` that bounds each tool call with a wall-clock timeout."""

    def __init__(
        self,
        guards: list[ExecutionGuard] | None = None,
        *,
        audit: AuditService | None = None,
        policy: SandboxPolicy | None = None,
    ) -> None:
        super().__init__(guards)
        self.audit = audit or _audit_from_guards(self.guards)
        self.policy = policy or _policy_from_guards(self.guards)

    def execute(
        self,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        if not self.policy.enabled or self.policy.timeout_seconds <= 0:
            return super().execute(tool, arguments, context)
        timeout = self.policy.timeout_seconds
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aegis-sandbox")
        future = pool.submit(self._execute_guarded, tool, arguments, context)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            self._release_guards(force=True)
            reason = (
                f"工具 {tool.metadata.name} 执行超过沙箱超时上限 {timeout:g} 秒，"
                "已中止并写入审计。"
            )
            try:
                audited = self._record(
                    event=SANDBOX_TIMEOUT_EVENT,
                    kind="timeout",
                    reason=reason,
                    tool=tool,
                    arguments=arguments,
                    context=context,
                )
            except Exception as audit_exc:  # noqa: BLE001 - timeout must still be raised
                reason = f"{reason}（审计写入失败：{audit_exc}）"
                audited = True
            violation = SandboxViolation(reason)
            violation.sandbox_kind = "timeout"
            violation.sandbox_event = SANDBOX_TIMEOUT_EVENT
            violation.sandbox_audited = audited
            raise violation from exc
        except SandboxViolation as exc:
            if not getattr(exc, "sandbox_audited", False):
                try:
                    exc.sandbox_audited = self._record(
                        event=SANDBOX_BLOCKED_EVENT,
                        kind=getattr(exc, "sandbox_kind", "tool_violation"),
                        reason=str(exc),
                        tool=tool,
                        arguments=arguments,
                        context=context,
                    )
                except Exception as audit_exc:  # noqa: BLE001 - violation must still surface
                    exc.sandbox_audited = True
                    exc.add_note(f"沙箱审计写入失败：{audit_exc}")
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _execute_guarded(
        self,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        try:
            return super().execute(tool, arguments, context)
        finally:
            self._release_guards()

    def _release_guards(self, *, force: bool = False) -> None:
        for guard in self.guards:
            if force:
                force_release = getattr(guard, "force_release", None)
                if callable(force_release):
                    force_release()
            release = getattr(guard, "release_thread", None)
            if callable(release):
                release()

    def _record(
        self,
        *,
        event: str,
        kind: str,
        reason: str,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> bool:
        if self.audit is None:
            return False
        self.audit.record(
            event=event,
            user_id=context.user_id,
            instruction=context.instruction,
            dag_path=context.dag_path or "sandbox",
            tool_name=tool.metadata.name,
            arguments=dict(arguments),
            result={
                "kind": kind,
                "reason": reason,
                "policy": self.policy.as_dict(),
            },
            confirmation_state="blocked",
            risk_level=tool.metadata.risk_level.value,
            evidence=evidence_payload(
                policy_decision_evidence(True, f"沙箱拦截：{reason}"),
                tool_result_evidence(False, "工具调用未通过沙箱检查"),
            ),
        )
        return True