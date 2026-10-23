"""账单与订阅深度场景：月报/年报、异常检测、订阅扣费识别与续费提醒。

本模块只读取确定性演示数据（``bank_transactions`` / ``bank_subscriptions``），
并向自己的 ``budgets`` 表与历史流水写入幂等种子数据。所有工具与路由都是只读
查询，输出统一标注 ``simulated=True``，不接入真实银行接口。
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..banking.repository import to_cents, to_cny
from ..db import Database
from ..domain import ExecutionContext, RiskLevel, ToolMetadata, ToolResult
from ..planning.contracts import ExecutionPlan, PlanStep
from ..planning.intents import IntentContext
from ..registry import BaseTool
from ..risk_rules import RiskContext, RiskGuess
from ..services import CoreServices

NAME = "bills"
DEMO_USER = "demo-user"
DEFAULT_ACCOUNT = "ACC-1001"
DEFAULT_CARD = "CARD-8821"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS budgets (
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    monthly_budget_cents INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, category)
);
"""

# (category, monthly_budget_cents) —— 单位：分
_BUDGETS: tuple[tuple[str, int], ...] = (
    ("food", 150_000),
    ("shopping", 200_000),
    ("subscription", 50_000),
    ("transport", 50_000),
)

_KIND_ORDER = {
    "duplicate_charge": 0,
    "over_budget": 1,
    "subscription_price_jump": 2,
    "off_hours": 3,
}
_KIND_LABELS = {
    "duplicate_charge": "同商户同日同金额重复扣费",
    "over_budget": "单类目超出月度预算",
    "subscription_price_jump": "订阅扣费金额环比突增",
    "off_hours": "非活跃时段（00:00-05:59）交易",
}
_KIND_SEVERITY = {
    "duplicate_charge": "high",
    "over_budget": "medium",
    "subscription_price_jump": "high",
    "off_hours": "medium",
}
_OFF_HOURS_START = 0
_OFF_HOURS_END = 5
_SUBSCRIPTION_JUMP_MIN_CENTS = 1_000
_SUBSCRIPTION_JUMP_MIN_PCT = 30.0

_MONTH_KEY_PATTERN = re.compile(r"^(20\d{2})-(\d{2})$")
_YEAR_KEY_PATTERN = re.compile(r"^(20\d{2})$")
_MONTH_ALIASES = frozenset({"month", "current_month", "this_month", "本月", "月报", "monthly"})
_YEAR_ALIASES = frozenset({"year", "current_year", "this_year", "年度", "年报", "yearly", "annual"})

_SeedRow = tuple[str, date, str, str, str, float, str | None]


def _today() -> date:
    return datetime.now(UTC).date()


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _previous_month_start(value: date) -> date:
    return _month_start(_month_start(value) - timedelta(days=1))


def _current_month_day(today: date, offset: int) -> date:
    """当前月的某一天：跨月时收敛到本月 1 号，保证始终落在本月。"""
    return max(today - timedelta(days=offset), _month_start(today))


def _previous_month_day(today: date, day_of_month: int) -> date:
    return _previous_month_start(today) + timedelta(days=day_of_month - 1)


def _timestamp(day: date, clock: str) -> str:
    return f"{day.isoformat()}T{clock}+00:00"


def _seed_transactions(today: date) -> list[_SeedRow]:
    """返回确定性的两月流水，覆盖重复扣费 / 超预算 / 订阅跳价 / 凌晨交易。"""

    def prev(day_of_month: int) -> date:
        return _previous_month_day(today, day_of_month)

    def cur(offset: int) -> date:
        return _current_month_day(today, offset)

    return [
        # 上月订阅历史：用于环比与订阅金额突增检测
        ("TX-BILL-001", prev(5), "09:12:00", "云端影音", "subscription", -45.00, "SUB-3001"),
        ("TX-BILL-002", prev(6), "10:05:00", "AI 工具订阅", "subscription", -199.00, "SUB-3002"),
        ("TX-BILL-003", prev(8), "11:20:00", "健身房月卡", "subscription", -299.00, "SUB-3003"),
        ("TX-BILL-004", prev(10), "12:00:00", "星云影音会员", "subscription", -45.00, "未登记代扣"),
        ("TX-BILL-005", prev(12), "18:30:00", "城市生活超市", "shopping", -120.00, None),
        ("TX-BILL-006", prev(15), "08:40:00", "地铁出行", "transport", -50.00, None),
        ("TX-BILL-007", prev(18), "12:30:00", "午餐", "food", -60.00, None),
        ("TX-BILL-008", prev(20), "20:15:00", "电商购物", "shopping", -200.00, None),
        ("TX-BILL-009", prev(22), "03:20:00", "夜宵外卖", "food", -35.00, None),
        ("TX-BILL-010", prev(25), "16:00:00", "云存储空间", "subscription", -30.00, "未登记代扣"),
        # 本月订阅跳价（上月 45 元 → 本月 199 元）与未登记代扣
        (
            "TX-BILL-011",
            cur(3),
            "10:00:00",
            "星云影音会员",
            "subscription",
            -199.00,
            "疑似订阅涨价",
        ),
        ("TX-BILL-012", cur(5), "09:00:00", "云存储空间", "subscription", -30.00, "未登记代扣"),
        # 重复扣费：同商户、同日、同金额两笔
        ("TX-BILL-013", cur(4), "08:10:00", "咖啡工坊", "food", -38.00, "疑似重复扣费 1/2"),
        ("TX-BILL-014", cur(4), "08:11:00", "咖啡工坊", "food", -38.00, "疑似重复扣费 2/2"),
        # 类目超预算：food 与 shopping
        ("TX-BILL-015", cur(2), "19:20:00", "城市宴会厅", "food", -1600.00, "大额餐饮"),
        ("TX-BILL-016", cur(7), "15:45:00", "品牌旗舰店", "shopping", -2180.00, "大额购物"),
        # 非活跃时段 02:xx 交易
        ("TX-BILL-017", cur(6), "02:35:00", "夜间便利店", "food", -66.00, "非活跃时段交易"),
        # 正常流水
        ("TX-BILL-018", cur(0), "08:30:00", "地铁出行", "transport", -54.00, None),
        ("TX-BILL-019", cur(1), "21:05:00", "电商购物", "shopping", -158.00, None),
    ]


