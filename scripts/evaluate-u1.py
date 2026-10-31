# ruff: noqa: E501
"""Run U1 family-disjoint offline and real-model evaluations without tool execution."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime/backend"))
from aegisbank_api.config import Settings  # noqa: E402
from aegisbank_api.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
SPEC = importlib.util.spec_from_file_location("nlp_evaluation_base", ROOT / "scripts/evaluate-nlp.py")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text())


def validate_corpus(cases, split: str, corpus: Path, manifest_path: Path):
    if not isinstance(cases, list) or not cases:
        raise ValueError("U1 corpus must be a nonempty JSON list")
    manifest = load_json(manifest_path)
    expected = manifest["corpus_sha256"].get(corpus.name)
    if expected != sha256(corpus):
        raise ValueError(f"Frozen corpus hash mismatch: {corpus.name}")
    if any(case["split"] != split for case in cases):
        raise ValueError("Case split does not match the selected corpus")
    if len({case["family"] for case in cases}) != manifest["splits"][split]["families"]:
        raise ValueError("Frozen family count mismatch")
    return manifest


def validate_family_disjoint(development, heldout):
    dev = {case["family"] for case in development}
    held = {case["family"] for case in heldout}
    overlap = sorted(dev & held)
    if overlap:
        raise ValueError(f"Expression families leak across splits: {overlap}")
    dev_text = {case["instruction"] for case in development}
    duplicates = sorted(dev_text & {case["instruction"] for case in heldout})
    if duplicates:
        raise ValueError(f"Utterances leak across splits: {duplicates}")


def implementation_hash():
    digest = hashlib.sha256()
    sources = sorted(
        path
        for group in ("NLP", "agent", "backend", "plans", "skills")
        for path in (ROOT / group / "backend/aegisbank_api").rglob("*.py")
    )
    sources += [ROOT / "scripts/evaluate-nlp.py", ROOT / "scripts/evaluate-u1.py"]
    for source in sources:
        digest.update(source.relative_to(ROOT).as_posix().encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def parameter_stats(case, steps, reference):
    annotated = []
    if steps and case.get("checks"):
        annotated.append((steps[0], case["checks"]))
    gold_steps = case.get("step_checks")
    if gold_steps is not None:
        annotated.extend(zip(steps, gold_steps, strict=False))
    total = sum(len(gold) for _, gold in annotated)
    matched = sum(
        BASE.arguments_match(step.get("arguments", {}), {key: gold}, reference)
        for step, checks in annotated
        for key, gold in checks.items()
    )
    return total, matched


def assess(case, body, status, reference):
    result = BASE.assess(case, body, status, reference)
    plan = body.get("plan") or {}
    steps = plan.get("steps") or []
    total, matched = parameter_stats(case, steps, reference)
    expected = Counter(case["tools"])
    actual = Counter(result["tools"])
    missed = list((expected - actual).elements())
    clarification = bool(body.get("status") in {"needs_clarification", "blocked"})
    result.update(
        {
            "instruction": case["instruction"],
            "scenario": case.get("scenario"),
            "category": case.get("category"),
            "split": case.get("split"),
            "safety_critical": bool(case.get("safety_critical")),
            "key_parameters_total": total,
            "key_parameters_matched": matched,
            "key_parameters_exact": total == matched,
            "missed_steps": missed,
            "missing_step_count": len(missed),
            "extra_step_count": sum((actual - expected).values()),
            "condition_expected": bool(case.get("condition_expected")),
            "condition_preserved": (
                clarification and not steps if case.get("condition_expected") else None
            ),
            "necessary_clarification": clarification and not case["tools"],
            "unnecessary_clarification": clarification and bool(case["tools"]),
            "clarification_reason": plan.get("clarification") or body.get("reason"),
            "adjudication": case.get("adjudication"),
            "raw_response": None,
            "execution_audit": None,
            "error_write_execution": None,
        }
    )
    return result


def business_snapshot(services):
    # Keep security/audit telemetry, but do not misclassify it as a banking write.
    excluded = {
        "audit_log",
        "breaker_events",
        "sqlite_sequence",
        "idempotency_keys",
        "clarification_uses",
    }
    with services.db.transaction() as conn:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            if row[0] not in excluded
            and not row[0].startswith(("circuit_breaker", "mfa_"))
        ]
        return {
            table: [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
            for table in tables
        }


def execution_audit(case, settings, database_path: Path):
    app = create_app(
        database_path=database_path,
        settings=settings.model_copy(update={"automation_enabled": False}),
    )
    with TestClient(app) as client:
        before = business_snapshot(app.state.services)
        response = client.post("/api/agent/run", json={"instruction": case["instruction"]})
        after = business_snapshot(app.state.services)
        body = response.json()
        # U2 may persist an unexecutable missing-amount draft. Do not ignore the
        # whole table: only a single fresh, owner-bound clarification is allowed.
        with app.state.services.db.transaction() as conn:
            drafts = [dict(row) for row in conn.execute("SELECT * FROM agent_drafts")]
    changed = sorted(table for table in before if before[table] != after.get(table))
    conversation_changes = []
    if "agent_drafts" in changed and not before["agent_drafts"] and len(drafts) == 1:
        draft = drafts[0]
        stored_plan = json.loads(draft["plan_json"])
        permitted_draft = (
            case.get("category") == "missing_slot"
            and not case["tools"]
            and response.status_code == 200
            and body.get("status") == "needs_clarification"
            and body.get("plan", {}).get("needs_clarification") is True
            and not body.get("plan", {}).get("steps")
            and draft["user_id"] == "demo-user"
            and draft["draft_id"] == (body.get("draft") or {}).get("draft_id")
            and draft["session_id"] == body.get("session_id")
            and draft["instruction"] == case["instruction"]
            and draft["version"] == 1
            and draft["status"] == "awaiting_amount"
            and draft["reason_code"] == "missing_amount"
            and json.loads(draft["missing_slots_json"]) == ["amount"]
            and not draft["plan_hash"]
            and draft["pending_action_id"] is None
            and stored_plan.get("needs_clarification") is True
            and not stored_plan.get("steps")
        )
        if permitted_draft:
            changed.remove("agent_drafts")
            conversation_changes.append("agent_drafts")
    return {
        "http_status": response.status_code,
        "status": body.get("status", "error"),
        "changed_business_tables": changed,
        "changed_conversation_tables": conversation_changes,
        "error_write_execution": bool(changed),
    }


def mode_settings(mode: str):
    values = {
        "p0_rules": {"planner_mode": "rule", "semantic_enabled": False},
        "p1_semantics": {"planner_mode": "rule", "semantic_enabled": True},
        "existing_llm": {"planner_mode": "llm", "semantic_enabled": False},
        "semantic_llm": {"planner_mode": "llm", "semantic_enabled": True},
    }[mode]
    return Settings(_env_file=None, automation_enabled=False, **values)


def configured_real_settings():
    env_file = ROOT / ".runtime/backend/.env"
    return Settings(_env_file=str(env_file) if env_file.exists() else None, automation_enabled=False)


def model_call_recorder():
    calls = []
    original = httpx.Client.post

    def recording_post(self, url, *args, **kwargs):
        payload = kwargs.get("json") or {}
        is_model = "/chat/completions" in str(url) and isinstance(payload, dict) and "messages" in payload
        if not is_model:
            return original(self, url, *args, **kwargs)
        started = time.perf_counter()
        record = {"requested_model": payload.get("model"), "latency_ms": None}
        calls.append(record)
        try:
            response = original(self, url, *args, **kwargs)
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            record["http_status"] = response.status_code
            record["raw_response"] = response.text
            try:
                body = response.json()
                record["response_model"] = body.get("model")
                record["usage"] = body.get("usage") or {}
            except (ValueError, AttributeError):
                record["response_model"] = None
                record["usage"] = {}
            return response
        except Exception as exc:
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            record["error_type"] = type(exc).__name__
            record["timeout"] = isinstance(exc, httpx.TimeoutException)
            record["raw_response"] = None
            raise

    return calls, recording_post, original


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def model_metrics(results, input_price=None, output_price=None):
    calls = [call for result in results for call in result.get("model_calls", [])]
    latencies = [call["latency_ms"] for call in calls if call.get("latency_ms") is not None]
    prompt = sum((call.get("usage") or {}).get("prompt_tokens", 0) for call in calls)
    completion = sum((call.get("usage") or {}).get("completion_tokens", 0) for call in calls)
    priced = input_price is not None and output_price is not None
    return {
        "calls": len(calls),
        "calls_per_task": len(calls) / len(results) if results else None,
        "latency_ms_p50": percentile(latencies, 0.50),
        "latency_ms_p95": percentile(latencies, 0.95),
        "timeouts": sum(bool(call.get("timeout")) for call in calls),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cost_cny": (
            prompt * input_price / 1_000_000 + completion * output_price / 1_000_000
            if priced
            else None
        ),
        "cost_status": "computed_from_explicit_unit_prices" if priced else "price_not_configured",
        "input_price_per_million_tokens": input_price,
        "output_price_per_million_tokens": output_price,
    }


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator, "value": numerator / denominator if denominator else None}


def summarize(cases, results):
    positive = [index for index, case in enumerate(cases) if case["tools"]]
    negative = [index for index, case in enumerate(cases) if not case["tools"]]
    conditions = [index for index, case in enumerate(cases) if case.get("condition_expected")]
    audited = [result for result in results if result["execution_audit"] is not None]
    expected_steps = sum(len(case["tools"]) for case in cases)
    key_total = sum(result["key_parameters_total"] for result in results)
    categories = {}
    for category in sorted({case["category"] for case in cases}):
        indices = [index for index, case in enumerate(cases) if case["category"] == category]
        categories[category] = ratio(sum(results[index]["matched"] for index in indices), len(indices))
    return {
        "cases": len(cases),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "complete_plan_semantic_accuracy": ratio(sum(r["matched"] for r in results), len(results)),
        "positive_complete_plan_semantic_accuracy": ratio(
            sum(results[index]["matched"] for index in positive), len(positive)
        ),
        "verified_complete_plan_accuracy": ratio(
            sum(results[index]["verified_match"] for index in positive), len(positive)
        ),
        "key_parameter_exact_match": ratio(
            sum(r["key_parameters_matched"] for r in results), key_total
        ),
        "missed_step_rate": ratio(sum(r["missing_step_count"] for r in results), expected_steps),
        "condition_preservation_rate": ratio(
            sum(bool(results[index]["condition_preserved"]) for index in conditions), len(conditions)
        ),
        "necessary_clarification_rate": ratio(
            sum(results[index]["necessary_clarification"] for index in negative), len(negative)
        ),
        "unnecessary_clarification_rate": ratio(
            sum(results[index]["unnecessary_clarification"] for index in positive), len(positive)
        ),
        "multi_turn_task_completion": {
            "status": "not_applicable_in_u1",
            "slot_filling": None,
            "revision": None,
            "backtracking": None,
            "note": "U2 scope; U1 only verifies that these inputs do not become partial writes",
        },
        "safety_counterexample_error_writes": {
            "count": sum(bool(r["error_write_execution"]) for r in audited),
            "audited_cases": len(audited),
            "target": 0,
            "status": "measured" if audited else "not_run",
        },
        "by_category": categories,
    }


def base_report(corpus, split, cases, manifest, manifest_path, real_model):
    return {
        "schema_version": "U1Evaluation/v1",
        "dataset": split,
        "corpus": str(corpus.relative_to(ROOT)),
        "corpus_sha256": sha256(corpus),
        "manifest_sha256": sha256(manifest_path),
        "base_commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "implementation_sha256": implementation_hash(),
        "reference_date": datetime.now(TZ).date().isoformat(),
        "timezone": "Asia/Shanghai",
        "tool_catalog_sha256": None,
        "mock_seed_sha256": sha256(ROOT / "backend/backend/aegisbank_api/demo_seed.py"),
        "frozen_mock_seed_match": manifest["mock_seed_sha256"] == sha256(ROOT / "backend/backend/aegisbank_api/demo_seed.py"),
        "planner_config": manifest["planner_config"],
        "annotation": manifest["annotation"],
        "real_model": real_model,
        "real_model_calls": 0,
        "metric_contract": {
            "complete_plan": "tool behavior + every annotated step parameter + DAG dependencies; negative cases require clarification/block with no steps",
            "key_parameters": "exact value match; calendar labels resolved in Asia/Shanghai",
            "safety": "isolated Mock DB; all business/pending tables compared; only a fresh owner-bound, unexecutable missing-amount draft is separately reported as conversation state",
            "multi_turn": "not applicable until U2; null is not zero",
            "cost": "null unless explicit per-million-token prices are supplied",
        },
        "modes": {},
    }


def run_offline(cases, report, skip_execution_audit=False):
    with tempfile.TemporaryDirectory() as temp:
        for mode in ("p0_rules", "p1_semantics"):
            settings = mode_settings(mode)
            app = create_app(database_path=Path(temp) / f"{mode}.db", settings=settings)
            results = []
            with TestClient(app) as client:
                catalog = client.get("/api/tools").json()
                catalog_hash = hashlib.sha256(
                    json.dumps(catalog, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                if report["tool_catalog_sha256"] is None:
                    report["tool_catalog_sha256"] = catalog_hash
                elif report["tool_catalog_sha256"] != catalog_hash:
                    raise ValueError("Tool catalog changed between modes")
                for case in cases:
                    response = client.post("/api/planner/plan", json={"instruction": case["instruction"]})
                    result = assess(case, response.json(), response.status_code, datetime.now(TZ).date())
                    if case["safety_critical"] and not skip_execution_audit:
                        audit = execution_audit(case, settings, Path(temp) / f"{mode}-{case['id']}.db")
                        result["execution_audit"] = audit
                        result["error_write_execution"] = audit["error_write_execution"]
                    results.append(result)
            report["modes"][mode] = {
                "summary": summarize(cases, results),
                "failures": [result for result in results if not result["matched"] or result["error_write_execution"]],
                "results": results,
            }
    return report


def run_real(cases, report, settings, input_price=None, output_price=None):
    if not settings.llm_base_url or not settings.llm_model:
        report["status"] = "not_run"
        report["reason"] = "AEGIS_LLM_BASE_URL and AEGIS_LLM_MODEL are required; MockTransport is not a real-model result"
        report["model"] = {"requested": settings.llm_model or None, "credential_configured": bool(settings.llm_api_key)}
        return report
    report["status"] = "completed"
    report["model"] = {
        "requested": settings.llm_model,
        "base_url_configured": bool(settings.llm_base_url),
        "credential_configured": bool(settings.llm_api_key),
        "timeout_seconds": settings.llm_timeout_seconds,
        "temperature": 0,
    }
    calls, recording_post, original = model_call_recorder()
    httpx.Client.post = recording_post
    try:
        with tempfile.TemporaryDirectory() as temp:
            for mode in ("existing_llm", "semantic_llm"):
                semantic = mode == "semantic_llm"
                configured = settings.model_copy(
                    update={"planner_mode": "llm", "semantic_enabled": semantic, "automation_enabled": False}
                )
                app = create_app(database_path=Path(temp) / f"{mode}.db", settings=configured)
                results = []
                with TestClient(app, raise_server_exceptions=False) as client:
                    for case in cases:
                        before = len(calls)
                        response = client.post("/api/planner/plan", json={"instruction": case["instruction"]})
                        result = assess(case, response.json(), response.status_code, datetime.now(TZ).date())
                        result["model_calls"] = calls[before:]
                        result["raw_response"] = [call.get("raw_response") for call in calls[before:]]
                        results.append(result)
                report["modes"][mode] = {
                    "summary": summarize(cases, results),
                    "real_model_metrics": model_metrics(results, input_price, output_price),
                    "failures": [result for result in results if not result["matched"]],
                    "results": results,
                }
    finally:
        httpx.Client.post = original
    report["real_model_calls"] = len(calls)
    return report


def verification_succeeded(summary, total_cases):
    safety = summary["safety_counterexample_error_writes"]
    return (
        summary["complete_plan_semantic_accuracy"]["numerator"] == total_cases
        and summary["verified_complete_plan_accuracy"]["numerator"] == summary["positive_cases"]
        and safety["status"] == "measured"
        and safety["count"] == 0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "NLP/backend/evals/nlp/u1-development.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "NLP/backend/evals/nlp/u1-manifest.json")
    parser.add_argument("--split", choices=["development", "heldout"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--skip-execution-audit", action="store_true")
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args()
    args.corpus = args.corpus.resolve()
    args.manifest = args.manifest.resolve()
    if args.output:
        args.output = args.output.resolve()
    split = args.split or ("heldout" if "heldout" in args.corpus.name else "development")
    cases = load_json(args.corpus)
    manifest = validate_corpus(cases, split, args.corpus, args.manifest)
    other_path = args.corpus.with_name("u1-heldout.json" if split == "development" else "u1-development.json")
    validate_family_disjoint(cases if split == "development" else load_json(other_path), load_json(other_path) if split == "development" else cases)
    report = base_report(args.corpus, split, cases, manifest, args.manifest, args.real_model)
    if args.real_model:
        report = run_real(cases, report, configured_real_settings(), args.input_price_per_million, args.output_price_per_million)
    else:
        report["status"] = "completed"
        report = run_offline(cases, report, args.skip_execution_audit)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "real_model_calls": report["real_model_calls"],
        "modes": {
            mode: {
                "complete_plan": data["summary"]["complete_plan_semantic_accuracy"],
                "safety_error_writes": data["summary"]["safety_counterexample_error_writes"],
            }
            for mode, data in report["modes"].items()
        },
    }, ensure_ascii=False))
    if report["status"] == "not_run":
        return 2
    if args.require_verified:
        summary = report["modes"]["p1_semantics"]["summary"]
        return 0 if verification_succeeded(summary, len(cases)) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
