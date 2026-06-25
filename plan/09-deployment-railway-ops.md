# Phase 09 — Deployment & Operations (Railway)

Target platform: **Railway**. The current `Procfile`
(`web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`) is the starting point.

## 9.1 Railway service topology

```mermaid
flowchart TB
    subgraph Railway Project
      WEB[Service: api-web  (FastAPI/uvicorn)]
      WORKER[Service: worker  (background tasks)]
      FE[Service: frontend  (React static / Nginx or Vite preview)]
      PG[(Plugin: PostgreSQL  -> central + tenant DBs)]
      REDIS[(Plugin: Redis)]
    end
    Meta[Meta WhatsApp] --> WEB
    Browser[Admin/Tenant browsers] --> FE
    FE --> WEB
    WEB --> PG
    WEB --> REDIS
    WORKER --> PG
    WORKER --> REDIS
```

Services:
- **`api-web`** — FastAPI (webhook + API + WebSocket). Scales horizontally (replicas).
- **`worker`** — consumes Redis tasks: webhook processing, WhatsApp send retries,
  menu outbox sync, status notifications, rollup refresh, reconciliation.
  (Procfile-style `worker:` process or a second Railway service.)
- **`frontend`** — built React app served as static files (or a small Nginx). Could
  also be hosted on a static host/CDN; Railway works for v1.
- **PostgreSQL plugin** — hosts the central DB and (initially) all tenant databases
  in one cluster (separate DBs + roles). See cost ladder below.
- **Redis plugin** — cache, pub/sub, sessions, rate limiting, task queue.

> Procfile evolution:
> ```
> web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
> worker: python -m app.worker
> release: alembic -c migrations/central/alembic.ini upgrade head
> ```
> The `release` phase runs central migrations on deploy; tenant migrations run via an
> explicit "migrate all tenants" job (P02 §2.4) to control rollout.

## 9.2 Environment variables (Railway)

Central/shared:
`DATABASE_URL_CENTRAL`, `REDIS_URL`, `JWT_SECRET`, `JWT_ALG`, `FERNET_KEY`,
`ALLOWED_ORIGINS`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `GEMINI_API_KEY`, `GEMINI_MODEL`,
`TENANT_DB_HOST`, `TENANT_DB_PORT`, `TENANT_DB_ADMIN_URL` (for provisioning).

Update `.env.example` to include all of the above (currently only has 4 keys). Never
commit real values; Railway injects them.

## 9.3 Multi-tenant DB cost/scaling ladder

Because per-tenant *services* are costly, scale isolation with growth:

1. **v1 (cheap):** one Railway Postgres plugin → central DB + N tenant DBs (separate
   databases + roles) in the same cluster. Strong logical+credential isolation; no
   cross-DB access configured. Good to dozens of tenants.
2. **Growth:** move the heaviest tenants to their own Railway Postgres service; the
   registry just stores a different host/connection — **no app code change**.
3. **Scale:** managed Postgres (e.g., dedicated instances/regions) for premium
   tenants; same registry mechanism. Optional read replicas for analytics.

This honors "separate DB per tenant" from day one while staying affordable on Railway.

## 9.4 CI/CD

- **GitHub → Railway** auto-deploy on `main`. PRs deploy to a staging environment.
- **CI pipeline (GitHub Actions):**
  1. Lint (ruff) + type-check (mypy) + format check.
  2. Unit + integration tests (including **isolation tests**, P10).
  3. Security: `pip-audit`, `npm audit`, secret scan.
  4. Build frontend; build/verify backend.
  5. On merge: run `release` migrations (central), then guarded "migrate tenants" job.
- **Migration safety:** expand/contract pattern; never destructive in a single deploy.
- **Rollback:** Railway redeploy previous build; DB changes are backward compatible so
  rollback is safe.

## 9.5 Observability

- **Structured logging** (JSON) with `request_id`, `tenant_id` (never secrets/PII);
  centralized via Railway logs or an external sink (e.g., Logtail/Datadog).
- **Metrics:** request latency, error rate, agent latency p50/p95, WhatsApp send
  success, order-create rate, WS connections, pool usage, per-tenant order volume.
  Expose `/metrics` (Prometheus) or push to a provider.
- **Health checks:** `GET /` (exists) + `GET /health` (DB, Redis, WhatsApp token,
  migration drift). Railway healthcheck pings it.
- **Alerting:** error-rate spike, agent latency SLO breach, webhook signature failures
  surge, LLM/WhatsApp cost thresholds, tenant migration drift, pool exhaustion.
- **Tracing (optional):** OpenTelemetry around webhook → agent → routing → DB.

## 9.6 Backups & disaster recovery

- **Per-database backups:** automated daily `pg_dump` per tenant DB + central DB
  (Railway backups and/or a scheduled worker pushing dumps to object storage).
- **Point-in-time** where the plan supports it. Test **restores** quarterly.
- **RPO/RTO targets (see P12 F7):** for **order data**, target RPO ≤ 1h via frequent
  backups and enable **WAL-based PITR** as soon as the Postgres tier allows; RTO ≤ 2h.
  Orders are also operationally recoverable from the customer's WhatsApp history.
- Backups encrypted; access restricted; retention policy defined.
- Tenant-scoped restore runbook (restore one tenant without touching others).

## 9.7 Capacity & performance ops

- Start `api-web` with 1–2 replicas; scale on CPU/latency. WS works across replicas
  via Redis (P05).
- Tune per-tenant pool size + engine LRU cap to bound total Postgres connections;
  consider **PgBouncer** if connection count grows.
- Cache hot reads (menu, analytics) in Redis; CDN for frontend static assets.
- Async everywhere (asyncpg, httpx) to maximize throughput per instance.

## 9.8 Runbooks (ops playbooks)

- **Onboard tenant:** admin UI → provisioning (P02 §2.3) → verify health/migration.
- **Suspend tenant:** set status; block logins + agent ordering for that tenant.
- **Rotate a tenant DB password:** generate → update role → re-encrypt registry → evict
  cached engine.
- **WhatsApp token expired:** the startup check already logs invalid tokens; runbook to
  regenerate + update env + redeploy.
- **Incident (suspected leak):** revoke tokens, rotate keys, audit-log review, isolate.

Proceed to [Phase 10 — Testing & QA](./10-testing-qa.md).
