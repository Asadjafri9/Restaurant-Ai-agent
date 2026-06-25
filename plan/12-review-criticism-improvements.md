# Phase 12 — Self-Review, Criticism & Improvements

This phase critiques the plan honestly, then records the improvements applied back
into the earlier phases. Each finding has a severity, the criticism, and the fix.

## 12.1 Findings & fixes

### F1 — Connection-pool exhaustion at scale (Severity: High)
**Criticism:** Database-per-tenant means each API replica may open a pool per tenant.
With many tenants × replicas, total Postgres connections explode and Postgres falls
over — the classic database-per-tenant failure mode. The original P05/P09 mention an
LRU cap but under-specify the numbers and don't mandate a proxy.
**Fix (applied to P05 §5.5 / P09 §9.7):** Mandate **PgBouncer** (transaction pooling)
in front of Postgres once tenant count > ~10; cap engine LRU (e.g., 50) and per-engine
pool (2–3); idle-evict aggressively. Document a connection budget formula:
`replicas × max_engines × pool_size ≤ 80% of Postgres max_connections`.

### F2 — Provisioning needs superuser-level privileges in the web tier (Severity: High)
**Criticism:** `CREATE DATABASE/ROLE` from the Central API means the web-facing
service holds powerful DB admin credentials — a juicy target and a privilege
over-grant.
**Fix (applied to P02 §2.3 / P08 §8.6):** Move provisioning to the **worker**
service using a **dedicated, narrowly-scoped provisioning role** (can create
DB/role but nothing else), never exposed to the request path. The web API only
enqueues a provisioning job (admin-authorized + audited). Optionally gate behind a
manual approval for production.

### F3 — Dual-write consistency for the order routing index (Severity: Medium-High)
**Criticism:** Order creation writes the tenant DB **and** the central routing index.
The menu sync got an outbox, but order routing did not — a crash between the two
writes leaves central out of sync with the tenant.
**Fix (applied to P01 §1.6 / P05 §5.3):** Use the **transactional outbox** for the
routing index too: write an outbox row inside the tenant order transaction; the
worker projects it to `central.order_routing_index`. The tenant DB remains the source
of truth; central is eventually consistent and self-heals via the reconciler.

### F4 — Blast radius of the routing service holding all tenant creds (Severity: Medium-High)
**Criticism:** A single Order Routing Service that can decrypt and connect to *every*
tenant DB is a central point of compromise — defeating some of the isolation benefit.
**Fix (applied to P01 §1.4 / P08 §8.2):** (a) Keep decrypted creds only in-memory,
short-lived, never logged; (b) the Fernet/KMS key lives only on the routing/worker
service, separate from the central DB; (c) offer a **per-tenant microservice tier**
for premium/high-risk tenants where each tenant's API+creds run isolated, removing
the shared chokepoint. v1 uses the shared chokepoint with strict controls; the
registry design lets us split later with no schema change.

### F5 — WebSocket auth via query string leaks tokens (Severity: Medium)
**Criticism:** Passing the JWT as a `?token=` query param logs it in proxies/access
logs.
**Fix (applied to P05 §5.1 / P06 §6.7):** Authenticate the WS via the
`Sec-WebSocket-Protocol` subprotocol header or a first-message auth frame; never the
URL. Short-lived token; server derives the channel from the token, not client input.

### F6 — Cross-subdomain cookie scoping for refresh tokens (Severity: Medium)
**Criticism:** With `{slug}.app.com` per tenant and `admin.app.com`, an httpOnly
refresh cookie scoped to the parent domain would be shared across all tenant
subdomains — a tenant's browser context could carry another scope's cookie.
**Fix (applied to P03 §3.3 / P08 §8.3):** Scope refresh cookies to the **exact host**
(no parent-domain wildcard) so each subdomain has its own cookie; bind the refresh
token's `jti` to the tenant; re-validate tenant/host on refresh. Consider a dedicated
`auth.app.com` token endpoint with explicit per-host issuance.

### F7 — Backup RPO of 24h is too weak for live orders (Severity: Medium)
**Criticism:** Losing up to 24h of orders is unacceptable for restaurants.
**Fix (applied to P09 §9.6):** Target **RPO ≤ 1h** for order data via more frequent
backups and enable **WAL-based PITR** as soon as the Railway/Postgres tier allows.
Orders are also recoverable operationally because the customer has WhatsApp history.

