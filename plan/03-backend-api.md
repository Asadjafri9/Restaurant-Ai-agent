# Phase 03 — Backend API (FastAPI)

## 3.1 Project structure (evolved from current `app/`)

The current `app/` (webhook + Gemini + in-memory sessions + hardcoded restaurants)
becomes the **agent service** inside a larger, layered backend.

```text
app/
├── main.py                      # app factory, middleware, routers, lifespan
├── config/
│   └── settings.py              # pydantic-settings (extended: DB, Redis, secrets)
├── core/
│   ├── security.py              # JWT, password hashing (argon2id), CSRF
│   ├── crypto.py                # Fernet/KMS encrypt/decrypt for tenant creds
│   ├── rate_limit.py            # Redis-based limiter
│   ├── errors.py                # error model + handlers
│   └── logging.py               # structured logging, request IDs
├── db/
│   ├── central.py               # central engine/session (async)
│   ├── tenant_router.py         # LRU engine cache, tenant resolution
│   ├── models_central.py        # SQLAlchemy models (central schema)
│   └── models_tenant.py         # SQLAlchemy models (tenant schema)
├── deps/
│   ├── auth.py                  # get_current_user, require_role
│   └── tenant.py                # get_tenant_ctx (resolves tenant + session)
├── services/
│   ├── order_routing.py         # THE chokepoint to tenant DBs (create/update orders)
│   ├── menu_service.py          # tenant menu CRUD + publish to central catalog
│   ├── analytics_service.py     # tenant analytics queries + rollups
│   ├── provisioning.py          # create tenant DB/role/migrations/registry
│   ├── realtime.py              # Redis pub/sub publish + WS manager
│   ├── whatsapp_service.py      # (existing) send messages, now multi-number
│   ├── agent/                   # AI agent (existing order_agent split here)
│   │   ├── runner.py            # Gemini tool-calling loop
│   │   ├── tools.py             # get_menu / create_order / order_status tools
│   │   └── prompts.py           # system prompt + guardrails
│   └── session_service.py       # conversation state in Redis (was in-memory)
├── routes/
│   ├── webhook.py               # (existing) WhatsApp webhook (+ signature verify)
│   ├── auth.py                  # login/refresh/logout
│   ├── admin.py                 # platform admin (tenants, monitoring)
│   ├── menu.py                  # tenant menu CRUD
│   ├── orders.py                # tenant orders list/detail/status
│   ├── analytics.py             # tenant analytics endpoints
│   └── ws.py                    # WebSocket gateway
└── migrations/
    ├── central/
    └── tenant/
```

## 3.2 Tenant context dependency (the heart of isolation)

A FastAPI dependency resolves the tenant and yields a **single-tenant session**.
No handler ever opens a tenant connection by hand.

```python
# deps/tenant.py (illustrative)
async def get_tenant_ctx(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> TenantContext:
    # 1. Resolve tenant from JWT claim
    tenant_id = user.tenant_id
    if tenant_id is None:
        raise HTTPException(403, "No tenant scope")

    # 2. Defense in depth: subdomain must match the token's tenant
    host_slug = subdomain_of(request)            # kababjees.app.com -> "kababjees"
    if host_slug and host_slug != user.tenant_slug:
        raise HTTPException(403, "Tenant/host mismatch")

    # 3. Get a scoped async session bound to THIS tenant's DB + role
    engine = await tenant_router.get_engine(tenant_id)   # LRU, decrypts creds
    async with AsyncSession(engine) as session:
        yield TenantContext(tenant_id=tenant_id, session=session, slug=user.tenant_slug)
```

Rules enforced:
- The handler receives `ctx.session` already bound to the right DB; it physically
  cannot query another tenant's DB.
- `tenant_router.get_engine` uses the tenant's **own** DB role (least privilege).
- Platform-admin endpoints use a **different** dependency that talks to the central
  DB or routes through `order_routing` per explicit `tenant_id` (audited).

## 3.3 Authentication & authorization

- **Login** (`POST /auth/login`): email + password (argon2id verify) → issues a
  short-lived **access JWT** (~15 min) and a **refresh token** (httpOnly, Secure,
  SameSite=strict cookie, ~7 days, rotating).
- **JWT claims:** `sub` (user id), `role`, `tenant_id`, `tenant_slug`, `jti`, `exp`.
- **RBAC roles:** `platform_admin`, `owner`, `manager`, `staff`. `require_role(...)`
  dependency guards endpoints; **deny by default**.
- **Refresh rotation + reuse detection:** store `jti` allowlist/denylist in Redis;
  a reused refresh token revokes the family (theft mitigation).
- **CSRF:** double-submit token for cookie-based flows; pure Bearer API calls are
  CSRF-exempt but require the `Authorization` header.

Authorization matrix (high level):

