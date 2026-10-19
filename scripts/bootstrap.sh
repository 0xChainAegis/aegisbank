#!/usr/bin/env bash
# One-time local dependency bootstrap.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[bootstrap] Python dependencies"
(cd "$ROOT/backend" && uv sync --frozen)

echo "[bootstrap] Frontend dependencies"
(cd "$ROOT/frontend" && pnpm install --frozen-lockfile)

echo "[bootstrap] done. Start with: bash scripts/dev.sh"
