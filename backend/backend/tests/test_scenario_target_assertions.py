"""The scenario gate must prove its target transferred, not count other gifts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from aegisbank_api.main import create_app


def load_scenario_check():
    test_file = Path(__file__).resolve()
    candidates = [
        test_file.parents[2] / "scripts" / "scenario-check.py",
        test_file.parents[3] / "backend" / "scripts" / "scenario-check.py",
    ]
    script = next(path for path in candidates if path.exists())
    spec = importlib.util.spec_from_file_location("scenario_target_regression", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_other_successful_gifts_cannot_hide_target_awaiting_reauth():
    module = load_scenario_check()
    ok, detail = module.fast_forward_result(
        200,
        {
            "executed_count": 2,
            "failed_count": 0,
            "pending_reauth_count": 1,
            "executed": [
                {"task_id": "GIFT-1", "kind": "gift", "status": "executed"},
                {"task_id": "GIFT-2", "kind": "gift", "status": "executed"},
            ],
            "pending_reauth": [{"task_id": "TARGET", "execution_status": "needs_reauth"}],
        },
        target_task_id="TARGET",
    )
    assert ok is False
    assert "TARGET" in detail and "pending_reauth=1" in detail


def test_unrelated_executed_transfer_cannot_replace_the_target():
    module = load_scenario_check()
    ok, detail = module.fast_forward_result(
        200,
        {
            "executed_count": 1,
            "failed_count": 0,
            "pending_reauth_count": 0,
            "executed": [{"task_id": "OTHER", "kind": "transfer", "status": "executed"}],
        },
        target_task_id="TARGET",
    )
    assert ok is False
    assert "TARGET" in detail


def test_cross_scenario_gate_proves_task_state_and_actual_balance(tmp_path):
    module = load_scenario_check()
    with TestClient(create_app(database_path=tmp_path / "cross-target.db")) as client:
        module.scenario_cross(module.Agent(client))
    target_check = next(item for item in module.RESULTS if item[1] == "时间快进执行到期任务")
    assert target_check[2] is True, module.RESULTS
    assert "target_done=True balance_ok=True" in target_check[3]


def test_cross_scenario_gate_fails_when_real_target_needs_reauth(tmp_path):
    module = load_scenario_check()

    class EscalateAfterScheduling(module.Agent):
        def run_and_complete(self, instruction, **extra):
            original = super().run_and_complete(instruction, **extra)
            if instruction == "下周三给张三转 500":
                # A real transfer after mandate approval raises the due risk.
                _, transfer = super().run_and_complete("向 ACC-2002 转账 600 元")
                assert transfer["status"] == "completed", transfer
            return original

    with TestClient(create_app(database_path=tmp_path / "cross-target-reauth.db")) as client:
        module.scenario_cross(EscalateAfterScheduling(client))
    target_check = next(item for item in module.RESULTS if item[1] == "时间快进执行到期任务")
    assert target_check[2] is False, module.RESULTS
    assert "pending_reauth=1" in target_check[3]
    assert "balance_ok=False" in target_check[3]


def test_expected_reauth_is_a_separate_safety_check(tmp_path):
    module = load_scenario_check()
    with TestClient(create_app(database_path=tmp_path / "expected-reauth.db")) as client:
        module.scenario_schedule_reauth(module.Agent(client))
    assert len(module.RESULTS) == 1
    assert module.RESULTS[0][0] == "定时/安全"
    assert module.RESULTS[0][2] is True, module.RESULTS
