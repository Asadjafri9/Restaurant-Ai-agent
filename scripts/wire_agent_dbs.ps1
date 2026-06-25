# Wire agent to 3 Postgres services and redeploy
# Run AFTER creating postgres-admin, postgres-kfc, postgres-kababjees in Railway dashboard

$ErrorActionPreference = "Stop"

function Get-RailwayVar($service, $name) {
    try {
        $json = railway variables --service $service --json 2>$null | ConvertFrom-Json
        return $json.$name
    } catch { return $null }
}

$adminUrl = Get-RailwayVar "postgres-admin" "DATABASE_URL"
if (-not $adminUrl) { $adminUrl = Get-RailwayVar "Postgres" "DATABASE_URL" }
$kfcUrl = Get-RailwayVar "postgres-kfc" "DATABASE_URL"
if (-not $kfcUrl) { $kfcUrl = Get-RailwayVar "Postgres-3p8I" "DATABASE_URL" }
$kababUrl = Get-RailwayVar "postgres-kababjees" "DATABASE_URL"
if (-not $kababUrl) { $kababUrl = Get-RailwayVar "Postgres-A4-B" "DATABASE_URL" }
$adminPublic = Get-RailwayVar "postgres-admin" "DATABASE_PUBLIC_URL"
if (-not $adminPublic) { $adminPublic = Get-RailwayVar "Postgres" "DATABASE_PUBLIC_URL" }
$kfcPublic = Get-RailwayVar "postgres-kfc" "DATABASE_PUBLIC_URL"
if (-not $kfcPublic) { $kfcPublic = Get-RailwayVar "Postgres-3p8I" "DATABASE_PUBLIC_URL" }
$kababPublic = Get-RailwayVar "postgres-kababjees" "DATABASE_PUBLIC_URL"
if (-not $kababPublic) { $kababPublic = Get-RailwayVar "Postgres-A4-B" "DATABASE_PUBLIC_URL" }

$missing = @()
if (-not $adminUrl) { $missing += "postgres-admin" }
if (-not $kfcUrl) { $missing += "postgres-kfc" }
if (-not $kababUrl) { $missing += "postgres-kababjees" }

if ($missing.Count -gt 0) {
    Write-Host "MISSING Railway services: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "Follow RAILWAY_DB_RESET.md steps 1-2 in the Railway dashboard first."
    exit 1
}

Write-Host "Configuring agent service..." -ForegroundColor Cyan
railway variables set `
    SERVICE_MODE=agent `
    DATABASE_URL_CENTRAL="$adminUrl" `
    DATABASE_URL_KFC="$kfcUrl" `
    DATABASE_URL_KABABJEES="$kababUrl" `
    TENANT_DB_ADMIN_URL="$($adminUrl -replace 'postgresql\+asyncpg://','postgresql://')" `
    --service "Restaurant-Watsapp-Ai-Automation"

# Parse host from admin URL for tenant provisioning
if ($adminUrl -match '@([^:/]+)') {
    railway variables set TENANT_DB_HOST="$($Matches[1])" --service "Restaurant-Watsapp-Ai-Automation"
}

Write-Host "Redeploying agent..." -ForegroundColor Cyan
railway up --detach --service "Restaurant-Watsapp-Ai-Automation"

Write-Host ""
Write-Host "Done. Agent wired to:" -ForegroundColor Green
Write-Host "  postgres-admin     (central)"
Write-Host "  postgres-kfc       (KFC tenant)"
Write-Host "  postgres-kababjees (Kababjees tenant)"
Write-Host ""
Write-Host "Next: powershell -File scripts/fetch_local_env.ps1" -ForegroundColor Cyan
Write-Host "       powershell -File scripts/run_all_local.ps1" -ForegroundColor Cyan
