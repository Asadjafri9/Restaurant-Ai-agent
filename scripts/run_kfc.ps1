$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$envFile = Join-Path $root "local\kfc.env"
if (-not (Test-Path $envFile)) { Write-Host "Missing local/kfc.env - run fetch_local_env.ps1"; exit 1 }
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $p = $_ -split '=', 2
    Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim()
}
$env:PYTHONPATH = $root
$env:TENANT_DATABASE_URL = $env:DATABASE_URL
Write-Host "[kfc] migrations..." -ForegroundColor Cyan
python -m alembic -c migrations/tenant/alembic.ini upgrade head
python scripts/seed_tenant.py
Write-Host "[kfc] http://localhost:8002" -ForegroundColor Green
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload --reload-dir app
