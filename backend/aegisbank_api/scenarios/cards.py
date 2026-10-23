"""Cards scenario: virtual card application, issuance, password reset and unlock.

Contract: ``backend/aegisbank_api/scenarios/README.md``. The module owns its
SQLite schema, demo seed, tool nodes, planner intents, risk rules and read-only
routes. Every fact comes from SQLite. No plaintext card password is ever
received, stored or audited -- only a ``password_changed_at`` timestamp.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..banking.repository import to_cents, to_cny
from ..db import Database
from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..planning.contracts import ExecutionPlan, PlanStep
from ..planning.intents import IntentContext, IntentRule
from ..registry import BaseTool
from ..risk_rules import RiskContext, RiskGuess, RiskRule
from ..services import CoreServices

NAME = "cards"
SIMULATED = True

DEMO_USER = "demo-user"
DEFAULT_REQUESTED_LIMIT_CNY = 3000.0
MAX_REQUESTED_LIMIT_CNY = 20_000.0
DEFAULT_TRANSACTION_LIMIT_CNY = 10_000.0
HIGH_LIMIT_THRESHOLD_CNY = 5_000.0
DEFAULT_REPAYMENT_DAY = 8
SEEDED_APPLICATION_ID = "APP-8001"
APPLICATION_NUMBER_START = 9001
VIRTUAL_CARD_NUMBER_START = 9001
VIRTUAL_CARD_NUMBER_END = 9999

PLACEHOLDER_PATTERN = r"^\$\{steps\.[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+\}$"
_APPLICATION_ID_PATTERN = re.compile(r"^APP-\d{3,}$")
_APPLY_CARD_PATTERN = re.compile(r"(申请|办理|办)\s*(?:一张|张)?\s*(?:虚拟卡|信用卡)")
_PASSWORD_PATTERN = re.compile(
    r"(?:修改|重置|变更|更改)[^，。；,;]{0,8}密码|密码[^，。；,;]{0,6}(?:修改|重置|变更|更改)"
)
_UNLOCK_LIMIT_PATTERN = re.compile(
    r"(?:解锁|解除|恢复)[^，。；,;]{0,8}限额|限额[^，。；,;]{0,6}(?:解锁|解除|恢复)"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS card_applications (
    application_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('virtual', 'physical')),
    status TEXT NOT NULL CHECK (status IN ('applying', 'approved', 'issued', 'rejected')),
    requested_limit_cents INTEGER NOT NULL,
    card_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_card_applications_user
    ON card_applications(user_id, created_at);

CREATE TABLE IF NOT EXISTS card_secrets (
    card_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    password_changed_at TEXT NOT NULL
);
"""


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _next_application_id(conn: sqlite3.Connection) -> str:
    used = {
        str(row["application_id"])
        for row in conn.execute("SELECT application_id FROM card_applications")
    }
    for number in range(APPLICATION_NUMBER_START, 10_000):
        candidate = f"APP-{number}"
        if candidate not in used:
            return candidate
    raise ValueError("虚拟卡申请编号段已用尽（演示环境）。")


def _next_virtual_card_id(conn: sqlite3.Connection) -> str:
    used = {str(row["card_id"]) for row in conn.execute("SELECT card_id FROM bank_cards")}
    used |= {
        str(row["card_id"])
        for row in conn.execute(
            "SELECT card_id FROM card_applications WHERE card_id IS NOT NULL"
        )
    }
    for number in range(VIRTUAL_CARD_NUMBER_START, VIRTUAL_CARD_NUMBER_END + 1):
        candidate = f"CARD-{number}"
        if candidate not in used:
            return candidate
    raise ValueError("虚拟卡号段已用尽（演示环境）。")


def _masked_number(card_id: str) -> str:
    return f"**** {card_id.split('-', 1)[-1]}"


def _account_id_for_new_card(conn: sqlite3.Connection, user_id: str) -> str:
    """New cards share the account of the user's first existing card."""
    card = conn.execute(
        "SELECT account_id FROM bank_cards WHERE user_id = ? ORDER BY card_id LIMIT 1",
        (user_id,),
    ).fetchone()
    if card is not None:
        return str(card["account_id"])
    account = conn.execute(
        "SELECT account_id FROM bank_accounts WHERE user_id = ? ORDER BY account_id LIMIT 1",
        (user_id,),
    ).fetchone()
    if account is None:
        raise ValueError("当前用户没有可用账户，无法发卡。")
    return str(account["account_id"])


