"""时间维度场景：定时转账调度、预算资金锁定与生日跨场景联动。

模块契约见同目录 ``README.md``：

- 事实全部来自 SQLite（本模块 ``SCHEMA_SQL`` + ``seed``，以及 transfers 模块的
  ``contacts`` 联系人簿）；Planner 不得凭空造人或造日期；
- 资金动作只经工具节点执行，最终由统一权限网关裁决；路由层只读，
  ``POST /api/automation/run-due`` 通过调度器调用 ``run_due_tasks`` 工具完成“时间快进”；
- 到期执行前重新调用 ``gateway.evaluate`` 复检权限，审计 event 为
  ``scheduled_task_executed`` 且 result 内含 ``trigger_source="scheduled"``；
- 任务在统一事务中完成领取、子工具执行与 done 提交，重复调用不会重复扣款；
- 后台线程只在 ``settings.automation_enabled`` 为真时启动，测试默认关闭。
"""

from __future__ import annotations

import calendar
import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from ..banking.repository import SHANGHAI_TZ, to_cents, to_cny
from ..compensation import CompensationSpec
from ..db import Database
from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..planning.contracts import ExecutionPlan, PlanStep
from ..planning.intents import IntentContext, extract_amounts
from ..registry import BaseTool
from ..risk_rules import RiskContext, RiskGuess
from ..services import CoreServices
from ..trust.action_envelope import canonical_hash
from ..trust.readiness import NotReadyError

NAME = "automation"
SIMULATED = True
DEFAULT_USER = "demo-user"
SELF_ACCOUNT = "ACC-1001"

FLOWER_AMOUNT_CNY = 199.0
CAKE_AMOUNT_CNY = 159.0
GIFT_LEAD_DAYS = 2
MAX_TRANSFER_CNY = 50_000.0
HIGH_TRANSFER_THRESHOLD_CNY = 5_000.0
DEFAULT_RUN_HOUR_SHANGHAI = 9
DEFAULT_RUN_HOUR_UTC = DEFAULT_RUN_HOUR_SHANGHAI


class ScheduledTaskNeedsReauth(PermissionError):
    """A due task is safe to keep pending but needs a stronger re-auth mandate."""

    def __init__(
        self,
        reason: str,
        *,
        required_risk: str,
        original_risk: str,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.required_risk = required_risk
        self.original_risk = original_risk


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    task_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('transfer', 'gift')),
    payload_json TEXT NOT NULL,
    run_at TEXT NOT NULL,
    recurrence TEXT NOT NULL DEFAULT 'none'
        CHECK (recurrence IN ('none', 'monthly', 'yearly')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'cancelled', 'failed')),
    last_run_at TEXT,
    last_result_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user
    ON scheduled_tasks(user_id, status, run_at);

CREATE TABLE IF NOT EXISTS scheduled_authorizations (
    task_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_action_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    mfa_verified INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_goals (
    goal_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    target_cents INTEGER NOT NULL,
    locked_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'cancelled')),
    deadline TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_budget_goals_user ON budget_goals(user_id, status);

CREATE TABLE IF NOT EXISTS gift_orders (
    order_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    goal_id TEXT,
    gift_kind TEXT NOT NULL CHECK (gift_kind IN ('flowers', 'cake')),
    amount_cents INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'ordered', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_gift_orders_user ON gift_orders(user_id, status, due_at);
"""

_ACCOUNT_PATTERN = re.compile(r"ACC-\d{3,}", re.IGNORECASE)
_PHONE_IN_TEXT_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_PHONE_FULL_PATTERN = re.compile(r"1[3-9]\d{9}")
_NAME_TRANSFER_PATTERN = re.compile(
    r"(?:给|向|帮|替)\s*([\u4e00-\u9fa5A-Za-z·]{1,12}?)\s*(?:转账|汇款|转)"
)
_TASK_ID_PATTERN = re.compile(r"TASK-[A-Z0-9]{4,}")

_SCHEDULE_HINTS = (
    "定时",
    "每天",
    "每周",
    "每月",
    "每个月",
    "每年",
    "明天",
    "后天",
    "下周",
    "下个月",
    "明年",
    "之后",
    "将来",
    "自动",
)
_TRANSFER_VERBS = ("转账", "汇款", "转")
_WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
_TASK_STATUSES = ("pending", "done", "cancelled", "failed", "all")


# ---------------------------------------------------------------------------
# 时间与任务基础工具函数
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_iso_datetime(value: str) -> datetime:
    """Parse ISO8601 (full datetime or ``YYYY-MM-DD``) into an aware UTC value."""
    text = (value or "").strip()
    if not text:
        raise ValueError("时间不能为空")
    normalized = text[:-1] + "+00:00" if text[-1:] in {"Z", "z"} else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"无法解析时间：{value}（请使用 ISO8601，例如 2026-12-01T09:00:00+08:00）"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise ValueError(f"无法解析日期：{value}（应为 YYYY-MM-DD）") from exc


def _safe_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        if month == 2 and day == 29:
            return date(year, 3, 1)
        raise ValueError(f"日期非法：{year} 年 {month} 月 {day} 日") from exc


def _today() -> date:
    """Return the user-facing banking date in Asia/Shanghai."""
    return datetime.now(SHANGHAI_TZ).date()


def _future_morning(moment: date, now: datetime) -> datetime:
    # 09:00 is a China-local wall-clock time, not 09:00 UTC.
    target = datetime(
        moment.year,
        moment.month,
        moment.day,
        DEFAULT_RUN_HOUR_SHANGHAI,
        tzinfo=SHANGHAI_TZ,
    ).astimezone(UTC)
    if target <= now:
        raise ValueError("执行时间必须晚于当前时间，请调整时间。")
    return target


def _next_monthly_day(today: date, day: int) -> date:
    if not 1 <= day <= 31:
        raise ValueError(f"日期非法：每月 {day} 号")
    year, month = today.year, today.month
    for _ in range(14):
        last = calendar.monthrange(year, month)[1]
        candidate = date(year, month, min(day, last))
        if candidate > today:
            return candidate
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    raise ValueError("无法计算下一次执行日期。")


def _next_annual_date(today: date, month: int, day: int) -> date:
    for year in (today.year, today.year + 1, today.year + 2):
        candidate = _safe_date(year, month, day)
        if candidate > today:
            return candidate
    raise ValueError("无法计算下一次执行日期。")


def _next_birthday(birthday: date, today: date) -> date:
    try:
        candidate = birthday.replace(year=today.year)
    except ValueError:
        candidate = date(today.year, 3, 1)
    if candidate < today:
        try:
            candidate = birthday.replace(year=today.year + 1)
        except ValueError:
            candidate = date(today.year + 1, 3, 1)
    return candidate


def _at_morning_utc(moment: date) -> datetime:
    return datetime(
        moment.year,
        moment.month,
        moment.day,
        DEFAULT_RUN_HOUR_SHANGHAI,
        tzinfo=SHANGHAI_TZ,
    ).astimezone(UTC)


def _resolve_run_at(instruction: str, now: datetime) -> tuple[datetime, str]:
    """Resolve a scheduled-transfer execution time from the instruction."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    today = now.astimezone(SHANGHAI_TZ).date()
    if "每天" in instruction or "每周" in instruction:
        raise ValueError("当前仅支持一次性、每月或每年的定时转账，暂不支持每天/每周。")
    recurrence = "none"
    if "每月" in instruction or "每个月" in instruction:
        recurrence = "monthly"
    elif "每年" in instruction:
        recurrence = "yearly"

    iso_match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", instruction)
    if iso_match is not None:
        target = _safe_date(
            int(iso_match.group(1)),
            int(iso_match.group(2)),
            int(iso_match.group(3)),
        )
        return _future_morning(target, now), recurrence

    if recurrence == "monthly":
        day_match = re.search(r"每(?:个)?月\s*(\d{1,2})\s*[日号]", instruction)
        if day_match is None:
            day_match = re.search(r"(\d{1,2})\s*号", instruction)
        if day_match is not None:
            return _future_morning(
                _next_monthly_day(today, int(day_match.group(1))), now
            ), recurrence
        raise ValueError("每月定时转账需要指定日期，例如：每月 5 号给张三转 500 元。")

    next_month_match = re.search(r"下个?月\s*(\d{1,2})\s*[日号]", instruction)
    if next_month_match is not None:
        target = _safe_date(
            today.year + 1 if today.month == 12 else today.year,
            1 if today.month == 12 else today.month + 1,
            int(next_month_match.group(1)),
        )
        return _future_morning(target, now), recurrence

    week_match = re.search(r"下(?:个)?周([一二三四五六日天])", instruction)
    if week_match is not None:
        weekday = _WEEKDAY_MAP[week_match.group(1)]
        days_to_monday = (7 - today.weekday()) % 7 or 7
        target = today + timedelta(days=days_to_monday + weekday)
        return _future_morning(target, now), recurrence

    if "大后天" in instruction:
        return _future_morning(today + timedelta(days=3), now), recurrence
    if "后天" in instruction:
        return _future_morning(today + timedelta(days=2), now), recurrence
    if "明天" in instruction:
        return _future_morning(today + timedelta(days=1), now), recurrence

    month_day_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", instruction)
    if month_day_match is not None:
        target = _next_annual_date(
            today, int(month_day_match.group(1)), int(month_day_match.group(2))
        )
        return _future_morning(target, now), recurrence

    raise ValueError(
        "请提供明确的执行时间，例如：明天、下周三、每月 5 号、每年 3 月 15 日或 2026-12-01。"
    )


def _transfer_amount_from(instruction: str) -> float | None:
    amounts = extract_amounts(instruction)
    return amounts[-1] if amounts else None


def _budget_amount_from(instruction: str) -> float | None:
    amounts = extract_amounts(instruction)
    return amounts[0] if amounts else None


# ---------------------------------------------------------------------------
# 联系人簿读取（transfers 场景拥有 contacts 表；只读，不写别人的表）
# ---------------------------------------------------------------------------


def _contact_rows(db: Database, user_id: str) -> list[dict[str, Any]]:
    try:
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM contacts WHERE user_id = ? AND status = 'active' "
                "ORDER BY contact_id",
                (user_id,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


def _resolve_contact(
    db: Database, user_id: str, token: str
) -> tuple[dict[str, Any] | None, str | None]:
    contacts = _contact_rows(db, user_id)
    if not contacts:
        return None, "联系人簿为空或未启用，请先在转账场景添加联系人，我不会猜测收款人。"
    key = token.strip().casefold()
    hits = [
        item
        for item in contacts
        if str(item.get("name") or "").casefold() == key
        or str(item.get("alias") or "").casefold() == key
        or str(item.get("phone") or "") == token.strip()
    ]
    if not hits:
        return None, f"联系人簿中未找到「{token}」，请先添加联系人，我不会猜测收款人。"
    if len(hits) > 1:
        return None, f"「{token}」匹配到多个联系人，请改用手机号或别名，我不会猜测收款人。"
    return hits[0], None


def _mentioned_contact(
    db: Database, user_id: str, instruction: str
) -> tuple[dict[str, Any] | None, str | None]:
    contacts = _contact_rows(db, user_id)
    if not contacts:
        return None, "联系人簿为空或未启用，请先在转账场景添加联系人，我不会猜测生日对象。"
    hits = [
        item
        for item in contacts
        if any(
            token and str(token) in instruction for token in (item.get("name"), item.get("alias"))
        )
    ]
    if not hits:
        return None, "未在联系人簿中找到生日对象，请先添加联系人，我不会猜测联系人。"
    if len(hits) > 1:
        names = "、".join(str(item.get("name")) for item in hits)
        return None, f"识别到多个生日对象（{names}），请一次只准备一位联系人的生日。"
    return hits[0], None


# ---------------------------------------------------------------------------
# 行数据转换与通用查询
# ---------------------------------------------------------------------------


def _task_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(str(row["payload_json"] or "{}"))
    last_result = json.loads(str(row["last_result_json"] or "{}"))
    return {
        "task_id": str(row["task_id"]),
        "kind": str(row["kind"]),
        "status": str(row["status"]),
        "run_at": str(row["run_at"]),
        "recurrence": str(row["recurrence"]),
        "created_at": str(row["created_at"]),
        "last_run_at": row["last_run_at"],
        "last_result": last_result or None,
        "payload": payload,
        "amount_cny": payload.get("amount_cny"),
        "label": payload.get("label") or payload.get("note"),
        "simulated": SIMULATED,
    }


def _goal_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "goal_id": str(row["goal_id"]),
        "name": str(row["name"]),
        "target_cny": to_cny(int(row["target_cents"])),
        "locked_cny": to_cny(int(row["locked_cents"])),
        "status": str(row["status"]),
        "deadline": row["deadline"],
        "created_at": str(row["created_at"]),
        "simulated": SIMULATED,
    }


def _order_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "order_id": str(row["order_id"]),
        "goal_id": row["goal_id"],
        "gift_kind": str(row["gift_kind"]),
        "amount_cny": to_cny(int(row["amount_cents"])),
        "due_at": str(row["due_at"]),
        "status": str(row["status"]),
        "simulated": SIMULATED,
    }


