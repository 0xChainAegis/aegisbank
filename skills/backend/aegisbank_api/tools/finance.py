"""Deterministic mock banking tools backed by the bank repository.

The tools deliberately contain no business-data literals. All account, bill,
card and subscription facts come from BankingRepository so the Planner and LLM
cannot invent financial data.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..banking.models import AccountInfo
from ..banking.repository import BankingRepository
from ..db import Database
from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..registry import BaseTool, ToolRegistry


class QueryBillArgs(BaseModel):
    account_id: str = Field(default="ACC-1001", min_length=3, max_length=32)
    period: str = Field(default="current_month", max_length=32)


class QueryBalanceArgs(BaseModel):
    account_id: str = Field(default="ACC-1001", min_length=3, max_length=32)


class QueryBalanceOutput(AccountInfo):
    simulated: bool


class QueryBalanceTool(BaseTool):
    metadata = ToolMetadata(
        name="query_balance",
        title="查询余额",
        description="读取指定本人模拟账户的余额与可用余额。",
        risk_level=RiskLevel.GREEN,
        permission="account:read",
        input_schema=QueryBalanceArgs.model_json_schema(),
        output_schema=QueryBalanceOutput.model_json_schema(),
    )
    arguments_model = QueryBalanceArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = QueryBalanceArgs.model_validate(arguments)
        account = self.repository.account(context.user_id, args.account_id)
        if account is None:
            raise ValueError("指定账户不存在或不属于当前用户。")
        return ToolResult(
            self.metadata.name, "已读取模拟账户余额。", {**account.model_dump(), "simulated": True}
        )


class QueryBillOutput(BaseModel):
    account_id: str
    period: str
    total_spend_cny: float
    categories: dict[str, float]
    anomalies: list[str]
    suspicious_subscription_id: str | None
    transactions: list[dict[str, Any]]


class QueryBillTool(BaseTool):
    metadata = ToolMetadata(
        name="query_bill",
        title="分析账单",
        description="读取并分析指定账户的本月账单，识别消费分类和异常订阅，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="billing:read",
        input_schema=QueryBillArgs.model_json_schema(),
        output_schema=QueryBillOutput.model_json_schema(),
    )
    arguments_model = QueryBillArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = QueryBillArgs.model_validate(arguments)
        bill = self.repository.bill(context.user_id, args.account_id, args.period)
        return ToolResult(
            tool_name=self.metadata.name,
            message="已完成账单分析（演示银行数据）。",
            data={**bill.model_dump(), "simulated": True},
        )


class TransferArgs(BaseModel):
    from_account: str = Field(default="ACC-1001", min_length=3, max_length=32)
    to_account: str = Field(min_length=3, max_length=32)
    amount_cny: float = Field(gt=0, le=50_000)
    note: str = Field(default="AegisBank 演示转账", max_length=120)


class TransferOutput(BaseModel):
    transaction_id: str
    from_account: str
    to_account: str
    amount_cny: float
    status: str
    daily_transfer_total_cny: float
    simulated: bool


class TransferTool(BaseTool):
    metadata = ToolMetadata(
        name="transfer",
        title="智能转账",
        description="从本人账户向指定账户转账；金额和日累计决定最终风险等级。",
        risk_level=RiskLevel.YELLOW,
        permission="transfer:execute",
        compensable=True,
        compensation_tool="reverse_transfer",
        input_schema=TransferArgs.model_json_schema(),
        output_schema=TransferOutput.model_json_schema(),
    )
    arguments_model = TransferArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = TransferArgs.model_validate(arguments)
        data = self.repository.transfer(context.user_id, args.model_dump())
        return ToolResult(
            tool_name=self.metadata.name,
            message="转账指令已通过风险校验并完成模拟执行。",
            data=data,
        )


class AdjustRepaymentDateArgs(BaseModel):
    card_id: str = Field(default="CARD-8821", min_length=3, max_length=32)
    new_day: int = Field(ge=1, le=28)

    @field_validator("new_day")
    @classmethod
    def validate_day(cls, value: int) -> int:
        if not 1 <= value <= 28:
            raise ValueError("还款日必须落在每月 1 至 28 日")
        return value


class AdjustRepaymentDateTool(BaseTool):
    metadata = ToolMetadata(
        name="adjust_repayment_date",
        title="调整还款日",
        description="调整信用卡每月还款日，属于会修改账户设置的黄色操作。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        compensable=True,
        compensation_tool="restore_repayment_date",
        input_schema=AdjustRepaymentDateArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = AdjustRepaymentDateArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = AdjustRepaymentDateArgs.model_validate(arguments)
        data = self.repository.adjust_repayment_date(context.user_id, args.card_id, args.new_day)
        return ToolResult(self.metadata.name, "还款日调整已生效（演示数据）。", data)


class AdjustCardLimitArgs(BaseModel):
    card_id: str = Field(default="CARD-8821", min_length=3, max_length=32)
    new_limit_cny: float = Field(gt=0, le=100_000)


class AdjustCardLimitTool(BaseTool):
    metadata = ToolMetadata(
        name="adjust_card_limit",
        title="调整卡片额度",
        description="调整信用卡额度；超过 5000 元会升级为红色强验证。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        compensable=True,
        compensation_tool="restore_card_limit",
        input_schema=AdjustCardLimitArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = AdjustCardLimitArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = AdjustCardLimitArgs.model_validate(arguments)
        data = self.repository.adjust_card_limit(context.user_id, args.card_id, args.new_limit_cny)
        return ToolResult(self.metadata.name, "卡片额度调整已生效（演示数据）。", data)


class SetTransactionLimitArgs(BaseModel):
    card_id: str = Field(default="CARD-8821", min_length=3, max_length=32)
    daily_limit_cny: float = Field(gt=0, le=100_000)


class SetTransactionLimitTool(BaseTool):
    metadata = ToolMetadata(
        name="set_transaction_limit",
        title="设置交易限额",
        description="设置信用卡每日交易限额，属于账户设置变更。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=SetTransactionLimitArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = SetTransactionLimitArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = SetTransactionLimitArgs.model_validate(arguments)
        data = self.repository.set_transaction_limit(
            context.user_id, args.card_id, args.daily_limit_cny
        )
        return ToolResult(self.metadata.name, "交易限额已更新（演示数据）。", data)


class CardActionArgs(BaseModel):
    card_id: str = Field(default="CARD-8821", min_length=3, max_length=32)


class ReportCardLostTool(BaseTool):
    metadata = ToolMetadata(
        name="report_card_lost",
        title="卡片挂失",
        description="挂失信用卡，属于高风险账户安全操作。",
        risk_level=RiskLevel.RED,
        permission="card:security",
        input_schema=CardActionArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = CardActionArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = CardActionArgs.model_validate(arguments)
        data = self.repository.set_card_status(context.user_id, args.card_id, "lost")
        return ToolResult(self.metadata.name, "卡片已挂失（演示数据）。", data)


class UnlockCardTool(BaseTool):
    metadata = ToolMetadata(
        name="unlock_card",
        title="卡片解挂",
        description="解除信用卡挂失状态，属于高风险账户安全操作。",
        risk_level=RiskLevel.RED,
        permission="card:security",
        input_schema=CardActionArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = CardActionArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = CardActionArgs.model_validate(arguments)
        data = self.repository.set_card_status(context.user_id, args.card_id, "active")
        return ToolResult(self.metadata.name, "卡片解挂已生效（演示数据）。", data)


class ListSubscriptionsArgs(BaseModel):
    include_cancelled: bool = False


class ListSubscriptionsTool(BaseTool):
    metadata = ToolMetadata(
        name="list_subscriptions",
        title="订阅查询",
        description="查询当前订阅及异常扣费提示，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="subscription:read",
        input_schema=ListSubscriptionsArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = ListSubscriptionsArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = ListSubscriptionsArgs.model_validate(arguments)
        items = self.repository.subscriptions(context.user_id)
        if not args.include_cancelled:
            items = [item for item in items if item.status == "active"]
        return ToolResult(
            self.metadata.name,
            "已读取订阅列表（演示数据）。",
            {"subscriptions": [item.model_dump() for item in items], "simulated": True},
        )


class CancelSubscriptionArgs(BaseModel):
    subscription_id: str = Field(min_length=3, max_length=64)


class CancelSubscriptionTool(BaseTool):
    metadata = ToolMetadata(
        name="cancel_subscription",
        title="取消订阅",
        description="取消指定订阅，属于会改变扣费状态的黄色操作。",
        risk_level=RiskLevel.YELLOW,
        permission="subscription:manage",
        compensable=True,
        compensation_tool="reactivate_subscription",
        input_schema=CancelSubscriptionArgs.model_json_schema(),
        output_schema={},
    )
    arguments_model = CancelSubscriptionArgs

    def __init__(self, repository: BankingRepository) -> None:
        self.repository = repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = CancelSubscriptionArgs.model_validate(arguments)
        data = self.repository.cancel_subscription(context.user_id, args.subscription_id)
        return ToolResult(self.metadata.name, "订阅取消已生效（演示数据）。", data)


def _default_repository() -> BankingRepository:
    # Used by planner unit tests and isolated tool catalogs. API runtime always
    # injects the real repository tied to the application database.
    return BankingRepository(Database(Path(gettempdir()) / "aegisbank-tool-registry.db"))


def build_registry(repository: BankingRepository | None = None) -> ToolRegistry:
    repo = repository or _default_repository()
    registry = ToolRegistry()
    registry.register(QueryBillTool(repo))
    registry.register(QueryBalanceTool(repo))
    registry.register(TransferTool(repo))
    registry.register(AdjustRepaymentDateTool(repo))
    registry.register(AdjustCardLimitTool(repo))
    registry.register(SetTransactionLimitTool(repo))
    registry.register(ReportCardLostTool(repo))
    registry.register(UnlockCardTool(repo))
    registry.register(ListSubscriptionsTool(repo))
    registry.register(CancelSubscriptionTool(repo))
    return registry