def seed(db: Database, user_id: str) -> None:
    """Seed one historical issued application; reruns are idempotent."""
    now = _iso_now()
    with db.transaction() as conn:
        first_card = conn.execute(
            "SELECT card_id FROM bank_cards WHERE user_id = ? ORDER BY card_id LIMIT 1",
            (user_id,),
        ).fetchone()
        if first_card is None:
            return
        conn.execute(
            """
            INSERT OR IGNORE INTO card_applications
            (application_id, user_id, kind, status, requested_limit_cents,
             card_id, created_at, updated_at)
            VALUES (?, ?, 'virtual', 'issued', ?, ?, ?, ?)
            """,
            (
                SEEDED_APPLICATION_ID,
                user_id,
                to_cents(8000),
                str(first_card["card_id"]),
                now,
                now,
            ),
        )


# ---------------------------------------------------------------------------
# Tool input/output models
# ---------------------------------------------------------------------------


class ApplyVirtualCardArgs(BaseModel):
    requested_limit_cny: float = Field(
        default=DEFAULT_REQUESTED_LIMIT_CNY,
        gt=0,
        le=MAX_REQUESTED_LIMIT_CNY,
        description="申请额度（元），默认 3000，最高 20000",
    )


class ApplyVirtualCardOutput(BaseModel):
    application_id: str
    kind: str
    status: str
    requested_limit_cny: float
    simulated: bool


class IssueVirtualCardArgs(BaseModel):
    application_id: str = Field(
        min_length=3, max_length=64, description="申请编号，例如 APP-9001"
    )


class IssueVirtualCardOutput(BaseModel):
    application_id: str
    card_id: str
    masked_number: str
    account_id: str
    status: str
    credit_limit_cny: float
    available_limit_cny: float
    repayment_day: int
    transaction_limit_cny: float
    simulated: bool


class ResetCardPasswordArgs(BaseModel):
    card_id: str = Field(default="CARD-8821", min_length=3, max_length=32)


class ResetCardPasswordOutput(BaseModel):
    card_id: str
    status: str
    password_changed_at: str
    simulated: bool


class UnlockTransactionLimitArgs(BaseModel):
    card_id: str = Field(default="CARD-8821", min_length=3, max_length=32)
    daily_limit_cny: float | None = Field(
        default=None,
        gt=0,
        le=100_000,
        description="可选目标限额（元）；不传则恢复默认 10000 元",
    )


class UnlockTransactionLimitOutput(BaseModel):
    card_id: str
    previous_transaction_limit_cny: float
    daily_limit_cny: float
    restored_default: bool
    status: str
    simulated: bool


# ---------------------------------------------------------------------------
# Tool nodes
# ---------------------------------------------------------------------------


class ApplyVirtualCardTool(BaseTool):
    metadata = ToolMetadata(
        name="apply_virtual_card",
        title="申请虚拟卡",
        description="创建一张虚拟卡的申请单，初始状态为 applying，属于账户开立类黄色操作。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=ApplyVirtualCardArgs.model_json_schema(),
        output_schema=ApplyVirtualCardOutput.model_json_schema(),
    )
    arguments_model = ApplyVirtualCardArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ApplyVirtualCardArgs.model_validate(arguments)
        requested_limit_cents = to_cents(args.requested_limit_cny)
        now = _iso_now()
        with self.services.db.transaction() as conn:
            application_id = _next_application_id(conn)
            conn.execute(
                """
                INSERT INTO card_applications
                (application_id, user_id, kind, status, requested_limit_cents,
                 card_id, created_at, updated_at)
                VALUES (?, ?, 'virtual', 'applying', ?, NULL, ?, ?)
                """,
                (application_id, context.user_id, requested_limit_cents, now, now),
            )
        output = ApplyVirtualCardOutput(
            application_id=application_id,
            kind="virtual",
            status="applying",
            requested_limit_cny=args.requested_limit_cny,
            simulated=SIMULATED,
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"虚拟卡申请已提交（{application_id}），等待审核发卡（演示数据）。",
            data=output.model_dump(),
        )


