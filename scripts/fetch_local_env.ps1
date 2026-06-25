# Pull Railway connection strings into local/*.env (run once after login: railway login)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/fetch_local_env.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$localDir = Join-Path $root "local"
if (-not (Test-Path $localDir)) { New-Item -ItemType Directory -Path $localDir | Out-Null }

function Get-RailwayVar($service, $name) {
    try {
        $json = railway variables --service $service --json 2>$null | ConvertFrom-Json
        return $json.$name
    } catch {
        return $null
    }
}

$jwt = Get-RailwayVar "Restaurant-Watsapp-Ai-Automation" "JWT_SECRET"
$fernet = Get-RailwayVar "Restaurant-Watsapp-Ai-Automation" "FERNET_KEY"
$redis = Get-RailwayVar "Redis" "REDIS_PUBLIC_URL"

# Admin DB
$adminDb = Get-RailwayVar "postgres-admin" "DATABASE_PUBLIC_URL"
if (-not $adminDb) { $adminDb = Get-RailwayVar "Postgres" "DATABASE_PUBLIC_URL" }
# KFC DB
$kfcDb = Get-RailwayVar "postgres-kfc" "DATABASE_PUBLIC_URL"
if (-not $kfcDb) { $kfcDb = Get-RailwayVar "Postgres-3p8I" "DATABASE_PUBLIC_URL" }
# Kababjees DB
$kababDb = Get-RailwayVar "postgres-kababjees" "DATABASE_PUBLIC_URL"
if (-not $kababDb) { $kababDb = Get-RailwayVar "Postgres-A4-B" "DATABASE_PUBLIC_URL" }

if (-not $adminDb -or -not $kfcDb) {
    Write-Host "ERROR: Could not fetch Postgres URLs. Run: railway login" -ForegroundColor Red
    exit 1
}

@"
SERVICE_MODE=admin
ENVIRONMENT=development
DATABASE_URL_CENTRAL=$adminDb
JWT_SECRET=$jwt
FERNET_KEY=$fernet
REDIS_URL=$redis
ALLOWED_ORIGINS=http://localhost:8001,http://localhost:8002,http://localhost:8003
"@ | Set-Content -Encoding utf8 "$localDir\admin.env"

@"
SERVICE_MODE=kfc
ENVIRONMENT=development
DATABASE_URL=$kfcDb
TENANT_ID=8c83eeeb-d7ee-5c0c-8ff7-30f1751134f6
JWT_SECRET=$jwt
REDIS_URL=$redis
ALLOWED_ORIGINS=http://localhost:8001,http://localhost:8002,http://localhost:8003
"@ | Set-Content -Encoding utf8 "$localDir\kfc.env"

if ($kababDb) {
@"
SERVICE_MODE=kababjees
ENVIRONMENT=development
DATABASE_URL=$kababDb
TENANT_ID=fa19b25a-09cd-5e68-9166-1a7459f69b09
JWT_SECRET=$jwt
REDIS_URL=$redis
ALLOWED_ORIGINS=http://localhost:8001,http://localhost:8002,http://localhost:8003
"@ | Set-Content -Encoding utf8 "$localDir\kababjees.env"
    Write-Host "OK: local/kababjees.env" -ForegroundColor Green
} else {
@"
# Create postgres-kababjees on Railway, then re-run fetch_local_env.ps1
# SERVICE_MODE=kababjees
# DATABASE_URL=postgresql://...
"@ | Set-Content -Encoding utf8 "$localDir\kababjees.env.example"
    Write-Host "WARN: No kababjees Postgres yet - add postgres-kababjees on Railway, then re-run this script" -ForegroundColor Yellow
}

Write-Host "OK: local/admin.env  -> port 8001" -ForegroundColor Green
Write-Host "OK: local/kfc.env     -> port 8002" -ForegroundColor Green
Write-Host ""
Write-Host "Agent on Railway should use:" -ForegroundColor Cyan
Write-Host "  DATABASE_URL_CENTRAL = (Postgres internal URL)"
Write-Host "  DATABASE_URL_KFC     = $kfcDb"
if ($kababDb) { Write-Host "  DATABASE_URL_KABABJEES = $kababDb" }
