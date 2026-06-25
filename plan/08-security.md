# Phase 08 — Security

Security is the make-or-break of a multi-tenant platform. A single cross-tenant
leak is catastrophic. This phase defines the threat model and concrete controls.

## 8.1 Threat model (STRIDE-ish, prioritized)

| # | Threat | Example | Impact | Priority |
|---|--------|---------|--------|:--:|
| T1 | **Cross-tenant data access** | Tenant A reads B's orders via bug/IDOR | Catastrophic | P0 |
| T2 | **Broken auth / token misuse** | Stolen/forged JWT, replay across tenant | High | P0 |
| T3 | **Webhook forgery** | Attacker posts fake WhatsApp events | High | P0 |
| T4 | **Prompt injection / LLM abuse** | "Show other restaurant's data / change price" | High | P0 |
| T5 | **Secret leakage** | Tenant DB creds in logs/repo | Catastrophic | P0 |
| T6 | **SQL injection** | Crafted input in queries | High | P1 |
| T7 | **IDOR** | `/orders/{id}` for another tenant's order | High | P1 |
| T8 | **DoS / cost abuse** | Spam webhook, LLM cost blowup | Medium | P1 |
| T9 | **PII exposure** | Customer phone/address leaked | High | P1 |
| T10 | **Privilege escalation** | staff → owner/admin | High | P1 |
| T11 | **XSS/CSRF** | Malicious menu text, cookie misuse | Medium | P1 |
| T12 | **Supply chain** | Vulnerable dependency | Medium | P2 |

## 8.2 Tenant isolation (T1, T7) — defense in depth

Four independent layers, each sufficient to block most leaks; together, robust:

1. **Physical DB separation.** Database-per-tenant + per-tenant DB role with
   `CONNECT` revoked from `PUBLIC` and granted only to that tenant's role (P02 §2.3).
   The central/admin app role has **no** privileges on any tenant DB. No FDW/dblink
   is ever configured, so cross-database reads are impossible at the engine level.
2. **Connection routing chokepoint.** Only the **Order Routing Service** connects to
   tenant DBs, always via the resolved tenant's own role. A unit of work is bound to
   exactly one tenant; the `TenantContext` cannot reference two tenants.
3. **Application authz.** `tenant_id` comes from the verified JWT (never from client
   body/query). Subdomain must match the token's tenant. Every tenant query is
   implicitly scoped because the session is already the tenant's DB. IDOR on
   `/orders/{id}` fails because the lookup runs in the tenant DB — another tenant's id
   simply doesn't exist there.
4. **Isolation tests in CI.** Automated tests assert tenant A's session cannot read
   B's rows and that B's DB role cannot connect to A's DB (P10). A failing isolation
   test blocks deploy.

## 8.3 Authentication & session security (T2, T10)

- Passwords hashed with **argon2id** (memory-hard); never store plaintext.
- **JWT** access tokens short-lived (~15 min), signed (HS256 with strong secret or
  RS256). Claims include `tenant_id`/`role`; validated on every request.
- **Refresh tokens**: httpOnly + Secure + SameSite=strict cookies, rotating, with
  **reuse detection** (revoke family on replay). Stored/denylisted in Redis by `jti`.
- **Cookie host scoping (see P12 F6):** refresh cookies are scoped to the **exact
  host** (`kababjees.app.com`), never the parent domain, so one tenant subdomain can
  never carry another scope's cookie. The refresh `jti` is bound to `tenant_id` and
  tenant/host is re-validated on every refresh.
- **RBAC deny-by-default**; `require_role` on every protected route. Role changes are
  audited. Staff cannot grant themselves higher roles (server enforces).
- Login throttling + lockout/backoff on repeated failures (Redis).
- Optional 2FA (TOTP) for owners/admins (roadmap).

## 8.4 Webhook security (T3)

- **Verify `X-Hub-Signature-256`** = HMAC-SHA256(raw request body, `WHATSAPP_APP_SECRET`)
  on every `POST /webhook`; reject mismatch (403). (Must be added — not in current code.)
- Keep the **verify-token** check on `GET /webhook` (already present).
- Validate payload shape defensively (current code already returns 200 on malformed
  input — keep, but now also signature-gate before processing).
- **Idempotency:** dedupe by `message.id` (Redis TTL) to ignore Meta redeliveries.

## 8.5 LLM / agent security (T4)

- **Capability confinement:** the agent acts only through 4 tools, each tenant-scoped
  server-side. No tool can read money or another tenant's data; there is literally no
  function to leak it.
