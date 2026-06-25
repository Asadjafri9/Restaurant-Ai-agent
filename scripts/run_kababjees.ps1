$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$envFile = Join-Path $root "local\kababjees.env"
if (-not (Test-Path $envFile)) {
    Write-Host "Missing local/kababjees.env" -ForegroundColor Red
    Write-Host "1. Railway dashboard: delete 'worker' service (free a slot)"
    Write-Host "2. + Add -> Database -> Postgres, name it postgres-kababjees"
    Write-Host "3. Re-run: scripts/fetch_local_env.ps1"
    exit 1
}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $p = $_ -split '=', 2
    Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim()
}
$env:PYTHONPATH = $root
$env:TENANT_DATABASE_URL = $env:DATABASE_URL
Write-Host "[kababjees] migrations..." -ForegroundColor Cyan
python -m alembic -c migrations/tenant/alembic.ini upgrade head
python scripts/seed_tenant.py
Write-Host "[kababjees] http://localhost:8003" -ForegroundColor Green
python -m uvicorn app.main:app --host 127.0.0.1 --port 8003 --reload --reload-dir app
