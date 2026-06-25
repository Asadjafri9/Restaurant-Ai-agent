# Phase 07 — Analytics (Filtered & Unfiltered)

Two analytics scopes, by design:

- **Tenant analytics (rich, financial):** computed from the tenant's own DB. Full
  revenue, AOV, top items, etc.
- **Central admin analytics (operational, money-free):** computed from the central
  routing index + catalog. Counts, volumes, agent performance — **no revenue**,
  honoring "central has no balance."

## 7.1 Tenant metrics catalog

| Metric | Definition | Chart |
|--------|-----------|-------|
| Revenue | Σ `orders.total` where status not cancelled | KPI + area/line timeseries |
| Orders count | count of orders | KPI + bar timeseries |
| Average order value (AOV) | revenue / orders | KPI + line |
| Items sold | Σ `order_items.quantity` | KPI |
| Top items | rank by qty or revenue | horizontal bar |
| Orders by status | distribution across statuses | donut/stacked bar |
| Peak hours | orders grouped by hour-of-day | heatmap / bar |
| Peak days | orders by day-of-week | bar |
| New vs returning customers | first-time vs repeat | stacked bar |
| Fulfillment time | avg(`delivered_at` − `placed_at`) | KPI + line |
| Cancellation rate | cancelled / total | KPI |
| Revenue by category | join items→categories | bar/treemap |
| Avg items per order | items / orders | KPI |

### Comparisons & deltas
Each KPI shows a delta vs the previous comparable period (e.g., "▲ 12% vs last
week"). Computed by querying current vs prior range.

## 7.2 Filters (filtered vs unfiltered)

The brief wants both. Default views are **unfiltered** (whole selected period);
users can drill down with filters:

- **Date range** (presets: Today, 7d, 30d, This month, Custom) — primary filter.
- **Granularity** (hour/day/week/month) — drives timeseries buckets.
- **Status** (include/exclude statuses; default excludes cancelled for revenue).
- **Category** and **specific item**.
- **Channel** (currently WhatsApp; future-proofed).
- **Customer type** (new vs returning).

Filters are encoded in the URL/query params so views are shareable/bookmarkable and
the back button works. "Unfiltered" = the period total with no secondary filters.

## 7.3 Aggregation strategy (performance)

Three tiers, chosen by query cost:

1. **Live SQL aggregates** for small/medium ranges — parameterized `GROUP BY` queries
   with the indexes from P02 §2.5. Cheap and always fresh.
2. **`daily_sales_rollup` table** for long ranges (e.g., last 90 days, year): a
   nightly + incremental job (or trigger on order delivery) updates per-day rollups.
   Long-range charts read the rollup instead of scanning all orders.
3. **Materialized views** (optional) for expensive cross-cuts (top items over 90d),
   refreshed on a schedule (`REFRESH MATERIALIZED VIEW CONCURRENTLY`).

Caching: analytics responses cached in Redis (`analytics:{tenant}:{range}:{filters}`)
with short TTL (60–300s) + invalidated on new delivered order. Charts feel instant.

Example timeseries query (illustrative, tenant DB, parameterized):
```sql
SELECT date_trunc(:granularity, placed_at) AS bucket,
       count(*)              AS orders,
       sum(total)            AS revenue,
       avg(total)            AS aov
FROM orders
WHERE placed_at >= :from AND placed_at < :to
  AND status <> 'cancelled'
GROUP BY 1
ORDER BY 1;
```

## 7.4 API → chart mapping

| Endpoint | Returns | Frontend chart (Recharts) |
|----------|---------|---------------------------|
| `GET /analytics/summary` | KPIs + deltas | `<KpiCard>` row |
| `GET /analytics/revenue-timeseries` | `[{bucket, revenue, orders, aov}]` | Area/Line + toggle |
| `GET /analytics/top-items` | `[{item, qty, revenue}]` | Horizontal Bar |
| `GET /analytics/orders-by-status` | `[{status, count}]` | Donut/Pie |
| `GET /analytics/peak-hours` | `[{hour, count}]` (or day×hour matrix) | Bar/Heatmap |
| `GET /analytics/customers` | `[{bucket, new, returning}]` | Stacked Bar |
| `GET /analytics/fulfillment` | `[{bucket, avg_minutes}]` | Line |

All accept `from`, `to`, and optional `granularity`, `status`, `category`, `item`.

## 7.5 Central admin analytics (money-free)

Computed from `order_routing_index` + `tenants` + `agent_conversations`:

| Metric | Source | Note |
|--------|--------|------|
| Active tenants | `tenants.status` | — |
| Platform order volume | count of routing index rows | counts only, **no totals** |
| Orders by status (all tenants) | routing index | operational |
| Orders per tenant | routing index group by tenant | leaderboard by *volume*, not revenue |
| Agent sessions / outcomes | `agent_conversations` | conversion to order |
| Agent latency p50/p95 | agent metrics (P11) | SLO tracking |
| Error rate | logs/metrics | reliability |

This keeps the central plane useful for operations while structurally unable to show
tenant money.

## 7.6 Chart UX details

- Responsive Recharts with shared color tokens (status colors match P06).
- Tooltips with formatted currency (PKR) and counts; tabular numerals.
- Loading skeletons; empty states ("No orders in this range"); error fallback.
- **Accessibility:** every chart has an accessible name + a "view as table" toggle
  for screen-reader users and CSV export.
- **Export:** CSV/PNG export per chart; "export report" bundles the current filtered
  view (useful for owners).
- Date range + granularity persist in URL; switching tenants (admin) or periods is
  instant from cache.

## 7.7 Privacy & correctness

- Tenant analytics never cross tenants (queries run on that tenant's DB only).
- Historical correctness via order-time price snapshots (P02) — past revenue doesn't
  change when menu prices change.
- Cancelled/refunded handling explicit in every revenue metric (excluded by default,
  toggleable).

Proceed to [Phase 08 — Security](./08-security.md).
