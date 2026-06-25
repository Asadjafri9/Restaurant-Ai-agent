# Multi-Tenant WhatsApp Ordering Platform — Master Plan

This folder contains the full, phased engineering plan to evolve the current
single-tenant WhatsApp bot (FastAPI + Google Gemini) into a **multi-tenant
restaurant ordering SaaS** with:

- A **centralized control plane** that holds only *metadata* (restaurant name,
  owner email, menu, prices) — **never** tenant financial balances or private data.
- A **centralized AI agent** that chats with customers on WhatsApp, takes orders,
  and routes each order to the correct restaurant.
- A **central admin web dashboard** that sees all tenants (operational metadata only).
- A **per-tenant web dashboard** (same design, isolated data) showing live orders,
  menu management, and modern analytics.
- **Database-per-tenant isolation** so no tenant can ever access another tenant's data.

> Target deployment: **Railway**. Backend: **FastAPI + PostgreSQL**.
> Frontend: **React (Vite + TypeScript + Tailwind + shadcn/ui + Recharts)**
> (rationale in Phase 06).

---

## How to read this plan

Each phase is a standalone, sequential document. Build them in order; later
phases depend on earlier ones.

| Phase | File | What it covers |
|------:|------|----------------|
| 00 | [`00-vision-scope-glossary.md`](./00-vision-scope-glossary.md) | Goals, scope, personas, glossary, success metrics |
| 01 | [`01-architecture.md`](./01-architecture.md) | System architecture, multi-tenancy strategy, data flows |
| 02 | [`02-database-design.md`](./02-database-design.md) | Central DB + tenant DB schemas, ERDs, indexes, provisioning |
| 03 | [`03-backend-api.md`](./03-backend-api.md) | FastAPI structure, endpoints, tenant routing, services |
| 04 | [`04-ai-agent-whatsapp.md`](./04-ai-agent-whatsapp.md) | Agent design, tool-calling, WhatsApp, conversation state |
| 05 | [`05-realtime-and-sync.md`](./05-realtime-and-sync.md) | WebSockets, Redis pub/sub, menu sync, order routing |
| 06 | [`06-frontend-design.md`](./06-frontend-design.md) | Design system, admin + tenant dashboards, wireframes |
| 07 | [`07-analytics.md`](./07-analytics.md) | Metrics, filtered/unfiltered charts, aggregation strategy |
| 08 | [`08-security.md`](./08-security.md) | Threat model, tenant isolation, OWASP, LLM security |
| 09 | [`09-deployment-railway-ops.md`](./09-deployment-railway-ops.md) | Railway services, CI/CD, scaling, backups, observability |
| 10 | [`10-testing-qa.md`](./10-testing-qa.md) | Test strategy, isolation tests, load tests, QA gates |
| 11 | [`11-roadmap-milestones.md`](./11-roadmap-milestones.md) | Sequenced milestones, estimates, risks |
| 12 | [`12-review-criticism-improvements.md`](./12-review-criticism-improvements.md) | Self-review, criticism, and improvements applied |

---

## Executive summary (TL;DR)

1. **Two planes.** A *control plane* (central API + admin UI + AI agent + central
   metadata DB) and a *data plane* (one PostgreSQL database per restaurant tenant).
2. **The agent never touches tenant DB credentials directly through the LLM.** It
   calls an internal, authorized **Order Routing Service** that owns the
   per-tenant connections, encrypted at rest.
3. **Menu is owned by the tenant**, published *up* to the central catalog so the
   agent always shows the latest menu. Central stores menu metadata + prices only.
4. **Orders flow down**: agent creates an order → routing service writes to the
   correct tenant DB → real-time push (WebSocket via Redis) lights up that
   tenant's dashboard instantly. Central keeps only a routing index (status +
   timestamps, **no money**).
5. **Isolation is enforced in three layers**: connection routing, per-tenant DB
   roles/credentials, and application authz (tenant_id in JWT validated against
   the subdomain). Defense in depth.
6. **Analytics**: tenant dashboards get full financial analytics from their own
   DB; the central admin sees only privacy-preserving operational metrics.

The current code (`app/`) becomes the seed of the **AI agent + WhatsApp webhook**
service inside the control plane. See Phase 11 for the migration path.
