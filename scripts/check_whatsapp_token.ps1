# Verify WhatsApp token before sync/deploy.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/check_whatsapp_token.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

python -c @"
import asyncio
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)
from app.config.settings import get_settings

get_settings.cache_clear()
from app.config.settings import settings
from app.services.whatsapp_service import verify_whatsapp_token

ok, err = asyncio.run(verify_whatsapp_token())
print('whatsapp_token_valid:', ok)
if err:
    print('error:', err[:300])
elif ok:
    token = settings.whatsapp_access_token.strip()
    async def expiry_hint():
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f'https://graph.facebook.com/{settings.whatsapp_api_version}/debug_token',
                params={'input_token': token, 'access_token': token},
            )
            exp = r.json().get('data', {}).get('expires_at', 0)
            if exp and int(exp) > 0:
                hrs = (int(exp) - int(time.time())) / 3600
                when = datetime.fromtimestamp(int(exp), tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                print(f'token_expires: {when} ({hrs:.1f}h remaining)')
                if hrs < 48:
                    print('warning: temporary token — create a permanent System User token in Meta Business Settings')
            else:
                print('token_expires: never (permanent)')
    asyncio.run(expiry_hint())
raise SystemExit(0 if ok else 1)
"@

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Fix: Meta Developer Console -> WhatsApp -> API Setup -> Generate access token" -ForegroundColor Yellow
    Write-Host "     Paste into .env as WHATSAPP_ACCESS_TOKEN, then run scripts/sync_env_to_railway.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host "WhatsApp token OK" -ForegroundColor Green
