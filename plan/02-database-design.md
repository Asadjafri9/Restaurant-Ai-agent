# Phase 02 — Database Design

Two distinct schemas:

- **Central Metadata DB** — one database for the whole platform (control plane).
- **Tenant DB schema** — *identical* schema instantiated once per restaurant
  (data plane). Same DDL, different data, separate databases & roles.

Conventions: `snake_case`, UUID v7 primary keys (time-sortable; fall back to
`gen_random_uuid()` if v7 unavailable), `timestamptz` everywhere (store UTC),
money as `NUMERIC(12,2)` (never floats), soft-delete via `deleted_at` where useful,
`created_at`/`updated_at` audit columns on every table.

---

## 2.1 Central Metadata DB

> Holds only what the platform needs to *route* and *sell*. **No order amounts,
> no balances, no revenue.** The routing index intentionally omits money.

```mermaid
erDiagram
    TENANTS ||--o{ TENANT_CONNECTIONS : has
    TENANTS ||--o{ USERS : has
    TENANTS ||--o{ CATALOG_ITEMS : publishes
    TENANTS ||--o{ WHATSAPP_NUMBERS : owns
    TENANTS ||--o{ ORDER_ROUTING_INDEX : routes
    USERS ||--o{ AUDIT_LOG : acts

    TENANTS {
        uuid id PK
        text slug UK "subdomain, unique"
        text name
        text owner_email
        text status "active|suspended|provisioning"
        text plan "free|pro"
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at
    }
    TENANT_CONNECTIONS {
        uuid id PK
        uuid tenant_id FK
        text db_host
        int  db_port
        text db_name
        text db_role
        bytea db_password_enc "Fernet/KMS encrypted"
        text  pool_class "default|dedicated"
        timestamptz created_at
        timestamptz updated_at
    }
    USERS {
        uuid id PK
        uuid tenant_id FK "null for platform admins"
        text email UK
        text password_hash "argon2id"
        text role "platform_admin|owner|manager|staff"
        bool is_active
        timestamptz last_login_at
        timestamptz created_at
        timestamptz updated_at
    }
    CATALOG_ITEMS {
        uuid id PK
        uuid tenant_id FK
        uuid tenant_item_id "id in tenant DB (link)"
        text name
        text description
        text category
        numeric price "current sell price"
        bool is_available
        int  sort_order
        timestamptz published_at
        timestamptz updated_at
    }
    WHATSAPP_NUMBERS {
        uuid id PK
        uuid tenant_id FK "null = central shared number"
        text phone_number_id UK "Meta phone_number_id"
        text display_number
        bool is_active
    }
    ORDER_ROUTING_INDEX {
        uuid id PK "== order_id in tenant DB"
        uuid tenant_id FK
        text status "placed|accepted|preparing|out_for_delivery|delivered|cancelled"
        text customer_phone_hash "hashed, not raw"
        text idempotency_key UK
        timestamptz placed_at
        timestamptz updated_at
    }
    AUDIT_LOG {
        uuid id PK
        uuid actor_user_id FK
        uuid tenant_id "nullable"
        text action
        text entity
        text entity_id
        jsonb metadata "no secrets/PII raw"
        inet ip
        timestamptz created_at
    }
    AGENT_CONVERSATIONS {
        uuid id PK
        text customer_phone_hash
        uuid active_tenant_id "nullable"
        text state "greeting|browsing|ordering|confirming|done"
        timestamptz last_message_at
        timestamptz created_at
    }
```

### Notes & rationale (central)
- **`tenant_connections.db_password_enc`** is encrypted with a Fernet key (or KMS)
  held only in the control-plane env. Compromising the central DB dump alone does
  not yield tenant DB access (key is separate). See P08.
- **`order_routing_index`** stores **status + timestamps + hashed phone + idempotency
  key only**. No `total`, no `amount`. This is what lets central "track orders" while
  honoring "central does not have balance/money."
