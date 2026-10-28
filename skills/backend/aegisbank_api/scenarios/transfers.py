"""转账形态场景：联系人簿、人名/手机号转账与 AA 拆分的多步 DAG。

模块契约见同目录 ``README.md``：

- 联系人事实全部来自 SQLite（``SCHEMA_SQL`` + ``seed``），Planner 不得凭空造人；
- 姓名/别名/手机号解析失败或多命中时一律澄清，绝不猜测收款人；
- 所有资金动作只经 ``transfer_to_contact`` 工具节点执行，最终由权限网关裁决；
- 返回数据统一标注 ``simulated=True``（演示银行，不接真实接口）。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from ..banking.repository import BankingRepository, to_cents, to_cny
from ..db import Database
from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..planning.contracts import ExecutionPlan, PlanStep
from ..planning.intents import IntentContext, extract_amounts
from ..registry import BaseTool
from ..risk_rules import RiskContext, RiskGuess
from ..services import CoreServices

NAME = "transfers"
DEFAULT_USER = "demo-user"
SELF_ACCOUNT = "ACC-1001"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS contacts (
    contact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    alias TEXT,
    phone TEXT,
    account_id TEXT NOT NULL,
    birthday TEXT,
    relation TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);
"""

# 固定演示联系人：account_id 为外部收款账户（不在本人 bank_accounts 中）。
# birthday 为 automation 场景生日联动保留字段，格式固定为 YYYY-MM-DD。
_SEED_CONTACTS: tuple[dict[str, str], ...] = (
    {
        "contact_id": "CT-9001",
        "name": "妈妈",
        "alias": "妈妈",
        "phone": "13900001111",
        "account_id": "ACC-9001",
        "birthday": "1990-11-18",
        "relation": "mother",
    },
    {
        "contact_id": "CT-9002",
        "name": "老爸",
        "alias": "老爸",
        "phone": "13900002222",
        "account_id": "ACC-9002",
        "birthday": "1965-06-09",
        "relation": "father",
    },
    {
        "contact_id": "CT-9003",
        "name": "张三",
        "alias": None,
        "phone": "13800138000",
        "account_id": "ACC-9003",
        "birthday": "1992-03-15",
        "relation": "friend",
    },
    {
        "contact_id": "CT-9004",
        "name": "李四",
        "alias": None,
        "phone": "13900139000",
        "account_id": "ACC-9004",
        "birthday": "1993-08-20",
        "relation": "friend",
    },
)

# Common spoken address terms for seeded relations. The mapping is only a
# normalisation hint: the resolved contact still has to exist in SQLite and an
# ambiguous match is always clarified, never guessed.
_CONTACT_RELATION_ALIASES = {
    "我妈": "妈妈",
    "我妈妈": "妈妈",
    "我老妈": "妈妈",
    "我母亲": "妈妈",
    "老妈": "妈妈",
    "母亲": "妈妈",
    "妈咪": "妈妈",
    "我的妈妈": "妈妈",
    "我爸": "老爸",
    "我爸爸": "老爸",
    "我老爸": "老爸",
    "我父亲": "老爸",
    "老爹": "老爸",
    "父亲": "老爸",
    "爸爸": "老爸",
    "我的爸爸": "老爸",
}

_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_ACCOUNT_RE = re.compile(r"ACC-\d{3,}")
_PHONE_IN_TEXT = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")

_SCHEDULE_HINTS = (
    "定时",
    "每天",
    "每周",
    "每月",
    "自动",
    "明天",
    "后天",
    "下个月",
    "生日",
    "提醒",
    "之后",
    "将来",
)

