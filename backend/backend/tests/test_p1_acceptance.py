"""Reviewed development corpus: source slots and complete annotated DAGs."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from aegisbank_api.config import Settings
from aegisbank_api.main import create_app

BASE = Path(__file__).resolve().parents[1] / "evals/nlp"
CASES = [
    case
    for name in ["p1-acceptance-dev.json", "p1-reviewed-probes.json"]
    for case in json.loads((BASE / name).read_text())
]
SCRIPT = Path(__file__).resolve().parents[3] / "scripts/evaluate-nlp.py"
spec = importlib.util.spec_from_file_location("evaluation_acceptance", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_reviewed_acceptance_corpus_has_verified_plan_or_no_writes(tmp_path, case):
    app = create_app(database_path=tmp_path / "acceptance.db", settings=Settings(_env_file=None))
    with TestClient(app) as client:
        response = client.post("/api/planner/plan", json={"instruction": case["instruction"]})
        assert response.status_code == 200, response.text
        body = response.json()
        assessment = evaluation.assess(
            case,
            body,
            response.status_code,
            datetime.now(ZoneInfo("Asia/Shanghai")).date(),
        )
        assert assessment["verified_match"], (case, body, assessment)
        if case["tools"]:
            for item in body["plan"]["semantic"]["slots"]:
                assert item["verified"]
                span = item["span"]
                if span:
                    assert case["instruction"][span["start"] : span["end"]] == span["text"]
        else:
            before = app.state.services.repository.overview("demo-user").model_dump()
            run = client.post("/api/agent/run", json={"instruction": case["instruction"]})
            assert run.status_code == 200, run.text
            assert run.json()["status"] in {"needs_clarification", "blocked"}
            assert app.state.services.repository.overview("demo-user").model_dump() == before
            with app.state.services.db.transaction() as conn:
                assert conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0
