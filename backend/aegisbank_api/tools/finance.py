"""Simulated banking tools used by the MVP demo.

No real account, card, or money movement is touched. Replacing these adapters with
bank-grade APIs is intentionally isolated from the scheduler and gateway.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..registry import BaseTool, ToolRegistry


class QueryBillArgs(BaseModel):
    account_id: str = Field(default="ACC-1001", min_length=3, max_length=32)
    period: str = Field(default="current_month", max_length=32)


class QueryBillOutput(BaseModel):
    account_id: str
    period: str
    total_due_cny: float
    minimum_due_cny: float
    due_date: str
    transactions: list[dict[str, Any]]


class QueryBillTool(BaseTool):
    metadata = ToolMetadata(
        name="query_bill",
        title="查询账单",
        description="读取指定账户的账单汇总与近期交易，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="billing:read",
        input_schema=QueryBillArgs.model_json_schema(),
        output_schema=QueryBillOutput.model_json_schema(),
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = QueryBillArgs.model_validate(arguments)
        data = {
            "account_id": args.account_id,
            "period": args.period,
            "total_due_cny": 3280.50,
            "minimum_due_cny": 328.05,
            "due_date": "2026-11-08",
            "transactions": [
                {"date": "2026-10-16", "merchant": "城市生活超市", "amount_cny": -286.40},
                {"date": "2026-10-14", "merchant": "工资入账", "amount_cny": 18500.00},
                {"date": "2026-10-11", "merchant": "公共交通", "amount_cny": -54.00},
            ],
            "simulated": True,
        }
        return ToolResult(
            tool_name=self.metadata.name,
            message="已完成账单查询（演示数据）。",
            data=data,
        )


class AdjustRepaymentDateArgs(BaseModel):
    card_id: str = Field(default="CARD-8821", min_length=3, max_length=32)
    new_day: int = Field(default=18, ge=1, le=28)

    @field_validator("new_day")
    @classmethod
    def validate_day(cls, value: int) -> int:
        if not 1 <= value <= 28:
            raise ValueError("还款日必须落在每月 1 至 28 日")
        return value


class AdjustRepaymentDateOutput(BaseModel):
    card_id: str
    previous_day: int
    new_day: int
    effective_from: str
    simulated: bool


class AdjustRepaymentDateTool(BaseTool):
    metadata = ToolMetadata(
        name="adjust_repayment_date",
        title="调整还款日",
        description="调整信用卡每月还款日，属于会影响账户设置的黄色操作。",
        risk_level=RiskLevel.YELLOW,
        permission="card:manage",
        input_schema=AdjustRepaymentDateArgs.model_json_schema(),
        output_schema=AdjustRepaymentDateOutput.model_json_schema(),
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = AdjustRepaymentDateArgs.model_validate(arguments)
        data = {
            "card_id": args.card_id,
            "previous_day": 8,
            "new_day": args.new_day,
            "effective_from": "2026-11-01",
            "simulated": True,
        }
        return ToolResult(
            tool_name=self.metadata.name,
            message="还款日调整已生效（演示数据）。",
            data=data,
        )


class TransferArgs(BaseModel):
    from_account: str = Field(default="ACC-1001", min_length=3, max_length=32)
    to_account: str = Field(default="ACC-2002", min_length=3, max_length=32)
    amount_cny: float = Field(default=880.0, gt=0, le=50_000)
    note: str = Field(default="AegisBank MVP demo", max_length=120)


class TransferOutput(BaseModel):
    transaction_id: str
    from_account: str
    to_account: str
    amount_cny: float
    status: str
    executed_at: str
    simulated: bool


class TransferTool(BaseTool):
    metadata = ToolMetadata(
        name="transfer",
        title="小额转账",
        description="从本人账户向指定账户转账，属于红色高风险操作。",
        risk_level=RiskLevel.RED,
        permission="transfer:execute",
        input_schema=TransferArgs.model_json_schema(),
        output_schema=TransferOutput.model_json_schema(),
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = TransferArgs.model_validate(arguments)
        if args.from_account == args.to_account:
            raise ValueError("转出账户与转入账户不能相同")
        data = {
            "transaction_id": f"SIM-{uuid4().hex[:12].upper()}",
            "from_account": args.from_account,
            "to_account": args.to_account,
            "amount_cny": args.amount_cny,
            "status": "simulated_success",
            "executed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "simulated": True,
        }
        return ToolResult(
            tool_name=self.metadata.name,
            message="转账指令已通过红色风险校验并完成模拟执行。",
            data=data,
        )


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(QueryBillTool())
    registry.register(AdjustRepaymentDateTool())
    registry.register(TransferTool())
    return registry
