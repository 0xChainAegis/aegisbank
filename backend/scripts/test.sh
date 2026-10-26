#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[test] backend · pytest"
(cd "$ROOT/backend" && uv run pytest -q)

echo "[test] frontend · vitest"
(cd "$ROOT/frontend" && pnpm test)
