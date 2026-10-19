#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[lint] backend · ruff"
(cd "$ROOT/backend" && uv run ruff check aegisbank_api tests)

echo "[lint] frontend · TypeScript"
(cd "$ROOT/frontend" && pnpm typecheck)
