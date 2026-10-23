"""IM channel adapter: a thin, governed entry point for external messages.

The adapter never plans, authorizes or executes a tool on its own. It parses an
explicit confirmation command or forwards free-form text to the existing
``DagScheduler``, so the IM path reuses exactly the same rule planner, dynamic
risk engine, permission gateway, MFA provider and SHA-256 audit chain as the
Web console.

Supported commands::

    确认 <action_id> <otp>
    确认 <action_id> 验证码 <otp>

Any other text becomes ``scheduler.run(instruction=text)``.

Every inbound message is audited as ``im_message_executed`` (with the resulting
status) or ``im_message_rejected`` (with the error reason). When the caller
supplies ``message_id`` the first :class:`ImReply` is cached in ``im_messages``
and replayed verbatim, so an IM platform retrying a delivery never triggers a
second financial action. Idempotency is scoped by channel, sender and message ID,
with a content hash. To retry a failed confirmation, send a new message ID.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from ..db import utc_now
from ..scheduler import ExecutionFailedError, IntentError, ReauthError
from ..services import CoreServices
from ..trust.action_envelope import EnvelopeError, canonical_hash
from ..trust.evidence import evidence_payload, policy_decision_evidence
from ..trust.idempotency import IdempotencyKeyReused

DEMO_USER = "demo-user"
CHANNELS: tuple[str, ...] = ("im", "cli", "webhook")
MAX_TEXT_LENGTH = 2000
MAX_MESSAGE_ID_LENGTH = 96

ImChannelName = Literal["im", "cli", "webhook"]

CONFIRM_PATTERN = re.compile(
    r"^\s*确认\s+(?P<action_id>[A-Za-z0-9_-]{3,64})"
    r"(?:\s+(?:验证码\s*)?(?P<otp>\d{6}))?\s*$"
)

IM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS im_actions (
    action_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS im_messages (
    message_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    text TEXT NOT NULL,
    reply_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_CONFIRMATION_STATES = {
    "completed": "not_required",
    "awaiting_confirmation": "pending",
    "needs_clarification": "clarification",
    "blocked": "blocked",
    "rejected": "rejected",
    "failed": "failed",
    "unknown": "unknown",
    "reconciled": "reconciled",
    "rolled_back": "rolled_back",
}


@dataclass(frozen=True, slots=True)
class ImMessage:
    """One normalized inbound message; ``channel`` is im / cli / webhook."""

    channel: ImChannelName
    sender_id: str
    text: str
    message_id: str | None = None
    role: str = "user"

    def __post_init__(self) -> None:
        channel = str(self.channel or "").strip().lower()
        if channel not in CHANNELS:
            raise ValueError(f"不支持的 IM 渠道：{self.channel}（可选：{' / '.join(CHANNELS)}）。")
        sender_id = str(self.sender_id or "").strip()
        if not sender_id:
            raise ValueError("sender_id 不能为空。")
        text = str(self.text or "").strip()
        if not text:
            raise ValueError("消息内容不能为空。")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(f"消息内容过长（最多 {MAX_TEXT_LENGTH} 字）。")
        raw_message_id = str(self.message_id).strip() if self.message_id else ""
        if len(raw_message_id) > MAX_MESSAGE_ID_LENGTH:
            raise ValueError(f"message_id 过长（最多 {MAX_MESSAGE_ID_LENGTH} 字符）。")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "sender_id", sender_id)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "message_id", raw_message_id or None)


@dataclass(slots=True)
class ImReply:
    """A human-readable receipt plus the untouched scheduler result."""

    text: str
    status: str
    structured: dict[str, Any] = field(default_factory=dict)
    confirmation: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "status": self.status,
            "structured": self.structured,
            "confirmation": self.confirmation,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ImReply:
        confirmation = payload.get("confirmation")
        return cls(
            text=str(payload.get("text") or ""),
            status=str(payload.get("status") or "unknown"),
            structured=dict(payload.get("structured") or {}),
            confirmation=dict(confirmation) if isinstance(confirmation, dict) else None,
        )


class ImChannel:
    """Dispatch inbound messages; never bypasses the governed execution path."""

    name = "im"

    def __init__(self, services: CoreServices | None = None) -> None:
        self.services = services
        self._schema_path: str | None = None

    # ---------- public API ----------
    def handle(self, services: CoreServices | None, message: ImMessage) -> ImReply:
        """Return a receipt for ``message``; cached by ``message_id`` if given."""
        bound = services or self.services
        if bound is None:
            raise RuntimeError("IM 适配器尚未绑定 CoreServices。")
        if not isinstance(message, ImMessage):
            raise TypeError("message 必须是 ImMessage。")
        bound.authz.require(message.role, "tool:execute")
        with bound.db.action_lock(
            "im:"
            + self._cache_key(
                message.channel,
                message.sender_id,
                message.message_id or canonical_hash(message.text),
            )
        ):
            return self._handle_locked(bound, message)

    def _handle_locked(self, bound: CoreServices, message: ImMessage) -> ImReply:
        if message.message_id:
            cached = self.cached_reply(
                bound,
                message.message_id,
                channel=message.channel,
                sender_id=message.sender_id,
                text=message.text,
            )
            if cached is not None:
                return cached
        match = CONFIRM_PATTERN.match(message.text)
        if match:
            reply = self._confirm(
                bound,
                message,
                action_id=match.group("action_id"),
                otp=match.group("otp"),
            )
        else:
            reply = self._run(bound, message)
        if message.message_id:
            self._store_reply(bound, message, reply)
        return reply

    @staticmethod
    def _cache_key(channel: str, sender_id: str, message_id: str) -> str:
        return canonical_hash([channel, sender_id, message_id])

    def cached_reply(
        self,
        services: CoreServices,
        message_id: str,
        *,
        channel: str = "im",
        sender_id: str = DEMO_USER,
        text: str | None = None,
    ) -> ImReply | None:
        if not message_id:
            return None
        self._ensure_schema(services)
        with services.db.transaction() as conn:
            row = conn.execute(
                "SELECT reply_json, text FROM im_messages WHERE message_id = ?",
                (self._cache_key(channel, sender_id, message_id),),
            ).fetchone()
        if row is None or not row["reply_json"]:
            return None
        if text is not None and row["text"] != canonical_hash(text):
            raise IdempotencyKeyReused("相同通道和发送者的 message_id 不能携带不同内容。")
        try:
            payload = json.loads(row["reply_json"])
        except ValueError:
            return None
        return ImReply.from_dict(payload) if isinstance(payload, dict) else None

    # ---------- dispatch ----------
    def _run(self, services: CoreServices, message: ImMessage) -> ImReply:
        try:
            result = services.scheduler.run(
                user_id=DEMO_USER,
                instruction=message.text,
                role=message.role,
            )
        except (IntentError, ExecutionFailedError) as exc:
            return self._reject(services, message, exc, stage="run")
        return self._accept(services, message, result)

    def _confirm(
        self,
        services: CoreServices,
        message: ImMessage,
        *,
        action_id: str,
        otp: str | None,
    ) -> ImReply:
        with services.db.transaction() as conn:
            owner = conn.execute(
                "SELECT channel, sender_id FROM im_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
        if owner is None or (owner["channel"], owner["sender_id"]) != (
            message.channel,
            message.sender_id,
        ):
            return self._reject(
                services,
                message,
                IntentError("确认动作不属于该通道发送者。"),
                stage="confirm",
                action_id=action_id,
            )
        try:
            result = services.scheduler.confirm(
                user_id=DEMO_USER,
                action_id=action_id,
                approved=True,
                reauth_token=otp,
                role=message.role,
                mfa_provider=None,
            )
        except (ReauthError, IntentError, ExecutionFailedError, EnvelopeError) as exc:
            return self._reject(services, message, exc, stage="confirm", action_id=action_id)
        return self._accept(services, message, result)

    def _accept(
        self, services: CoreServices, message: ImMessage, result: dict[str, Any]
    ) -> ImReply:
        status = str(result.get("status") or "unknown")
        raw_confirmation = result.get("confirmation")
        confirmation = raw_confirmation if isinstance(raw_confirmation, dict) else None
        if confirmation and confirmation.get("id"):
            with services.db.transaction() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO im_actions (action_id, channel, sender_id) "
                    "VALUES (?, ?, ?)",
                    (confirmation["id"], message.channel, message.sender_id),
                )
        reply = ImReply(
            text=self._render_text(
                status,
                result,
                demo_otp=str(services.settings.demo_otp),
            ),
            status=status,
            structured=result,
            confirmation=dict(confirmation) if confirmation is not None else None,
        )
        self._record_audit(
            services,
            message,
            event="im_message_executed",
            status=status,
            result={
                "channel": message.channel,
                "sender_id": message.sender_id,
                "message_id": message.message_id,
                "status": status,
                "run_id": str(result.get("run_id") or ""),
                "reason": str(result.get("reason") or "")[:240],
                "action_id": str((confirmation or {}).get("id") or "") or None,
            },
            risk_level=str(result.get("risk_level") or "green"),
        )
        return reply

    def _reject(
        self,
        services: CoreServices,
        message: ImMessage,
        error: Exception,
        *,
        stage: str,
        action_id: str | None = None,
    ) -> ImReply:
        detail = str(error).strip() or error.__class__.__name__
        prefix = "确认失败" if stage == "confirm" else "处理失败"
        risk_level = "green"
        if action_id:
            pending = services.db.get_pending(action_id)
            if pending is not None:
                risk_level = str(pending.get("risk_level") or "green")
        reply = ImReply(
            text=f"❌ {prefix}：{detail}",
            status="rejected",
            structured={
                "status": "rejected",
                "reason": detail,
                "error_type": error.__class__.__name__,
                "action_id": action_id,
            },
        )
        self._record_audit(
            services,
            message,
            event="im_message_rejected",
            status="rejected",
            result={
                "channel": message.channel,
                "sender_id": message.sender_id,
                "message_id": message.message_id,
                "status": "rejected",
                "error": detail,
                "error_type": error.__class__.__name__,
                "action_id": action_id,
            },
            risk_level=risk_level,
        )
        return reply

    # ---------- rendering ----------
    def _render_text(self, status: str, result: dict[str, Any], *, demo_otp: str) -> str:
        reason = str(result.get("reason") or "").strip()
        if status == "completed":
            lines = ["✅ 已完成。"]
            if reason:
                lines.append(f"原因：{reason}")
            lines.extend(self._summarize_results(result.get("results")))
            return "\n".join(lines)
        if status == "awaiting_confirmation":
            raw_confirmation = result.get("confirmation")
            confirmation = raw_confirmation if isinstance(raw_confirmation, dict) else {}
            action_id = str(confirmation.get("id") or "")
            risk = str(result.get("risk_level") or "")
            requires_reauth = bool(confirmation.get("requires_reauth")) or risk == "red"
            lines = [f"⏳ 该操作需要人工确认（风险等级：{risk or '未知'}）。"]
            if reason:
                lines.append(f"原因：{reason}")
            if requires_reauth:
                lines.append(f"请在有效期内回复：确认 {action_id} 验证码 <6 位动态验证码>")
                lines.append(f"本地演示验证码：{demo_otp}（生产环境须接入银行真实 MFA）。")
            else:
                lines.append(f"请在有效期内回复：确认 {action_id}")
            return "\n".join(lines)
        if status == "needs_clarification":
            return f"❓ 需要补充信息：{reason or '请提供更具体的指令。'}"
        if status == "blocked":
            return f"⛔ 已拦截：{reason or '请求未通过权限网关。'}"
        if status == "rejected":
            return f"🚫 已拒绝：{reason or '操作已拒绝。'}"
        if status == "failed":
            return f"⚠️ 执行失败：{reason or '工具执行失败。'}"
        if status == "unknown":
            return f"⚠️ 结果不确定：{reason or '请先对账，勿重复提交。'}"
        return f"ℹ️ 状态：{status}。{reason}"

    @staticmethod
    def _summarize_results(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        lines: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("tool_name") or "tool")
            message = str(item.get("message") or "").strip()
            lines.append(f"• {name}：{message}" if message else f"• {name}")
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            facts: list[str] = []
            for key, fact in data.items():
                if isinstance(fact, (dict, list)) or key in {"simulated", "transactions"}:
                    continue
                facts.append(f"{key}={fact}")
                if len(facts) >= 4:
                    break
            if facts:
                lines.append("  " + " · ".join(facts))
        return lines

    # ---------- audit ----------
    def _record_audit(
        self,
        services: CoreServices,
        message: ImMessage,
        *,
        event: str,
        status: str,
        result: dict[str, Any],
        risk_level: str,
    ) -> None:
        services.require_audit().record(
            event=event,
            user_id=DEMO_USER,
            instruction=self._redact(message.text),
            dag_path=f"im:{message.channel}",
            tool_name="im_channel",
            arguments={
                "channel": message.channel,
                "sender_id": message.sender_id,
                "message_id": message.message_id,
                "text": self._redact(message.text),
            },
            result=result,
            confirmation_state=_CONFIRMATION_STATES.get(status, status),
            risk_level=risk_level,
            evidence=evidence_payload(
                policy_decision_evidence(True, "IM 渠道消息复用统一 Planner / 权限网关 / 审计链")
            ),
        )

    # ---------- idempotency cache ----------
    @staticmethod
    def _redact(text: str) -> str:
        if CONFIRM_PATTERN.match(text):
            return re.sub(r"\b\d{6}\b", "[REDACTED]", text)
        return text

    def _ensure_schema(self, services: CoreServices) -> None:
        path = str(services.db.path)
        if self._schema_path == path:
            return
        with services.db.transaction() as conn:
            conn.executescript(IM_SCHEMA_SQL)
        self._schema_path = path

    def _store_reply(self, services: CoreServices, message: ImMessage, reply: ImReply) -> None:
        if not message.message_id:
            return
        self._ensure_schema(services)
        with services.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO im_messages
                (message_id, channel, sender_id, text, reply_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self._cache_key(message.channel, message.sender_id, message.message_id),
                    message.channel,
                    message.sender_id,
                    canonical_hash(message.text),
                    json.dumps(reply.as_dict(), ensure_ascii=False, sort_keys=True),
                    utc_now(),
                ),
            )


ImAdapter = ImChannel


def handle(services: CoreServices, message: ImMessage) -> ImReply:
    """Convenience entry point: attach the adapter to ``services.extras`` once."""
    adapter = services.extras.get("im")
    if not isinstance(adapter, ImChannel):
        adapter = ImChannel(services)
        services.extras["im"] = adapter
    return adapter.handle(services, message)