_AA_PARTICIPANTS_RE = re.compile(
    r"(?:和|跟|与|同)\s*([^\s，,。；;！!？?：:]+?)\s*(?:一起)?\s*aa",
    re.IGNORECASE,
)
_AA_PEOPLE_RE = re.compile(r"(\d+)\s*(?:个|位)?\s*人")
_PARTICIPANT_SPLIT_RE = re.compile(r"[、,，/和跟与\s]+")
_AA_NOISE_TOKENS = frozenset(
    {"", "一起", "我们", "大家", "这顿", "这餐", "今天", "昨天", "中午", "晚上", "请"}
)
_AA_NOISE_SUBSTRINGS = (
    "这顿",
    "这餐",
    "午饭",
    "晚饭",
    "午餐",
    "晚餐",
    "吃饭",
    "聚餐",
    "一起",
    "我们",
    "大家",
    "总共",
    "一共",
    "个人",
)

_NAME_TRANSFER_RE = re.compile(
    r"(?:给|向|帮|替)\s*([\u4e00-\u9fa5A-Za-z·]{1,12}?)\s*(?:转账|汇款|转)"
)


# ---------------------------------------------------------------------------
# 联系人事实层
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Contact:
    """联系人簿中的一条记录；展示时账户与手机号脱敏。"""

    contact_id: str
    user_id: str
    name: str
    alias: str | None
    phone: str | None
    account_id: str
    birthday: str | None
    relation: str | None
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "name": self.name,
            "alias": self.alias,
            "phone": _mask_phone(self.phone),
            "account_id": _mask_account(self.account_id),
            "birthday": self.birthday,
            "relation": self.relation,
            "status": self.status,
        }


def _mask_account(account_id: str) -> str:
    if len(account_id) <= 6:
        return f"{account_id[:2]}****"
    return f"{account_id[:4]}****{account_id[-2:]}"


