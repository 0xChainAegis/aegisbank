"""Bounded one-session/one-active-draft state for the U2 transfer flow.

The draft is deliberately *not* an execution plan. It only remembers the
server-verified receiver of a pending contact transfer, the current amount and
the exact run/confirmation identifiers needed to continue the conversation.
Every amount change goes back through the normal planner/compiler/risk/gateway
chain; no old confirmation, MFA token or nonce is reused.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from ..audit import AuditService
from ..db import Database

ACTIVE_STATUSES = frozenset({"awaiting_amount", "awaiting_confirmation", "processing"})
TERMINAL_STATUSES = frozenset(
    {"completed", "rejected", "blocked", "failed", "unknown", "expired", "superseded"}
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_drafts (
    draft_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    instruction TEXT NOT NULL,
    clarification TEXT NOT NULL DEFAULT '',
    semantic_json TEXT NOT NULL DEFAULT '{}',
    plan_json TEXT NOT NULL DEFAULT '{}',
    plan_hash TEXT NOT NULL DEFAULT '',
    pending_action_id TEXT,
    missing_slots_json TEXT NOT NULL DEFAULT '[]',
    context_json TEXT NOT NULL DEFAULT '{}',
    run_ids_json TEXT NOT NULL DEFAULT '[]',
    last_run_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_drafts_active_session
    ON agent_drafts(user_id, session_id)
    WHERE status IN ('awaiting_amount', 'awaiting_confirmation', 'processing');
CREATE INDEX IF NOT EXISTS idx_agent_drafts_user_expiry
    ON agent_drafts(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_agent_drafts_pending_action
    ON agent_drafts(pending_action_id);
"""