class IssueVirtualCardTool(BaseTool):
    metadata = ToolMetadata(
        name="issue_virtual_card",
        title="审核并发放虚拟卡",
        description=(
            "审核 applying 状态的虚拟卡申请，生成卡号并写入卡片清单，"
            "属于账户开立类黄色操作。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=IssueVirtualCardArgs.model_json_schema(),
        output_schema=IssueVirtualCardOutput.model_json_schema(),
    )
    arguments_model = IssueVirtualCardArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = super().validate_arguments(arguments)
        application_id = str(normalized["application_id"])
        # DAG 上一步产出的申请编号在编译期还是占位符，交给调度器执行前解析。
        if re.fullmatch(PLACEHOLDER_PATTERN, application_id):
            return normalized
        if not _APPLICATION_ID_PATTERN.fullmatch(application_id):
            raise ValueError(f"申请编号格式非法：{application_id}（应形如 APP-9001）")
        return normalized

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = IssueVirtualCardArgs.model_validate(arguments)
        now = _iso_now()
        with self.services.db.transaction() as conn:
            application = conn.execute(
                "SELECT * FROM card_applications WHERE application_id = ? AND user_id = ?",
                (args.application_id, context.user_id),
            ).fetchone()
            if application is None:
                raise ValueError(f"虚拟卡申请不存在：{args.application_id}")
            if application["status"] != "applying":
                raise ValueError(
                    f"虚拟卡申请 {args.application_id} 当前状态为 "
                    f"{application['status']}，只有 applying 状态可以发卡。"
                )
            account_id = _account_id_for_new_card(conn, context.user_id)
            card_id = _next_virtual_card_id(conn)
            masked_number = _masked_number(card_id)
            credit_limit_cents = int(application["requested_limit_cents"])
            transaction_limit_cents = to_cents(DEFAULT_TRANSACTION_LIMIT_CNY)
            conn.execute(
                """
                INSERT INTO bank_cards
                (card_id, user_id, account_id, masked_number, status,
                 credit_limit_cents, available_limit_cents, repayment_day,
                 transaction_limit_cents)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    card_id,
                    context.user_id,
                    account_id,
                    masked_number,
                    credit_limit_cents,
                    credit_limit_cents,
                    DEFAULT_REPAYMENT_DAY,
                    transaction_limit_cents,
                ),
            )
            conn.execute(
                "UPDATE card_applications SET status = 'issued', card_id = ?, updated_at = ? "
                "WHERE application_id = ? AND user_id = ? AND status = 'applying'",
                (card_id, now, args.application_id, context.user_id),
            )
        output = IssueVirtualCardOutput(
            application_id=args.application_id,
            card_id=card_id,
            masked_number=masked_number,
            account_id=account_id,
            status="active",
            credit_limit_cny=to_cny(credit_limit_cents),
            available_limit_cny=to_cny(credit_limit_cents),
            repayment_day=DEFAULT_REPAYMENT_DAY,
            transaction_limit_cny=to_cny(transaction_limit_cents),
            simulated=SIMULATED,
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"虚拟卡已发放（{card_id} / {masked_number}），模拟数据。",
            data=output.model_dump(),
        )


class ResetCardPasswordTool(BaseTool):
    metadata = ToolMetadata(
        name="reset_card_password",
        title="重置卡片密码",
        description=(
            "受理卡片密码重置：不接收、不保存明文密码，只记录安全事件时间，"
            "属于红色强验证操作。"
        ),
        risk_level=RiskLevel.RED,
        permission="card:security",
        input_schema=ResetCardPasswordArgs.model_json_schema(),
        output_schema=ResetCardPasswordOutput.model_json_schema(),
    )
    arguments_model = ResetCardPasswordArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ResetCardPasswordArgs.model_validate(arguments)
        card = self.services.repository.card(context.user_id, args.card_id)
        if card is None:
            raise ValueError(f"卡片不存在：{args.card_id}")
        now = _iso_now()
        with self.services.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO card_secrets (card_id, user_id, password_changed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    password_changed_at = excluded.password_changed_at
                """,
                (args.card_id, context.user_id, now),
            )
        output = ResetCardPasswordOutput(
            card_id=args.card_id,
            status="password_reset_accepted",
            password_changed_at=now,
            simulated=SIMULATED,
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message="密码重置已受理（演示数据）：系统只记录修改时间，不保存任何明文密码。",
            data=output.model_dump(),
        )


class UnlockTransactionLimitTool(BaseTool):
    metadata = ToolMetadata(
        name="unlock_transaction_limit",
        title="解锁交易限额",
        description=(
            "解除当前交易限额并恢复默认 10000 元；显式指定更高目标限额时风险升级，"
            "属于账户设置变更。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=UnlockTransactionLimitArgs.model_json_schema(),
        output_schema=UnlockTransactionLimitOutput.model_json_schema(),
    )
    arguments_model = UnlockTransactionLimitArgs

    def __init__(self, services: CoreServices) -> None:
        self.services = services

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = UnlockTransactionLimitArgs.model_validate(arguments)
        card = self.services.repository.card(context.user_id, args.card_id)
        if card is None:
            raise ValueError(f"卡片不存在：{args.card_id}")
        if args.daily_limit_cny is None:
            restored_default = True
            target_limit_cny = DEFAULT_TRANSACTION_LIMIT_CNY
        else:
            restored_default = False
            target_limit_cny = args.daily_limit_cny
        self.services.repository.set_transaction_limit(
            context.user_id, args.card_id, target_limit_cny
        )
        output = UnlockTransactionLimitOutput(
            card_id=args.card_id,
            previous_transaction_limit_cny=card.transaction_limit_cny,
            daily_limit_cny=target_limit_cny,
            restored_default=restored_default,
            status="unlocked",
            simulated=SIMULATED,
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"交易限额已解除，当前每日限额 {target_limit_cny:.2f} 元（演示数据）。",
            data=output.model_dump(),
        )


# ---------------------------------------------------------------------------
# Risk rules: baseline YELLOW tools + RED password reset / high unlock target
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApplyVirtualCardRisk:
    name: str = "cards.apply_virtual_card"
    priority: int = 20

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "apply_virtual_card":
            return None
        return RiskGuess(
            level=RiskLevel.YELLOW,
            score=45,
            reasons=["虚拟卡申请属于账户开立类操作，需要黄色确认。"],
        )


@dataclass(frozen=True, slots=True)
class IssueVirtualCardRisk:
    name: str = "cards.issue_virtual_card"
    priority: int = 20

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "issue_virtual_card":
            return None
        return RiskGuess(
            level=RiskLevel.YELLOW,
            score=45,
            reasons=["虚拟卡发卡会新增卡片并复用账户额度，需要黄色确认。"],
        )


@dataclass(frozen=True, slots=True)
class ResetCardPasswordRisk:
    name: str = "cards.reset_card_password"
    priority: int = 30

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "reset_card_password":
            return None
        return RiskGuess(
            level=RiskLevel.RED,
            score=90,
            reasons=[
                "卡片密码属于账户安全凭证，需要强验证。",
                "本操作不接收、不保存明文密码，仅记录已修改事件。",
            ],
        )


@dataclass(frozen=True, slots=True)
class UnlockTransactionLimitRisk:
    name: str = "cards.unlock_transaction_limit"
    priority: int = 30

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "unlock_transaction_limit":
            return None
        requested = ctx.arguments.get("daily_limit_cny")
        if requested is not None and float(requested) > HIGH_LIMIT_THRESHOLD_CNY:
            return RiskGuess(
                level=RiskLevel.RED,
                score=90,
                reasons=[
                    f"将交易限额恢复到 {float(requested):.2f} 元，"
                    "超过 5000 元高风险阈值。",
                    "需要红色强验证和明确确认。",
                ],
            )
        return RiskGuess(
            level=RiskLevel.YELLOW,
            score=45,
            reasons=[
                "解除交易限额属于账户设置变更。",
                f"未显式指定目标限额时恢复默认 {DEFAULT_TRANSACTION_LIMIT_CNY:.0f} 元。",
            ],
        )


# ---------------------------------------------------------------------------
# Planner intents
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApplyVirtualCardIntent:
    name: str = "cards.apply_virtual_card"
    priority: int = 10

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not _APPLY_CARD_PATTERN.search(ctx.instruction):
            return None
        if not (ctx.has_tool("apply_virtual_card") and ctx.has_tool("issue_virtual_card")):
            return None
        amounts = ctx.amounts()
        requested_limit_cny = amounts[0] if amounts else DEFAULT_REQUESTED_LIMIT_CNY
        if requested_limit_cny > MAX_REQUESTED_LIMIT_CNY:
            return ExecutionPlan(
                intent="virtual_card_issuance",
                planner="rule",
                confidence=0.4,
                needs_clarification=True,
                clarification=(
                    f"单张虚拟卡申请额度不能超过 {MAX_REQUESTED_LIMIT_CNY:.0f} 元，"
                    "请调整后重试。"
                ),
            )
        assumptions = (
            []
            if amounts
            else [f"未指定申请额度，默认申请 {DEFAULT_REQUESTED_LIMIT_CNY:.0f} 元额度。"]
        )
        return ExecutionPlan(
            intent="virtual_card_issuance",
            planner="rule",
            confidence=0.92,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="apply_virtual_card",
                    arguments={"requested_limit_cny": requested_limit_cny},
                    description="创建虚拟卡申请单（applying）。",
                ),
                PlanStep(
                    id="step-2",
                    tool_name="issue_virtual_card",
                    arguments={"application_id": "${steps.step-1.data.application_id}"},
                    depends_on=["step-1"],
                    description="审核通过并生成虚拟卡，写入卡片清单。",
                ),
            ],
        )


