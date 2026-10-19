#!/usr/bin/env bash
# Start the FastAPI API and Vite dev server together.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

(
  cd "$ROOT/backend"
  exec uv run uvicorn aegisbank_api.main:app --reload --host 0.0.0.0 --port 8000
) &
PIDS+=("$!")

(
  cd "$ROOT/frontend"
  exec pnpm dev
) &
PIDS+=("$!")

echo "API:  http://127.0.0.1:8000/docs"
echo "UI:   http://127.0.0.1:5173"
echo "Ctrl+C to stop both services."
wait
