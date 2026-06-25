# Phase 06 — Frontend Design (Admin + Tenant Dashboards)

## 6.1 Frontend stack decision

**Choice: React + Vite + TypeScript**, with:

- **Tailwind CSS** + **shadcn/ui** (Radix primitives) → consistent, modern,
  accessible components; one design system reused by every tenant ("similar design
  for each restaurant").
- **TanStack Query** → server state, caching, background refetch, optimistic updates.
- **Recharts** → modern, responsive analytics charts (P07).
- **React Router** → routing (`/admin/*` vs tenant scope).
- **Native WebSocket** (thin wrapper hook) → real-time orders.
- **Zustand** (light) → local UI state (filters, theme, board layout).

**Why React over plain HTML/CSS/JS:** the app is genuinely interactive — live order
boards, optimistic status changes, rich filterable charts, and a shared component
library across many tenants. React + a component kit makes "same design, different
data" trivial and keeps quality consistent. (Plain HTML/JS would be fine only for a
static marketing page, which isn't what this is.)

**One app, two layouts.** A single React app (one codebase, one design system) with:
- **Admin layout** (`admin.app.com` or `/admin`): platform admin only.
- **Tenant layout** (`{slug}.app.com`): restaurant owner/staff, data scoped by JWT.

This maximizes design consistency and code reuse while keeping data isolation at the
API/DB layer (the frontend never decides isolation — the backend does).

## 6.2 Design system

**Brand-neutral, professional, modern.** Tenants share the system; optional
per-tenant accent color + logo so each restaurant feels "theirs" without forking UI.

- **Theme tokens** (CSS variables): `--primary` (tenant accent, default indigo
  `#4F46E5`), `--bg`, `--surface`, `--text`, `--muted`, `--success #16A34A`,
  `--warning #D97706`, `--danger #DC2626`, `--info #2563EB`. Light + dark mode.
- **Typography:** Inter (or system stack). Scale: 12/14/16/20/24/30/36. Numeric
  tabular figures for money/metrics.
- **Spacing:** 4px base grid (4/8/12/16/24/32/48). Generous whitespace.
- **Radius:** `rounded-2xl` cards, `rounded-lg` controls. Soft shadows (`shadow-sm`).
- **Status colors (orders):** placed=blue, accepted=indigo, preparing=amber,
  out_for_delivery=violet, delivered=green, cancelled=gray/red. Consistent
  everywhere (badges, kanban, charts).
- **Components (shadcn):** Button, Card, Badge, Table (sortable + paginated), Dialog,
  Sheet (drawer), Tabs, Toast, Tooltip, DropdownMenu, Select, DatePicker/RangePicker,
  Skeleton (loading), EmptyState, Command palette (⌘K).
- **Accessibility:** WCAG AA contrast, full keyboard nav, focus rings, ARIA on
  interactive widgets, `prefers-reduced-motion` respected, screen-reader labels on
  charts (data tables as fallback).
- **Responsive:** desktop-first dashboards that gracefully collapse to tablet (kitchen
  often uses tablets). Sidebar → bottom nav / hamburger on small screens.
- **Micro-interactions:** subtle card-in animations for new orders, toast + optional
  sound, hover elevation, loading skeletons (never spinners-only), optimistic updates.

## 6.3 Information architecture

### Tenant Dashboard (restaurant)
```
Login → Overview (analytics summary)
        ├── Live Orders (kanban board)   ← real-time
        ├── Orders (table + filters + detail)
        ├── Menu (categories + items CRUD, availability toggle)
        ├── Analytics (charts, filters)
        ├── Staff (invite/manage staff, roles)        [owner only]
        └── Settings (profile, hours, delivery fee, tax, accent/logo, WhatsApp)
```

### Central Admin Dashboard (platform)
```
Login → Platform Overview (operational KPIs, no money)
        ├── Tenants (list, status, health, provision new)
        │     └── Tenant detail (metadata, migration head, order volume)
        ├── Catalog (cross-tenant menu metadata view, read-mostly)
        ├── Agent Monitor (live conversations metadata, latency, errors)
        ├── WhatsApp Numbers (map number → tenant)
        ├── Audit Log (filterable)
        └── Settings (admins, platform config)
```

## 6.4 Admin Dashboard — wireframes

### Platform Overview
```
┌───────────────────────────────────────────────────────────────────────────┐
│  ☰  Platform Admin                       🔍 ⌘K        🌙   admin@platform ▾ │
├───────────┬───────────────────────────────────────────────────────────────┤
│ ▸ Overview│  Platform Overview                         [ Last 7 days  ▾ ]  │
│ ▸ Tenants │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│ ▸ Catalog │  │ Active   │ │ Orders   │ │ Agent    │ │ Avg reply│          │
│ ▸ Agent   │  │ tenants  │ │ today    │ │ sessions │ │ latency  │          │
│ ▸ Numbers │  │   12     │ │  1,284   │ │   37     │ │  2.1 s   │          │
│ ▸ Audit   │  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│ ▸ Settings│  ┌─────────────────────────────┐ ┌──────────────────────────┐ │
│           │  │ Orders volume (all tenants) │ │ Orders by status          │ │
│           │  │  ▁▂▃▅▇▆▅▃  (line chart)      │ │  (stacked bar)            │ │
│           │  └─────────────────────────────┘ └──────────────────────────┘ │
│           │  Tenants needing attention                                     │
│           │  ┌───────────────────────────────────────────────────────────┐│
│           │  │ Restaurant   Status     Migration   Orders/24h   Health    ││
│           │  │ Kababjees    ● active   up-to-date     142       ● ok      ││
│           │  │ KFC          ● active   PENDING ⚠      210       ● ok      ││
│           │  │ BurgerLab    ⏸ suspended  —             0        ○ idle    ││
│           │  └───────────────────────────────────────────────────────────┘│
└───────────┴───────────────────────────────────────────────────────────────┘
```
> Note: charts here are **operational counts only** — no revenue/money (central
> never holds balances).

### Tenants list + Provision new
```
┌───────────────────────────────────────────────────────────────────────────┐
│  Tenants                                            [ + Provision tenant ]  │
│  🔍 search    [ Status ▾ ] [ Plan ▾ ]                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Name        Slug        Owner email          Status   Plan   Created   │ │
│  │ Kababjees   kababjees   owner@kababjees.pk   active   pro    2026-01-04│ │
│  │ KFC         kfc         ops@kfc.pk           active   pro    2026-01-09│ │
│  │ BurgerLab   burgerlab   hi@burgerlab.pk      suspend  free   2026-02-… │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Provision tenant (dialog):                                                 │
│  ┌─────────────────────────────────────────┐                              │
│  │ Restaurant name [ ____________________ ] │                              │
│  │ Slug/subdomain  [ ______ ].app.com       │  (validated, unique)         │
│  │ Owner email     [ ____________________ ] │                              │
│  │ Plan            [ free ▾ ]               │                              │
│  │            [ Cancel ]  [ Create ▶ ]      │  → runs P02 §2.3 provisioning │
│  └─────────────────────────────────────────┘                              │
└───────────────────────────────────────────────────────────────────────────┘
```

### Agent Monitor (metadata only)
```
┌───────────────────────────────────────────────────────────────────────────┐
│  Agent Monitor                                   [ Live ● ]  [ 24h ▾ ]      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐  ┌───────────────────────────────┐ │
│  │ Active   │ │ Orders   │ │ Errors   │  │ Latency p50 / p95             │ │
│  │ convos 37│ │ placed 91│ │ 0.4%     │  │  1.1s / 2.1s   (line)         │ │
│  └──────────┘ └──────────┘ └──────────┘  └───────────────────────────────┘ │
│  Conversations (no message contents shown — privacy)                        │
│  │ Phone(hash)  Restaurant   State        Last msg     Msgs  Outcome      │ │
│  │ a91f…        KFC          confirming   12s ago       8    —            │ │
│  │ 7c30…        Kababjees    done         2m ago       11    order #1284  │ │
└───────────────────────────────────────────────────────────────────────────┘
```

## 6.5 Tenant Dashboard — wireframes

### Live Orders (kanban, real-time)
```
┌───────────────────────────────────────────────────────────────────────────┐
│  ☰  Kababjees   ● Live          🔔3   [ Today ▾ ]   🌙   owner@kababjees ▾ │
├───────────┬───────────────────────────────────────────────────────────────┤
│ ▸ Overview│  Live Orders                            🔊  Auto-accept: [off] │
│ ▸ Orders• │ ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌─────────────┐ ┌───────┐│
│ ▸ Menu    │ │ PLACED 3│ │ACCEPTED2│ │PREPARING4│ │OUT FOR DEL 1│ │DELIV 9││
│ ▸ Analytic│ │┌───────┐│ │┌───────┐│ │┌────────┐│ │┌───────────┐│ │       ││
│ ▸ Staff   │ ││#1284  ││ ││#1280  ││ ││#1277   ││ ││#1271      ││ │       ││
│ ▸ Settings│ ││2 items││ ││1 item ││ ││3 items ││ ││5 items    ││ │       ││
│           │ ││Rs 1040││ ││Rs 520 ││ ││Rs 1500 ││ ││Rs 2750    ││ │       ││
│           │ ││08:42  ││ ││08:39  ││ ││08:31   ││ ││08:20      ││ │       ││
│           │ ││[Accept]│ ││[Prep ]│ ││[Out ▶ ]│ ││[Delivered]││ │       ││
│           │ │└───────┘│ │└───────┘│ │└────────┘│ │└───────────┘│ │       ││
│           │ └─────────┘ └─────────┘ └──────────┘ └─────────────┘ └───────┘│
│           │  New order #1284 just arrived  ⟶ (toast + chime)               │
└───────────┴───────────────────────────────────────────────────────────────┘
```
Cards drag/click to advance status (optimistic, with rollback on error). New cards
animate in via WebSocket; a connection dot shows live/reconnecting.

### Order detail (drawer)
```
┌──────────────────────────── Order #1284 ───────────────────────────┐
│ Status:  ● Placed   →  [ Accept ]                                    │
│ Customer: Ahmed Khan   ☎ +9230••••  (revealed on click, audit-logged)│
│ Address:  House 12, Street 4, Gulshan, Karachi                       │
│ Channel:  WhatsApp · placed 08:42 · ETA 45–60m                       │
│ ─ Items ─────────────────────────────────────────────────────────── │
│   2 × Chicken Biryani        Rs 450     Rs 900                       │
│   1 × Garlic Naan            Rs 60      Rs 60                        │
│   Subtotal Rs 960 · Delivery Rs 80 · Tax Rs 0 · Total Rs 1040       │
│ ─ Timeline ───────────────────────────────────────────────────────  │
│   08:42 placed (agent) · — accepted · — preparing                    │
│ [ Print ]                         [ Cancel order ]  [ Accept ▶ ]     │
└─────────────────────────────────────────────────────────────────────┘
```

### Menu management
```
┌───────────────────────────────────────────────────────────────────────────┐
│  Menu                                  [ + Category ]   [ + Item ]          │
│  Categories: [ All ] [ BBQ ] [ Biryani ] [ Breads ] [ Drinks ]             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Item                 Category   Price    Available   Actions           │ │
│  │ Chicken Biryani      Biryani    Rs 450   [●ON ]      ✎  🗑             │ │
│  │ Seekh Kabab (2 pcs)  BBQ        Rs 400   [●ON ]      ✎  🗑             │ │
│  │ Garlic Naan          Breads     Rs 60    [ OFF]      ✎  🗑             │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│  Edit item (sheet): name, description, price, category, availability, image │
│  → On save: writes tenant DB + publishes to central catalog (agent updates) │
└───────────────────────────────────────────────────────────────────────────┘
```

### Overview (tenant) — analytics summary
```
┌───────────────────────────────────────────────────────────────────────────┐
│  Overview                                        [ This week ▾ ] [ ⚙ ]     │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐               │
│  │ Revenue    │ │ Orders     │ │ Avg order  │ │ Items sold │               │
│  │ Rs 184,200 │ │   312      │ │ Rs 590     │ │   968      │  (sparkline)  │
│  │ ▲ 12%      │ │ ▲ 8%       │ │ ▼ 2%       │ │ ▲ 9%       │               │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘               │
│  ┌────────────────────────────────┐ ┌────────────────────────────────────┐ │
│  │ Revenue over time (area)       │ │ Top items (horizontal bar)         │ │
│  └────────────────────────────────┘ └────────────────────────────────────┘ │
│  ┌────────────────────────────────┐ ┌────────────────────────────────────┐ │
│  │ Orders by status (donut)       │ │ Peak hours (heatmap/bar)           │ │
│  └────────────────────────────────┘ └────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
```

## 6.6 Component reuse for "same design, different data"

- A single `<DashboardLayout>` with configurable nav items (admin vs tenant).
- `<KpiCard>`, `<ChartCard>`, `<DataTable>`, `<StatusBadge>`, `<OrderCard>`,
  `<FilterBar>` are tenant-agnostic; they render whatever data the API returns for
  the current scope.
- Per-tenant theming via CSS variables loaded from tenant settings (accent + logo);
  no component forking. This guarantees visual consistency while feeling bespoke.

## 6.7 Frontend security & UX guardrails

- Access token in memory; refresh token in httpOnly cookie (frontend never reads it).
- All data fetched through the tenant-scoped API — the frontend cannot and does not
  select a tenant; the backend derives it from the JWT/host.
- Route guards by role; hide actions the role can't perform (and the API re-checks).
- Sensitive data (full phone) revealed on explicit click and audit-logged.
- Optimistic updates with rollback + toast on failure; skeletons for loading;
  empty states with helpful CTAs; error boundaries.
- ⌘K command palette for power users (jump to order #, switch view).

## 6.8 Optional: high-fidelity mockups

I can generate image mockups of these screens (admin overview, tenant kanban,
analytics) on request — the ASCII wireframes above are the spec they'd follow.

Proceed to [Phase 07 — Analytics](./07-analytics.md).