- **`catalog_items`** is the agent's menu source. `price` lives here because the agent
  must quote prices — prices are *menu metadata*, which the brief explicitly allows
  ("menu, price"). It is **not** revenue/balance.
- **`customer_phone_hash`**: store HMAC-SHA256(phone, pepper), never raw phone in
  central, to minimize PII centrally (the raw phone for delivery lives in tenant DB).
- **`users.tenant_id` null** → platform admin. RBAC enforced in app + checked in P08.
- **Indexes:** `tenants(slug)`, `users(email)`, `catalog_items(tenant_id, is_available)`,
  `order_routing_index(tenant_id, status, placed_at desc)`, `whatsapp_numbers(phone_number_id)`.

---

## 2.2 Tenant DB schema (one per restaurant — identical DDL)

> This is the restaurant's private world: full order details, customer delivery
> info, money, and analytics source data. No other tenant — and not even the
> central admin role — can read this database.

```mermaid
erDiagram
    MENU_CATEGORIES ||--o{ MENU_ITEMS : groups
    MENU_ITEMS ||--o{ ORDER_ITEMS : ordered_as
    CUSTOMERS ||--o{ ORDERS : places
    ORDERS ||--o{ ORDER_ITEMS : contains
    ORDERS ||--o{ ORDER_STATUS_HISTORY : tracks
    STAFF_USERS ||--o{ ORDER_STATUS_HISTORY : updates

    RESTAURANT_PROFILE {
        uuid id PK
        text name
        text owner_email
        text phone
        text address
        text currency "PKR"
        jsonb business_hours
        jsonb settings "prep time, delivery fee, tax %"
        timestamptz updated_at
    }
    MENU_CATEGORIES {
        uuid id PK
        text name
        int  sort_order
        bool is_active
    }
    MENU_ITEMS {
        uuid id PK
        uuid category_id FK
        text name
        text description
        numeric price
        bool is_available
        text image_url
        int  sort_order
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at
    }
    CUSTOMERS {
        uuid id PK
        text phone "raw, for delivery/contact"
        text name
        jsonb addresses
        int  orders_count
        timestamptz first_seen_at
        timestamptz last_order_at
    }
    ORDERS {
        uuid id PK "== central routing id"
        uuid customer_id FK
        text channel "whatsapp"
        text status
        numeric subtotal
        numeric delivery_fee
        numeric tax
        numeric total
        text delivery_address
        text notes
        text idempotency_key UK
        text source_agent "agent version"
        timestamptz placed_at
        timestamptz accepted_at
        timestamptz delivered_at
        timestamptz updated_at
    }
    ORDER_ITEMS {
        uuid id PK
        uuid order_id FK
        uuid menu_item_id FK "nullable if item later deleted"
        text item_name_snapshot "name at order time"
        numeric unit_price_snapshot
        int  quantity
        numeric line_total
        text modifiers
    }
    ORDER_STATUS_HISTORY {
        uuid id PK
        uuid order_id FK
        text from_status
        text to_status
        uuid changed_by FK "staff_users.id, nullable for agent"
        text source "agent|dashboard|system"
        timestamptz created_at
    }
    STAFF_USERS {
        uuid id PK
        text email
        text role "owner|manager|staff"
        bool is_active
        timestamptz created_at
    }
    DAILY_SALES_ROLLUP {
        date day PK
        int  orders_count
        numeric gross_revenue
        numeric avg_order_value
        int  items_sold
        jsonb by_status
        timestamptz refreshed_at
    }
```

### Notes & rationale (tenant)
- **Price snapshots** (`item_name_snapshot`, `unit_price_snapshot`) on order items so
  later menu price edits never rewrite historical order totals (correct analytics).
- **`orders.id == order_routing_index.id`**: same UUID generated by the routing
  service, so central can correlate status without ever holding amounts.