@dataclass(frozen=True, slots=True)
class ResetCardPasswordIntent:
    name: str = "cards.reset_card_password"
    priority: int = 20

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not _PASSWORD_PATTERN.search(ctx.instruction):
            return None
        if not ctx.has_tool("reset_card_password"):
            return None
        return ExecutionPlan(
            intent="reset_card_password",
            planner="rule",
            confidence=0.9,
            assumptions=["密码重置不接收、不保存明文密码，只记录安全事件时间。"],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="reset_card_password",
                    arguments={"card_id": ctx.card_id()},
                    description="受理卡片密码重置，仅记录已修改事件。",
                )
            ],
        )


@dataclass(frozen=True, slots=True)
class UnlockTransactionLimitIntent:
    name: str = "cards.unlock_transaction_limit"
    priority: int = 30

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not _UNLOCK_LIMIT_PATTERN.search(ctx.instruction):
            return None
        if not ctx.has_tool("unlock_transaction_limit"):
            return None
        arguments: dict[str, Any] = {"card_id": ctx.card_id()}
        amounts = ctx.amounts()
        if amounts:
            arguments["daily_limit_cny"] = amounts[0]
        assumptions = (
            []
            if amounts
            else [f"未指定目标限额，恢复默认 {DEFAULT_TRANSACTION_LIMIT_CNY:.0f} 元。"]
        )
        return ExecutionPlan(
            intent="unlock_transaction_limit",
            planner="rule",
            confidence=0.9,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="unlock_transaction_limit",
                    arguments=arguments,
                    description="解除交易限额并恢复默认额度。",
                )
            ],
        )


