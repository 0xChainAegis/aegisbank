"""Typed views returned by the mock banking repository."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AccountInfo(BaseModel):
    account_id: str
    name: str
    kind: str
    currency: str
    balance_cny: float
    available_cny: float


class CardInfo(BaseModel):
    card_id: str
    account_id: str
    masked_number: str
    status: str
    credit_limit_cny: float
    available_limit_cny: float
    repayment_day: int
    transaction_limit_cny: float


class SubscriptionInfo(BaseModel):
    subscription_id: str
    merchant: str
    amount_cny: float
    cycle: str
    next_charge_date: str
    status: str
    risk_flag: str | None = None


class BillAnalysis(BaseModel):
    account_id: str
    period: str
    month: str
    total_spend_cny: float
    categories: dict[str, float] = Field(default_factory=dict)
    anomalies: list[str] = Field(default_factory=list)
    suspicious_subscription_id: str | None = None
    suspicious_subscription_name: str | None = None
    transactions: list[dict[str, Any]] = Field(default_factory=list)


class BankingOverview(BaseModel):
    accounts: list[AccountInfo]
    cards: list[CardInfo]
    subscriptions: list[SubscriptionInfo]
    monthly_spend_cny: float
    daily_transfer_total_cny: float
    suspicious_subscription_id: str | None = None
    suspicious_reason: str | None = None
