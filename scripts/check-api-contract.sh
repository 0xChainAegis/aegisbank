#!/usr/bin/env bash
# Assemble the six modules, then verify every frontend /api path exists in
# the backend OpenAPI document.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/scripts/assemble.py"
cd "$ROOT/.runtime/backend"
exec uv run --frozen python "$ROOT/scripts/check_api_contract.py"