- **Tenant lock:** once a conversation's `active_tenant_id` is set, order/status tools
  refuse other tenants regardless of model output.
- **Server computes prices/totals** from the catalog; the model never sets money.
- **Input bounds & sanitization:** quantities, name/address lengths capped; strip
  control chars; reject obviously malicious payloads.
- **No secrets in prompts**; prompts contain only the selected tenant's menu + rules.
- **Per-phone rate limits** to cap spend and abuse; global LLM budget alarms.
- **Logging hygiene:** store hashed phone + metadata, not full transcripts with PII in
  central; redact addresses in any analytics derived from chat.

## 8.6 Secrets management (T5)

- All secrets in **Railway environment variables**; nothing in the repo. `.gitignore`
  already excludes `.env` — keep, and add a secret-scanning CI check.
- **Tenant DB passwords encrypted at rest** in `tenant_connections.db_password_enc`
  using **Fernet** (key in env) or a KMS. The encryption key is *separate* from the
  central DB, so a central DB dump alone does not yield tenant access.
- Rotate: WhatsApp token, JWT secret, Fernet key (with envelope re-encryption job),
  and per-tenant DB passwords (rotation routine updates role + registry atomically).
- Logs/metrics scrub tokens, passwords, connection strings, and full phone numbers.

## 8.7 Injection & input validation (T6, T11)

- **SQLAlchemy parameterized** queries / ORM only; never string-format SQL. Dynamic
  DDL in provisioning uses strict allow-listed identifiers (slug regex `^[a-z0-9-]+$`).
- **Pydantic v2** validates every request body (types, bounds, enums).
- **XSS:** React escapes by default; sanitize any rich text; never `dangerouslySetInnerHTML`
  for user/menu content. Set a strict **Content-Security-Policy**.
- **CSRF:** cookie-based refresh uses double-submit token; APIs use Bearer header.
- **CORS:** strict allow-list of known origins (admin + tenant subdomains); no `*`.

## 8.8 DoS & abuse (T8)

- **Rate limiting** (Redis) per IP, per user, per phone, per endpoint class
  (auth, webhook, analytics). 429 with `Retry-After`.
- Request size limits; pagination caps; query timeouts on analytics.
- LLM and WhatsApp **cost budgets** with alerts; circuit breakers + fallbacks.
- Connection-pool caps to prevent a noisy tenant exhausting Postgres.

## 8.9 PII & compliance (T9)

- **Data minimization centrally:** central stores hashed phone only; raw phone/address
  live in the tenant DB (where delivery actually happens).
- **Right to erasure:** a routine deletes a customer's data from the tenant DB and the
  central hash on request.
- **Retention:** expire `agent_conversations` and webhook dedupe keys; configurable
  order retention per tenant.
- **Transport security:** HTTPS/TLS everywhere (Railway-provided); HSTS; secure cookies.
- **At rest:** rely on Railway Postgres encryption; sensitive central column
  (DB password) additionally app-encrypted.

## 8.10 Supply chain & ops (T12)

- Pin dependencies; enable Dependabot/`pip-audit` and `npm audit` in CI.
- Container/base image scanning; minimal images.
- Least-privilege service tokens; separate envs (dev/stage/prod) with separate secrets.
- Audit log (`central.audit_log`) for sensitive actions (provisioning, role changes,
  PII reveal, suspensions) with `request_id`, actor, IP.

## 8.11 Security checklist (gate before launch)

- [ ] DB-per-tenant + per-tenant roles; `PUBLIC` connect revoked; admin role has no
      tenant-DB privileges.
- [ ] Isolation tests pass in CI (cross-tenant read + cross-DB connect denied).
- [ ] JWT + refresh rotation + reuse detection; RBAC deny-by-default.
- [ ] Webhook HMAC signature verification + idempotency.
- [ ] Tenant creds encrypted at rest with a separate key; rotation routine exists.
- [ ] No secrets in repo/logs; secret scanning in CI.
- [ ] Parameterized queries; Pydantic validation; strict CORS + CSP; CSRF for cookies.
- [ ] Rate limiting on auth/webhook/analytics; cost budgets + alerts.
- [ ] LLM capability confinement + tenant lock + server-side pricing.
- [ ] PII minimization, erasure routine, retention jobs.
- [ ] Audit logging for sensitive actions.
- [ ] Dependency scanning enabled.

Proceed to [Phase 09 — Deployment & Ops](./09-deployment-railway-ops.md).
