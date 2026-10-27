"""Compare P0 rules with P1 on the curated development corpus (no model calls)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime/backend"))
from aegisbank_api.config import Settings  # noqa: E402
from aegisbank_api.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def evaluate(corpus):
    cases = json.loads(corpus.read_text())
    report = {
        "dataset": "development regression; not held-out or real-model evaluation",
        "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "metric": "tool sequence and annotated first-step arguments; rejection for negative cases",
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
            results = []
            with TestClient(app) as client:
                for case in cases:
                    response = client.post(
                        "/api/planner/plan", json={"instruction": case["instruction"]}
                    )
                    body = response.json()
                    if response.status_code != 200:
                        results.append(
                            {
                                "id": case["id"],
                                "family": case["family"],
                                "matched": False,
                                "http_status": response.status_code,
                                "status": "error",
                                "tools": [],
                            }
                        )
                        continue
                    steps = (body.get("plan") or {}).get("steps", [])
                    actual = [s["tool_name"] for s in steps]
                    matched = (
                        (
                            body["status"] == "planned"
                            and actual == case["tools"]
                            and all(
                                steps[0]["arguments"].get(k) == v for k, v in case["checks"].items()
                            )
                        )
                        if case["tools"]
                        else (body["status"] in {"needs_clarification", "blocked"} and not steps)
                    )
                    results.append(
                        {
                            "id": case["id"],
                            "family": case["family"],
                            "matched": matched,
                            "status": body["status"],
                            "tools": actual,
                            "semantic_status": (body.get("plan") or {})
                            .get("semantic", {})
                            .get("status")
                            if (body.get("plan") or {}).get("semantic")
                            else None,
                        }
                    )
            report["modes"][mode] = {
                "matched": sum(r["matched"] for r in results),
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
    args = parser.parse_args()
    report = evaluate(args.corpus)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(json.dumps({k: v["matched"] for k, v in report["modes"].items()}))
    sys.exit(0 if report["modes"]["p1_semantics"]["matched"] == report["cases"] else 1)
