#!/usr/bin/env bash
# Run from any directory: bash /path/to/aegisbank/start.sh
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo '[AegisBank] 请先安装 Python 3.11+，再执行 bash start.sh。' >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/scripts/start.py" "$@"
