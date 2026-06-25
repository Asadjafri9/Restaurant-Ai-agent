#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.." || exit 1
export SERVICE_MODE=admin
echo "[admin] Running central migrations..."
python -m alembic -c migrations/central/alembic.ini upgrade head || echo "Migration warning (continuing)"
echo "[admin] Seeding admin account..."
PYTHONPATH=. python scripts/seed_admin.py || echo "Seed warning (continuing)"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