def seed(db: Database, user_id: str = DEMO_USER) -> None:
    """幂等写入预算与两月演示流水（重复执行不会产生第二份数据）。"""
    today = _today()
    rows = _seed_transactions(today)
    with db.transaction() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO budgets "
            "(user_id, category, monthly_budget_cents, updated_at) VALUES (?, ?, ?, ?)",
            [(user_id, category, cents, today.isoformat()) for category, cents in _BUDGETS],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO bank_transactions "
            "(transaction_id, user_id, account_id, card_id, merchant, category, "
            "amount_cents, occurred_at, status, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?)",
            [
                (
                    transaction_id,
                    user_id,
                    DEFAULT_ACCOUNT,
                    DEFAULT_CARD,
                    merchant,
                    category,
                    to_cents(amount),
                    _timestamp(day, clock),
                    note,
                )
                for transaction_id, day, clock, merchant, category, amount, note in rows
            ],
        )


def _query(db: Database, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with db.transaction() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _month_rows(
    db: Database, user_id: str, account_id: str, month_key: str
) -> list[dict[str, Any]]:
    return _query(
        db,
        "SELECT * FROM bank_transactions WHERE user_id = ? AND account_id = ? "
        "AND occurred_at LIKE ? ORDER BY occurred_at, transaction_id",
        (user_id, account_id, f"{month_key}%"),
    )


def _year_rows(db: Database, user_id: str, account_id: str, year: int) -> list[dict[str, Any]]:
    return _query(
        db,
        "SELECT * FROM bank_transactions WHERE user_id = ? AND account_id = ? "
        "AND occurred_at LIKE ? ORDER BY occurred_at, transaction_id",
        (user_id, account_id, f"{year:04d}%"),
    )


def _budget_cents(db: Database, user_id: str) -> dict[str, int]:
    rows = _query(
        db,
        "SELECT category, monthly_budget_cents FROM budgets WHERE user_id = ? ORDER BY category",
        (user_id,),
    )
    return {str(row["category"]): int(row["monthly_budget_cents"]) for row in rows}


def _subscription_rows(db: Database, user_id: str) -> list[dict[str, Any]]:
    return _query(
        db,
        "SELECT * FROM bank_subscriptions WHERE user_id = ? ORDER BY subscription_id",
        (user_id,),
    )


def _previous_month_key(month_key: str) -> str:
    year, month = int(month_key[:4]), int(month_key[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def _resolve_period(
    period: str | None, month: str | None = None
) -> tuple[str, str | None, int, str]:
    today = _today()
    raw = (month or period or "month").strip()
    lowered = raw.lower()
    if raw == "" or lowered in _MONTH_ALIASES:
        key = today.strftime("%Y-%m")
        return "month", key, today.year, key
    if lowered in _YEAR_ALIASES:
        return "year", None, today.year, f"{today.year} 年"
    month_match = _MONTH_KEY_PATTERN.match(raw)
    if month_match:
        key = f"{month_match.group(1)}-{month_match.group(2)}"
        return "month", key, int(month_match.group(1)), key
    year_match = _YEAR_KEY_PATTERN.match(raw)
    if year_match:
        year = int(year_match.group(1))
        return "year", None, year, f"{year} 年"
    raise ValueError("period 仅支持 month、year、YYYY-MM 或 YYYY。")


def _resolve_month(period: str | None, month: str | None = None) -> str:
    raw = (month or period or "month").strip()
    lowered = raw.lower()
    if raw == "" or lowered in _MONTH_ALIASES:
        return _today().strftime("%Y-%m")
    month_match = _MONTH_KEY_PATTERN.match(raw)
    if month_match:
        return f"{month_match.group(1)}-{month_match.group(2)}"
    raise ValueError("period 仅支持 month 或 YYYY-MM。")


def _aggregate_spend(
    rows: list[dict[str, Any]],
) -> tuple[int, int, dict[str, int], dict[str, dict[str, Any]]]:
    total_cents = 0
    spend_count = 0
    categories: dict[str, int] = {}
    merchants: dict[str, dict[str, Any]] = {}
    for row in rows:
        amount_cents = int(row["amount_cents"])
        if amount_cents >= 0:
            continue
        cents = -amount_cents
        total_cents += cents
        spend_count += 1
        category = str(row["category"])
        categories[category] = categories.get(category, 0) + cents
        merchant = str(row["merchant"]).strip()
        entry = merchants.setdefault(
            merchant,
            {
                "merchant": merchant,
                "category": category,
                "amount_cents": 0,
                "count": 0,
            },
        )
        entry["amount_cents"] += cents
        entry["count"] += 1
    return total_cents, spend_count, categories, merchants


def _top_merchants(merchants: dict[str, dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    items = [
        {
            "merchant": item["merchant"],
            "category": item["category"],
            "amount_cny": to_cny(int(item["amount_cents"])),
            "count": int(item["count"]),
        }
        for item in merchants.values()
    ]
    items.sort(key=lambda item: (-float(item["amount_cny"]), str(item["merchant"])))
    return items[:limit]


def _comparison(current_cny: float, previous_cny: float, baseline: str) -> dict[str, Any]:
    change_cny = round(current_cny - previous_cny, 2)
    comparable = previous_cny > 0
    change_pct = round(change_cny / previous_cny * 100, 1) if comparable else None
    if not comparable:
        direction = "缺少可比基线"
    elif change_cny > 0:
        direction = "增长"
    elif change_cny < 0:
        direction = "下降"
    else:
        direction = "持平"
    return {
        "baseline": baseline,
        "previous_total_cny": previous_cny,
        "change_cny": change_cny,
        "change_pct": change_pct,
        "direction": direction,
        "comparable": comparable,
    }


def _budget_usage(
    categories: dict[str, float], budgets_cents: dict[str, int]
) -> list[dict[str, Any]]:
    usage: list[dict[str, Any]] = []
    for category in sorted(budgets_cents):
        budget_cny = to_cny(budgets_cents[category])
        spent_cny = round(categories.get(category, 0.0), 2)
        usage_pct = round(spent_cny / budget_cny * 100, 1) if budget_cny > 0 else None
        usage.append(
            {
                "category": category,
                "budget_cny": budget_cny,
                "spent_cny": spent_cny,
                "usage_pct": usage_pct,
                "over_budget": spent_cny > budget_cny,
            }
        )
    return usage


def _conclusion(
    label: str,
    total_cny: float,
    comparison: dict[str, Any],
    categories: dict[str, float],
    over_budget: list[dict[str, Any]],
) -> str:
    prefix = label if label.endswith("年") else f"{label} "
    parts = [f"{prefix}账单共支出 {total_cny:.2f} 元"]
    if comparison["comparable"] and comparison["change_pct"] is not None:
        baseline = str(comparison["baseline"])
        direction = str(comparison["direction"])
        if direction == "持平":
            parts.append(f"与{baseline}基本持平")
        else:
            change_pct = abs(float(comparison["change_pct"]))
            parts.append(f"较{baseline}{direction} {change_pct:.1f}%")
    else:
        parts.append(f"暂无{comparison['baseline']}数据可供对比")
    if categories:
        top_category, top_amount = next(iter(categories.items()))
        parts.append(f"支出主要集中在「{top_category}」（{top_amount:.2f} 元）")
    if over_budget:
        names = "、".join(str(item["category"]) for item in over_budget)
        parts.append(f"「{names}」已超出月度预算，建议优先核对")
    return "；".join(parts) + "。以上为模拟数据，仅供演示。"


def _duplicate_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        amount_cents = int(row["amount_cents"])
        if amount_cents >= 0:
            continue
        key = (str(row["merchant"]).strip(), str(row["occurred_at"])[:10], amount_cents)
        groups.setdefault(key, []).append(row)
    anomalies: list[dict[str, Any]] = []
    for merchant, day, amount_cents in sorted(groups):
        items = groups[(merchant, day, amount_cents)]
        if len(items) < 2:
            continue
        amount_cny = to_cny(-amount_cents)
        transaction_ids = sorted(str(item["transaction_id"]) for item in items)
        anomalies.append(
            {
                "kind": "duplicate_charge",
                "severity": _KIND_SEVERITY["duplicate_charge"],
                "message": (
                    f"检测到「{merchant}」在 {day} 出现 {len(items)} 笔相同金额 "
                    f"{amount_cny:.2f} 元的扣费，疑似重复扣费。"
                ),
                "evidence": {
                    "merchant": merchant,
                    "date": day,
                    "amount_cny": amount_cny,
                    "count": len(items),
                    "transaction_ids": transaction_ids,
                },
            }
        )
    return anomalies


def _spend_by_category(rows: list[dict[str, Any]]) -> dict[str, int]:
    category_cents: dict[str, int] = {}
    for row in rows:
        amount_cents = int(row["amount_cents"])
        if amount_cents >= 0:
            continue
        category = str(row["category"])
        category_cents[category] = category_cents.get(category, 0) + -amount_cents
    return category_cents


def _over_budget_anomalies(
    rows: list[dict[str, Any]], budgets_cents: dict[str, int]
) -> list[dict[str, Any]]:
    spent = _spend_by_category(rows)
    anomalies: list[dict[str, Any]] = []
    for category in sorted(budgets_cents):
        budget_cents = budgets_cents[category]
        spent_cents = spent.get(category, 0)
        if spent_cents <= budget_cents:
            continue
        anomalies.append(
            {
                "kind": "over_budget",
                "severity": _KIND_SEVERITY["over_budget"],
                "message": (
                    f"类目「{category}」本月支出 {to_cny(spent_cents):.2f} 元，"
                    f"已超出月度预算 {to_cny(budget_cents):.2f} 元"
                    f"（超支 {to_cny(spent_cents - budget_cents):.2f} 元）。"
                ),
                "evidence": {
                    "category": category,
                    "spent_cny": to_cny(spent_cents),
                    "budget_cny": to_cny(budget_cents),
                    "over_cny": to_cny(spent_cents - budget_cents),
                    "usage_pct": round(spent_cents / budget_cents * 100, 1),
                },
            }
        )
    return anomalies


def _subscription_average_by_merchant(
    rows: list[dict[str, Any]],
) -> dict[str, tuple[int, int]]:
    totals: dict[str, list[int]] = {}
    for row in rows:
        amount_cents = int(row["amount_cents"])
        if amount_cents >= 0 or str(row["category"]) != "subscription":
            continue
        merchant = str(row["merchant"]).strip()
        bucket = totals.setdefault(merchant, [0, 0])
        bucket[0] += -amount_cents
        bucket[1] += 1
    return {
        merchant: (total_cents // count, count)
        for merchant, (total_cents, count) in totals.items()
        if count > 0
    }


def _subscription_jump_anomalies(
    rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    month_key: str,
    previous_key: str,
    registered: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    current = _subscription_average_by_merchant(rows)
    previous = _subscription_average_by_merchant(previous_rows)
    anomalies: list[dict[str, Any]] = []
    for merchant in sorted(set(current) & set(previous)):
        current_avg, _ = current[merchant]
        previous_avg, _ = previous[merchant]
        if previous_avg <= 0 or current_avg <= previous_avg:
            continue
        change_cents = current_avg - previous_avg
        change_pct = round((current_avg / previous_avg - 1) * 100, 1)
        if change_cents < _SUBSCRIPTION_JUMP_MIN_CENTS or change_pct < _SUBSCRIPTION_JUMP_MIN_PCT:
            continue
        sub = registered.get(merchant)
        anomalies.append(
            {
                "kind": "subscription_price_jump",
                "severity": _KIND_SEVERITY["subscription_price_jump"],
                "message": (
                    f"订阅「{merchant}」本月平均扣费 {to_cny(current_avg):.2f} 元，"
                    f"较上月 {to_cny(previous_avg):.2f} 元上涨 {change_pct:.1f}%，"
                    "疑似订阅涨价，建议核对。"
                ),
                "evidence": {
                    "merchant": merchant,
                    "current_month": month_key,
                    "last_month": previous_key,
                    "current_average_cny": to_cny(current_avg),
                    "last_average_cny": to_cny(previous_avg),
                    "change_pct": change_pct,
                    "subscription_id": None if sub is None else str(sub["subscription_id"]),
                },
            }
        )
    return anomalies


def _off_hours_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for row in rows:
        amount_cents = int(row["amount_cents"])
        if amount_cents >= 0:
            continue
        occurred_at = str(row["occurred_at"])
        parsed = _parse_iso(occurred_at)
        if parsed is None or not _OFF_HOURS_START <= parsed.hour <= _OFF_HOURS_END:
            continue
        amount_cny = to_cny(-amount_cents)
        anomalies.append(
            {
                "kind": "off_hours",
                "severity": _KIND_SEVERITY["off_hours"],
                "message": (
                    f"检测到「{row['merchant']}」在非活跃时段 {parsed.strftime('%H:%M')} "
                    f"发生 {amount_cny:.2f} 元交易，请确认是否本人操作。"
                ),
                "evidence": {
                    "transaction_id": str(row["transaction_id"]),
                    "merchant": str(row["merchant"]),
                    "occurred_at": occurred_at,
                    "amount_cny": amount_cny,
                    "hour": parsed.hour,
                },
            }
        )
    anomalies.sort(key=lambda item: str(item["evidence"]["transaction_id"]))
    return anomalies


def build_anomalies(
    db: Database,
    user_id: str,
    account_id: str = DEFAULT_ACCOUNT,
    period: str | None = "month",
    month: str | None = None,
) -> dict[str, Any]:
    """按 4 条确定性规则检测异常，返回可解释证据。"""
    month_key = _resolve_month(period, month)
    rows = _month_rows(db, user_id, account_id, month_key)
    previous_key = _previous_month_key(month_key)
    previous_rows = _month_rows(db, user_id, account_id, previous_key)
    budgets_cents = _budget_cents(db, user_id)
    registered = {str(row["merchant"]).strip(): row for row in _subscription_rows(db, user_id)}
    anomalies: list[dict[str, Any]] = []
    anomalies.extend(_duplicate_anomalies(rows))
    anomalies.extend(_over_budget_anomalies(rows, budgets_cents))
    anomalies.extend(
        _subscription_jump_anomalies(rows, previous_rows, month_key, previous_key, registered)
    )
    anomalies.extend(_off_hours_anomalies(rows))
    anomalies.sort(key=lambda item: (_KIND_ORDER[item["kind"]], item["message"]))
    counts_by_kind = {kind: 0 for kind in _KIND_ORDER}
    for anomaly in anomalies:
        counts_by_kind[str(anomaly["kind"])] += 1
    high_count = sum(1 for item in anomalies if item["severity"] == "high")
    return {
        "account_id": account_id,
        "period": "month",
        "month": month_key,
        "anomalies": anomalies,
        "counts_by_kind": counts_by_kind,
        "total": len(anomalies),
        "high_severity_count": high_count,
        "rules": [
            {
                "kind": kind,
                "description": _KIND_LABELS[kind],
                "severity": _KIND_SEVERITY[kind],
            }
            for kind in _KIND_ORDER
        ],
        "conclusion": (
            f"已在 {month_key} 账单中按 4 条确定性规则识别到 {len(anomalies)} 条疑似异常"
            f"（高严重度 {high_count} 条），建议优先核对重复扣费与订阅涨价。"
            "以上为模拟数据，仅供演示。"
        ),
        "simulated": True,
    }


def build_bill_report(
    db: Database,
    user_id: str,
    account_id: str = DEFAULT_ACCOUNT,
    period: str | None = "month",
    month: str | None = None,
) -> dict[str, Any]:
    """生成月报或年报：分类汇总、Top5 商户、环比与结论文本。"""
    mode, month_key, year, label = _resolve_period(period, month)
    budgets_cents = _budget_cents(db, user_id)
    if mode == "month":
        rows = _month_rows(db, user_id, account_id, str(month_key))
        previous_rows = _month_rows(db, user_id, account_id, _previous_month_key(str(month_key)))
        previous_label = "上月"
    else:
        rows = _year_rows(db, user_id, account_id, year)
        previous_rows = _year_rows(db, user_id, account_id, year - 1)
        previous_label = "去年"
    total_cents, spend_count, categories_cents, merchants = _aggregate_spend(rows)
    previous_total_cents, _, _, _ = _aggregate_spend(previous_rows)
    total_cny = to_cny(total_cents)
    ordered_categories = sorted(categories_cents.items(), key=lambda item: (-item[1], item[0]))
    categories = {category: to_cny(cents) for category, cents in ordered_categories}
    comparison = _comparison(total_cny, to_cny(previous_total_cents), previous_label)
    budget_usage = _budget_usage(categories, budgets_cents) if mode == "month" else []
    over_budget = [item for item in budget_usage if item["over_budget"]]
    return {
        "account_id": account_id,
        "period": mode,
        "label": label,
        "month": month_key,
        "year": year,
        "total_spend_cny": total_cny,
        "categories": categories,
        "top_merchants": _top_merchants(merchants),
        "transaction_count": spend_count,
        "all_transaction_count": len(rows),
        "comparison": comparison,
        "budget_usage": budget_usage,
        "conclusion": _conclusion(label, total_cny, comparison, categories, over_budget),
        "simulated": True,
    }


def _subscription_entities(
    db: Database, user_id: str, account_id: str | None
) -> dict[str, list[dict[str, Any]]]:
    sql = "SELECT * FROM bank_transactions WHERE user_id = ? AND category = 'subscription'"
    params: list[Any] = [user_id]
    if account_id:
        sql += " AND account_id = ?"
        params.append(account_id)
    sql += " ORDER BY occurred_at, transaction_id"
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _query(db, sql, tuple(params)):
        if int(row["amount_cents"]) >= 0:
            continue
        merchant = str(row["merchant"]).strip()
        grouped.setdefault(merchant, []).append(row)
    return grouped


def build_subscription_charges(
    db: Database, user_id: str, account_id: str | None = None
) -> dict[str, Any]:
    """把 subscription 类目流水聚合成订阅实体，并标记未登记代扣。"""
    grouped = _subscription_entities(db, user_id, account_id)
    registered = {str(row["merchant"]).strip(): row for row in _subscription_rows(db, user_id)}
    subscriptions: list[dict[str, Any]] = []
    for merchant in sorted(grouped):
        charges = grouped[merchant]
        total_cents = sum(-int(item["amount_cents"]) for item in charges)
        latest = charges[-1]
        sub = registered.get(merchant)
        is_registered = sub is not None
        subscriptions.append(
            {
                "merchant": merchant,
                "charge_count": len(charges),
                "total_spend_cny": to_cny(total_cents),
                "average_amount_cny": to_cny(total_cents // len(charges)),
                "latest_charge_date": str(latest["occurred_at"])[:10],
                "latest_charge_cny": to_cny(-int(latest["amount_cents"])),
                "latest_transaction_id": str(latest["transaction_id"]),
                "registered": is_registered,
                "unregistered_debit": not is_registered,
                "subscription_id": None if sub is None else str(sub["subscription_id"]),
                "cycle": None if sub is None else str(sub["cycle"]),
                "status": None if sub is None else str(sub["status"]),
                "risk_flag": None if sub is None else sub["risk_flag"],
                "advice": (
                    "已登记在订阅管理中，请核对扣费金额与周期是否与登记一致。"
                    if is_registered
                    else "未登记在订阅管理中，疑似未登记代扣，建议核对并在不再使用时取消。"
                ),
            }
        )
    subscriptions.sort(key=lambda item: (-float(item["total_spend_cny"]), item["merchant"]))
    unregistered = [item for item in subscriptions if item["unregistered_debit"]]
    return {
        "account_id": account_id,
        "subscriptions": subscriptions,
        "total": len(subscriptions),
        "registered_count": len(subscriptions) - len(unregistered),
        "unregistered_count": len(unregistered),
        "window": "全部历史账单流水（category=subscription）",
        "conclusion": (
            f"共识别出 {len(subscriptions)} 个订阅扣费实体，其中 {len(unregistered)} 个未登记代扣。"
            "以上为模拟数据，仅供演示。"
        ),
        "simulated": True,
    }


def build_renewal_reminders(
    db: Database,
    user_id: str,
    cycle: str | None = None,
    days_ahead: int = 30,
) -> dict[str, Any]:
    """基于 next_charge_date 生成站内续费提醒（不含外部推送）。"""
    today = _today()
    wanted_cycle = cycle.strip().lower() if cycle else None
    reminders: list[dict[str, Any]] = []
    for row in _subscription_rows(db, user_id):
        if str(row["status"]) != "active":
            continue
        row_cycle = str(row["cycle"]).lower()
        if wanted_cycle and row_cycle != wanted_cycle:
            continue
        next_charge_date = str(row["next_charge_date"])[:10]
        try:
            charge_date = date.fromisoformat(next_charge_date)
        except ValueError:
            continue
        raw_days = (charge_date - today).days
        if raw_days > days_ahead:
            continue
        days_left = max(raw_days, 0)
        overdue = raw_days < 0
        if overdue:
            advice = "预计扣费日期已过，请核对是否已经扣费，避免遗漏。"
        elif days_left <= 3:
            advice = "即将扣费，如不再需要请在 3 天内取消订阅。"
        elif days_left <= 7:
            advice = "一周内将续费，建议确认该订阅是否仍在使用。"
        else:
            advice = "续费日期尚远，可保持关注或提前调整订阅。"
        reminders.append(
            {
                "subscription_id": str(row["subscription_id"]),
                "merchant": str(row["merchant"]),
                "amount_cny": to_cny(int(row["amount_cents"])),
                "cycle": str(row["cycle"]),
                "next_charge_date": next_charge_date,
                "days_left": days_left,
                "overdue": overdue,
                "risk_flag": row["risk_flag"],
                "advice": advice,
            }
        )
    reminders.sort(key=lambda item: (int(item["days_left"]), str(item["next_charge_date"])))
    return {
        "reminders": reminders,
        "count": len(reminders),
        "cycle": wanted_cycle or "all",
        "days_ahead": days_ahead,
        "as_of": today.isoformat(),
        "channel": "in_app_only",
        "note": "仅生成站内续费提醒，不包含短信、邮件等外部推送。",
        "simulated": True,
    }


class BillReportArgs(BaseModel):
    account_id: str = Field(default=DEFAULT_ACCOUNT, min_length=3, max_length=32)
    period: str = Field(default="month", max_length=16)
    month: str | None = Field(default=None, max_length=7)


class BillReportOutput(BaseModel):
    account_id: str
    period: str
    label: str
    month: str | None = None
    year: int
    total_spend_cny: float
    categories: dict[str, float] = Field(default_factory=dict)
    top_merchants: list[dict[str, Any]] = Field(default_factory=list)
    transaction_count: int
    all_transaction_count: int
    comparison: dict[str, Any] = Field(default_factory=dict)
    budget_usage: list[dict[str, Any]] = Field(default_factory=list)
    conclusion: str
    simulated: bool


class DetectAnomaliesArgs(BaseModel):
    account_id: str = Field(default=DEFAULT_ACCOUNT, min_length=3, max_length=32)
    period: str = Field(default="month", max_length=16)
    month: str | None = Field(default=None, max_length=7)


class DetectAnomaliesOutput(BaseModel):
    account_id: str
    period: str
    month: str
    anomalies: list[dict[str, Any]] = Field(default_factory=list)
    counts_by_kind: dict[str, int] = Field(default_factory=dict)
    total: int
    high_severity_count: int
    rules: list[dict[str, Any]] = Field(default_factory=list)
    conclusion: str
    simulated: bool


class SubscriptionChargesArgs(BaseModel):
    account_id: str | None = Field(default=None, max_length=32)


class SubscriptionChargesOutput(BaseModel):
    account_id: str | None = None
    subscriptions: list[dict[str, Any]] = Field(default_factory=list)
    total: int
    registered_count: int
    unregistered_count: int
    window: str
    conclusion: str
    simulated: bool


class RenewalRemindersArgs(BaseModel):
    cycle: str | None = Field(default=None, max_length=16)
    days_ahead: int = Field(default=30, ge=0, le=365)


class RenewalRemindersOutput(BaseModel):
    reminders: list[dict[str, Any]] = Field(default_factory=list)
    count: int
    cycle: str
    days_ahead: int
    as_of: str
    channel: str
    note: str
    simulated: bool


class BillReportTool(BaseTool):
    metadata = ToolMetadata(
        name="bill_report",
        title="账单报告",
        description="生成月报/年报：分类汇总、Top5 商户与环比，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="billing:read",
        input_schema=BillReportArgs.model_json_schema(),
        output_schema=BillReportOutput.model_json_schema(),
    )
    arguments_model = BillReportArgs

    def __init__(self, services: CoreServices) -> None:
        self.db = services.db
        self.repository = services.repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = BillReportArgs.model_validate(arguments)
        if self.repository.account(context.user_id, args.account_id) is None:
            raise ValueError(f"账户不存在：{args.account_id}")
        data = build_bill_report(self.db, context.user_id, args.account_id, args.period, args.month)
        return ToolResult(
            self.metadata.name,
            f"已生成 {data['label']} 账单报告（演示银行数据）。",
            data,
        )


class DetectBillAnomaliesTool(BaseTool):
    metadata = ToolMetadata(
        name="detect_bill_anomalies",
        title="账单异常检测",
        description="按确定性规则检测重复扣费、超预算、订阅涨价与凌晨交易，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="billing:read",
        input_schema=DetectAnomaliesArgs.model_json_schema(),
        output_schema=DetectAnomaliesOutput.model_json_schema(),
    )
    arguments_model = DetectAnomaliesArgs

    def __init__(self, services: CoreServices) -> None:
        self.db = services.db
        self.repository = services.repository

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = DetectAnomaliesArgs.model_validate(arguments)
        if self.repository.account(context.user_id, args.account_id) is None:
            raise ValueError(f"账户不存在：{args.account_id}")
        data = build_anomalies(self.db, context.user_id, args.account_id, args.period, args.month)
        return ToolResult(
            self.metadata.name,
            f"已完成 {data['month']} 账单异常检测（演示银行数据）。",
            data,
        )


class IdentifySubscriptionChargesTool(BaseTool):
    metadata = ToolMetadata(
        name="identify_subscription_charges",
        title="订阅扣费识别",
        description="按订阅类目聚合订阅实体并标记未登记代扣，只读操作。",
        risk_level=RiskLevel.GREEN,
        permission="subscription:read",
        input_schema=SubscriptionChargesArgs.model_json_schema(),
        output_schema=SubscriptionChargesOutput.model_json_schema(),
    )
    arguments_model = SubscriptionChargesArgs

    def __init__(self, services: CoreServices) -> None:
        self.db = services.db

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = SubscriptionChargesArgs.model_validate(arguments)
        data = build_subscription_charges(self.db, context.user_id, args.account_id)
        return ToolResult(
            self.metadata.name,
            "已识别订阅扣费与未登记代扣（演示银行数据）。",
            data,
        )


class ListRenewalRemindersTool(BaseTool):
    metadata = ToolMetadata(
        name="list_renewal_reminders",
        title="续费提醒",
        description="基于订阅下次扣费日生成站内续费提醒，只读操作且不含外部推送。",
        risk_level=RiskLevel.GREEN,
        permission="subscription:read",
        input_schema=RenewalRemindersArgs.model_json_schema(),
        output_schema=RenewalRemindersOutput.model_json_schema(),
    )
    arguments_model = RenewalRemindersArgs

    def __init__(self, services: CoreServices) -> None:
        self.db = services.db

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
        args = RenewalRemindersArgs.model_validate(arguments)
        data = build_renewal_reminders(self.db, context.user_id, args.cycle, args.days_ahead)
        return ToolResult(
            self.metadata.name,
            "已生成站内续费提醒（演示银行数据，不含外部推送）。",
            data,
        )


def tools(services: CoreServices) -> list[BaseTool]:
    return [
        BillReportTool(services),
        DetectBillAnomaliesTool(services),
        IdentifySubscriptionChargesTool(services),
        ListRenewalRemindersTool(services),
    ]


def _default_account(ctx: IntentContext) -> tuple[str, list[str]]:
    accounts = ctx.account_ids()
    if accounts:
        return accounts[0], []
    return DEFAULT_ACCOUNT, ["未指定账户，默认使用演示账户 ACC-1001（模拟数据）。"]


_MONTH_IN_TEXT_PATTERN = re.compile(r"(20\d{2})[-/年](\d{1,2})月?")


def _explicit_month(ctx: IntentContext) -> str | None:
    match = _MONTH_IN_TEXT_PATTERN.search(ctx.instruction)
    if match is None:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


class DetectAnomaliesIntent:
    """异常扣费 / 账单异常 → detect_bill_anomalies。"""

    name = "bills.anomalies"
    priority = 20
    _markers = (
        "异常扣费",
        "重复扣费",
        "可疑扣费",
        "账单异常",
        "异常交易",
        "可疑交易",
        "扣费异常",
        "重复扣款",
        "被多扣",
        "anomal",
    )

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("detect_bill_anomalies"):
            return None
        text = ctx.text
        if not any(marker in text for marker in self._markers):
            return None
        account_id, assumptions = _default_account(ctx)
        explicit_month = _explicit_month(ctx)
        arguments: dict[str, Any] = {"account_id": account_id}
        if explicit_month:
            arguments.update({"period": explicit_month, "month": explicit_month})
        return ExecutionPlan(
            intent="detect_bill_anomalies",
            planner="scenario:bills",
            confidence=0.9,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="detect_bill_anomalies",
                    arguments=arguments,
                    description="按确定性规则检测账单异常。",
                )
            ],
        )


class BillReportIntent:
    """账单报告 / 账单分析 / 年度账单 → bill_report。"""

    name = "bills.report"
    priority = 30
    _markers = (
        "账单报告",
        "账单分析",
        "消费报告",
        "支出报告",
        "消费分析",
        "支出分析",
        "年度账单",
        "年账单",
        "billing report",
        "bill report",
    )
    _generate_pattern = re.compile(r"(生成|出具|整理|做).{0,10}账单")

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("bill_report"):
            return None
        instruction = ctx.instruction
        text = ctx.text
        matched = any(marker in text for marker in self._markers)
        if not matched:
            matched = bool(self._generate_pattern.search(instruction))
        if not matched:
            return None
        account_id, assumptions = _default_account(ctx)
        explicit_month = _explicit_month(ctx)
        period = "month"
        month: str | None = None
        if explicit_month:
            period = explicit_month
            month = explicit_month
        elif any(marker in text for marker in ("年度", "全年", "年报", "year")):
            period = "year"
        arguments: dict[str, Any] = {"account_id": account_id, "period": period}
        if month:
            arguments["month"] = month
        return ExecutionPlan(
            intent="bill_report",
            planner="scenario:bills",
            confidence=0.9,
            assumptions=assumptions,
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="bill_report",
                    arguments=arguments,
                    description="生成账单报告（分类汇总 / Top 商户 / 环比）。",
                )
            ],
        )


class SubscriptionChargesIntent:
    """订阅扣费分析 / 识别代扣 / 自动扣费 → identify_subscription_charges。"""

    name = "bills.subscription_charges"
    priority = 40
    _markers = (
        "订阅扣费",
        "扣费分析",
        "识别代扣",
        "未登记代扣",
        "自动扣费",
        "订阅分析",
        "订阅账单",
        "代扣",
        "direct debit",
    )

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("identify_subscription_charges"):
            return None
        text = ctx.text
        if not any(marker in text for marker in self._markers):
            return None
        accounts = ctx.account_ids()
        arguments: dict[str, Any] = {}
        if accounts:
            arguments["account_id"] = accounts[0]
        return ExecutionPlan(
            intent="identify_subscription_charges",
            planner="scenario:bills",
            confidence=0.9,
            assumptions=[],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="identify_subscription_charges",
                    arguments=arguments,
                    description="聚合订阅扣费实体并标记未登记代扣。",
                )
            ],
        )


class RenewalRemindersIntent:
    """续费提醒 / 快到期订阅 / 什么时候扣费 → list_renewal_reminders。"""

    name = "bills.renewal_reminders"
    priority = 50
    _markers = (
        "续费提醒",
        "快到期",
        "什么时候扣费",
        "续费",
        "到期订阅",
        "renewal",
    )

    def build(self, ctx: IntentContext) -> ExecutionPlan | None:
        if not ctx.has_tool("list_renewal_reminders"):
            return None
        text = ctx.text
        if not any(marker in text for marker in self._markers):
            return None
        arguments: dict[str, Any] = {"days_ahead": 30}
        if any(marker in text for marker in ("每月", "月付", "monthly")):
            arguments["cycle"] = "monthly"
        elif any(marker in text for marker in ("每年", "年付", "yearly", "annual")):
            arguments["cycle"] = "yearly"
        return ExecutionPlan(
            intent="list_renewal_reminders",
            planner="scenario:bills",
            confidence=0.9,
            assumptions=[],
            steps=[
                PlanStep(
                    id="step-1",
                    tool_name="list_renewal_reminders",
                    arguments=arguments,
                    description="生成站内续费提醒列表。",
                )
            ],
        )


def intents() -> list[Any]:
    return [
        DetectAnomaliesIntent(),
        BillReportIntent(),
        SubscriptionChargesIntent(),
        RenewalRemindersIntent(),
    ]


_READ_ONLY_TOOL_NAMES = frozenset(
    {
        "bill_report",
        "detect_bill_anomalies",
        "identify_subscription_charges",
        "list_renewal_reminders",
    }
)


class BillReadOnlyRiskRule:
    """账单与订阅工具全部是只读查询，只允许保持绿色基线。"""

    name = "bills.read_only"
    priority = 10

    def assess(self, ctx: RiskContext) -> RiskGuess | None:
        if ctx.tool_name not in _READ_ONLY_TOOL_NAMES:
            return None
        return RiskGuess(
            level=RiskLevel.GREEN,
            score=10,
            reasons=["只读查询操作，仅读取模拟账单与订阅数据，不会改变资金或账户状态。"],
        )


def risk_rules() -> list[Any]:
    return [BillReadOnlyRiskRule()]


def _route_context(user_id: str, dag_path: str) -> ExecutionContext:
    return ExecutionContext(
        user_id=user_id,
        instruction="账单场景只读查询",
        run_id="api-bills",
        dag_path=dag_path,
    )


def router(services: CoreServices) -> APIRouter:
    api = APIRouter(tags=["bills"])
    report_tool = BillReportTool(services)
    anomaly_tool = DetectBillAnomaliesTool(services)
    charges_tool = IdentifySubscriptionChargesTool(services)
    reminder_tool = ListRenewalRemindersTool(services)

    @api.get("/api/bills/report")
    def bill_report_route(
        account_id: str = Query(default=DEFAULT_ACCOUNT, max_length=32),
        period: str = Query(default="month", max_length=16),
        month: str | None = Query(default=None, max_length=7),
        user_id: str = Query(default=DEMO_USER, max_length=64),
    ) -> dict[str, Any]:
        try:
            result = report_tool.execute(
                {"account_id": account_id, "period": period, "month": month},
                _route_context(user_id, "api:bills/report"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.data

    @api.get("/api/bills/anomalies")
    def bill_anomalies_route(
        account_id: str = Query(default=DEFAULT_ACCOUNT, max_length=32),
        period: str = Query(default="month", max_length=16),
        month: str | None = Query(default=None, max_length=7),
        user_id: str = Query(default=DEMO_USER, max_length=64),
    ) -> dict[str, Any]:
        try:
            result = anomaly_tool.execute(
                {"account_id": account_id, "period": period, "month": month},
                _route_context(user_id, "api:bills/anomalies"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.data

    @api.get("/api/subscriptions/charges")
    def subscription_charges_route(
        account_id: str | None = Query(default=None, max_length=32),
        user_id: str = Query(default=DEMO_USER, max_length=64),
    ) -> dict[str, Any]:
        result = charges_tool.execute(
            {"account_id": account_id},
            _route_context(user_id, "api:subscriptions/charges"),
        )
        return result.data

    @api.get("/api/subscriptions/reminders")
    def renewal_reminders_route(
        cycle: str | None = Query(default=None, max_length=16),
        days_ahead: int = Query(default=30, ge=0, le=365),
        user_id: str = Query(default=DEMO_USER, max_length=64),
    ) -> dict[str, Any]:
        result = reminder_tool.execute(
            {"cycle": cycle, "days_ahead": days_ahead},
            _route_context(user_id, "api:subscriptions/reminders"),
        )
        return result.data

    return api