class DraftError(ValueError):
    """A stable, user-visible draft/session error code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _loads(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return fallback
    return parsed


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _amount(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number.quantize(Decimal("0.01"))


def _amount_text(value: Decimal) -> str:
    text = format(value.quantize(Decimal("0.01")), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _normalise_slots(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        value = str(item).strip()
        if not value:
            continue
        label = value.rsplit(".", 1)[-1]
        if label and label not in result:
            result.append(label)
    return result


MONEY_TOKEN = r"[0-9０-９零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟.,，．点]+"
PLAIN_MONEY_TOKEN = r"[0-9０-９零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟.．点]+"
_CURRENCY = r"(?:元|块钱|块|人民币|CNY|RMB)?"
_PREFIX = r"(?:人民币|CNY|RMB)?"
_STRICT_AMOUNT_RE = re.compile(
    rf"^\s*{_PREFIX}\s*(?P<amount>{PLAIN_MONEY_TOKEN})\s*{_CURRENCY}\s*[。.!！]?\s*$",
    re.I,
)
_AMEND_WITH_OLD_RE = re.compile(
    rf"^\s*(?:不是|不要|不对|并非)\s*(?P<old>{PLAIN_MONEY_TOKEN})\s*{_CURRENCY}"
    rf"\s*[，,、]?\s*(?:改成|改为|换成|换为|改到|调整为|调成|是)\s*"
    rf"(?P<new>{PLAIN_MONEY_TOKEN})\s*{_CURRENCY}\s*[。.!！]?\s*$",
    re.I,
)
_AMEND_ONLY_RE = re.compile(
    rf"^\s*(?:改成|改为|换成|换为|改到|调整为|调成)\s*"
    rf"(?P<new>{PLAIN_MONEY_TOKEN})\s*{_CURRENCY}\s*[。.!！]?\s*$",
    re.I,
)


def _parse_decimal(raw: str) -> Decimal:
    # Reuse the deterministic amount parser; the strict whole-token regex above
    # prevents a suffix or a second action from being smuggled into a slot answer.
    from ..planning.amounts import AmountError, parse_amount

    try:
        value = Decimal(str(parse_amount(raw)))
    except (AmountError, InvalidOperation, TypeError, ValueError) as exc:
        raise DraftError(
            "missing_amount",
            "金额无法识别，请只补充一个有效金额，例如：五百 或 500 元。",
            status_code=422,
        ) from exc
    if not value.is_finite() or value <= 0 or value > Decimal("50000"):
        raise DraftError(
            "missing_amount",
            "金额必须在 0.01 至 50000 元之间，请重新补充。",
            status_code=422,
        )
    return value.quantize(Decimal("0.01"))


class ConversationDraftService:
    """SQLite-backed one-active-draft state scoped by user and session."""

    def __init__(
        self,
        db: Database,
        audit: AuditService,
        *,
        repository: Any = None,
        ttl_seconds: int = 900,
        max_terminal_per_user: int = 20,
    ) -> None:
        self.db = db
        self.audit = audit
        self.repository = repository
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.max_terminal_per_user = max(1, int(max_terminal_per_user))
        with self.db.transaction() as conn:
            conn.executescript(SCHEMA_SQL)

    # ---------- row helpers ----------
    @staticmethod
    def _row(row: Any) -> dict[str, Any] | None:
        return None if row is None else dict(row)

    def get_for_user(self, draft_id: str, user_id: str) -> dict[str, Any] | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM agent_drafts WHERE draft_id = ? AND user_id = ?",
                (draft_id, user_id),
            ).fetchone()
        return self._row(row)

    def get_by_pending_action(
        self, pending_action_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM agent_drafts WHERE pending_action_id = ?"
        params: list[Any] = [pending_action_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self.db.transaction() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row(row)
    def find_active(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM agent_drafts WHERE user_id = ? AND session_id = ? "
                "AND status IN ('awaiting_amount', 'awaiting_confirmation', 'processing') "
                "ORDER BY updated_at DESC LIMIT 1",
                (user_id, session_id),
            ).fetchone()
        return self._row(row)

    def active_for_session(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_drafts WHERE user_id = ? AND session_id = ? "
                "AND status IN ('awaiting_amount', 'awaiting_confirmation', 'processing') "
                "ORDER BY updated_at DESC",
                (user_id, session_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def public(
        self, row: dict[str, Any], *, changed_fields: list[str] | None = None
    ) -> dict[str, Any]:
        context = _loads(row.get("context_json"), {})
        payload: dict[str, Any] = {
            "draft_id": row["draft_id"],
            "session_id": row["session_id"],
            "version": int(row["version"]),
            "status": row["status"],
            "reason_code": row.get("reason_code") or "",
            "missing_slots": _normalise_slots(_loads(row.get("missing_slots_json"), [])),
            "plan_hash": row.get("plan_hash") or "",
            "pending_action_id": row.get("pending_action_id"),
            "expires_at": row["expires_at"],
            "last_run_id": row.get("last_run_id") or "",
        }
        if "current_amount_cny" in context and context["current_amount_cny"] is not None:
            payload["amount_cny"] = context["current_amount_cny"]
        if changed_fields is not None:
            payload["changed_fields"] = changed_fields
        return payload

    def _audit(
        self,
        *,
        event: str,
        user_id: str,
        instruction: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        run_id: str | None = None,
    ) -> None:
        self.audit.record(
            event=event,
            user_id=user_id,
            instruction=instruction[:2000],
            dag_path="conversation-draft",
            tool_name="planner",
            arguments=arguments,
            result=result,
            confirmation_state="draft",
            risk_level="green",
            run_id=run_id,
        )

    # ---------- transfer context extraction ----------
    def _resolve_contact(self, user_id: str, value: str) -> Any | None:
        if self.repository is None:
            return None
        from ..scenarios.transfers import contact_rows

        token = str(value or "").strip()
        if not token:
            return None
        hits = []
        for contact in contact_rows(self.repository.db, user_id):
            candidates = {
                contact.contact_id,
                contact.name,
                contact.alias or "",
                contact.phone or "",
                contact.account_id,
            }
            if token in candidates:
                hits.append(contact)
        return hits[0] if len(hits) == 1 else None

    def _transfer_context(
        self, *, user_id: str, plan_payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        semantic = plan_payload.get("semantic")
        if not isinstance(semantic, dict):
            return None
        frame = semantic.get("frame")
        if not isinstance(frame, dict):
            return None
        intents = frame.get("intents") or []
        if not any(
            isinstance(item, dict) and item.get("kind") == "contact_transfer"
            for item in intents
        ):
            return None
        slots = semantic.get("slots") or []
        contact_values = [
            str(item.get("value"))
            for item in slots
            if isinstance(item, dict)
            and item.get("slot") == "contact"
            and item.get("verified") is True
            and item.get("value")
        ]
        if not contact_values:
            # A missing-amount clarification has no executable steps yet, so the
            # server verifies the contact slot directly against this user's
            # contact facts before creating a draft.
            for intent in intents:
                if not isinstance(intent, dict):
                    continue
                frame_slots = intent.get("slots") or {}
                contact_span = frame_slots.get("contact")
                if isinstance(contact_span, dict) and contact_span.get("text"):
                    contact_values.append(str(contact_span["text"]))
        if len(contact_values) != 1:
            return None
        contact = self._resolve_contact(user_id, contact_values[0])
        if contact is None:
            return None
        steps = plan_payload.get("steps") or []
        if len(steps) > 1:
            return None
        amount: Decimal | None = None
        if steps:
            step = steps[0]
            if step.get("tool_name") != "transfer_to_contact":
                return None
            amount = _amount((step.get("arguments") or {}).get("amount_cny"))
            if amount is None:
                return None
        return {
            "contact_name": contact.name,
            "contact_phone": contact.phone,
            "receiver": contact.phone or contact.name,
            "current_amount_cny": float(amount) if amount is not None else None,
        }

    def _canonical_instruction(self, context: dict[str, Any], amount_cny: Decimal) -> str:
        # The receiver is a server-verified contact fact, not user/model text from
        # the follow-up turn. This makes "五百" unable to smuggle a new receiver.
        receiver = str(context.get("receiver") or context.get("contact_name") or "").strip()
        if not receiver:
            raise DraftError("context_expired", "草稿上下文不完整，请重新发起任务。")
        return f"给{receiver}转账{_amount_text(amount_cny)}元"

    # ---------- creation ----------
    def _cleanup(self, user_id: str) -> None:
        now = _iso(_now())
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM agent_drafts WHERE expires_at < ?", (now,))
            rows = conn.execute(
                "SELECT draft_id FROM agent_drafts WHERE user_id = ? "
                "AND status NOT IN ('awaiting_amount', 'awaiting_confirmation', 'processing') "
                "ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                (user_id, self.max_terminal_per_user),
            ).fetchall()
            for row in rows:
                conn.execute("DELETE FROM agent_drafts WHERE draft_id = ?", (row["draft_id"],))

    def create_awaiting_amount(
        self,
        *,
        user_id: str,
        session_id: str,
        instruction: str,
        plan_payload: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any] | None:
        context = self._transfer_context(user_id=user_id, plan_payload=plan_payload)
        if context is None:
            return None
        semantic = plan_payload.get("semantic") or {}
        frame = semantic.get("frame") or {}
        missing = _normalise_slots(frame.get("missing_slots") or [])
        if "amount" not in missing:
            return None
        self._cleanup(user_id)
        now = _now()
        draft_id = f"drf_{uuid4().hex}"
        expires = now + timedelta(seconds=self.ttl_seconds)
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_drafts
                    (draft_id, session_id, user_id, version, status, reason_code, instruction,
                     clarification, semantic_json, plan_json, plan_hash, pending_action_id,
                     missing_slots_json, context_json, run_ids_json, created_at, updated_at,
                     expires_at, last_run_id)
                    VALUES (?, ?, ?, 1, 'awaiting_amount', 'missing_amount', ?, ?, ?, ?, '',
                            NULL, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft_id,
                        session_id,
                        user_id,
                        instruction,
                        str(plan_payload.get("clarification") or ""),
                        _dumps(semantic),
                        _dumps(plan_payload),
                        _dumps(missing),
                        _dumps(context),
                        _dumps([run_id]),
                        _iso(now),
                        _iso(now),
                        _iso(expires),
                        run_id,
                    ),
                )
        except Exception as exc:
            raise DraftError(
                "draft_version_conflict",
                "当前会话已有活动草稿，请使用原草稿继续或显式开始新任务。",
            ) from exc
        row = self.get_for_user(draft_id, user_id)
        assert row is not None
        self._audit(
            event="conversation_draft_created",
            user_id=user_id,
            instruction=instruction,
            arguments={"draft_id": draft_id, "session_id": session_id},
            result={
                "status": "awaiting_amount",
                "missing_slots": missing,
                "run_id": run_id,
                "expires_at": _iso(expires),
            },
            run_id=run_id,
        )
        return row
    def create_awaiting_confirmation(
        self,
        *,
        user_id: str,
        session_id: str,
        instruction: str,
        plan_payload: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        context = self._transfer_context(user_id=user_id, plan_payload=plan_payload)
        if context is None:
            return None
        confirmation = result.get("confirmation") or {}
        pending_action_id = confirmation.get("id")
        if not pending_action_id:
            return None
        self._cleanup(user_id)
        now = _now()
        expires = confirmation.get("expires_at") or _iso(
            now + timedelta(seconds=self.ttl_seconds)
        )
        draft_id = f"drf_{uuid4().hex}"
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_drafts
                    (draft_id, session_id, user_id, version, status, reason_code, instruction,
                     clarification, semantic_json, plan_json, plan_hash, pending_action_id,
                     missing_slots_json, context_json, run_ids_json, created_at, updated_at,
                     expires_at, last_run_id)
                    VALUES (?, ?, ?, 1, 'awaiting_confirmation', 'awaiting_confirmation', ?,
                            '', ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft_id,
                        session_id,
                        user_id,
                        instruction,
                        _dumps(plan_payload.get("semantic") or {}),
                        _dumps(plan_payload),
                        str(plan_payload.get("plan_hash") or ""),
                        pending_action_id,
                        _dumps(context),
                        _dumps([str(result.get("run_id") or "")]),
                        _iso(now),
                        _iso(now),
                        expires,
                        str(result.get("run_id") or ""),
                    ),
                )
        except Exception as exc:
            raise DraftError(
                "draft_version_conflict",
                "当前会话已有活动草稿，请使用原草稿继续或显式开始新任务。",
            ) from exc
        row = self.get_for_user(draft_id, user_id)
        assert row is not None
        self._audit(
            event="conversation_draft_created",
            user_id=user_id,
            instruction=instruction,
            arguments={"draft_id": draft_id, "session_id": session_id},
            result={
                "status": "awaiting_confirmation",
                "pending_action_id": pending_action_id,
                "plan_hash": plan_payload.get("plan_hash"),
                "run_id": result.get("run_id"),
                "expires_at": expires,
            },
            run_id=str(result.get("run_id") or "") or None,
        )
        return row

    def mark_superseded(
        self, draft_id: str, *, user_id: str, reason: str, reason_code: str = "context_expired"
    ) -> dict[str, Any] | None:
        draft = self.get_for_user(draft_id, user_id)
        if draft is None:
            return None
        now = _iso(_now())
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE agent_drafts SET status='superseded', reason_code=?, version=version+1, "
                "updated_at=? WHERE draft_id=? AND user_id=? AND status IN "
                "('awaiting_amount','awaiting_confirmation','processing')",
                (reason_code, now, draft_id, user_id),
            )
        updated = self.get_for_user(draft_id, user_id)
        if updated is not None and updated["status"] == "superseded":
            self._audit(
                event="conversation_draft_superseded",
                user_id=user_id,
                instruction=str(draft.get("instruction") or ""),
                arguments={"draft_id": draft_id, "session_id": draft.get("session_id")},
                result={"reason": reason, "reason_code": reason_code},
            )
        return updated
    # ---------- follow-up reservation ----------
    def _load_followup(
        self,
        *,
        user_id: str,
        session_id: str | None,
        draft_id: str,
        draft_version: int,
    ) -> dict[str, Any]:
        draft = self.get_for_user(draft_id, user_id)
        if draft is None:
            raise DraftError("context_expired", "草稿不存在或不属于当前用户，请重新发起任务。")
        if session_id and draft["session_id"] != session_id:
            raise DraftError("context_expired", "会话与草稿不匹配，请重新发起任务。")
        expires = _parse_time(draft.get("expires_at"))
        if expires is None or _now() > expires:
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE agent_drafts SET status='expired', reason_code='context_expired', "
                    "version=version+1, updated_at=? WHERE draft_id=? AND user_id=?",
                    (_iso(_now()), draft_id, user_id),
                )
            raise DraftError("context_expired", "草稿已过期，请重新发起任务。")
        if draft["status"] not in {"awaiting_amount", "awaiting_confirmation"}:
            raise DraftError(
                "context_expired",
                "该草稿已结束或已被替代，不能继续编辑，请重新发起任务。",
            )
        if int(draft["version"]) != int(draft_version):
            raise DraftError(
                "draft_version_conflict",
                "草稿版本已变化，请刷新最新草稿后再试。",
            )
        return draft

    def reserve_followup(
        self,
        *,
        user_id: str,
        session_id: str | None,
        draft_id: str,
        draft_version: int,
        answer: str,
    ) -> dict[str, Any]:
        draft = self._load_followup(
            user_id=user_id,
            session_id=session_id,
            draft_id=draft_id,
            draft_version=draft_version,
        )
        context = _loads(draft.get("context_json"), {})
        step = "fill" if draft["status"] == "awaiting_amount" else "amend"
        if step == "fill":
            match = _STRICT_AMOUNT_RE.fullmatch(answer)
            if match is None:
                raise DraftError(
                    "unsupported_amendment",
                    "当前草稿只缺金额；补充回复只能提供一个金额（例如：五百）。"
                    "新增收款人、动作或条件请重新发起任务。",
                )
            new_amount = _parse_decimal(match.group("amount"))
            old_amount = None
            changed_fields = ["amount"]
        else:
            current = _amount(context.get("current_amount_cny"))
            if current is None:
                raise DraftError(
                    "context_expired", "草稿缺少当前金额，不能修订，请重新发起任务。"
                )
            match = _AMEND_WITH_OLD_RE.fullmatch(answer)
            changed_fields = ["amount"]
            if match is not None:
                stated_old = _parse_decimal(match.group("old"))
                new_amount = _parse_decimal(match.group("new"))
                if stated_old != current:
                    raise DraftError(
                        "unsupported_amendment",
                        f"表述中的原金额 {_amount_text(stated_old)} 元与当前草稿 "
                        f"{_amount_text(current)} 元不一致，未做任何修改。",
                    )
            else:
                only = _AMEND_ONLY_RE.fullmatch(answer)
                if only is None:
                    raise DraftError(
                        "unsupported_amendment",
                        "未执行草稿只允许修改金额，请使用仅含金额的修订。"
                        "收款人、动作或附加条件变更必须重新发起。",
                    )
                new_amount = _parse_decimal(only.group("new"))
            old_amount = current
        new_version = int(draft["version"]) + 1
        now = _iso(_now())
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE agent_drafts SET version=?, status='processing', reason_code='processing', "
                "updated_at=? WHERE draft_id=? AND user_id=? AND version=? "
                "AND status IN ('awaiting_amount','awaiting_confirmation')",
                (new_version, now, draft_id, user_id, int(draft["version"])),
            )
            if cursor.rowcount != 1:
                raise DraftError(
                    "draft_version_conflict",
                    "草稿已被其他请求更新，请刷新最新草稿后再试。",
                )
        reserved = self.get_for_user(draft_id, user_id)
        assert reserved is not None
        instruction = self._canonical_instruction(context, new_amount)
        self._audit(
            event="conversation_draft_followup_reserved",
            user_id=user_id,
            instruction=str(draft.get("instruction") or ""),
            arguments={
                "draft_id": draft_id,
                "session_id": draft.get("session_id"),
                "previous_version": int(draft["version"]),
                "version": new_version,
                "answer": answer[:2000],
            },
            result={
                "action": step,
                "old_amount_cny": float(old_amount) if old_amount is not None else None,
                "new_amount_cny": float(new_amount),
                "changed_fields": changed_fields,
                "old_pending_action_id": draft.get("pending_action_id"),
            },
        )
        return {
            "draft": reserved,
            "previous": draft,
            "action": step,
            "old_amount_cny": float(old_amount) if old_amount is not None else None,
            "new_amount_cny": float(new_amount),
            "changed_fields": changed_fields,
            "instruction": instruction,
            "previous_version": int(draft["version"]),
            "version": new_version,
            "old_pending_action_id": draft.get("pending_action_id"),
        }
    def abort_followup(
        self,
        *,
        draft_id: str,
        user_id: str,
        expected_version: int,
        reason: str,
        status: str = "superseded",
        reason_code: str = "context_expired",
    ) -> dict[str, Any] | None:
        now = _iso(_now())
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE agent_drafts SET status=?, reason_code=?, updated_at=? "
                "WHERE draft_id=? AND user_id=? AND version=? AND status='processing'",
                (status, reason_code, now, draft_id, user_id, expected_version),
            )
        row = self.get_for_user(draft_id, user_id)
        if row is not None:
            self._audit(
                event="conversation_draft_followup_aborted",
                user_id=user_id,
                instruction=str(row.get("instruction") or ""),
                arguments={"draft_id": draft_id},
                result={"reason": reason, "status": status, "reason_code": reason_code},
            )
        return row

    def restore_after_retryable_error(
        self, *, draft_id: str, user_id: str, expected_version: int
    ) -> dict[str, Any] | None:
        """Undo the version reservation when no external action changed yet."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM agent_drafts WHERE draft_id=? AND user_id=? AND version=? "
                "AND status='processing'",
                (draft_id, user_id, expected_version),
            ).fetchone()
            if row is None:
                return self.get_for_user(draft_id, user_id)
            restored = (
                "awaiting_amount" if not row["pending_action_id"] else "awaiting_confirmation"
            )
            reason = "missing_amount" if restored == "awaiting_amount" else "awaiting_confirmation"
            conn.execute(
                "UPDATE agent_drafts SET version=version-1, status=?, reason_code=?, updated_at=? "
                "WHERE draft_id=? AND user_id=? AND version=? AND status='processing'",
                (restored, reason, _iso(_now()), draft_id, user_id, expected_version),
            )
        return self.get_for_user(draft_id, user_id)
    def finalize_followup(
        self,
        *,
        user_id: str,
        session_id: str,
        prepared: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        draft = prepared["draft"]
        draft_id = str(draft["draft_id"])
        version = int(prepared["version"])
        confirmation = result.get("confirmation") or {}
        plan_payload = result.get("plan") or {}
        context = _loads(draft.get("context_json"), {})
        context["current_amount_cny"] = prepared["new_amount_cny"]
        run_id = str(result.get("run_id") or "")
        now = _iso(_now())
        status = str(result.get("status") or "")
        if status == "awaiting_confirmation" and confirmation.get("id"):
            expires = confirmation.get("expires_at") or _iso(
                _now() + timedelta(seconds=self.ttl_seconds)
            )
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE agent_drafts SET status='awaiting_confirmation', "
                    "reason_code='awaiting_confirmation', plan_json=?, semantic_json=?, "
                    "plan_hash=?, pending_action_id=?, missing_slots_json='[]', "
                    "context_json=?, run_ids_json=?, last_run_id=?, updated_at=?, expires_at=? "
                    "WHERE draft_id=? AND user_id=? AND version=? AND status='processing'",
                    (
                        _dumps(plan_payload),
                        _dumps(plan_payload.get("semantic") or {}),
                        str(plan_payload.get("plan_hash") or ""),
                        str(confirmation.get("id")),
                        _dumps(context),
                        _dumps(self._append_run(draft, run_id)),
                        run_id,
                        now,
                        expires,
                        draft_id,
                        user_id,
                        version,
                    ),
                )
            updated = self.get_for_user(draft_id, user_id)
            if updated is not None:
                self._audit(
                    event=(
                        "conversation_draft_amount_filled"
                        if prepared["action"] == "fill"
                        else "conversation_draft_amount_amended"
                    ),
                    user_id=user_id,
                    instruction=str(updated.get("instruction") or ""),
                    arguments={
                        "draft_id": draft_id,
                        "session_id": session_id,
                        "version": version,
                        "old_amount_cny": prepared["old_amount_cny"],
                        "new_amount_cny": prepared["new_amount_cny"],
                        "changed_fields": prepared["changed_fields"],
                    },
                    result={
                        "plan_hash": plan_payload.get("plan_hash"),
                        "pending_action_id": confirmation.get("id"),
                        "run_id": run_id,
                        "old_pending_action_id": prepared.get("old_pending_action_id"),
                    },
                    run_id=run_id or None,
                )
            return updated
        # Any result other than a new confirmation ends this draft. The user must
        # start over rather than retry against an ambiguous intermediate state.
        mapped = status if status in TERMINAL_STATUSES else "superseded"
        reason_code = str(result.get("reason_code") or "context_expired")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE agent_drafts SET status=?, reason_code=?, plan_json=?, "
                "semantic_json=?, plan_hash=?, pending_action_id=NULL, "
                "context_json=?, run_ids_json=?, last_run_id=?, updated_at=? "
                "WHERE draft_id=? AND user_id=? AND version=? AND status='processing'",
                (
                    mapped,
                    reason_code,
                    _dumps(plan_payload),
                    _dumps(plan_payload.get("semantic") or {}),
                    str(plan_payload.get("plan_hash") or ""),
                    _dumps(context),
                    _dumps(self._append_run(draft, run_id)),
                    run_id,
                    now,
                    draft_id,
                    user_id,
                    version,
                ),
            )
        updated = self.get_for_user(draft_id, user_id)
        if updated is not None:
            self._audit(
                event="conversation_draft_followup_ended",
                user_id=user_id,
                instruction=str(updated.get("instruction") or ""),
                arguments={"draft_id": draft_id, "session_id": session_id},
                result={"status": mapped, "reason_code": reason_code, "run_id": run_id},
                run_id=run_id or None,
            )
        return updated

    @staticmethod
    def _append_run(draft: dict[str, Any], run_id: str) -> list[str]:
        values = _loads(draft.get("run_ids_json"), [])
        result = [str(item) for item in values if item]
        if run_id and run_id not in result:
            result.append(run_id)
        return result[-10:]
    # ---------- confirmation lifecycle ----------
    def on_confirmation_result(
        self, *, pending_action_id: str, user_id: str, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        draft = self.get_by_pending_action(pending_action_id, user_id)
        if draft is None or draft["status"] != "awaiting_confirmation":
            return draft
        status = str(result.get("status") or "")
        mapped = status if status in TERMINAL_STATUSES else "superseded"
        run_id = str(result.get("run_id") or "")
        now = _iso(_now())
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE agent_drafts SET status=?, reason_code=?, version=version+1, "
                "run_ids_json=?, last_run_id=?, updated_at=? "
                "WHERE draft_id=? AND user_id=? AND status='awaiting_confirmation'",
                (
                    mapped,
                    mapped,
                    _dumps(self._append_run(draft, run_id)),
                    run_id,
                    now,
                    draft["draft_id"],
                    user_id,
                ),
            )
        updated = self.get_for_user(str(draft["draft_id"]), user_id)
        if updated is not None:
            self._audit(
                event="conversation_draft_closed",
                user_id=user_id,
                instruction=str(draft.get("instruction") or ""),
                arguments={"draft_id": draft["draft_id"]},
                result={"status": mapped, "pending_action_id": pending_action_id, "run_id": run_id},
                run_id=run_id or None,
            )
        return updated

    def supersede_session(
        self, *, user_id: str, session_id: str, exclude_draft_id: str | None = None
    ) -> list[dict[str, Any]]:
        drafts = [
            item
            for item in self.active_for_session(user_id, session_id)
            if item["draft_id"] != exclude_draft_id
        ]
        updated: list[dict[str, Any]] = []
        for item in drafts:
            row = self.mark_superseded(
                str(item["draft_id"]),
                user_id=user_id,
                reason="同一会话开始了新的任务，旧草稿已失效",
                reason_code="context_expired",
            )
            if row is not None:
                updated.append(row)
        return updated

    def expire_stale(self) -> int:
        now = _iso(_now())
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE agent_drafts SET status='expired', reason_code='context_expired', "
                "version=version+1, updated_at=? WHERE expires_at < ? "
                "AND status IN ('awaiting_amount','awaiting_confirmation')",
                (now, now),
            )
            return int(cursor.rowcount)