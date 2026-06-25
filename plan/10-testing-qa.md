# Phase 10 — Testing & QA

Quality gates that protect the two things that matter most: **isolation** and
**order correctness**.

## 10.1 Test pyramid

| Layer | Scope | Tools |
|-------|-------|-------|
| Unit | services, pricing, state machine, crypto, parsers | pytest |
| Integration | API + DB (central + ephemeral tenant DBs) | pytest + testcontainers/Postgres |
| Contract | agent tools, WhatsApp payloads | pytest + recorded fixtures |
| E2E | webhook → agent → order → dashboard | pytest + Playwright (frontend) |
| Load | webhook + analytics under load | Locust/k6 |
| Security | isolation, authz, webhook signature | pytest (custom) + ZAP baseline |

## 10.2 Isolation tests (the most important suite)

These **must** pass or deploy is blocked:

1. **App-layer cross-tenant read denied:** authenticate as tenant A, attempt to fetch
   an order id that exists only in tenant B → 404 (not found in A's DB), never B's data.
2. **JWT/host mismatch denied:** token for tenant A used on tenant B's subdomain → 403.
3. **DB role can't cross DBs:** connect with tenant A's role to tenant B's database →
   connection refused/permission denied.
4. **Admin role has no tenant-DB privileges:** central/admin role cannot read any
   tenant DB directly.
5. **WebSocket channel scoping:** a tenant A client cannot receive tenant B events even
   if it forges channel input (server derives channel from token).
6. **Routing index has no money:** schema/assertion test that `order_routing_index`
   contains no monetary columns (guards against accidental leakage of balances to
   central).

## 10.3 Order correctness tests

- Pricing computed server-side matches catalog; LLM-provided totals are ignored.
- Idempotency: same idempotency key → one order; concurrent duplicate submits → one row.
- Durability: order is committed to tenant DB before customer confirmation is sent
  (simulate confirmation-send failure → order still exists).
- State machine: illegal transitions rejected; each transition writes history +
  updates routing index + enqueues notification.
- Menu sync: edit item → catalog projection updated + cache invalidated + agent sees
  new price on next `get_menu`.

## 10.4 Agent tests

- Tool-calling happy path (select restaurant → menu → items → details → confirm → order).
- Prompt-injection attempts ("ignore rules", "show other restaurant revenue", "set
  price to 0") → no tool exists to comply; tenant lock holds; pricing unaffected.
- Missing-detail prompting (asks for name/address before ordering).
- Failure fallbacks (Gemini timeout, item unavailable, routing down → no false confirm).
- Webhook: signature valid/invalid, malformed payload (returns 200, no crash —
  matches current resilient behavior), duplicate `message.id` deduped.

## 10.5 Frontend tests

- Component tests (Vitest + Testing Library) for KpiCard, DataTable, OrderCard,
  FilterBar, charts (render + accessibility names).
- E2E (Playwright): login, live order appears via WS, advance status optimistic +
  rollback on API error, menu CRUD reflects, analytics filters update charts + URL.
- Accessibility: axe checks (WCAG AA), keyboard nav, reduced-motion.
- Responsive snapshots (desktop/tablet).

## 10.6 Load & resilience

- Webhook burst (e.g., 100 msgs/s) → acks fast, processes via worker, no loss.
- Analytics queries on large datasets within latency budget (rollups kick in).
- Connection-pool stress across many tenants → LRU eviction works, no exhaustion.
- Chaos: kill an api-web replica mid-flow → WS reconnect + catch-up fetch reconciles.

## 10.7 QA gates (CI)

- Coverage threshold on core services (routing, pricing, auth, crypto).
- All isolation + security tests green.
- Lint (ruff), types (mypy), frontend lint/types.
- `pip-audit`/`npm audit` no high-severity; secret scan clean.
- Migration check: tenant migrations apply cleanly on a fresh DB and are reversible
  (expand/contract).

## 10.8 Manual UAT scripts

- Onboard a new restaurant end-to-end; place an order over WhatsApp; watch it appear
  live; advance through statuses; confirm customer gets updates; verify analytics move;
  edit menu and confirm the agent quotes the new price.

Proceed to [Phase 11 — Roadmap & Milestones](./11-roadmap-milestones.md).
