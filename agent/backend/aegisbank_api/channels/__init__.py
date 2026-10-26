"""IM / CLI / webhook channel adapters (stage 2A).

The channel layer is intentionally thin: it normalizes an inbound message,
parses the explicit confirmation grammar, and delegates to ``DagScheduler`` so
an external chat entry point reuses the same planner, risk engine, permission
gateway, MFA provider and audit chain as the Web console.

See :mod:`aegisbank_api.channels.im` for the contract, audit events and
``message_id`` idempotency behaviour.
"""

from __future__ import annotations

from .im import (
    CHANNELS,
    DEMO_USER,
    MAX_MESSAGE_ID_LENGTH,
    MAX_TEXT_LENGTH,
    ImAdapter,
    ImChannel,
    ImMessage,
    ImReply,
    handle,
)

__all__ = [
    "CHANNELS",
    "DEMO_USER",
    "MAX_MESSAGE_ID_LENGTH",
    "MAX_TEXT_LENGTH",
    "ImAdapter",
    "ImChannel",
    "ImMessage",
    "ImReply",
    "handle",
]