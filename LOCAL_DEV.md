# Local dev — 3 portals on different ports, Railway DBs + agent

## Architecture

| What | Where | URL |
|------|-------|-----|
| **AI Agent + WhatsApp** | Railway | https://restaurant-watsapp-ai-automation-production.up.railway.app |
| **Admin dashboard** | Local :8001 | http://localhost:8001 |
| **KFC dashboard** | Local :8002 | http://localhost:8002 |
| **Kababjees dashboard** | Local :8003 | http://localhost:8003 |

## Railway databases (3 Postgres plugins)

| Railway service | Used for | Local port |
|-----------------|----------|------------|
| `Postgres` | Admin / central metadata | 8001 |
| `Postgres-ptDP` | KFC data only | 8002 |
| `postgres-kababjees` | Kababjees data only | 8003 |

You already have **Postgres** and **Postgres-ptDP**. To add the third:

1. Railway dashboard → delete **worker** (frees 1 slot on free plan)
2. **+ Add** → **Database** → **PostgreSQL** → name it `postgres-kababjees`

## One-time setup

```powershell
cd "C:\Users\DELL\Desktop\ai agent"
pip install -r requirements.txt
railway login
powershell -ExecutionPolicy Bypass -File scripts/fetch_local_env.ps1
```

## Run all 3 local websites

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_all_local.ps1
```

Or run individually in 3 terminals:

```powershell
powershell -File scripts/run_admin.ps1      # :8001
powershell -File scripts/run_kfc.ps1        # :8002
powershell -File scripts/run_kababjees.ps1  # :8003
```

## Logins

| Portal | URL | Email | Password |
|--------|-----|-------|----------|
| Admin | :8001 | admin@platform.local | admin123 |
| KFC | :8002 | owner@kfc.local | owner123 |
| Kababjees | :8003 | owner@kababjees.local | owner123 |

## Wire agent to tenant DBs (Railway)

On **Restaurant-Watsapp-Ai-Automation** set:

```
SERVICE_MODE=agent
DATABASE_URL_KFC=<Postgres-ptDP DATABASE_PUBLIC_URL>
DATABASE_URL_KABABJEES=<postgres-kababjees DATABASE_PUBLIC_URL>
```

Then redeploy agent. The agent places orders into each tenant's isolated Railway Postgres.

## Redis

Local portals use Railway **Redis** (public URL) for live order WebSockets — fetched automatically by `fetch_local_env.ps1`.
