#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/scripts/assemble.py"
APP="$ROOT/.runtime"
(cd "$APP/backend" && uv sync --frozen --quiet)
(cd "$APP/frontend" && pnpm install --frozen-lockfile --prefer-offline --silent)
case "${1:-test}" in
  lint)
    python3 "$ROOT/scripts/update_manifests.py" --check
    bash "$APP/scripts/lint.sh"
    "$APP/backend/.venv/bin/ruff" check --config "$ROOT/backend/backend/pyproject.toml" \
      "$ROOT/scripts/evaluate-nlp.py" \
      "$ROOT/scripts/build-u1-corpus.py" \
      "$ROOT/scripts/evaluate-u1.py"
    (cd "$APP/backend" && uv run python "$ROOT/scripts/check_api_contract.py")
    ;;
  build) bash "$APP/scripts/build.sh" ;;
  test)
    (cd "$ROOT" && python3 -m unittest discover -s tests -v)
    bash "$APP/scripts/test.sh"
    ;;
  scenarios) (cd "$APP/backend" && uv run python ../scripts/scenario-check.py) ;;
  *) echo 'Usage: check.sh lint|build|test|scenarios' >&2; exit 2 ;;
esac