# ---------------------------------------------------------------------------
# Factories consumed by create_app()
# ---------------------------------------------------------------------------


def tools(services: CoreServices) -> list[BaseTool]:
    return [
        ApplyVirtualCardTool(services),
        IssueVirtualCardTool(services),
        ResetCardPasswordTool(services),
        UnlockTransactionLimitTool(services),
    ]


def risk_rules() -> list[RiskRule]:
    return [
        ApplyVirtualCardRisk(),
        IssueVirtualCardRisk(),
        ResetCardPasswordRisk(),
        UnlockTransactionLimitRisk(),
    ]


def intents() -> list[IntentRule]:
    return [
        ApplyVirtualCardIntent(),
        ResetCardPasswordIntent(),
        UnlockTransactionLimitIntent(),
    ]


def router(services: CoreServices) -> APIRouter:
    api = APIRouter(prefix="/api/cards", tags=["cards"])

    @api.get("/applications")
    def list_applications(
        user_id: str = Query(default=DEMO_USER, max_length=64),
    ) -> dict[str, Any]:
        with services.db.transaction() as conn:
            rows = conn.execute(
                """
                SELECT a.application_id, a.kind, a.status, a.requested_limit_cents,
                       a.card_id, a.created_at, a.updated_at, c.masked_number
                FROM card_applications AS a
                LEFT JOIN bank_cards AS c ON c.card_id = a.card_id
                WHERE a.user_id = ?
                ORDER BY a.created_at DESC, a.application_id DESC
                """,
                (user_id,),
            ).fetchall()
        applications = [
            {
                "application_id": row["application_id"],
                "kind": row["kind"],
                "status": row["status"],
                "requested_limit_cny": to_cny(row["requested_limit_cents"]),
                "card_id": row["card_id"],
                "masked_number": row["masked_number"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return {
            "applications": applications,
            "count": len(applications),
            "simulated": SIMULATED,
        }

    return api
