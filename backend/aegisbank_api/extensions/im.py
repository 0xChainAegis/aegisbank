"""IM channel extension (stage 2A).

Discoverable through the core extension contract: the module owns the
``im_messages`` schema, wires the :class:`~aegisbank_api.channels.im.ImChannel`
adapter into ``services.extras["im"]`` and exposes the demo-facing HTTP entry
points. It adds no business logic and never bypasses the scheduler/gateway.

Endpoints::

    POST /api/channels/im/message   -> dispatch one IM/CLI/webhook message
    GET  /api/channels/im/help      -> field list, confirmation grammar, examples
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..channels.im import (
    CHANNELS,
    DEMO_USER,
    IM_SCHEMA_SQL,
    MAX_MESSAGE_ID_LENGTH,
    MAX_TEXT_LENGTH,
    ImChannel,
    ImMessage,
    ImReply,
)
from ..services import CoreServices
from ..trust.readiness import NotReadyError, ReadinessService

NAME = "im"
SCHEMA_SQL = IM_SCHEMA_SQL


def activate(services: CoreServices) -> None:
    """Attach the adapter once the scheduler, audit and gateway are ready."""
    services.extras["im"] = ImChannel(services)


def _adapter(services: CoreServices) -> ImChannel:
    adapter = services.extras.get("im")
    if isinstance(adapter, ImChannel):
        return adapter
    adapter = ImChannel(services)
    services.extras["im"] = adapter
    return adapter


def handle_message(services: CoreServices, message: ImMessage) -> ImReply:
    """Dispatch a message through the shared adapter (used by demos/tests)."""
    return _adapter(services).handle(services, message)


class ImMessageRequest(BaseModel):
    """One inbound IM payload; mirrors :class:`ImMessage` with validation."""

    channel: Literal["im", "cli", "webhook"] = "im"
    sender_id: str = Field(default=DEMO_USER, min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    message_id: str | None = Field(default=None, max_length=MAX_MESSAGE_ID_LENGTH)

    @field_validator("sender_id", "text")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("不能为空。")
        return cleaned

    @field_validator("message_id")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


def router(services: CoreServices) -> APIRouter:
    api = APIRouter(prefix="/api/channels/im", tags=["channels"])
    readiness = ReadinessService(
        db=services.db,
        audit=services.require_audit(),
        repository=services.repository,
        planner=getattr(services.scheduler, "planner", None),
        user_id=DEMO_USER,
    )
    demo_otp = str(services.settings.demo_otp)

    @api.get("/help")
    def im_help() -> dict[str, Any]:
        """How to drive the IM adapter from curl, a bot or the CLI demo."""
        return {
            "name": "AegisBank IM 渠道适配器",
            "channel": "im",
            "method": "POST",
            "endpoint": "/api/channels/im/message",
            "channels": list(CHANNELS),
            "demo_user": DEMO_USER,
            "message_fields": {
                "channel": "im | cli | webhook（默认 im）",
                "sender_id": "外部发送者标识，写入审计（演示环境不绑用户身份）",
                "text": f"消息正文，1-{MAX_TEXT_LENGTH} 字",
                "message_id": (
                    "可选幂等键；同一 message_id 重复提交返回首次回执，"
                    "不会二次执行"
                ),
            },
            "confirmation_syntax": [
                "确认 <action_id> <6 位验证码>",
                "确认 <action_id> 验证码 <6 位验证码>",
            ],
            "demo_otp": demo_otp,
            "audit_events": ["im_message_executed", "im_message_rejected"],
            "idempotency": (
                "message_id 命中缓存时直接回放首次回执；"
                "重试失败确认请使用新的 message_id。"
            ),
            "policy": (
                "IM 只是入口：Planner、动态风险、统一权限网关、MFA 与审计链"
                "全部复用核心链路，适配器本身不做权限判断。"
            ),
            "examples": [
                {
                    "label": "绿色：查询账单（直接执行）",
                    "payload": {
                        "channel": "im",
                        "sender_id": "alice",
                        "message_id": "msg-green-1",
                        "text": "查询我的本月账单",
                    },
                },
                {
                    "label": "红色：挂失卡片（创建待确认动作）",
                    "payload": {
                        "channel": "im",
                        "sender_id": "alice",
                        "message_id": "msg-red-1",
                        "text": "挂失 CARD-9902",
                    },
                },
                {
                    "label": "红色确认：action_id 取自上一条回执的 confirmation.id",
                    "payload": {
                        "channel": "im",
                        "sender_id": "alice",
                        "message_id": "msg-red-2",
                        "text": f"确认 cfm_xxxxxxxx 验证码 {demo_otp}",
                    },
                },
                {
                    "label": "无匹配意图：返回澄清回执",
                    "payload": {
                        "channel": "webhook",
                        "sender_id": "bot",
                        "text": "帮我处理一下",
                    },
                },
            ],
            "note": (
                "演示 OTP 仅用于本地开发；生产环境必须接入银行真实 MFA，"
                "不得复用该验证码。"
            ),
        }

    @api.post("/message")
    def post_message(body: ImMessageRequest) -> dict[str, Any]:
        try:
            readiness.require_ready()
        except NotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            message = ImMessage(
                channel=body.channel,
                sender_id=body.sender_id,
                text=body.text,
                message_id=body.message_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        adapter = _adapter(services)
        replayed = bool(
            message.message_id
            and adapter.cached_reply(services, message.message_id or "") is not None
        )
        reply = adapter.handle(services, message)
        return {
            "channel": message.channel,
            "sender_id": message.sender_id,
            "message_id": message.message_id,
            "replayed": replayed,
            **reply.as_dict(),
        }

    return api