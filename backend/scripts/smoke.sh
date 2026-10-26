#!/usr/bin/env bash
# Boot the API, exercise a green-path run, and verify the audit chain.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${TMPDIR:-/tmp}/aegisbank-smoke.log"

cleanup() {
  kill "${API_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT

(cd "$ROOT/backend" && exec uv run uvicorn aegisbank_api.main:app --host 127.0.0.1 --port 8000) >"$LOG" 2>&1 &
API_PID=$!

for _ in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo "[smoke] health"
curl -fsS http://127.0.0.1:8000/api/health
echo

echo "[smoke] planner info"
curl -fsS http://127.0.0.1:8000/api/planner/info
echo

echo "[smoke] structured plan preview (no execution)"
curl -fsS -X POST http://127.0.0.1:8000/api/planner/plan \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"向 ACC-2002 转账 880 元"}'
echo

echo "[smoke] green tool run"
curl -fsS -X POST http://127.0.0.1:8000/api/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"查询我的本月账单","tool_name":"query_bill","arguments":{"account_id":"ACC-1001"}}'
echo

echo "[smoke] audit chain"
curl -fsS http://127.0.0.1:8000/api/audit/verify
echo
