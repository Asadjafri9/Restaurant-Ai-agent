# Railway — Split Services Architecture

Each portal runs as its **own Railway web service** with its **own Postgres plugin**.

## Topology

| Service | SERVICE_MODE | Postgres plugin | Purpose |
|---------|--------------|-----------------|---------|
| `Restaurant-Watsapp-Ai-Automation` | `agent` | Postgres (central) | WhatsApp webhook, AI agent, worker |
| `admin-web` | `admin` | `postgres-admin` | Platform admin UI + metadata DB |
| `kfc-web` | `kfc` | `postgres-kfc` | KFC dashboard + isolated KFC data |
| `kababjees-web` | `kababjees` | `postgres-kababjees` | Kababjees dashboard + isolated data |
| `worker` | — | — | Background jobs (links central + Redis) |
| `Redis` | — | — | Shared cache, sessions, real-time |

Delete the unused `fantastic-learning` service from the Railway dashboard.

## One-time setup (Railway CLI)

```bash
# 1. Add databases
railway add --database postgres --service postgres-admin
railway add --database postgres --service postgres-kfc
railway add --database postgres --service postgres-kababjees

# 2. Add web services (same repo)
railway add --service admin-web --repo <your-github-repo>
railway add --service kfc-web --repo <your-github-repo>
railway add --service kababjees-web --repo <your-github-repo>

# 3. Agent service (existing)
railway service Restaurant-Watsapp-Ai-Automation
railway variables set SERVICE_MODE=agent
# DATABASE_URL_CENTRAL = existing Postgres URL
# DATABASE_URL_KFC = postgres-kfc internal URL
# DATABASE_URL_KABABJEES = postgres-kababjees internal URL

# 4. Admin web
railway service admin-web
railway variables set SERVICE_MODE=admin
railway variables set DATABASE_URL='${{postgres-admin.DATABASE_URL}}'
railway variables set JWT_SECRET='<same-as-agent>'
railway variables set FERNET_KEY='<same-as-agent>'

# 5. KFC web
railway service kfc-web
railway variables set SERVICE_MODE=kfc
railway variables set DATABASE_URL='${{postgres-kfc.DATABASE_URL}}'
railway variables set REDIS_URL='${{Redis.REDIS_URL}}'
railway variables set JWT_SECRET='<same-as-agent>'
railway variables set TENANT_ID=8c83eeeb-d7ee-5c0c-8ff7-30f1751134f6

# 6. Kababjees web
railway service kababjees-web
railway variables set SERVICE_MODE=kababjees
railway variables set DATABASE_URL='${{postgres-kababjees.DATABASE_URL}}'
railway variables set REDIS_URL='${{Redis.REDIS_URL}}'
railway variables set JWT_SECRET='<same-as-agent>'
railway variables set TENANT_ID=fa19b25a-09cd-5e68-9166-1a7459f69b09
```

Each web service uses `bash scripts/start.sh` (dispatches by `SERVICE_MODE`).

## URLs after deploy

| Portal | URL |
|--------|-----|
| Agent / API | `https://<agent-service>.up.railway.app` |
| Admin | `https://<admin-web>.up.railway.app/` |
| KFC | `https://<kfc-web>.up.railway.app/` |
| Kababjees | `https://<kababjees-web>.up.railway.app/` |

## Logins (per service)

| Service | Email | Password |
|---------|-------|----------|
| admin-web | `admin@platform.local` | `admin123` |
| kfc-web | `owner@kfc.local` | `owner123` |
| kababjees-web | `owner@kababjees.local` | `owner123` |

Accounts exist only in that service's database — cross-login is impossible.
