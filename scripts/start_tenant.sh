#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.." || exit 1
# SERVICE_MODE must be kfc or kababjees (set by Railway per service)
echo "[${SERVICE_MODE}] Running tenant migrations..."
export TENANT_DATABASE_URL="${TENANT_DATABASE_URL:-$DATABASE_URL}"
python -m alembic -c migrations/tenant/alembic.ini upgrade head || echo "Migration warning (continuing)"
echo "[${SERVICE_MODE}] Seeding tenant data..."
PYTHONPATH=. python scripts/seed_tenant.py || echo "Seed warning (continuing)"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
