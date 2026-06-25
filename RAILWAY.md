# Railway Deployment Guide

## 1. Create services

In your Railway project ([Restaurant-Ai-agent](https://github.com/Asadjafri9/Restaurant-Ai-agent)):

1. **PostgreSQL** — Add plugin, copy `DATABASE_URL`
2. **Redis** — Add plugin, copy `REDIS_URL`
3. **api-web** — Deploy from GitHub, uses root `Procfile`
4. **worker** — Same repo, start command: `python -m app.worker`
5. **frontend** (M5+) — Build `frontend/`, serve static

## 2. Environment variables (api-web + worker)

| Variable | Source |
|----------|--------|
| `DATABASE_URL_CENTRAL` | Postgres `DATABASE_URL` |
| `REDIS_URL` | Redis plugin URL |
| `JWT_SECRET` | Generate: `openssl rand -hex 32` |
| `FERNET_KEY` | Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `WHATSAPP_APP_SECRET` | Meta App Dashboard → App Secret |
| `TENANT_DB_HOST` | Parse from Postgres URL host |
| `TENANT_DB_PORT` | `5432` |
| `TENANT_DB_ADMIN_URL` | Same as `DATABASE_URL_CENTRAL` (superuser for provisioning) |
| `ALLOWED_ORIGINS` | Your frontend URL(s), comma-separated |

Plus existing: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `GEMINI_API_KEY`.

## 3. Deploy

Push to `main` — Railway runs `release: alembic upgrade head` then starts `web`.

## 4. Webhook URL

Set Meta webhook to: `https://<your-railway-domain>/webhook`