| Endpoint group | platform_admin | owner | manager | staff |
|----------------|:--:|:--:|:--:|:--:|
| `/admin/*` (tenants, platform) | ✅ | ❌ | ❌ | ❌ |
| `/menu/*` (CRUD) | ❌ | ✅ | ✅ | ❌ |
| `/orders` (view) | ❌ | ✅ | ✅ | ✅ |
| `/orders/{id}/status` | ❌ | ✅ | ✅ | ✅ |
| `/analytics/*` | ❌ | ✅ | ✅ | ⚠️ limited |
| `/auth/*` | ✅ | ✅ | ✅ | ✅ |

(Platform admin never reads tenant order data — consistent with "no balance/data
in central." Admin sees only routing-index/operational metrics.)

## 3.4 API surface (REST)

All tenant endpoints require `get_tenant_ctx`. Versioned under `/api/v1`.

### Auth
- `POST /auth/login` → tokens
- `POST /auth/refresh` → rotate access token
- `POST /auth/logout` → revoke refresh family
- `GET  /auth/me` → current user + tenant

### Platform admin (central) — `require_role(platform_admin)`
- `POST /admin/tenants` → provision tenant (P02 §2.3)
- `GET  /admin/tenants` → list tenants (status, plan, migration head, health)
- `GET  /admin/tenants/{id}` → tenant metadata + operational counters
- `PATCH /admin/tenants/{id}` → suspend/activate/plan change
- `GET  /admin/overview` → platform-wide operational KPIs (order volume, active
  tenants, agent latency) — **no money**
- `GET  /admin/whatsapp-numbers` / `POST` → map Meta number → tenant
- `GET  /admin/audit` → audit log (filtered)
- `GET  /admin/agent/conversations` → live agent sessions (metadata only)

### Tenant menu — `require_role(owner|manager)`
- `GET    /menu/categories` / `POST` / `PATCH` / `DELETE`
- `GET    /menu/items` / `POST` / `PATCH /{id}` / `DELETE /{id}`
- `PATCH  /menu/items/{id}/availability` (quick toggle)
- (each write also publishes to central catalog + invalidates cache — P05)

### Tenant orders
- `GET   /orders` (filters: status, date range, search) — paginated
- `GET   /orders/{id}` (full detail + items + status history)
- `PATCH /orders/{id}/status` (state machine guarded; triggers customer notify)
- `GET   /orders/board` (kitchen view: active queue grouped by status)

### Tenant analytics — see P07 for full list
- `GET /analytics/summary?from&to`
- `GET /analytics/revenue-timeseries?from&to&granularity`
- `GET /analytics/top-items?from&to&limit`
- `GET /analytics/orders-by-status?from&to`
- `GET /analytics/peak-hours?from&to`

### Realtime
- `WS /ws/orders` (tenant-scoped; authenticated; subscribes to `tenant:{id}:orders`)

### Webhook (agent)
- `GET  /webhook` (Meta verification — existing)
- `POST /webhook` (inbound messages — existing, now with signature verification)

## 3.5 Order state machine

```text
placed → accepted → preparing → out_for_delivery → delivered
   └──────────────► cancelled (allowed before delivered)
```
- Transitions validated server-side (`order_routing.update_status`); illegal jumps
  rejected (e.g., delivered → preparing).
- Every transition writes `order_status_history` (who/what/when/source) and updates
  the central routing index status, and enqueues a customer WhatsApp notification.

## 3.6 Idempotency & reliability

- `create_order` requires an **idempotency key** (derived from conversation +
  confirmation). Re-submits return the existing order, never a duplicate.
- Tenant DB write committed **before** the agent confirms to the customer.
- Outbound WhatsApp notifications go through a **retry queue** (Redis) so a transient
  Meta API failure doesn't drop a status update.
- All external calls (Meta, Gemini) have timeouts + circuit-breaker-style fallbacks
  (the existing `ai_fallback_message` pattern, generalized).

## 3.7 Validation, errors, and pagination

- **Pydantic v2** request/response models for every endpoint (strict types, bounds).
- Uniform error envelope: `{ "error": { "code", "message", "request_id" } }`;
  never leak stack traces, SQL, or secrets.
- Cursor or offset pagination on list endpoints with sane max page sizes.
- Global exception handlers map domain errors → HTTP codes; unhandled → 500 + logged
  with `request_id` (correlatable in logs).

## 3.8 Configuration (extended settings)

Extend `app/config/settings.py` with:
`DATABASE_URL_CENTRAL`, `REDIS_URL`, `JWT_SECRET`, `JWT_ALG`, `FERNET_KEY`,
`WHATSAPP_APP_SECRET` (for webhook signature), `ALLOWED_ORIGINS`,
`TENANT_DB_HOST/PORT` (provisioning target), plus existing WhatsApp/Gemini keys.
All loaded from Railway env; never committed. `.env.example` updated accordingly.

Proceed to [Phase 04 — AI Agent & WhatsApp](./04-ai-agent-whatsapp.md).