### F8 — "Total" exists but there's no payment; refunds/cancellations fuzzy (Severity: Low-Med)
**Criticism:** Analytics use `orders.total`, but payment collection is out of scope —
the revenue is "expected" not "collected," and cancellations after preparation are
unclear.
**Fix (applied to P00 §0.3 / P07 §7.7):** State explicitly that v1 tracks
**order value (cash/COD assumed)**, not settled payments; define cancellation/refund
handling (excluded from revenue; tracked separately) and a `cancellation_reason`.

### F9 — Gemini tool-calling reliability / structured output (Severity: Medium)
**Criticism:** LLMs sometimes don't call tools correctly or hallucinate arguments.
**Fix (applied to P04 §4.2 / §4.8):** Validate every tool argument with Pydantic;
on malformed tool calls, re-prompt with the validation error (bounded retries) and
fall back to asking the customer to rephrase; never place an order from ambiguous
input. Keep the existing graceful fallback message for hard failures.

### F10 — Tenant migration fan-out can partially fail (Severity: Medium)
**Criticism:** Migrating N tenant DBs sequentially can fail midway, leaving the fleet
on mixed schema versions.
**Fix (applied to P02 §2.4 / P09 §9.4):** Strict **expand/contract** migrations
(backward compatible), an idempotent **migrate-all** job with per-tenant
retry/resume, and a **drift dashboard** that blocks "contract" steps until 100% of
tenants are on the expand version.

### F11 — Same customer across tenants is duplicated (Severity: Low — by design)
**Criticism:** A customer ordering from two restaurants exists separately in each
tenant DB; there's no unified customer.
**Resolution:** This is **intentional** — isolation forbids a shared customer table.
Documented as accepted (the central phone *hash* is only for routing/dedup, not a
cross-tenant profile). No change needed beyond documentation.

### F12 — i18n / localization (Severity: Low)
**Criticism:** Pakistani customers may message in Urdu/Roman Urdu; UI is English-only.
**Fix (applied to P04 / P06 roadmap):** Agent already handles multilingual input via
Gemini; add an i18n layer (English first, Urdu next) to the dashboard as a
fast-follow. Currency fixed to PKR with locale-aware formatting.

### F13 — Admin "Catalog" view could become a cross-tenant data backdoor (Severity: Medium)
**Criticism:** The admin Catalog screen (P06) shows every tenant's menu+prices; if
scope-creep adds order data there, it violates "central has no tenant data."
**Fix (applied to P06 §6.4 / P08):** Hard rule — the admin plane may render only
`central.*` tables (catalog metadata + routing index counts). Any tenant order/money
data is **never** exposed to admin endpoints; enforced by using the central-only
session for all `/admin/*` routes and an isolation test.

### F14 — Webhook background processing could drop work on restart (Severity: Medium)
**Criticism:** The current code uses FastAPI `BackgroundTasks`, which die if the
instance restarts mid-task.
**Fix (applied to P04 §4.5 / P05 §5.5):** Replace `BackgroundTasks` with a
**Redis-backed task queue** consumed by the worker; ack the webhook immediately,
enqueue durable work. Already reflected in the worker service (P09).

## 12.2 Cross-cutting improvements adopted
- **Transactional outbox** is now the standard for *both* menu sync and routing-index
  projection (consistency without distributed transactions).
- **PgBouncer + explicit connection budget** is a first-class requirement, not an
  afterthought.
- **Privilege separation**: provisioning + cred-decryption live on the worker, not the
  web tier.
- **PITR/short RPO** for order durability.
- **Strict admin/central data boundary** with an isolation test guarding it.

## 12.3 Residual risks (accepted for v1)
- Shared routing-service chokepoint (mitigated, splittable later — F4).
- Cost ladder assumes manual promotion of heavy tenants to dedicated DBs (P09 §9.3).
- No real payments → revenue = order value, not settled funds (F8).
- Eventual consistency (seconds) between tenant data and central projections (by design).

## 12.4 Post-improvement scorecard

| Dimension | Before | After | Notes |
|-----------|:--:|:--:|------|
| Tenant isolation | Strong | Strong+ | Outbox + admin boundary test + cred isolation |
| Performance/scale | Risky at scale | Solid | PgBouncer + connection budget + rollups |
| Reliability | Good | Strong | Durable queue + outbox + PITR + idempotency |
| Security | Strong | Strong+ | Privilege separation, WS/cookie hardening |
| UX/consistency | Strong | Strong | Shared design system, accessibility, i18n path |
| Cost on Railway | Unclear | Managed | Explicit cost ladder |

The plan is internally consistent and ready to execute milestone-by-milestone
(Phase 11). The most important guardrails — isolation tests, durable order writes,
and the central "no money" boundary — are enforced by tests, not just intentions.