- **`idempotency_key`** unique → safe retries from the agent (no duplicate orders).
- **`daily_sales_rollup`** is a pre-aggregated table (refreshed by a job or trigger)
  powering fast analytics; raw tables remain the source. See P07.
- **`staff_users`** lets a restaurant invite its own staff; their auth is still via
  central `users` (single login), but role/permission scoping is per tenant.
- **Money columns** (`subtotal/total/tax/...`) exist **only here**, satisfying the
  "central has no balance" rule.

---

## 2.3 Provisioning a new tenant (onboarding)

Sequence executed by the Central API during admin onboarding (idempotent, audited):

```mermaid
sequenceDiagram
    participant Admin
    participant API as Central API
    participant PG as Postgres (cluster)
    participant Mig as Alembic (tenant migrations)
    participant Reg as central.tenant_connections

    Admin->>API: POST /admin/tenants {name, owner_email, slug}
    API->>PG: CREATE ROLE tenant_<slug> LOGIN PASSWORD <random>
    API->>PG: CREATE DATABASE tdb_<slug> OWNER tenant_<slug>
    API->>PG: REVOKE CONNECT ON DATABASE tdb_<slug> FROM PUBLIC
    API->>PG: GRANT CONNECT ON tdb_<slug> TO tenant_<slug> (only)
    API->>Mig: run tenant migrations on tdb_<slug>
    API->>Reg: INSERT connection row (password Fernet-encrypted)
    API->>API: seed restaurant_profile + default categories
    API-->>Admin: tenant ready (status=active)
```

Hardening during provisioning (see P12 F2):
- **Privilege separation:** provisioning runs on the **worker** service using a
  dedicated, narrowly-scoped `provisioner` DB role that can `CREATE DATABASE/ROLE`
  but nothing else. The web-facing Central API never holds DB-admin credentials — it
  only enqueues an admin-authorized, audited provisioning job (optionally gated by
  manual approval in production).
- Generate a strong random password per tenant role; never reuse.
- `REVOKE CONNECT ... FROM PUBLIC` and grant only to the tenant role → other
  tenant roles cannot even connect to this database.
- The central/admin app role has **no privileges** on tenant databases (it talks to
  tenants only through the Order Routing Service using each tenant's own role).
- All steps wrapped so a failure rolls back/cleans up partial artifacts.

## 2.4 Migrations strategy

- Two Alembic migration trees: `migrations/central` and `migrations/tenant`.
- `migrations/tenant` is applied to **every** tenant DB. A "migrate all tenants"
  command iterates the registry and runs upgrades (with concurrency limit + retries).
- Schema changes must be **backward compatible** during rollout (expand/contract
  pattern) because tenants migrate sequentially, not atomically.
- Version drift detection: a health check compares each tenant's Alembic head to the
  expected head and flags stragglers in the admin dashboard.

## 2.5 Indexing & performance (DB layer)

Tenant DB hot paths and indexes:
- `orders(status, placed_at desc)` — live order board + filtering.
- `orders(placed_at)` — analytics time ranges.
- `order_items(order_id)`, `order_items(menu_item_id)` — joins + top-items.
- `customers(phone)` — repeat-customer lookup by agent.
- `menu_items(category_id, is_available)` — menu rendering.
- Partial index `orders(status) WHERE status IN ('placed','accepted','preparing')`
  for the active queue.

General:
- Use `NUMERIC` for money; `BIGINT`/counters for rollups.
- Connection pools sized per tenant tier (P09); avoid pool explosion across many tenants.
- `daily_sales_rollup` + optional materialized views for heavy charts (P07).

## 2.6 Data retention & PII

- Central: store only hashed customer phone; purge `agent_conversations` after N days.
- Tenant: raw customer phone/address retained per the restaurant's needs; provide a
  data-deletion routine for GDPR-style "delete my data" requests (delete from tenant
  DB + central hash). See P08.

Proceed to [Phase 03 — Backend API](./03-backend-api.md).
