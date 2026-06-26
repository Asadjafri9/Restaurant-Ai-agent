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
& "$PSScriptRoot\kill_port.ps1" -Port 8003
& "$PSScriptRoot\kill_port.ps1" -Port 8033
Write-Host "kababjees migrations..." -ForegroundColor Cyan
python -m alembic -c migrations/tenant/alembic.ini upgrade head
python scripts/seed_tenant.py

function Test-PortFree($port) {
    python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',$port)); s.close()" 2>$null
    return $LASTEXITCODE -eq 0
}

$port = $null
foreach ($candidate in @(8003, 8033, 8043)) {
    if (Test-PortFree $candidate) {
        $port = $candidate
        break
    }
}
if (-not $port) {
    Write-Host "Ports 8003/8033/8043 blocked. Reboot PC to clear ghost sockets." -ForegroundColor Red
    exit 1
}
if ($port -ne 8003) {
    Write-Host "Port 8003 unavailable - Kababjees portal will use $port" -ForegroundColor Yellow
}
Write-Host "[kababjees] http://localhost:$port" -ForegroundColor Green
# Bind IPv6 dual-stack (::) so the browser's IPv6-first resolution of
# "localhost" (::1) connects instantly instead of stalling ~2s before
# falling back to IPv4. Dual-stack also accepts IPv4 (127.0.0.1).
python -m uvicorn app.main:app --host :: --port $port --reload --reload-dir app
