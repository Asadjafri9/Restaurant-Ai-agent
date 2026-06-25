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
Write-Host "kfc migrations..." -ForegroundColor Cyan
python -m alembic -c migrations/tenant/alembic.ini upgrade head
python scripts/seed_tenant.py

function Test-PortFree($port) {
    python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',$port)); s.close()" 2>$null
    return $LASTEXITCODE -eq 0
}

$port = $null
foreach ($candidate in 8002, 8012, 8004, 8022) {
    if (Test-PortFree $candidate) { $port = $candidate; break }
}
if (-not $port) {
    Write-Host "No free port for KFC (tried 8002, 8012, 8004, 8022)" -ForegroundColor Red
    exit 1
}
if ($port -ne 8002) {
    Write-Host "Port 8002 blocked by stale socket - using $port" -ForegroundColor Yellow
    Write-Host "Open http://localhost:$port (reboot PC to free port 8002)" -ForegroundColor Yellow
}
Write-Host "KFC portal: http://localhost:$port" -ForegroundColor Green
python -m uvicorn app.main:app --host 127.0.0.1 --port $port --reload --reload-dir app
