#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.." || exit 1
echo "[agent] Running central migrations..."
python -m alembic -c migrations/central/alembic.ini upgrade head || echo "Migration warning (continuing)"
echo "[agent] Seeding central registry..."
PYTHONPATH=. python scripts/seed.py || echo "Seed warning (continuing)"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
