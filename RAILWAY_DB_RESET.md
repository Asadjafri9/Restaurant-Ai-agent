# Railway — Reset to 3 Postgres databases

Keep **Restaurant-Watsapp-Ai-Automation** (agent) + **Redis** running.  
Remove old DBs, add 3 fresh ones.

## Step 1 — Delete in Railway dashboard

Open your project → for each service below: click it → **Settings** → scroll down → **Delete Service**

| Delete | Why |
|--------|-----|
| **Postgres** | Old shared DB |
| **Postgres-ptDP** | Old KFC DB |
| **worker** | Frees a slot on free plan (agent runs without it for now) |

**Keep:** `Restaurant-Watsapp-Ai-Automation`, `Redis`

## Step 2 — Add 3 new Postgres databases

Click **+ Add** → **Database** → **PostgreSQL** — do this **3 times**:

| Name (rename after create) | Purpose |
|----------------------------|---------|
| `postgres-admin` | Admin / central metadata (agent catalog, tenants registry) |
| `postgres-kfc` | KFC orders, menu, customers only |
| `postgres-kababjees` | Kababjees orders, menu, customers only |

To rename: click the new Postgres service → **Settings** → **Service name**.

## Step 3 — Wire agent + local env (run in terminal)

```powershell
cd "C:\Users\DELL\Desktop\ai agent"
railway login
powershell -ExecutionPolicy Bypass -File scripts/wire_agent_dbs.ps1
powershell -ExecutionPolicy Bypass -File scripts/fetch_local_env.ps1
```

This sets on the **agent** service:

- `DATABASE_URL_CENTRAL` → postgres-admin
- `DATABASE_URL_KFC` → postgres-kfc  
- `DATABASE_URL_KABABJEES` → postgres-kababjees

Then redeploys the agent and runs migrations + seed.

## Step 4 — Local portals

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_all_local.ps1
```

| Portal | URL | DB |
|--------|-----|-----|
| Admin | http://localhost:8001 | postgres-admin |
| KFC | http://localhost:8002 | postgres-kfc |
| Kababjees | http://localhost:8003 | postgres-kababjees |

## Logins

| Portal | Email | Password |
|--------|-------|----------|
| Admin | admin@platform.local | admin123 |
| KFC | owner@kfc.local | owner123 |
| Kababjees | owner@kababjees.local | owner123 |

## Free plan note

Max **5 services**: agent + Redis + 3 Postgres = **5** (worker removed). Upgrade to Hobby if you need worker back.
