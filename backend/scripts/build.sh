#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[build] backend · compileall"
(cd "$ROOT/backend" && uv run python -m compileall -q aegisbank_api)

echo "[build] frontend · Vite production bundle"
(cd "$ROOT/frontend" && pnpm build)
