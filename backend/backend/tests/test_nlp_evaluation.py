"""Evaluation must catch wrong amounts, references and order beyond step one."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/evaluate-nlp.py"
spec = importlib.util.spec_from_file_location("nlp_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def fixture():
    case = {
        "id": "gold",
        "family": "cross",
        "tools": ["query_bill", "cancel_subscription"],
        "checks": {"account_id": "ACC-1001"},
        "step_checks": [{}, {"subscription_id": "${steps.a.data.suspicious_subscription_id}"}],
        "depends_on": [[], [0]],
    }
    body = {
        "status": "planned",
        "plan": {
            "semantic": {"status": "verified"},
            "steps": [
                {
                    "id": "a",
                    "tool_name": "query_bill",
                    "arguments": {"account_id": "ACC-1001"},
                    "depends_on": [],
                },
                {
                    "id": "b",
                    "tool_name": "cancel_subscription",
                    "arguments": {"subscription_id": "${steps.a.data.suspicious_subscription_id}"},
                    "depends_on": ["a"],
                },
            ],
        },
    }
    return case, body


@pytest.mark.parametrize("mutation", ["object", "dependency", "legacy", "missing"])
def test_evaluation_detects_later_step_and_coverage_errors(mutation):
    case, body = fixture()
    assert evaluation.assess(case, body, 200, date(2026, 11, 1))["verified_match"]
    changed = deepcopy(body)
    if mutation == "object":
        changed["plan"]["steps"][1]["arguments"]["subscription_id"] = "SUB-OTHER"
    elif mutation == "dependency":
        changed["plan"]["steps"][1]["depends_on"] = []
    elif mutation == "legacy":
        changed["plan"]["semantic"]["status"] = "legacy"
    else:
        changed["plan"]["steps"].pop()
    result = evaluation.assess(case, changed, 200, date(2026, 11, 1))
    assert not result["verified_match"]
    if mutation != "legacy":
        assert not result["matched"]


def test_evaluation_relative_months_are_calendar_labels():
    assert evaluation.normalize_gold("@previous_month", date(2027, 1, 1)) == "2026-12"
    assert evaluation.arguments_match(
        {"run_at": "2026-11-01T16:00:00+00:00"},
        {"run_at": "@local_date:+1"},
        date(2026, 11, 1),
    )
    assert not evaluation.arguments_match(
        {"run_at": "2026-11-01T16:00:00"},
        {"run_at": "@local_date:+1"},
        date(2026, 11, 1),
    )
