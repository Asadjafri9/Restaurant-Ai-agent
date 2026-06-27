# AGENTS.md

Multi-tenant WhatsApp food-ordering SaaS. FastAPI + Postgres + Redis + WhatsApp Cloud API + Groq/Gemini + ElevenLabs.

Detailed design lives in `plan/00-vision-scope-glossary.md` through `plan/12-review-criticism-improvements.md`. Read this file first, the plan only when you need design rationale.

## Service modes

One binary (`uvicorn app.main:app`) behaves differently based on `SERVICE_MODE`:

| Mode | What it serves | Required env |
|------|----------------|--------------|
| `agent` | WhatsApp webhook + AI agent | `DATABASE_URL_CENTRAL`, `WHATSAPP_*`, `GROQ_API_KEY` or `GEMINI_API_KEY`, `REDIS_URL` |
| `admin` | Platform admin dashboard | `DATABASE_URL_CENTRAL`, `REDIS_URL`, `JWT_SECRET`, `FERNET_KEY` |
| `kfc` / `kababjees` | Standalone tenant web | `DATABASE_URL` (tenant), plus central to mirror catalog |
| `all` | Everything (local dev) | All of the above |

`SERVICE_MODE` in `app/config/settings.py:44` auto-derives `tenant_slug`/`tenant_id` from `app/core/tenant_ids.py` — those are deterministic UUID5s, not random.

Routers mount conditionally: webhook only in `agent`, admin router only in `admin`, menu/orders/analytics/ws only in tenant modes (`app/main.py:115-129`). Home page HTML also varies by mode.

## Databases

Two schemas, two migration trees:

- `migrations/central/alembic.ini` → `app/db/models_central.py` (tenants, users, catalog_items, order_routing_index, agent_conversations, audit_log)
- `migrations/tenant/alembic.ini` → `app/db/models_tenant.py` (menu_items, customers, orders, order_items, staff_users, menu_outbox, routing_outbox)

Run **central first**, then tenant:
```bash
alembic -c migrations/central/alembic.ini upgrade head
alembic -c migrations/tenant/alembic.ini upgrade head
```

**Menu source of truth rule** (non-obvious — read `app/services/catalog_service.py:124-143`):
- Standalone tenant service with its own Postgres → reads `menu_items` from its tenant DB
- Agent + shared Postgres → reads `central.catalog_items` keyed by `tenant_id`
- `_tenant_menu_looks_isolated` (`catalog_service.py:26-39`) detects pollution and falls back to central

After any `menu_items` mutation, `app/services/menu_sync.py:sync_menu_after_mutation` rebuilds the central mirror via outbox (`MenuOutbox` → `process_tenant_outboxes`).

Tenant engine cache is LRU with `MAX_ENGINES=50` (`app/db/tenant_router.py:19`). Long-lived idle tenants get evicted.

## Agent / ordering pipeline

Webhook → `app/routes/webhook.py` → `app/services/agent/runner.py` OR `app/services/order_agent.py` (preferred). The LLM only runs as a fallback — most replies are deterministic:

- `_try_serve_catalog_menu` / `_reply_with_menu` → menu replies
- `_reply_after_items_added` → after extracting items
- `format_order_summary` → after "done adding"
- `process_order_message_async` is the LLM path; LLM must output `[ORDER_JSON]...[/ORDER_JSON]` block (schema in `app/services/agent/prompts.py:94`)

`app/services/order_agent.py:788` is the early-confirm path — when customer says YES, it persists directly from `session.pending_items` without round-tripping the LLM. Don't refactor this without reading the test (`tests/test_order_confirm.py`).

LLM provider order: Gemini 2.5 Flash (new google.genai SDK) first, Groq (Llama 3.3 70B) as fallback on rate limit. Speech-to-text: Gemini 2.5 Flash (multimodal audio), Groq Whisper as fallback. See `app/services/llm_client.py:generate_reply` and `app/services/speech_service.py:transcribe`. Voice reply uses ElevenLabs only if `ELEVENLABS_API_KEY` is set; text reply is always sent first.

## Commands

```bash
pip install -r requirements.txt                  # python 3.12
ruff check app tests                              # CI lint (no auto-fix in CI)
pytest tests/ -v                                  # asyncio_mode=auto from pytest.ini
uvicorn app.main:app --host 0.0.0.0 --port $PORT # one service per process
python -m app.worker                              # outbox + provisioning queue (Redis "platform:jobs")
python scripts/seed.py                            # one-time, idempotent
```

