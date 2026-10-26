#!/usr/bin/env bash
# 重置演示数据并植入一张「3000 元存款的虚拟卡」（ACC-3003 / CARD-9001）。
# 用法：bash scripts/seed-demo.sh [db_path]
#   默认 db_path：backend/data/dogfood.db（与推荐启动命令一致）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${1:-$ROOT/backend/data/dogfood.db}"

echo "[seed-demo] 重置数据库：$DB_PATH"
cd "$ROOT/backend"
uv run python -m aegisbank_api.demo_seed --db "$DB_PATH" --reset

echo
echo "[seed-demo] 完成。启动后端时请指向同一个库："
echo "  cd backend && AEGIS_DATABASE_PATH=\"$DB_PATH\" \\"
echo "    uv run uvicorn aegisbank_api.main:app --host 0.0.0.0 --port 8000"
echo "[seed-demo] 然后启动前端：cd frontend && pnpm dev"