def _mask_phone(phone: str | None) -> str | None:
    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def _contact_from_row(row: sqlite3.Row) -> Contact:
    return Contact(
        contact_id=str(row["contact_id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        alias=None if row["alias"] is None else str(row["alias"]),
        phone=None if row["phone"] is None else str(row["phone"]),
        account_id=str(row["account_id"]),
        birthday=None if row["birthday"] is None else str(row["birthday"]),
        relation=None if row["relation"] is None else str(row["relation"]),
        status=str(row["status"]),
    )


def contact_rows(db: Database, user_id: str, *, include_inactive: bool = False) -> list[Contact]:
    """Read contacts for one user; facts always come from SQLite."""
    sql = "SELECT * FROM contacts WHERE user_id = ?"
    if not include_inactive:
        sql += " AND status = 'active'"
    sql += " ORDER BY contact_id"
    with db.transaction() as conn:
        rows = conn.execute(sql, (user_id,)).fetchall()
    return [_contact_from_row(row) for row in rows]


def _name_matches(contact: Contact, token: str) -> bool:
    key = token.strip().casefold()
    names = {contact.name.casefold()}
    if contact.alias:
        names.add(contact.alias.casefold())
    if key in names:
        return True
    canonical = _CONTACT_RELATION_ALIASES.get(key)
    return canonical is not None and canonical.casefold() in names


def _resolve_contacts(
    db: Database,
    user_id: str,
    *,
    to_name: str | None = None,
    to_phone: str | None = None,
) -> list[Contact]:
    """Resolve a receiver by phone first, then by name/alias (including spoken kin terms)."""
    contacts = contact_rows(db, user_id)
    if to_phone:
        phone = to_phone.strip()
        hits = [item for item in contacts if item.phone == phone]
        if hits or not to_name:
            return hits
    if to_name:
        return [item for item in contacts if _name_matches(item, to_name)]
    return []


def _resolve_participant(db: Database, user_id: str, token: str) -> list[Contact]:
    if _PHONE_RE.fullmatch(token):
        return _resolve_contacts(db, user_id, to_phone=token)
    return _resolve_contacts(db, user_id, to_name=token)


# ---------------------------------------------------------------------------
# 演示数据 seed
# ---------------------------------------------------------------------------


def seed(db: Database, user_id: str) -> None:
    """Idempotently seed the contact book (``INSERT OR IGNORE``)."""
    rows = [
        (
            item["contact_id"],
            user_id,
            item["name"],
            item["alias"],
            item["phone"],
            item["account_id"],
            item["birthday"],
            item["relation"],
        )
        for item in _SEED_CONTACTS
    ]
    with db.transaction() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO contacts
            (contact_id, user_id, name, alias, phone, account_id, birthday, relation, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            rows,
        )


# ---------------------------------------------------------------------------
# 工具节点
# ---------------------------------------------------------------------------


class ListContactsArgs(BaseModel):
    include_inactive: bool = False


class ListContactsTool(BaseTool):
    metadata = ToolMetadata(
        name="list_contacts",
        read_only=True,
        title="查看联系人",
        description="读取联系人簿，账户与手机号脱敏展示，纯只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="contact:read",
        input_schema=ListContactsArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ListContactsArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ListContactsArgs.model_validate(arguments)
        contacts = contact_rows(
            self.repository.db, context.user_id, include_inactive=args.include_inactive
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message="已读取联系人簿（演示数据）。",
            data={
                "contacts": [item.as_dict() for item in contacts],
                "count": len(contacts),
                "simulated": True,
            },
        )


class AddContactArgs(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    phone: str = Field(min_length=11, max_length=11)
    account_id: str = Field(min_length=4, max_length=32)
    alias: str | None = Field(default=None, max_length=32)
    relation: str | None = Field(default=None, max_length=32)
    birthday: str | None = Field(default=None, max_length=10)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("联系人姓名不能为空")
        return stripped

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        stripped = value.strip()
        if not _PHONE_RE.fullmatch(stripped):
            raise ValueError("手机号格式不正确，应为 11 位中国大陆手机号")
        return stripped

    @field_validator("account_id")
    @classmethod
    def _validate_account_id(cls, value: str) -> str:
        stripped = value.strip().upper()
        if not _ACCOUNT_RE.fullmatch(stripped):
            raise ValueError("收款账户应形如 ACC-9001")
        return stripped

    @field_validator("alias")
    @classmethod
    def _clean_alias(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AddContactTool(BaseTool):
    metadata = ToolMetadata(
        name="add_contact",
        title="新增联系人",
        description="把姓名、手机号和收款账户写入联系人簿，属于会修改数据的黄色操作。",
        risk_level=RiskLevel.YELLOW,
        permission="contact:manage",
        input_schema=AddContactArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = AddContactArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = AddContactArgs.model_validate(arguments)
        contacts = contact_rows(self.repository.db, context.user_id)
        if any(item.phone == args.phone for item in contacts):
            raise ValueError(f"手机号 {_mask_phone(args.phone)} 已存在于联系人簿，未重复新增")
        contact_id = f"CT-{uuid4().hex[:8].upper()}"
        with self.repository.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO contacts
                (contact_id, user_id, name, alias, phone, account_id, birthday, relation, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    contact_id,
                    context.user_id,
                    args.name,
                    args.alias,
                    args.phone,
                    args.account_id,
                    args.birthday,
                    args.relation,
                ),
            )
        contact = Contact(
            contact_id=contact_id,
            user_id=context.user_id,
            name=args.name,
            alias=args.alias,
            phone=args.phone,
            account_id=args.account_id,
            birthday=args.birthday,
            relation=args.relation,
            status="active",
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"已新增联系人 {contact.name}（演示数据）。",
            data={"contact": contact.as_dict(), "status": "created", "simulated": True},
        )


class TransferToContactArgs(BaseModel):
    to_name: str | None = Field(default=None, max_length=32)
    to_phone: str | None = Field(default=None, max_length=11)
    amount_cny: float = Field(gt=0, le=50_000)
    note: str = Field(default="AegisBank 联系人转账", max_length=120)

    @field_validator("to_phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not _PHONE_RE.fullmatch(stripped):
            raise ValueError("手机号格式不正确，应为 11 位中国大陆手机号")
        return stripped

    @model_validator(mode="after")
    def _require_receiver(self) -> TransferToContactArgs:
        name = (self.to_name or "").strip()
        phone = (self.to_phone or "").strip()
        if not name and not phone:
            raise ValueError("必须提供 to_name 或 to_phone，以便解析收款联系人")
        if not self.note:
            object.__setattr__(self, "note", "AegisBank 联系人转账")
        return self


class TransferToContactTool(BaseTool):
    metadata = ToolMetadata(
        name="transfer_to_contact",
        title="联系人转账",
        description=(
            "按姓名/别名/手机号解析联系人后，从本人账户向该联系人收款账户完成模拟转账；"
            "解析失败或多命中会报错，不会猜测收款人。"
        ),
        risk_level=RiskLevel.YELLOW,
        permission="transfer:execute",
        compensable=True,
        compensation_tool="reverse_transfer",
        input_schema=TransferToContactArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = TransferToContactArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = TransferToContactArgs.model_validate(arguments)
        label = (args.to_name or "").strip() or (args.to_phone or "").strip()
        hits = _resolve_contacts(
            self.repository.db,
            context.user_id,
            to_name=args.to_name,
            to_phone=args.to_phone,
        )
        if not hits:
            raise ValueError(f"联系人簿中未找到「{label}」，请先添加联系人，我不会猜测收款人")
        if len(hits) > 1:
            names = "、".join(item.name for item in hits)
            raise ValueError(
                f"「{label}」匹配到多个联系人（{names}），请改用手机号或别名，我不会猜测收款人"
            )
        contact = hits[0]
        transfer = self.repository.transfer(
            context.user_id,
            {
                "from_account": SELF_ACCOUNT,
                "to_account": contact.account_id,
                "amount_cny": args.amount_cny,
                "note": args.note,
            },
        )
        return ToolResult(
            tool_name=self.metadata.name,
            message=f"已向联系人 {contact.name} 完成模拟转账（演示数据）。",
            data={
                "contact": contact.as_dict(),
                "transfer": transfer,
                "amount_cny": transfer["amount_cny"],
                "simulated": True,
            },
        )


# ---------------------------------------------------------------------------
# 风险规则：复用核心转账阈值，AA 按总额与日累计判定
# ---------------------------------------------------------------------------


def _is_aa_instruction(instruction: str) -> bool:
    return "aa" in instruction.lower()


def _aa_total_from(instruction: str) -> float | None:
    amounts = extract_amounts(instruction)
    if amounts:
        return amounts[0]
    return None


class ContactTransferRiskRule:
    """联系人转账风险：单笔 > 5000 元或日累计 > 1000 元升级红色。"""

    name = "transfers.contact_transfer_risk"
    priority = 20

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name != "transfer_to_contact":
            return None
        amount = float(ctx.arguments.get("amount_cny") or 0)
        instruction = ctx.instruction or ""
        aa_total = _aa_total_from(instruction) if _is_aa_instruction(instruction) else None
        effective = max(amount, aa_total or amount)
        daily = ctx.repository.daily_transfer_total_cny(ctx.user_id)
        projected = round(daily + effective, 2)
        facts: list[str] = []
        if aa_total is not None:
            facts.append(f"AA 总金额 {aa_total:.2f} 元，本次分摊转账 {amount:.2f} 元。")
        else:
            facts.append(f"本次联系人转账 {amount:.2f} 元。")
        if effective > 5000:
            facts.append(f"已超过 5000 元单笔高风险阈值，预计今日累计 {projected:.2f} 元。")
            facts.append("需要红色强验证（演示 OTP）并由用户明确确认。")
            return RiskGuess(level=RiskLevel.RED, score=100, reasons=facts)
        if projected > 1000:
            facts.append(f"预计今日累计转账 {projected:.2f} 元，超过 1000 元上限。")
            facts.append("需要红色强验证（演示 OTP）并由用户明确确认。")
            return RiskGuess(level=RiskLevel.RED, score=80, reasons=facts)
        facts.append(f"已低于 1000 元日累计阈值，今日累计预计 {projected:.2f} 元。")
        facts.append("需要黄色轻量确认。")
        return RiskGuess(level=RiskLevel.YELLOW, score=40, reasons=facts)


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


def _aa_participants(instruction: str) -> list[str]:
    match = _AA_PARTICIPANTS_RE.search(instruction)
    if match is not None:
        raw = match.group(1)
    else:
        head = re.split(r"aa", instruction, maxsplit=1, flags=re.IGNORECASE)[0]
        raw = re.sub(r"\d+(?:\.\d+)?\s*(?:元|块|rmb|cny)?", "", head, flags=re.IGNORECASE)
        for noise in _AA_NOISE_SUBSTRINGS:
            raw = raw.replace(noise, "、")
    tokens: list[str] = []
    for token in _PARTICIPANT_SPLIT_RE.split(raw):
        cleaned = token.strip()
        if not cleaned or cleaned in _AA_NOISE_TOKENS:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
            continue
        tokens.append(cleaned)
    return tokens


def _aa_people_count(instruction: str) -> int | None:
    match = _AA_PEOPLE_RE.search(instruction)
    return None if match is None else int(match.group(1))


class AASplitIntent:
    """AA 拆分：总金额 ÷ 人数，为每位参与者生成一笔转账款（可并行）。"""

    name = "transfers.aa_split"
    priority = 10

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        instruction = ctx.instruction
        if not _is_aa_instruction(instruction):
            return None
        if not ctx.has_tool("transfer_to_contact") or ctx.repository is None:
            return None
        total = _aa_total_from(instruction)
        if total is None or total <= 0:
            return _clarification(
                "请补充 AA 总金额，例如：这顿 300 元 3 个人 AA。",
                "transfer_aa_split",
            )
        tokens = _aa_participants(instruction)
        people_hint = _aa_people_count(instruction)
        if not tokens:
            if people_hint is not None and people_hint >= 2:
                return _clarification(
                    f"已识别 AA 共 {people_hint} 人，需要 {people_hint - 1} 位收款人；"
                    "请补充参与者姓名或手机号，我不会猜测收款人。",
                    "transfer_aa_split",
                )
            return _clarification(
                "请补充 AA 参与者（姓名或手机号）与总人数，例如：和妈妈、张三 AA 300。",
                "transfer_aa_split",
            )

        db = ctx.repository.db
        user_id = ctx.request.user_id
        contacts: list[Contact] = []
        unresolved: list[str] = []
        for token in tokens:
            hits = _resolve_participant(db, user_id, token)
            if not hits:
                unresolved.append(token)
            elif len(hits) > 1:
                return _clarification(
                    f"AA 参与者「{token}」匹配到多个联系人，请改用手机号或别名，我不会猜测收款人。",
                    "transfer_aa_split",
                )
            else:
                contacts.append(hits[0])
        if unresolved:
            return _clarification(
                "联系人簿中未找到 AA 参与者："
                + "、".join(unresolved)
                + "。请先添加联系人，我不会猜测收款人。",
                "transfer_aa_split",
            )
        seen: set[str] = set()
        for contact in contacts:
            if contact.contact_id in seen:
                return _clarification(
                    f"AA 参与者重复：{contact.name}，请确认参与名单。",
                    "transfer_aa_split",
                )
            seen.add(contact.contact_id)

        people = people_hint if people_hint is not None else len(contacts) + 1
        if people < 2:
            return _clarification("AA 至少需要 2 人参与，请确认人数。", "transfer_aa_split")
        if people != len(contacts) + 1:
            return _clarification(
                f"识别到 {len(contacts)} 位参与者，与 AA 共 {people} 人（需 {people - 1} 位"
                "收款人）不一致，请确认参与名单与总人数。",
                "transfer_aa_split",
            )
        total_cents = to_cents(total)
        per_person_cents = total_cents // people
        remainder_cents = total_cents - per_person_cents * people
        if per_person_cents <= 0:
            return _clarification(
                f"AA 总金额 {total:.2f} 元分摊到 {people} 人后人均不足 0.01 元，无法转账。",
                "transfer_aa_split",
            )
        amounts_cents = [per_person_cents] * len(contacts)
        amounts_cents[-1] += remainder_cents
        if sum(amounts_cents) + per_person_cents != total_cents:
            return _clarification(
                "AA 金额无法精确分摊到分，请调整总金额或参与人数。",
                "transfer_aa_split",
            )

        steps: list[PlanStep] = []
        for index, (contact, amount_cents) in enumerate(
            zip(contacts, amounts_cents, strict=True), start=1
        ):
            step_arguments: dict[str, Any] = {
                "to_name": contact.name,
                "amount_cny": to_cny(amount_cents),
                "note": f"AA 分摊：{instruction[:80]}",
            }
            if contact.phone:
                step_arguments["to_phone"] = contact.phone
            steps.append(
                PlanStep(
                    id=f"step-{index}",
                    tool_name="transfer_to_contact",
                    arguments=step_arguments,
                    description=(
                        f"向 {contact.name} 转账 {to_cny(amount_cents):.2f} 元"
                        f"（AA 分摊，共 {people} 人）。"
                    ),
                )
            )
        others_total = to_cny(sum(amounts_cents))
        assumptions = [
            f"AA 总金额 {total:.2f} 元，共 {people} 人，人均 {to_cny(per_person_cents):.2f} 元。",
            f"用户已垫付账单，向其余 {len(contacts)} 位参与者转账合计 {others_total:.2f} 元。",
            f"金额校验：人均 {to_cny(per_person_cents):.2f} × {people} 人 = {total:.2f} 元"
            "（分位尾差计入最后一笔）。",
        ]
        return ExecutionPlan(
            intent="transfer_aa_split",
            planner="rule",
            confidence=0.9,
            assumptions=assumptions,
            steps=steps,
        )


class ContactTransferIntent:
    """单笔联系人转账：按别名/姓名/手机号解析联系人后生成工具节点。"""

    name = "transfers.transfer_to_contact"
    priority = 20

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        instruction = ctx.instruction
        if _is_aa_instruction(instruction):
            return None
        if not ctx.has_tool("transfer_to_contact") or ctx.repository is None:
            return None
        if any(hint in instruction for hint in _SCHEDULE_HINTS):
            # 时间维度指令交给 automation 场景，避免抢占定时转账。
            return None

        receiver_name: str | None = None
        receiver_phone: str | None = None
        phone_match = _PHONE_IN_TEXT.search(instruction)
        if phone_match is not None:
            receiver_phone = phone_match.group(1)
        else:
            name_match = _NAME_TRANSFER_RE.search(instruction)
            if name_match is None:
                return None
            receiver_name = name_match.group(1).strip()
            if not receiver_name:
                return None
        label = receiver_name or receiver_phone or ""

        amounts = ctx.amounts()
        amount = amounts[0] if amounts else None
        if amount is None or amount <= 0:
            return _clarification(
                f"请补充给「{label}」的转账金额，例如：给{label}转 200 元。",
                "transfer_to_contact",
            )

        db = ctx.repository.db
        hits = _resolve_contacts(
            db, ctx.request.user_id, to_name=receiver_name, to_phone=receiver_phone
        )
        if not hits:
            return _clarification(
                f"联系人簿中未找到「{label}」，请先添加联系人，我不会猜测收款人。",
                "transfer_to_contact",
            )
        if len(hits) > 1:
            names = "、".join(item.name for item in hits)
            return _clarification(
                f"「{label}」匹配到多个联系人（{names}），请提供手机号或别名，我不会猜测收款人。",
                "transfer_to_contact",
            )
        contact = hits[0]
        step_arguments: dict[str, Any] = {
            "to_name": contact.name,
            "amount_cny": amount,
            "note": instruction[:120],
        }
        if contact.phone:
            step_arguments["to_phone"] = contact.phone
        return ExecutionPlan(
            intent="transfer_to_contact",
            planner="rule",
            confidence=0.92,
            assumptions=[
                f"按联系人簿解析「{label}」→ {contact.name}"
                f"（{_mask_account(contact.account_id)}）。",
                "未指定转出账户，默认使用本人工资卡 ACC-1001。",
            ],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="transfer_to_contact",
                    arguments=step_arguments,
                    description=f"向联系人 {contact.name} 转账 {amount:.2f} 元。",
                )
            ],
        )


class ListContactsIntent:
    """只读联系人查询。"""

    name = "transfers.list_contacts"
    priority = 35

    _QUERY_WORDS = ("查看", "列出", "看看", "看一下", "有哪些", "列表", "显示", "我的")

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("list_contacts"):
            return None
        instruction = ctx.instruction
        if "联系人" not in instruction and "通讯录" not in instruction:
            return None
        if not any(word in instruction for word in self._QUERY_WORDS):
            return None
        return ExecutionPlan(
            intent="list_contacts",
            planner="rule",
            confidence=0.9,
            assumptions=[],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="list_contacts",
                    arguments={},
                    description="读取联系人簿（账户与手机号脱敏展示）。",
                )
            ],
        )


# ---------------------------------------------------------------------------
# 场景契约工厂
# ---------------------------------------------------------------------------


def tools(services: CoreServices) -> list[BaseTool]:
    repository = services.repository
    return [
        ListContactsTool(repository),
        AddContactTool(repository),
        TransferToContactTool(repository),
    ]


def risk_rules() -> list[ContactTransferRiskRule]:
    return [ContactTransferRiskRule()]


def intents() -> list[AASplitIntent | ContactTransferIntent | ListContactsIntent]:
    # 顺序即优先级：AA 先于普通转账，联系人查询最后兜底。
    return [AASplitIntent(), ContactTransferIntent(), ListContactsIntent()]


def router(services: CoreServices) -> APIRouter:
    api = APIRouter(prefix="/api", tags=["transfers"])

    @api.get("/contacts")
    def get_contacts(
        user_id: str = Query(default=DEFAULT_USER, max_length=64),
    ) -> dict[str, Any]:
        contacts = contact_rows(services.repository.db, user_id)
        return {
            "contacts": [item.as_dict() for item in contacts],
            "count": len(contacts),
            "simulated": True,
        }

    return api


def semantic_intents():
    from ..planning.semantic_catalog import CURRENCY, ENTITY, MONEY, SemanticSpec

    return [
        SemanticSpec(
            "contact_transfer",
            (
                rf"(?:请)?(?:给|向)(?P<contact>(?!\s*ACC-){ENTITY})(?:转账|转|汇|打|划)(?:\n补充信息：)?(?P<amount>{MONEY}){CURRENCY}",
                rf"(?:给|向)(?P<contact>(?!\s*ACC-){ENTITY})(?:汇款|打款)\s*(?P<amount>{MONEY}){CURRENCY}",
                rf"(?:给|向)(?P<contact>(?!\s*ACC-){ENTITY})(?:汇款|打款|转账|汇|转)(?:钱)?",
            ),
            "给{contact}转{amount}元",
            {"contact": "contact", "amount": "money"},
            tools=("transfer_to_contact",),
        )
    ]


def semantic_entities(repository, user_id, kind):
    if kind != "contact":
        return []
    # Use phone as the canonical lookup key to disambiguate duplicate names.
    # Spoken kin terms are facts derived from the contact's actual name/alias;
    # they are not a model guess and still require a unique SQLite match.
    rows = []
    for contact in contact_rows(repository.db, user_id):
        canonical = {
            contact.name.casefold(),
            (contact.alias or "").casefold(),
        }
        spoken = [
            term
            for term, target in _CONTACT_RELATION_ALIASES.items()
            if target.casefold() in canonical
        ]
        names: list[str] = []
        for name in [
            contact.name,
            contact.alias or contact.name,
            contact.phone or contact.name,
            *spoken,
        ]:
            if name and name not in names:
                names.append(name)
        rows.append((contact.phone or contact.name, names))
    return rows
