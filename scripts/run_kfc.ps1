$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$envFile = Join-Path $root "local\kfc.env"
if (-not (Test-Path $envFile)) { Write-Host "Missing local/kfc.env - run fetch_local_env.ps1"; exit 1 }

# Free port 8002 from stale processes before starting (Windows may keep ghost sockets)
& "$PSScriptRoot\kill_port.ps1" -Port 8002
& "$PSScriptRoot\kill_port.ps1" -Port 8012

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
foreach ($candidate in @(8002, 8012, 8022, 8032)) {
    if (Test-PortFree $candidate) {
        $port = $candidate
        break
    }
}
if (-not $port) {
    Write-Host "Ports 8002/8012/8022/8032 blocked (Windows ghost sockets). Reboot PC to clear them." -ForegroundColor Red
    exit 1
}
if ($port -ne 8002) {
    Write-Host "Port 8002 unavailable - KFC portal will use $port" -ForegroundColor Yellow
    Write-Host "After reboot you can use 8002 again." -ForegroundColor Yellow
}
Write-Host "KFC portal: http://localhost:$port" -ForegroundColor Green
# Bind IPv6 dual-stack (::) so the browser's IPv6-first resolution of
# "localhost" (::1) connects instantly instead of stalling ~2s before
# falling back to IPv4. Dual-stack also accepts IPv4 (127.0.0.1).
python -m uvicorn app.main:app --host :: --port $port --reload --reload-dir app