def _task_rows(db: Database, user_id: str, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM scheduled_tasks WHERE user_id = ?"
    params: list[Any] = [user_id]
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY run_at ASC, task_id ASC"
    with db.transaction() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_task_row_to_dict(row) for row in rows]


def _new_task_id(conn: sqlite3.Connection) -> str:
    """Digits-only task ids: hex ids could contain "AA" and trip AA intents."""
    for _ in range(20):
        task_id = f"TASK-{uuid4().int % 100_000_000:08d}"
        exists = conn.execute(
            "SELECT 1 FROM scheduled_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if exists is None:
            return task_id
    raise ValueError("定时任务编号生成失败，请重试。")


def _insert_scheduled_task(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    kind: str,
    payload: dict[str, Any],
    run_at: str,
    recurrence: str = "none",
) -> str:
    task_id = _new_task_id(conn)
    conn.execute(
        """
        INSERT INTO scheduled_tasks
        (task_id, user_id, kind, payload_json, run_at, recurrence, status,
         last_run_at, last_result_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?)
        """,
        (
            task_id,
            user_id,
            kind,
            json.dumps(payload, ensure_ascii=False),
            run_at,
            recurrence,
            _iso_now(),
        ),
    )
    return task_id


# ---------------------------------------------------------------------------
# 演示数据 seed：空表，避免干扰测试（幂等）
# ---------------------------------------------------------------------------


def seed(db: Database, user_id: str) -> None:
    """Intentionally seed nothing: scheduled tasks are only created by tools.

    Keeping these tables empty makes every test deterministic and avoids demo
    rows accidentally executing during someone else's test window.
    """
    return


# ---------------------------------------------------------------------------
# 工具输入模型
# ---------------------------------------------------------------------------


def _store_task_authorization(
    conn, task_id: str, payload: dict[str, Any], context: ExecutionContext
) -> None:
    if context.approved_risk is RiskLevel.GREEN:
        raise PermissionError("创建定时写任务必须具有用户明确确认的授权。")
    conn.execute(
        "INSERT INTO scheduled_authorizations "
        "(task_id,user_id,source_action_id,payload_hash,risk_level,mfa_verified) "
        "VALUES (?,?,?,?,?,?)",
        (
            task_id,
            context.user_id,
            context.run_id,
            canonical_hash(payload),
            context.approved_risk.value,
            int(context.reauth_verified),
        ),
    )


class QueryContactBirthdayArgs(BaseModel):
    to_name: str | None = Field(default=None, max_length=32)
    to_phone: str | None = Field(default=None, max_length=11)

    @field_validator("to_name", "to_phone")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _require_token(self) -> QueryContactBirthdayArgs:
        if not self.to_name and not self.to_phone:
            raise ValueError("必须提供 to_name 或 to_phone 以定位联系人")
        return self


class LockBudgetFundsArgs(BaseModel):
    amount_cny: float = Field(gt=0, le=MAX_TRANSFER_CNY)
    name: str = Field(default="生日预算", min_length=1, max_length=60)
    deadline: str | None = Field(default=None, max_length=10)


class UnlockBudgetFundsArgs(BaseModel):
    goal_id: str = Field(min_length=3, max_length=64)


class GiftOrderArgs(BaseModel):
    goal_id: str = Field(min_length=3, max_length=64)
    birthday: str | None = Field(default=None, max_length=64)
    date: str | None = Field(default=None, max_length=64)
    note: str = Field(default="", max_length=120)


class ScheduleTransferArgs(BaseModel):
    to_account: str | None = Field(default=None, max_length=32)
    to_name: str | None = Field(default=None, max_length=32)
    amount_cny: float = Field(gt=0, le=MAX_TRANSFER_CNY)
    run_at: str = Field(min_length=4, max_length=40)
    recurrence: Literal["none", "monthly", "yearly"] = "none"
    note: str = Field(default="AegisBank 定时转账", max_length=120)
    from_account: str = Field(default=SELF_ACCOUNT, max_length=32)

    @field_validator("to_account", "from_account")
    @classmethod
    def _validate_account(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().upper()
        if not re.fullmatch(r"ACC-\d{3,}", stripped):
            raise ValueError("账户应形如 ACC-1001")
        return stripped

    @field_validator("to_name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _require_receiver(self) -> ScheduleTransferArgs:
        if not self.to_account and not self.to_name:
            raise ValueError("必须提供 to_account 或 to_name，以便确定收款账户")
        return self


class ListScheduledTasksArgs(BaseModel):
    status: str | None = Field(default=None, max_length=16)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        if cleaned not in _TASK_STATUSES:
            raise ValueError(f"任务状态只能是 {'/'.join(_TASK_STATUSES)}")
        return cleaned


class CancelScheduledTaskArgs(BaseModel):
    task_id: str = Field(min_length=3, max_length=64)


class RunDueTasksArgs(BaseModel):
    now: str | None = Field(default=None, max_length=40)


# ---------------------------------------------------------------------------
# 工具节点
# ---------------------------------------------------------------------------


class QueryContactBirthdayTool(BaseTool):
    metadata = ToolMetadata(
        name="query_contact_birthday",
        read_only=True,
        title="查询联系人生日",
        description="按姓名/别名/手机号读取联系人簿中的生日，并计算下一次生日与剩余天数，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="calendar:read",
        input_schema=QueryContactBirthdayArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = QueryContactBirthdayArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = QueryContactBirthdayArgs.model_validate(arguments)
        token = args.to_name or args.to_phone or ""
        contact, error = _resolve_contact(self.services.db, context.user_id, token)
        if error is not None or contact is None:
            raise ValueError(error or "未找到联系人")
        birthday_text = str(contact.get("birthday") or "").strip()
        if not birthday_text:
            raise ValueError(f"联系人 {contact.get('name')} 未登记生日，请先在联系人簿补充生日。")
        birthday = _parse_date(birthday_text)
        today = _today()
        next_birthday = _next_birthday(birthday, today)
        return ToolResult(
            tool_name=self.metadata.name,
            message=(
                f"已读取 {contact.get('name')} 的生日（演示数据）："
                f"下一次生日 {next_birthday.isoformat()}。"
            ),
            data={
                "contact": {
                    "contact_id": contact.get("contact_id"),
                    "name": contact.get("name"),
                    "relation": contact.get("relation"),
                },
                "birthday": birthday.isoformat(),
                "next_birthday": next_birthday.isoformat(),
                "days_until": (next_birthday - today).days,
                "simulated": SIMULATED,
            },
        )


class LockBudgetFundsTool(BaseTool):
    metadata = ToolMetadata(
        name="lock_budget_funds",
        title="锁定预算资金",
        description=(
            "从本人 ACC-1001 可用余额中划出指定金额并锁定到预算目标，"
            "资金仍留在账户余额中，属于黄色资金安排操作；由 unlock_budget_funds 补偿。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="automation:manage",
        compensable=True,
        compensation_tool="unlock_budget_funds",
        input_schema=LockBudgetFundsArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = LockBudgetFundsArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = LockBudgetFundsArgs.model_validate(arguments)
        amount_cents = to_cents(args.amount_cny)
        if amount_cents <= 0:
            raise ValueError("预算金额必须大于 0")
        deadline: str | None = None
        if args.deadline:
            deadline = _parse_date(args.deadline).isoformat()
        with self.services.db.transaction() as conn:
            account = conn.execute(
                "SELECT available_cents FROM bank_accounts WHERE user_id = ? AND account_id = ?",
                (context.user_id, SELF_ACCOUNT),
            ).fetchone()
            if account is None:
                raise ValueError(f"账户不存在：{SELF_ACCOUNT}")
            available_cents = int(account["available_cents"])
            if available_cents < amount_cents:
                raise ValueError(
                    f"{SELF_ACCOUNT} 可用余额不足：需要 {to_cny(amount_cents):.2f} 元，"
                    f"当前 {to_cny(available_cents):.2f} 元。"
                )
            goal_id = f"GOAL-{uuid4().hex[:8].upper()}"
            conn.execute(
                """
                INSERT INTO budget_goals
                (goal_id, user_id, name, target_cents, locked_cents, status,
                 deadline, created_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    goal_id,
                    context.user_id,
                    args.name,
                    amount_cents,
                    amount_cents,
                    deadline,
                    _iso_now(),
                ),
            )
            conn.execute(
                "UPDATE bank_accounts SET available_cents = available_cents - ? "
                "WHERE user_id = ? AND account_id = ?",
                (amount_cents, context.user_id, SELF_ACCOUNT),
            )
        return ToolResult(
            tool_name=self.metadata.name,
            message=(
                f"已锁定 {to_cny(amount_cents):.2f} 元预算资金（演示数据），目标编号 {goal_id}。"
            ),
            data={
                "goal_id": goal_id,
                "name": args.name,
                "target_cny": to_cny(amount_cents),
                "locked_cny": to_cny(amount_cents),
                "status": "active",
                "deadline": deadline,
                "account_id": SELF_ACCOUNT,
                "simulated": SIMULATED,
            },
        )


class UnlockBudgetFundsTool(BaseTool):
    metadata = ToolMetadata(
        name="unlock_budget_funds",
        title="解锁预算资金",
        description=(
            "补偿操作：把预算目标中尚未使用的锁定金额退回 ACC-1001 可用余额，"
            "并取消该目标下尚未执行的礼物订购任务。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="automation:manage",
        input_schema=UnlockBudgetFundsArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = UnlockBudgetFundsArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = UnlockBudgetFundsArgs.model_validate(arguments)
        with self.services.db.transaction() as conn:
            goal = conn.execute(
                "SELECT * FROM budget_goals WHERE goal_id = ? AND user_id = ?",
                (args.goal_id, context.user_id),
            ).fetchone()
            if goal is None:
                raise ValueError(f"预算目标不存在：{args.goal_id}")
            if str(goal["status"]) != "active":
                raise ValueError(
                    f"预算目标 {args.goal_id} 当前状态为 {goal['status']}，只有 active 可以解锁。"
                )
            released_cents = int(goal["locked_cents"])
            cancelled_task_ids: list[str] = []
            pending_tasks = conn.execute(
                "SELECT task_id, payload_json FROM scheduled_tasks "
                "WHERE user_id = ? AND kind = 'gift' AND status = 'pending'",
                (context.user_id,),
            ).fetchall()
            for task_row in pending_tasks:
                task_payload = json.loads(str(task_row["payload_json"] or "{}"))
                if str(task_payload.get("goal_id") or "") != args.goal_id:
                    continue
                conn.execute(
                    "UPDATE scheduled_tasks SET status = 'cancelled', last_result_json = ? "
                    "WHERE task_id = ? AND status = 'pending'",
                    (
                        json.dumps(
                            {"reason": "预算目标已解锁，礼物订购计划同步取消"},
                            ensure_ascii=False,
                        ),
                        str(task_row["task_id"]),
                    ),
                )
                cancelled_task_ids.append(str(task_row["task_id"]))
            conn.execute(
                "UPDATE gift_orders SET status = 'cancelled' "
                "WHERE goal_id = ? AND user_id = ? AND status = 'scheduled'",
                (args.goal_id, context.user_id),
            )
            conn.execute(
                "UPDATE budget_goals SET status = 'cancelled', locked_cents = 0 "
                "WHERE goal_id = ? AND user_id = ?",
                (args.goal_id, context.user_id),
            )
            if released_cents > 0:
                conn.execute(
                    "UPDATE bank_accounts SET available_cents = available_cents + ? "
                    "WHERE user_id = ? AND account_id = ?",
                    (released_cents, context.user_id, SELF_ACCOUNT),
                )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"已解锁并退回 {to_cny(released_cents):.2f} 元（演示数据）。",
            data={
                "goal_id": args.goal_id,
                "released_cny": to_cny(released_cents),
                "status": "cancelled",
                "cancelled_task_ids": cancelled_task_ids,
                "account_id": SELF_ACCOUNT,
                "simulated": SIMULATED,
            },
        )


class _GiftOrderTool(BaseTool):
    """Shared implementation for flower/cake order tools; subclasses set facts."""

    gift_kind: str = "flowers"
    gift_amount_cny: float = FLOWER_AMOUNT_CNY
    arguments_model = GiftOrderArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def _execute_gift(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = GiftOrderArgs.model_validate(arguments)
        goal: dict[str, Any] | None = None
        if args.goal_id:
            with self.services.db.transaction() as conn:
                row = conn.execute(
                    "SELECT * FROM budget_goals WHERE goal_id = ? AND user_id = ?",
                    (args.goal_id, context.user_id),
                ).fetchone()
            if row is None:
                raise ValueError(f"预算目标不存在：{args.goal_id}")
            goal = dict(row)
            if str(goal["status"]) != "active":
                raise ValueError(
                    f"预算目标 {args.goal_id} 当前状态为 {goal['status']}，只有 active 可以下单。"
                )
        birthday_text = args.birthday or args.date
        if birthday_text is None and goal is not None:
            birthday_text = goal.get("deadline")
        if not birthday_text:
            raise ValueError("缺少生日日期：请提供 birthday/date，或使用带 deadline 的预算目标。")
        birthday = _parse_date(str(birthday_text))
        due_at = birthday - timedelta(days=GIFT_LEAD_DAYS)
        amount_cents = to_cents(self.gift_amount_cny)
        order_id = f"GIFT-{uuid4().hex[:8].upper()}"
        payload = {
            "order_id": order_id,
            "gift_kind": self.gift_kind,
            "amount_cny": to_cny(amount_cents),
            "goal_id": args.goal_id,
            "birthday": birthday.isoformat(),
            "due_at": due_at.isoformat(),
            "tool_name": self.metadata.name,
            "note": args.note,
        }
        with self.services.db.transaction() as conn:
            reserved = conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM gift_orders "
                "WHERE goal_id = ? AND user_id = ? AND status = 'scheduled'",
                (args.goal_id, context.user_id),
            ).fetchone()[0]
            if goal is None or int(reserved) + amount_cents > int(goal["locked_cents"]):
                raise ValueError("礼物预约总额超过该目标剩余锁定预算，已拒绝。")
            conn.execute(
                """
                INSERT INTO gift_orders
                (order_id, user_id, goal_id, gift_kind, amount_cents, due_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'scheduled')
                """,
                (
                    order_id,
                    context.user_id,
                    args.goal_id,
                    self.gift_kind,
                    amount_cents,
                    due_at.isoformat(),
                ),
            )
            task_id = _insert_scheduled_task(
                conn,
                user_id=context.user_id,
                kind="gift",
                payload=payload,
                run_at=due_at.isoformat(),
            )
            _store_task_authorization(conn, task_id, payload, context)
        label = "鲜花" if self.gift_kind == "flowers" else "蛋糕"
        return ToolResult(
            tool_name=self.metadata.name,
            message=(
                f"已创建{label}订购计划（演示数据）：生日前 {GIFT_LEAD_DAYS} 天"
                f"（{due_at.isoformat()}）下单，{to_cny(amount_cents):.2f} 元。"
            ),
            data={
                "order_id": order_id,
                "task_id": task_id,
                "goal_id": args.goal_id,
                "gift_kind": self.gift_kind,
                "amount_cny": to_cny(amount_cents),
                "birthday": birthday.isoformat(),
                "due_at": due_at.isoformat(),
                "status": "scheduled",
                "simulated": SIMULATED,
            },
        )


class ScheduleFlowerOrderTool(_GiftOrderTool):
    gift_kind = "flowers"
    gift_amount_cny = FLOWER_AMOUNT_CNY
    metadata = ToolMetadata(
        name="schedule_flower_order",
        title="预约生日鲜花",
        description=(
            "创建一条生日鲜花订购计划（固定模拟金额 199 元），"
            "到期时间为生日前 2 天，由时间快进触发订购。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="automation:manage",
        compensable=True,
        compensation_tool="cancel_scheduled_task",
        input_schema=GiftOrderArgs.model_json_schema(),
        output_schema={},
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return self._execute_gift(arguments, context)


class ScheduleCakeOrderTool(_GiftOrderTool):
    gift_kind = "cake"
    gift_amount_cny = CAKE_AMOUNT_CNY
    metadata = ToolMetadata(
        name="schedule_cake_order",
        title="预约生日蛋糕",
        description=(
            "创建一条生日蛋糕订购计划（固定模拟金额 159 元），"
            "到期时间为生日前 2 天，由时间快进触发订购。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="automation:manage",
        compensable=True,
        compensation_tool="cancel_scheduled_task",
        input_schema=GiftOrderArgs.model_json_schema(),
        output_schema={},
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return self._execute_gift(arguments, context)


class ScheduleTransferTool(BaseTool):
    metadata = ToolMetadata(
        name="schedule_transfer",
        title="定时转账",
        description=(
            "创建一次性/每月/每年的定时转账任务；创建时不扣款，到期执行时复检权限后"
            "完成模拟转账。单笔超过 1000 元会升级为红色强验证，到期重新校验日累计。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="transfer:execute",
        compensable=True,
        compensation_tool="cancel_scheduled_task",
        input_schema=ScheduleTransferArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ScheduleTransferArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ScheduleTransferArgs.model_validate(arguments)
        run_at = _parse_iso_datetime(args.run_at)
        if run_at <= datetime.now(UTC):
            raise ValueError("定时转账执行时间必须晚于当前时间。")
        to_account = args.to_account
        to_name = args.to_name
        if to_account is None:
            contact, error = _resolve_contact(self.services.db, context.user_id, to_name or "")
            if error is not None or contact is None:
                raise ValueError(error or "未找到收款联系人")
            to_account = str(contact["account_id"])
            to_name = str(contact.get("name") or to_name)
        payload = {
            "from_account": args.from_account,
            "to_account": to_account,
            "to_name": to_name,
            "amount_cny": to_cny(to_cents(args.amount_cny)),
            "note": args.note,
            "tool_name": self.metadata.name,
            "label": f"定时转账给 {to_name or to_account}",
        }
        run_at_text = run_at.isoformat(timespec="seconds")
        with self.services.db.transaction() as conn:
            task_id = _insert_scheduled_task(
                conn,
                user_id=context.user_id,
                kind="transfer",
                payload=payload,
                run_at=run_at_text,
                recurrence=args.recurrence,
            )
            _store_task_authorization(conn, task_id, payload, context)
        return ToolResult(
            tool_name=self.metadata.name,
            message=(
                f"已创建定时转账任务 {task_id}（演示数据），将于 {run_at_text} 执行 "
                f"{payload['amount_cny']:.2f} 元。"
            ),
            data={
                "task_id": task_id,
                "kind": "transfer",
                "status": "pending",
                "run_at": run_at_text,
                "recurrence": args.recurrence,
                "amount_cny": payload["amount_cny"],
                "from_account": args.from_account,
                "to_account": to_account,
                "to_name": to_name,
                "simulated": SIMULATED,
            },
        )


class ListScheduledTasksTool(BaseTool):
    metadata = ToolMetadata(
        name="list_scheduled_tasks",
        read_only=True,
        title="查看定时任务",
        description="查看本人定时转账、预算目标和生日礼物订购任务，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="automation:read",
        input_schema=ListScheduledTasksArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ListScheduledTasksArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ListScheduledTasksArgs.model_validate(arguments)
        tasks = _task_rows(self.services.db, context.user_id, args.status)
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"已读取定时任务 {len(tasks)} 条（演示数据）。",
            data={"tasks": tasks, "count": len(tasks), "simulated": SIMULATED},
        )


class CancelScheduledTaskTool(BaseTool):
    metadata = ToolMetadata(
        name="cancel_scheduled_task",
        title="取消定时任务",
        description="取消尚未执行的 pending 定时任务；已执行/失败任务不可取消。",
        risk_level=RiskLevel.YELLOW,
        permission="automation:manage",
        input_schema=CancelScheduledTaskArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = CancelScheduledTaskArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = CancelScheduledTaskArgs.model_validate(arguments)
        with self.services.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_id = ? AND user_id = ?",
                (args.task_id, context.user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"定时任务不存在：{args.task_id}")
            if str(row["status"]) != "pending":
                raise ValueError(
                    f"定时任务 {args.task_id} 当前状态为 {row['status']}，只有 pending 可以取消。"
                )
            conn.execute(
                "UPDATE scheduled_tasks SET status = 'cancelled' "
                "WHERE task_id = ? AND user_id = ? AND status = 'pending'",
                (args.task_id, context.user_id),
            )
            payload = json.loads(row["payload_json"])
            if row["kind"] == "gift":
                conn.execute(
                    "UPDATE gift_orders SET status = 'cancelled' "
                    "WHERE order_id = ? AND user_id = ? AND status = 'scheduled'",
                    (payload["order_id"], context.user_id),
                )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"已取消定时任务 {args.task_id}（演示数据）。",
            data={
                "task_id": args.task_id,
                "kind": str(row["kind"]),
                "status": "cancelled",
                "run_at": str(row["run_at"]),
                "simulated": SIMULATED,
            },
        )


class ExecuteGiftArgs(BaseModel):
    task_id: str = Field(min_length=3, max_length=64)


class ExecuteGiftOrderTool(BaseTool):
    metadata = ToolMetadata(
        name="execute_gift_order",
        title="执行已授权礼物订单",
        description="内部到期消费节点。",
        risk_level=RiskLevel.YELLOW,
        permission="automation:manage",
        internal_only=True,
        allowed_purposes=("scheduled",),
        input_schema=ExecuteGiftArgs.model_json_schema(),
    )
    arguments_model = ExecuteGiftArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        if context.purpose != "scheduled":
            raise PermissionError("只允许受已确认任务授权约束的到期执行。")
        args = ExecuteGiftArgs.model_validate(arguments)
        with self.services.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_id = ? AND user_id = ? "
                "AND kind = 'gift' AND status = 'pending'",
                (args.task_id, context.user_id),
            ).fetchone()
        if row is None:
            raise ValueError("礼物到期任务不存在或已处理。")
        task = dict(row)
        payload = json.loads(task["payload_json"])
        data = _execute_gift_task(
            self.services, user_id=context.user_id, task=task, payload=payload
        )
        return ToolResult(self.metadata.name, "已完成受预算约束的模拟礼物消费。", data)


class RunDueTasksTool(BaseTool):
    metadata = ToolMetadata(
        name="run_due_tasks",
        title="执行到期任务",
        description=(
            "演示用“时间快进”：执行所有到期（run_at <= now）的定时转账与礼物订单，"
            "执行前经权限网关复检，逐任务写审计 scheduled_task_executed。"
        ),
        risk_level=RiskLevel.GREEN,
        permission="automation:manage",
        input_schema=RunDueTasksArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = RunDueTasksArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = RunDueTasksArgs.model_validate(arguments)
        data = run_due(self.services, now=args.now, user_id=context.user_id)
        return ToolResult(
            tool_name=self.metadata.name,
            message=(
                f"时间快进到 {data['now']}：执行 {data['executed_count']} 条，"
                f"失败 {data['failed_count']} 条，"
                f"待重新强验证 {data['pending_reauth_count']} 条（演示数据）。"
            ),
            data=data,
        )


# ---------------------------------------------------------------------------
# 到期执行引擎（同时供工具与后台线程使用）
# ---------------------------------------------------------------------------


def _claim_task(db: Database, task_id: str, now_iso: str) -> bool:
    """The surrounding execution transaction owns the task until commit."""
    with db.transaction() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM scheduled_tasks WHERE task_id = ? AND status = 'pending'", (task_id,)
            ).fetchone()
            is not None
        )


def _finish_task(
    db: Database,
    task_id: str,
    *,
    status: str,
    now_iso: str,
    result: dict[str, Any],
    next_run_at: str | None = None,
) -> None:
    with db.transaction() as conn:
        if next_run_at is None:
            conn.execute(
                "UPDATE scheduled_tasks SET status = ?, last_run_at = ?, "
                "last_result_json = ? WHERE task_id = ?",
                (
                    status,
                    now_iso,
                    json.dumps(result, ensure_ascii=False),
                    task_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE scheduled_tasks SET status = ?, run_at = ?, last_run_at = ?, "
                "last_result_json = ? WHERE task_id = ?",
                (
                    status,
                    next_run_at,
                    now_iso,
                    json.dumps(result, ensure_ascii=False),
                    task_id,
                ),
            )


def _assert_permission(
    services: CoreServices,
    *,
    user_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    instruction: str,
) -> None:
    tool = services.require_registry().get(tool_name)
    decision = services.require_gateway().evaluate(
        user_id=user_id,
        tool_name=tool_name,
        risk_level=tool.metadata.risk_level,
        permission=tool.metadata.permission,
        instruction=instruction,
        arguments=arguments,
    )
    if decision.denied:
        raise PermissionError(decision.reason)


def _audit_task(
    services: CoreServices,
    *,
    event: str,
    user_id: str,
    task: dict[str, Any],
    payload: dict[str, Any],
    result: dict[str, Any],
    risk_level: str,
) -> None:
    audit = services.require_audit()
    task_id = str(task["task_id"])
    audit.record(
        event=event,
        user_id=user_id,
        instruction=f"定时任务到期执行：{task_id}（{task['kind']}）",
        dag_path=f"{task_id}:{task['kind']}",
        tool_name=str(payload.get("tool_name") or "scheduled_task"),
        arguments=payload,
        result=result,
        confirmation_state="scheduled",
        risk_level=risk_level,
    )


def _task_risk_level(services: CoreServices, payload: dict[str, Any]) -> str:
    tool_name = payload.get("tool_name")
    if isinstance(tool_name, str):
        try:
            return services.require_registry().get(tool_name).metadata.risk_level.value
        except KeyError:
            pass
    return RiskLevel.YELLOW.value


def _execute_transfer_task(
    services: CoreServices,
    *,
    user_id: str,
    task: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    _assert_permission(
        services,
        user_id=user_id,
        tool_name="schedule_transfer",
        arguments=payload,
        instruction=f"定时转账到期执行 {task_id}",
    )
    transfer = _execute_scheduled_tool(
        services,
        task=task,
        payload=payload,
        user_id=user_id,
        tool_name="transfer",
        arguments={
            "from_account": str(payload.get("from_account") or SELF_ACCOUNT),
            "to_account": str(payload["to_account"]),
            "amount_cny": float(payload["amount_cny"]),
            "note": f"定时转账 {task_id}：{payload.get('note') or ''}"[:120],
        },
    )["data"]
    return {
        "task_id": task_id,
        "kind": "transfer",
        "status": "executed",
        "amount_cny": transfer["amount_cny"],
        "to_account": transfer["to_account"],
        "to_name": payload.get("to_name"),
        "transaction_id": transfer["transaction_id"],
        "executed_at": transfer["executed_at"],
        "simulated": SIMULATED,
    }


def _execute_gift_task(
    services: CoreServices,
    *,
    user_id: str,
    task: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    order_id = str(payload["order_id"])
    goal_id = payload.get("goal_id")
    tool_name = str(payload.get("tool_name") or "schedule_flower_order")
    _assert_permission(
        services,
        user_id=user_id,
        tool_name=tool_name,
        arguments=payload,
        instruction=f"生日礼物到期订购 {task_id}",
    )
    with services.db.transaction() as conn:
        order = conn.execute(
            "SELECT * FROM gift_orders WHERE order_id = ? AND user_id = ?",
            (order_id, user_id),
        ).fetchone()
        if order is None:
            raise ValueError(f"礼物订单不存在：{order_id}")
        order_status = str(order["status"])
        if order_status == "ordered":
            amount_cents = int(order["amount_cents"])
        elif order_status == "scheduled":
            amount_cents = int(order["amount_cents"])
            if not goal_id:
                raise ValueError("旧礼物任务缺少预算授权，请取消并重新创建。")
            goal = conn.execute(
                "SELECT locked_cents, status FROM budget_goals WHERE goal_id = ? AND user_id = ?",
                (goal_id, user_id),
            ).fetchone()
            if (
                goal is None
                or goal["status"] != "active"
                or int(goal["locked_cents"]) < amount_cents
            ):
                raise ValueError("礼物消费超过目标的剩余锁定预算。")
            account = conn.execute(
                "SELECT balance_cents FROM bank_accounts WHERE user_id = ? AND account_id = ?",
                (user_id, SELF_ACCOUNT),
            ).fetchone()
            if account is None:
                raise ValueError(f"账户不存在：{SELF_ACCOUNT}")
            if int(account["balance_cents"]) < amount_cents:
                raise ValueError(
                    f"账户余额不足：礼物 {to_cny(amount_cents):.2f} 元，"
                    f"当前余额 {to_cny(int(account['balance_cents'])):.2f} 元。"
                )
            deducted = conn.execute(
                "UPDATE bank_accounts SET balance_cents = balance_cents - ? "
                "WHERE user_id = ? AND account_id = ? AND balance_cents - available_cents >= ?",
                (amount_cents, user_id, SELF_ACCOUNT, amount_cents),
            ).rowcount
            if deducted != 1:
                raise ValueError("锁定资金与账户余额不一致，拒绝礼物扣款。")
            conn.execute(
                "INSERT INTO bank_transactions "
                "(transaction_id,user_id,account_id,card_id,merchant,category,"
                "amount_cents,occurred_at,status,note) VALUES (?,?,?,NULL,?,'gift',?,?,'posted',?)",
                (
                    f"TX-{order_id}",
                    user_id,
                    SELF_ACCOUNT,
                    str(payload.get("gift_kind") or "gift"),
                    -amount_cents,
                    _iso_now(),
                    f"模拟礼物订单 {order_id}",
                ),
            )
            conn.execute(
                "UPDATE gift_orders SET status = 'ordered' "
                "WHERE order_id = ? AND status = 'scheduled'",
                (order_id,),
            )
            if goal_id:
                conn.execute(
                    "UPDATE budget_goals SET locked_cents = MAX(locked_cents - ?, 0), "
                    "status = CASE WHEN locked_cents - ? <= 0 THEN 'completed' "
                    "ELSE status END WHERE goal_id = ? AND user_id = ?",
                    (amount_cents, amount_cents, goal_id, user_id),
                )
        else:
            raise ValueError(f"礼物订单 {order_id} 状态为 {order_status}，无法订购。")
    return {
        "task_id": task_id,
        "kind": "gift",
        "status": "executed",
        "gift_kind": str(payload.get("gift_kind") or "flowers"),
        "order_id": order_id,
        "goal_id": goal_id,
        "amount_cny": to_cny(amount_cents),
        "simulated": SIMULATED,
    }


def _execute_scheduled_tool(
    services: CoreServices,
    *,
    task: dict[str, Any],
    payload: dict[str, Any],
    user_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    with services.db.transaction() as conn:
        mandate = conn.execute(
            "SELECT * FROM scheduled_authorizations WHERE task_id = ? AND user_id = ?",
            (task["task_id"], user_id),
        ).fetchone()
    if mandate is None or mandate["payload_hash"] != canonical_hash(payload):
        raise PermissionError("任务缺少匹配的确认授权，拒绝执行；旧任务请取消后重新创建。")
    source = services.db.get_pending(mandate["source_action_id"])
    if source is None or source["user_id"] != user_id or source["state"] != "COMPLETED":
        raise PermissionError("来源计划未完成或已撤销，拒绝执行定时任务。")
    tool = services.require_registry().get(tool_name)
    arguments = tool.validate_arguments(arguments)
    assessment = services.scheduler.risk_engine.assess(
        user_id=user_id,
        tool_name=tool_name,
        arguments=arguments,
        base_risk=tool.metadata.risk_level,
        instruction=f"到期任务 {task['task_id']}",
    )
    decision = services.require_gateway().evaluate(
        user_id=user_id,
        tool_name=tool_name,
        risk_level=assessment.level,
        permission=tool.metadata.permission,
        instruction=f"到期任务 {task['task_id']}",
        arguments=arguments,
        role="user",
        purpose="scheduled",
    )
    if decision.denied:
        raise PermissionError("定时任务执行前的权限复检未通过。")
    if assessment.level is RiskLevel.RED and mandate["risk_level"] != "red":
        risk_reasons = "；".join(assessment.reasons) or "到期动态风险复检升级为红色"
        raise ScheduledTaskNeedsReauth(
            "到期风险由 "
            f"{mandate['risk_level']} 升为 red（{risk_reasons}）。"
            "为防止重复扣款，任务保持 pending 且本次未执行；请取消该任务后"
            "按红色风险重新创建并完成 OTP 强验证，再执行时间快进。",
            required_risk=RiskLevel.RED.value,
            original_risk=str(mandate["risk_level"]),
        )
    if decision.requires_reauth and not mandate["mfa_verified"]:
        raise ScheduledTaskNeedsReauth(
            "到期执行需要强验证，但原任务没有可用的 MFA 授权；任务保持 pending，未执行。",
            required_risk=assessment.level.value,
            original_risk=str(mandate["risk_level"]),
        )
    context = ExecutionContext(
        user_id=user_id,
        instruction=f"执行已确认定时任务 {task['task_id']}",
        run_id=mandate["source_action_id"],
        dag_path=f"scheduled:{task['task_id']}:{tool_name}",
        approved_risk=RiskLevel(mandate["risk_level"]),
        reauth_verified=bool(mandate["mfa_verified"]),
        purpose="scheduled",
    )

    def persist(result):
        services.require_audit().record(
            event="scheduled_tool_executed",
            run_id=context.run_id,
            step_id=task["task_id"],
            user_id=user_id,
            instruction=context.instruction,
            dag_path=context.dag_path,
            tool_name=tool_name,
            arguments=arguments,
            result={"task_id": task["task_id"], "risk": assessment.as_dict(), "result": result},
            confirmation_state="scheduled_authorization",
            risk_level=assessment.level.value,
        )

    return services.scheduler.executor.execute(tool, arguments, context, on_success=persist)


def _next_occurrence(run_at: datetime, recurrence: str, now: datetime) -> datetime | None:
    if recurrence == "monthly":
        next_run = run_at
        for _ in range(240):
            year = next_run.year
            month = next_run.month + 1
            if month > 12:
                year, month = year + 1, 1
            last = calendar.monthrange(year, month)[1]
            next_run = next_run.replace(year=year, month=month, day=min(run_at.day, last))
            if next_run > now:
                return next_run
        return None
    if recurrence == "yearly":
        next_run = run_at
        for _ in range(240):
            year = next_run.year + 1
            day = min(next_run.day, calendar.monthrange(year, next_run.month)[1])
            next_run = next_run.replace(year=year, day=day)
            if next_run > now:
                return next_run
        return None
    return None


def _execute_one_task(
    services: CoreServices,
    *,
    user_id: str,
    task: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    payload = json.loads(str(task["payload_json"] or "{}"))
    kind = str(task["kind"])
    now_iso = now.isoformat(timespec="seconds")
    risk_level = _task_risk_level(services, payload)
    try:
        if kind == "transfer":
            result = _execute_transfer_task(services, user_id=user_id, task=task, payload=payload)
        elif kind == "gift":
            result = _execute_scheduled_tool(
                services,
                task=task,
                payload=payload,
                user_id=user_id,
                tool_name="execute_gift_order",
                arguments={"task_id": task_id},
            )["data"]
        else:
            raise ValueError(f"未知的定时任务类型：{kind}")
    except ScheduledTaskNeedsReauth as exc:
        reason = str(exc) or "到期任务需要重新完成强验证。"
        needs_reauth = {
            "task_id": task_id,
            "kind": kind,
            "status": "pending",
            "execution_status": "needs_reauth",
            "reason": reason,
            "action_required": (
                "取消该定时任务后按红色风险重新创建并完成 OTP 强验证，"
                "再执行时间快进；原任务不会扣款或自动重放。"
            ),
            "reauth_required": True,
            "required_risk": exc.required_risk,
            "previous_risk": exc.original_risk,
            "trigger_source": "scheduled",
            "amount_cny": payload.get("amount_cny"),
            "simulated": SIMULATED,
        }
        _finish_task(
            services.db,
            task_id,
            status="pending",
            now_iso=now_iso,
            result=needs_reauth,
        )
        _audit_task(
            services,
            event="scheduled_task_needs_reauth",
            user_id=user_id,
            task=task,
            payload=payload,
            result=needs_reauth,
            risk_level=exc.required_risk,
        )
        return {"ok": True, "needs_reauth": True, **needs_reauth}
    except Exception as exc:  # noqa: BLE001 - failures are audited, never retried
        reason = str(exc) or type(exc).__name__
        failure = {
            "task_id": task_id,
            "kind": kind,
            "status": "failed",
            "reason": reason,
            "trigger_source": "scheduled",
            "amount_cny": payload.get("amount_cny"),
            "simulated": SIMULATED,
        }
        _finish_task(
            services.db,
            task_id,
            status="failed",
            now_iso=now_iso,
            result=failure,
        )
        _audit_task(
            services,
            event="scheduled_task_failed",
            user_id=user_id,
            task=task,
            payload=payload,
            result=failure,
            risk_level=risk_level,
        )
        return {"ok": False, **failure}

    success = {
        **result,
        "trigger_source": "scheduled",
    }
    recurrence = str(task.get("recurrence") or "none")
    next_run = _next_occurrence(_parse_iso_datetime(str(task["run_at"])), recurrence, now)
    if kind == "transfer" and next_run is not None:
        _finish_task(
            services.db,
            task_id,
            status="pending",
            now_iso=now_iso,
            result=success,
            next_run_at=next_run.isoformat(timespec="seconds"),
        )
    else:
        _finish_task(
            services.db,
            task_id,
            status="done",
            now_iso=now_iso,
            result=success,
        )
    _audit_task(
        services,
        event="scheduled_task_executed",
        user_id=user_id,
        task=task,
        payload=payload,
        result=success,
        risk_level=risk_level,
    )
    return {"ok": True, **success}


def _execute_due_tasks(services: CoreServices, user_id: str, now: datetime) -> dict[str, Any]:
    with services.db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE user_id = ? AND status = 'pending' "
            "ORDER BY run_at ASC, task_id ASC",
            (user_id,),
        ).fetchall()
    due = [dict(row) for row in rows if _parse_iso_datetime(str(row["run_at"])) <= now][:20]
    executed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    pending_reauth: list[dict[str, Any]] = []
    now_iso = now.isoformat(timespec="seconds")
    for task in due:
        if not _claim_task(services.db, str(task["task_id"]), now_iso):
            continue
        outcome = _execute_one_task(services, user_id=user_id, task=task, now=now)
        if outcome.pop("ok"):
            if outcome.pop("needs_reauth", False):
                pending_reauth.append(outcome)
            else:
                executed.append(outcome)
        else:
            failed.append(outcome)
    return {
        "now": now_iso,
        "executed": executed,
        "failed": failed,
        "pending_reauth": pending_reauth,
        "executed_count": len(executed),
        "failed_count": len(failed),
        "pending_reauth_count": len(pending_reauth),
        "action_required": bool(pending_reauth),
        "simulated": SIMULATED,
    }


def run_due(
    services: CoreServices,
    now: datetime | str | None = None,
    user_id: str = DEFAULT_USER,
) -> dict[str, Any]:
    """Execute all due tasks for a user (shared by the tool and the background thread)."""
    readiness = services.extras.get("readiness")
    if readiness is not None:
        readiness.require_ready()
    if services.scheduler.breaker.is_open(user_id=user_id):
        raise PermissionError("熔断已打开，定时写任务暂停执行。")
    if not services.db.in_transaction:
        response = services.scheduler.run(
            user_id=user_id,
            instruction="执行本人已确认的到期任务",
            tool_name="run_due_tasks",
            arguments={"now": now.isoformat() if isinstance(now, datetime) else now} if now else {},
        )
        if response.get("status") != "completed":
            raise PermissionError(response.get("reason") or "到期任务未通过统一执行链。")
        return response["results"][0]["data"]
    if now is None:
        now_dt = datetime.now(UTC)
    elif isinstance(now, str):
        now_dt = _parse_iso_datetime(now)
    else:
        now_dt = now.astimezone(UTC)
    return _execute_due_tasks(services, user_id, now_dt)


# ---------------------------------------------------------------------------
# 风险规则：只保持或升级工具基线
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScheduleTransferRisk:
    name: str = "automation.schedule_transfer"
    priority: int = 20

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "schedule_transfer":
            return None
        amount = float(ctx.arguments.get("amount_cny") or 0)
        if amount > 1000:
            return RiskGuess(
                level=RiskLevel.RED,
                score=85,
                reasons=[
                    f"定时转账单笔 {amount:.2f} 元超过 1000 元强验证阈值。",
                    "大额资金将在未来自动转出，需要红色强验证和明确确认。",
                ],
            )
        return RiskGuess(
            level=RiskLevel.YELLOW,
            score=45,
            reasons=[
                f"定时转账 {amount:.2f} 元将在未来自动执行，需要黄色确认。",
                "创建任务不扣款；到期执行时会再次复检权限。",
            ],
        )


@dataclass(frozen=True, slots=True)
class LockBudgetFundsRisk:
    name: str = "automation.lock_budget_funds"
    priority: int = 20

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "lock_budget_funds":
            return None
        amount = float(ctx.arguments.get("amount_cny") or 0)
        return RiskGuess(
            level=RiskLevel.YELLOW,
            score=45,
            reasons=[
                f"将在 ACC-1001 可用余额中锁定 {amount:.2f} 元预算资金。",
                "锁定不改变账户余额，可通过 unlock_budget_funds 补偿退回。",
            ],
        )


@dataclass(frozen=True, slots=True)
class GiftOrderRisk:
    name: str = "automation.gift_order"
    priority: int = 20

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name not in {"schedule_flower_order", "schedule_cake_order"}:
            return None
        label = "鲜花" if ctx.tool_name == "schedule_flower_order" else "蛋糕"
        return RiskGuess(
            level=RiskLevel.YELLOW,
            score=40,
            reasons=[
                f"将在生日前 2 天自动订购{label}（固定模拟金额，演示数据）。",
                "交付前需要用户确认购买计划。",
            ],
        )


@dataclass(frozen=True, slots=True)
class CancelScheduledTaskRisk:
    name: str = "automation.cancel_scheduled_task"
    priority: int = 30

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "cancel_scheduled_task":
            return None
        return RiskGuess(
            level=RiskLevel.GREEN,
            score=10,
            reasons=["取消尚未执行的定时任务，不产生资金变动。"],
        )


@dataclass(frozen=True, slots=True)
class UnlockBudgetFundsRisk:
    name: str = "automation.unlock_budget_funds"
    priority: int = 30

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "unlock_budget_funds":
            return None
        return RiskGuess(
            level=RiskLevel.GREEN,
            score=10,
            reasons=["解锁预算资金是退回锁定金额的补偿操作，不产生额外扣款。"],
        )


# ---------------------------------------------------------------------------
# Planner 意图
# ---------------------------------------------------------------------------


def _clarification(message: str, intent: str) -> ExecutionPlan:
    return ExecutionPlan(
        intent=intent,
        planner="rule",
        confidence=0.2,
        needs_clarification=True,
        clarification=message,
    )


class BirthdayPlanIntent:
    """生日跨场景联动：查生日 → 锁预算 → 预约鲜花/蛋糕（4 步 DAG）。"""

    name = "automation.birthday_plan"
    priority: int = 10

    _REQUIRED_TOOLS = (
        "query_contact_birthday",
        "lock_budget_funds",
        "schedule_flower_order",
        "schedule_cake_order",
    )

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        instruction = ctx.instruction
        if "生日" not in instruction:
            return None
        if not all(ctx.has_tool(name) for name in self._REQUIRED_TOOLS):
            return None
        if ctx.repository is None:
            return None
        contact, error = _mentioned_contact(ctx.repository.db, ctx.request.user_id, instruction)
        if error is not None or contact is None:
            return _clarification(error or "未找到生日对象", "birthday_plan")
        budget = _budget_amount_from(instruction)
        if budget is None or budget <= 0:
            return _clarification(
                "请补充生日预算，例如：帮我准备妈妈的生日，预算 1000 元。",
                "birthday_plan",
            )
        if budget < FLOWER_AMOUNT_CNY + CAKE_AMOUNT_CNY:
            return _clarification(
                "当前鲜花与蛋糕总价 358 元，超过所给预算；请提高预算或分别安排。", "birthday_plan"
            )
        if budget > MAX_TRANSFER_CNY:
            return _clarification(
                f"生日预算不能超过 {MAX_TRANSFER_CNY:.0f} 元，请调整金额。",
                "birthday_plan",
            )
        name = str(contact.get("name"))
        birthday = str(contact.get("birthday") or "").strip()
        assumptions = [
            f"联系人簿识别生日对象：{name}（生日 {birthday or '未登记'}）。",
            f"生日预算 {budget:.2f} 元将在确认后从 ACC-1001 可用余额锁定。",
            "鲜花（199 元）与蛋糕（159 元）在生日前 2 天下单，可用“时间快进”立即触发。",
        ]
        return ExecutionPlan(
            intent="birthday_plan",
            planner="rule",
            confidence=0.9,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="query_contact_birthday",
                    arguments={"to_name": name},
                    description=f"读取联系人 {name} 的生日并计算下一次生日。",
                ),
                PlanStep(
                    id="step-2",
                    tool_name="lock_budget_funds",
                    arguments={
                        "amount_cny": budget,
                        "name": f"{name}的生日预算",
                    },
                    depends_on=["step-1"],
                    description=f"从 ACC-1001 锁定 {budget:.2f} 元作为生日预算。",
                ),
                PlanStep(
                    id="step-3",
                    tool_name="schedule_flower_order",
                    arguments={
                        "goal_id": "${steps.step-2.data.goal_id}",
                        "birthday": "${steps.step-1.data.next_birthday}",
                        "note": f"{name}的生日鲜花",
                    },
                    depends_on=["step-1", "step-2"],
                    description="预约生日前 2 天配送鲜花（固定模拟金额 199 元）。",
                ),
                PlanStep(
                    id="step-4",
                    tool_name="schedule_cake_order",
                    arguments={
                        "goal_id": "${steps.step-2.data.goal_id}",
                        "birthday": "${steps.step-1.data.next_birthday}",
                        "note": f"{name}的生日蛋糕",
                    },
                    depends_on=["step-1", "step-2"],
                    description="预约生日前 2 天配送蛋糕（固定模拟金额 159 元）。",
                ),
            ],
        )


class ScheduledTransferIntent:
    """定时转账：“明天/下周三/每月 5 号给张三转 500” → schedule_transfer。"""

    name = "automation.scheduled_transfer"
    priority: int = 20

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        instruction = ctx.instruction
        if "生日" in instruction:
            return None
        if not any(hint in instruction for hint in _SCHEDULE_HINTS):
            return None
        if not ctx.has_tool("schedule_transfer") or ctx.repository is None:
            return None
        if not any(word in instruction for word in _TRANSFER_VERBS):
            return None
        now = datetime.now(UTC)
        try:
            run_at, recurrence = _resolve_run_at(instruction, now)
        except ValueError as exc:
            return _clarification(str(exc), "scheduled_transfer")
        amount = _transfer_amount_from(instruction)
        if amount is None or amount <= 0:
            return _clarification(
                "请补充定时转账金额，例如：明天给张三转 500 元。",
                "scheduled_transfer",
            )
        if amount > MAX_TRANSFER_CNY:
            return _clarification(
                f"单笔定时转账不能超过 {MAX_TRANSFER_CNY:.0f} 元，请调整金额。",
                "scheduled_transfer",
            )
        to_name: str | None = None
        to_account: str | None = None
        account_match = _ACCOUNT_PATTERN.search(instruction)
        if account_match is not None:
            to_account = account_match.group(0).upper()
        else:
            phone_match = _PHONE_IN_TEXT_PATTERN.search(instruction)
            token: str | None = phone_match.group(1) if phone_match else None
            if token is None:
                name_match = _NAME_TRANSFER_PATTERN.search(instruction)
                if name_match is None:
                    return _clarification(
                        "请补充收款人（联系人姓名/别名/手机号或 ACC 账户），我不会猜测收款人。",
                        "scheduled_transfer",
                    )
                token = name_match.group(1).strip()
            contact, error = _resolve_contact(ctx.repository.db, ctx.request.user_id, token)
            if error is not None or contact is None:
                return _clarification(error or "未找到收款人", "scheduled_transfer")
            to_name = str(contact.get("name"))
            to_account = str(contact.get("account_id"))
        run_at_text = run_at.isoformat(timespec="seconds")
        assumptions = [
            f"定时转账将在 {run_at_text} 执行，创建任务本身不扣款。",
            "到期执行时重新调用权限网关复检，并用“时间快进”立即触发。",
        ]
        if recurrence != "none":
            assumptions.append(f"该任务按 {recurrence} 周期重复执行。")
        label = to_name or to_account
        return ExecutionPlan(
            intent="scheduled_transfer",
            planner="rule",
            confidence=0.9,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="schedule_transfer",
                    arguments={
                        "to_name": to_name,
                        "to_account": to_account,
                        "amount_cny": amount,
                        "run_at": run_at_text,
                        "recurrence": recurrence,
                        "note": instruction[:120],
                    },
                    description=f"创建定时转账：{run_at_text} 向 {label} 转 {amount:.2f} 元。",
                )
            ],
        )


class CancelScheduledTaskIntent:
    """取消定时任务：需要明确任务编号，不猜测取消对象。"""

    name = "automation.cancel_task"
    priority: int = 30

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        instruction = ctx.instruction
        if "取消" not in instruction:
            return None
        if "定时任务" not in instruction and "定时转账" not in instruction:
            return None
        if not ctx.has_tool("cancel_scheduled_task"):
            return None
        match = _TASK_ID_PATTERN.search(instruction.upper())
        if match is None:
            return _clarification(
                "请提供要取消的定时任务编号（例如 TASK-1A2B3C4D），"
                "可先说“查看我的定时任务”获取编号。",
                "cancel_scheduled_task",
            )
        return ExecutionPlan(
            intent="cancel_scheduled_task",
            planner="rule",
            confidence=0.9,
            assumptions=[],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="cancel_scheduled_task",
                    arguments={"task_id": match.group(0)},
                    description=f"取消定时任务 {match.group(0)}。",
                )
            ],
        )


class RunDueTasksIntent:
    """演示用“时间快进”：立即执行到期的定时任务。"""

    name = "automation.run_due"
    priority: int = 30

    _TRIGGER_WORDS = (
        "时间快进",
        "快进时间",
        "执行到期",
        "到期任务",
        "运行到期",
        "立即执行定时",
    )

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        instruction = ctx.instruction
        if not any(word in instruction for word in self._TRIGGER_WORDS):
            return None
        if not ctx.has_tool("run_due_tasks"):
            return None
        arguments: dict[str, Any] = {}
        iso_match = re.search(
            r"(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)",
            instruction,
        )
        if iso_match is not None:
            arguments["now"] = iso_match.group(1)
        return ExecutionPlan(
            intent="run_due_tasks",
            planner="rule",
            confidence=0.95,
            assumptions=["时间快进仅用于本地演示，会对到期的定时任务真实执行模拟转账。"],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="run_due_tasks",
                    arguments=arguments,
                    description="执行所有已到期的定时转账与礼物订购任务。",
                )
            ],
        )


class TaskQueryIntent:
    """查看定时任务/计划。"""

    name: str = "automation.task_query"
    priority: int = 30

    _QUERY_WORDS = ("查看", "列出", "看看", "看一下", "有哪些", "列表", "显示", "我的")

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        instruction = ctx.instruction
        if "取消" in instruction:
            return None
        if not any(
            word in instruction for word in ("定时任务", "定时转账", "定时计划", "自动化任务")
        ):
            return None
        if not any(word in instruction for word in self._QUERY_WORDS):
            return None
        if not ctx.has_tool("list_scheduled_tasks"):
            return None
        return ExecutionPlan(
            intent="list_scheduled_tasks",
            planner="rule",
            confidence=0.92,
            assumptions=[],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="list_scheduled_tasks",
                    arguments={},
                    description="读取本人定时任务列表。",
                )
            ],
        )


# ---------------------------------------------------------------------------
# 场景契约工厂
# ---------------------------------------------------------------------------


def tools(services: CoreServices) -> list[BaseTool]:
    services.compensation.register(
        CompensationSpec(
            "execute_gift_order",
            "",
            "已完成礼物订单不可自动退回，需人工核实。",
            irreversible=True,
        )
    )
    return [
        QueryContactBirthdayTool(services),
        LockBudgetFundsTool(services),
        UnlockBudgetFundsTool(services),
        ScheduleFlowerOrderTool(services),
        ScheduleCakeOrderTool(services),
        ScheduleTransferTool(services),
        ListScheduledTasksTool(services),
        CancelScheduledTaskTool(services),
        RunDueTasksTool(services),
        ExecuteGiftOrderTool(services),
    ]


def risk_rules() -> list[Any]:
    return [
        ScheduleTransferRisk(),
        LockBudgetFundsRisk(),
        GiftOrderRisk(),
        CancelScheduledTaskRisk(),
        UnlockBudgetFundsRisk(),
    ]


def intents() -> list[Any]:
    # 顺序即优先级：生日 DAG 最高，定时转账次之，任务查询/取消/快进最后兜底。
    return [
        BirthdayPlanIntent(),
        ScheduledTransferIntent(),
        CancelScheduledTaskIntent(),
        RunDueTasksIntent(),
        TaskQueryIntent(),
    ]


class RunDueRequest(BaseModel):
    now: str | None = Field(default=None, max_length=40)


def router(services: CoreServices) -> APIRouter:
    api = APIRouter(prefix="/api/automation", tags=["automation"])

    @api.get("/schedules")
    def list_schedules(
        user_id: str = Query(default=DEFAULT_USER, max_length=64),
        status: str | None = Query(default=None, max_length=16),
    ) -> dict[str, Any]:
        tasks = _task_rows(services.db, user_id, status)
        return {"tasks": tasks, "count": len(tasks), "simulated": SIMULATED}

    @api.get("/goals")
    def list_goals(
        user_id: str = Query(default=DEFAULT_USER, max_length=64),
    ) -> dict[str, Any]:
        with services.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM budget_goals WHERE user_id = ? "
                "ORDER BY created_at DESC, goal_id DESC",
                (user_id,),
            ).fetchall()
        goals = [_goal_row_to_dict(row) for row in rows]
        return {"goals": goals, "count": len(goals), "simulated": SIMULATED}

    @api.get("/orders")
    def list_orders(
        user_id: str = Query(default=DEFAULT_USER, max_length=64),
    ) -> dict[str, Any]:
        with services.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM gift_orders WHERE user_id = ? ORDER BY due_at ASC, order_id ASC",
                (user_id,),
            ).fetchall()
        orders = [_order_row_to_dict(row) for row in rows]
        return {"orders": orders, "count": len(orders), "simulated": SIMULATED}

    @api.post("/run-due")
    def trigger_run_due(
        request: Request,
        now: str | None = Query(default=None, max_length=40),
        body: RunDueRequest | None = None,
    ) -> dict[str, Any]:
        readiness = getattr(request.app.state, "readiness", None)
        if readiness is not None:
            try:
                readiness.require_ready()
            except NotReadyError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        effective_now = (body.now if body is not None else None) or now
        arguments: dict[str, Any] = {"now": effective_now} if effective_now else {}
        scheduler = services.scheduler
        if scheduler is None:
            raise HTTPException(status_code=503, detail="调度器尚未初始化。")
        try:
            result = scheduler.run(
                user_id=DEFAULT_USER,
                instruction="时间快进：执行到期的定时任务",
                tool_name="run_due_tasks",
                arguments=arguments,
                role=services.authz.normalize(
                    request.headers.get("X-Aegis-Role"),
                    default=services.settings.authz_default_role,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        data: dict[str, Any] = {}
        if result.get("status") == "completed":
            results = result.get("results") or []
            if results:
                data = results[-1].get("data") or {}
        return {
            "status": result.get("status"),
            "risk_level": result.get("risk_level"),
            "reason": result.get("reason"),
            "now": data.get("now"),
            "executed": data.get("executed", []),
            "failed": data.get("failed", []),
            "pending_reauth": data.get("pending_reauth", []),
            "executed_count": data.get("executed_count", 0),
            "failed_count": data.get("failed_count", 0),
            "pending_reauth_count": data.get("pending_reauth_count", 0),
            "action_required": data.get("action_required", False),
            "simulated": SIMULATED,
        }

    return api


# ---------------------------------------------------------------------------
# 后台调度线程（仅当 settings.automation_enabled=True）
# ---------------------------------------------------------------------------

_background_thread: threading.Thread | None = None
_background_stop = threading.Event()


def start_background(services: CoreServices) -> None:
    """Start the optional polling scheduler; tests keep automation disabled."""
    global _background_thread
    if not services.settings.automation_enabled:
        return
    if _background_thread is not None and _background_thread.is_alive():
        return
    _background_stop.clear()
    interval = max(1, int(services.settings.automation_interval_seconds))

    def _loop() -> None:
        while not _background_stop.wait(interval):
            try:
                run_due(services)
            except Exception:  # noqa: BLE001 - a background loop must survive
                continue

    _background_thread = threading.Thread(target=_loop, name="aegisbank-automation", daemon=True)
    _background_thread.start()


def stop_background() -> None:
    """Signal the polling thread and wait briefly for it to exit."""
    global _background_thread
    _background_stop.set()
    thread = _background_thread
    _background_thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)


def semantic_intents():
    from ..planning.semantic_catalog import CURRENCY, DATE, ENTITY, MONEY, SemanticSpec

    return [
        SemanticSpec(
            "scheduled_transfer",
            (
                rf"(?P<date>{DATE})(?:给|向)(?P<contact>(?!\s*ACC-){ENTITY})(?:汇|打|转)(?P<amount>{MONEY}){CURRENCY}",
            ),
            "定时{date}给{contact}转{amount}元",
            {"date": "date", "contact": "contact_account", "amount": "money"},
            tools=("schedule_transfer",),
            bindings={"date": (0, "run_at"), "contact": (0, "to_account"),
                      "amount": (0, "amount_cny")},
        ),
        SemanticSpec(
            "birthday",
            (
                rf"(?:帮|给|为)(?P<contact>(?!\s*ACC-){ENTITY})(?:筹备|安排|准备)生日(?:礼物)?[，,]?预算\s*(?P<amount>{MONEY}){CURRENCY}",
                rf"(?P<contact>{ENTITY})(?:快过|快要过|过)?生日(?:了)?[，,]?(?:帮我)?(?:用|拿)(?P<amount>{MONEY}){CURRENCY}(?:准备|安排)鲜花(?:和|与)蛋糕",
                rf"(?:查下|查查|查询)(?P<contact>{ENTITY})的生日(?:是哪天)?[，,](?:先)?(?:锁定|锁住)(?P<amount>{MONEY}){CURRENCY}预算[，,](?:再安排|把)鲜花(?:和|与)蛋糕(?:订好)?",
            ),
            "帮我准备{contact}的生日，预算{amount}元",
            {"contact": "contact_name", "amount": "money"},
            tools=(
                "query_contact_birthday",
                "lock_budget_funds",
                "schedule_flower_order",
                "schedule_cake_order",
            ),
            bindings={"contact": (0, "to_name"), "amount": (1, "amount_cny")},
        ),
    ]