CI runs `ruff check app tests` then `pytest tests/ -v` with Postgres 16 + Redis 7 services and a fixture `FERNET_KEY`. Local dev expects the same — see `.github/workflows/ci.yml` for the env vars it sets.

## Local dev (Windows + PowerShell)

- `scripts/fetch_local_env.ps1` pulls Railway connection strings into `local/*.env` (gitignored). Requires `railway login` first.
- `scripts/run_all_local.ps1` launches admin (8001), KFC (8002), Kababjees (8003) as separate processes; the agent runs on Railway.
- `scripts/run_admin.ps1` binds `--host ::` (IPv6 dual-stack) intentionally — browsers hit `::1` first, dual-stack avoids a ~2s IPv4 fallback.
- `railway.toml` / `nixpacks.toml` / `Procfile` all call `bash scripts/start_agent.sh` which migrates + seeds + execs uvicorn.
- Seed accounts: `admin@platform.local / admin123`, `owner@<slug>.local / owner123`.

## Auth / WebSocket

- JWT (HS256, secret in `JWT_SECRET`). Refresh tokens stored in Redis under `refresh:<portal>:<jti>`; cookies are `refresh_token_<portal>` (path `/`, `samesite=strict`).
- Standalone tenant web reads `StaffUser` from tenant DB; admin reads central `User`.
- WebSocket auth at `app/routes/ws.py:31` — client offers subprotocol `access.<jwt>`, server **must echo the exact string back** (RFC 6455). Regression test: `tests/test_ws_subprotocol.py`.
- Cross-portal login blocked by `app/core/portals.py:user_matches_portal`.

## Operational gotchas

- WhatsApp webhook signature (`app/core/webhook_security.py`) — set `WHATSAPP_APP_SECRET` in production. In dev with `WEBHOOK_SIGNATURE_REQUIRED=false` it's skipped.
- `phone_hash_pepper` auto-generated in dev, must be set in production (otherwise tokens can't be re-derived across restarts).
- `FERNET_KEY` encrypts tenant DB passwords stored in `tenant_connections.db_password_enc`. Auto-generated in development only.
- `db_pool_pre_ping` auto-off in dev (saves a round trip to remote DB), auto-on in prod (`app/config/settings.py:135`).
- `use_read_cache` (`app/core/read_cache.py:142`) bypasses Redis in dev to skip round trips; in prod uses Redis JSON cache, 5–30s TTL.
- Webhook dedupe key: `wamid:<message_id>` with 600s TTL (`app/routes/webhook.py:225`).
- WhatsApp token verification is cached 5 min (`app/services/whatsapp_service.py:_TOKEN_CACHE_TTL`); `invalidate_whatsapp_token_cache()` on 401/403 from send.
- Rate limiter (`app/core/rate_limit.py`) is disabled in dev and skips `/webhook`, `/health`, `/`, `/app/*`.
- Subdomain-based tenant routing: `app/deps/auth.py:subdomain_of` rejects mismatched tenant on subdomain (skips `www`, `api`, `admin`).
- `app/data/restaurants.py` is a hardcoded fallback used when central catalog is empty — keep the KFC/Kababjees slugs in sync with `app/core/tenant_ids.py` and the seed.

## Tests

- `pytest.ini` sets `asyncio_mode = auto` and `testpaths = tests`.
- Unit tests are pure-Python with `monkeypatch` — no DB/Redis required (`tests/test_voice_intent.py`, `tests/test_menu_reply.py`, `tests/test_ws_subprotocol.py`).
- `tests/test_isolation.py` is a schema/state-machine guard (`OrderRoutingIndex` must never carry money columns; `ORDER_STATUSES` transitions).
- Tests do **not** boot FastAPI; they call internal functions directly. Do the same for new tests.

## Don't

- Don't call `genai.GenerativeModel` outside `app/services/agent/runner.py` — `app/services/llm_client.py` is the supported async path.
- Don't add money columns to `OrderRoutingIndex` — it indexes routing state only; the source of truth for totals is the tenant `orders` table.
- Don't modify `app/core/tenant_ids.py` UUIDs — they are referenced by tenant DBs and seeded data; changing them strands existing tenants.
- Don't add a top-level `try/except` around FastAPI handlers in route files — `app/main.py:144-156` already wraps unhandled errors with a 500 + `X-Request-ID` (use `AppError` from `app/core/errors.py` for expected errors).
- Don't run `pytest` with a stale `local/*.env` — services in those envs point at Railway databases you may not have access to.
