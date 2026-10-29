"""Reproduce bounded P1 planning metrics without any real model/tool execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime/backend"))
from aegisbank_api.config import Settings  # noqa: E402
from aegisbank_api.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")


def normalize_gold(value, reference):
    """Only explicitly documented relative labels; never take gold from model output."""
    if value == "@current_month":
        return reference.strftime("%Y-%m")
    if value == "@previous_month":
        return (reference.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    return value


def arguments_match(actual, expected, reference):
    for key, gold in expected.items():
        value = actual.get(key)
        if isinstance(gold, str) and gold.startswith("@local_date:"):
            try:
                moment = datetime.fromisoformat(str(value))
                if moment.tzinfo is None or moment.astimezone(TZ).date() != (
                    reference + timedelta(days=int(gold.split(":", 1)[1]))
                ):
                    return False
            except (ValueError, TypeError):
                return False
        elif value != normalize_gold(gold, reference):
            return False
    return True


def assess(case, body, http_status, reference):
    plan = body.get("plan") or {}
    steps = plan.get("steps") or []
    actual_tools = [s["tool_name"] for s in steps]
    positive = bool(case["tools"])
    tools_match = actual_tools == case["tools"]
    args_match = not positive or (
        bool(steps)
        and arguments_match(
            steps[0]["arguments"],
            case.get("checks", {}),
            reference,
        )
    )
    gold_steps = case.get("step_checks")
    if gold_steps is not None:
        args_match = (
            args_match
            and len(steps) == len(gold_steps)
            and all(
                arguments_match(step["arguments"], gold, reference)
                for step, gold in zip(steps, gold_steps, strict=False)
            )
        )
    deps_match = True
    if "depends_on" in case:
        ids = [s["id"] for s in steps]
        deps_match = len(ids) == len(case["depends_on"]) and all(
            step.get("depends_on", []) == [ids[i] for i in indices]
            for step, indices in zip(steps, case["depends_on"], strict=False)
        )
    semantic = (plan.get("semantic") or {}).get("status")
    verified = semantic == "verified"
    correct = http_status == 200 and (
        body.get("status") == "planned" and tools_match and args_match and deps_match
        if positive
        else body.get("status") in {"needs_clarification", "blocked"} and not steps
    )
    return {
        "id": case["id"],
        "family": case["family"],
        "matched": correct,
        "verified_match": correct and (verified or not positive),
        "http_status": http_status,
        "status": body.get("status", "error"),
        "tool_sequence_match": tools_match,
        "annotated_arguments_match": args_match,
        "dependencies_match": deps_match,
        "semantic_status": semantic,
        "tools": actual_tools,
        "arguments": [s["arguments"] for s in steps],
        "depends_on": [s.get("depends_on", []) for s in steps],
    }


def evaluate(corpus, dataset):
    cases = json.loads(corpus.read_text())
    reference = datetime.now(TZ).date()
    sources = sorted(
        p
        for group in ("NLP", "agent", "backend", "plans", "skills")
        for p in (ROOT / group / "backend/aegisbank_api").rglob("*.py")
    )
    implementation = hashlib.sha256()
    for source in sources:
        implementation.update(source.relative_to(ROOT).as_posix().encode())
        implementation.update(source.read_bytes())
    report = {
        "schema_version": "NlpEvaluation/v2",
        "dataset": dataset,
        "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "base_commit": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
        "implementation_sha256": implementation.hexdigest(),
        "reference_date": reference.isoformat(),
        "timezone": "Asia/Shanghai",
        "mock_seed": "unmodified create_app demo seed; isolated temporary DB per mode",
        "metric": "tool sequence + all annotated step parameters + annotated dependencies; "
        "negative cases must clarify/block with no steps; verified coverage separate",
        "real_model_calls": 0,
        "cases": len(cases),
        "positive_cases": sum(bool(c["tools"]) for c in cases),
        "negative_cases": sum(not c["tools"] for c in cases),
        "modes": {},
    }
    with tempfile.TemporaryDirectory() as temp:
        for mode, enabled in [("p0_rules", False), ("p1_semantics", True)]:
            app = create_app(
                database_path=Path(temp) / (mode + ".db"),
                settings=Settings(
                    _env_file=None,
                    planner_mode="rule",
                    semantic_enabled=enabled,
                ),
            )
            with TestClient(app) as client:
                catalog = client.get("/api/tools").json()
                report["tool_catalog_sha256"] = hashlib.sha256(
                    json.dumps(
                        catalog,
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                results = []
                for case in cases:
                    response = client.post(
                        "/api/planner/plan",
                        json={
                            "instruction": case["instruction"],
                        },
                    )
                    results.append(assess(case, response.json(), response.status_code, reference))
            report["modes"][mode] = {
                "matched": sum(r["matched"] for r in results),
                "verified_matched": sum(r["verified_match"] for r in results),
                "positive_matched": sum(
                    r["matched"] for c, r in zip(cases, results, strict=True) if c["tools"]
                ),
                "negative_matched": sum(
                    r["matched"] for c, r in zip(cases, results, strict=True) if not c["tools"]
                ),
                "results": results,
            }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--corpus", type=Path, default=ROOT / "NLP/backend/evals/nlp/p1-regression.json"
    )
    parser.add_argument("--dataset", default="development regression, not held-out")
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.corpus, args.dataset)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: {m: v[m] for m in ("matched", "verified_matched")}
                for k, v in report["modes"].items()
            }
        )
    )
    metric = "verified_matched" if args.require_verified else "matched"
    sys.exit(0 if report["modes"]["p1_semantics"][metric] == report["cases"] else 1)
