# Start all 3 local portals (admin :8001, kfc :8002, kababjees :8003)
# Prerequisites: pip install -r requirements.txt && scripts/fetch_local_env.ps1

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (-not (Test-Path "local\admin.env")) {
    Write-Host "Run scripts/fetch_local_env.ps1 first" -ForegroundColor Red
    exit 1
}

Write-Host "Starting local portals..." -ForegroundColor Cyan
Write-Host "  Admin:      http://localhost:8001"
Write-Host "  KFC:        http://localhost:8002"
Write-Host "  Kababjees:  http://localhost:8003"
Write-Host "  Agent API:  https://restaurant-watsapp-ai-automation-production.up.railway.app"
Write-Host ""

Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$PSScriptRoot\run_admin.ps1"
Start-Sleep 2
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$PSScriptRoot\run_kfc.ps1"
Start-Sleep 2
if (Test-Path "local\kababjees.env") {
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$PSScriptRoot\run_kababjees.ps1"
} else {
    Write-Host "Skipping kababjees (no local/kababjees.env - add 3rd Postgres on Railway)" -ForegroundColor Yellow
}
