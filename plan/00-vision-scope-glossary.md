# Phase 00 — Vision, Scope, Personas & Glossary

## 0.1 Vision

Build a SaaS platform where many restaurants ("tenants") each get their own
isolated dashboard and database, while a single AI agent on WhatsApp serves
customers across all of them. The platform owner operates a **central control
plane** that knows *about* each restaurant (name, owner, menu, prices) but never
stores a restaurant's private operational/financial data.

The product delivers three experiences:

1. **Customer (WhatsApp):** Chats with the AI agent, browses a restaurant's menu,
   places an order; receives confirmation and status updates.
2. **Restaurant owner/staff (Tenant Dashboard):** Sees incoming orders live,
   updates order status (Accepted → Preparing → Out for delivery → Delivered),
   manages the menu, and views modern analytics — all on their own isolated data.
3. **Platform admin (Central Admin Dashboard):** Onboards restaurants, monitors
   platform-wide *operational* health (order volumes, active tenants, agent
   performance), manages the WhatsApp routing — without seeing tenant money.

## 0.2 In scope (this plan)

- Multi-tenant architecture with **database-per-tenant** isolation.
- Central metadata DB + central admin dashboard.
- AI agent (Gemini) + WhatsApp Cloud API, evolving the existing code.
- Per-tenant dashboards: live orders (real-time), menu CRUD, analytics.
- Menu publish (tenant → central catalog) + order routing (agent → tenant DB).
- Security hardening, performance, deployment to Railway, testing, observability.

## 0.3 Out of scope (explicitly deferred)

- Payments/settlement, invoicing, payouts (kept out; central must not hold money).
- Driver/logistics dispatch system (status is manual by the owner for v1).
- Native mobile apps (web only; dashboards are responsive).
- Multi-language NLU beyond what Gemini provides out of the box.
- Marketplace discovery / customer-facing web storefront (WhatsApp is the channel).

## 0.4 Personas

| Persona | Goals | Pain if we fail |
|--------|-------|-----------------|
| **Customer** | Order food fast over WhatsApp, no app install | Confusing chat, wrong order, no confirmation |
| **Restaurant owner** | See & fulfill orders, tweak menu, understand sales | Missed orders, stale menu, no insight |
| **Kitchen/staff** | Glanceable queue of orders to prepare | Cluttered UI, no real-time updates |
| **Platform admin** | Onboard tenants, keep platform healthy | No visibility, noisy incidents, security risk |
| **Platform owner (business)** | Grow tenants, stay secure & cheap on infra | Data leak between tenants = company-ending |

## 0.5 Top-level requirements traceability

| # | Requirement (from brief) | Where addressed |
|---|---------------------------|-----------------|
| R1 | Central system holds metadata only (name, owner email, menu, price), **not balance** | P01, P02 (`central` schema), P08 |
| R2 | AI agent places orders to the correct restaurant | P04, P05 |
| R3 | Central web shows records across tenants | P06 (Admin), P07 |
| R4 | Each tenant has a **separate DB**, no cross-tenant access | P01, P02, P08 |
| R5 | Tenant web shows orders updating in **real time** | P05, P06 |
| R6 | **Modern analytics** per dashboard, filtered & unfiltered | P07 |
| R7 | Restaurant edits menu in its portal → reflected centrally for the agent | P05 (menu sync) |
| R8 | Flow: WhatsApp chat → order → tenant dashboard → prepare → deliver | P04, P05, P06 |
| R9 | Similar design across tenants, separate data | P06 (shared design system) |
| R10 | Security vulnerabilities considered | P08 (threat model + controls) |
| R11 | Admin dashboard design used by all tenants | P06 |
| R12 | DB design: same schema, different data per tenant | P02 |
| R13 | Deploy on Railway | P09 |
| R14 | FastAPI + PostgreSQL; React frontend | P03, P06 |

## 0.6 Success metrics (definition of done for v1)

- **Isolation:** An automated test proves tenant A's credentials/queries can never
  read tenant B's data (DB role + app-layer). Zero cross-tenant reads in audit.
- **Latency:** WhatsApp reply p95 < 5s; order appears on dashboard < 1.5s after creation.
- **Menu freshness:** Menu edit visible to the agent within < 10s.
- **Reliability:** Webhook never crashes on malformed payloads; orders are never lost
  (idempotent creation + durable write before WhatsApp confirmation).
- **Analytics:** Each tenant dashboard renders revenue, orders, AOV, top items, and
  peak-hours charts with date/status/item filters.
- **Security:** Passes the Phase 08 checklist (authz, secrets, webhook signature,
  rate limiting, prompt-injection guardrails).

## 0.7 Glossary

- **Control plane:** Central services (API, admin UI, AI agent) + central metadata DB.
- **Data plane:** The per-tenant PostgreSQL databases holding private order data.
- **Tenant:** One restaurant. Has exactly one isolated database and one dashboard scope.
- **Central catalog:** The metadata copy of every tenant's menu, used by the agent.
- **Order routing index:** Central record `{order_id, tenant_id, status, timestamps}`
  with **no monetary amounts** — used to track/route, not to store money.
- **Order Routing Service:** Internal component that owns per-tenant DB connections
  and performs writes/reads on behalf of the agent and dashboards.
- **Tenant resolution:** Mapping an inbound request (subdomain/JWT) or WhatsApp
  number to a specific tenant context.
- **Provisioning:** Creating a new tenant's database, role, schema (migrations), and
  registry entry during onboarding.
